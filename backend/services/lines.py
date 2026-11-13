"""细胞株相关服务。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..domain import (
    LINE_TYPES,
    normalize_choice,
    normalize_date,
    normalize_int,
    normalize_species,
    normalize_text,
    today_iso,
)
from ..errors import Conflict, NotFound, ValidationError
from . import audit, fetch_all, fetch_one, get_or_404, require_non_empty

LINE_SUMMARY_SQL = """
SELECT cl.*,
    (SELECT COUNT(*) FROM culture_batches b WHERE b.cell_line_id = cl.id AND b.is_active = 1) AS active_batch_count,
    (SELECT COUNT(*) FROM culture_batches b WHERE b.cell_line_id = cl.id) AS batch_count,
    (SELECT COUNT(*) FROM frozen_vials v WHERE v.cell_line_id = cl.id) AS total_vials,
    (SELECT COUNT(*) FROM frozen_vials v WHERE v.cell_line_id = cl.id AND v.status = '在库') AS in_stock_vials,
    (SELECT cr.cumulative_pd FROM culture_records cr
        JOIN culture_batches b3 ON b3.id = cr.batch_id
        WHERE b3.cell_line_id = cl.id
        ORDER BY cr.date DESC, cr.id DESC LIMIT 1) AS latest_pd,
    (SELECT cr.date FROM culture_records cr
        JOIN culture_batches b4 ON b4.id = cr.batch_id
        WHERE b4.cell_line_id = cl.id
        ORDER BY cr.date DESC, cr.id DESC LIMIT 1) AS latest_record_date
