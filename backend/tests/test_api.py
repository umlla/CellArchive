"""API 端到端测试（Flask test client + 临时数据库）。"""

from __future__ import annotations

import io

import pytest
from openpyxl import Workbook, load_workbook

from backend import db
from backend.services import maintenance

from .conftest import add_record, create_batch, create_line


# --------------------------------------------------------------------------
# 基础与细胞株
# --------------------------------------------------------------------------
def test_meta_and_dashboard_empty(client):
    meta = client.get("/api/meta").get_json()
    assert meta["app_version"].startswith("4.")
    assert meta["counts"]["cell_lines"] == 0
    dashboard = client.get("/api/dashboard").get_json()
    assert dashboard["stats"]["active_batches"] == 0
    assert dashboard["today"]


def test_cell_line_crud_and_conflict(client):
    line = create_line(client, "HeLa", interval=3)
    assert line["name"] == "HeLa"
    assert line["default_passage_interval"] == 3

    duplicate = client.post("/api/cell-lines", json={"name": "HeLa"})
    assert duplicate.status_code == 409

    updated = client.patch(f"/api/cell-lines/{line['id']}", json={"name": "HeLa-S3"})
    assert updated.status_code == 200
    assert updated.get_json()["name"] == "HeLa-S3"

    listing = client.get("/api/cell-lines?search=HeLa").get_json()
    assert [item["name"] for item in listing] == ["HeLa-S3"]

    deleted = client.delete(f"/api/cell-lines/{line['id']}")
    assert deleted.status_code == 200
    assert client.get(f"/api/cell-lines/{line['id']}").status_code == 404


def test_create_line_requires_name(client):
    response = client.post("/api/cell-lines", json={"type": "永生化"})
    assert response.status_code == 400
    assert response.get_json()["error"]["code"] == "validation_error"


# --------------------------------------------------------------------------
# 物种标签与配色
# --------------------------------------------------------------------------
def test_line_species_is_free_text(client):
    line = create_line(client, "HeLa", species="抹香鲸")
    # 物种不预设，原样保存，不做任何归一
    assert line["species"] == "抹香鲸"
    updated = client.patch(f"/api/cell-lines/{line['id']}", json={"species": "Whale X"})
    assert updated.get_json()["species"] == "Whale X"
    cleared = client.patch(f"/api/cell-lines/{line['id']}", json={"species": ""})
    assert cleared.get_json()["species"] is None
    # 接口不再下发任何预设物种列表
    assert "species_choices" not in client.get("/api/meta").get_json()


def test_adding_species_does_not_recolor_existing(client):
    """新增物种时，已有物种的颜色必须保持不变（不能整体重排）。"""
    first = create_line(client, "样本甲-1", species="抹香鲸")
    second = create_line(client, "样本乙-2", species="人")

    def colors():
        palette = client.get("/api/meta").get_json()["species_colors"]
        return {item["cell_line_id"]: item["color"] for item in palette["lines"]}

    before = colors()
    create_line(client, "新物种样本", species="全新物种")
    after = colors()
    # 老细胞株的颜色一个都不能变
    assert after[first["id"]] == before[first["id"]]
    assert after[second["id"]] == before[second["id"]]


def test_species_colors_are_stable_and_grouped(client):
    human_a = create_line(client, "HeLa", species="人")
    human_b = create_line(client, "A549", species="人")
    mouse = create_line(client, "NIH3T3", species="小鼠")

    palette = client.get("/api/meta").get_json()["species_colors"]
    colors = {item["cell_line_id"]: item["color"] for item in palette["lines"]}
    # 颜色只由「物种 + 细胞株」决定，多次请求完全一致
    again = client.get("/api/meta").get_json()["species_colors"]
    assert colors == {item["cell_line_id"]: item["color"] for item in again["lines"]}

    def hue_of(hex_color):
        value = hex_color.lstrip("#")
        red, green, blue = (int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))
        high, low = max(red, green, blue), min(red, green, blue)
        delta = high - low
        if delta == 0:
            return 0.0
        if high == red:
            return (60 * ((green - blue) / delta)) % 360
        if high == green:
            return 60 * ((blue - red) / delta) + 120
        return 60 * ((red - green) / delta) + 240

    def hue_distance(first, second):
        diff = abs(first - second) % 360
        return min(diff, 360 - diff)

    human_colors = [colors[human_a["id"]], colors[human_b["id"]]]
    mouse_color = colors[mouse["id"]]
    human_hues = [hue_of(color) for color in human_colors]
    mouse_hue = hue_of(mouse_color)
    # 同物种：色相相近（同一区间内）
    assert abs(human_hues[0] - human_hues[1]) < 40
    # 不同物种：色相落在不同区间，至少隔开一个槽位宽度的 60%
    assert min(hue_distance(hue, mouse_hue) for hue in human_hues) > 13.5


