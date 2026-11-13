package app

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// TestPaletteMatchesPythonOutput 用同一个数据库，对比 Go 与 Python 的配色结果。
// 期望值由 backend/services/palette.py 生成（见 .tmp/palette_check/python.json）。
func TestPaletteMatchesPythonOutput(t *testing.T) {
	expectedPath := filepath.Join("..", "..", ".tmp", "palette_check", "python.json")
	raw, err := os.ReadFile(expectedPath)
	if err != nil {
		t.Skipf("缺少 Python 对照文件，跳过：%v", err)
	}
	var expected struct {
		Slots  map[string]int    `json:"slots"`
		Colors map[string]string `json:"colors"`
	}
	if err := json.Unmarshal(raw, &expected); err != nil {
		t.Fatalf("解析对照文件失败：%v", err)
	}

	// 槽位必须逐一相等
	speciesNames := make([]string, 0, len(expected.Slots))
	for name := range expected.Slots {
		speciesNames = append(speciesNames, name)
	}
	gotSlots := assignSlots(speciesNames)
	for name, want := range expected.Slots {
		if gotSlots[name] != want {
			t.Errorf("槽位不一致 %q：go=%d python=%d", name, gotSlots[name], want)
		}
	}

	// 颜色必须逐一相等
	dbPath := filepath.Join("..", "..", ".tmp", "palette_check", "py.db")
	if _, err := os.Stat(dbPath); err != nil {
		t.Skipf("缺少对照数据库，跳过颜色比对：%v", err)
	}
	cfg := &Config{
		Host: "127.0.0.1", Port: 0, OpenBrowser: false,
		DBPath:    dbPath,
		BackupDir: filepath.Join(t.TempDir(), "backups"),
		BaseDir:   filepath.Dir(dbPath), SessionDays: 30,
	}
	store, err := OpenStore(cfg.DBPath)
	if err != nil {
		t.Fatalf("打开对照数据库失败：%v", err)
	}
	defer store.Close()

	colors, err := lineColors(context.Background(), store.DB())
	if err != nil {
		t.Fatalf("计算配色失败：%v", err)
	}

	mismatch := 0
	for id, want := range expected.Colors {
		lineID := int64(0)
		for _, ch := range id {
			lineID = lineID*10 + int64(ch-'0')
		}
		got := colors[lineID].Color
		if got != want {
			mismatch++
			if mismatch <= 10 {
				t.Errorf("颜色不一致 line %d：go=%s python=%s", lineID, got, want)
			}
		}
	}
	if mismatch > 0 {
		t.Fatalf("共 %d 处颜色不一致", mismatch)
	}
	t.Logf("配色与 Python 完全一致（%d 株）", len(expected.Colors))
}