FROM cell_lines cl
"""


def _clean_payload(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if not partial or "name" in payload:
        data["name"] = require_non_empty(payload.get("name"), "细胞株名称")
        if len(data["name"]) > 120:
            raise ValidationError("细胞株名称过长（最多 120 字）")
    if not partial or "type" in payload:
        data["type"] = normalize_choice(payload.get("type"), LINE_TYPES, "细胞类型", default="永生化")
    if not partial or "species" in payload:
        data["species"] = normalize_species(payload.get("species"))
    if not partial or "revival_date" in payload:
        data["revival_date"] = normalize_date(payload.get("revival_date"), "复苏日期")
    if not partial or "default_passage_interval" in payload:
        interval = normalize_int(payload.get("default_passage_interval"), "默认传代间隔", minimum=0)
        data["default_passage_interval"] = interval if interval is not None else 0
    if not partial or "notes" in payload:
        data["notes"] = normalize_text(payload.get("notes"))
    return data


def list_lines(conn: sqlite3.Connection, search: str | None = None) -> list[dict[str, Any]]:
    if search:
        rows = fetch_all(
            conn,
            LINE_SUMMARY_SQL + " WHERE cl.name LIKE ? OR cl.notes LIKE ? ORDER BY cl.name",
            (f"%{search.strip()}%", f"%{search.strip()}%"),
        )
    else:
        rows = fetch_all(conn, LINE_SUMMARY_SQL + " ORDER BY cl.name")
    return rows


def get_line(conn: sqlite3.Connection, line_id: int) -> dict[str, Any]:
    return get_or_404(conn, "cell_lines", line_id, "细胞株")


def get_line_summary(conn: sqlite3.Connection, line_id: int) -> dict[str, Any]:
    row = fetch_one(conn, LINE_SUMMARY_SQL + " WHERE cl.id = ?", (line_id,))
    if row is None:
        raise NotFound(f"细胞株不存在（id={line_id}）")
    return row


def create_line(conn: sqlite3.Connection, payload: dict[str, Any], user: str | None = None) -> dict[str, Any]:
    data = _clean_payload(payload)
    existing = conn.execute("SELECT id FROM cell_lines WHERE name = ?", (data["name"],)).fetchone()
    if existing:
        raise Conflict(f"细胞株「{data['name']}」已存在")
    if not data.get("revival_date"):
        data["revival_date"] = today_iso()
    cursor = conn.execute(
        "INSERT INTO cell_lines (name, revival_date, type, default_passage_interval, notes, species) "
        "VALUES (?,?,?,?,?,?)",
        (data["name"], data["revival_date"], data["type"], data["default_passage_interval"],
         data["notes"], data.get("species")),
    )
    line_id = int(cursor.lastrowid)
    audit(conn, user, "create", "cell_line", line_id, data)
    return get_line_summary(conn, line_id)


def update_line(conn: sqlite3.Connection, line_id: int, payload: dict[str, Any],
                user: str | None = None) -> dict[str, Any]:
    get_or_404(conn, "cell_lines", line_id, "细胞株")
    data = _clean_payload(payload, partial=True)
    if not data:
        return get_line_summary(conn, line_id)
    if "name" in data:
        existing = conn.execute(
            "SELECT id FROM cell_lines WHERE name = ? AND id <> ?", (data["name"], line_id)
        ).fetchone()
        if existing:
            raise Conflict(f"细胞株名称「{data['name']}」已被占用")
    assignments = ", ".join(f"{key} = ?" for key in data)
    conn.execute(f"UPDATE cell_lines SET {assignments} WHERE id = ?", (*data.values(), line_id))
    audit(conn, user, "update", "cell_line", line_id, data)
    return get_line_summary(conn, line_id)


def delete_line(conn: sqlite3.Connection, line_id: int, user: str | None = None) -> dict[str, Any]:
    get_or_404(conn, "cell_lines", line_id, "细胞株")
    deleted = {
        "vials": conn.execute("DELETE FROM frozen_vials WHERE cell_line_id = ?", (line_id,)).rowcount,
        "records": conn.execute(
            "DELETE FROM culture_records WHERE batch_id IN "
            "(SELECT id FROM culture_batches WHERE cell_line_id = ?)", (line_id,)
        ).rowcount,
        "batches": conn.execute("DELETE FROM culture_batches WHERE cell_line_id = ?", (line_id,)).rowcount,
        "group_links": conn.execute(
            "DELETE FROM cell_group_members WHERE cell_line_id = ?", (line_id,)
        ).rowcount,
    }
    conn.execute("DELETE FROM cell_lines WHERE id = ?", (line_id,))
    audit(conn, user, "delete", "cell_line", line_id, deleted)
    return deleted


def line_batches(conn: sqlite3.Connection, line_id: int, include_ended: bool = True) -> list[dict[str, Any]]:
    get_or_404(conn, "cell_lines", line_id, "细胞株")
    sql = (
        "SELECT cb.*, "
        "  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1 "
        "   ORDER BY r.date DESC, r.id DESC LIMIT 1) AS active_record_id, "
        "  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id "
        "   ORDER BY r.date DESC, r.id DESC LIMIT 1) AS latest_record_id, "
        "  (SELECT COUNT(*) FROM culture_records r WHERE r.batch_id = cb.id) AS records_count "
        "FROM culture_batches cb WHERE cb.cell_line_id = ?"
    )
    params: list[Any] = [line_id]
    if not include_ended:
        sql += " AND cb.is_active = 1"
    sql += " ORDER BY cb.is_active DESC, COALESCE(cb.revival_date, '') DESC, cb.id DESC"

    batches = fetch_all(conn, sql, params)
    for batch in batches:
        record_id = batch["active_record_id"] or batch["latest_record_id"]
        batch["current_record"] = None
        if record_id:
            batch["current_record"] = fetch_one(conn, "SELECT * FROM culture_records WHERE id = ?", (record_id,))
        batch["is_active"] = int(batch["is_active"] or 0)
    return batches


def line_vials(conn: sqlite3.Connection, line_id: int) -> list[dict[str, Any]]:
    get_or_404(conn, "cell_lines", line_id, "细胞株")
    return fetch_all(
        conn,
        "SELECT * FROM frozen_vials WHERE cell_line_id = ? ORDER BY COALESCE(freeze_date, '') DESC, location",
        (line_id,),
    )
