package app

import (
	"context"
	"fmt"
	"io"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/xuri/excelize/v2"
)

var gridRows = []string{"A", "B", "C", "D", "E", "F", "G", "H", "I"}
var gridCols = []int{1, 2, 3, 4, 5, 6, 7, 8, 9}

const gridCapacity = 81

func splitLocation(location string) (string, string) {
	text := strings.TrimSpace(location)
	if text == "" {
		return "", ""
	}
	parts := []string{}
	for _, part := range strings.Split(text, "/") {
		part = strings.TrimSpace(part)
		if part != "" {
			parts = append(parts, part)
		}
	}
	if len(parts) < 2 {
		return "", ""
	}
	box := strings.Join(parts[:len(parts)-1], "/")
	hole := parts[len(parts)-1]
	hole = strings.TrimPrefix(hole, "孔")
	return box, strings.ToUpper(hole)
}

func holeNumber(hole string) (string, int, bool) {
	hole = strings.ToUpper(strings.TrimSpace(hole))
	if len(hole) < 2 {
		return "", 0, false
	}
	row := hole[:1]
	colText := hole[1:]
	if !strings.Contains("ABCDEFGHI", row) {
		return "", 0, false
	}
	col, err := strconv.Atoi(colText)
	if err != nil || col < 1 || col > 9 {
		return "", 0, false
	}
	return row, col, true
}

func listVials(ctx context.Context, q Querier, search string, cellLineID *int64, status string, limit int, unplaced bool) ([]Row, error) {
	sqlText := `SELECT fv.*, cl.name AS cell_name, cb.batch_name
		FROM frozen_vials fv LEFT JOIN cell_lines cl ON cl.id = fv.cell_line_id
		LEFT JOIN culture_batches cb ON cb.id = fv.batch_id WHERE 1 = 1`
	args := []any{}
	if strings.TrimSpace(search) != "" {
		like := "%" + strings.TrimSpace(search) + "%"
		sqlText += " AND (cl.name LIKE ? OR fv.location LIKE ? OR fv.notes LIKE ?)"
		args = append(args, like, like, like)
	}
	if cellLineID != nil {
		sqlText += " AND fv.cell_line_id = ?"
		args = append(args, *cellLineID)
	}
	if strings.TrimSpace(status) != "" {
		sqlText += " AND fv.status = ?"
		args = append(args, status)
	}
	if unplaced {
		sqlText += " AND (fv.location IS NULL OR TRIM(fv.location) = '')"
	}
	if limit < 1 {
		limit = 500
	}
	if limit > 2000 {
		limit = 2000
	}
	sqlText += " ORDER BY fv.location, fv.id LIMIT ?"
	args = append(args, limit)
	return queryMaps(ctx, q, sqlText, args...)
}

func getVial(ctx context.Context, q Querier, vialID int64) (Row, error) {
	row, err := queryOne(ctx, q,
		`SELECT fv.*, cl.name AS cell_name FROM frozen_vials fv
		 LEFT JOIN cell_lines cl ON cl.id = fv.cell_line_id WHERE fv.id = ?`, vialID)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, notFoundError(fmt.Sprintf("冻存管不存在（id=%d）", vialID))
	}
	return row, nil
}

