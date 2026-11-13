"""业务规则：PD 计算、日期/数字解析、传代记录重算。

这里刻意保持与旧版 Streamlit 应用一致的语义：
- 单次 PD = log2(本次收获 / 上次接种)，两者都 > 0 才计算，否则记 0
- 累计 PD = 批次初始 PD + 每次 max(0, 单次 PD) 之和
- 单次 PD 允许为负数（例如计数下降），但累计 PD 只累加正数
- 重算按日期升序、同日期按 id 升序，逐一以「上一条记录的接种数」为分母
"""

from __future__ import annotations

import math
import re
import sqlite3
from datetime import date, datetime
from typing import Any, Iterable

from .errors import ValidationError

DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y.%m.%d",
    "%Y%m%d",
    "%Y-%m",
    "%Y/%m",
    "%Y.%m",
)

STATUS_CHOICES = ("良好", "一般", "较差", "污染")
LINE_TYPES = ("永生化", "原代")
# 物种标签不预设任何固定选项：完全由使用者自由填写，配色按标签自动分色系
VIAL_STATUSES = ("在库", "已复苏", "已丢弃")
END_REASONS = ("污染", "全部冻存", "丢弃", "实验结束", "其他")

TODAY = lambda: date.today().isoformat()  # noqa: E731


def today_iso() -> str:
    return date.today().isoformat()


# --------------------------------------------------------------------------
# 数字 / 日期解析
# --------------------------------------------------------------------------
def calc_pd(harvested: Any, inoculum: Any) -> float:
    try:
        harvested_f = float(harvested)
        inoculum_f = float(inoculum)
    except (TypeError, ValueError):
        return 0.0
    if inoculum_f > 0 and harvested_f > 0:
        return round(math.log2(harvested_f / inoculum_f), 2)
    return 0.0


_SCI_RE = re.compile(r"(\d+(?:\.\d+)?)\s*[xX×*]\s*10\s*\^?\s*(\d+)")


