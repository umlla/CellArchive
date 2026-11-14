"""课题讨论服务。

用于记录与导师的课题讨论：
- 课题（research_topics）是独立实体，按课题组织讨论记录
- 讨论记录（topic_discussions）带「讨论日期」，默认当天，可回填
- 内容按 Markdown 存储，前端渲染为轻量富文本（不支持表格/HTML）
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Any

from ..domain import normalize_text, parse_date_value
from ..errors import NotFound, ValidationError
from . import audit, fetch_all, fetch_one, get_or_404

MAX_NAME = 120
MAX_ADVISOR = 80
MAX_TITLE = 200
MAX_SUMMARY = 2000
MAX_CONTENT = 50000
MAX_PARTICIPANTS = 200

TOPIC_STATUSES = {"active": "进行中", "paused": "暂缓", "closed": "已结题"}


def _now() -> datetime:
    return datetime.now().replace(second=0, microsecond=0)


def _today() -> str:
    return date.today().isoformat()


def _normalize_date(value: Any, field: str = "讨论日期") -> str:
    if value in (None, ""):
        return _today()
    parsed = parse_date_value(value)
    if not parsed:
        raise ValidationError(f"{field}格式无法识别：{value!r}，请使用 YYYY-MM-DD")
    return parsed


def _clean(value: Any, field: str, limit: int, *, required: bool = False) -> str | None:
    text = normalize_text(value, max_length=limit) if value is not None else ""
    if not text:
        if required:
            raise ValidationError(f"{field}不能为空")
        return None
    return text


# --------------------------------------------------------------------------
# 课题
# --------------------------------------------------------------------------
def _decorate_topic(row: dict[str, Any]) -> dict[str, Any]:
    topic = dict(row)
    status = topic.get("status") or "active"
    topic["status"] = status if status in TOPIC_STATUSES else "active"
    topic["status_label"] = TOPIC_STATUSES[topic["status"]]
    return topic


def list_topics(conn: sqlite3.Connection, *, status: str | None = None,
                q: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status and status in TOPIC_STATUSES:
        clauses.append("t.status = ?")
        params.append(status)
    if q:
        keyword = f"%{q.strip()}%"
        clauses.append("(t.name LIKE ? OR IFNULL(t.advisor, '') LIKE ? OR IFNULL(t.summary, '') LIKE ?)")
        params.extend([keyword, keyword, keyword])

    sql = """
        SELECT t.*,
               (SELECT COUNT(*) FROM topic_discussions d WHERE d.topic_id = t.id) AS discussion_count,
               (SELECT MAX(d.discussed_on) FROM topic_discussions d WHERE d.topic_id = t.id) AS last_discussed_on
        FROM research_topics t
    """
    if clauses:
        sql += " WHERE " + " AND ".join(clauses)
    # 进行中的排前面，然后按最近讨论时间倒序
    sql += """
        ORDER BY CASE t.status WHEN 'active' THEN 0 WHEN 'paused' THEN 1 ELSE 2 END,
                 IFNULL((SELECT MAX(d.discussed_on) FROM topic_discussions d WHERE d.topic_id = t.id), '') DESC,
                 t.id DESC
    """
    rows = fetch_all(conn, sql, tuple(params))
    return [_decorate_topic(row) for row in rows]


def get_topic(conn: sqlite3.Connection, topic_id: int) -> dict[str, Any]:
    row = fetch_one(
        conn,
        """SELECT t.*,
                  (SELECT COUNT(*) FROM topic_discussions d WHERE d.topic_id = t.id) AS discussion_count,
                  (SELECT MAX(d.discussed_on) FROM topic_discussions d WHERE d.topic_id = t.id) AS last_discussed_on
             FROM research_topics t WHERE t.id = ?""",
        (topic_id,),
    )
    if not row:
        raise NotFound("课题不存在")
    return _decorate_topic(row)


def _clean_markdown(value: Any, field: str, limit: int) -> str | None:
    """Markdown 正文：只去掉首尾空行，保留正文内部的空白与换行（对渲染有意义）。"""
    if value is None:
        return None
    text = str(value)
    if len(text) > limit:
        raise ValidationError(f"{field}最多 {limit} 个字符")
    text = text.strip("\r\n")
    return text or None


def create_topic(conn: sqlite3.Connection, payload: dict[str, Any],
                 user: str | None = None) -> dict[str, Any]:
    name = _clean(payload.get("name"), "课题名", MAX_NAME, required=True)
    advisor = _clean(payload.get("advisor"), "导师", MAX_ADVISOR)
    summary = _clean(payload.get("summary"), "简介", MAX_SUMMARY)
    status = payload.get("status") or "active"
    if status not in TOPIC_STATUSES:
        raise ValidationError(f"课题状态无效：{status}")

    stamp = _now().strftime("%Y-%m-%d %H:%M")
    cur = conn.execute(
        """INSERT INTO research_topics (name, advisor, status, summary, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (name, advisor, status, summary, stamp, stamp),
    )
    conn.commit()
    topic_id = int(cur.lastrowid)
    audit(conn, user, "create", "topic", topic_id, {"name": name})
    return get_topic(conn, topic_id)


def update_topic(conn: sqlite3.Connection, topic_id: int, payload: dict[str, Any],
                 user: str | None = None) -> dict[str, Any]:
    current = get_topic(conn, topic_id)
    name = _clean(payload.get("name", current["name"]), "课题名", MAX_NAME, required=True)
    advisor = _clean(payload.get("advisor", current.get("advisor")), "导师", MAX_ADVISOR)
    summary = _clean(payload.get("summary", current.get("summary")), "简介", MAX_SUMMARY)
    status = payload.get("status", current["status"])
    if status not in TOPIC_STATUSES:
        raise ValidationError(f"课题状态无效：{status}")

    conn.execute(
        """UPDATE research_topics SET name = ?, advisor = ?, status = ?, summary = ?, updated_at = ?
           WHERE id = ?""",
        (name, advisor, status, summary, _now().strftime("%Y-%m-%d %H:%M"), topic_id),
    )
    conn.commit()
    audit(conn, user, "update", "topic", topic_id, {"name": name})
    return get_topic(conn, topic_id)