def test_bulk_assign_species_keeps_existing(client):
    first = create_line(client, "HeLa", species="人")
    second = create_line(client, "NIH3T3")
    result = client.post("/api/cell-lines/species", json={"species": "小鼠", "only_unset": True})
    assert result.status_code == 200
    assert result.get_json()["updated"] == 1
    listing = {item["name"]: item["species"] for item in client.get("/api/cell-lines").get_json()}
    # 默认只补未标注的，已单独设置的人不会被覆盖
    assert listing["HeLa"] == "人"
    assert listing["NIH3T3"] == "小鼠"
    assert first["species"] == "人" and second["species"] is None


def test_species_entries_written_per_row(client):
    """物种标签是自由文本，按行分别写入。"""
    first = create_line(client, "样本甲-1")
    second = create_line(client, "样本乙-2")
    result = client.post("/api/cell-lines/species", json={"entries": [
        {"id": first["id"], "species": "标签甲"},
        {"id": second["id"], "species": "标签乙"},
    ]})
    assert result.status_code == 200
    assert result.get_json()["updated"] == 2
    listing = {item["name"]: item["species"] for item in client.get("/api/cell-lines").get_json()}
    assert listing["样本甲-1"] == "标签甲"
    assert listing["样本乙-2"] == "标签乙"


def test_species_is_free_text(client):
    """物种不预设任何选项，用户输入什么就存什么。"""
    line = create_line(client, "自由标签细胞", species="任意自定义标签")
    assert line["species"] == "任意自定义标签"

    updated = client.patch(f"/api/cell-lines/{line['id']}", json={"species": "另一个标签"})
    assert updated.status_code == 200
    assert updated.get_json()["species"] == "另一个标签"

    # 不提供预设列表
    assert "species_choices" not in client.get("/api/meta").get_json()


def test_each_species_gets_its_own_hue_band(client):
    names = ["标签甲", "标签乙", "标签丙", "标签丁"]
    for index, species in enumerate(names):
        create_line(client, f"L{index}-a", species=species)
        create_line(client, f"L{index}-b", species=species)
    palette = client.get("/api/meta").get_json()["species_colors"]
    bands = {}
    for item in palette["lines"]:
        bands.setdefault(item["species"], set()).add(item["color"])
    # 每个标签都有颜色，且同标签两株颜色不同（同色系但可区分）
    assert all(len(colors) == 2 for colors in bands.values())
    # 不同标签之间不共享任何颜色
    all_colors = [color for colors in bands.values() for color in colors]
    assert len(all_colors) == len(set(all_colors))


def test_group_charts_reuse_cell_line_color(client):
    line = create_line(client, "HeLa", species="人")
    batch_one = create_batch(client, line["id"])
    batch_two = create_batch(client, line["id"], revival_date="2026-03-01")
    add_record(client, batch_one["id"])
    add_record(client, batch_two["id"])
    group = client.post("/api/groups", json={"group_name": "G", "cell_line_ids": [line["id"]]})
    group_id = group.get_json()["id"]

    rates = client.get(f"/api/groups/{group_id}/rates").get_json()
    curves = client.get(f"/api/groups/{group_id}/curves").get_json()
    compare = client.get(f"/api/compare/curves?line_ids={line['id']}").get_json()
    palette = client.get("/api/meta").get_json()["species_colors"]
    base = next(item["color"] for item in palette["lines"] if item["cell_line_id"] == line["id"])

    # 增殖速率柱与累计 PD 曲线：同一细胞株同一颜色，多批次只差深浅
    assert len(rates) == 2
    assert all(row["species"] == "人" for row in rates)
    assert base in {row["color"] for row in rates}
    assert all(row["color"].startswith("#") for row in rates)
    assert all(item["species"] == "人" for item in curves["series"])
    assert base in {item["color"] for item in curves["series"]}
    # 对比页同样是同细胞株同色系：首批次用主色，其余批次是主色的浅色
    assert base in {item["color"] for item in compare["series"]}
    assert len({item["color"] for item in compare["series"]}) == 2


