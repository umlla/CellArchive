"""用户待办事项服务。

与细胞实验无关的独立待办（例如「买培养基」「预约离心机」）：
- 必须有一个日期，时间可留空（全天待办）
- 可以勾选完成 / 撤销 / 推迟一天 / 删除
- 在月视图、周视图里排在实验检查之后，用专属颜色区分
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from ..domain import normalize_text, parse_date_value
from ..errors import NotFound, ValidationError
from . import audit, fetch_all, fetch_one, get_or_404

MAX_TITLE = 200
MAX_NOTES = 2000

_STATE_LABELS = {
    "overdue": "已逾期",
    "due": "今天",
    "upcoming": "即将到点",
    "scheduled": "计划中",
    "done": "已完成",
}


def _now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def _normalize_date(value: Any, field: str = "日期", required: bool = True) -> str | None:
    if value in (None, ""):
        if required:
            raise ValidationError(f"{field}不能为空")
        return None
    parsed = parse_date_value(value)
    if not parsed:
        raise ValidationError(f"{field}格式无法识别：{value!r}，请使用 YYYY-MM-DD")
    return parsed


def _normalize_clock(value: Any) -> str | None:
    """时间可留空；支持 'HH:MM'、'H:MM'、'HH:MM:SS'。"""
    text = "" if value is None else str(value).strip()
    if not text:
        return None
    for fmt in ("%H:%M", "%H:%M:%S", "%H%M"):
        try:
            return datetime.strptime(text, fmt).strftime("%H:%M")
        except ValueError:
            continue
    raise ValidationError(f"时间格式无法识别：{text}（应为 HH:MM）")


def _due_datetime(row: dict[str, Any]) -> datetime | None:
    """待办的到期时刻；没有时间时按当天 23:59 计算（全天待办当天都算「今天」）。"""
    if not row.get("due_date"):
        return None
    clock = row.get("due_clock") or "23:59"
    try:
        return datetime.strptime(f"{row['due_date']} {clock}", "%Y-%m-%d %H:%M")
    except ValueError:
        return None


def _state(row: dict[str, Any], now: datetime) -> str:
    if row.get("done"):
        return "done"
    due = _due_datetime(row)
    if due is None:
        return "scheduled"
    if row.get("due_clock"):
        # 有具体时间：过点即逾期，24 小时内算今天
        if due < now:
            return "overdue"
        if due - now <= timedelta(hours=24):
            return "due"
    else:
        # 全天待办：日期过了才算逾期
        if due.date() < now.date():
            return "overdue"
        if due.date() == now.date():
            return "due"
    if (due.date() - now.date()).days <= 3:
        return "upcoming"
    return "scheduled"


def _rel_label(day: date, now: datetime) -> str:
    delta = (day - now.date()).days
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
    return day.strftime("%m-%d")


def _decorate(row: dict[str, Any], now: datetime) -> dict[str, Any]:
    item = dict(row)
    item["done"] = bool(row.get("done"))
    state = _state(row, now)
    item["state"] = state
    item["state_label"] = _STATE_LABELS.get(state, state)
    item["kind"] = "todo"
    # 与实验检查点保持同样的字段名，前端日历可以共用渲染逻辑
    if row.get("due_clock"):
        item["due_clock"] = row["due_clock"]
        item["due_label"] = f"{_rel_label(date.fromisoformat(row['due_date']), now)} {row['due_clock']}"
    else:
        item["due_clock"] = None
        item["due_label"] = f"{_rel_label(date.fromisoformat(row['due_date']), now)}（全天）"
    item["rel_day"] = _rel_label(date.fromisoformat(row["due_date"]), now)
    due = _due_datetime(row)
    if due and state != "done":
        # 与细胞实验共用同一套「按日历天数」的算法，避免两处不一致
        from .experiments import human_gap

        item["gap_text"] = human_gap(due, now)
    else:
        item["gap_text"] = ""
    return item


# --------------------------------------------------------------------------
# 查询
# --------------------------------------------------------------------------
def list_todos(
    conn: sqlite3.Connection,
    *,
    start: str | None = None,
    end: str | None = None,
    include_done: bool = True,
    q: str | None = None,
    only_done: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    now = now or _now()
    clauses: list[str] = []
    params: list[Any] = []
    if start:
        clauses.append("due_date >= ?")
        params.append(_normalize_date(start, "起始日期"))
    if end:
        clauses.append("due_date <= ?")
        params.append(_normalize_date(end, "结束日期"))
    if only_done:
        clauses.append("done = 1")
    elif not include_done:
        clauses.append("done = 0")
    if q:
        keyword = f"%{q.strip()}%"
        clauses.append("(title LIKE ? OR IFNULL(notes, '') LIKE ?)")
        params.extend([keyword, keyword])
    sql = "SELECT * FROM todo_items"
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    sql += " ORDER BY due_date ASC, IFNULL(due_clock, '99:99') ASC, id ASC"
    rows = fetch_all(conn, sql, tuple(params))
    return [_decorate(row, now) for row in rows]


def todos_between(conn: sqlite3.Connection, start: str, end: str,
                  *, now: datetime | None = None) -> dict[str, list[dict[str, Any]]]:
    """按日期分组的待办，供日历视图使用。"""
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in list_todos(conn, start=start, end=end, include_done=True, now=now):
        grouped.setdefault(item["due_date"], []).append(item)
    return grouped


def todo_stats(conn: sqlite3.Connection, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or _now()
    today = now.date().isoformat()
    pending = list_todos(conn, include_done=False, now=now)
    overdue = [item for item in pending if item["state"] == "overdue"]
    today_items = [item for item in pending if item["state"] == "due"]
    done_count = int(conn.execute("SELECT COUNT(*) FROM todo_items WHERE done = 1").fetchone()[0] or 0)
    return {
        "pending": len(pending),
        "overdue": len(overdue),
        "today": len(today_items),
        "done": done_count,
        "today_date": today,
    }


# --------------------------------------------------------------------------
# 写入
# --------------------------------------------------------------------------
def _clean_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if "title" in payload or not partial:
        title = normalize_text(payload.get("title"), max_length=MAX_TITLE)
        if not title:
            raise ValidationError("待办内容不能为空")
        data["title"] = title
    if "notes" in payload or not partial:
        data["notes"] = normalize_text(payload.get("notes"), max_length=MAX_NOTES)
    if "due_date" in payload or not partial:
        data["due_date"] = _normalize_date(payload.get("due_date"), "日期", required=True)
    if "due_clock" in payload or not partial:
        data["due_clock"] = _normalize_clock(payload.get("due_clock"))
    return data


def create_todo(conn: sqlite3.Connection, payload: dict[str, Any],
                user: str | None = None) -> dict[str, Any]:
    """新建待办。

    支持两种写法：
    - 完整：{title, due_date, due_clock?, notes?}
    - 日历格子里快速添加：{title, date} 或 {title, due_date}，时间留空即为全天
    """
    if "due_date" not in payload and "date" in payload:
        payload = {**payload, "due_date": payload.get("date")}
    if "title" not in payload and "content" in payload:
        payload = {**payload, "title": payload.get("content")}
    data = _clean_payload(payload)
    now_text = _fmt(_now())
    cursor = conn.execute(
        "INSERT INTO todo_items (title, notes, due_date, due_clock, done, created_at, updated_at) "
        "VALUES (?,?,?,?,0,?,?)",
        (data["title"], data["notes"], data["due_date"], data["due_clock"], now_text, now_text),
    )
    todo_id = int(cursor.lastrowid)
    audit(conn, user, "create", "todo", todo_id, data)
    return get_todo(conn, todo_id)


def get_todo(conn: sqlite3.Connection, todo_id: int, *, now: datetime | None = None) -> dict[str, Any]:
    row = get_or_404(conn, "todo_items", todo_id, "待办")
    return _decorate(row, now or _now())


def update_todo(conn: sqlite3.Connection, todo_id: int, payload: dict[str, Any],
                user: str | None = None) -> dict[str, Any]:
    get_or_404(conn, "todo_items", todo_id, "待办")
    data = _clean_payload(payload, partial=True)
    if data:
        data["updated_at"] = _fmt(_now())
        clause = ", ".join(f"{key} = ?" for key in data)
        conn.execute(f"UPDATE todo_items SET {clause} WHERE id = ?", (*data.values(), todo_id))
        audit(conn, user, "update", "todo", todo_id, {"fields": list(data)})
    return get_todo(conn, todo_id)


def complete_todo(conn: sqlite3.Connection, todo_id: int, payload: dict[str, Any],
                  user: str | None = None) -> dict[str, Any]:
    row = get_or_404(conn, "todo_items", todo_id, "待办")
    done = payload.get("done", True)
    done_flag = 1 if done not in (False, 0, "0", "false") else 0
    conn.execute(
        "UPDATE todo_items SET done = ?, done_at = ?, updated_at = ? WHERE id = ?",
        (done_flag, _fmt(_now()) if done_flag else None, _fmt(_now()), todo_id),
    )
    audit(conn, user, "complete" if done_flag else "reopen", "todo", todo_id,
          {"title": row["title"]})
    return get_todo(conn, todo_id)


def postpone_todo(conn: sqlite3.Connection, todo_id: int, payload: dict[str, Any],
                  user: str | None = None) -> dict[str, Any]:
    row = get_or_404(conn, "todo_items", todo_id, "待办")
    try:
        days = int(payload.get("days", 1))
    except (TypeError, ValueError) as exc:
        raise ValidationError("推迟天数必须是整数") from exc
    if days == 0:
        raise ValidationError("推迟天数不能为 0")
    if abs(days) > 90:
        raise ValidationError("一次最多推迟 90 天")
    base = datetime.strptime(row["due_date"], "%Y-%m-%d")
    new_date = (base + timedelta(days=days)).strftime("%Y-%m-%d")
    conn.execute(
        "UPDATE todo_items SET due_date = ?, updated_at = ? WHERE id = ?",
        (new_date, _fmt(_now()), todo_id),
    )
    audit(conn, user, "postpone", "todo", todo_id, {"days": days, "new_date": new_date})
    return get_todo(conn, todo_id)


def delete_todo(conn: sqlite3.Connection, todo_id: int, user: str | None = None) -> dict[str, Any]:
    row = get_or_404(conn, "todo_items", todo_id, "待办")
    conn.execute("DELETE FROM todo_items WHERE id = ?", (todo_id,))
    audit(conn, user, "delete", "todo", todo_id, {"title": row["title"]})
    return {"deleted": todo_id}
