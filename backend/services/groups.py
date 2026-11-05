"""细胞组服务。"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..domain import END_REASONS, normalize_choice, normalize_text, remaining_days
from ..errors import Conflict, NotFound, ValidationError
from . import audit, fetch_all, fetch_one, get_or_404, placeholders, require_non_empty
from .batches import create_batch, terminate_batch


def list_groups(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    groups = fetch_all(conn, "SELECT * FROM cell_groups ORDER BY group_name")
    if not groups:
        return groups
    members = fetch_all(
        conn,
        "SELECT gm.group_id, gm.cell_line_id, gm.sort_order, cl.name, cl.type, "
        "  (SELECT COUNT(*) FROM culture_batches b WHERE b.cell_line_id = cl.id AND b.is_active = 1) AS active_batch_count "
        "FROM cell_group_members gm JOIN cell_lines cl ON cl.id = gm.cell_line_id "
        "ORDER BY gm.group_id, gm.sort_order, cl.name",
    )
    by_group: dict[int, list[dict[str, Any]]] = {}
    for member in members:
        by_group.setdefault(int(member["group_id"]), []).append({
            "cell_line_id": int(member["cell_line_id"]),
            "name": member["name"],
            "type": member["type"],
            "sort_order": int(member["sort_order"] or 0),
            "active_batch_count": int(member["active_batch_count"] or 0),
        })
    for group in groups:
        group["members"] = by_group.get(int(group["id"]), [])
        group["member_count"] = len(group["members"])
    return groups


def get_group(conn: sqlite3.Connection, group_id: int) -> dict[str, Any]:
    group = get_or_404(conn, "cell_groups", group_id, "细胞组")
    group["members"] = fetch_all(
        conn,
        "SELECT gm.cell_line_id, gm.sort_order, cl.name, cl.type FROM cell_group_members gm "
        "JOIN cell_lines cl ON cl.id = gm.cell_line_id WHERE gm.group_id = ? "
        "ORDER BY gm.sort_order, cl.name",
        (group_id,),
    )
    group["member_count"] = len(group["members"])
    return group


def create_group(conn: sqlite3.Connection, payload: dict[str, Any],
                 user: str | None = None) -> dict[str, Any]:
    name = require_non_empty(payload.get("group_name"), "组名")
    notes = normalize_text(payload.get("notes"))
    if conn.execute("SELECT id FROM cell_groups WHERE group_name = ?", (name,)).fetchone():
        raise Conflict(f"细胞组「{name}」已存在")
    cursor = conn.execute("INSERT INTO cell_groups (group_name, notes) VALUES (?,?)", (name, notes))
    group_id = int(cursor.lastrowid)
    member_ids = payload.get("cell_line_ids") or []
    if member_ids:
        set_members(conn, group_id, [int(value) for value in member_ids], user=user)
    audit(conn, user, "create", "group", group_id, {"group_name": name})
    return get_group(conn, group_id)


def update_group(conn: sqlite3.Connection, group_id: int, payload: dict[str, Any],
                 user: str | None = None) -> dict[str, Any]:
    get_or_404(conn, "cell_groups", group_id, "细胞组")
    assignments: dict[str, Any] = {}
    if "group_name" in payload:
        name = require_non_empty(payload.get("group_name"), "组名")
        clash = conn.execute(
            "SELECT id FROM cell_groups WHERE group_name = ? AND id <> ?", (name, group_id)
        ).fetchone()
        if clash:
            raise Conflict(f"细胞组「{name}」已存在")
        assignments["group_name"] = name
    if "notes" in payload:
        assignments["notes"] = normalize_text(payload.get("notes"))
    if assignments:
        clause = ", ".join(f"{key} = ?" for key in assignments)
        conn.execute(f"UPDATE cell_groups SET {clause} WHERE id = ?", (*assignments.values(), group_id))
        audit(conn, user, "update", "group", group_id, {"fields": list(assignments)})
    return get_group(conn, group_id)


def delete_group(conn: sqlite3.Connection, group_id: int, user: str | None = None) -> dict[str, Any]:
    group = get_or_404(conn, "cell_groups", group_id, "细胞组")
    conn.execute("DELETE FROM cell_group_members WHERE group_id = ?", (group_id,))
    conn.execute("DELETE FROM cell_groups WHERE id = ?", (group_id,))
    audit(conn, user, "delete", "group", group_id, {"group_name": group["group_name"]})
    return {"deleted": group_id}


def set_members(conn: sqlite3.Connection, group_id: int, members: list[Any],
                user: str | None = None) -> dict[str, Any]:
    """整体替换组成员，列表顺序即展示顺序。"""
    get_or_404(conn, "cell_groups", group_id, "细胞组")
    if not isinstance(members, list):
        raise ValidationError("members 必须是数组")

    normalized: list[int] = []
    for item in members:
        if isinstance(item, dict):
            raw = item.get("cell_line_id", item.get("id"))
        else:
            raw = item
        try:
            line_id = int(raw)
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"无效的细胞株 id：{raw!r}") from exc
        if line_id not in normalized:
            normalized.append(line_id)

    if normalized:
        found = conn.execute(
            f"SELECT id FROM cell_lines WHERE id IN ({placeholders(normalized)})", tuple(normalized)
        ).fetchall()
        missing = set(normalized) - {int(row["id"]) for row in found}
        if missing:
            raise ValidationError(f"细胞株不存在：{sorted(missing)}")

    conn.execute("DELETE FROM cell_group_members WHERE group_id = ?", (group_id,))
    for index, line_id in enumerate(normalized, start=1):
        conn.execute(
            "INSERT INTO cell_group_members (group_id, cell_line_id, sort_order) VALUES (?,?,?)",
            (group_id, line_id, index),
        )
    audit(conn, user, "set_members", "group", group_id, {"member_ids": normalized})
    return get_group(conn, group_id)


def group_status(conn: sqlite3.Connection, group_id: int) -> list[dict[str, Any]]:
    group = get_group(conn, group_id)
    member_ids = [int(member["cell_line_id"]) for member in group["members"]]
    if not member_ids:
        return []
    rows = fetch_all(
        conn,
        f"""
        SELECT cb.id AS batch_id, cb.batch_name, cb.revival_date, cb.initial_pd,
               cl.id AS cell_line_id, cl.name AS cell_name, cl.type, cl.default_passage_interval,
               gm.sort_order,
               cr.id AS record_id, cr.passage, cr.date AS last_passage,
               cr.inoculum_cells, cr.inoculum_dishes, cr.harvested_cells,
               cr.pd, cr.cumulative_pd, cr.status, cr.next_passage_date, cr.notes
        FROM culture_batches cb
        JOIN cell_lines cl ON cl.id = cb.cell_line_id
        LEFT JOIN cell_group_members gm ON gm.group_id = ? AND gm.cell_line_id = cb.cell_line_id
        LEFT JOIN culture_records cr ON cr.id = (
            SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
            ORDER BY r.date DESC, r.id DESC LIMIT 1
        )
        WHERE cb.is_active = 1 AND cb.cell_line_id IN ({placeholders(member_ids)})
        ORDER BY COALESCE(gm.sort_order, 9999), cl.name, cb.batch_name, cb.id
        """,
        (group_id, *member_ids),
    )
    for row in rows:
        row["remaining_days"] = remaining_days(row.get("next_passage_date"))
        row["cumulative_pd"] = row.get("cumulative_pd") if row.get("cumulative_pd") is not None else row.get("initial_pd")
    return rows


def group_records(conn: sqlite3.Connection, group_id: int) -> list[dict[str, Any]]:
    """组内所有活跃批次的全部传代记录（用于批量编辑）。"""
    group = get_group(conn, group_id)
    member_ids = [int(member["cell_line_id"]) for member in group["members"]]
    if not member_ids:
        return []
    rows = fetch_all(
        conn,
        f"""
        SELECT cr.*, cb.batch_name, cb.initial_pd, cb.initial_cell_count,
               cl.name AS cell_line, cl.type AS cell_type
        FROM culture_records cr
        JOIN culture_batches cb ON cb.id = cr.batch_id
        JOIN cell_lines cl ON cl.id = cb.cell_line_id
        WHERE cb.is_active = 1 AND cb.cell_line_id IN ({placeholders(member_ids)})
        ORDER BY cl.name, cb.batch_name, cr.date, cr.id
        """,
        tuple(member_ids),
    )
    for row in rows:
        dishes = row.get("inoculum_dishes") or 0
        row["per_dish_cells"] = round((row.get("inoculum_cells") or 0) / dishes, 2) if dishes else 0
    return rows


def group_create_batches(conn: sqlite3.Connection, group_id: int, payload: dict[str, Any],                         user: str | None = None) -> dict[str, Any]:
    group = get_group(conn, group_id)
    if not group["members"]:
        raise ValidationError("该细胞组还没有成员")
    created: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for member in group["members"]:
        line_id = int(member["cell_line_id"])
        try:
            batch = create_batch(conn, {**payload, "cell_line_id": line_id}, user=user)
            created.append({"cell_line_id": line_id, "batch_id": batch["id"],
                            "batch_name": batch["batch_name"]})
        except Exception as exc:  # noqa: BLE001
            errors.append({"cell_line_id": line_id, "name": member["name"],
                           "error": getattr(exc, "message", str(exc))})
    audit(conn, user, "create_bulk", "batch", None,
          {"group_id": group_id, "created": len(created), "failed": len(errors)})
    return {"created": created, "errors": errors, "group": group["group_name"]}


def group_terminate(conn: sqlite3.Connection, group_id: int, reason: str | None,
                    user: str | None = None) -> dict[str, Any]:
    group = get_group(conn, group_id)
    reason_value = normalize_choice(reason, END_REASONS, "终止原因", default="其他")
    member_ids = [int(member["cell_line_id"]) for member in group["members"]]
    if not member_ids:
        raise ValidationError("该细胞组还没有成员")
    rows = conn.execute(
        f"SELECT id FROM culture_batches WHERE is_active = 1 AND cell_line_id IN ({placeholders(member_ids)})",
        tuple(member_ids),
    ).fetchall()
    terminated: list[int] = []
    for row in rows:
        try:
            terminate_batch(conn, int(row["id"]), reason_value, user=user)
            terminated.append(int(row["id"]))
        except Conflict:
            continue
    audit(conn, user, "terminate_bulk", "batch", None,
          {"group_id": group_id, "reason": reason_value, "count": len(terminated)})
    return {"terminated": terminated, "count": len(terminated), "reason": reason_value}


def get_group_or_404(conn: sqlite3.Connection, group_id: int) -> dict[str, Any]:
    row = fetch_one(conn, "SELECT * FROM cell_groups WHERE id = ?", (group_id,))
    if row is None:
        raise NotFound(f"细胞组不存在（id={group_id}）")
    return row