# --------------------------------------------------------------------------
# 批次与传代记录
# --------------------------------------------------------------------------
def test_batch_and_record_pd_flow(client):
    line = create_line(client)
    batch = create_batch(client, line["id"])
    assert batch["batch_name"] == f"{line['name']}-260201"

    first = add_record(client, batch["id"])
    assert first["pd"] == pytest.approx(1.0)
    assert first["cumulative_pd"] == pytest.approx(2.0)  # 初始 PD 1 + 1
    assert first["inoculum_cells"] == pytest.approx(2.0)
    assert first["next_passage_date"] == "2026-02-04"
    assert first["is_active"] == 1

    second = add_record(client, batch["id"], date="2026-02-04", harvested_cells=8.0,
                        next_passage_days=0)
    assert second["pd"] == pytest.approx(2.0)
    assert second["cumulative_pd"] == pytest.approx(4.0)

    detail = client.get(f"/api/batches/{batch['id']}").get_json()
    assert len(detail["records"]) == 2
    assert detail["records"][0]["per_dish_cells"] == pytest.approx(1.0)
    active = [record for record in detail["records"] if record["is_active"] == 1]
    assert len(active) == 1
    assert active[0]["id"] == second["id"]
    assert detail["summary"]["cumulative_pd"] == pytest.approx(4.0)

    # 编辑第 1 条记录后整批重算：pd1=2, cum1=3；pd2=2, cum2=5
    updated = client.patch(f"/api/records/{first['id']}", json={
        "harvested_cells": 8.0, "per_dish_cells": 1.0, "next_passage_days": 0,
    })
    assert updated.status_code == 200
    records = client.get(f"/api/batches/{batch['id']}/records").get_json()
    assert [record["cumulative_pd"] for record in records] == pytest.approx([3.0, 5.0])

    # 删除第 2 条后，活跃记录回到第 1 条
    assert client.delete(f"/api/records/{second['id']}").status_code == 200
    records = client.get(f"/api/batches/{batch['id']}/records").get_json()
    assert len(records) == 1
    assert records[0]["is_active"] == 1

    # 终止批次后不能再加记录
    terminated = client.post(f"/api/batches/{batch['id']}/terminate", json={"reason": "污染"})
    assert terminated.status_code == 200
    assert terminated.get_json()["is_active"] == 0
    assert client.post("/api/records", json={
        "batch_id": batch["id"], "harvested_cells": 1,
    }).status_code == 409


def test_compare_curves_across_cell_lines(client):
    line_a = create_line(client, "HeLa")
    line_b = create_line(client, "A549")
    line_c = create_line(client, "MCF-7")
    batch_a = create_batch(client, line_a["id"])
    batch_b = create_batch(client, line_b["id"])
    batch_c = create_batch(client, line_c["id"], revival_date="2026-03-01")

    add_record(client, batch_a["id"], date="2026-02-02", harvested_cells=4.0)
    add_record(client, batch_a["id"], date="2026-02-04", harvested_cells=8.0, next_passage_days=0)
    add_record(client, batch_b["id"], date="2026-02-03", harvested_cells=8.0)
    add_record(client, batch_c["id"], date="2026-02-05", harvested_cells=16.0)

    # 只选两个细胞株，第三个不应出现
    response = client.get(f"/api/compare/curves?line_ids={line_a['id']},{line_b['id']}")
    assert response.status_code == 200
    body = response.get_json()
    names = [item["cell_line"] for item in body["series"]]
    assert names == ["HeLa", "A549"]
    assert body["dates"] == ["2026-02-02", "2026-02-03", "2026-02-04"]
    assert body["series"][0]["points"][0]["value"] == pytest.approx(2.0)
    assert body["series"][0]["points"][0]["day"] == 0
    assert body["series"][0]["points"][1]["day"] == 2

    # PD/天 与倍增时间：首条记录没有上一次接种，无法计算；第二条 pd=2、间隔 2 天
    hela_points = body["series"][0]["points"]
    assert hela_points[0]["pd_per_day"] is None
    assert hela_points[0]["doubling_hours"] is None
    assert hela_points[1]["pd_per_day"] == pytest.approx(1.0)
    assert hela_points[1]["doubling_hours"] == pytest.approx(24.0)
    hela_series = body["series"][0]
    assert hela_series["avg_pd_per_day"] == pytest.approx(1.0)
    assert hela_series["avg_doubling_hours"] == pytest.approx(24.0)
    assert hela_series["overall_pd_per_day"] == pytest.approx(1.0)
    assert hela_series["overall_doubling_hours"] == pytest.approx(24.0)

    # 按培养天数对齐时，每个点带 day 字段
    elapsed = client.get(
        f"/api/compare/curves?line_ids={line_a['id']},{line_c['id']}&basis=elapsed"
    ).get_json()
    assert elapsed["basis"] == "elapsed"
    assert elapsed["series"][1]["points"][0]["day"] == 0

    # 标准化 = 2^(ΔPD)：HeLa 基准日累计 PD 2，次日 4 -> 扩增 4 倍
    normalized = client.get(
        f"/api/compare/curves?line_ids={line_a['id']},{line_b['id']}"
        f"&normalize=true&start_date=2026-02-02"
    ).get_json()
    assert normalized["normalize"] is True
    hela = normalized["series"][0]
    assert hela["points"][0]["value"] == pytest.approx(1.0)
    assert hela["points"][1]["value"] == pytest.approx(4.0)
    assert hela["points"][1]["fold"] == pytest.approx(4.0)
    # 基准点重新计为第 0 天
    assert hela["points"][0]["day"] == 0
    assert hela["points"][1]["day"] == 2

    # 起始日当天没有记录时，向后找最近一条作为基准（不再整批丢弃）
    shifted = client.get(
        f"/api/compare/curves?line_ids={line_a['id']},{line_b['id']}"
        f"&normalize=true&start_date=2026-02-03"
    ).get_json()
    names = [item["cell_line"] for item in shifted["series"]]
    assert names == ["HeLa", "A549"]
    a549 = shifted["series"][1]
    assert a549["points"][0]["date"] == "2026-02-03"
    assert a549["points"][0]["value"] == pytest.approx(1.0)

    # 起始日晚于全部记录时跳过并给出原因
    late = client.get(
        f"/api/compare/curves?line_ids={line_a['id']}&normalize=true&start_date=2026-12-01"
    ).get_json()
    assert late["series"] == []
    assert "没有记录" in late["skipped"][0]["reason"]

    # 缺少起始日期 / 没选细胞株时给出明确错误
    assert client.get(f"/api/compare/curves?line_ids={line_a['id']}&normalize=true").status_code == 400
    assert client.get("/api/compare/curves").status_code == 400

    # 默认不包含已终止批次，显式开启后才包含
    client.post(f"/api/batches/{batch_b['id']}/terminate", json={"reason": "其他"})
    default_body = client.get(f"/api/compare/curves?line_ids={line_b['id']}").get_json()
    assert default_body["series"] == []
    ended_body = client.get(
        f"/api/compare/curves?line_ids={line_b['id']}&include_ended=true"
    ).get_json()
    assert len(ended_body["series"]) == 1
    assert ended_body["series"][0]["ended"] is True