def delete_topic(conn: sqlite3.Connection, topic_id: int,
                 user: str | None = None) -> dict[str, Any]:
    get_topic(conn, topic_id)
    count = int(
        conn.execute("SELECT COUNT(*) FROM topic_discussions WHERE topic_id = ?", (topic_id,)).fetchone()[0]
        or 0
    )
    conn.execute("DELETE FROM topic_discussions WHERE topic_id = ?", (topic_id,))
    conn.execute("DELETE FROM research_topics WHERE id = ?", (topic_id,))
    conn.commit()
    audit(conn, user, "delete", "topic", topic_id, {"discussions": count})
    return {"ok": True, "removed_discussions": count}


# --------------------------------------------------------------------------
# 讨论记录
# --------------------------------------------------------------------------
def _decorate_discussion(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["discussed_on"] = row.get("discussed_on") or ""
    return item


def list_discussions(conn: sqlite3.Connection, topic_id: int, *,
                     q: str | None = None) -> list[dict[str, Any]]:
    get_topic(conn, topic_id)  # 确保课题存在
    sql = "SELECT * FROM topic_discussions WHERE topic_id = ?"
    params: list[Any] = [topic_id]
    if q:
        keyword = f"%{q.strip()}%"
        sql += " AND (IFNULL(title, '') LIKE ? OR IFNULL(content, '') LIKE ? OR IFNULL(participants, '') LIKE ?)"
        params.extend([keyword, keyword, keyword])
    sql += " ORDER BY discussed_on DESC, id DESC"
    rows = fetch_all(conn, sql, tuple(params))
    return [_decorate_discussion(row) for row in rows]


def get_discussion(conn: sqlite3.Connection, discussion_id: int) -> dict[str, Any]:
    row = get_or_404(conn, "topic_discussions", discussion_id, "讨论记录不存在")
    return _decorate_discussion(row)


def create_discussion(conn: sqlite3.Connection, topic_id: int,
                      payload: dict[str, Any], user: str | None = None) -> dict[str, Any]:
    get_topic(conn, topic_id)
    discussed_on = _normalize_date(payload.get("discussed_on"))
    title = _clean(payload.get("title"), "标题", MAX_TITLE)
    content = _clean_markdown(payload.get("content"), "内容", MAX_CONTENT)
    participants = _clean(payload.get("participants"), "参与人", MAX_PARTICIPANTS)

    if not title and not content:
        raise ValidationError("标题和内容不能都为空")

    stamp = _now().strftime("%Y-%m-%d %H:%M")
    cur = conn.execute(
        """INSERT INTO topic_discussions
               (topic_id, discussed_on, title, content, participants, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (topic_id, discussed_on, title, content, participants, stamp, stamp),
    )
    conn.commit()
    discussion_id = int(cur.lastrowid)
    audit(conn, user, "create", "discussion", discussion_id,
          {"topic_id": topic_id, "discussed_on": discussed_on})
    return get_discussion(conn, discussion_id)


def update_discussion(conn: sqlite3.Connection, discussion_id: int,
                      payload: dict[str, Any], user: str | None = None) -> dict[str, Any]:
    current = get_discussion(conn, discussion_id)
    discussed_on = _normalize_date(payload.get("discussed_on", current["discussed_on"]))
    title = _clean(payload.get("title", current.get("title")), "标题", MAX_TITLE)
    content = _clean_markdown(payload.get("content", current.get("content")), "内容", MAX_CONTENT)
    participants = _clean(payload.get("participants", current.get("participants")),
                          "参与人", MAX_PARTICIPANTS)
    if not title and not content:
        raise ValidationError("标题和内容不能都为空")

    conn.execute(
        """UPDATE topic_discussions
              SET discussed_on = ?, title = ?, content = ?, participants = ?, updated_at = ?
            WHERE id = ?""",
        (discussed_on, title, content, participants,
         _now().strftime("%Y-%m-%d %H:%M"), discussion_id),
    )
    conn.commit()
    audit(conn, user, "update", "discussion", discussion_id,
          {"discussed_on": discussed_on})
    return get_discussion(conn, discussion_id)


def delete_discussion(conn: sqlite3.Connection, discussion_id: int,
                      user: str | None = None) -> dict[str, Any]:
    get_discussion(conn, discussion_id)
    conn.execute("DELETE FROM topic_discussions WHERE id = ?", (discussion_id,))
    conn.commit()
    audit(conn, user, "delete", "discussion", discussion_id, {})
    return {"ok": True}


def discussion_stats(conn: sqlite3.Connection) -> dict[str, Any]:
    total_topics = int(conn.execute("SELECT COUNT(*) FROM research_topics").fetchone()[0] or 0)
    active = int(
        conn.execute("SELECT COUNT(*) FROM research_topics WHERE status = 'active'").fetchone()[0] or 0
    )
    total_discussions = int(conn.execute("SELECT COUNT(*) FROM topic_discussions").fetchone()[0] or 0)
    last = fetch_one(
        conn, "SELECT MAX(discussed_on) AS d FROM topic_discussions"
    )
    return {
        "topics": total_topics,
        "active_topics": active,
        "discussions": total_discussions,
        "last_discussed_on": (last or {}).get("d"),
    }