def parse_number(value: Any) -> float | None:
    """解析数字，支持 1,200、5.1X10^5、5.1×105 等写法。无法解析返回 None。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return None if isinstance(value, float) and math.isnan(value) else float(value)
    text = str(value).strip().replace(",", "").replace(" ", "")
    if not text:
        return None
    match = _SCI_RE.match(text)
    if match:
        return float(match.group(1)) * (10 ** int(match.group(2)))
    try:
        return float(text)
    except ValueError:
        return None


def parse_date_value(value: Any) -> str | None:
    """把多种日期写法转成 ISO 字符串，解析不了返回 None。"""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value).strip()
    if not text:
        return None
    # 去掉可能的时间部分
    text = text.replace("年", "-").replace("月", "-").replace("日", "")
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # 2026-1-5 这类无前导零格式
    match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        year, month, day = (int(part) for part in match.groups())
        try:
            return date(year, month, day).isoformat()
        except ValueError:
            return None
    # 只给年份
    if re.fullmatch(r"(19|20)\d{2}", text):
        return f"{text}-01-01"
    return None


def normalize_date(value: Any, field: str = "日期", required: bool = False) -> str | None:
    if value in (None, ""):
        if required:
            raise ValidationError(f"{field}不能为空")
        return None
    parsed = parse_date_value(value)
    if not parsed:
        raise ValidationError(f"{field}格式无法识别：{value!r}，请使用 YYYY-MM-DD")
    return parsed


def normalize_number(value: Any, field: str, required: bool = False, minimum: float | None = None) -> float | None:
    if value in (None, ""):
        if required:
            raise ValidationError(f"{field}不能为空")
        return None
    parsed = parse_number(value)
    if parsed is None:
        raise ValidationError(f"{field}必须是数字，收到：{value!r}")
    if minimum is not None and parsed < minimum:
        raise ValidationError(f"{field}不能小于 {minimum}")
    return parsed


def normalize_int(value: Any, field: str, required: bool = False, minimum: int | None = None) -> int | None:
    parsed = normalize_number(value, field, required=required, minimum=minimum)
    if parsed is None:
        return None
    if abs(parsed - round(parsed)) > 1e-9:
        raise ValidationError(f"{field}必须是整数，收到：{value!r}")
    return int(round(parsed))


def normalize_text(value: Any, max_length: int = 2000) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if len(text) > max_length:
        raise ValidationError(f"文本过长（最多 {max_length} 字符）")
    return text


def normalize_choice(value: Any, choices: Iterable[str], field: str, default: str | None = None,
                     allow_empty: bool = False) -> str | None:
    text = normalize_text(value)
    if not text:
        if default is not None:
            return default
        if allow_empty:
            return None
        raise ValidationError(f"{field}不能为空")
    if text not in choices:
        raise ValidationError(f"{field}必须是 {'/'.join(choices)} 之一")
    return text


def normalize_species(value: Any) -> str | None:
    """物种标签：完全自由填写，不做任何预设或归一，只去掉首尾空白。"""
    text = normalize_text(value, max_length=40)
    return text or None


# --------------------------------------------------------------------------
# 批次累计 PD
# --------------------------------------------------------------------------
def recalculate_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any] | None:
    """按旧版规则重算某批次所有记录的单次/累计 PD，返回汇总。"""
    batch = conn.execute(
        "SELECT id, initial_pd, initial_cell_count FROM culture_batches WHERE id = ?", (batch_id,)
    ).fetchone()
    if batch is None:
        return None

    initial_pd = float(batch["initial_pd"] or 0.0)
    records = conn.execute(
        "SELECT id, harvested_cells, inoculum_cells FROM culture_records "
        "WHERE batch_id = ? ORDER BY date ASC, id ASC",
        (batch_id,),
    ).fetchall()

    cumulative = initial_pd
    prev_inoculum = batch["initial_cell_count"]
    last_pd = 0.0
    for record in records:
        harvested = record["harvested_cells"]
        pd_value = calc_pd(harvested, prev_inoculum) if prev_inoculum else 0.0
        cumulative += max(0.0, pd_value)
        conn.execute(
            "UPDATE culture_records SET pd = ?, cumulative_pd = ? WHERE id = ?",
            (pd_value, round(cumulative, 2), record["id"]),
        )
        prev_inoculum = record["inoculum_cells"]
        last_pd = pd_value

    return {
        "batch_id": batch_id,
        "records": len(records),
        "cumulative_pd": round(cumulative, 2),
        "last_pd": last_pd,
    }


def refresh_active_record(conn: sqlite3.Connection, batch_id: int) -> int | None:
    """保证活跃批次只有「日期最新、同日期 id 最大」的一条活跃记录。"""
    batch = conn.execute("SELECT is_active FROM culture_batches WHERE id = ?", (batch_id,)).fetchone()
    if batch is None or not batch["is_active"]:
        return None
    latest = conn.execute(
        "SELECT id FROM culture_records WHERE batch_id = ? ORDER BY date DESC, id DESC LIMIT 1",
        (batch_id,),
    ).fetchone()
    if latest is None:
        conn.execute("UPDATE culture_records SET is_active = 0 WHERE batch_id = ?", (batch_id,))
        return None
    conn.execute(
        "UPDATE culture_records SET is_active = CASE WHEN id = ? THEN 1 ELSE 0 END WHERE batch_id = ?",
        (latest["id"], batch_id),
    )
    return int(latest["id"])


# --------------------------------------------------------------------------
# Excel 单元格文本解析（与旧版 parse_cell_text 行为一致）
# --------------------------------------------------------------------------
def parse_cell_text(text: Any) -> dict[str, Any] | None:
    if text is None:
        return None
    raw = str(text).strip()
    if not raw:
        return None
    lines = [line.strip() for line in raw.splitlines() if line.strip()]
    if len(lines) == 1 and " " in lines[0]:
        alt = re.split(r"\s{2,}|\t|,|;", lines[0])
        if len(alt) > 1:
            lines = [part.strip() for part in alt if part.strip()]
        else:
            lines = [part for part in lines[0].split() if part]

    if not lines:
        return None

    cell_name = lines[0].strip()
    if not cell_name:
        return None

    numbers: list[float] = []
    dates: list[str] = []
    others: list[str] = []

    for token in lines[1:]:
        token = token.strip()
        if not token:
            continue
        pd_match = re.search(r"[pP][dD]\s*[=：:]\s*(\d+(?:\.\d+)?)", token)
        if pd_match:
            numbers.append(float(pd_match.group(1)))
            continue
        parsed_date = parse_date_value(token)
        if parsed_date:
            dates.append(parsed_date)
            continue
        number = parse_number(token)
        if number is not None:
            numbers.append(number)
        else:
            others.append(token)

    cell_count = numbers[0] if numbers else None
    pd_value = numbers[1] if len(numbers) > 1 else None
    freeze_date = dates[0] if dates else None
    revived_date = dates[1] if len(dates) > 1 else None

    return {
        "cell_name": cell_name,
        "cell_count": cell_count,
        "pd": pd_value,
        "freeze_date": freeze_date,
        "revived_date": revived_date,
        "status": "已复苏" if revived_date else "在库",
        "notes": " ".join(others),
    }


# --------------------------------------------------------------------------
# 展示辅助
# --------------------------------------------------------------------------
def remaining_days(next_passage_date: Any, today: date | None = None) -> int | None:
    if not next_passage_date:
        return None
    parsed = parse_date_value(next_passage_date)
    if not parsed:
        return None
    base = today or date.today()
    return (date.fromisoformat(parsed) - base).days


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None