def test_restore_terminated_batch(client):
    line = create_line(client)
    batch = create_batch(client, line["id"])
    first = add_record(client, batch["id"])
    second = add_record(client, batch["id"], date="2026-02-04", harvested_cells=8.0, next_passage_days=0)

    assert client.post(f"/api/batches/{batch['id']}/terminate", json={"reason": "其他"}).status_code == 200
    ended = client.get(f"/api/batches/{batch['id']}").get_json()["batch"]
    assert ended["is_active"] == 0
    assert ended["end_reason"] == "其他"
    assert client.post("/api/records", json={"batch_id": batch["id"], "harvested_cells": 1}).status_code == 409

    restored = client.post(f"/api/batches/{batch['id']}/restore")
    assert restored.status_code == 200
    body = restored.get_json()
    assert body["is_active"] == 1
    assert body["end_date"] is None
    assert body["end_reason"] is None
    assert body["current_record"]["id"] == second["id"]

    records = client.get(f"/api/batches/{batch['id']}/records").get_json()
    active = [record for record in records if record["is_active"] == 1]
    assert [record["id"] for record in active] == [second["id"]]
    assert first["id"] in [record["id"] for record in records]

    # 恢复后可以继续录入
    assert client.post("/api/records", json={
        "batch_id": batch["id"], "harvested_cells": 4.0,
    }).status_code == 201

    # 活跃批次再次恢复会提示冲突
    assert client.post(f"/api/batches/{batch['id']}/restore").status_code == 409


def test_record_with_negative_pd_keeps_cumulative(client):
    line = create_line(client)
    batch = create_batch(client, line["id"])
    add_record(client, batch["id"], harvested_cells=4.0)  # pd=1, cum=2
    negative = add_record(client, batch["id"], date="2026-02-05", harvested_cells=1.0)
    assert negative["pd"] == pytest.approx(-1.0)  # log2(1 / 上次接种 2)
    assert negative["cumulative_pd"] == pytest.approx(2.0)


def test_bulk_create_reports_per_row_errors(client):
    line = create_line(client)
    batch_a = create_batch(client, line["id"])
    batch_b = create_batch(client, line["id"], revival_date="2026-03-01")

    response = client.post("/api/records/bulk", json={"entries": [
        {"batch_id": batch_a["id"], "date": "2026-02-02", "harvested_cells": 4.0,
         "inoculum_dishes": 1, "per_dish_cells": 2.0},
        {"batch_id": batch_b["id"], "date": "2026-02-02", "harvested_cells": None},
    ]})
    body = response.get_json()
    assert response.status_code == 200
    assert body["success"] == 1
    assert body["failed"] == 1
    assert body["results"][1]["ok"] is False
    assert len(client.get(f"/api/batches/{batch_b['id']}/records").get_json()) == 0


def test_bulk_update_recalculates(client):
    line = create_line(client)
    batch = create_batch(client, line["id"])
    first = add_record(client, batch["id"])
    second = add_record(client, batch["id"], date="2026-02-06", harvested_cells=6.0)

    response = client.post("/api/records/bulk-update", json={"entries": [
        {"id": first["id"], "harvested_cells": 4.0, "per_dish_cells": 1.0},
        {"id": second["id"], "harvested_cells": 16.0},
    ]})
    assert response.status_code == 200
    assert response.get_json()["success"] == 2
    records = client.get(f"/api/batches/{batch['id']}/records").get_json()
    # pd1 = 1, cum=2；pd2 = log2(16/2)=3，cum=5
    assert [record["cumulative_pd"] for record in records] == pytest.approx([2.0, 5.0])


