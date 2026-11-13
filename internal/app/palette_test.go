package app

import (
	"context"
	"path/filepath"
	"testing"
)

// 与 Python 版 backend/services/palette.py 对照：
// 槽位分配、同标签同色系、新增标签不影响已有颜色。
func TestPaletteSlotsStable(t *testing.T) {
	names := []string{"标签甲", "标签乙", "标签丙", "标签丁"}
	slots := assignSlots(names)

	// 同名标签永远同一槽位
	for _, name := range names {
		if again := assignSlots(names)[name]; again != slots[name] {
			t.Fatalf("槽位不稳定：%s %d -> %d", name, slots[name], again)
		}
	}

	// 不同标签不能落在同一槽位
	seen := map[int]string{}
	for _, name := range names {
		slot := slots[name]
		if other, ok := seen[slot]; ok {
			t.Fatalf("槽位冲突：%s 与 %s 都在 %d", name, other, slot)
		}
		seen[slot] = name
	}

	// 新增标签不能让已有标签的槽位变化
	after := assignSlots(append(append([]string{}, names...), "新标签"))
	for _, name := range names {
		if slots[name] != after[name] {
			t.Fatalf("新增标签导致 %s 槽位变化：%d -> %d", name, slots[name], after[name])
		}
	}
}

func TestPaletteEmptySpeciesIsNeutral(t *testing.T) {
	if got := colorFor("", 1, 0); got != noSpeciesColor {
		t.Fatalf("空标签应返回中性色 %s，得到 %s", noSpeciesColor, got)
	}
}

func TestPaletteSameSpeciesSharesHue(t *testing.T) {
	slot := assignSlots([]string{"同一标签"})["同一标签"]
	first := colorFor("同一标签", 1, slot)
	second := colorFor("同一标签", 2, slot)
	if first == second {
		t.Fatalf("同一标签的不同细胞株应有可区分的颜色，都是 %s", first)
	}
	// 同一标签两株颜色的色相差应明显小于不同标签之间
	otherSlot := assignSlots([]string{"同一标签", "另一个标签"})["另一个标签"]
	other := colorFor("另一个标签", 1, otherSlot)
	if other == first || other == second {
		t.Fatalf("不同标签不应撞色")
	}
}

func newPaletteTestDB(t *testing.T) (context.Context, Querier) {
	t.Helper()
	dir := t.TempDir()
	cfg := &Config{
		Host: "127.0.0.1", Port: 0, OpenBrowser: false,
		DBPath:    filepath.Join(dir, "data", "cell_data.db"),
		BackupDir: filepath.Join(dir, "backups"),
		BaseDir:   dir, SessionDays: 30,
	}
	if _, err := EnsureDatabase(cfg); err != nil {
		t.Fatal(err)
	}
	store, err := OpenStore(cfg.DBPath)
	if err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _ = store.Close() })
	return context.Background(), store.DB()
}

func TestAssignSpeciesWritesLabel(t *testing.T) {
	ctx, db := newPaletteTestDB(t)

	line, err := createLine(ctx, db, map[string]any{
		"name": "样本甲", "species": "自定义标签",
	}, nil)
	if err != nil {
		t.Fatalf("创建细胞株失败：%v", err)
	}
	if got := rowString(line, "species"); got != "自定义标签" {
		t.Fatalf("标签未写入，得到 %q", got)
	}

	// only_unset 不应覆盖已标注的细胞株
	result, err := assignSpecies(ctx, db, "另一个标签", nil, true, nil)
	if err != nil {
		t.Fatalf("批量标注失败：%v", err)
	}
	if updated, _ := asInt(result["updated"]); updated != 0 {
		t.Fatalf("only_unset 不应覆盖已标注的细胞株，实际更新 %d", updated)
	}

	// 显式覆盖
	if _, err := assignSpecies(ctx, db, "另一个标签", nil, false, nil); err != nil {
		t.Fatalf("批量标注失败：%v", err)
	}
	row, err := getLineSummary(ctx, db, rowInt(line, "id"))
	if err != nil {
		t.Fatalf("读取细胞株失败：%v", err)
	}
	if got := rowString(row, "species"); got != "另一个标签" {
		t.Fatalf("覆盖后应为「另一个标签」，得到 %q", got)
	}
}

func TestSpeciesPaletteIncludedInMeta(t *testing.T) {
	ctx, db := newPaletteTestDB(t)

	for _, name := range []string{"样本甲", "样本乙"} {
		if _, err := createLine(ctx, db, map[string]any{
			"name": name, "species": "同组标签",
		}, nil); err != nil {
			t.Fatalf("创建细胞株失败：%v", err)
		}
	}

	palette := buildSpeciesPalette(ctx, db)
	if len(palette.Lines) != 2 {
		t.Fatalf("配色表应含 2 条细胞株，实际 %d", len(palette.Lines))
	}
	if len(palette.Species) != 1 {
		t.Fatalf("配色表应含 1 个标签，实际 %d", len(palette.Species))
	}
	if palette.Species[0].Species != "同组标签" {
		t.Fatalf("标签名不符：%q", palette.Species[0].Species)
	}
}

func TestDashboardCountsUnplacedVials(t *testing.T) {
	ctx, db := newPaletteTestDB(t)

	line, err := createLine(ctx, db, map[string]any{"name": "待定位细胞"}, nil)
	if err != nil {
		t.Fatalf("创建细胞株失败：%v", err)
	}
	lineID := rowInt(line, "id")

	// 在库 + 未填位置 → 计入
	if _, err := createVials(ctx, db, map[string]any{
		"cell_line_id": lineID, "cell_count": 1.0, "location": "",
	}, nil); err != nil {
		t.Fatalf("创建冻存管失败：%v", err)
	}
	// 在库 + 已填位置 → 不计入
	if _, err := createVials(ctx, db, map[string]any{
		"cell_line_id": lineID, "cell_count": 1.0, "location": "罐A/架1/盒1/A1",
	}, nil); err != nil {
		t.Fatalf("创建冻存管失败：%v", err)
	}

	dash, err := dashboard(ctx, db)
	if err != nil {
		t.Fatalf("看板统计失败：%v", err)
	}
	stats, ok := dash["stats"].(map[string]any)
	if !ok {
		t.Fatalf("stats 类型不符：%T", dash["stats"])
	}
	if got, _ := asInt(stats["unplaced_vials"]); got != 1 {
		t.Fatalf("unplaced_vials 应为 1，得到 %d", got)
	}
	if got, _ := asInt(stats["in_stock_vials"]); got != 2 {
		t.Fatalf("in_stock_vials 应为 2，得到 %d", got)
	}
}
