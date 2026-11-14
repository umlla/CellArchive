"""培养实验（细胞实验日程）接口测试。"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from backend.services import experiments

from .conftest import create_line


def _dt(hours_from_now: float) -> str:
    return (datetime.now() + timedelta(hours=hours_from_now)).strftime("%Y-%m-%d %H:%M")


def _iso(hours_from_now: float) -> str:
    return (datetime.now() + timedelta(hours=hours_from_now)).isoformat(timespec="seconds")


def create_experiment(client, **overrides):
    payload = {
        "name": "A549 紫杉醇梯度实验",
        "notes": "A549，紫杉醇 0/10/50 nM",
        "interval_value": 24,
        "interval_unit": "h",
        "started_at": _dt(2),
    }
    payload.update(overrides)
    response = client.post("/api/experiments", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


# --------------------------------------------------------------------------
# 基础 CRUD
# --------------------------------------------------------------------------
def test_create_experiment_builds_schedule(client):
    exp = create_experiment(client)
    assert exp["name"] == "A549 紫杉醇梯度实验"
    assert exp["status"] == "active"
    assert exp["interval_value"] == 1 and exp["interval_unit"] == "d"
    assert exp["interval_text"] == "1d（每 1 天）"
    # 首个时间点 + 预先铺好的下一个
    assert exp["checkpoint_count"] >= 2
    assert exp["pending_count"] >= 1
    first, second = exp["checkpoints"][0], exp["checkpoints"][1]
    assert first["done"] is False
    gap = datetime.strptime(second["due_at"], "%Y-%m-%d %H:%M") - datetime.strptime(
        first["due_at"], "%Y-%m-%d %H:%M"
    )
    assert gap == timedelta(hours=24)


def test_create_requires_name_and_valid_interval(client):
    bad = client.post("/api/experiments", json={"notes": "x"})
    assert bad.status_code == 400
    assert "实验名" in bad.get_json()["error"]["message"]

    too_short = client.post(
        "/api/experiments", json={"name": "x", "interval_value": 5, "interval_unit": "m"}
    )
    assert too_short.status_code == 400

    bad_unit = client.post(
        "/api/experiments", json={"name": "x", "interval_value": 2, "interval_unit": "w"}
    )
    assert bad_unit.status_code == 400


def test_interval_in_days_is_stored_as_hours(client):
    exp = create_experiment(client, interval_value=2, interval_unit="d")
    assert (exp["interval_value"], exp["interval_unit"]) == (2, "d")
    assert exp["interval_text"] == "2d（每 2 天）"
    first, second = exp["checkpoints"][0], exp["checkpoints"][1]
    gap = datetime.strptime(second["due_at"], "%Y-%m-%d %H:%M") - datetime.strptime(
        first["due_at"], "%Y-%m-%d %H:%M"
    )
    assert gap == timedelta(days=2)


def test_interval_in_hours_of_a_full_day_is_normalized_to_days(client):
    exp = create_experiment(client, interval_value=24, interval_unit="h")
    assert (exp["interval_value"], exp["interval_unit"]) == (1, "d")
    exp = create_experiment(client, interval_value=48, interval_unit="h")
    assert (exp["interval_value"], exp["interval_unit"]) == (2, "d")


def test_fractional_day_interval(client):
    exp = create_experiment(client, interval_value=1.5, interval_unit="d")
    # 36 小时既不是整天也不是分钟精度：按小时存
    assert (exp["interval_value"], exp["interval_unit"]) == (36, "h")


def test_update_and_delete_experiment(client):
    exp = create_experiment(client)
    updated = client.patch(
        f"/api/experiments/{exp['id']}",
        json={"name": "改名后的实验", "notes": "换培养基", "interval_value": 12, "interval_unit": "h"},
    )
    assert updated.status_code == 200
    body = updated.get_json()
    assert body["name"] == "改名后的实验"
    assert (body["interval_value"], body["interval_unit"]) == (12, "h")
    # 改间隔后，后续时间点按新间隔重排
    first, second = body["checkpoints"][0], body["checkpoints"][1]
    gap = datetime.strptime(second["due_at"], "%Y-%m-%d %H:%M") - datetime.strptime(
        first["due_at"], "%Y-%m-%d %H:%M"
    )
    assert gap == timedelta(hours=12)

    assert client.delete(f"/api/experiments/{exp['id']}").status_code == 200
    assert client.get(f"/api/experiments/{exp['id']}").status_code == 404


def test_cell_line_link_and_unknown_line(client):
    line = create_line(client, "HeLa")
    exp = create_experiment(client, cell_line_id=line["id"])
    assert exp["cell_line_id"] == line["id"]
    assert exp["cell_line_name"] == "HeLa"

    bad = client.post("/api/experiments", json={"name": "x", "cell_line_id": 9999})
    assert bad.status_code == 400


def test_multiple_cell_lines_and_groups(client):
    """一个实验可以关联多株细胞和多个细胞组，之后可自由增减。"""
    a = create_line(client, "HeLa")
    b = create_line(client, "A549")
    c = create_line(client, "CHO-K1")
    group = client.post("/api/groups", json={"group_name": "第一组"}).get_json()

    exp = create_experiment(
        client,
        cell_line_ids=[a["id"], b["id"]],
        group_ids=[group["id"]],
    )
    assert exp["cell_line_ids"] == [a["id"], b["id"]]
    assert exp["cell_line_names"] == ["HeLa", "A549"]
    assert exp["cell_line_count"] == 2
    assert [g["group_name"] for g in exp["groups"]] == ["第一组"]
    # 兼容旧字段：第一条细胞株仍写入 cell_line_id
    assert exp["cell_line_id"] == a["id"]

    # 增减细胞株：去掉 A549，加上 CHO-K1
    updated = client.patch(
        f"/api/experiments/{exp['id']}",
        json={"cell_line_ids": [a["id"], c["id"]], "group_ids": []},
    ).get_json()
    assert updated["cell_line_ids"] == [a["id"], c["id"]]
    assert updated["groups"] == []

    bad = client.patch(f"/api/experiments/{exp['id']}", json={"cell_line_ids": [9999]})
    assert bad.status_code == 400


def test_search_matches_linked_cell_line(client):
    line = create_line(client, "非常特殊的细胞名")
    create_experiment(client, name="普通实验", cell_line_ids=[line["id"]])
    create_experiment(client, name="另一个实验")
    hits = client.get("/api/experiments?q=非常特殊").get_json()
    assert [item["name"] for item in hits] == ["普通实验"]


def test_started_at_decides_first_check(client):
    """记录实验时间后，第一次检查时间 = 实验时间 + 间隔。"""
    started = _dt(-30)
    exp = create_experiment(client, started_at=started, interval_value=24, interval_unit="h")
    first = exp["checkpoints"][0]
    delta = datetime.strptime(first["due_at"], "%Y-%m-%d %H:%M") - datetime.strptime(
        started, "%Y-%m-%d %H:%M"
    )
    assert delta == timedelta(hours=24)
    assert exp["started_at"] == started


def test_extra_notes_saved(client):
    exp = create_experiment(client, extra_notes="仪器：酶标仪 2 号；试剂批号 B20261101")
    assert exp["extra_notes"] == "仪器：酶标仪 2 号；试剂批号 B20261101"
    updated = client.patch(f"/api/experiments/{exp['id']}", json={"extra_notes": "改过的备注"})
    assert updated.get_json()["extra_notes"] == "改过的备注"


# --------------------------------------------------------------------------
# 勾选推进
# --------------------------------------------------------------------------
def test_complete_checkpoint_advances_schedule(client):
    exp = create_experiment(client, started_at=_dt(1 - 24), interval_value=24, interval_unit="h")
    first = exp["checkpoints"][0]
    response = client.post(
        f"/api/experiments/{exp['id']}/complete",
        json={"checkpoint_id": first["id"], "cell_status": "良好", "observation": "密度约 60%"},
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["done_count"] == 1
    done = body["checkpoints"][0]
    assert done["done"] is True
    assert done["cell_status"] == "良好"
    assert done["observation"] == "密度约 60%"
    # 勾选后自动提醒下一个时间点
    nxt = body["next_checkpoint"]
    assert nxt is not None and nxt["done"] is False
    assert body["next_due_label"]
    assert body["next_due_label"].startswith(("今天", "明天")) or "-" in body["next_due_label"]


def test_complete_without_checkpoint_id_uses_earliest(client):
    exp = create_experiment(client)
    body = client.post(f"/api/experiments/{exp['id']}/complete", json={}).get_json()
    assert body["checkpoints"][0]["done"] is True


def test_complete_twice_conflicts(client):
    exp = create_experiment(client)
    first = exp["checkpoints"][0]
    client.post(f"/api/experiments/{exp['id']}/complete", json={"checkpoint_id": first["id"]})
    again = client.post(f"/api/experiments/{exp['id']}/complete", json={"checkpoint_id": first["id"]})
    assert again.status_code == 409


def test_reopen_checkpoint(client):
    exp = create_experiment(client)
    first = exp["checkpoints"][0]
    client.post(f"/api/experiments/{exp['id']}/complete", json={"checkpoint_id": first["id"]})
    body = client.post(
        f"/api/experiments/{exp['id']}/checkpoints/{first['id']}/reopen"
    ).get_json()
    assert body["checkpoints"][0]["done"] is False
    assert body["checkpoints"][0]["cell_status"] is None


def test_completing_last_checkpoint_creates_next(client):
    exp = create_experiment(client, started_at=_dt(-1 - 24))
    ids = [cp["id"] for cp in exp["checkpoints"]]
    before = exp["checkpoint_count"]
    for checkpoint_id in ids:
        body = client.post(
            f"/api/experiments/{exp['id']}/complete", json={"checkpoint_id": checkpoint_id}
        ).get_json()
    assert body["checkpoint_count"] > before
    assert body["next_checkpoint"] is not None


def test_paused_experiment_does_not_advance(client):
    exp = create_experiment(client, started_at=_dt(-1 - 24))
    client.patch(f"/api/experiments/{exp['id']}", json={"status": "paused"})
    detail = client.get(f"/api/experiments/{exp['id']}").get_json()
    ids = [cp["id"] for cp in detail["checkpoints"]]
    before = detail["checkpoint_count"]
    for checkpoint_id in ids:
        body = client.post(
            f"/api/experiments/{exp['id']}/complete", json={"checkpoint_id": checkpoint_id}
        ).get_json()
    assert body["checkpoint_count"] == before
    assert body["next_checkpoint"] is None


def test_custom_interval_checkpoint_changes_cycle(client):
    exp = create_experiment(client, started_at=_dt(-1 - 24), interval_value=24, interval_unit="h")
    response = client.post(
        f"/api/experiments/{exp['id']}/checkpoints",
        json={"due_at": _dt(3), "interval_value": 6, "interval_unit": "h"},
    )
    assert response.status_code == 201
    body = response.get_json()
    custom = [cp for cp in body["checkpoints"] if cp["kind"] == "custom"]
    assert len(custom) == 1
    # 自定义点之后自动补的点按 6 小时间隔
    following = [cp for cp in body["checkpoints"] if cp["kind"] == "schedule" and cp["seq"] > custom[0]["seq"]]
    assert following, body["checkpoints"]
    gap = datetime.strptime(following[0]["due_at"], "%Y-%m-%d %H:%M") - datetime.strptime(
        custom[0]["due_at"], "%Y-%m-%d %H:%M"
    )
    assert gap == timedelta(hours=6)


def test_add_and_delete_checkpoint(client):
    exp = create_experiment(client)
    added = client.post(
        f"/api/experiments/{exp['id']}/checkpoints", json={"due_at": _dt(5), "notes": "换液"}
    ).get_json()
    target = [cp for cp in added["checkpoints"] if cp["notes"] == "换液"][0]
    assert target["kind"] == "manual"
    removed = client.delete(
        f"/api/experiments/{exp['id']}/checkpoints/{target['id']}"
    ).get_json()
    assert all(cp["id"] != target["id"] for cp in removed["checkpoints"])


# --------------------------------------------------------------------------
# 手动加点不应触发自动排程（Soft agar 场景回归测试）
# --------------------------------------------------------------------------
def test_manual_checkpoint_does_not_schedule_more(client):
    """加一个手动点（不带间隔），不应自动多排后续检查点。"""
    exp = create_experiment(client)
    before = exp["checkpoint_count"]
    added = client.post(
        f"/api/experiments/{exp['id']}/checkpoints", json={"due_at": _dt(3)}
    ).get_json()
    # 只多出一个（手动加的那个）
    assert added["checkpoint_count"] == before + 1
    manual = [cp for cp in added["checkpoints"] if cp["kind"] == "manual"]
    assert len(manual) == 1


def test_custom_interval_checkpoint_still_schedules(client):
    """带新间隔的自定义点，仍然会自动往后补点（原有行为不变）。"""
    exp = create_experiment(client)
    before = exp["checkpoint_count"]
    added = client.post(
        f"/api/experiments/{exp['id']}/checkpoints",
        json={"due_at": _dt(3), "interval_value": 6, "interval_unit": "h"},
    ).get_json()
    assert added["checkpoint_count"] > before + 1


def test_deleted_checkpoint_stays_deleted(client):
    """删掉的自动补点不会自己长回来。"""
    exp = create_experiment(client)
    auto = exp["checkpoints"][1]
    assert auto["kind"] == "schedule"
    removed = client.delete(f"/api/experiments/{exp['id']}/checkpoints/{auto['id']}").get_json()
    assert all(cp["id"] != auto["id"] for cp in removed["checkpoints"])
    again = client.get(f"/api/experiments/{exp['id']}").get_json()
    assert all(cp["id"] != auto["id"] for cp in again["checkpoints"])


def test_deleting_all_pending_keeps_one(client):
    """删完所有待办时补一个后续点，避免实验变成没有待办。"""
    exp = create_experiment(client)
    body = None
    for cp in list(exp["checkpoints"]):
        body = client.delete(f"/api/experiments/{exp['id']}/checkpoints/{cp['id']}").get_json()
    assert body["next_checkpoint"] is not None


def test_update_checkpoint_time(client):
    exp = create_experiment(client)
    first = exp["checkpoints"][0]
    new_time = _dt(30)
    body = client.patch(
        f"/api/experiments/{exp['id']}/checkpoints/{first['id']}",
        json={"due_at": new_time},
    ).get_json()
    assert body["checkpoints"][0]["due_at"] == new_time


# --------------------------------------------------------------------------
# 提醒汇总
# --------------------------------------------------------------------------
def test_summary_groups_overdue_and_today(client):
    client.post("/api/experiments", json={"name": "逾期实验", "interval_value": 24,
                                          "interval_unit": "h", "started_at": _dt(-5 - 24)})
    client.post("/api/experiments", json={"name": "今日实验", "interval_value": 24,
                                          "interval_unit": "h", "started_at": _dt(1 - 24)})
    client.post("/api/experiments", json={"name": "远期实验", "interval_value": 24,
                                          "interval_unit": "h", "started_at": _dt(24 * 10)})
    data = client.get("/api/experiments/summary").get_json()
    names = [item["experiment_name"] for item in data["overdue"]]
    assert "逾期实验" in names
    assert data["stats"]["overdue_checkpoints"] >= 1
    today_names = [item["experiment_name"] for item in data["due_today"]]
    assert "今日实验" in today_names
    assert all(item["due_label"] for item in data["items"])


def test_summary_ignores_done_and_paused(client):
    exp = create_experiment(client, started_at=_dt(-5 - 24))
    client.patch(f"/api/experiments/{exp['id']}", json={"status": "done"})
    data = client.get("/api/experiments/summary").get_json()
    assert all(item["experiment_id"] != exp["id"] for item in data["items"])


def test_list_scopes(client):
    overdue = create_experiment(client, name="逾期的", started_at=_dt(-3 - 24))
    create_experiment(client, name="远期的", started_at=_dt(24 * 20))
    attention = client.get("/api/experiments?scope=attention").get_json()
    assert [item["id"] for item in attention] == [overdue["id"]]
    assert client.get("/api/experiments?scope=all").get_json()
    search = client.get("/api/experiments?q=逾期").get_json()
    assert len(search) == 1


def test_meta_and_choices(client):
    meta = client.get("/api/meta").get_json()
    assert meta["reminders"]["interval_minutes"] >= 1
    choices = client.get("/api/experiments/meta").get_json()
    assert "良好" in choices["cell_statuses"]
    assert {unit["value"] for unit in choices["interval_units"]} == {"h", "d", "m"}


# --------------------------------------------------------------------------
# 服务层细节
# --------------------------------------------------------------------------
def test_ensure_schedule_is_idempotent(client):
    exp = create_experiment(client)
    detail = client.get(f"/api/experiments/{exp['id']}").get_json()
    count = detail["checkpoint_count"]
    # 列表/详情接口只读，不应该悄悄铺点
    for _ in range(3):
        client.get(f"/api/experiments/{exp['id']}")
    assert client.get(f"/api/experiments/{exp['id']}").get_json()["checkpoint_count"] == count


def test_interval_text_variants():
    assert experiments.interval_text(1, "d") == "1d（每 1 天）"
    assert experiments.interval_text(2, "d") == "2d（每 2 天）"
    assert experiments.interval_text(12, "h") == "12h（每 12 小时）"
    assert experiments.interval_text(48, "h") == "48h（2d · 每 48 小时）"
    assert experiments.interval_text(90, "m") == "90m（每 90 分钟）"
    assert experiments.interval_text(None, None) == "未设置"


def test_due_label_is_human_readable():
    now = datetime(2026, 11, 14, 12, 25)
    assert experiments.due_label(datetime(2026, 11, 14, 9, 0), now) == "今天 09:00"
    assert experiments.due_label(datetime(2026, 11, 15, 10, 30), now) == "明天 10:30"
    assert experiments.due_label(datetime(2026, 11, 18, 14, 0), now) == "11-18 周三 14:00"
    assert experiments.human_gap(datetime(2026, 11, 14, 9, 0), now) == "逾期 3 小时"
    assert experiments.human_gap(datetime(2026, 11, 14, 12, 50), now) == "还有 25 分钟"


def test_human_gap_counts_calendar_days():
    """超过 1 天时按日历天数算：同一天内任何时刻都显示相同的天数。"""
    due = datetime(2026, 11, 23, 22, 0)
    # 11-14 当天不同时刻，都应显示 9 天（不会因为过了 22:00 变 8 天）
    for hour in (8, 12, 21, 22, 23):
        now = datetime(2026, 11, 14, hour, 0)
        assert experiments.human_gap(due, now) == "还有 9 天", f"11-14 {hour}:00"

    # 跨天逐日递减
    assert experiments.human_gap(due, datetime(2026, 11, 15, 12, 0)) == "还有 8 天"
    assert experiments.human_gap(due, datetime(2026, 11, 22, 12, 0)) == "还有 1 天"

    # 当天内不足 1 天，按小时显示
    assert experiments.human_gap(due, datetime(2026, 11, 23, 9, 0)) == "还有 13 小时"


def test_human_gap_overdue_uses_calendar_days():
    due = datetime(2026, 11, 14, 22, 0)
    assert experiments.human_gap(due, datetime(2026, 11, 15, 12, 0)) == "逾期 1 天"
    assert experiments.human_gap(due, datetime(2026, 11, 23, 12, 0)) == "逾期 9 天"
    # 当天内逾期，按小时
    assert experiments.human_gap(due, datetime(2026, 11, 14, 23, 0)) == "逾期 1 小时"


def test_human_gap_hour_interval_shows_hours():
    """按小时计算的实验始终显示小时数，即使超过 24 小时。"""
    now = datetime(2026, 11, 14, 22, 10)
    assert experiments.human_gap(datetime(2026, 11, 15, 10, 10), now, "h") == "还有 12 小时"
    assert experiments.human_gap(datetime(2026, 11, 17, 6, 10), now, "h") == "还有 56 小时"
    # 超过 72 小时时补一个天数，避免「还有 240 小时」这类难读的数字
    assert experiments.human_gap(datetime(2026, 11, 24, 22, 10), now, "h") == "还有 240 小时（10 天）"
    # 不足 1 小时按分钟
    assert experiments.human_gap(datetime(2026, 11, 14, 22, 40), now, "h") == "还有 30 分钟"


def test_human_gap_day_interval_shows_days():
    """按天计算的实验仍按日历天数显示。"""
    now = datetime(2026, 11, 14, 22, 10)
    assert experiments.human_gap(datetime(2026, 11, 23, 22, 0), now, "d") == "还有 9 天"
    assert experiments.human_gap(datetime(2026, 11, 15, 22, 0), now, "d") == "还有 1 天"


def test_parse_dt_accepts_iso_and_timestamps():
    parsed = experiments.parse_dt("2026-11-14T09:30:00")
    assert experiments.fmt_dt(parsed) == "2026-11-14 09:30"
    with pytest.raises(Exception):
        experiments.parse_dt("not a time")


# --------------------------------------------------------------------------
# B：结束实验（原因自填可空，清掉剩余检查点）
# --------------------------------------------------------------------------
def test_finish_experiment_with_custom_reason(client):
    exp = create_experiment(client, started_at=_dt(-30))
    # 先勾一个，保证已完成的记录被保留
    client.post(f"/api/experiments/{exp['id']}/complete", json={})
    response = client.post(
        f"/api/experiments/{exp['id']}/finish",
        json={"status": "done", "end_reason": "细胞污染，提前收尾"},
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    assert body["status"] == "done"
    assert body["end_reason"] == "细胞污染，提前收尾"
    assert body["pending_count"] == 0
    assert body["removed_checkpoints"] >= 1
    # 已勾选的检查记录保留
    assert body["done_count"] >= 1


def test_finish_experiment_reason_is_optional(client):
    exp = create_experiment(client)
    body = client.post(f"/api/experiments/{exp['id']}/finish", json={"status": "aborted"}).get_json()
    assert body["status"] == "aborted"
    assert body["end_reason"] is None
    assert body["pending_count"] == 0


def test_finished_experiment_disappears_from_summary(client):
    exp = create_experiment(client, started_at=_dt(-30))
    client.post(f"/api/experiments/{exp['id']}/finish", json={"status": "done"})
    data = client.get("/api/experiments/summary").get_json()
    assert all(item["experiment_id"] != exp["id"] for item in data["items"])


def test_finish_invalid_status_falls_back_to_done(client):
    exp = create_experiment(client)
    body = client.post(f"/api/experiments/{exp['id']}/finish", json={"status": "weird"}).get_json()
    assert body["status"] == "done"


# --------------------------------------------------------------------------
# D：实验与细胞株 / 培养批次打通
# --------------------------------------------------------------------------
def test_batch_carries_active_experiments(client):
    line = create_line(client, "HeLa")
    batch = client.post("/api/batches", json={
        "cell_line_id": line["id"], "revival_date": "2026-02-01", "initial_pd": 1.0,
        "initial_cell_count": 2.0,
    }).get_json()
    exp = create_experiment(client, name="HeLa 药物处理", cell_line_ids=[line["id"]])

    detail = client.get(f"/api/batches/{batch['id']}").get_json()
    names = [item["name"] for item in detail["batch"]["active_experiments"]]
    assert names == ["HeLa 药物处理"]
    linked = detail["batch"]["active_experiments"][0]
    assert linked["experiment_id"] == exp["id"]
    assert linked["next_due_label"]

    # 细胞株详情里也能看到
    line_detail = client.get(f"/api/cell-lines/{line['id']}").get_json()
    assert [item["name"] for item in line_detail["cell_line"]["active_experiments"]] == ["HeLa 药物处理"]

    # 实验结束后不再出现在批次卡片上
    client.post(f"/api/experiments/{exp['id']}/finish", json={"status": "done"})
    detail = client.get(f"/api/batches/{batch['id']}").get_json()
    assert detail["batch"]["active_experiments"] == []


# --------------------------------------------------------------------------
# G：周视图
# --------------------------------------------------------------------------
def test_week_view_groups_by_day(client):
    now = datetime.now()
    client.post("/api/experiments", json={"name": "今天要做", "interval_value": 24, "interval_unit": "h",
                                          "started_at": _dt(-1)})
    client.post("/api/experiments", json={"name": "很久以后", "interval_value": 24, "interval_unit": "h",
                                          "started_at": _dt(24 * 60)})
    data = client.get("/api/experiments/week").get_json()
    assert len(data["days"]) == 7
    assert data["start"] <= data["today"] <= data["end"]
    # 每一天都有固定字段，前端可以直接渲染
    for day in data["days"]:
        assert {"date", "weekday", "is_today", "items", "pending_count"} <= set(day)
    today_items = [item for day in data["days"] for item in day["items"]]
    assert any(item["experiment_name"] == "今天要做" for item in today_items)
    assert all(item["experiment_name"] != "很久以后" for item in today_items)


def test_week_view_accepts_start_and_navigation(client):
    data = client.get("/api/experiments/week?start=2026-03-04").get_json()
    assert data["start"] == "2026-03-02"  # 自动对齐到周一
    assert data["end"] == "2026-03-08"
    assert data["prev_start"] < data["start"] < data["next_start"]


# --------------------------------------------------------------------------
# 月视图（检查点 + 传代待办）
# --------------------------------------------------------------------------
def test_month_view_grid_and_checks(client):
    data = client.get("/api/experiments/month").get_json()
    assert data["month"] == datetime.now().strftime("%Y-%m")
    # 6 行 × 7 列，周一起始
    assert len(data["days"]) == 42
    assert data["days"][0]["weekday"] == 0
    assert any(day["is_today"] for day in data["days"])
    # 当月天数正确（含闰年判断交给 date 自己）
    in_month = [day for day in data["days"] if day["in_month"]]
    assert 28 <= len(in_month) <= 31


def test_month_view_accepts_month_param(client):
    data = client.get("/api/experiments/month?month=2026-02").get_json()
    assert data["month"] == "2026-02"
    assert data["prev_month"] == "2026-01"
    assert data["next_month"] == "2026-03"
    assert len([day for day in data["days"] if day["in_month"]]) == 28


def test_month_view_includes_passage_todos(client):
    line = create_line(client, "HeLa")
    today = datetime.now().strftime("%Y-%m-%d")
    batch = client.post("/api/batches", json={
        "cell_line_id": line["id"], "revival_date": "2026-02-01", "initial_pd": 1.0,
        "initial_cell_count": 2.0,
    }).get_json()
    # 建一条活跃传代记录，建议下次传代 = 今天
    client.post("/api/records", json={
        "batch_id": batch["id"], "date": today, "harvested_cells": 4.0,
        "inoculum_dishes": 2, "per_dish_cells": 1.0, "status": "良好",
        "next_passage_date": today, "notes": "",
    })
    data = client.get("/api/experiments/month").get_json()
    today_cell = next(day for day in data["days"] if day["is_today"])
    assert today_cell["passage_count"] >= 1
    names = [item["batch_name"] for item in today_cell["passages"]]
    assert batch["batch_name"] in names
    assert data["totals"]["passages"] >= 1


def test_month_view_rejects_bad_month(client):
    assert client.get("/api/experiments/month?month=abc").status_code == 400


def test_month_view_shows_todos_outside_current_month(client):
    """加在下个月/上个月的待办，在月视图的非本月格子里也要能看到。

    月视图是 6×7=42 格，会露出上月末和下月初的日期，
    查询范围必须覆盖整个格子范围，而不只是本月 1 号到月末。
    """
    # 2026-11 的格子范围是 10-26 ~ 12-06
    for title, due in [
        ("下月待办", "2026-12-03"),
        ("上月待办", "2026-10-28"),
        ("本月待办", "2026-11-20"),
    ]:
        assert client.post("/api/todos", json={"title": title, "due_date": due}).status_code == 201

    data = client.get("/api/experiments/month?month=2026-11").get_json()
    found = {day["date"]: [t["title"] for t in (day.get("todos") or [])] for day in data["days"]}

    assert found.get("2026-12-03") == ["下月待办"], "下月格子的待办应可见"
    assert found.get("2026-10-28") == ["上月待办"], "上月格子的待办应可见"
    assert found.get("2026-11-20") == ["本月待办"]


def test_month_view_shows_checks_outside_current_month(client):
    """跨月实验的检查点，落在非本月格子里也要能看到。"""
    assert client.post("/api/experiments", json={
        "name": "跨月实验", "notes": "", "started_at": "2026-12-01 09:00",
        "interval_value": 1, "interval_unit": "d",
    }).status_code == 201

    data = client.get("/api/experiments/month?month=2026-11").get_json()
    outside = [day for day in data["days"] if not day["in_month"] and day.get("checks")]
    assert outside, "12 月初的检查点应出现在 11 月视图的非本月格子里"
    assert any("跨月实验" in [c["experiment_name"] for c in day["checks"]] for day in outside)


# --------------------------------------------------------------------------
# 推迟 / 删除检查点（月视图、周视图里的待办操作）
# --------------------------------------------------------------------------
def test_postpone_checkpoint_one_day(client):
    exp = create_experiment(client, started_at=_dt(-30))
    cp = exp["checkpoints"][0]
    response = client.post(
        f"/api/experiments/{exp['id']}/checkpoints/{cp['id']}/postpone", json={"days": 1}
    )
    assert response.status_code == 200, response.get_json()
    body = response.get_json()
    moved = next(item for item in body["checkpoints"] if item["id"] == cp["id"])
    gap = datetime.strptime(moved["due_at"], "%Y-%m-%d %H:%M") - datetime.strptime(
        cp["due_at"], "%Y-%m-%d %H:%M"
    )
    assert gap == timedelta(days=1)
    # 时间点用钟点不变，只是日期后移
    assert moved["due_clock"] == cp["due_clock"]


def test_postpone_defaults_to_one_day(client):
    exp = create_experiment(client, started_at=_dt(-30))
    cp = exp["checkpoints"][0]
    body = client.post(
        f"/api/experiments/{exp['id']}/checkpoints/{cp['id']}/postpone", json={}
    ).get_json()
    moved = next(item for item in body["checkpoints"] if item["id"] == cp["id"])
    assert moved["due_date"] > cp["due_date"]


def test_postpone_rejects_bad_days(client):
    exp = create_experiment(client)
    cp = exp["checkpoints"][0]
    url = f"/api/experiments/{exp['id']}/checkpoints/{cp['id']}/postpone"
    assert client.post(url, json={"days": 0}).status_code == 400
    assert client.post(url, json={"days": 999}).status_code == 400


def test_cannot_postpone_done_checkpoint(client):
    exp = create_experiment(client)
    cp = exp["checkpoints"][0]
    client.post(f"/api/experiments/{exp['id']}/complete", json={"checkpoint_id": cp["id"]})
    url = f"/api/experiments/{exp['id']}/checkpoints/{cp['id']}/postpone"
    assert client.post(url, json={"days": 1}).status_code == 409


def test_delete_checkpoint_from_calendar(client):
    exp = create_experiment(client, started_at=_dt(-30))
    cp = exp["checkpoints"][0]
    body = client.delete(f"/api/experiments/{exp['id']}/checkpoints/{cp['id']}").get_json()
    assert all(item["id"] != cp["id"] for item in body["checkpoints"])
    # 删掉后仍保证有下一个待办
    assert body["next_checkpoint"] is not None or body["status"] != "active"


# --------------------------------------------------------------------------
# 实际间隔记录（提前 / 延后检查）
# --------------------------------------------------------------------------
def test_actual_span_on_time(client):
    """按时检查：实际间隔等于设定间隔，偏差为「准时」。"""
    started = datetime.now() - timedelta(hours=25)
    exp = create_experiment(client, started_at=started.strftime("%Y-%m-%d %H:%M"),
                            interval_value=24, interval_unit="h")
    cp = exp["checkpoints"][0]
    # 按计划时间勾选（不传 done_at 时按计划时间计）
    body = client.post(f"/api/experiments/{exp['id']}/complete", json={"checkpoint_id": cp["id"]}).get_json()
    done = next(item for item in body["checkpoints"] if item["id"] == cp["id"])
    assert done["actual_span_minutes"] == 24 * 60
    assert done["actual_span_text"] == "1 天"
    assert done["actual_from"] == "实验开始"
    assert done["deviation_kind"] == "on_time"
    assert done["interval_delta_text"] == "与设定间隔一致"


def test_actual_span_when_checked_early(client):
    """提前检查：实际间隔变短，标记为「提前」。

    实验开始于 30 小时前 → 计划检查在 6 小时前；实际 8 小时前就查了 = 提前 2 小时。
    """
    started = datetime.now() - timedelta(hours=30)
    exp = create_experiment(client, started_at=started.strftime("%Y-%m-%d %H:%M"),
                            interval_value=24, interval_unit="h")
    cp = exp["checkpoints"][0]
    early = datetime.now() - timedelta(hours=8)
    body = client.post(
        f"/api/experiments/{exp['id']}/complete",
        json={"checkpoint_id": cp["id"], "done_at": early.strftime("%Y-%m-%d %H:%M")},
    ).get_json()
    done = next(item for item in body["checkpoints"] if item["id"] == cp["id"])
    assert done["actual_span_minutes"] == 22 * 60
    assert done["actual_span_text"] == "22 小时"
    assert done["deviation_kind"] == "early"
    assert "提前" in done["deviation_text"]
    assert "短" in done["interval_delta_text"]


def test_actual_span_when_checked_late(client):
    """延后检查：实际间隔变长，标记为「延后」。"""
    started = datetime.now() - timedelta(hours=40)
    exp = create_experiment(client, started_at=started.strftime("%Y-%m-%d %H:%M"),
                            interval_value=24, interval_unit="h")
    cp = exp["checkpoints"][0]
    late = datetime.now() - timedelta(hours=2)
    body = client.post(
        f"/api/experiments/{exp['id']}/complete",
        json={"checkpoint_id": cp["id"], "done_at": late.strftime("%Y-%m-%d %H:%M")},
    ).get_json()
    done = next(item for item in body["checkpoints"] if item["id"] == cp["id"])
    assert done["actual_span_minutes"] == 38 * 60
    assert done["deviation_kind"] == "late"
    assert "延后" in done["deviation_text"]
    assert "长" in done["interval_delta_text"]


def test_second_checkpoint_measures_from_previous_check(client):
    """第二次检查的实际间隔，以上一次实际检查为基准。"""
    started = datetime.now() - timedelta(hours=50)
    exp = create_experiment(client, started_at=started.strftime("%Y-%m-%d %H:%M"),
                            interval_value=24, interval_unit="h")
    first, second = exp["checkpoints"][0], exp["checkpoints"][1]
    t1 = datetime.now() - timedelta(hours=26)
    t2 = datetime.now() - timedelta(hours=6)
    client.post(f"/api/experiments/{exp['id']}/complete",
                json={"checkpoint_id": first["id"], "done_at": t1.strftime("%Y-%m-%d %H:%M")})
    body = client.post(f"/api/experiments/{exp['id']}/complete",
                       json={"checkpoint_id": second["id"], "done_at": t2.strftime("%Y-%m-%d %H:%M")}).get_json()
    done2 = next(item for item in body["checkpoints"] if item["id"] == second["id"])
    assert done2["actual_from"] == "上次检查"
    assert done2["actual_span_minutes"] == 20 * 60


def test_pending_checkpoint_has_no_actual_span(client):
    exp = create_experiment(client)
    pending = exp["checkpoints"][0]
    assert pending["actual_span_minutes"] is None
    assert pending["deviation_kind"] is None


# --------------------------------------------------------------------------
# 手动/补检查点不应被当成循环起点（soft agar 场景回归）
# --------------------------------------------------------------------------
def test_completing_manual_checkpoint_does_not_schedule(client):
    """勾选手动加的点后，不应自动生成后续计划点。"""
    exp = create_experiment(client)
    eid = exp["id"]

    # 手动加两个远期点（不带间隔）
    client.post(f"/api/experiments/{eid}/checkpoints", json={"due_at": _dt(24 * 9)})
    added = client.post(f"/api/experiments/{eid}/checkpoints", json={"due_at": _dt(24 * 19)}).get_json()
    before = added["checkpoint_count"]

    # 勾选第一个（不是最后一个自动点）
    first = [cp for cp in added["checkpoints"] if not cp["done"]][0]
    result = client.post(f"/api/experiments/{eid}/complete",
                         json={"checkpoint_id": first["id"]}).get_json()

    assert result["checkpoint_count"] == before, "勾选手动点不应生成新检查点"


def test_completing_last_auto_checkpoint_advances(client):
    """勾选最后一个自动排程点时，仍应正常推进一个。"""
    exp = create_experiment(client)
    eid = exp["id"]
    # 加一个手动点，使它排在自动点之后
    added = client.post(f"/api/experiments/{eid}/checkpoints",
                        json={"due_at": _dt(24 * 30)}).get_json()
    before = added["checkpoint_count"]

    auto = [cp for cp in added["checkpoints"]
            if cp["kind"] in ("schedule", "custom", "followup") and not cp["done"]]
    last_auto = auto[-1]
    result = client.post(f"/api/experiments/{eid}/complete",
                         json={"checkpoint_id": last_auto["id"]}).get_json()

    assert result["checkpoint_count"] == before + 1, "勾最后一个自动点应推进一个"


def test_completing_manual_checkpoint_when_no_auto_left(client):
    """自动点都勾完后，勾手动点不应重新铺排程。"""
    exp = create_experiment(client)
    eid = exp["id"]
    added = client.post(f"/api/experiments/{eid}/checkpoints",
                        json={"due_at": _dt(24 * 40)}).get_json()

    # 勾完所有自动点
    for cp in [c for c in added["checkpoints"] if c["kind"] != "manual"]:
        current = client.get(f"/api/experiments/{eid}").get_json()
        target = [c for c in current["checkpoints"] if c["id"] == cp["id"]]
        if target and not target[0]["done"]:
            client.post(f"/api/experiments/{eid}/complete", json={"checkpoint_id": cp["id"]})

    before = client.get(f"/api/experiments/{eid}").get_json()["checkpoint_count"]
    manual = [c for c in client.get(f"/api/experiments/{eid}").get_json()["checkpoints"]
              if c["kind"] == "manual" and not c["done"]]
    assert manual, "应还有一个手动点"
    result = client.post(f"/api/experiments/{eid}/complete",
                         json={"checkpoint_id": manual[0]["id"]}).get_json()
    assert result["checkpoint_count"] == before


def test_renaming_experiment_does_not_add_checkpoints(client):
    """只改名字不应触发生成新检查点。"""
    exp = create_experiment(client)
    eid = exp["id"]
    client.post(f"/api/experiments/{eid}/checkpoints", json={"due_at": _dt(24 * 12)})
    before = client.get(f"/api/experiments/{eid}").get_json()["checkpoint_count"]
    after = client.patch(f"/api/experiments/{eid}", json={"name": "改个名字"}).get_json()
    assert after["checkpoint_count"] == before