func createVials(ctx context.Context, q Querier, payload map[string]any, username any) ([]Row, error) {
	cellLineID, err := normalizeInt(payload["cell_line_id"], "细胞株", true, nil)
	if err != nil {
		return nil, err
	}
	if _, err := getOr404(ctx, q, "cell_lines", *cellLineID, "细胞株"); err != nil {
		return nil, err
	}
	freezeDate, err := normalizeDate(payload["freeze_date"], "冻存日期", false)
	if err != nil {
		return nil, err
	}
	if freezeDate == nil {
		today := todayISO()
		freezeDate = &today
	}
	zero := 0.0
	cellCount, err := normalizeNumber(payload["cell_count"], "每管细胞数", false, &zero)
	if err != nil {
		return nil, err
	}
	pdValue, err := normalizeNumber(payload["pd"], "冻存时PD值", false, nil)
	if err != nil {
		return nil, err
	}
	status, err := normalizeChoice(payload["status"], vialStatuses, "状态", "在库", false)
	if err != nil {
		return nil, err
	}
	notes, err := normalizeText(payload["notes"], 2000)
	if err != nil {
		return nil, err
	}
	one := int64(1)
	count, err := normalizeInt(payload["count"], "添加管数", false, &one)
	if err != nil {
		return nil, err
	}
	if count == nil {
		count = &one
	}
	rawLocation := strings.TrimSpace(asString(payload["location"]))
	rawLocation = strings.ReplaceAll(rawLocation, "，", ",")
	locations := []string{}
	for _, part := range strings.Split(rawLocation, ",") {
		part = strings.TrimSpace(part)
		if part != "" {
			locations = append(locations, part)
		}
	}
	if len(locations) == 0 {
		locations = []string{""}
	}
	if int(*count)*len(locations) > 200 {
		return nil, validationError("一次最多添加 200 支冻存管")
	}
	createdIDs := []int64{}
	for _, location := range locations {
		for i := int64(0); i < *count; i++ {
			result, err := q.ExecContext(ctx,
				`INSERT INTO frozen_vials (cell_line_id, freeze_date, cell_count, location, pd, status, notes)
				 VALUES (?,?,?,?,?,?,?)`,
				*cellLineID, *freezeDate, nullableFloat(cellCount), location, nullableFloat(pdValue), *status, notes)
			if err != nil {
				return nil, err
			}
			id, _ := result.LastInsertId()
			createdIDs = append(createdIDs, id)
		}
	}
	var first any
	if len(createdIDs) > 0 {
		first = createdIDs[0]
	}
	if err := audit(ctx, q, username, "create", "vial", first, map[string]any{
		"count": len(createdIDs), "location": rawLocation,
	}); err != nil {
		return nil, err
	}
	result := make([]Row, 0, len(createdIDs))
	for _, id := range createdIDs {
		vial, err := getVial(ctx, q, id)
		if err != nil {
			return nil, err
		}
		result = append(result, vial)
	}
	return result, nil
}

func updateVial(ctx context.Context, q Querier, vialID int64, payload map[string]any, username any) (Row, error) {
	if _, err := getOr404(ctx, q, "frozen_vials", vialID, "冻存管"); err != nil {
		return nil, err
	}
	assignments := []string{}
	args := []any{}
	fields := []string{}
	if hasKey(payload, "cell_line_id") {
		lineID, err := normalizeInt(payload["cell_line_id"], "细胞株", true, nil)
		if err != nil {
			return nil, err
		}
		if _, err := getOr404(ctx, q, "cell_lines", *lineID, "细胞株"); err != nil {
			return nil, err
		}
		assignments = append(assignments, "cell_line_id = ?")
		args = append(args, *lineID)
		fields = append(fields, "cell_line_id")
	}
	if hasKey(payload, "location") {
		value, err := normalizeText(payload["location"], 200)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "location = ?")
		args = append(args, value)
		fields = append(fields, "location")
	}
	if hasKey(payload, "cell_count") {
		zero := 0.0
		value, err := normalizeNumber(payload["cell_count"], "细胞数", false, &zero)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "cell_count = ?")
		args = append(args, nullableFloat(value))
		fields = append(fields, "cell_count")
	}
	if hasKey(payload, "pd") {
		value, err := normalizeNumber(payload["pd"], "PD值", false, nil)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "pd = ?")
		args = append(args, nullableFloat(value))
		fields = append(fields, "pd")
	}
	if hasKey(payload, "freeze_date") {
		value, err := normalizeDate(payload["freeze_date"], "冻存日期", false)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "freeze_date = ?")
		args = append(args, nullableString(value))
		fields = append(fields, "freeze_date")
	}
	if hasKey(payload, "status") {
		value, err := normalizeChoice(payload["status"], vialStatuses, "状态", "", false)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "status = ?")
		args = append(args, *value)
		fields = append(fields, "status")
	}
	if hasKey(payload, "notes") {
		value, err := normalizeText(payload["notes"], 2000)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "notes = ?")
		args = append(args, value)
		fields = append(fields, "notes")
	}
	if hasKey(payload, "batch_id") {
		value, err := normalizeInt(payload["batch_id"], "关联批次", false, nil)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "batch_id = ?")
		args = append(args, nullableInt(value))
		fields = append(fields, "batch_id")
	}
	if len(assignments) > 0 {
		args = append(args, vialID)
		if _, err := q.ExecContext(ctx,
			"UPDATE frozen_vials SET "+strings.Join(assignments, ", ")+" WHERE id = ?", args...); err != nil {
			return nil, err
		}
		if err := audit(ctx, q, username, "update", "vial", vialID, map[string]any{"fields": fields}); err != nil {
			return nil, err
		}
	}
	return getVial(ctx, q, vialID)
}

