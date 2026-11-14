"""课题讨论接口测试。"""

from __future__ import annotations

from datetime import date, timedelta


def _today(offset: int = 0) -> str:
    return (date.today() + timedelta(days=offset)).isoformat()


def create_topic(client, **overrides):
    payload = {"name": "肿瘤耐药机制", "advisor": "导师A", "summary": "研究紫杉醇耐药"}
    payload.update(overrides)
    response = client.post("/api/topics", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def create_discussion(client, topic_id, **overrides):
    payload = {"title": "第一次讨论", "content": "确定实验方向"}
    payload.update(overrides)
    response = client.post(f"/api/topics/{topic_id}/discussions", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


# --------------------------------------------------------------------------
# 课题
# --------------------------------------------------------------------------
def test_create_topic(client):
    topic = create_topic(client)
    assert topic["name"] == "肿瘤耐药机制"
    assert topic["advisor"] == "导师A"
    assert topic["status"] == "active"
    assert topic["status_label"] == "进行中"
    assert topic["discussion_count"] == 0


def test_topic_name_required(client):
    assert client.post("/api/topics", json={"name": "  "}).status_code == 400
    assert client.post("/api/topics", json={}).status_code == 400


def test_invalid_topic_status_rejected(client):
    assert client.post("/api/topics", json={"name": "x", "status": "bogus"}).status_code == 400


def test_list_topics_ordering(client):
    """进行中的排在前面，然后按最近讨论时间倒序。"""
    a = create_topic(client, name="课题A")
    b = create_topic(client, name="课题B", status="closed")
    c = create_topic(client, name="课题C")
    create_discussion(client, a["id"], discussed_on=_today(-5))
    create_discussion(client, c["id"], discussed_on=_today())

    names = [t["name"] for t in client.get("/api/topics").get_json()]
    # 进行中（C 最近讨论、A）在前，已结题（B）在后
    assert names.index("课题C") < names.index("课题A") < names.index("课题B")


def test_filter_topics_by_status(client):
    create_topic(client, name="进行中课题")
    create_topic(client, name="已结题课题", status="closed")
    active = client.get("/api/topics?status=active").get_json()
    assert [t["name"] for t in active] == ["进行中课题"]


def test_search_topics(client):
    create_topic(client, name="肿瘤耐药", advisor="导师A")
    create_topic(client, name="干细胞分化", advisor="导师B")
    found = client.get("/api/topics?q=导师B").get_json()
    assert len(found) == 1 and found[0]["name"] == "干细胞分化"


def test_update_topic(client):
    topic = create_topic(client)
    updated = client.patch(f"/api/topics/{topic['id']}", json={
        "name": "新名字", "status": "closed", "advisor": "导师B"
    }).get_json()
    assert updated["name"] == "新名字"
    assert updated["status"] == "closed"
    assert updated["advisor"] == "导师B"


def test_delete_topic_removes_discussions(client):
    topic = create_topic(client)
    create_discussion(client, topic["id"])
    create_discussion(client, topic["id"])
    result = client.delete(f"/api/topics/{topic['id']}").get_json()
    assert result["removed_discussions"] == 2
    assert client.get(f"/api/topics/{topic['id']}").status_code == 404


def test_topic_not_found(client):
    assert client.get("/api/topics/9999").status_code == 404


# --------------------------------------------------------------------------
# 讨论记录
# --------------------------------------------------------------------------
def test_discussion_defaults_to_today(client):
    """不传日期时默认当天。"""
    topic = create_topic(client)
    disc = create_discussion(client, topic["id"])
    assert disc["discussed_on"] == _today()


def test_discussion_accepts_backfill_date(client):
    """支持回填过去的讨论日期。"""
    topic = create_topic(client)
    disc = create_discussion(client, topic["id"], discussed_on=_today(-3))
    assert disc["discussed_on"] == _today(-3)


def test_discussion_requires_title_or_content(client):
    topic = create_topic(client)
    response = client.post(f"/api/topics/{topic['id']}/discussions",
                           json={"title": "", "content": ""})
    assert response.status_code == 400


def test_discussion_ordering_newest_first(client):
    topic = create_topic(client)
    create_discussion(client, topic["id"], title="旧", discussed_on=_today(-10))
    create_discussion(client, topic["id"], title="新", discussed_on=_today())
    items = client.get(f"/api/topics/{topic['id']}/discussions").get_json()
    assert [d["title"] for d in items] == ["新", "旧"]


def test_long_markdown_content_accepted(client):
    """长 Markdown 内容不应被 2000 字符的默认上限截断或拒绝。"""
    topic = create_topic(client)
    long_content = "# 标题\n\n" + ("这是一段很长的讨论内容。\n" * 400).rstrip("\n")
    assert len(long_content) > 2000
    disc = create_discussion(client, topic["id"], content=long_content)
    assert disc["content"] == long_content


def test_markdown_content_preserved_verbatim(client):
    """Markdown 原文必须原样保存，不能做任何转义或改写。"""
    md = "## 结论\n\n- **重点**：耐药性增强\n- 下一步：`qPCR` 验证\n\n> 引用一段话"
    topic = create_topic(client)
    disc = create_discussion(client, topic["id"], content=md)
    assert disc["content"] == md


def test_update_discussion(client):
    topic = create_topic(client)
    disc = create_discussion(client, topic["id"])
    updated = client.patch(f"/api/discussions/{disc['id']}", json={
        "title": "改过的标题", "discussed_on": _today(-1)
    }).get_json()
    assert updated["title"] == "改过的标题"
    assert updated["discussed_on"] == _today(-1)


def test_delete_discussion(client):
    topic = create_topic(client)
    disc = create_discussion(client, topic["id"])
    assert client.delete(f"/api/discussions/{disc['id']}").status_code == 200
    assert client.get(f"/api/topics/{topic['id']}/discussions").get_json() == []


def test_search_discussions(client):
    topic = create_topic(client)
    create_discussion(client, topic["id"], title="讨论 A", content="关于凋亡")
    create_discussion(client, topic["id"], title="讨论 B", content="关于迁移")
    found = client.get(f"/api/topics/{topic['id']}/discussions?q=迁移").get_json()
    assert len(found) == 1 and found[0]["title"] == "讨论 B"


def test_topic_counts_and_last_date(client):
    topic = create_topic(client)
    create_discussion(client, topic["id"], discussed_on=_today(-7))
    create_discussion(client, topic["id"], discussed_on=_today(-1))
    refreshed = client.get(f"/api/topics/{topic['id']}").get_json()
    assert refreshed["discussion_count"] == 2
    assert refreshed["last_discussed_on"] == _today(-1)


def test_stats(client):
    topic = create_topic(client)
    create_discussion(client, topic["id"], discussed_on=_today())
    stats = client.get("/api/topics/stats").get_json()
    assert stats["topics"] == 1
    assert stats["active_topics"] == 1
    assert stats["discussions"] == 1
    assert stats["last_discussed_on"] == _today()

