"""用户待办事项接口测试。"""

from __future__ import annotations

from datetime import datetime, timedelta


def _today(offset: int = 0) -> str:
    return (datetime.now() + timedelta(days=offset)).strftime("%Y-%m-%d")


def create_todo(client, **overrides):
    payload = {"title": "买培养基", "due_date": _today(), "notes": ""}
    payload.update(overrides)
    response = client.post("/api/todos", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


# --------------------------------------------------------------------------
# 基础 CRUD
# --------------------------------------------------------------------------
def test_create_todo_with_and_without_clock(client):
    with_time = create_todo(client, title="预约离心机", due_clock="14:30")
    assert with_time["due_clock"] == "14:30"
    assert "14:30" in with_time["due_label"]
    assert with_time["kind"] == "todo"

    all_day = create_todo(client, title="整理冻存记录", due_clock=None)
    assert all_day["due_clock"] is None
    assert "全天" in all_day["due_label"]


def test_todo_requires_title_and_date(client):
    assert client.post("/api/todos", json={"due_date": _today()}).status_code == 400
    assert client.post("/api/todos", json={"title": "x"}).status_code == 400
    assert client.post("/api/todos", json={"title": "x", "due_date": "不是日期"}).status_code == 400
    assert client.post("/api/todos", json={"title": "x", "due_date": _today(), "due_clock": "25:00"}).status_code == 400


def test_update_and_delete_todo(client):
    todo = create_todo(client)
    updated = client.patch(f"/api/todos/{todo['id']}", json={"title": "买 DMEM", "due_clock": "09:00"})
    assert updated.status_code == 200
    assert updated.get_json()["title"] == "买 DMEM"
    assert updated.get_json()["due_clock"] == "09:00"

    assert client.delete(f"/api/todos/{todo['id']}").status_code == 200
    assert client.get(f"/api/todos/{todo['id']}").status_code == 404


def test_complete_and_reopen_todo(client):
    todo = create_todo(client)
    done = client.post(f"/api/todos/{todo['id']}/complete", json={}).get_json()
    assert done["done"] is True
    assert done["state"] == "done"
    assert done["done_at"]

    reopened = client.post(f"/api/todos/{todo['id']}/complete", json={"done": False}).get_json()
    assert reopened["done"] is False
    assert reopened["done_at"] is None


def test_postpone_todo(client):
    todo = create_todo(client, due_date=_today(0))
    moved = client.post(f"/api/todos/{todo['id']}/postpone", json={"days": 1}).get_json()
    assert moved["due_date"] == _today(1)
    # 时间不变
    assert moved["due_clock"] == todo["due_clock"]

    assert client.post(f"/api/todos/{todo['id']}/postpone", json={"days": 0}).status_code == 400


# --------------------------------------------------------------------------
# 状态与统计
# --------------------------------------------------------------------------
def test_todo_states(client):
    overdue = create_todo(client, title="昨天的", due_date=_today(-2))
    today = create_todo(client, title="今天的", due_date=_today())
    future = create_todo(client, title="下周的", due_date=_today(10))
    assert overdue["state"] == "overdue"
    assert today["state"] == "due"
    assert future["state"] == "scheduled"


def test_todo_stats_and_scope(client):
    create_todo(client, title="逾期", due_date=_today(-3))
    create_todo(client, title="今天", due_date=_today())
    done = create_todo(client, title="已完成", due_date=_today())
    client.post(f"/api/todos/{done['id']}/complete", json={})

    stats = client.get("/api/todos/stats").get_json()
    assert stats["overdue"] == 1
    assert stats["today"] >= 1
    assert stats["done"] == 1
    assert stats["pending"] >= 2

    only_done = client.get("/api/todos?only_done=1").get_json()
    assert [item["title"] for item in only_done] == ["已完成"]

    pending_only = client.get("/api/todos?include_done=0").get_json()
    assert all(not item["done"] for item in pending_only)


def test_todo_range_query(client):
    create_todo(client, title="本月第一天", due_date=_today(-1))
    create_todo(client, title="很久以后", due_date=_today(200))
    rows = client.get(f"/api/todos?start={_today(-7)}&end={_today(7)}").get_json()
    titles = [item["title"] for item in rows]
    assert "本月第一天" in titles
    assert "很久以后" not in titles


# --------------------------------------------------------------------------
# 与日历 / 提醒的整合
# --------------------------------------------------------------------------
def test_todos_appear_in_month_and_week_views(client):
    todo = create_todo(client, title="日历里的待办", due_date=_today())
    month = client.get("/api/experiments/month").get_json()
    today_cell = next(day for day in month["days"] if day["is_today"])
    assert any(item["id"] == todo["id"] for item in today_cell["todos"])
    assert today_cell["todo_count"] >= 1

    week = client.get("/api/experiments/week").get_json()
    week_today = next(day for day in week["days"] if day["is_today"])
    assert any(item["id"] == todo["id"] for item in week_today["todos"])


def test_summary_includes_todo_counts(client):
    create_todo(client, title="逾期待办", due_date=_today(-1))
    create_todo(client, title="今天待办", due_date=_today())
    stats = client.get("/api/experiments/summary").get_json()["stats"]
    assert stats["todo_overdue"] >= 1
    assert stats["todo_today"] >= 1
    assert stats["todo_pending"] >= 2


# --------------------------------------------------------------------------
# 日历格子里快速添加（只给标题 + 日期）
# --------------------------------------------------------------------------
def test_quick_add_from_calendar_cell(client):
    """点格子直接建待办：只需要标题和日期，默认全天。"""
    response = client.post("/api/todos", json={"title": "点格子建的待办", "date": _today(1)})
    assert response.status_code == 201, response.get_json()
    todo = response.get_json()
    assert todo["due_date"] == _today(1)
    assert todo["due_clock"] is None
    assert "全天" in todo["due_label"]


def test_quick_add_accepts_content_alias(client):
    response = client.post("/api/todos", json={"content": "别名写法", "due_date": _today()})
    assert response.status_code == 201
    assert response.get_json()["title"] == "别名写法"


def test_quick_add_still_requires_title(client):
    assert client.post("/api/todos", json={"date": _today()}).status_code == 400