func deleteVial(ctx context.Context, q Querier, vialID int64, username any) (map[string]any, error) {
	vial, err := getOr404(ctx, q, "frozen_vials", vialID, "冻存管")
	if err != nil {
		return nil, err
	}
	if _, err := q.ExecContext(ctx, `DELETE FROM frozen_vials WHERE id = ?`, vialID); err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "delete", "vial", vialID, map[string]any{
		"location": rowString(vial, "location"),
	}); err != nil {
		return nil, err
	}
	return map[string]any{"deleted": vialID}, nil
}

func listBoxes(ctx context.Context, q Querier) ([]Row, error) {
	rows, err := queryMaps(ctx, q,
		`SELECT location FROM frozen_vials WHERE location IS NOT NULL AND location <> ''`)
	if err != nil {
		return nil, err
	}
	counts := map[string]int{}
	for _, row := range rows {
		box, _ := splitLocation(rowString(row, "location"))
		if box != "" {
			counts[box]++
		}
	}
	boxes := make([]string, 0, len(counts))
	for box := range counts {
		boxes = append(boxes, box)
	}
	sort.Strings(boxes)
	result := make([]Row, 0, len(boxes))
	for _, box := range boxes {
		result = append(result, Row{
			"box": box, "occupied": counts[box], "capacity": gridCapacity,
			"free": gridCapacity - counts[box],
		})
	}
	return result, nil
}

func boxDetail(ctx context.Context, q Querier, box string) (map[string]any, error) {
	vials, err := queryMaps(ctx, q,
		`SELECT fv.*, cl.name AS cell_name FROM frozen_vials fv
		 LEFT JOIN cell_lines cl ON cl.id = fv.cell_line_id
		 WHERE fv.location LIKE ? ORDER BY fv.location`, box+"/%")
	if err != nil {
		return nil, err
	}
	holes := map[string]Row{}
	unplaced := []Row{}
	for _, vial := range vials {
		_, hole := splitLocation(rowString(vial, "location"))
		if _, _, ok := holeNumber(hole); ok {
			holes[hole] = vial
		} else {
			unplaced = append(unplaced, vial)
		}
	}
	return map[string]any{
		"box": box, "rows": gridRows, "cols": gridCols, "capacity": gridCapacity,
		"occupied": len(holes), "holes": holes, "unplaced": unplaced,
	}, nil
}

func clearBox(ctx context.Context, q Querier, box string, username any) (map[string]any, error) {
	if strings.TrimSpace(box) == "" {
		return nil, validationError("盒子名称不能为空")
	}
	result, err := q.ExecContext(ctx, `DELETE FROM frozen_vials WHERE location LIKE ?`, box+"/%")
	if err != nil {
		return nil, err
	}
	deleted, _ := result.RowsAffected()
	if err := audit(ctx, q, username, "delete_box", "vial", nil, map[string]any{
		"box": box, "deleted": deleted,
	}); err != nil {
		return nil, err
	}
	return map[string]any{"box": box, "deleted": deleted}, nil
}