def test_record_can_create_freeze_vials(client):
    line = create_line(client, "冻存联动细胞", type_="永生化")
    batch = create_batch(client, line["id"])
    record = add_record(
        client,
        batch["id"],
        harvested_cells=4.0,
        freeze_vials={"enabled": True, "cell_count_per_vial": 5.0, "count": 2, "include_pd": True},
    )
    assert record["vials_count"] == 2
    assert len(record["vials_created"]) == 2

    vials = client.get(f"/api/vials?cell_line_id={line['id']}").get_json()
    assert len(vials) == 2
    for vial in vials:
        assert vial["freeze_date"] == "2026-02-02"  # 与传代日期一致
        assert vial["cell_count"] == pytest.approx(5.0)
        assert vial["pd"] == pytest.approx(2.0)  # 初始 PD 1 + 本次 1
        assert vial["location"] == ""
        assert vial["status"] == "在库"
        assert vial["batch_id"] == batch["id"]
        assert "P1" in vial["notes"]


def test_immortalized_can_skip_pd_but_primary_cannot(client):
    immortal = create_line(client, "永生化细胞", type_="永生化")
    immortal_batch = create_batch(client, immortal["id"])
    record = add_record(
        client,
        immortal_batch["id"],
        freeze_vials={"enabled": True, "cell_count_per_vial": 1.0, "count": 1, "include_pd": False},
    )
    assert record["vials_count"] == 1
    vial = client.get(f"/api/vials?cell_line_id={immortal['id']}").get_json()[0]
    assert vial["pd"] is None

    primary = create_line(client, "原代细胞", type_="原代")
    primary_batch = create_batch(client, primary["id"])
    primary_record = add_record(
        client,
        primary_batch["id"],
        freeze_vials={"enabled": True, "cell_count_per_vial": 2.0, "count": 1, "include_pd": False},
    )
    assert primary_record["vials_count"] == 1
    primary_vial = client.get(f"/api/vials?cell_line_id={primary['id']}").get_json()[0]
    assert primary_vial["pd"] == pytest.approx(2.0)


def test_freeze_vials_validation_and_bulk(client):
    line = create_line(client, "批量冻存细胞")
    batch = create_batch(client, line["id"])

    missing = client.post("/api/records", json={
        "batch_id": batch["id"], "harvested_cells": 4.0,
        "freeze_vials": {"enabled": True, "count": 1},
    })
    assert missing.status_code == 400
    assert "每管冻存细胞数" in missing.get_json()["error"]["message"]

    zero_count = client.post("/api/records", json={
        "batch_id": batch["id"], "harvested_cells": 4.0,
        "freeze_vials": {"enabled": True, "cell_count_per_vial": 1.0, "count": 0},
    })
    assert zero_count.status_code == 400

    bulk = client.post("/api/records/bulk", json={"entries": [
        {"batch_id": batch["id"], "date": "2026-02-03", "harvested_cells": 8.0,
         "freeze_vials": {"enabled": True, "cell_count_per_vial": 3.0, "count": 2}},
        {"batch_id": batch["id"], "date": "2026-02-05", "harvested_cells": 8.0},
    ]})
    assert bulk.status_code == 200
    body = bulk.get_json()
    assert body["success"] == 2
    assert body["vials_created"] == 2
    assert body["results"][0]["vials_created"] == 2
    assert body["results"][1]["vials_created"] == 0
    assert len(client.get(f"/api/vials?cell_line_id={line['id']}").get_json()) == 2


def test_batch_csv_export(client):
    line = create_line(client)
    batch = create_batch(client, line["id"])
    add_record(client, batch["id"])
    response = client.get(f"/api/batches/{batch['id']}/records.csv")
    assert response.status_code == 200
    assert response.data.startswith("\ufeff".encode("utf-8"))
    text = response.data.decode("utf-8-sig")
    assert "passage,date,inoculum_cells" in text


def test_delete_batch_and_line_cascade(client):
    line = create_line(client, "级联细胞")
    batch = create_batch(client, line["id"])
    add_record(client, batch["id"])
    assert client.delete(f"/api/batches/{batch['id']}").status_code == 200
    assert client.get(f"/api/batches/{batch['id']}").status_code == 404

    batch2 = create_batch(client, line["id"], revival_date="2026-04-01")
    add_record(client, batch2["id"])
    assert client.delete(f"/api/cell-lines/{line['id']}").status_code == 200
    assert client.get("/api/cell-lines").get_json() == []


