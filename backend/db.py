"""SQLite 连接、建表/升级、备份与数据库校验。

表结构与旧版 Streamlit 应用完全兼容（旧库可直接使用），另外新增了
`_schema_meta`、`users`、`audit_log` 三张辅助表，旧应用不会读取它们。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

from .config import SCHEMA_VERSION

CORE_TABLES = (
    "cell_lines",
    "culture_batches",
    "culture_records",
    "frozen_vials",
    "cell_groups",
    "cell_group_members",
)

SCHEMA_STATEMENTS = (
    """
    CREATE TABLE IF NOT EXISTS cell_lines (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        revival_date TEXT,
        type TEXT,
        default_passage_interval INTEGER DEFAULT 0,
        notes TEXT,
        species TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS culture_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cell_line_id INTEGER,
        batch_name TEXT NOT NULL,
        revival_date TEXT,
        source_freeze_date TEXT,
        initial_pd REAL DEFAULT 0,
        initial_cell_count REAL,
        is_active INTEGER DEFAULT 1,
        end_date TEXT,
        end_reason TEXT,
        notes TEXT,
        FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS culture_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER,
        passage INTEGER,
        date TEXT,
        inoculum_cells REAL,
        inoculum_dishes INTEGER,
        harvested_cells REAL,
        pd REAL,
        cumulative_pd REAL,
        status TEXT,
        next_passage_date TEXT,
        is_active INTEGER DEFAULT 1,
        notes TEXT,
        FOREIGN KEY(batch_id) REFERENCES culture_batches(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS frozen_vials (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cell_line_id INTEGER,
        batch_id INTEGER,
        freeze_date TEXT,
        cell_count REAL,
        location TEXT DEFAULT '',
        pd REAL,
        status TEXT DEFAULT '在库',
        notes TEXT,
        FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id),
        FOREIGN KEY(batch_id) REFERENCES culture_batches(id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cell_groups (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        group_name TEXT NOT NULL UNIQUE,
        notes TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS cell_group_members (
        group_id INTEGER,
        cell_line_id INTEGER,
        sort_order INTEGER DEFAULT 0,
        FOREIGN KEY(group_id) REFERENCES cell_groups(id),
        FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id),
        PRIMARY KEY(group_id, cell_line_id)
    )
    """,
    # ---------- 新版本辅助表（旧应用不感知） ----------
    """
    CREATE TABLE IF NOT EXISTS _schema_meta (
        key TEXT PRIMARY KEY,
        value TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        display_name TEXT,
        is_active INTEGER DEFAULT 1,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ts TEXT NOT NULL,
        username TEXT,
        action TEXT NOT NULL,
        entity TEXT,
        entity_id INTEGER,
        detail TEXT
    )
    """,
)

INDEX_STATEMENTS = (
    "CREATE INDEX IF NOT EXISTS idx_records_batch_date ON culture_records(batch_id, date)",
    "CREATE INDEX IF NOT EXISTS idx_records_batch_active ON culture_records(batch_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_batches_line ON culture_batches(cell_line_id, is_active)",
    "CREATE INDEX IF NOT EXISTS idx_vials_line ON frozen_vials(cell_line_id)",
    "CREATE INDEX IF NOT EXISTS idx_vials_location ON frozen_vials(location)",
    "CREATE INDEX IF NOT EXISTS idx_group_members_group ON cell_group_members(group_id, sort_order)",
)


def connect(db_path: str | Path, *, readonly: bool = False, wal: bool = True) -> sqlite3.Connection:
    path = Path(db_path)
    if readonly:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)
    else:
        conn = sqlite3.connect(str(path), timeout=30)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 15000")
        if not readonly:
            if wal:
                conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
    except Exception:
        conn.close()
        raise
    return conn


@contextmanager
def session(db_path: str | Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_schema(conn: sqlite3.Connection) -> None:
    for statement in SCHEMA_STATEMENTS:
        conn.execute(statement)
    # 兼容旧库：cell_group_members 可能缺少 sort_order（索引依赖该列，必须在建索引前补上）
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(cell_group_members)")}
    if "sort_order" not in columns:
        conn.execute("ALTER TABLE cell_group_members ADD COLUMN sort_order INTEGER DEFAULT 0")
    # 兼容旧库：细胞株的物种标签（用于图表配色分组）
    line_columns = {row["name"] for row in conn.execute("PRAGMA table_info(cell_lines)")}
    if "species" not in line_columns:
        conn.execute("ALTER TABLE cell_lines ADD COLUMN species TEXT")
    for statement in INDEX_STATEMENTS:
        conn.execute(statement)
    set_meta(conn, "schema_version", str(SCHEMA_VERSION))
    conn.commit()


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [row["name"] for row in conn.execute(f'PRAGMA table_info("{table}")')]


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    try:
        row = conn.execute("SELECT value FROM _schema_meta WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    return row["value"] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO _schema_meta(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def table_counts(conn: sqlite3.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in CORE_TABLES:
        try:
            counts[table] = int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])
        except sqlite3.OperationalError:
            counts[table] = 0
    return counts


def table_checksum(conn: sqlite3.Connection, table: str, columns: list[str] | None = None) -> str:
    """按物理行序对整表内容做 SHA256，用于迁移前后逐表比对。

    columns 可指定只比较部分列（用于兼容迁移后新增列的情况）。
    """
    selected = columns or table_columns(conn, table)
    projection = ", ".join(f'"{column}"' for column in selected)
    digest = hashlib.sha256()
    cursor = conn.execute(f'SELECT {projection} FROM "{table}" ORDER BY rowid')
    for row in cursor:
        digest.update(json.dumps(list(row), ensure_ascii=False, default=str).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def data_fingerprint(conn: sqlite3.Connection) -> dict[str, Any]:
    counts = table_counts(conn)
    checksums = {table: table_checksum(conn, table) for table in CORE_TABLES if counts.get(table, 0) > 0}
    return {"counts": counts, "checksums": checksums}


def validate_database_file(path: str | Path) -> dict[str, Any]:
    """检查一个 SQLite 文件是否可以当作本系统的数据库。"""
    path = Path(path)
    if not path.exists():
        return {"ok": False, "reason": "文件不存在"}
    if path.stat().st_size == 0:
        return {"ok": False, "reason": "文件为空"}
    try:
        conn = connect(path, readonly=True, wal=False)
    except sqlite3.Error as exc:
        return {"ok": False, "reason": f"无法打开为 SQLite：{exc}"}
    try:
        tables = {row["name"] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        missing = [table for table in CORE_TABLES if table not in tables]
        if missing:
            return {"ok": False, "reason": f"缺少数据表：{', '.join(missing)}", "tables": sorted(tables)}
        info: dict[str, Any] = {
            "ok": True,
            "tables": sorted(tables & set(CORE_TABLES)),
            "counts": table_counts(conn),
            "fingerprint": data_fingerprint(conn),
            "schema_version": get_meta(conn, "schema_version"),
        }
        # 迁移前的一致性检查（不阻断，只报告）
        info["issues"] = consistency_issues(conn)
        return info
    except sqlite3.Error as exc:
        return {"ok": False, "reason": f"读取失败：{exc}"}
    finally:
        conn.close()


def consistency_issues(conn: sqlite3.Connection) -> list[str]:
    issues: list[str] = []
    queries = {
        "存在没有对应细胞株的批次": "SELECT COUNT(*) FROM culture_batches WHERE cell_line_id NOT IN (SELECT id FROM cell_lines)",
        "存在没有对应批次的传代记录": "SELECT COUNT(*) FROM culture_records WHERE batch_id NOT IN (SELECT id FROM culture_batches)",
        "存在没有对应细胞株的冻存管": "SELECT COUNT(*) FROM frozen_vials WHERE cell_line_id NOT IN (SELECT id FROM cell_lines)",
        "同一批次存在多条活跃记录": (
            "SELECT COUNT(*) FROM (SELECT batch_id FROM culture_records WHERE is_active = 1 "
            "GROUP BY batch_id HAVING COUNT(*) > 1)"
        ),
        "已终止批次仍有活跃记录": (
            "SELECT COUNT(*) FROM culture_records cr JOIN culture_batches cb ON cb.id = cr.batch_id "
            "WHERE cr.is_active = 1 AND cb.is_active = 0"
        ),
        "活跃批次没有活跃记录": (
            "SELECT COUNT(*) FROM culture_batches cb WHERE cb.is_active = 1 AND NOT EXISTS "
            "(SELECT 1 FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1)"
        ),
        "日期格式不是 YYYY-MM-DD": "SELECT COUNT(*) FROM culture_records WHERE date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'",
    }
    for label, sql in queries.items():
        try:
            count = int(conn.execute(sql).fetchone()[0])
        except sqlite3.Error:
            continue
        if count:
            issues.append(f"{label}：{count}")
    return issues


def backup_database(db_path: str | Path, dest: str | Path) -> Path:
    """用 SQLite 在线备份 API 做一致性快照。"""
    db_path = Path(db_path)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = connect(db_path)
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
        finally:
            target.close()
    finally:
        source.close()
    return dest


def default_backup_name(prefix: str = "cell_data") -> str:
    return f"{prefix}-{datetime.now().strftime('%Y%m%d-%H%M%S')}.db"


def copy_database_file(source: str | Path, target: str | Path) -> Path:
    """用备份 API 复制为自包含文件（避免 WAL 未合并导致丢数据）。"""
    source_path = Path(source)
    target_path = Path(target)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    source_conn = connect(source_path, readonly=True, wal=False)
    try:
        target_conn = sqlite3.connect(str(target_path))
        try:
            source_conn.backup(target_conn)
        finally:
            target_conn.close()
    finally:
        source_conn.close()
    checkpoint = sqlite3.connect(str(target_path))
    try:
        checkpoint.execute("PRAGMA journal_mode = DELETE")
        checkpoint.commit()
    finally:
        checkpoint.close()
    for suffix in ("-wal", "-shm"):
        Path(str(target_path) + suffix).unlink(missing_ok=True)
    return target_path


def replace_database(db_path: str | Path, new_file: str | Path, backup_dir: str | Path) -> dict[str, Any]:
    """用新文件原子替换当前数据库，替换前自动备份。"""
    db_path = Path(db_path)
    new_file = Path(new_file)
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    previous_backup = None
    if db_path.exists():
        previous_backup = backup_database(db_path, backup_dir / default_backup_name("before-restore"))

    staging = db_path.with_suffix(db_path.suffix + ".incoming")
    staging.unlink(missing_ok=True)
    copy_database_file(new_file, staging)

    conn = connect(staging, wal=False)
    try:
        init_schema(conn)
    finally:
        conn.close()

    for suffix in ("-wal", "-shm"):
        Path(str(db_path) + suffix).unlink(missing_ok=True)
    try:
        os.replace(staging, db_path)
    except PermissionError:
        db_path.unlink(missing_ok=True)
        os.replace(staging, db_path)

    return {
        "restored_from": str(new_file),
        "previous_backup": str(previous_backup) if previous_backup else None,
    }