func importFromWorkbook(ctx context.Context, q Querier, reader io.Reader, mode string, username any) (map[string]any, error) {
	if mode != "append" && mode != "replace" {
		return nil, validationError("导入模式必须是 append 或 replace")
	}
	workbook, err := excelize.OpenReader(reader)
	if err != nil {
		return nil, validationError("无法读取 Excel 文件：" + err.Error())
	}
	defer workbook.Close()
	inserted := 0
	skipped := 0
	errorsList := []string{}
	linesCreated := []string{}
	boxStats := []map[string]any{}
	today := time.Now().Format("2006-01-02")
	for _, sheet := range workbook.GetSheetList() {
		box := strings.TrimSpace(sheet)
		if box == "" {
			continue
		}
		if mode == "replace" {
			if _, err := q.ExecContext(ctx, `DELETE FROM frozen_vials WHERE location LIKE ?`, box+"/%"); err != nil {
				return nil, err
			}
		}
		boxInserted := 0
		boxSkipped := 0
		for rowIndex := 1; rowIndex <= 9; rowIndex++ {
			rowLetter := string(rune('A' + rowIndex - 1))
			for colIndex := 1; colIndex <= 9; colIndex++ {
				cellName, _ := excelize.CoordinatesToCellName(colIndex, rowIndex)
				value, err := workbook.GetCellValue(sheet, cellName)
				if err != nil {
					continue
				}
				parsed := parseCellText(value)
				if parsed == nil {
					continue
				}
				hole := fmt.Sprintf("%s%d", rowLetter, colIndex)
				location := box + "/" + hole
				if mode == "append" {
					existing, err := queryOne(ctx, q,
						`SELECT id FROM frozen_vials WHERE location = ? LIMIT 1`, location)
					if err != nil {
						return nil, err
					}
					if existing != nil {
						boxSkipped++
						continue
					}
				}
				line, err := queryOne(ctx, q, `SELECT id, name FROM cell_lines WHERE name = ?`, parsed.CellName)
				if err != nil {
					return nil, err
				}
				var lineID int64
				if line != nil {
					lineID = rowInt(line, "id")
				} else {
					result, err := q.ExecContext(ctx,
						`INSERT INTO cell_lines (name, type, revival_date) VALUES (?, '永生化', ?)`,
						parsed.CellName, today)
					if err != nil {
						return nil, err
					}
					lineID, _ = result.LastInsertId()
					linesCreated = append(linesCreated, parsed.CellName)
				}
				_, err = q.ExecContext(ctx,
					`INSERT INTO frozen_vials (cell_line_id, location, freeze_date, cell_count, pd, status, notes)
					 VALUES (?,?,?,?,?,?,?)`,
					lineID, location, nullableString(parsed.FreezeDate), nullableFloat(parsed.CellCount),
					nullableFloat(parsed.PD), parsed.Status, parsed.Notes)
				if err != nil {
					if len(errorsList) < 50 {
						errorsList = append(errorsList, fmt.Sprintf("%s: %v", location, err))
					}
					continue
				}
				boxInserted++
			}
		}
		inserted += boxInserted
		skipped += boxSkipped
		boxStats = append(boxStats, map[string]any{
			"box": box, "inserted": boxInserted, "skipped": boxSkipped,
		})
	}
	if err := audit(ctx, q, username, "import", "vial", nil, map[string]any{
		"inserted": inserted, "skipped": skipped, "boxes": len(boxStats),
	}); err != nil {
		return nil, err
	}
	return map[string]any{
		"mode": mode, "inserted": inserted, "skipped": skipped, "errors": errorsList,
		"boxes": boxStats, "lines_created": linesCreated,
	}, nil
}