# --------------------------------------------------------------------------
# 冻存管 / 冻存盒
# --------------------------------------------------------------------------
def test_vials_and_boxes(client):
    line = create_line(client, "Vial细胞")
    created = client.post("/api/vials", json={
        "cell_line_id": line["id"],
        "freeze_date": "2026-01-05",
        "cell_count": 5.1e5,
        "pd": 3.2,
        "location": "罐A/架1/盒1/A1, 罐A/架1/盒1/A2",
        "count": 1,
    })
    assert created.status_code == 201
    vials = created.get_json()
    assert len(vials) == 2
    assert {vial["location"].split("/")[-1] for vial in vials} == {"A1", "A2"}

    boxes = client.get("/api/vials/boxes").get_json()
    assert boxes[0]["box"] == "罐A/架1/盒1"
    assert boxes[0]["occupied"] == 2

    detail = client.get("/api/vials/boxes/detail?box=罐A/架1/盒1").get_json()
    assert set(detail["holes"].keys()) == {"A1", "A2"}
    assert detail["holes"]["A1"]["cell_name"] == "Vial细胞"

    updated = client.patch(f"/api/vials/{vials[0]['id']}", json={"status": "已丢弃"})
    assert updated.get_json()["status"] == "已丢弃"
    assert client.delete(f"/api/vials/{vials[1]['id']}").status_code == 200
    assert len(client.get("/api/vials").get_json()) == 1


def test_vials_unplaced_filter(client):
    line = create_line(client, "待定位细胞")
    client.post("/api/vials", json={"cell_line_id": line["id"], "cell_count": 1.0, "location": ""})
    client.post("/api/vials", json={"cell_line_id": line["id"], "cell_count": 2.0,
                                    "location": "罐Z/架1/盒1/A1"})
    all_vials = client.get(f"/api/vials?cell_line_id={line['id']}").get_json()
    assert len(all_vials) == 2
    unplaced = client.get(f"/api/vials?cell_line_id={line['id']}&unplaced=1").get_json()
    assert len(unplaced) == 1
    assert unplaced[0]["location"] == ""


def test_dashboard_counts_unplaced_in_stock_vials(client):
    """首页「待录入位置」只统计在库且未填位置的管，已复苏/已丢弃的不算。"""
    line = create_line(client, "待定位统计细胞")
    # 在库 + 未填位置 → 计入
    client.post("/api/vials", json={"cell_line_id": line["id"], "cell_count": 1.0, "location": ""})
    # 在库 + 已填位置 → 不计入
    client.post("/api/vials", json={"cell_line_id": line["id"], "cell_count": 1.0,
                                    "location": "罐C/架1/盒1/A1"})
    # 未填位置但已丢弃 → 不计入
    discarded = client.post("/api/vials", json={
        "cell_line_id": line["id"], "cell_count": 1.0, "location": "", "status": "已丢弃",
    }).get_json()
    assert discarded[0]["status"] == "已丢弃"

    stats = client.get("/api/dashboard").get_json()["stats"]
    assert stats["total_vials"] == 3
    assert stats["in_stock_vials"] == 2
    assert stats["unplaced_vials"] == 1


def test_batch_binds_vial_and_marks_revived(client):
    line = create_line(client, "复苏细胞")
    vial = client.post("/api/vials", json={
        "cell_line_id": line["id"], "freeze_date": "2026-01-05",
        "cell_count": 1e6, "location": "罐B/架2/盒3/C4",
    }).get_json()[0]

    batch = create_batch(client, line["id"], vial_id=vial["id"])
    refreshed = client.get(f"/api/vials?cell_line_id={line['id']}").get_json()[0]
    assert refreshed["status"] == "已复苏"
    assert refreshed["batch_id"] == batch["id"]

    reuse = client.post("/api/batches", json={
        "cell_line_id": line["id"], "vial_id": vial["id"], "revival_date": "2026-02-02",
    })
    assert reuse.status_code == 409


def test_vial_excel_import_append_and_replace(client):
    create_line(client, "HeLa")
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "冻存盒A"
    sheet["A1"] = "HeLa\n5X10^5\nPD=10.26\n2022.4.15"
    sheet["B1"] = "新细胞\n2X10^6\n2023.5.1"
    buffer = io.BytesIO()
    workbook.save(buffer)
    payload = buffer.getvalue()

    def upload(mode: str):
        return client.post(
            "/api/vials/import",
            data={"file": (io.BytesIO(payload), "vials.xlsx"), "mode": mode},
            content_type="multipart/form-data",
        )

    response = upload("append")
    assert response.status_code == 200, response.get_json()
    result = response.get_json()
    assert result["inserted"] == 2
    assert result["lines_created"] == ["新细胞"]
    boxes = client.get("/api/vials/boxes").get_json()
    assert [box["box"] for box in boxes] == ["冻存盒A"]

    again = upload("append").get_json()
    assert again["inserted"] == 0
    assert again["skipped"] == 2

    replaced = upload("replace").get_json()
    assert replaced["inserted"] == 2
    assert len(client.get("/api/vials").get_json()) == 2


