"""看板统计、增殖速率与生长曲线数据。"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Any

from ..domain import remaining_days
from ..errors import ValidationError
from . import fetch_all, get_or_404, placeholders


def dashboard(conn: sqlite3.Connection) -> dict[str, Any]:
    today = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()

    def scalar(sql: str, params: tuple[Any, ...] = ()) -> int:
        return int(conn.execute(sql, params).fetchone()[0] or 0)

    active_batches = scalar("SELECT COUNT(*) FROM culture_batches WHERE is_active = 1")
    active_lines = scalar(
        "SELECT COUNT(DISTINCT cell_line_id) FROM culture_batches WHERE is_active = 1"
    )
    total_lines = scalar("SELECT COUNT(*) FROM cell_lines")
    total_groups = scalar("SELECT COUNT(*) FROM cell_groups")
    total_vials = scalar("SELECT COUNT(*) FROM frozen_vials")
    in_stock_vials = scalar("SELECT COUNT(*) FROM frozen_vials WHERE status = '在库'")
    total_records = scalar("SELECT COUNT(*) FROM culture_records")
    recent_records = scalar(
        "SELECT COUNT(*) FROM culture_records WHERE date >= ?", (week_ago,)
    )

    due_rows = fetch_all(
        conn,
        """
        SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, cl.id AS cell_line_id,
               cr.next_passage_date, cr.passage, cr.status, cr.cumulative_pd
        FROM culture_batches cb
        JOIN cell_lines cl ON cl.id = cb.cell_line_id
        JOIN culture_records cr ON cr.id = (
            SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
            ORDER BY r.date DESC, r.id DESC LIMIT 1
        )
        WHERE cb.is_active = 1 AND cr.next_passage_date IS NOT NULL AND cr.next_passage_date <> ''
        ORDER BY cr.next_passage_date
        """,
    )
    for row in due_rows:
        row["remaining_days"] = remaining_days(row["next_passage_date"], today)
    due_soon = [row for row in due_rows if row["remaining_days"] is not None and row["remaining_days"] <= 3]

    recent = fetch_all(
        conn,
        """
        SELECT cr.id, cr.date, cr.passage, cr.pd, cr.cumulative_pd, cr.harvested_cells,
               cr.inoculum_cells, cr.inoculum_dishes, cr.status, cr.notes,
               cb.id AS batch_id, cb.batch_name, cl.name AS cell_line
        FROM culture_records cr
        JOIN culture_batches cb ON cb.id = cr.batch_id
        JOIN cell_lines cl ON cl.id = cb.cell_line_id
        ORDER BY cr.date DESC, cr.id DESC LIMIT 10
        """,
    )

    month_start = (today.replace(day=1) - timedelta(days=150)).replace(day=1).isoformat()
    monthly = fetch_all(
        conn,
        """
        SELECT substr(date, 1, 7) AS month, COUNT(*) AS count
        FROM culture_records WHERE date >= ?
        GROUP BY month ORDER BY month
        """,
        (month_start,),
    )

    return {
        "stats": {
            "active_cell_lines": active_lines,
            "active_batches": active_batches,
            "total_cell_lines": total_lines,
            "total_groups": total_groups,
            "total_vials": total_vials,
            "in_stock_vials": in_stock_vials,
            "total_records": total_records,
            "records_last_7_days": recent_records,
        },
        "due_soon": due_soon,
        "all_due": due_rows,
        "recent_records": recent,
        "records_by_month": monthly,
        "today": today.isoformat(),
    }


def _active_member_ids(conn: sqlite3.Connection, group_id: int) -> list[int]:
    get_or_404(conn, "cell_groups", group_id, "细胞组")
    return [
        int(row["cell_line_id"])
        for row in conn.execute(
            "SELECT cell_line_id FROM cell_group_members WHERE group_id = ? ORDER BY sort_order, cell_line_id",
            (group_id,),
        ).fetchall()
    ]


def group_rates(conn: sqlite3.Connection, group_id: int) -> list[dict[str, Any]]:
    """组内每个活跃批次的增殖速度，用于比较不同细胞株的快慢。

    主要指标是「整段 PD/天」：首末两条记录之间的累计 PD ÷ 跨度天数，
    单次计数误差会被平均掉，最适合判断两株细胞增殖速度是否有差异。
    同时给出平均 PD/天（各区间算术平均）、对应倍增时间、区间数与稳定度。
    """
    member_ids = _active_member_ids(conn, group_id)
    if not member_ids:
        return []
    batches = fetch_all(
        conn,
        f"""
        SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, cl.id AS cell_line_id,
               gm.sort_order
        FROM culture_batches cb
        JOIN cell_lines cl ON cl.id = cb.cell_line_id
        LEFT JOIN cell_group_members gm ON gm.group_id = ? AND gm.cell_line_id = cb.cell_line_id
        WHERE cb.is_active = 1 AND cb.cell_line_id IN ({placeholders(member_ids)})
        ORDER BY COALESCE(gm.sort_order, 9999), cl.name, cb.batch_name
        """,
        (group_id, *member_ids),
    )
    results: list[dict[str, Any]] = []
    for batch in batches:
        records = fetch_all(
            conn,
            "SELECT date, pd, cumulative_pd FROM culture_records WHERE batch_id = ? "
            "ORDER BY date ASC, id ASC",
            (batch["batch_id"],),
        )
        samples: list[dict[str, Any]] = []
        previous_date: date | None = None
        for record in records:
            current_date = date.fromisoformat(record["date"]) if record["date"] else None
            if previous_date is not None and current_date is not None:
                interval = (current_date - previous_date).days
                pd_value = record["pd"]
                if interval > 0 and pd_value is not None:
                    samples.append({
                        "date": record["date"],
                        "interval_days": interval,
                        "pd": float(pd_value),
                        "pd_per_day": round(float(pd_value) / interval, 4),
                    })
            if current_date is not None:
                previous_date = current_date

        first = records[0] if records else None
        last = records[-1] if records else None
        span = 0
        overall = None
        if first and last and first["date"] and last["date"]:
            span = (date.fromisoformat(last["date"]) - date.fromisoformat(first["date"])).days
            if span > 0:
                delta = float(last["cumulative_pd"] or 0) - float(first["cumulative_pd"] or 0)
                overall = round(delta / span, 4)

        average = (
            round(sum(sample["pd_per_day"] for sample in samples) / len(samples), 4)
            if samples else None
        )
        values = [sample["pd_per_day"] for sample in samples]
        mean = sum(values) / len(values) if values else 0.0
        # 稳定度：各区间 PD/天 的变异系数，越小说明越平稳、越可信
        cv = None
        if len(values) >= 2 and mean:
            variance = sum((value - mean) ** 2 for value in values) / len(values)
            cv = round((variance ** 0.5) / abs(mean), 3)

        results.append({
            **batch,
            "overall_pd_per_day": overall,
            "overall_doubling_hours": (
                round(24 / overall, 2) if overall is not None and overall > 0 else None
            ),
            "avg_pd_per_day": average,
            "avg_doubling_hours": (
                round(24 / average, 2) if average is not None and average > 0 else None
            ),
            "interval_count": len(samples),
            "span_days": span,
            "first_date": first["date"] if first else None,
            "last_date": last["date"] if last else None,
            "cumulative_pd": float(last["cumulative_pd"] or 0) if last else None,
            "cv": cv,
            "samples": samples[-3:],
        })
    return results


def compare_curves(
    conn: sqlite3.Connection,
    line_ids: list[int],
    *,
    batch_ids: list[int] | None = None,
    include_ended: bool = False,
    normalize: bool = False,
    start_date: str | None = None,
    basis: str = "date",
) -> dict[str, Any]:
    """任选细胞株的生长曲线对比。

    - line_ids：要对比的细胞株，按传入顺序排列
    - batch_ids：可只取指定批次；为空时取这些细胞株的批次（默认仅活跃批次）
    - normalize：以各批次在 start_date 的累计 PD 为基准做归一化，便于比较增殖快慢
    - basis：date 按日期对齐；elapsed 按「距批次首条记录的天数」对齐

    每个点同时给出：
    - pd_per_day：本次 PD ÷ 距上一条记录的天数
    - doubling_hours：倍增时间 = 24 ÷ PD/天
    批次级再给出平均 PD/天、平均倍增时间，以及整段时间的累计 PD/天。
    """
    if not line_ids:
        return {"series": [], "dates": [], "skipped": [],
                "normalize": normalize, "start_date": start_date, "basis": basis}
    if normalize and not start_date:
        raise ValidationError("标准化模式必须提供起始日期")
    if basis not in ("date", "elapsed"):
        raise ValidationError("basis 必须是 date 或 elapsed")

    rows = fetch_all(
        conn,
        f"""
        SELECT cb.id AS batch_id, cb.batch_name, cb.revival_date, cb.is_active,
               cl.id AS cell_line_id, cl.name AS cell_line
        FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
        WHERE cl.id IN ({placeholders(line_ids)})
        ORDER BY cl.name, cb.revival_date DESC, cb.id DESC
        """,
        tuple(line_ids),
    )
    wanted = {int(value) for value in (batch_ids or [])}
    if wanted:
        candidates = [row for row in rows if int(row["batch_id"]) in wanted]
    else:
        candidates = [row for row in rows if include_ended or int(row["is_active"])]

    order = {int(line_id): index for index, line_id in enumerate(line_ids)}
    candidates.sort(key=lambda row: (order.get(int(row["cell_line_id"]), 9999),
                                     row["revival_date"] or "", row["batch_id"]))

    series: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    all_dates: set[str] = set()

    for batch in candidates:
        records = fetch_all(
            conn,
            "SELECT date, passage, pd, cumulative_pd, harvested_cells FROM culture_records "
            "WHERE batch_id = ? ORDER BY date ASC, id ASC",
            (batch["batch_id"],),
        )
        if not records:
            skipped.append({"batch_id": batch["batch_id"], "name": batch["batch_name"],
                            "reason": "没有传代记录"})
            continue
        for record in records:
            all_dates.add(record["date"])

        first_date = date.fromisoformat(records[0]["date"])
        points = []
        previous: dict[str, Any] | None = None
        for record in records:
            record_date = date.fromisoformat(record["date"])
            day = (record_date - first_date).days
            interval = (record_date - date.fromisoformat(previous["date"])).days if previous else None
            single_pd = float(record["pd"] or 0)
            # 本次 PD / 间隔天数；首次记录没有「上一次接种」，无法计算
            pd_per_day = (
                round(single_pd / interval, 4)
                if previous is not None and interval and interval > 0
                else None
            )
            # 倍增时间（小时）= 24 / (PD/天)；PD/天 为 0 或负数时不计算
            doubling_hours = (
                round(24 / pd_per_day, 2) if pd_per_day is not None and pd_per_day > 0 else None
            )
            points.append({
                "date": record["date"],
                "day": day,
                "interval_days": interval,
                "passage": record["passage"],
                "value": record["cumulative_pd"],
                "cumulative_pd": record["cumulative_pd"],
                "pd": record["pd"],
                "pd_per_day": pd_per_day,
                "doubling_hours": doubling_hours,
                "harvested_cells": record["harvested_cells"],
            })
            previous = record

        if normalize:
            exact = next((point for point in points if point["date"] == start_date), None)
            if exact is None:
                skipped.append({"batch_id": batch["batch_id"], "name": batch["batch_name"],
                                "reason": f"{start_date} 当天没有记录"})
                continue
            base = float(exact["cumulative_pd"] or 0)
            if base == 0:
                skipped.append({"batch_id": batch["batch_id"], "name": batch["batch_name"],
                                "reason": "起始累计 PD 为 0，无法标准化"})
                continue
            points = [point for point in points if point["date"] >= start_date]
            for point in points:
                point["value"] = round(float(point["cumulative_pd"]) / base, 3)

        # 批次级汇总：整段时间的平均 PD/天 与平均倍增时间
        rates = [point["pd_per_day"] for point in points if point["pd_per_day"] is not None]
        span = points[-1]["day"] - points[0]["day"] if len(points) > 1 else 0
        avg_pd_per_day = round(sum(rates) / len(rates), 4) if rates else None
        if span > 0 and points:
            overall = (float(points[-1]["cumulative_pd"] or 0) - float(points[0]["cumulative_pd"] or 0)) / span
        else:
            overall = None

        series.append({
            "batch_id": batch["batch_id"],
            "batch_name": batch["batch_name"],
            "cell_line": batch["cell_line"],
            "cell_line_id": batch["cell_line_id"],
            "ended": not bool(batch["is_active"]),
            "name": batch["batch_name"],
            "points": points,
            "avg_pd_per_day": avg_pd_per_day,
            "avg_doubling_hours": (
                round(24 / avg_pd_per_day, 2)
                if avg_pd_per_day is not None and avg_pd_per_day > 0
                else None
            ),
            "overall_pd_per_day": round(overall, 4) if overall is not None else None,
            "overall_doubling_hours": (
                round(24 / overall, 2) if overall is not None and overall > 0 else None
            ),
        })

    return {
        "series": series,
        "dates": sorted(all_dates),
        "normalize": normalize,
        "start_date": start_date,
        "basis": basis,
        "skipped": skipped,
    }


def group_curves(
    conn: sqlite3.Connection,
    group_id: int,
    *,
    normalize: bool = False,
    start_date: str | None = None,
    ended_ids: list[int] | None = None,
) -> dict[str, Any]:
    """组内生长曲线：活跃批次 + 指定已终止批次；可选按起始日期标准化。"""
    member_ids = _active_member_ids(conn, group_id)
    if not member_ids:
        return {"series": [], "dates": [], "normalize": normalize, "start_date": start_date,
                "ended_batches": [], "skipped": []}

    active_batches = fetch_all(
        conn,
        f"""
        SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, 0 AS ended
        FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
        WHERE cb.is_active = 1 AND cb.cell_line_id IN ({placeholders(member_ids)})
        ORDER BY cl.name, cb.batch_name, cb.id
        """,
        tuple(member_ids),
    )
    ended_batches = fetch_all(
        conn,
        f"""
        SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, 1 AS ended
        FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
        WHERE cb.is_active = 0 AND cb.cell_line_id IN ({placeholders(member_ids)})
        ORDER BY cl.name, cb.batch_name, cb.id
        """,
        tuple(member_ids),
    )
    ended_lookup = {int(row["batch_id"]): row for row in ended_batches}

    selected_ended: list[dict[str, Any]] = []
    for raw_id in ended_ids or []:
        try:
            batch_id = int(raw_id)
        except (TypeError, ValueError):
            continue
        if batch_id in ended_lookup:
            selected_ended.append(ended_lookup[batch_id])

    all_batches = active_batches + selected_ended
    series: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    all_dates: set[str] = set()

    for batch in all_batches:
        records = fetch_all(
            conn,
            "SELECT date, pd, cumulative_pd, harvested_cells, passage FROM culture_records "
            "WHERE batch_id = ? ORDER BY date ASC, id ASC",
            (batch["batch_id"],),
        )
        if not records:
            skipped.append({"batch_id": batch["batch_id"], "reason": "没有传代记录"})
            continue
        for record in records:
            all_dates.add(record["date"])

        name = batch["batch_name"]
        points = [
            {
                "date": record["date"],
                "passage": record["passage"],
                "value": record["cumulative_pd"],
                "cumulative_pd": record["cumulative_pd"],
                "pd": record["pd"],
                "harvested_cells": record["harvested_cells"],
            }
            for record in records
        ]

        if normalize:
            if not start_date:
                raise ValidationError("标准化模式必须提供起始日期")
            exact = next((record for record in records if record["date"] == start_date), None)
            if exact is None:
                skipped.append({"batch_id": batch["batch_id"], "reason": f"{start_date} 当天没有记录"})
                continue
            base = float(exact["cumulative_pd"] or 0)
            if base == 0:
                skipped.append({"batch_id": batch["batch_id"], "reason": "起始累计 PD 为 0，无法标准化"})
                continue
            points = [
                point for point in points if point["date"] >= start_date
            ]
            for point in points:
                point["value"] = round(float(point["cumulative_pd"]) / base, 3)

        series.append({
            "batch_id": batch["batch_id"],
            "batch_name": batch["batch_name"],
            "cell_line": batch["cell_line"],
            "name": name,
            "ended": bool(batch["ended"]),
            "points": points,
        })

    return {
        "series": series,
        "dates": sorted(all_dates),
        "normalize": normalize,
        "start_date": start_date,
        "ended_batches": [
            {"batch_id": row["batch_id"], "batch_name": row["batch_name"], "cell_line": row["cell_line"]}
            for row in ended_batches
        ],
        "skipped": skipped,
    }
