package app

import (
	"bytes"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

type testAPI struct {
	t      *testing.T
	base   string
	client *http.Client
}

func newTestAPI(t *testing.T) *testAPI {
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
	application, err := New(cfg, store)
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(application.Handler())
	t.Cleanup(server.Close)
	return &testAPI{t: t, base: server.URL, client: server.Client()}
}

func (a *testAPI) do(method, path string, body any) (int, []byte) {
	a.t.Helper()
	var reader io.Reader
	if body != nil {
		encoded, err := json.Marshal(body)
		if err != nil {
			a.t.Fatal(err)
		}
		reader = bytes.NewReader(encoded)
	}
	request, err := http.NewRequest(method, a.base+path, reader)
	if err != nil {
		a.t.Fatal(err)
	}
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	response, err := a.client.Do(request)
	if err != nil {
		a.t.Fatal(err)
	}
	defer response.Body.Close()
	data, err := io.ReadAll(response.Body)
	if err != nil {
		a.t.Fatal(err)
	}
	return response.StatusCode, data
}

func (a *testAPI) object(method, path string, body any, wantStatus int) map[string]any {
	a.t.Helper()
	status, data := a.do(method, path, body)
	if status != wantStatus {
		a.t.Fatalf("%s %s = %d, want %d: %s", method, path, status, wantStatus, data)
	}
	var result map[string]any
	if err := json.Unmarshal(data, &result); err != nil {
		a.t.Fatalf("decode %s: %v (%s)", path, err, data)
	}
	return result
}

func (a *testAPI) array(method, path string, body any, wantStatus int) []map[string]any {
	a.t.Helper()
	status, data := a.do(method, path, body)
	if status != wantStatus {
		a.t.Fatalf("%s %s = %d, want %d: %s", method, path, status, wantStatus, data)
	}
	var result []map[string]any
	if err := json.Unmarshal(data, &result); err != nil {
		a.t.Fatalf("decode %s: %v (%s)", path, err, data)
	}
	return result
}

func number(t *testing.T, value any) float64 {
	t.Helper()
	switch typed := value.(type) {
	case float64:
		return typed
	case int:
		return float64(typed)
	default:
		t.Fatalf("not a number: %#v", value)
		return 0
	}
}

func TestAPIWorkflow(t *testing.T) {
	api := newTestAPI(t)

	line := api.object("POST", "/api/cell-lines", map[string]any{
		"name": "HeLa", "type": "永生化", "revival_date": "2026-01-01",
		"default_passage_interval": 2, "notes": "测试",
	}, http.StatusCreated)
	lineID := int64(number(t, line["id"]))
	if line["name"] != "HeLa" {
		t.Fatalf("line = %#v", line)
	}
	api.object("POST", "/api/cell-lines", map[string]any{"name": "HeLa"}, http.StatusConflict)

	batch := api.object("POST", "/api/batches", map[string]any{
		"cell_line_id": lineID, "revival_date": "2026-02-01",
		"initial_pd": 1.0, "initial_cell_count": 2.0,
	}, http.StatusCreated)
	batchID := int64(number(t, batch["id"]))
	if batch["batch_name"] != "HeLa-260201" {
		t.Fatalf("batch name = %v", batch["batch_name"])
	}

	first := api.object("POST", "/api/records", map[string]any{
		"batch_id": batchID, "date": "2026-02-02", "harvested_cells": 4.0,
		"inoculum_dishes": 2, "per_dish_cells": 1.0, "status": "良好",
		"next_passage_days": 2,
	}, http.StatusCreated)
	if number(t, first["pd"]) != 1 || number(t, first["cumulative_pd"]) != 2 {
		t.Fatalf("first record = %#v", first)
	}
	if first["next_passage_date"] != "2026-02-04" || number(t, first["is_active"]) != 1 {
		t.Fatalf("first record dates = %#v", first)
	}
	second := api.object("POST", "/api/records", map[string]any{
		"batch_id": batchID, "date": "2026-02-04", "harvested_cells": 8.0,
		"inoculum_dishes": 2, "per_dish_cells": 1.0, "status": "良好",
		"next_passage_days": 0,
	}, http.StatusCreated)
	if number(t, second["pd"]) != 2 || number(t, second["cumulative_pd"]) != 4 {
		t.Fatalf("second record = %#v", second)
	}

	detail := api.object("GET", "/api/batches/"+strconv.FormatInt(batchID, 10), nil, http.StatusOK)
	detailRecords := detail["records"].([]any)
	if len(detailRecords) != 2 {
		t.Fatalf("records = %#v", detailRecords)
	}
	firstRecord := detailRecords[0].(map[string]any)
	if number(t, firstRecord["per_dish_cells"]) != 1 {
		t.Fatalf("per dish = %#v", firstRecord)
	}

	firstID := int64(number(t, first["id"]))
	updated := api.object("PATCH", "/api/records/"+strconv.FormatInt(firstID, 10), map[string]any{
		"harvested_cells": 8.0, "per_dish_cells": 1.0, "next_passage_days": 0,
	}, http.StatusOK)
	if number(t, updated["cumulative_pd"]) != 3 {
		t.Fatalf("updated first = %#v", updated)
	}
	recordRows := api.array("GET", "/api/batches/"+strconv.FormatInt(batchID, 10)+"/records", nil, http.StatusOK)
	if len(recordRows) != 2 || number(t, recordRows[0]["cumulative_pd"]) != 3 || number(t, recordRows[1]["cumulative_pd"]) != 5 {
		t.Fatalf("records after patch = %#v", recordRows)
	}

	group := api.object("POST", "/api/groups", map[string]any{
		"group_name": "测试组", "cell_line_ids": []int64{lineID},
	}, http.StatusCreated)
	groupID := int64(number(t, group["id"]))
	status := api.array("GET", "/api/groups/"+strconv.FormatInt(groupID, 10)+"/status", nil, http.StatusOK)
	if len(status) != 1 || status[0]["cell_line_id"] != float64(lineID) {
		t.Fatalf("group status = %#v", status)
	}
	rates := api.array("GET", "/api/groups/"+strconv.FormatInt(groupID, 10)+"/rates", nil, http.StatusOK)
	if len(rates) != 1 || number(t, rates[0]["overall_pd_per_day"]) <= 0 {
		t.Fatalf("group rates = %#v", rates)
	}

	vials := api.array("POST", "/api/vials", map[string]any{
		"cell_line_id": lineID, "freeze_date": "2026-01-05", "cell_count": 510000,
		"pd": 3.2, "location": "罐A/架1/盒1/A1, 罐A/架1/盒1/A2", "count": 1,
	}, http.StatusCreated)
	if len(vials) != 2 {
		t.Fatalf("vials = %#v", vials)
	}
	boxes := api.array("GET", "/api/vials/boxes", nil, http.StatusOK)
	if len(boxes) != 1 || boxes[0]["box"] != "罐A/架1/盒1" {
		t.Fatalf("boxes = %#v", boxes)
	}
	box := api.object("GET", "/api/vials/boxes/detail?box="+urlQuery("罐A/架1/盒1"), nil, http.StatusOK)
	holes := box["holes"].(map[string]any)
	if len(holes) != 2 {
		t.Fatalf("holes = %#v", holes)
	}

	curves := api.object("GET", "/api/compare/curves?line_ids="+strconv.FormatInt(lineID, 10), nil, http.StatusOK)
	if len(curves["series"].([]any)) != 1 {
		t.Fatalf("curves = %#v", curves)
	}
	normalized := api.object("GET", "/api/compare/curves?line_ids="+strconv.FormatInt(lineID, 10)+
		"&normalize=true&start_date=2026-02-02", nil, http.StatusOK)
	series := normalized["series"].([]any)[0].(map[string]any)
	points := series["points"].([]any)
	if number(t, points[0].(map[string]any)["value"]) != 1 {
		t.Fatalf("normalized first point = %#v", points[0])
	}

	terminated := api.object("POST", "/api/batches/"+strconv.FormatInt(batchID, 10)+"/terminate",
		map[string]any{"reason": "污染"}, http.StatusOK)
	if number(t, terminated["is_active"]) != 0 {
		t.Fatalf("terminated = %#v", terminated)
	}
	api.object("POST", "/api/records", map[string]any{"batch_id": batchID, "harvested_cells": 1}, http.StatusConflict)
	restored := api.object("POST", "/api/batches/"+strconv.FormatInt(batchID, 10)+"/restore", nil, http.StatusOK)
	if number(t, restored["is_active"]) != 1 {
		t.Fatalf("restored = %#v", restored)
	}

	statusCode, data := api.do("GET", "/api/export/full", nil)
	if statusCode != http.StatusOK || !strings.HasPrefix(string(data), "PK") {
		t.Fatalf("export status=%d prefix=%q", statusCode, string(data[:min(len(data), 4)]))
	}
}

func urlQuery(value string) string {
	return url.QueryEscape(value)
}