# --------------------------------------------------------------------------
# 细胞组
# --------------------------------------------------------------------------
def test_group_members_order_status_and_curves(client):
    line_a = create_line(client, "A细胞")
    line_b = create_line(client, "B细胞")
    group = client.post("/api/groups", json={"group_name": "实验组", "notes": "测试"}).get_json()
    assert group["member_count"] == 0

    members = client.put(f"/api/groups/{group['id']}/members",
                         json={"members": [line_b["id"], line_a["id"]]})
    assert members.status_code == 200
    assert [member["name"] for member in members.get_json()["members"]] == ["B细胞", "A细胞"]

    batch_a = create_batch(client, line_a["id"])
    batch_b = create_batch(client, line_b["id"])
    add_record(client, batch_a["id"], date="2026-02-02", harvested_cells=8.0)
    add_record(client, batch_b["id"], date="2026-02-02", harvested_cells=4.0)
    add_record(client, batch_b["id"], date="2026-02-04", harvested_cells=8.0)

    status = client.get(f"/api/groups/{group['id']}/status").get_json()
    assert len(status) == 2
    assert all(row["remaining_days"] is not None for row in status)

    curves = client.get(f"/api/groups/{group['id']}/curves").get_json()
    assert len(curves["series"]) == 2
    assert curves["dates"] == ["2026-02-02", "2026-02-04"]

    # 标准化 = 2^(ΔPD)：基准点一定为 1.0，之后按累计 PD 差值翻倍
    normalized = client.get(
        f"/api/groups/{group['id']}/curves?normalize=true&start_date=2026-02-02"
    ).get_json()
    assert len(normalized["series"]) == 2
    for series in normalized["series"]:
        first_point = series["points"][0]
        assert first_point["value"] == pytest.approx(1.0)
    by_name = {series["cell_line"]: series for series in normalized["series"]}
    b_points = by_name["B细胞"]["points"]
    # B：基准 2026-02-02 累计 PD 1，02-04 累计 PD 3 -> 2^(3-1) = 4 倍
    assert [point["value"] for point in b_points] == pytest.approx([1.0, 4.0])

    rates = client.get(f"/api/groups/{group['id']}/rates").get_json()
    # A、B 都有记录；B 有两条（间隔 2 天，PD=2），A 只有一条
    by_line = {row["cell_line"]: row for row in rates}
    assert set(by_line) == {"A细胞", "B细胞"}
    b_rate = by_line["B细胞"]
    assert b_rate["avg_pd_per_day"] == pytest.approx(1.0)  # PD 2 / 2 天
    assert b_rate["overall_pd_per_day"] == pytest.approx(1.0)  # 整段累计 PD 2 / 2 天
    assert b_rate["avg_doubling_hours"] == pytest.approx(24.0)
    assert b_rate["interval_count"] == 1
    assert b_rate["span_days"] == 2
    assert b_rate["cv"] is None  # 只有一段区间，无法算变异系数
    # A 只有一条记录：没有区间速率，但仍有首末记录（跨度 0 天）
    a_rate = by_line["A细胞"]
    assert a_rate["avg_pd_per_day"] is None
    assert a_rate["interval_count"] == 0
    assert a_rate["span_days"] == 0


def test_group_rates_can_include_ended_batches(client):
    line = create_line(client, "速率终止细胞")
    group = client.post("/api/groups", json={
        "group_name": "速率终止组", "cell_line_ids": [line["id"]],
    }).get_json()

    active = create_batch(client, line["id"], revival_date="2026-02-01")
    ended = create_batch(client, line["id"], revival_date="2026-03-01")
    add_record(client, active["id"], date="2026-02-02", harvested_cells=4.0)
    add_record(client, active["id"], date="2026-02-04", harvested_cells=8.0, next_passage_days=0)
    add_record(client, ended["id"], date="2026-03-02", harvested_cells=4.0)
    add_record(client, ended["id"], date="2026-03-04", harvested_cells=8.0, next_passage_days=0)
    assert client.post(f"/api/batches/{ended['id']}/terminate",
                       json={"reason": "实验结束"}).status_code == 200

    default_rows = client.get(f"/api/groups/{group['id']}/rates").get_json()
    assert [row["batch_id"] for row in default_rows] == [active["id"]]

    all_rows = client.get(f"/api/groups/{group['id']}/rates?include_ended=true").get_json()
    assert len(all_rows) == 2
    ended_row = next(row for row in all_rows if row["batch_id"] == ended["id"])
    assert ended_row["is_active"] == 0
    assert ended_row["overall_pd_per_day"] == pytest.approx(1.0)


def test_group_bulk_batch_create_and_terminate(client):
    line_a = create_line(client, "组批A")
    line_b = create_line(client, "组批B")
    group = client.post("/api/groups", json={
        "group_name": "批量组", "cell_line_ids": [line_a["id"], line_b["id"]],
    }).get_json()

    created = client.post(f"/api/groups/{group['id']}/batches", json={
        "revival_date": "2026-05-01", "initial_pd": 0.5, "initial_cell_count": 1.0,
    })
    assert created.status_code == 201
    assert len(created.get_json()["created"]) == 2

    terminated = client.post(f"/api/groups/{group['id']}/terminate", json={"reason": "实验结束"})
    assert terminated.status_code == 200
    assert terminated.get_json()["count"] == 2
    assert client.get(f"/api/groups/{group['id']}/status").get_json() == []


