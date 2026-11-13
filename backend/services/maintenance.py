"""备份、恢复、迁移导入与数据体检。"""

from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from .. import db
from ..config import Config
from ..errors import ValidationError
from . import audit, fetch_all
from .batches import recalc_all
from ..migrate import audit_active_records, audit_pd


def create_backup(config: Config) -> Path:
    config.ensure_dirs()
    path = config.backup_dir / db.default_backup_name()
    db.backup_database(config.db_path, path)
    prune_backups(config.backup_dir)
    return path


def list_backups(config: Config) -> list[dict[str, Any]]:
    if not config.backup_dir.exists():
        return []
    items = []
    for path in sorted(config.backup_dir.glob("*.db"), key=lambda item: item.stat().st_mtime, reverse=True):
        stat = path.stat()
        items.append({
            "name": path.name,
            "size": stat.st_size,
            "modified": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "path": str(path),
        })
    return items


def prune_backups(backup_dir: Path, keep: int = 30) -> None:
    files = sorted(backup_dir.glob("*.db"), key=lambda item: item.stat().st_mtime, reverse=True)
    for stale in files[keep:]:
        try:
            stale.unlink()
        except OSError:
            pass


def restore_database(config: Config, uploaded_path: str | Path) -> dict[str, Any]:
    info = db.validate_database_file(uploaded_path)
    if not info.get("ok"):
        raise ValidationError(f"备份文件无效：{info.get('reason')}")
    result = db.replace_database(config.db_path, uploaded_path, config.backup_dir)
    result["source_counts"] = info["counts"]
    return result


def import_legacy_database(config: Config, uploaded_path: str | Path) -> dict[str, Any]:
    """导入旧版数据库（表结构兼容，直接替换当前库），并逐表校验数据完整复制。"""
    info = db.validate_database_file(uploaded_path)
    if not info.get("ok"):
        raise ValidationError(f"旧版数据库无效：{info.get('reason')}")

    source_conn = db.connect(uploaded_path, readonly=True, wal=False)
    try:
        source_counts = db.table_counts(source_conn)
        source_columns = {table: db.table_columns(source_conn, table) for table in db.CORE_TABLES}
        source_checksums = {
            table: db.table_checksum(source_conn, table, source_columns[table])
            for table in db.CORE_TABLES
        }
    finally:
        source_conn.close()

    result = db.replace_database(config.db_path, uploaded_path, config.backup_dir)

    conn = db.connect(config.db_path, wal=False)
    try:
        db.init_schema(conn)
        pd_audit = audit_pd(conn)
        active_problems = audit_active_records(conn)
        counts = db.table_counts(conn)
        checksums = {
            table: db.table_checksum(conn, table, source_columns[table])
            for table in db.CORE_TABLES
        }
    finally:
        conn.close()

    counts_equal = counts == source_counts
    checksums_equal = checksums == source_checksums
    if not (counts_equal and checksums_equal):
        # 校验不通过时回滚到导入前的数据库，避免留下不完整数据
        if result.get("previous_backup"):
            db.replace_database(config.db_path, result["previous_backup"], config.backup_dir)
        raise ValidationError("导入后校验失败，已回滚到导入前的数据库，请检查源文件")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(uploaded_path),
        "target": str(config.db_path),
        "source_counts": source_counts,
        "target_counts": counts,
        "counts_equal": counts_equal,
        "checksums_equal": checksums_equal,
        "pd_audit": pd_audit,
        "active_record_problems": active_problems,
        "previous_backup": result.get("previous_backup"),
        "status": "ok" if pd_audit["mismatch_count"] == 0 and not active_problems else "ok_with_warnings",
    }
    report_path = config.db_path.parent / "migration-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def read_migration_report(config: Config) -> dict[str, Any] | None:
    path = config.db_path.parent / "migration-report.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def database_audit(config: Config) -> dict[str, Any]:
    """只读体检：表行数、外键/活跃标记问题、PD 偏差。"""
    conn = db.connect(config.db_path, readonly=True, wal=False)
    try:
        counts = db.table_counts(conn)
        issues = db.consistency_issues(conn)
        pd_audit = audit_pd(conn)
        active_problems = audit_active_records(conn)
        meta = {
            key: db.get_meta(conn, key)
            for key in ("schema_version", "migrated_from", "migrated_at", "created_at")
            if db.get_meta(conn, key) is not None
        }
    finally:
        conn.close()
    return {
        "database": str(config.db_path),
        "size_bytes": config.db_path.stat().st_size if config.db_path.exists() else 0,
        "counts": counts,
        "issues": issues,
        "pd_audit": pd_audit,
        "active_record_problems": active_problems,
        "meta": meta,
        "status": "ok" if not issues and pd_audit["mismatch_count"] == 0 and not active_problems
        else "warning",
    }


def recalculate_everything(config: Config, username: str | None = None) -> dict[str, Any]:
    conn = db.connect(config.db_path)
    try:
        with conn:
            result = recalc_all(conn, user=username)
            result.update(database_audit_after(conn))
        return result
    finally:
        conn.close()


def database_audit_after(conn: sqlite3.Connection) -> dict[str, Any]:
    return {
        "remaining_issues": db.consistency_issues(conn),
        "pd_mismatches": audit_pd(conn)["mismatch_count"],
    }


def assign_species(
    conn: sqlite3.Connection,
    species: str,
    *,
    line_ids: list[int] | None = None,
    only_unset: bool = True,
    user: str | None = None,
) -> dict[str, Any]:
    """批量给细胞株打物种标签。

    only_unset 为真时只处理还没标物种的细胞株，不会覆盖已单独设置的值。
    """
    from ..domain import normalize_species

    value = normalize_species(species)
    if not value:
        raise ValidationError("物种不能为空")
    sql = "SELECT id, name, species FROM cell_lines WHERE 1 = 1"
    params: list[Any] = []
    if line_ids:
        sql += f" AND id IN ({','.join('?' * len(line_ids))})"
        params.extend(int(item) for item in line_ids)
    if only_unset:
        sql += " AND (species IS NULL OR TRIM(species) = '')"
    rows = conn.execute(sql, params).fetchall()
    for row in rows:
        conn.execute("UPDATE cell_lines SET species = ? WHERE id = ?", (value, int(row["id"])))
    audit(conn, user, "assign_species", "cell_line", None,
          {"species": value, "updated": len(rows), "only_unset": only_unset})
    return {"species": value, "updated": len(rows), "names": [row["name"] for row in rows]}


def save_upload(config: Config, file_storage, filename: str = "upload.db") -> Path:
    """把上传文件落到 data/uploads/ 下，返回路径。"""
    upload_dir = config.db_path.parent / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(filename or "upload.db").name
    target = upload_dir / f"{datetime.now():%Y%m%d-%H%M%S}-{safe_name}"
    file_storage.save(target)
    return target


def cleanup_upload(path: str | Path | None) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def copy_for_download(config: Config) -> Path:
    """生成一份备份供下载（与在线备份分离，避免下载时写库冲突）。"""
    config.ensure_dirs()
    path = config.backup_dir / db.default_backup_name("cell_data-download")
    db.backup_database(config.db_path, path)
    prune_backups(config.backup_dir)
    return path


def export_all_tables(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    tables = ("cell_lines", "culture_batches", "culture_records", "frozen_vials",
              "cell_groups", "cell_group_members")
    return {table: fetch_all(conn, f'SELECT * FROM "{table}"') for table in tables}


def copy_file(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
