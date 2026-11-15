"""培养实验（细胞实验日程）服务。

一个培养实验 = 实验名 + 备注（细胞与处理条件）+ 一组检查时间点。
时间点按固定间隔从「首次检查时间」往后推：间隔可以是小时（24h、48h）或天（2d、3d），
后续还可以换成自定义间隔（如 12h、1.5d），甚至可以指定某一轮的具体时间。

每个时间点是一条「检查点」：
- 到点后出现在首页卡片、提醒铃和实验页的待处理列表里；
- 检查完打勾（可选填细胞状况与观察记录），日程自动推进到下一个时间点；
- 若实验还没结束，推进时自动补出后续检查点。

时间一律按服务器本地时间（北京时间）存储为「YYYY-MM-DD HH:MM」。
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any, Sequence

from ..domain import STATUS_CHOICES, normalize_text
from ..errors import Conflict, NotFound, ValidationError
from . import audit, fetch_all, fetch_one, placeholders

# --------------------------------------------------------------------------
# 常量
# --------------------------------------------------------------------------
INTERVAL_UNITS = {"h": "小时", "d": "天", "m": "分钟"}
EXPERIMENT_STATUSES = {"active": "进行中", "paused": "已暂停", "done": "已完成", "aborted": "已终止"}
CHECK_KINDS = {
    "schedule": "计划检查",
    "manual": "手动加点",
    "custom": "自定义间隔",
    "followup": "补检查",
}
CHECK_KIND_DEFAULT = "schedule"

DEFAULT_INTERVAL_VALUE = 24
DEFAULT_INTERVAL_UNIT = "h"
MIN_INTERVAL_MINUTES = 15
MAX_INTERVAL_MINUTES = 60 * 24 * 90
# 自动补点最多往后铺这么多天，避免「间隔 15 分钟」把表铺爆
HORIZON_DAYS = 120
# 自动补点时顺带把下一个时间点也建出来，方便提前看到下一次安排
LOOKAHEAD = 1
# 已完成实验仍保留的未来时间点数量
DONE_KEEP_FUTURE = 0

# 提前提醒窗口：1 天内到点显示「今天」，3 天内显示「明天 / X 天后」
WINDOW_DAYS = 3

STATUS_PRIORITY = {"overdue": 0, "due": 1, "upcoming": 2}

_TIME_FORMATS = ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# 时间工具
# --------------------------------------------------------------------------
def _now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def fmt_dt(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M")


def parse_dt(value: Any, field: str = "时间") -> datetime:
    """解析时间：接受 'YYYY-MM-DD HH:MM'、ISO 格式、只给日期（取当前时刻）或 epoch 毫秒。"""
    if isinstance(value, datetime):
        return value.replace(second=0, microsecond=0)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        # 前端日期选择器直接传时间戳（毫秒）
        seconds = float(value) / 1000 if abs(float(value)) > 1e11 else float(value)
        return datetime.fromtimestamp(seconds).replace(second=0, microsecond=0)
    text = "" if value is None else str(value).strip()
    if not text:
        raise ValidationError(f"{field}不能为空")
    # 先走 ISO 解析（兼容 'YYYY-MM-DDTHH:MM:SS' 和 'YYYY-MM-DD HH:MM'），再退回固定格式
    try:
        return datetime.fromisoformat(text).replace(second=0, microsecond=0)
    except ValueError:
        pass
    for fmt in _TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).replace(second=0, microsecond=0)
        except ValueError:
            continue
    if len(text) == 10:  # 只给日期：沿用当前时刻
        try:
            day = datetime.strptime(text, "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError(f"{field}格式无法识别：{text}") from exc
        return datetime.combine(day, _now().time())
    raise ValidationError(f"{field}格式无法识别：{text}（应为 YYYY-MM-DD HH:MM）")


def interval_minutes(value: Any, unit: Any, field: str = "间隔") -> int:
    if unit not in ("h", "d", "m"):
        raise ValidationError(f"{field}单位必须是 h（小时）/ d（天）/ m（分钟）")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"{field}必须是数字") from exc
    factor = {"h": 60, "d": 1440, "m": 1}[unit]
    minutes = number * factor
    if abs(minutes - round(minutes)) > 1e-6:
        raise ValidationError(f"{field}最多精确到分钟")
    minutes = int(round(minutes))
    if minutes < MIN_INTERVAL_MINUTES:
        raise ValidationError(f"{field}不能小于 {MIN_INTERVAL_MINUTES} 分钟")
    if minutes > MAX_INTERVAL_MINUTES:
        raise ValidationError(f"{field}不能超过 90 天")
    return minutes


def interval_text(value: int | None, unit: str | None) -> str:
    """间隔文案：24h → 「24h（1d · 每 24 小时）」；2d → 「2d（每 2 天）」；90m → 「90m（每 90 分钟）」。"""
    if not value:
        return "未设置"
    if unit == "d":
        return f"{value:g}d（每 {value:g} 天）"
    if unit == "m":
        return f"{value:g}m（每 {value:g} 分钟）"
    if value % 24 == 0 and value >= 24:
        return f"{value:g}h（{value // 24:g}d · 每 {value:g} 小时）"
    return f"{value:g}h（每 {value:g} 小时）"


def human_gap(due: datetime, now: datetime, interval_unit: str | None = None) -> str:
    """把时间差写成人话：逾期 3 小时 / 还有 25 分钟 / 还有 9 天。

    - 按天计算的实验（interval_unit='d'）：超过 1 天时按「日历天数」算，
      11-14 到 11-23 始终是 9 天，不会因为当天过了 22:00 就变成 8 天。
    - 按小时计算的实验（interval_unit='h'）：始终显示小时数（如「还有 56 小时」），
      与用户自己按小时记录的习惯一致。
    """
    seconds = (due - now).total_seconds()
    overdue = seconds < 0
    seconds = abs(seconds)
    minutes = int(seconds // 60)

    prefix = "逾期" if overdue else "还有"

    # 按小时计算的实验：用小时数表达；超过 72 小时时补一个天数，避免「还有 240 小时」
    if interval_unit == "h":
        if minutes < 60:
            return f"{prefix} {minutes} 分钟"
        hours = round(minutes / 60)
        if hours >= 72:
            return f"{prefix} {hours} 小时（{hours // 24} 天）"
        return f"{prefix} {hours} 小时"

    # 日历天数：逾期时 due 在前，未逾期时 now 在前
    earlier, later = (due, now) if overdue else (now, due)
    day_diff = (later.date() - earlier.date()).days

    if day_diff >= 1:
        text = f"{day_diff} 天"
    elif minutes < 60:
        text = f"{minutes} 分钟"
    else:
        text = f"{round(minutes / 60)} 小时"
    return f"{prefix} {text}"


def span_text(minutes: int | None) -> str:
    """把一段时长写成「2 天 6 小时」/「18 小时」/「45 分钟」。"""
    if minutes is None:
        return ""
    minutes = int(round(minutes))
    if minutes < 0:
        minutes = 0
    if minutes < 60:
        return f"{minutes} 分钟"
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    parts: list[str] = []
    if days:
        parts.append(f"{days} 天")
    if hours:
        parts.append(f"{hours} 小时")
    if mins and not days:
        parts.append(f"{mins} 分钟")
    return " ".join(parts) if parts else "0 分钟"


def rel_day_label(due_date: date, today: date) -> str:
    delta = (due_date - today).days
    if delta == 0:
        return "今天"
    if delta == 1:
        return "明天"
    if delta == 2:
        return "后天"
    if delta == -1:
        return "昨天"
    if delta < 0:
        return f"{-delta} 天前"
    if delta <= 6:
        return f"{delta} 天后"
    return due_date.strftime("%m-%d")


_WEEKDAYS = "一二三四五六日"


def weekday_label(day: date) -> str:
    return f"周{_WEEKDAYS[day.weekday()]}"


def due_label(due: datetime, now: datetime) -> str:
    """提醒里直接显示「哪一天几点」：今天 09:00 / 明天 10:30 / 11-18 周三 14:00。"""
    day = due.date()
    if day == now.date():
        return f"今天 {due:%H:%M}"
    if day == now.date() + timedelta(days=1):
        return f"明天 {due:%H:%M}"
    if day == now.date() - timedelta(days=1):
        return f"昨天 {due:%H:%M}"
    if due.year == now.year:
        return f"{due:%m-%d} {weekday_label(day)} {due:%H:%M}"
    return f"{due:%Y-%m-%d} {weekday_label(day)} {due:%H:%M}"


def _due_state(due: datetime, now: datetime, done: bool = False) -> str:
    if done:
        return "done"
    if due < now:
        return "overdue"
    if due - now <= timedelta(hours=24):
        return "due"
    if due - now <= timedelta(days=WINDOW_DAYS):
        return "upcoming"
    return "scheduled"


_STATE_LABELS = {
    "overdue": "已逾期",
    "due": "待检查",
    "upcoming": "即将到点",
    "scheduled": "计划中",
    "done": "已完成",
}


# --------------------------------------------------------------------------
# 读取
# --------------------------------------------------------------------------
def _experiment_row(conn: sqlite3.Connection, experiment_id: int) -> dict[str, Any]:
    row = fetch_one(
        conn,
        """
        SELECT e.*, cl.name AS cell_line_name,
               (SELECT COUNT(*) FROM experiment_checkpoints c
                 WHERE c.experiment_id = e.id AND c.done = 0) AS pending_count,
               (SELECT MIN(c.due_at) FROM experiment_checkpoints c
                 WHERE c.experiment_id = e.id AND c.done = 0) AS next_due_at,
               (SELECT MIN(c.due_date) FROM experiment_checkpoints c
                 WHERE c.experiment_id = e.id AND c.done = 0) AS next_due_date,
               (SELECT COUNT(*) FROM experiment_checkpoints c
                 WHERE c.experiment_id = e.id AND c.done = 1) AS done_count,
               (SELECT COUNT(*) FROM experiment_checkpoints c
                 WHERE c.experiment_id = e.id) AS checkpoint_count
        FROM culture_experiments e
        LEFT JOIN cell_lines cl ON cl.id = e.cell_line_id
        WHERE e.id = ?
        """,
        (experiment_id,),
    )
    if row is None:
        raise NotFound(f"培养实验不存在（id={experiment_id}）")
    return row


def _checkpoint_row(conn: sqlite3.Connection, checkpoint_id: int) -> dict[str, Any]:
    row = fetch_one(conn, "SELECT * FROM experiment_checkpoints WHERE id = ?", (checkpoint_id,))
    if row is None:
        raise NotFound(f"检查点不存在（id={checkpoint_id}）")
    return row


def _experiment_lines(conn: sqlite3.Connection, experiment_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    """实验 id → 关联细胞株列表。"""
    if not experiment_ids:
        return {}
    rows = fetch_all(
        conn,
        f"SELECT el.experiment_id, el.cell_line_id, el.sort_order, cl.name, cl.species, cl.type "
        f"FROM experiment_lines el JOIN cell_lines cl ON cl.id = el.cell_line_id "
        f"WHERE el.experiment_id IN ({placeholders(experiment_ids)}) "
        f"ORDER BY el.experiment_id, el.sort_order, cl.name",
        tuple(experiment_ids),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["experiment_id"]), []).append({
            "cell_line_id": int(row["cell_line_id"]),
            "name": row["name"],
            "species": row["species"],
            "type": row["type"],
        })
    return grouped


def _experiment_groups(conn: sqlite3.Connection, experiment_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    if not experiment_ids:
        return {}
    rows = fetch_all(
        conn,
        f"SELECT eg.experiment_id, eg.group_id, g.group_name "
        f"FROM experiment_groups eg JOIN cell_groups g ON g.id = eg.group_id "
        f"WHERE eg.experiment_id IN ({placeholders(experiment_ids)}) "
        f"ORDER BY eg.experiment_id, g.group_name",
        tuple(experiment_ids),
    )
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["experiment_id"]), []).append({
            "group_id": int(row["group_id"]),
            "group_name": row["group_name"],
        })
    return grouped


def _attach_relations(conn: sqlite3.Connection, experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """给实验列表补上关联细胞株/细胞组，并生成一句摘要文案。"""
    ids = [int(item["id"]) for item in experiments]
    line_map = _experiment_lines(conn, ids)
    group_map = _experiment_groups(conn, ids)
    for item in experiments:
        exp_id = int(item["id"])
        cells = line_map.get(exp_id, [])
        groups = group_map.get(exp_id, [])
        # 兼容单细胞株的老数据：cell_line_id 有值但关联表为空时补一条
        if not cells and item.get("cell_line_name"):
            cells = [{
                "cell_line_id": int(item["cell_line_id"]),
                "name": item["cell_line_name"],
                "species": None,
                "type": None,
            }]
        item["cell_lines"] = cells
        item["groups"] = groups
        item["cell_line_ids"] = [cell["cell_line_id"] for cell in cells]
        item["group_ids"] = [group["group_id"] for group in groups]
        item["cell_line_names"] = [cell["name"] for cell in cells]
        item["cell_line_name"] = "、".join(cell["name"] for cell in cells) or None
        item["cell_line_count"] = len(cells)
    return experiments


def experiments_for_cell_lines(conn: sqlite3.Connection, line_ids: Sequence[int],
                               *, now: datetime | None = None) -> dict[int, list[dict[str, Any]]]:
    """细胞株 id → 该细胞株正在进行中的实验（用于在养细胞页的批次卡片）。"""
    if not line_ids:
        return {}
    rows = fetch_all(
        conn,
        f"SELECT e.id, e.name, e.status, e.interval_unit, el.cell_line_id "
        f"FROM experiment_lines el JOIN culture_experiments e ON e.id = el.experiment_id "
        f"WHERE el.cell_line_id IN ({placeholders(line_ids)}) "
        f"AND e.status IN ('active', 'paused') ORDER BY e.id",
        tuple(line_ids),
    )
    if not rows:
        return {}
    ids = sorted({int(row["id"]) for row in rows})
    unit_by_exp = {int(row["id"]): row.get("interval_unit") for row in rows}
    now = now or _now()
    checks = fetch_all(
        conn,
        f"SELECT * FROM experiment_checkpoints WHERE experiment_id IN ({placeholders(ids)}) "
        "ORDER BY experiment_id, seq, id",
        tuple(ids),
    )
    next_by_exp: dict[int, dict[str, Any] | None] = {}
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in checks:
        grouped.setdefault(int(item["experiment_id"]), []).append(item)
    for exp_id in ids:
        pending = [cp for cp in grouped.get(exp_id, []) if not cp["done"]]
        next_by_exp[exp_id] = (
            decorate_checkpoint(pending[0], now, unit_by_exp.get(exp_id)) if pending else None
        )

    mapping: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        line_id = int(row["cell_line_id"])
        nxt = next_by_exp.get(int(row["id"]))
        mapping.setdefault(line_id, []).append({
            "experiment_id": int(row["id"]),
            "name": row["name"],
            "status": row["status"],
            "next_due_label": nxt["due_label"] if nxt else None,
            "next_state": nxt["state"] if nxt else None,
            "gap_text": nxt["gap_text"] if nxt else None,
        })
    return mapping


def _checkpoints(conn: sqlite3.Connection, experiment_id: int, *, limit: int | None = None) -> list[dict[str, Any]]:
    sql = (
        "SELECT * FROM experiment_checkpoints WHERE experiment_id = ? "
        "ORDER BY seq ASC, id ASC"
    )
    params: tuple[Any, ...] = (experiment_id,)
    if limit:
        sql += " LIMIT ?"
        params += (limit,)
    return fetch_all(conn, sql, params)


def actual_span_text(minutes: int | None, unit: str | None = None,
                     manual: bool = False) -> str:
    """实际间隔的显示文字。

    规则很简单：能凑成整天的就用天（如 24h → 1 天、48h → 2 天），
    凑不成整天的就用小时（如 30h → 30 小时），保留精确时间点。
    """
    if minutes is None:
        return ""
    minutes = int(round(minutes))
    if minutes < 0:
        minutes = 0

    # 正好是整天：显示天数
    if minutes >= 1440 and minutes % 1440 == 0:
        return f"{minutes // 1440} 天"

    # 其余一律用小时，不足 1 小时用分钟
    if minutes < 60:
        return f"{minutes} 分钟"
    return f"{round(minutes / 60)} 小时"


def annotate_actual_spans(checkpoints: list[dict[str, Any]], experiment: dict[str, Any]) -> None:
    """给已完成的检查点补上「实际间隔」。

    基准是上一次实际检查（done_at），第一次检查则以实验开始时间为基准。
    只记录「距离上一次处理过了多久」，不再计算与计划时间的偏差。
    """
    started = None
    if experiment.get("started_at"):
        try:
            started = parse_dt(experiment["started_at"])
        except ValidationError:
            started = None

    prev_done: datetime | None = None
    for item in checkpoints:
        item["actual_span_minutes"] = None
        item["actual_span_text"] = ""
        item["actual_from"] = None
        if not item.get("done") or not item.get("done_at"):
            continue
        try:
            done_at = parse_dt(item["done_at"])
        except ValidationError:
            continue
        # 基准：上一次实际检查；没有则用实验开始时间
        if prev_done is not None:
            base, base_label = prev_done, "上次检查"
        elif started is not None:
            base, base_label = started, "实验开始"
        else:
            base, base_label = None, None
        if base is not None:
            minutes = int(round((done_at - base).total_seconds() / 60))
            item["actual_span_minutes"] = minutes
            item["actual_span_text"] = actual_span_text(minutes)
            item["actual_from"] = base_label
        prev_done = done_at


def decorate_checkpoint(checkpoint: dict[str, Any], now: datetime,
                        interval_unit: str | None = None) -> dict[str, Any]:
    due = parse_dt(checkpoint["due_at"])
    done = bool(checkpoint.get("done"))
    state = _due_state(due, now, done)
    item = dict(checkpoint)
    item["done"] = done
    item["state"] = state
    item["state_label"] = _STATE_LABELS[state]
    item["due_label"] = due_label(due, now)
    item["rel_day"] = rel_day_label(due.date(), now.date())
    item["weekday"] = weekday_label(due.date())
    item["gap_text"] = human_gap(due, now, interval_unit)
    item["kind_label"] = CHECK_KINDS.get(checkpoint.get("kind") or "", "检查")
    return item


def next_pending(checkpoints: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    pending = [item for item in checkpoints if not item.get("done")]
    return pending[0] if pending else None


def _summarize(experiment: dict[str, Any], checkpoints: Sequence[dict[str, Any]],
               now: datetime) -> dict[str, Any]:
    unit = experiment.get("interval_unit")
    decorated = [decorate_checkpoint(item, now, unit) for item in checkpoints]
    pending = [item for item in decorated if not item["done"]]
    done = [item for item in decorated if item["done"]]
    nxt = next_pending(decorated)
    overdue = [item for item in pending if item["state"] == "overdue"]

    summary = dict(experiment)
    summary["status_label"] = EXPERIMENT_STATUSES.get(experiment.get("status"), experiment.get("status"))
    summary["interval_text"] = interval_text(
        experiment.get("interval_value"), experiment.get("interval_unit")
    )
    summary["pending_count"] = len(pending)
    summary["done_count"] = len(done)
    summary["overdue_count"] = len(overdue)
    summary["checkpoint_count"] = len(decorated)
    summary["next_checkpoint"] = nxt
    summary["last_done"] = done[-1] if done else None
    summary["state"] = nxt["state"] if nxt else ("done" if experiment.get("status") == "done" else "empty")
    summary["state_label"] = _STATE_LABELS.get(summary["state"], "无待办")
    if nxt and experiment.get("status") in ("active", "paused"):
        summary["sort_key"] = (STATUS_PRIORITY.get(nxt["state"], 3), nxt["due_at"])
    else:
        summary["sort_key"] = (9 if experiment.get("status") in ("done", "aborted") else 4,
                               nxt["due_at"] if nxt else "")
    summary["priority"] = summary["sort_key"][0]
    return summary


def get_experiment(conn: sqlite3.Connection, experiment_id: int,
                   now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    row = _experiment_row(conn, experiment_id)
    checkpoints = _checkpoints(conn, experiment_id)
    summary = _summarize(row, checkpoints, now)
    summary["checkpoints"] = [
        decorate_checkpoint(item, now, row.get("interval_unit")) for item in checkpoints
    ]
    # 实际间隔 / 提前延后，供详情页展示
    annotate_actual_spans(summary["checkpoints"], summary)
    return _attach_relations(conn, [summary])[0]


def list_experiments(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    q: str | None = None,
    scope: str | None = None,
    now: datetime | None = None,
    with_checkpoints: int = 0,
) -> list[dict[str, Any]]:
    """scope: all / active / attention（逾期或今日到点） / today（今日有安排）。"""
    now = now or _now()
    clauses: list[str] = []
    params: list[Any] = []
    if status in EXPERIMENT_STATUSES:
        clauses.append("e.status = ?")
        params.append(status)
    elif scope in ("active", "attention", "today", "overdue"):
        clauses.append("e.status IN ('active', 'paused')")
    if q:
        # 搜索也覆盖关联细胞株/细胞组的名字
        keyword = f"%{q.strip()}%"
        clauses.append(
            "(e.name LIKE ? OR IFNULL(e.notes, '') LIKE ? OR IFNULL(e.extra_notes, '') LIKE ? "
            "OR EXISTS (SELECT 1 FROM experiment_lines el JOIN cell_lines l ON l.id = el.cell_line_id "
            "           WHERE el.experiment_id = e.id AND l.name LIKE ?) "
            "OR EXISTS (SELECT 1 FROM experiment_groups eg JOIN cell_groups g ON g.id = eg.group_id "
            "           WHERE eg.experiment_id = e.id AND g.group_name LIKE ?))"
        )
        params.extend([keyword] * 5)

    sql = (
        "SELECT e.*, cl.name AS cell_line_name FROM culture_experiments e "
        "LEFT JOIN cell_lines cl ON cl.id = e.cell_line_id "
    )
    if clauses:
        sql += "WHERE " + " AND ".join(clauses) + " "
    sql += "ORDER BY e.id DESC"
    rows = fetch_all(conn, sql, tuple(params))

    if rows:
        ids = [int(row["id"]) for row in rows]
        all_checks = fetch_all(
            conn,
            f"SELECT * FROM experiment_checkpoints WHERE experiment_id IN ({placeholders(ids)}) "
            "ORDER BY experiment_id, seq, id",
            tuple(ids),
        )
    else:
        all_checks = []
    grouped: dict[int, list[dict[str, Any]]] = {}
    for item in all_checks:
        grouped.setdefault(int(item["experiment_id"]), []).append(item)

    summaries = [_summarize(row, grouped.get(int(row["id"]), []), now) for row in rows]

    if scope == "attention":
        summaries = [
            item for item in summaries
            if item["next_checkpoint"] and item["state"] in ("overdue", "due")
        ]
    elif scope == "overdue":
        summaries = [item for item in summaries if item["state"] == "overdue"]
    elif scope == "today":
        today = now.date().isoformat()
        summaries = [
            item for item in summaries
            if any(cp["due_date"] == today and not cp["done"] for cp in grouped.get(int(item["id"]), []))
        ]

    summaries.sort(key=lambda item: (item["sort_key"], -int(item["id"])))
    summaries = _attach_relations(conn, summaries)
    if with_checkpoints:
        for item in summaries:
            checks = grouped.get(int(item["id"]), [])
            item["checkpoints"] = [
                decorate_checkpoint(cp, now, item.get("interval_unit"))
                for cp in checks[:with_checkpoints]
            ]
            item["checkpoints_total"] = len(checks)
    return [_strip_internal(item) for item in summaries]


def _strip_internal(item: dict[str, Any]) -> dict[str, Any]:
    item.pop("sort_key", None)
    return item


# --------------------------------------------------------------------------
# 日程推进
# --------------------------------------------------------------------------
def interval_to_minutes(value: Any, unit: Any) -> int:
    """(数值, 单位) → 分钟。单位接受 h / d / m。"""
    unit = unit if unit in ("h", "d", "m") else DEFAULT_INTERVAL_UNIT
    return interval_minutes(value, unit)


def stored_interval(payload: dict[str, Any], prefix: str = "") -> tuple[int, str]:
    """界面提交的间隔 → 落库写法：整小时存 h，整 24 小时优先存 d，带零头存 m。"""
    raw_value = payload.get(f"{prefix}interval_value", payload.get("interval_value", DEFAULT_INTERVAL_VALUE))
    raw_unit = payload.get(f"{prefix}interval_unit", payload.get("interval_unit", DEFAULT_INTERVAL_UNIT))
    if raw_unit not in INTERVAL_UNITS:
        raise ValidationError("间隔单位必须是 h（小时）/ d（天）/ m（分钟）")
    minutes = interval_to_minutes(raw_value, raw_unit)
    if minutes % 1440 == 0:
        return minutes // 1440, "d"
    if minutes % 60 == 0:
        return minutes // 60, "h"
    return minutes, "m"


def _current_interval_minutes(conn: sqlite3.Connection, experiment: dict[str, Any]) -> int:
    """当前生效间隔（分钟）：最近一次「自定义间隔」加点的设置优先，否则用实验默认间隔。"""
    row = conn.execute(
        "SELECT interval_value, interval_unit FROM experiment_checkpoints "
        "WHERE experiment_id = ? AND interval_value IS NOT NULL AND interval_unit IS NOT NULL "
        "ORDER BY seq DESC, id DESC LIMIT 1",
        (experiment["id"],),
    ).fetchone()
    if row and row["interval_value"]:
        return interval_to_minutes(row["interval_value"], row["interval_unit"])
    return interval_to_minutes(
        experiment.get("interval_value") or DEFAULT_INTERVAL_VALUE,
        experiment.get("interval_unit") or DEFAULT_INTERVAL_UNIT,
    )


def _latest_checkpoint(conn: sqlite3.Connection, experiment_id: int) -> dict[str, Any] | None:
    return fetch_one(
        conn,
        "SELECT * FROM experiment_checkpoints WHERE experiment_id = ? ORDER BY seq DESC, id DESC LIMIT 1",
        (experiment_id,),
    )


def _next_seq(conn: sqlite3.Connection, experiment_id: int) -> int:
    row = conn.execute(
        "SELECT MAX(seq) FROM experiment_checkpoints WHERE experiment_id = ?", (experiment_id,)
    ).fetchone()
    return int(row[0] or 0) + 1


def _insert_checkpoint(
    conn: sqlite3.Connection,
    experiment_id: int,
    due: datetime,
    *,
    kind: str = CHECK_KIND_DEFAULT,
    interval_value: int | None = None,
    interval_unit: str | None = None,
    notes: str = "",
) -> int:
    seq = _next_seq(conn, experiment_id)
    cursor = conn.execute(
        "INSERT INTO experiment_checkpoints "
        "(experiment_id, seq, due_at, due_date, due_clock, kind, done, interval_value, interval_unit, notes) "
        "VALUES (?,?,?,?,?,?,0,?,?,?)",
        (
            experiment_id,
            seq,
            fmt_dt(due),
            due.date().isoformat(),
            due.strftime("%H:%M"),
            kind,
            interval_value,
            interval_unit,
            notes or "",
        ),
    )
    return int(cursor.lastrowid)


def ensure_schedule(conn: sqlite3.Connection, experiment_id: int, *, lookahead: int | None = None) -> int:
    """保证实验一直有「下一个检查点」，并顺带铺出后续几个。

    - 进行中：始终保留至少 1 个未完成时间点，并预铺下一个（LOOKAHEAD）
    - 已暂停：只保证「还有 1 个未完成时间点」，勾完后不再自动往后加
    - 已完成/已终止：清掉多余的未来时间点，不再提醒

    返回本次新建的检查点数量。
    """
    experiment = fetch_one(conn, "SELECT * FROM culture_experiments WHERE id = ?", (experiment_id,))
    if experiment is None:
        return 0
    status = experiment.get("status") or "active"
    created = 0

    if status in ("done", "aborted"):
        _trim_future(conn, experiment_id, keep=DONE_KEEP_FUTURE)
        return 0

    if status == "paused":
        # 暂停后不再往后推进：勾完最后一个就停住
        return 0

    target = LOOKAHEAD if lookahead is None else lookahead
    # 锚点必须是「最后一个自动排程点」，不能用最后插入的点：
    # 手动加点、补检查点都排在后面，若以它们为锚，会被当成循环起点继续往后铺。
    auto = fetch_one(
        conn,
        "SELECT * FROM experiment_checkpoints WHERE experiment_id = ? "
        "AND kind IN ('schedule', 'custom', 'followup') ORDER BY seq DESC, id DESC LIMIT 1",
        (experiment_id,),
    )
    if auto is None:
        return 0
    anchor = parse_dt(auto["due_at"])
    minutes = _current_interval_minutes(conn, experiment)
    horizon = _now() + timedelta(days=HORIZON_DAYS)

    # 锚点之后已经存在的自动点数量（手动点不算，它们不属于循环）
    auto_after = int(conn.execute(
        "SELECT COUNT(*) FROM experiment_checkpoints WHERE experiment_id = ? "
        "AND kind IN ('schedule', 'custom', 'followup') AND seq > ?",
        (experiment_id, auto["seq"]),
    ).fetchone()[0] or 0)
    # 锚点自己未完成也算 1 个待办
    pending_after = auto_after + (0 if auto["done"] else 1)

    while pending_after <= target:
        anchor = anchor + timedelta(minutes=minutes)
        if anchor > horizon:
            break
        _insert_checkpoint(conn, experiment_id, anchor, kind="schedule")
        created += 1
        pending_after += 1
    if created:
        conn.execute(
            "UPDATE culture_experiments SET updated_at = ? WHERE id = ?", (fmt_dt(_now()), experiment_id)
        )
    return created


def _trim_future(conn: sqlite3.Connection, experiment_id: int, *, keep: int) -> None:
    """实验结束后清掉多余的未来检查点（已完成/已终止的不再提醒）。"""
    pending = fetch_all(
        conn,
        "SELECT id, due_at FROM experiment_checkpoints WHERE experiment_id = ? AND done = 0 "
        "ORDER BY due_at ASC, seq ASC",
        (experiment_id,),
    )
    now_text = fmt_dt(_now())
    future = [item for item in pending if item["due_at"] > now_text]
    for item in future[keep:]:
        conn.execute("DELETE FROM experiment_checkpoints WHERE id = ?", (item["id"],))


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------
def _normalize_id_list(conn: sqlite3.Connection, values: Any, table: str, label: str) -> list[int]:
    """把界面传来的 id 数组清洗成去重后的整数列表，并校验目标记录存在。"""
    if values in (None, ""):
        return []
    if not isinstance(values, (list, tuple)):
        values = [values]
    cleaned: list[int] = []
    for value in values:
        if isinstance(value, dict):
            value = value.get("id", value.get(f"{label}_id"))
        try:
            item_id = int(value)
        except (TypeError, ValueError):
            continue
        if item_id not in cleaned:
            cleaned.append(item_id)
    if cleaned:
        found = conn.execute(
            f'SELECT id FROM "{table}" WHERE id IN ({placeholders(cleaned)})', tuple(cleaned)
        ).fetchall()
        missing = set(cleaned) - {int(row["id"]) for row in found}
        if missing:
            raise ValidationError(f"选择的{label}不存在：{sorted(missing)}")
    return cleaned


def _sync_relations(conn: sqlite3.Connection, experiment_id: int, payload: dict[str, Any]) -> None:
    """同步实验的关联细胞株与细胞组。

    - cell_line_ids：最终生效的细胞株列表（按组带入后用户可以自由增减，界面直接传最终结果）
    - group_ids：关联的细胞组（只作归类标记）
    - 兼容旧字段 cell_line_id（单个细胞株）
    """
    if "cell_line_ids" in payload or "cell_line_id" in payload:
        if "cell_line_ids" in payload:
            line_ids = _normalize_id_list(conn, payload.get("cell_line_ids"), "cell_lines", "细胞株")
        else:
            raw = payload.get("cell_line_id")
            line_ids = _normalize_id_list(conn, [raw] if raw not in (None, "", 0) else [], "cell_lines", "细胞株")
        conn.execute("DELETE FROM experiment_lines WHERE experiment_id = ?", (experiment_id,))
        for index, line_id in enumerate(line_ids, start=1):
            conn.execute(
                "INSERT INTO experiment_lines (experiment_id, cell_line_id, sort_order) VALUES (?,?,?)",
                (experiment_id, line_id, index),
            )
        # 保留旧列，方便老版本程序读取第一条细胞株
        conn.execute(
            "UPDATE culture_experiments SET cell_line_id = ? WHERE id = ?",
            (line_ids[0] if line_ids else None, experiment_id),
        )

    if "group_ids" in payload:
        group_ids = _normalize_id_list(conn, payload.get("group_ids"), "cell_groups", "细胞组")
        conn.execute("DELETE FROM experiment_groups WHERE experiment_id = ?", (experiment_id,))
        for group_id in group_ids:
            conn.execute(
                "INSERT INTO experiment_groups (experiment_id, group_id) VALUES (?,?)",
                (experiment_id, group_id),
            )


def create_experiment(conn: sqlite3.Connection, payload: dict[str, Any],
                      user: str | None = None) -> dict[str, Any]:
    name = normalize_text(payload.get("name"), max_length=120)
    if not name:
        raise ValidationError("实验名不能为空")
    notes = normalize_text(payload.get("notes"), max_length=4000)
    extra_notes = normalize_text(payload.get("extra_notes"), max_length=4000)
    interval_value, interval_unit = stored_interval(payload)
    # 用户原始选择的单位（h / d），用于实际间隔按小时还是按天显示
    # 记录的是「实验开始时间」，第一次检查时间 = 开始时间 + 间隔
    started_raw = payload.get("started_at")
    started_at = parse_dt(started_raw, "实验时间") if started_raw else _now()
    first_due = started_at + timedelta(minutes=interval_to_minutes(interval_value, interval_unit))
    now_text = fmt_dt(_now())

    cursor = conn.execute(
        "INSERT INTO culture_experiments "
        "(name, notes, started_at, interval_unit, interval_value, extra_notes, "
        " status, created_at, updated_at) VALUES (?,?,?,?,?,?,'active',?,?)",
        (name, notes, fmt_dt(started_at), interval_unit, interval_value,
         extra_notes, now_text, now_text),
    )
    experiment_id = int(cursor.lastrowid)
    _sync_relations(conn, experiment_id, payload)
    _insert_checkpoint(conn, experiment_id, first_due, kind="schedule")
    ensure_schedule(conn, experiment_id)
    audit(conn, user, "create", "experiment", experiment_id,
          {"name": name, "interval": f"{interval_value}{interval_unit}",
           "started_at": fmt_dt(started_at), "first_due_at": fmt_dt(first_due)})
    return get_experiment(conn, experiment_id)


def update_experiment(conn: sqlite3.Connection, experiment_id: int, payload: dict[str, Any],
                      user: str | None = None) -> dict[str, Any]:
    experiment = _experiment_row(conn, experiment_id)
    assignments: dict[str, Any] = {}
    interval_changed = False

    if "name" in payload:
        name = normalize_text(payload.get("name"), max_length=120)
        if not name:
            raise ValidationError("实验名不能为空")
        assignments["name"] = name
    if "notes" in payload:
        assignments["notes"] = normalize_text(payload.get("notes"), max_length=4000)
    if "extra_notes" in payload:
        assignments["extra_notes"] = normalize_text(payload.get("extra_notes"), max_length=4000)
    if "started_at" in payload and payload.get("started_at"):
        assignments["started_at"] = fmt_dt(parse_dt(payload.get("started_at"), "实验时间"))
    if "interval_value" in payload or "interval_unit" in payload:
        # 未传的字段沿用库里的值，再统一换算成落库写法
        value, unit = stored_interval({
            "interval_value": payload.get("interval_value", experiment.get("interval_value")),
            "interval_unit": payload.get("interval_unit", experiment.get("interval_unit")),
        })
        if interval_to_minutes(value, unit) != interval_to_minutes(
            experiment.get("interval_value"), experiment.get("interval_unit")
        ):
            assignments["interval_value"] = value
            assignments["interval_unit"] = unit
            interval_changed = True
    if "status" in payload:
        status = payload.get("status")
        if status not in EXPERIMENT_STATUSES:
            raise ValidationError("实验状态必须是 进行中/已暂停/已完成/已终止 之一")
        assignments["status"] = status
        if status in ("done", "aborted"):
            assignments["ended_at"] = fmt_dt(_now())
            assignments["end_reason"] = normalize_text(payload.get("end_reason"), max_length=200) or None
        else:
            assignments["ended_at"] = None
            assignments["end_reason"] = None

    if assignments:
        assignments["updated_at"] = fmt_dt(_now())
        clause = ", ".join(f"{key} = ?" for key in assignments)
        conn.execute(f"UPDATE culture_experiments SET {clause} WHERE id = ?",
                     (*assignments.values(), experiment_id))
        audit(conn, user, "update", "experiment", experiment_id, {"fields": list(assignments)})

    if "cell_line_ids" in payload or "cell_line_id" in payload or "group_ids" in payload:
        _sync_relations(conn, experiment_id, payload)

    if interval_changed:
        _reschedule_future(conn, experiment_id)
        # 只有改了间隔才需要补点；单纯改名字/备注不应该动日程
        ensure_schedule(conn, experiment_id)
    return get_experiment(conn, experiment_id)


def finish_experiment(
    conn: sqlite3.Connection,
    experiment_id: int,
    payload: dict[str, Any],
    user: str | None = None,
) -> dict[str, Any]:
    """结束实验：标记为已完成/已终止，原因由用户自填（可留空），并清掉剩余的待检查时间点。

    已勾选的检查记录全部保留，只是不再提醒。
    """
    experiment = _experiment_row(conn, experiment_id)
    status = payload.get("status") or "done"
    if status not in ("done", "aborted"):
        status = "done"
    reason = normalize_text(payload.get("end_reason"), max_length=200) or None

    now_text = fmt_dt(_now())
    conn.execute(
        "UPDATE culture_experiments SET status = ?, ended_at = ?, end_reason = ?, updated_at = ? WHERE id = ?",
        (status, now_text, reason, now_text, experiment_id),
    )
    # 清掉所有未完成的检查点（含已逾期的），避免留下永久逾期
    removed = conn.execute(
        "SELECT COUNT(*) FROM experiment_checkpoints WHERE experiment_id = ? AND done = 0",
        (experiment_id,),
    ).fetchone()[0]
    conn.execute(
        "DELETE FROM experiment_checkpoints WHERE experiment_id = ? AND done = 0", (experiment_id,)
    )
    audit(conn, user, "finish", "experiment", experiment_id,
          {"name": experiment["name"], "status": status, "reason": reason, "removed": int(removed)})
    result = get_experiment(conn, experiment_id)
    result["removed_checkpoints"] = int(removed)
    return result


def postpone_checkpoint(conn: sqlite3.Connection, experiment_id: int, checkpoint_id: int,
                        payload: dict[str, Any], user: str | None = None) -> dict[str, Any]:
    """把某个检查时间点往后推（默认 1 天）。

    days 可正可负，默认 1。只移动这一个时间点，不改实验的循环间隔。
    """
    checkpoint = _checkpoint_row(conn, checkpoint_id)
    if int(checkpoint["experiment_id"]) != experiment_id:
        raise ValidationError("该检查点不属于这个实验")
    if checkpoint["done"]:
        raise Conflict("已完成的检查不能推迟，请先撤销勾选")
    try:
        days = int(payload.get("days", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("推迟天数必须是整数") from exc
    if days == 0:
        raise ValidationError("推迟天数不能为 0")
    if abs(days) > 90:
        raise ValidationError("一次最多推迟 90 天")

    due = parse_dt(checkpoint["due_at"]) + timedelta(days=days)
    conn.execute(
        "UPDATE experiment_checkpoints SET due_at = ?, due_date = ?, due_clock = ? WHERE id = ?",
        (fmt_dt(due), due.date().isoformat(), due.strftime("%H:%M"), checkpoint_id),
    )
    conn.execute("UPDATE culture_experiments SET updated_at = ? WHERE id = ?",
                 (fmt_dt(_now()), experiment_id))
    audit(conn, user, "postpone", "experiment_check", checkpoint_id,
          {"experiment_id": experiment_id, "days": days, "new_due": fmt_dt(due)})
    result = get_experiment(conn, experiment_id)
    result["postponed_to"] = fmt_dt(due)
    return result


def _reschedule_future(conn: sqlite3.Connection, experiment_id: int) -> int:
    """改了间隔后，把「未完成的后续检查点」按新间隔重排（第一条待检查时间不动）。"""
    experiment = fetch_one(conn, "SELECT * FROM culture_experiments WHERE id = ?", (experiment_id,))
    pending = fetch_all(
        conn,
        "SELECT * FROM experiment_checkpoints WHERE experiment_id = ? AND done = 0 ORDER BY seq ASC, id ASC",
        (experiment_id,),
    )
    if not pending:
        return 0
    minutes = interval_to_minutes(experiment.get("interval_value"), experiment.get("interval_unit"))
    anchor = parse_dt(pending[0]["due_at"])
    for item in pending[1:]:
        if item.get("kind") == "manual":
            continue  # 手动加的时间点保持不动
        anchor = anchor + timedelta(minutes=minutes)
        conn.execute(
            "UPDATE experiment_checkpoints SET due_at = ?, due_date = ?, due_clock = ? WHERE id = ?",
            (fmt_dt(anchor), anchor.date().isoformat(), anchor.strftime("%H:%M"), item["id"]),
        )
    return len(pending) - 1


def delete_experiment(conn: sqlite3.Connection, experiment_id: int, user: str | None = None) -> dict[str, Any]:
    experiment = _experiment_row(conn, experiment_id)
    conn.execute("DELETE FROM experiment_checkpoints WHERE experiment_id = ?", (experiment_id,))
    conn.execute("DELETE FROM experiment_lines WHERE experiment_id = ?", (experiment_id,))
    conn.execute("DELETE FROM experiment_groups WHERE experiment_id = ?", (experiment_id,))
    conn.execute("DELETE FROM culture_experiments WHERE id = ?", (experiment_id,))
    audit(conn, user, "delete", "experiment", experiment_id, {"name": experiment["name"]})
    return {"deleted": experiment_id}


# --------------------------------------------------------------------------
# 检查点操作
# --------------------------------------------------------------------------
def complete_checkpoint(
    conn: sqlite3.Connection,
    experiment_id: int,
    payload: dict[str, Any],
    user: str | None = None,
) -> dict[str, Any]:
    """勾选检查完成：可选填细胞状况/观察记录，然后自动推进到下一个时间点。"""
    experiment = _experiment_row(conn, experiment_id)
    checkpoint_id = payload.get("checkpoint_id") or payload.get("id")
    if checkpoint_id is None:
        pending = fetch_all(
            conn,
            "SELECT * FROM experiment_checkpoints WHERE experiment_id = ? AND done = 0 "
            "ORDER BY seq ASC, id ASC LIMIT 1",
            (experiment_id,),
        )
        if not pending:
            raise ValidationError("这个实验已经没有待检查的时间点了")
        checkpoint = pending[0]
    else:
        checkpoint = _checkpoint_row(conn, int(checkpoint_id))
        if int(checkpoint["experiment_id"]) != experiment_id:
            raise ValidationError("该检查点不属于这个实验")
    if checkpoint["done"]:
        raise Conflict("这个检查点已经勾选过了")

    cell_status = normalize_text(payload.get("cell_status"), max_length=20) or None
    if cell_status and cell_status not in STATUS_CHOICES:
        raise ValidationError("细胞状况必须是 良好/一般/较差/污染 之一")
    observation = normalize_text(payload.get("observation"), max_length=2000)
    notes = normalize_text(payload.get("notes"), max_length=2000)

    # 勾选时如填了「实际检查时间」则按它计时；没填则按计划时间计（视为按时完成），
    # 这样「实际间隔」不会被勾选时的当前时刻污染
    done_time_raw = payload.get("done_at")
    if done_time_raw:
        done_time = parse_dt(done_time_raw, "检查时间")
        base = done_time
    else:
        done_time = parse_dt(checkpoint["due_at"])
        base = done_time

    conn.execute(
        "UPDATE experiment_checkpoints SET done = 1, done_at = ?, cell_status = ?, observation = ?, notes = ? "
        "WHERE id = ?",
        (fmt_dt(done_time), cell_status, observation, notes, checkpoint["id"]),
    )

    # 推进：只有勾的是「最后一个自动排程点」时，才按当前间隔补出下一个。
    # 手动加点 / 补检查点不属于循环，勾它们不应往后铺新的计划点。
    last_auto = fetch_one(
        conn,
        "SELECT * FROM experiment_checkpoints WHERE experiment_id = ? "
        "AND kind IN ('schedule', 'custom', 'followup') ORDER BY seq DESC, id DESC LIMIT 1",
        (experiment_id,),
    )
    created = 0
    if (
        last_auto
        and int(last_auto["id"]) == int(checkpoint["id"])
        and (experiment.get("status") or "active") == "active"
    ):
        minutes = _current_interval_minutes(conn, experiment)
        due = base + timedelta(minutes=minutes)
        if due <= _now() + timedelta(days=HORIZON_DAYS):
            _insert_checkpoint(conn, experiment_id, due, kind="followup")
            created += 1
    conn.execute("UPDATE culture_experiments SET updated_at = ? WHERE id = ?",
                 (fmt_dt(_now()), experiment_id))
    audit(conn, user, "complete", "experiment_check", int(checkpoint["id"]),
          {"experiment_id": experiment_id, "cell_status": cell_status})

    result = get_experiment(conn, experiment_id)
    nxt = result.get("next_checkpoint")
    result["next_due_label"] = nxt["due_label"] if nxt else None
    result["advanced"] = created > 0
    return result


def reopen_checkpoint(conn: sqlite3.Connection, experiment_id: int, checkpoint_id: int,
                      user: str | None = None) -> dict[str, Any]:
    checkpoint = _checkpoint_row(conn, checkpoint_id)
    if int(checkpoint["experiment_id"]) != experiment_id:
        raise ValidationError("该检查点不属于这个实验")
    conn.execute(
        "UPDATE experiment_checkpoints SET done = 0, done_at = NULL, cell_status = NULL, "
        "observation = NULL, notes = NULL WHERE id = ?",
        (checkpoint_id,),
    )
    audit(conn, user, "reopen", "experiment_check", checkpoint_id, {"experiment_id": experiment_id})
    return get_experiment(conn, experiment_id)


def add_checkpoint(conn: sqlite3.Connection, experiment_id: int, payload: dict[str, Any],
                   user: str | None = None) -> dict[str, Any]:
    """手动加一个检查点。

    - 不带 interval_value：只加这一个「单独的点」，不改变、也不往后铺任何自动检查点
    - 带 interval_value/interval_unit：视为从这里开始改用新间隔，才会自动补后续点
    """
    _experiment_row(conn, experiment_id)
    due_raw = payload.get("due_at") or payload.get("time")
    due = parse_dt(due_raw, "检查时间")
    kind = payload.get("kind") if payload.get("kind") in CHECK_KINDS else "manual"
    notes = normalize_text(payload.get("notes"), max_length=500)
    value = unit = None
    if payload.get("interval_value") not in (None, ""):
        value, unit = stored_interval(payload)
        kind = "custom"
    checkpoint_id = _insert_checkpoint(conn, experiment_id, due, kind=kind,
                                       interval_value=value, interval_unit=unit, notes=notes)
    # 只有「改了间隔」才需要保证后续还有自动点；单纯加一个点不要动其它安排
    if value is not None:
        ensure_schedule(conn, experiment_id)
    else:
        _trim_duplicate_auto(conn, experiment_id, after_due=due)
    audit(conn, user, "add_check", "experiment_check", checkpoint_id,
          {"experiment_id": experiment_id, "due_at": fmt_dt(due), "kind": kind})
    result = get_experiment(conn, experiment_id)
    result["created_checkpoint_id"] = checkpoint_id
    return result


def _trim_duplicate_auto(conn: sqlite3.Connection, experiment_id: int, *, after_due: datetime) -> None:
    """手动加点后，清掉与它重复的自动补点（同一时刻的 schedule 点）。

    只是避免出现「同一时间两个待办」，不会去动其它正常排程。
    """
    conn.execute(
        "DELETE FROM experiment_checkpoints WHERE experiment_id = ? AND done = 0 "
        "AND kind = 'schedule' AND due_at = ?",
        (experiment_id, fmt_dt(after_due)),
    )


def update_checkpoint(conn: sqlite3.Connection, experiment_id: int, checkpoint_id: int,
                      payload: dict[str, Any], user: str | None = None) -> dict[str, Any]:
    checkpoint = _checkpoint_row(conn, checkpoint_id)
    if int(checkpoint["experiment_id"]) != experiment_id:
        raise ValidationError("该检查点不属于这个实验")
    assignments: dict[str, Any] = {}
    if "due_at" in payload:
        due = parse_dt(payload.get("due_at"), "检查时间")
        assignments.update({
            "due_at": fmt_dt(due),
            "due_date": due.date().isoformat(),
            "due_clock": due.strftime("%H:%M"),
        })
    if "notes" in payload:
        assignments["notes"] = normalize_text(payload.get("notes"), max_length=500)
    if "cell_status" in payload:
        status = normalize_text(payload.get("cell_status"), max_length=20) or None
        if status and status not in STATUS_CHOICES:
            raise ValidationError("细胞状况必须是 良好/一般/较差/污染 之一")
        assignments["cell_status"] = status
    if "observation" in payload:
        assignments["observation"] = normalize_text(payload.get("observation"), max_length=2000)
    if "kind" in payload and payload["kind"] in CHECK_KINDS:
        assignments["kind"] = payload["kind"]
    if assignments:
        clause = ", ".join(f"{key} = ?" for key in assignments)
        conn.execute(f"UPDATE experiment_checkpoints SET {clause} WHERE id = ?",
                     (*assignments.values(), checkpoint_id))
        audit(conn, user, "update", "experiment_check", checkpoint_id, {"fields": list(assignments)})
    return get_experiment(conn, experiment_id)


def delete_checkpoint(conn: sqlite3.Connection, experiment_id: int, checkpoint_id: int,
                      user: str | None = None) -> dict[str, Any]:
    """删除一个检查时间点。

    删了就是删了，不会自动补回来（否则用户永远删不掉）。
    只有实验还在进行中、且删完后一个待办都不剩时，才补一个后续点，避免实验变成「没有待办」的死状态。
    """
    checkpoint = _checkpoint_row(conn, checkpoint_id)
    if int(checkpoint["experiment_id"]) != experiment_id:
        raise ValidationError("该检查点不属于这个实验")
    conn.execute("DELETE FROM experiment_checkpoints WHERE id = ?", (checkpoint_id,))

    experiment = _experiment_row(conn, experiment_id)
    status = experiment.get("status") or "active"
    remaining = conn.execute(
        "SELECT COUNT(*) FROM experiment_checkpoints WHERE experiment_id = ? AND done = 0",
        (experiment_id,),
    ).fetchone()[0]
    if int(remaining) == 0 and status == "active":
        # 用被删点的时间 + 当前间隔，补一个「下一个待办」，避免实验无待办
        try:
            base = parse_dt(checkpoint["due_at"])
            minutes = _current_interval_minutes(conn, experiment)
            _insert_checkpoint(conn, experiment_id, base + timedelta(minutes=minutes), kind="schedule")
        except (ValidationError, KeyError):
            pass

    audit(conn, user, "delete", "experiment_check", checkpoint_id, {"experiment_id": experiment_id})
    return get_experiment(conn, experiment_id)


# --------------------------------------------------------------------------
# 汇总：首页卡片 / 提醒铃
# --------------------------------------------------------------------------
def choices() -> dict[str, Any]:
    return {
        "cell_statuses": list(STATUS_CHOICES),
        "interval_units": [{"value": key, "label": label} for key, label in INTERVAL_UNITS.items()],
        "statuses": [{"value": key, "label": label} for key, label in EXPERIMENT_STATUSES.items()],
        "presets": [
            {"label": "12h", "interval_value": 12, "interval_unit": "h"},
            {"label": "24h", "interval_value": 24, "interval_unit": "h"},
            {"label": "48h", "interval_value": 48, "interval_unit": "h"},
            {"label": "72h", "interval_value": 72, "interval_unit": "h"},
            {"label": "1d", "interval_value": 1, "interval_unit": "d"},
            {"label": "2d", "interval_value": 2, "interval_unit": "d"},
            {"label": "3d", "interval_value": 3, "interval_unit": "d"},
        ],
        "min_interval_minutes": MIN_INTERVAL_MINUTES,
    }


def week_view(conn: sqlite3.Connection, *, start: Any = None,
              now: datetime | None = None) -> dict[str, Any]:
    """周视图：以 start（任意一天，默认本周一）为起点，返回 7 天里每天需要处理的检查点。

    包含「进行中/已暂停」实验的全部未完成检查点，以及本周内已勾选的记录（方便回看）。
    """
    now = now or _now()
    if start:
        # 任何一天都对齐到当周周一，保证「上一周/下一周」翻页步长稳定
        given = parse_dt(start, "起始日期").date()
        day0 = given - timedelta(days=given.weekday())
    else:
        day0 = now.date() - timedelta(days=now.weekday())
    days = [day0 + timedelta(days=offset) for offset in range(7)]
    start_text = f"{days[0].isoformat()} 00:00"
    end_text = f"{days[-1].isoformat()} 23:59"

    rows = fetch_all(
        conn,
        """
        SELECT c.*, e.name AS experiment_name, e.status AS experiment_status,
               e.interval_unit AS experiment_interval_unit,
               e.notes AS experiment_notes
        FROM experiment_checkpoints c
        JOIN culture_experiments e ON e.id = c.experiment_id
        WHERE c.due_date BETWEEN ? AND ?
          AND (c.done = 0 OR e.status IN ('active', 'paused', 'done', 'aborted'))
        ORDER BY c.due_at ASC, c.seq ASC
        """,
        (days[0].isoformat(), days[-1].isoformat()),
    )
    decorated = []
    for row in rows:
        item = decorate_checkpoint(row, now, row.get("experiment_interval_unit"))
        item["experiment_id"] = int(row["experiment_id"])
        decorated.append(item)

    # 关联细胞株，让日历条目能看出是哪几株细胞
    exp_ids = sorted({item["experiment_id"] for item in decorated})
    line_map = _experiment_lines(conn, exp_ids) if exp_ids else {}

    # 传代待办：活跃批次建议传代日期落在本周的
    passage_rows = fetch_all(
        conn,
        """
        SELECT cb.id AS batch_id, cb.batch_name, cb.cell_line_id,
               cl.name AS cell_line, cr.next_passage_date, cr.passage, cr.status
        FROM culture_batches cb
        JOIN cell_lines cl ON cl.id = cb.cell_line_id
        JOIN culture_records cr ON cr.id = (
            SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
            ORDER BY r.date DESC, r.id DESC LIMIT 1
        )
        WHERE cb.is_active = 1
          AND cr.next_passage_date IS NOT NULL AND cr.next_passage_date <> ''
          AND cr.next_passage_date BETWEEN ? AND ?
        ORDER BY cr.next_passage_date, cl.name
        """,
        (days[0].isoformat(), days[-1].isoformat()),
    )
    passages_by_day: dict[str, list[dict[str, Any]]] = {}
    for row in passage_rows:
        passages_by_day.setdefault(row["next_passage_date"], []).append({
            "batch_id": int(row["batch_id"]),
            "batch_name": row["batch_name"],
            "cell_line": row["cell_line"],
            "cell_line_id": int(row["cell_line_id"]),
            "passage": row["passage"],
            "status": row["status"],
            "date": row["next_passage_date"],
        })

    by_day: dict[str, list[dict[str, Any]]] = {day.isoformat(): [] for day in days}
    for item in decorated:
        item["cell_line_names"] = [cell["name"] for cell in line_map.get(item["experiment_id"], [])]
        by_day.setdefault(item["due_date"], []).append(item)

    from .todos import todos_between

    todo_map = todos_between(conn, days[0].isoformat(), days[-1].isoformat(), now=now)

    day_list = []
    for day in days:
        items = by_day.get(day.isoformat(), [])
        pending = [item for item in items if not item["done"]]
        todos = todo_map.get(day.isoformat(), [])
        day_list.append({
            "date": day.isoformat(),
            "weekday": weekday_label(day),
            "is_today": day == now.date(),
            "is_past": day < now.date(),
            "items": items,
            "passages": passages_by_day.get(day.isoformat(), []),
            "todos": todos,
            "pending_count": len(pending),
            "done_count": len(items) - len(pending),
            "overdue_count": len([item for item in pending if item["state"] == "overdue"]),
            "todo_count": len([item for item in todos if not item["done"]]),
        })

    return {
        "now": fmt_dt(now),
        "today": now.date().isoformat(),
        "start": days[0].isoformat(),
        "end": days[-1].isoformat(),
        "label": f"{days[0]:%m-%d} ~ {days[-1]:%m-%d}",
        "prev_start": (days[0] - timedelta(days=7)).isoformat(),
        "next_start": (days[0] + timedelta(days=7)).isoformat(),
        "this_week_start": (now.date() - timedelta(days=now.date().weekday())).isoformat(),
        "days": day_list,
        "total_pending": sum(day["pending_count"] for day in day_list),
    }


def month_view(conn: sqlite3.Connection, *, month: Any = None,
               now: datetime | None = None) -> dict[str, Any]:
    """月视图：一个月里每天的检查点 + 传代待办。

    - 检查点：进行中/已暂停实验的未完成时间点，外加本月内已勾选的记录（回看）
    - 传代：活跃批次建议传代日期落在当天的，记为「待传代」
    month 传 'YYYY-MM' 或任意日期；默认当月。
    """
    now = now or _now()
    if month:
        text = str(month).strip()
        try:
            first = datetime.strptime(text[:7] + "-01", "%Y-%m-%d").date()
        except ValueError as exc:
            raise ValidationError(f"月份格式无法识别：{text}（应为 YYYY-MM）") from exc
    else:
        first = now.date().replace(day=1)
    # 下个月第一天 - 1 天 = 本月最后一天
    if first.month == 12:
        next_first = first.replace(year=first.year + 1, month=1)
    else:
        next_first = first.replace(month=first.month + 1)
    last = next_first - timedelta(days=1)

    # 日历格子是 6 行 × 7 列，从本月第一天所在周的周一开始，
    # 因此会露出上月末和下月初的日期 —— 查询范围必须按格子范围来，
    # 否则「加在下个月的待办」在格子里能看到日期却看不到内容。
    grid_start = first - timedelta(days=first.weekday())
    grid_end = grid_start + timedelta(days=41)

    # ---------- 检查点 ----------
    rows = fetch_all(
        conn,
        """
        SELECT c.*, e.name AS experiment_name, e.status AS experiment_status,
               e.interval_unit AS experiment_interval_unit
        FROM experiment_checkpoints c
        JOIN culture_experiments e ON e.id = c.experiment_id
        WHERE c.due_date BETWEEN ? AND ?
          AND (c.done = 0 OR e.status IN ('active', 'paused', 'done', 'aborted'))
        ORDER BY c.due_at ASC, c.seq ASC
        """,
        (grid_start.isoformat(), grid_end.isoformat()),
    )
    decorated = []
    for row in rows:
        item = decorate_checkpoint(row, now, row.get("experiment_interval_unit"))
        item["experiment_id"] = int(row["experiment_id"])
        decorated.append(item)

    exp_ids = sorted({item["experiment_id"] for item in decorated})
    line_map = _experiment_lines(conn, exp_ids) if exp_ids else {}

    # ---------- 传代待办 ----------
    passage_rows = fetch_all(
        conn,
        """
        SELECT cb.id AS batch_id, cb.batch_name, cb.cell_line_id,
               cl.name AS cell_line, cr.next_passage_date, cr.passage, cr.status
        FROM culture_batches cb
        JOIN cell_lines cl ON cl.id = cb.cell_line_id
        JOIN culture_records cr ON cr.id = (
            SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
            ORDER BY r.date DESC, r.id DESC LIMIT 1
        )
        WHERE cb.is_active = 1
          AND cr.next_passage_date IS NOT NULL AND cr.next_passage_date <> ''
          AND cr.next_passage_date BETWEEN ? AND ?
        ORDER BY cr.next_passage_date, cl.name
        """,
        (grid_start.isoformat(), grid_end.isoformat()),
    )

    by_day: dict[str, dict[str, list[dict[str, Any]]]] = {}

    def day_bucket(day: str) -> dict[str, list[dict[str, Any]]]:
        return by_day.setdefault(day, {"checks": [], "passages": []})

    for item in decorated:
        item["cell_line_names"] = [cell["name"] for cell in line_map.get(item["experiment_id"], [])]
        day_bucket(item["due_date"])["checks"].append(item)

    for row in passage_rows:
        day_bucket(row["next_passage_date"])["passages"].append({
            "batch_id": int(row["batch_id"]),
            "batch_name": row["batch_name"],
            "cell_line": row["cell_line"],
            "cell_line_id": int(row["cell_line_id"]),
            "passage": row["passage"],
            "status": row["status"],
            "date": row["next_passage_date"],
        })

    # ---------- 用户自建待办（排在实验检查之后） ----------
    from .todos import todos_between

    # 同样按格子范围查，这样加在下个月（或上个月）的待办也能显示
    todo_map = todos_between(conn, grid_start.isoformat(), grid_end.isoformat(), now=now)

    days = []
    for offset in range(42):
        day = grid_start + timedelta(days=offset)
        key = day.isoformat()
        bucket = by_day.get(key, {"checks": [], "passages": []})
        pending_checks = [item for item in bucket["checks"] if not item["done"]]
        todos = todo_map.get(key, [])
        pending_todos = [item for item in todos if not item["done"]]
        # 右上角角标：把检查、待办、传代都算进去（传代无论几批次都只算 1 次）
        total_count = len(pending_checks) + len(pending_todos) + (1 if bucket["passages"] else 0)
        days.append({
            "date": key,
            "day": day.day,
            "weekday": day.weekday(),
            "in_month": day.month == first.month,
            "is_today": day == now.date(),
            "is_past": day < now.date(),
            "checks": bucket["checks"],
            "passages": bucket["passages"],
            "todos": todos,
            "pending_count": len(pending_checks),
            "total_count": total_count,
            "done_count": len(bucket["checks"]) - len(pending_checks),
            "overdue_count": len([item for item in pending_checks if item["state"] == "overdue"]),
            "passage_count": len(bucket["passages"]),
            "todo_count": len(pending_todos),
        })

    prev_first = (first - timedelta(days=1)).replace(day=1)
    return {
        "now": fmt_dt(now),
        "today": now.date().isoformat(),
        "month": f"{first:%Y-%m}",
        "label": f"{first.year} 年 {first.month} 月",
        "start": first.isoformat(),
        "end": last.isoformat(),
        "prev_month": f"{prev_first:%Y-%m}",
        "next_month": f"{next_first:%Y-%m}",
        "this_month": f"{now.date():%Y-%m}",
        "weekdays": ["周一", "周二", "周三", "周四", "周五", "周六", "周日"],
        "days": days,
        "totals": {
            "checks_pending": sum(day["pending_count"] for day in days if day["in_month"]),
            "passages": sum(day["passage_count"] for day in days if day["in_month"]),
        },
    }


def summary(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict[str, Any]:
    """一次查出所有未完成检查点，按实验聚合出提醒需要的数据。"""
    now = now or _now()
    horizon = fmt_dt(now + timedelta(days=WINDOW_DAYS))
    pending = fetch_all(
        conn,
        """
        SELECT c.*, e.name AS experiment_name, e.status AS experiment_status,
               e.interval_unit AS experiment_interval_unit,
               e.notes AS experiment_notes, cl.name AS cell_line_name
        FROM experiment_checkpoints c
        JOIN culture_experiments e ON e.id = c.experiment_id
        LEFT JOIN cell_lines cl ON cl.id = e.cell_line_id
        WHERE c.done = 0 AND e.status IN ('active', 'paused') AND c.due_at <= ?
        ORDER BY c.due_at ASC, c.seq ASC
        """,
        (horizon,),
    )
    decorated = []
    for row in pending:
        item = decorate_checkpoint(row, now, row.get("experiment_interval_unit"))
        item["experiment_id"] = int(row["experiment_id"])
        decorated.append(item)

    overdue = [item for item in decorated if item["state"] == "overdue"]
    today = now.date().isoformat()
    due_today = [item for item in decorated if item["state"] != "overdue" and item["due_date"] == today]
    upcoming = [item for item in decorated if item["state"] == "upcoming"]

    by_experiment: dict[int, dict[str, Any]] = {}
    for item in decorated:
        entry = by_experiment.setdefault(int(item["experiment_id"]), {
            "experiment_id": int(item["experiment_id"]),
            "experiment_name": item["experiment_name"],
            "experiment_status": item["experiment_status"],
            "cell_line_name": item.get("cell_line_name"),
            "experiment_notes": item.get("experiment_notes"),
            "overdue_count": 0,
            "today_count": 0,
            "upcoming_count": 0,
            "first_due": item,
        })
        if item["state"] == "overdue":
            entry["overdue_count"] += 1
        elif item["state"] == "due":
            entry["today_count"] += 1
        else:
            entry["upcoming_count"] += 1

    items = list(by_experiment.values())
    items.sort(key=lambda entry: (STATUS_PRIORITY.get(entry["first_due"]["state"], 3),
                                  entry["first_due"]["due_at"]))
    # 补上关联细胞株，提醒里也能看出是哪几株细胞
    line_map = _experiment_lines(conn, [entry["experiment_id"] for entry in items])
    for entry in items:
        cells = line_map.get(entry["experiment_id"], [])
        if not cells and entry.get("cell_line_name"):
            cells = [{"cell_line_id": None, "name": entry["cell_line_name"], "species": None, "type": None}]
        entry["cell_lines"] = cells
        entry["cell_line_name"] = "、".join(cell["name"] for cell in cells) or None
        first = entry["first_due"]
        if entry["overdue_count"]:
            entry["state"] = "overdue"
            entry["state_label"] = f"逾期 {entry['overdue_count']} 个"
        elif entry["today_count"]:
            entry["state"] = "due"
            entry["state_label"] = "今天到点"
        else:
            entry["state"] = "upcoming"
            entry["state_label"] = "即将到点"
        entry["due_label"] = first["due_label"]
        entry["gap_text"] = first["gap_text"]
        entry["checkpoints"] = [
            item for item in decorated if int(item["experiment_id"]) == entry["experiment_id"]
        ][:6]

    active_count = int(conn.execute(
        "SELECT COUNT(*) FROM culture_experiments WHERE status IN ('active', 'paused')"
    ).fetchone()[0] or 0)

    # 用户自建待办：逾期 / 今天到点的也进提醒
    from .todos import todo_stats

    todo_info = todo_stats(conn, now=now)

    return {
        "now": fmt_dt(now),
        "today": today,
        "stats": {
            "active_experiments": active_count,
            "overdue_experiments": len({i["experiment_id"] for i in overdue}),
            "overdue_checkpoints": len(overdue),
            "today_experiments": len({i["experiment_id"] for i in due_today}),
            "today_checkpoints": len(due_today),
            "upcoming_experiments": len({i["experiment_id"] for i in upcoming}),
            "pending_checkpoints": len(decorated),
            "todo_pending": todo_info["pending"],
            "todo_overdue": todo_info["overdue"],
            "todo_today": todo_info["today"],
            "todo_done": todo_info["done"],
        },
        "overdue": [item for item in items if item["state"] == "overdue"],
        "due_today": [item for item in items if item["state"] == "due"],
        "upcoming": [item for item in items if item["state"] == "upcoming"],
        "items": items,
        "window_days": WINDOW_DAYS,
    }