def test_group_records_endpoint(client):
    line = create_line(client, "组记录细胞")
    group = client.post("/api/groups", json={
        "group_name": "记录组", "cell_line_ids": [line["id"]],
    }).get_json()
    batch = create_batch(client, line["id"])
    add_record(client, batch["id"])

    rows = client.get(f"/api/groups/{group['id']}/records").get_json()
    assert len(rows) == 1
    assert rows[0]["cell_line"] == "组记录细胞"
    assert rows[0]["batch_name"] == batch["batch_name"]
    assert rows[0]["per_dish_cells"] == pytest.approx(1.0)


def test_group_export_xlsx(client):
    line = create_line(client, "导出细胞")
    group = client.post("/api/groups", json={
        "group_name": "导出组", "cell_line_ids": [line["id"]],
    }).get_json()
    batch = create_batch(client, line["id"])
    add_record(client, batch["id"])

    response = client.get(f"/api/groups/{group['id']}/export?include_all=true")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.data))
    assert workbook.sheetnames == ["细胞株信息", "培养批次", "传代记录", "冻存管"]
    assert workbook["传代记录"].max_row == 2
    assert workbook["细胞株信息"]["B1"].value == "细胞名称"


def test_full_export(client):
    line = create_line(client, "全量细胞")
    response = client.get("/api/export/full")
    assert response.status_code == 200
    workbook = load_workbook(io.BytesIO(response.data))
    assert "细胞组" in workbook.sheetnames
    assert workbook["细胞株信息"]["B2"].value == "全量细胞"


# --------------------------------------------------------------------------
# 维护
# --------------------------------------------------------------------------
def test_audit_and_recalculate(client):
    line = create_line(client)
    batch = create_batch(client, line["id"])
    add_record(client, batch["id"])
    audit = client.get("/api/maintenance/audit").get_json()
    assert audit["issues"] == []
    assert audit["pd_audit"]["mismatch_count"] == 0

    recalculated = client.post("/api/maintenance/recalculate")
    assert recalculated.status_code == 200
    assert recalculated.get_json()["remaining_issues"] == []


def test_backup_and_restore(client, config):
    line = create_line(client, "备份细胞")
    batch = create_batch(client, line["id"])
    add_record(client, batch["id"])

    response = client.get("/api/maintenance/backup")
    assert response.status_code == 200
    assert response.data[:16] == b"SQLite format 3\x00"

    backup_path = config.backup_dir / "restore-source.db"
    backup_path.write_bytes(response.data)

    # 破坏数据后恢复
    client.delete(f"/api/cell-lines/{line['id']}")
    assert client.get("/api/cell-lines").get_json() == []

    with open(backup_path, "rb") as handle:
        restored = client.post(
            "/api/maintenance/restore",
            data={"file": (handle, "restore-source.db")},
            content_type="multipart/form-data",
        )
    assert restored.status_code == 200, restored.get_json()
    lines = client.get("/api/cell-lines").get_json()
    assert [item["name"] for item in lines] == ["备份细胞"]
    assert client.get("/api/maintenance/audit").get_json()["pd_audit"]["mismatch_count"] == 0


def test_import_legacy_endpoint_validates_and_restores(client):
    create_line(client, "导入源细胞")
    backup = client.get("/api/maintenance/backup").data
    assert backup[:16] == b"SQLite format 3\x00"

    response = client.post(
        "/api/maintenance/import-legacy",
        data={"file": (io.BytesIO(backup), "legacy.db")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 200, response.get_json()
    report = response.get_json()
    assert report["counts_equal"] is True
    assert report["checksums_equal"] is True
    assert report["status"] == "ok"
    assert [line["name"] for line in client.get("/api/cell-lines").get_json()] == ["导入源细胞"]

    # 非法文件被拒绝，原数据保持不变
    invalid = client.post(
        "/api/maintenance/import-legacy",
        data={"file": (io.BytesIO(b"not a sqlite file"), "broken.db")},
        content_type="multipart/form-data",
    )
    assert invalid.status_code == 400
    assert [line["name"] for line in client.get("/api/cell-lines").get_json()] == ["导入源细胞"]


def test_migration_report_endpoint(client, config):
    assert client.get("/api/maintenance/migration-report").get_json() is None
    report_path = config.db_path.parent / "migration-report.json"
    report_path.write_text('{"status": "ok"}', encoding="utf-8")
    assert client.get("/api/maintenance/migration-report").get_json()["status"] == "ok"


def test_backup_listing(client, config):
    maintenance.create_backup(config)
    backups = client.get("/api/maintenance/backups").get_json()
    assert len(backups) == 1
    assert backups[0]["name"].endswith(".db")
