"""REST API 路由。"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import date
from functools import wraps
from typing import Any, Callable, Iterator

from flask import Blueprint, current_app, g, jsonify, request, send_file

from . import db
from .auth import current_username
from .config import Config
from .domain import END_REASONS
from .errors import ApiError, NotFound, ValidationError
from .services import (
    analytics,
    batches,
    excelio,
    experiments,
    groups,
    lines,
    maintenance,
    records,
    todos,
    topics,
    vials,
)

api_bp = Blueprint("api", __name__, url_prefix="/api")

# SQLite 写入串行化：并发请求排队，避免多人同时写导致 database is locked
WRITE_LOCK = threading.RLock()


# --------------------------------------------------------------------------
# 基础设施
# --------------------------------------------------------------------------
def get_config() -> Config:
    return current_app.config["CELLTRACKER_CONFIG"]


def get_db() -> sqlite3.Connection:
    if getattr(g, "db", None) is None:
        g.db = db.connect(get_config().db_path)
    return g.db


def close_request_db() -> None:
    conn = getattr(g, "db", None)
    if conn is not None:
        try:
            conn.close()
        except sqlite3.Error:
            pass
        g.db = None


def body() -> dict[str, Any]:
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ValidationError("请求体必须是 JSON 对象")
    return data


def user() -> str | None:
    return current_username()


def write(view: Callable) -> Callable:
    """串行写 + 事务提交/回滚。"""

    @wraps(view)
    def wrapper(*args, **kwargs):
        with WRITE_LOCK:
            conn = get_db()
            try:
                result = view(*args, **kwargs)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    return wrapper


@contextmanager
def exclusive_runtime() -> Iterator[None]:
    """替换数据库文件时使用：持有写锁并关闭当前请求连接。"""
    with WRITE_LOCK:
        close_request_db()
        yield


def _int_arg(name: str, default: int | None = None) -> int | None:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValidationError(f"参数 {name} 必须是整数") from exc


def _bool_arg(name: str, default: bool = False) -> bool:
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    return str(raw).lower() in ("1", "true", "yes", "on")


# --------------------------------------------------------------------------
# 元信息
# --------------------------------------------------------------------------
@api_bp.get("/healthz")
def healthz():
    return jsonify({"ok": True})


@api_bp.get("/meta")
def meta():
    config = get_config()
    conn = get_db()
    counts = db.table_counts(conn)
    report = maintenance.read_migration_report(config)
    return jsonify({
        **config.to_public_dict(),
        "counts": counts,
        "auth": {
            "enabled": config.auth_enabled,
            "username": current_username(),
        },
        "migration": _migration_summary(report),
        "backup_count": len(maintenance.list_backups(config)),
        "today": date.today().isoformat(),
        "species_colors": species_palette(conn),
    })


def species_palette(conn) -> dict[str, Any]:
    """物种 → 色系，以及每个细胞株的固定颜色，供前端图例与图表统一取色。"""
    from .services.palette import line_colors

    colors = line_colors(conn)
    species: dict[str, dict[str, Any]] = {}
    for info in colors.values():
        name = info["species"] or ""
        entry = species.setdefault(name, {"species": name, "color": info["color"], "count": 0})
        entry["count"] += 1
    return {
        "species": sorted(
            species.values(), key=lambda value: (value["species"] == "", value["species"])
        ),
        "lines": [
            {"cell_line_id": line_id, "species": info["species"], "color": info["color"]}
            for line_id, info in sorted(colors.items())
        ],
    }


def session_username(config: Config) -> str | None:
    from flask import session

    if not config.auth_enabled:
        return "local"
    return session.get("username")


def _migration_summary(report: dict[str, Any] | None) -> dict[str, Any] | None:
    if not report:
        return None
    return {
        "status": report.get("status"),
        "source": report.get("source"),
        "generated_at": report.get("generated_at"),
        "counts": report.get("target_counts"),
        "pd_mismatch_count": (report.get("pd_audit") or {}).get("mismatch_count"),
        "checksums_equal": report.get("checksums_equal"),
        "report_path": report.get("report_path"),
    }


# --------------------------------------------------------------------------
# 细胞株
# --------------------------------------------------------------------------
@api_bp.get("/cell-lines")
def list_cell_lines():
    return jsonify(lines.list_lines(get_db(), search=request.args.get("search")))


@api_bp.post("/cell-lines")
@write
def create_cell_line():
    return jsonify(lines.create_line(get_db(), body(), user=user())), 201


@api_bp.get("/cell-lines/<int:line_id>")
def get_cell_line(line_id: int):
    conn = get_db()
    return jsonify({
        "cell_line": lines.get_line_summary(conn, line_id),
        "batches": lines.line_batches(conn, line_id, include_ended=_bool_arg("include_ended", True)),
        "vials": lines.line_vials(conn, line_id),
    })


@api_bp.patch("/cell-lines/<int:line_id>")
@write
def update_cell_line(line_id: int):
    return jsonify(lines.update_line(get_db(), line_id, body(), user=user()))


@api_bp.delete("/cell-lines/<int:line_id>")
@write
def delete_cell_line(line_id: int):
    return jsonify(lines.delete_line(get_db(), line_id, user=user()))


@api_bp.post("/cell-lines/species")
@write
def assign_cell_line_species():
    """批量写物种。

    - entries: [{id, species}] 逐行写入（界面预览后确认用）
    - 兼容旧用法：{species, line_ids?, only_unset?} 给一批细胞株统一打同一标签
    """
    payload = body()
    conn = get_db()
    entries = payload.get("entries")
    if isinstance(entries, list):
        updated = 0
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            line_id = entry.get("id", entry.get("cell_line_id"))
            try:
                line_id = int(line_id)
            except (TypeError, ValueError):
                continue
            lines.update_line(conn, line_id, {"species": entry.get("species", "")}, user=user())
            updated += 1
        return jsonify({"updated": updated, "entries": updated})

    raw_ids = payload.get("line_ids") or []
    if not isinstance(raw_ids, list):
        raise ValidationError("line_ids 必须是数组")
    line_ids = [int(value) for value in raw_ids] if raw_ids else None
    return jsonify(maintenance.assign_species(
        conn,
        payload.get("species"),
        line_ids=line_ids,
        only_unset=bool(payload.get("only_unset", True)),
        user=user(),
    ))


@api_bp.get("/cell-lines/<int:line_id>/batches")
def list_line_batches(line_id: int):
    return jsonify(lines.line_batches(get_db(), line_id, include_ended=_bool_arg("include_ended", True)))


@api_bp.get("/cell-lines/<int:line_id>/vials")
def list_line_vials(line_id: int):
    return jsonify(lines.line_vials(get_db(), line_id))


# --------------------------------------------------------------------------
# 培养批次
# --------------------------------------------------------------------------
@api_bp.get("/batches")
def list_batches():
    conn = get_db()
    active_raw = request.args.get("is_active")
    active = None if active_raw in (None, "") else str(active_raw).lower() in ("1", "true", "yes")
    return jsonify(batches.list_batches(
        conn,
        cell_line_id=_int_arg("cell_line_id"),
        active=active,
        q=request.args.get("q"),
    ))


@api_bp.post("/batches")
@write
def create_batch():
    return jsonify(batches.create_batch(get_db(), body(), user=user())), 201


@api_bp.get("/batches/<int:batch_id>")
def get_batch(batch_id: int):
    return jsonify(batches.get_batch_detail(get_db(), batch_id))


@api_bp.patch("/batches/<int:batch_id>")
@write
def update_batch(batch_id: int):
    return jsonify(batches.update_batch(get_db(), batch_id, body(), user=user()))


@api_bp.delete("/batches/<int:batch_id>")
@write
def delete_batch(batch_id: int):
    return jsonify(batches.delete_batch(get_db(), batch_id, user=user()))


@api_bp.post("/batches/<int:batch_id>/terminate")
@write
def terminate_batch(batch_id: int):
    payload = request.get_json(silent=True) or {}
    reason = payload.get("reason", "其他")
    return jsonify(batches.terminate_batch(get_db(), batch_id, reason, user=user()))


@api_bp.post("/batches/<int:batch_id>/restore")
@write
def restore_batch(batch_id: int):
    return jsonify(batches.restore_batch(get_db(), batch_id, user=user()))


@api_bp.get("/batches/<int:batch_id>/records")
def list_batch_records(batch_id: int):
    return jsonify(records.list_records(get_db(), batch_id))


@api_bp.get("/batches/<int:batch_id>/records.csv")
def download_batch_csv(batch_id: int):
    content, filename = excelio.batch_records_csv(get_db(), batch_id)
    from io import BytesIO

    return send_file(
        BytesIO(content),
        mimetype="text/csv",
        as_attachment=True,
        download_name=filename,
    )


# --------------------------------------------------------------------------
# 传代记录
# --------------------------------------------------------------------------
@api_bp.post("/records")
@write
def create_record():
    return jsonify(records.create_record(get_db(), body(), user=user())), 201


@api_bp.post("/records/bulk")
@write
def create_records_bulk():
    payload = body()
    entries = payload.get("entries")
    if entries is None and isinstance(payload.get("records"), list):
        entries = payload["records"]
    if not isinstance(entries, list):
        raise ValidationError("entries 必须是数组")
    return jsonify(records.bulk_create(get_db(), entries, user=user()))


@api_bp.post("/records/bulk-update")
@write
def update_records_bulk():
    payload = body()
    entries = payload.get("entries")
    if entries is None and isinstance(payload.get("records"), list):
        entries = payload["records"]
    if not isinstance(entries, list):
        raise ValidationError("entries 必须是数组")
    return jsonify(records.bulk_update(get_db(), entries, user=user()))


@api_bp.patch("/records/<int:record_id>")
@write
def update_record(record_id: int):
    return jsonify(records.update_record(get_db(), record_id, body(), user=user()))


@api_bp.delete("/records/<int:record_id>")
@write
def delete_record(record_id: int):
    return jsonify(records.delete_record(get_db(), record_id, user=user()))


# --------------------------------------------------------------------------
# 冻存管 / 冻存盒
# --------------------------------------------------------------------------
@api_bp.get("/vials")
def list_vials():
    return jsonify(vials.list_vials(
        get_db(),
        q=request.args.get("q"),
        cell_line_id=_int_arg("cell_line_id"),
        status=request.args.get("status"),
        limit=_int_arg("limit", 500) or 500,
        unplaced=_bool_arg("unplaced", False),
    ))


@api_bp.post("/vials")
@write
def create_vials():
    return jsonify(vials.create_vials(get_db(), body(), user=user())), 201


@api_bp.get("/vials/boxes")
def list_boxes():
    return jsonify(vials.list_boxes(get_db()))


@api_bp.get("/vials/boxes/detail")
def box_detail():
    box = request.args.get("box")
    if not box:
        raise ValidationError("缺少 box 参数")
    return jsonify(vials.box_detail(get_db(), box))


@api_bp.delete("/vials/boxes")
@write
def clear_box():
    box = request.args.get("box")
    if not box:
        raise ValidationError("缺少 box 参数")
    return jsonify(vials.clear_box(get_db(), box, user=user()))


@api_bp.patch("/vials/<int:vial_id>")
@write
def update_vial(vial_id: int):
    return jsonify(vials.update_vial(get_db(), vial_id, body(), user=user()))


@api_bp.delete("/vials/<int:vial_id>")
@write
def delete_vial(vial_id: int):
    return jsonify(vials.delete_vial(get_db(), vial_id, user=user()))


@api_bp.post("/vials/import")
@write
def import_vials():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        raise ValidationError("请上传 Excel 文件")
    mode = request.form.get("mode", "append")
    return jsonify(vials.import_from_workbook(get_db(), uploaded.stream, mode=mode, user=user()))


# --------------------------------------------------------------------------
# 细胞组
# --------------------------------------------------------------------------
@api_bp.get("/groups")
def list_groups():
    return jsonify(groups.list_groups(get_db()))


@api_bp.post("/groups")
@write
def create_group():
    return jsonify(groups.create_group(get_db(), body(), user=user())), 201


@api_bp.get("/groups/<int:group_id>")
def get_group(group_id: int):
    return jsonify(groups.get_group(get_db(), group_id))


@api_bp.patch("/groups/<int:group_id>")
@write
def update_group(group_id: int):
    return jsonify(groups.update_group(get_db(), group_id, body(), user=user()))


@api_bp.delete("/groups/<int:group_id>")
@write
def delete_group(group_id: int):
    return jsonify(groups.delete_group(get_db(), group_id, user=user()))


@api_bp.put("/groups/<int:group_id>/members")
@write
def set_group_members(group_id: int):
    payload = body()
    members = payload.get("members", payload.get("cell_line_ids"))
    if not isinstance(members, list):
        raise ValidationError("members 必须是数组")
    return jsonify(groups.set_members(get_db(), group_id, members, user=user()))


@api_bp.get("/groups/<int:group_id>/status")
def group_status(group_id: int):
    return jsonify(groups.group_status(get_db(), group_id))


@api_bp.get("/groups/<int:group_id>/records")
def group_records(group_id: int):
    return jsonify(groups.group_records(get_db(), group_id))


@api_bp.get("/groups/<int:group_id>/rates")
def group_rates(group_id: int):
    return jsonify(analytics.group_rates(
        get_db(),
        group_id,
        include_ended=_bool_arg("include_ended", False),
    ))


@api_bp.get("/groups/<int:group_id>/curves")
def group_curves(group_id: int):
    ended_raw = request.args.get("ended_ids", "")
    ended_ids = [int(part) for part in ended_raw.split(",") if part.strip().isdigit()]
    return jsonify(analytics.group_curves(
        get_db(),
        group_id,
        normalize=_bool_arg("normalize", False),
        start_date=request.args.get("start_date"),
        ended_ids=ended_ids,
    ))


@api_bp.post("/groups/<int:group_id>/batches")
@write
def group_create_batches(group_id: int):
    return jsonify(groups.group_create_batches(get_db(), group_id, body(), user=user())), 201


@api_bp.post("/groups/<int:group_id>/terminate")
@write
def group_terminate(group_id: int):
    payload = request.get_json(silent=True) or {}
    reasons = payload.get("reason")
    if reasons not in END_REASONS:
        reasons = "其他"
    return jsonify(groups.group_terminate(get_db(), group_id, reasons, user=user()))


@api_bp.get("/groups/<int:group_id>/export")
def export_group(group_id: int):
    conn = get_db()
    group = groups.get_group(conn, group_id)
    include_all = _bool_arg("include_all", True)
    stream = excelio.group_export(conn, group_id, include_all=include_all)
    return send_file(
        stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"细胞组数据_{group['group_name']}.xlsx",
    )


# --------------------------------------------------------------------------
# 看板与统计
# --------------------------------------------------------------------------
@api_bp.get("/dashboard")
def dashboard():
    return jsonify(analytics.dashboard(get_db()))


@api_bp.get("/compare/curves")
def compare_curves():
    raw_lines = request.args.get("line_ids", "")
    line_ids = [int(part) for part in raw_lines.split(",") if part.strip().isdigit()]
    if not line_ids:
        raise ValidationError("请至少选择一个细胞株")
    raw_batches = request.args.get("batch_ids", "")
    batch_ids = [int(part) for part in raw_batches.split(",") if part.strip().isdigit()]
    return jsonify(analytics.compare_curves(
        get_db(),
        line_ids,
        batch_ids=batch_ids or None,
        include_ended=_bool_arg("include_ended", False),
        normalize=_bool_arg("normalize", False),
        start_date=request.args.get("start_date"),
        basis=request.args.get("basis", "date"),
    ))


# --------------------------------------------------------------------------
# 培养实验（细胞实验日程提醒）
# --------------------------------------------------------------------------
@api_bp.get("/experiments")
def list_experiments():
    scope = request.args.get("scope") or None
    return jsonify(experiments.list_experiments(
        get_db(),
        status=request.args.get("status") or None,
        q=request.args.get("q"),
        scope=scope,
        with_checkpoints=_int_arg("with_checkpoints", 0) or 0,
    ))


@api_bp.post("/experiments")
@write
def create_experiment():
    return jsonify(experiments.create_experiment(get_db(), body(), user=user())), 201


@api_bp.get("/experiments/summary")
def experiment_summary():
    """首页卡片与提醒铃用的汇总：逾期 / 今天到点 / 即将到点。"""
    return jsonify(experiments.summary(get_db()))


@api_bp.get("/experiments/meta")
def experiment_meta():
    """实验模块的下拉选项：细胞状况、间隔单位等。"""
    return jsonify(experiments.choices())


@api_bp.get("/experiments/week")
def experiment_week():
    """周视图：start 为任意一天（默认本周一），返回 7 天的检查安排。"""
    return jsonify(experiments.week_view(get_db(), start=request.args.get("start")))


@api_bp.get("/experiments/month")
def experiment_month():
    """月视图：month 为 YYYY-MM（默认当月），返回整月的检查点与传代待办。"""
    return jsonify(experiments.month_view(get_db(), month=request.args.get("month")))


@api_bp.get("/experiments/<int:experiment_id>")
def get_experiment(experiment_id: int):
    return jsonify(experiments.get_experiment(get_db(), experiment_id))


@api_bp.patch("/experiments/<int:experiment_id>")
@write
def update_experiment(experiment_id: int):
    return jsonify(experiments.update_experiment(get_db(), experiment_id, body(), user=user()))


@api_bp.delete("/experiments/<int:experiment_id>")
@write
def delete_experiment(experiment_id: int):
    return jsonify(experiments.delete_experiment(get_db(), experiment_id, user=user()))


@api_bp.post("/experiments/<int:experiment_id>/checkpoints")
@write
def add_experiment_checkpoint(experiment_id: int):
    return jsonify(experiments.add_checkpoint(get_db(), experiment_id, body(), user=user())), 201


@api_bp.post("/experiments/<int:experiment_id>/complete")
@write
def complete_experiment_checkpoint(experiment_id: int):
    """勾选某个检查点完成，并自动推进到下一个检查时间。"""
    return jsonify(experiments.complete_checkpoint(get_db(), experiment_id, body(), user=user()))


@api_bp.post("/experiments/<int:experiment_id>/finish")
@write
def finish_experiment(experiment_id: int):
    """结束实验（已完成/已终止）：原因自填可空，剩余待检查时间点一并清除。"""
    return jsonify(experiments.finish_experiment(get_db(), experiment_id, body(), user=user()))


@api_bp.patch("/experiments/<int:experiment_id>/checkpoints/<int:checkpoint_id>")
@write
def update_experiment_checkpoint(experiment_id: int, checkpoint_id: int):
    return jsonify(experiments.update_checkpoint(
        get_db(), experiment_id, checkpoint_id, body(), user=user()
    ))


@api_bp.post("/experiments/<int:experiment_id>/checkpoints/<int:checkpoint_id>/reopen")
@write
def reopen_experiment_checkpoint(experiment_id: int, checkpoint_id: int):
    return jsonify(experiments.reopen_checkpoint(get_db(), experiment_id, checkpoint_id, user=user()))


@api_bp.post("/experiments/<int:experiment_id>/checkpoints/<int:checkpoint_id>/postpone")
@write
def postpone_experiment_checkpoint(experiment_id: int, checkpoint_id: int):
    """把一个待检查时间点往后推（默认 1 天）。"""
    return jsonify(experiments.postpone_checkpoint(
        get_db(), experiment_id, checkpoint_id, body(), user=user()
    ))


@api_bp.delete("/experiments/<int:experiment_id>/checkpoints/<int:checkpoint_id>")
@write
def delete_experiment_checkpoint(experiment_id: int, checkpoint_id: int):
    return jsonify(experiments.delete_checkpoint(get_db(), experiment_id, checkpoint_id, user=user()))


# --------------------------------------------------------------------------
# 课题讨论（课题 + 与导师的讨论记录）
# --------------------------------------------------------------------------
@api_bp.get("/topics")
def list_topics():
    """课题列表。status 可筛选 active/paused/closed，q 搜索名称/导师/简介。"""
    return jsonify(topics.list_topics(
        get_db(),
        status=request.args.get("status") or None,
        q=request.args.get("q") or None,
    ))


@api_bp.get("/topics/stats")
def topic_stats():
    return jsonify(topics.discussion_stats(get_db()))


@api_bp.post("/topics")
@write
def create_topic():
    return jsonify(topics.create_topic(get_db(), body(), user=user())), 201


@api_bp.get("/topics/<int:topic_id>")
def get_topic(topic_id: int):
    return jsonify(topics.get_topic(get_db(), topic_id))


@api_bp.patch("/topics/<int:topic_id>")
@write
def update_topic(topic_id: int):
    return jsonify(topics.update_topic(get_db(), topic_id, body(), user=user()))


@api_bp.delete("/topics/<int:topic_id>")
@write
def delete_topic(topic_id: int):
    return jsonify(topics.delete_topic(get_db(), topic_id, user=user()))


@api_bp.get("/topics/<int:topic_id>/discussions")
def list_discussions(topic_id: int):
    return jsonify(topics.list_discussions(
        get_db(), topic_id, q=request.args.get("q") or None
    ))


@api_bp.post("/topics/<int:topic_id>/discussions")
@write
def create_discussion(topic_id: int):
    return jsonify(topics.create_discussion(get_db(), topic_id, body(), user=user())), 201


@api_bp.patch("/discussions/<int:discussion_id>")
@write
def update_discussion(discussion_id: int):
    return jsonify(topics.update_discussion(get_db(), discussion_id, body(), user=user()))


@api_bp.delete("/discussions/<int:discussion_id>")
@write
def delete_discussion(discussion_id: int):
    return jsonify(topics.delete_discussion(get_db(), discussion_id, user=user()))


# --------------------------------------------------------------------------
# 待办事项（用户自建，独立于实验）
# --------------------------------------------------------------------------
@api_bp.get("/todos")
def list_todos():
    """待办列表。只传 start/end 时可查任意区间；only_done=1 只看已完成。"""
    return jsonify(todos.list_todos(
        get_db(),
        start=request.args.get("start") or None,
        end=request.args.get("end") or None,
        include_done=_bool_arg("include_done", True),
        only_done=_bool_arg("only_done", False),
        q=request.args.get("q") or None,
    ))


@api_bp.post("/todos")
@write
def create_todo():
    return jsonify(todos.create_todo(get_db(), body(), user=user())), 201


@api_bp.get("/todos/stats")
def todo_stats():
    return jsonify(todos.todo_stats(get_db()))


@api_bp.get("/todos/<int:todo_id>")
def get_todo(todo_id: int):
    return jsonify(todos.get_todo(get_db(), todo_id))


@api_bp.patch("/todos/<int:todo_id>")
@write
def update_todo(todo_id: int):
    return jsonify(todos.update_todo(get_db(), todo_id, body(), user=user()))


@api_bp.post("/todos/<int:todo_id>/complete")
@write
def complete_todo(todo_id: int):
    """勾选 / 撤销勾选（body 里 done=false 表示撤销）。"""
    return jsonify(todos.complete_todo(get_db(), todo_id, body(), user=user()))


@api_bp.post("/todos/<int:todo_id>/postpone")
@write
def postpone_todo(todo_id: int):
    return jsonify(todos.postpone_todo(get_db(), todo_id, body(), user=user()))


@api_bp.delete("/todos/<int:todo_id>")
@write
def delete_todo(todo_id: int):
    return jsonify(todos.delete_todo(get_db(), todo_id, user=user()))


# --------------------------------------------------------------------------
# 维护：体检 / 重算 / 备份 / 恢复 / 导入
# --------------------------------------------------------------------------
@api_bp.get("/maintenance/audit")
def maintenance_audit():
    conn = get_db()
    return jsonify({
        "database": str(get_config().db_path),
        "size_bytes": get_config().db_path.stat().st_size if get_config().db_path.exists() else 0,
        "counts": db.table_counts(conn),
        "issues": db.consistency_issues(conn),
        "pd_audit": maintenance.audit_pd(conn),
        "active_record_problems": maintenance.audit_active_records(conn),
        "meta": {
            key: db.get_meta(conn, key)
            for key in ("schema_version", "migrated_from", "migrated_at", "created_at")
            if db.get_meta(conn, key)
        },
    })


@api_bp.post("/maintenance/recalculate")
@write
def maintenance_recalculate():
    conn = get_db()
    result = batches.recalc_all(conn, user=user())
    result["remaining_issues"] = db.consistency_issues(conn)
    return jsonify(result)


@api_bp.get("/maintenance/backups")
def maintenance_backups():
    return jsonify(maintenance.list_backups(get_config()))


@api_bp.get("/maintenance/migration-report")
def migration_report():
    return jsonify(maintenance.read_migration_report(get_config()))


@api_bp.get("/maintenance/backup")
def download_backup():
    config = get_config()
    path = maintenance.copy_for_download(config)
    return send_file(
        path,
        mimetype="application/octet-stream",
        as_attachment=True,
        download_name=path.name,
    )


@api_bp.get("/export/full")
def export_full():
    conn = get_db()
    stream = excelio.full_export(conn)
    return send_file(
        stream,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"CellTracker_全量数据_{date.today():%Y%m%d}.xlsx",
    )


def _uploaded_db():
    uploaded = request.files.get("file")
    if uploaded is None or not uploaded.filename:
        raise ValidationError("请上传数据库文件（.db）")
    if not uploaded.filename.lower().endswith((".db", ".sqlite", ".sqlite3")):
        raise ValidationError("只接受 .db / .sqlite / .sqlite3 文件")
    config = get_config()
    return config, maintenance.save_upload(config, uploaded, uploaded.filename)


@api_bp.post("/maintenance/restore")
def restore_database():
    config, saved = _uploaded_db()
    with exclusive_runtime():
        try:
            result = maintenance.restore_database(config, saved)
        finally:
            maintenance.cleanup_upload(saved)
    return jsonify(result)


@api_bp.post("/maintenance/import-legacy")
def import_legacy():
    config, saved = _uploaded_db()
    with exclusive_runtime():
        try:
            report = maintenance.import_legacy_database(config, saved)
        finally:
            maintenance.cleanup_upload(saved)
    return jsonify(report)
