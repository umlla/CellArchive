"""培养批次服务。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..domain import (
    END_REASONS,
    normalize_choice,
    normalize_date,
    normalize_int,
    normalize_number,
    normalize_text,
    recalculate_batch,
    refresh_active_record,
    today_iso,
)
from ..errors import Conflict, NotFound, ValidationError
from . import audit, fetch_all, fetch_one, get_or_404, require_non_empty

BATCH_SELECT = """
SELECT cb.*, cl.name AS cell_name, cl.type AS cell_type, cl.species AS cell_species,
    cl.default_passage_interval,
    (SELECT COUNT(*) FROM culture_records r WHERE r.batch_id = cb.id) AS records_count,
    (SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
        ORDER BY r.date DESC, r.id DESC LIMIT 1) AS active_record_id,
    (SELECT id FROM culture_records r WHERE r.batch_id = cb.id
        ORDER BY r.date DESC, r.id DESC LIMIT 1) AS latest_record_id
FROM culture_batches cb
JOIN cell_lines cl ON cl.id = cb.cell_line_id
"""


def serialize_batch(conn: sqlite3.Connection, batch: dict[str, Any]) -> dict[str, Any]:
    record_id = batch.get("active_record_id") or batch.get("latest_record_id")
    batch["current_record"] = (
        fetch_one(conn, "SELECT * FROM culture_records WHERE id = ?", (record_id,)) if record_id else None
    )
    batch["is_active"] = int(batch.get("is_active") or 0)
    batch["cumulative_pd"] = (
        batch["current_record"]["cumulative_pd"] if batch.get("current_record") else (batch.get("initial_pd") or 0.0)
    )
    return batch


def list_batches(
    conn: sqlite3.Connection,
    cell_line_id: int | None = None,
    active: bool | None = None,
    q: str | None = None,
) -> list[dict[str, Any]]:
    sql = BATCH_SELECT + " WHERE 1 = 1"
    params: list[Any] = []
    if cell_line_id:
        sql += " AND cb.cell_line_id = ?"
        params.append(cell_line_id)
    if active is not None:
        sql += " AND cb.is_active = ?"
        params.append(1 if active else 0)
    if q:
        sql += " AND (cb.batch_name LIKE ? OR cl.name LIKE ?)"
        params.extend([f"%{q.strip()}%", f"%{q.strip()}%"])
    sql += " ORDER BY cb.is_active DESC, COALESCE(cb.revival_date, '') DESC, cb.id DESC"
    return [serialize_batch(conn, row) for row in fetch_all(conn, sql, params)]


def get_batch(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    row = fetch_one(conn, BATCH_SELECT + " WHERE cb.id = ?", (batch_id,))
    if row is None:
        raise NotFound(f"培养批次不存在（id={batch_id}）")
    return serialize_batch(conn, row)


def create_batch(conn: sqlite3.Connection, payload: dict[str, Any],
                 user: str | None = None) -> dict[str, Any]:
    cell_line_id = normalize_int(payload.get("cell_line_id"), "细胞株", required=True)
    line = get_or_404(conn, "cell_lines", int(cell_line_id), "细胞株")
    revival_date = normalize_date(payload.get("revival_date"), "复苏日期") or today_iso()
    source_freeze_date = normalize_date(payload.get("source_freeze_date"), "冻存来源日期")
    initial_pd = normalize_number(payload.get("initial_pd"), "初始PD", minimum=0) or 0.0
    initial_cell_count = normalize_number(payload.get("initial_cell_count"), "复苏接种细胞数", minimum=0)
    if initial_cell_count == 0:
        initial_cell_count = None
    notes = normalize_text(payload.get("notes"))
    batch_name = (payload.get("batch_name") or "").strip()
    if not batch_name:
        cutoff = (revival_date or today_iso()).replace("-", "")[2:8]
        batch_name = f"{line['name']}-{cutoff}"

    vial_id = normalize_int(payload.get("vial_id"), "来源冻存管")
    vial = None
    if vial_id:
        vial = get_or_404(conn, "frozen_vials", int(vial_id), "冻存管")
        if int(vial["cell_line_id"] or 0) != int(line["id"]):
            raise ValidationError("所选冻存管不属于该细胞株")
        if vial["status"] != "在库":
            raise Conflict(f"冻存管当前状态为「{vial['status']}」，不能用于复苏")

    cursor = conn.execute(
        "INSERT INTO culture_batches (cell_line_id, batch_name, revival_date, source_freeze_date, "
        "initial_pd, initial_cell_count, is_active, notes) VALUES (?,?,?,?,?,?,1,?)",
        (line["id"], batch_name, revival_date, source_freeze_date, initial_pd, initial_cell_count, notes),
    )
    batch_id = int(cursor.lastrowid)
    if vial:
        conn.execute(
            "UPDATE frozen_vials SET status = '已复苏', batch_id = ? WHERE id = ?",
            (batch_id, vial["id"]),
        )
    audit(conn, user, "create", "batch", batch_id,
          {"batch_name": batch_name, "vial_id": vial_id})
    return get_batch(conn, batch_id)


def update_batch(conn: sqlite3.Connection, batch_id: int, payload: dict[str, Any],
                 user: str | None = None) -> dict[str, Any]:
    batch = get_or_404(conn, "culture_batches", batch_id, "培养批次")
    assignments: dict[str, Any] = {}
    if "batch_name" in payload:
        assignments["batch_name"] = require_non_empty(payload.get("batch_name"), "批次名称")
    if "revival_date" in payload:
        assignments["revival_date"] = normalize_date(payload.get("revival_date"), "复苏日期")
    if "source_freeze_date" in payload:
        assignments["source_freeze_date"] = normalize_date(payload.get("source_freeze_date"), "冻存来源日期")
    if "initial_pd" in payload:
        assignments["initial_pd"] = normalize_number(payload.get("initial_pd"), "初始PD", minimum=0) or 0.0
    if "initial_cell_count" in payload:
        value = normalize_number(payload.get("initial_cell_count"), "复苏接种细胞数", minimum=0)
        assignments["initial_cell_count"] = None if value == 0 else value
    if "notes" in payload:
        assignments["notes"] = normalize_text(payload.get("notes"))
    if not assignments:
        return get_batch(conn, batch_id)

    clause = ", ".join(f"{key} = ?" for key in assignments)
    conn.execute(
        f"UPDATE culture_batches SET {clause} WHERE id = ?", (*assignments.values(), batch_id)
    )
    if "initial_pd" in assignments or "initial_cell_count" in assignments:
        recalculate_batch(conn, batch_id)
    audit(conn, user, "update", "batch", batch_id, {"fields": list(assignments)})
    return get_batch(conn, int(batch["id"]))


def terminate_batch(conn: sqlite3.Connection, batch_id: int, reason: str | None = "其他",
                    user: str | None = None) -> dict[str, Any]:
    batch = get_or_404(conn, "culture_batches", batch_id, "培养批次")
    if not int(batch["is_active"]):
        raise Conflict("该批次已经终止")
    reason_value = normalize_choice(reason, END_REASONS, "终止原因", default="其他")
    end_date = today_iso()
    conn.execute(
        "UPDATE culture_batches SET is_active = 0, end_date = ?, end_reason = ? WHERE id = ?",
        (end_date, reason_value, batch_id),
    )
    conn.execute("UPDATE culture_records SET is_active = 0 WHERE batch_id = ?", (batch_id,))
    audit(conn, user, "terminate", "batch", batch_id, {"reason": reason_value, "end_date": end_date})
    return get_batch(conn, batch_id)


def restore_batch(conn: sqlite3.Connection, batch_id: int, user: str | None = None) -> dict[str, Any]:
    """撤销终止：恢复为在养状态，并重新标记最新一条传代记录为活跃记录。"""
    batch = get_or_404(conn, "culture_batches", batch_id, "培养批次")
    if int(batch["is_active"]):
        raise Conflict("该批次本来就是活跃状态，无需恢复")
    conn.execute(
        "UPDATE culture_batches SET is_active = 1, end_date = NULL, end_reason = NULL WHERE id = ?",
        (batch_id,),
    )
    refresh_active_record(conn, batch_id)
    audit(conn, user, "restore", "batch", batch_id, {"batch_name": batch["batch_name"]})
    return get_batch(conn, batch_id)


def delete_batch(conn: sqlite3.Connection, batch_id: int, user: str | None = None) -> dict[str, Any]:
    batch = get_or_404(conn, "culture_batches", batch_id, "培养批次")
    deleted_records = conn.execute(
        "DELETE FROM culture_records WHERE batch_id = ?", (batch_id,)
    ).rowcount
    conn.execute("UPDATE frozen_vials SET batch_id = NULL WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM culture_batches WHERE id = ?", (batch_id,))
    audit(conn, user, "delete", "batch", batch_id,
          {"batch_name": batch["batch_name"], "deleted_records": deleted_records})
    return {"deleted_records": deleted_records, "batch_name": batch["batch_name"]}


def get_batch_detail(conn: sqlite3.Connection, batch_id: int) -> dict[str, Any]:
    batch = get_batch(conn, batch_id)
    records = fetch_all(
        conn,
        "SELECT * FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC",
        (batch_id,),
    )
    for record in records:
        dishes = record.get("inoculum_dishes") or 0
        record["per_dish_cells"] = (
            round((record.get("inoculum_cells") or 0) / dishes, 2) if dishes else 0
        )
    line = fetch_one(conn, "SELECT * FROM cell_lines WHERE id = ?", (batch["cell_line_id"],))
    vials = fetch_all(
        conn, "SELECT * FROM frozen_vials WHERE batch_id = ? ORDER BY location", (batch_id,)
    )
    cumulative = records[-1]["cumulative_pd"] if records else (batch.get("initial_pd") or 0.0)
    return {
        "batch": batch,
        "cell_line": line,
        "records": records,
        "vials": vials,
        "summary": {
            "records_count": len(records),
            "cumulative_pd": cumulative,
            "current_record": batch.get("current_record"),
        },
    }


def recalc_all(conn: sqlite3.Connection, user: str | None = None) -> dict[str, Any]:
    batches = conn.execute("SELECT id FROM culture_batches ORDER BY id").fetchall()
    fixed = 0
    problems = 0
    for row in batches:
        if recalculate_batch(conn, int(row["id"])) is not None:
            fixed += 1
        if refresh_active_record(conn, int(row["id"])) is None and conn.execute(
            "SELECT is_active FROM culture_batches WHERE id = ?", (int(row["id"]),)
        ).fetchone()["is_active"]:
            problems += 1
    audit(conn, user, "recalculate", "batch", None, {"batches": fixed})
    return {"batches": fixed, "active_record_problems": problems}
