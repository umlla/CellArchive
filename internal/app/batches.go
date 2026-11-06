package app

import (
	"context"
	"fmt"
	"strings"
)

const batchSelect = `
SELECT cb.*, cl.name AS cell_name, cl.type AS cell_type, cl.default_passage_interval,
    (SELECT COUNT(*) FROM culture_records r WHERE r.batch_id = cb.id) AS records_count,
    (SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
        ORDER BY r.date DESC, r.id DESC LIMIT 1) AS active_record_id,
    (SELECT id FROM culture_records r WHERE r.batch_id = cb.id
        ORDER BY r.date DESC, r.id DESC LIMIT 1) AS latest_record_id
FROM culture_batches cb
JOIN cell_lines cl ON cl.id = cb.cell_line_id
`

func serializeBatch(ctx context.Context, q Querier, batch Row) (Row, error) {
	recordID := rowInt(batch, "active_record_id")
	if recordID == 0 {
		recordID = rowInt(batch, "latest_record_id")
	}
	batch["current_record"] = nil
	if recordID != 0 {
		record, err := queryOne(ctx, q, `SELECT * FROM culture_records WHERE id = ?`, recordID)
		if err != nil {
			return nil, err
		}
		batch["current_record"] = record
	}
	batch["is_active"] = rowInt(batch, "is_active")
	if batch["current_record"] != nil {
		batch["cumulative_pd"] = rowFloat(batch["current_record"].(Row), "cumulative_pd")
	} else {
		batch["cumulative_pd"] = rowFloat(batch, "initial_pd")
	}
	return batch, nil
}

func listBatches(ctx context.Context, q Querier, cellLineID *int64, active *bool, search string) ([]Row, error) {
	sqlText := batchSelect + " WHERE 1 = 1"
	args := []any{}
	if cellLineID != nil {
		sqlText += " AND cb.cell_line_id = ?"
		args = append(args, *cellLineID)
	}
	if active != nil {
		sqlText += " AND cb.is_active = ?"
		if *active {
			args = append(args, 1)
		} else {
			args = append(args, 0)
		}
	}
	if strings.TrimSpace(search) != "" {
		like := "%" + strings.TrimSpace(search) + "%"
		sqlText += " AND (cb.batch_name LIKE ? OR cl.name LIKE ?)"
		args = append(args, like, like)
	}
	sqlText += " ORDER BY cb.is_active DESC, COALESCE(cb.revival_date, '') DESC, cb.id DESC"
	rows, err := queryMaps(ctx, q, sqlText, args...)
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		if _, err := serializeBatch(ctx, q, row); err != nil {
			return nil, err
		}
	}
	return rows, nil
}

func getBatch(ctx context.Context, q Querier, batchID int64) (Row, error) {
	row, err := queryOne(ctx, q, batchSelect+" WHERE cb.id = ?", batchID)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, notFoundError(fmt.Sprintf("培养批次不存在（id=%d）", batchID))
	}
	return serializeBatch(ctx, q, row)
}

func createBatch(ctx context.Context, q Querier, payload map[string]any, username any) (Row, error) {
	cellLineID, err := normalizeInt(payload["cell_line_id"], "细胞株", true, nil)
	if err != nil {
		return nil, err
	}
	line, err := getOr404(ctx, q, "cell_lines", *cellLineID, "细胞株")
	if err != nil {
		return nil, err
	}
	revival, err := normalizeDate(payload["revival_date"], "复苏日期", false)
	if err != nil {
		return nil, err
	}
	if revival == nil {
		today := todayISO()
		revival = &today
	}
	sourceFreeze, err := normalizeDate(payload["source_freeze_date"], "冻存来源日期", false)
	if err != nil {
		return nil, err
	}
	zero := 0.0
	initialPD, err := normalizeNumber(payload["initial_pd"], "初始PD", false, &zero)
	if err != nil {
		return nil, err
	}
	if initialPD == nil {
		initialPD = &zero
	}
	initialCells, err := normalizeNumber(payload["initial_cell_count"], "复苏接种细胞数", false, &zero)
	if err != nil {
		return nil, err
	}
	if initialCells != nil && *initialCells == 0 {
		initialCells = nil
	}
	notes, err := normalizeText(payload["notes"], 2000)
	if err != nil {
		return nil, err
	}
	batchName := strings.TrimSpace(asString(payload["batch_name"]))
	if batchName == "" {
		cutoff := strings.ReplaceAll(*revival, "-", "")[2:8]
		batchName = fmt.Sprintf("%s-%s", rowString(line, "name"), cutoff)
	}
	var vial Row
	vialID, err := normalizeInt(payload["vial_id"], "来源冻存管", false, nil)
	if err != nil {
		return nil, err
	}
	if vialID != nil {
		vial, err = getOr404(ctx, q, "frozen_vials", *vialID, "冻存管")
		if err != nil {
			return nil, err
		}
		if rowInt(vial, "cell_line_id") != rowInt(line, "id") {
			return nil, validationError("所选冻存管不属于该细胞株")
		}
		if rowString(vial, "status") != "在库" {
			return nil, conflictError(fmt.Sprintf("冻存管当前状态为「%s」，不能用于复苏", rowString(vial, "status")))
		}
	}
	result, err := q.ExecContext(ctx,
		`INSERT INTO culture_batches
		 (cell_line_id, batch_name, revival_date, source_freeze_date, initial_pd, initial_cell_count, is_active, notes)
		 VALUES (?,?,?,?,?,?,1,?)`,
		rowInt(line, "id"), batchName, *revival, nullableString(sourceFreeze), *initialPD, nullableFloat(initialCells), notes)
	if err != nil {
		return nil, err
	}
	batchID, _ := result.LastInsertId()
	if vial != nil {
		if _, err := q.ExecContext(ctx,
			`UPDATE frozen_vials SET status = '已复苏', batch_id = ? WHERE id = ?`,
			batchID, rowInt(vial, "id")); err != nil {
			return nil, err
		}
	}
	if err := audit(ctx, q, username, "create", "batch", batchID, map[string]any{
		"batch_name": batchName, "vial_id": nullableInt(vialID),
	}); err != nil {
		return nil, err
	}
	return getBatch(ctx, q, batchID)
}

func updateBatch(ctx context.Context, q Querier, batchID int64, payload map[string]any, username any) (Row, error) {
	batch, err := getOr404(ctx, q, "culture_batches", batchID, "培养批次")
	if err != nil {
		return nil, err
	}
	assignments := []string{}
	args := []any{}
	fields := []string{}
	if hasKey(payload, "batch_name") {
		name, err := requireNonEmpty(payload["batch_name"], "批次名称")
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "batch_name = ?")
		args = append(args, name)
		fields = append(fields, "batch_name")
	}
	if hasKey(payload, "revival_date") {
		value, err := normalizeDate(payload["revival_date"], "复苏日期", false)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "revival_date = ?")
		args = append(args, nullableString(value))
		fields = append(fields, "revival_date")
	}
	if hasKey(payload, "source_freeze_date") {
		value, err := normalizeDate(payload["source_freeze_date"], "冻存来源日期", false)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "source_freeze_date = ?")
		args = append(args, nullableString(value))
		fields = append(fields, "source_freeze_date")
	}
	recalc := false
	if hasKey(payload, "initial_pd") {
		zero := 0.0
		value, err := normalizeNumber(payload["initial_pd"], "初始PD", false, &zero)
		if err != nil {
			return nil, err
		}
		if value == nil {
			value = &zero
		}
		assignments = append(assignments, "initial_pd = ?")
		args = append(args, *value)
		fields = append(fields, "initial_pd")
		recalc = true
	}
	if hasKey(payload, "initial_cell_count") {
		zero := 0.0
		value, err := normalizeNumber(payload["initial_cell_count"], "复苏接种细胞数", false, &zero)
		if err != nil {
			return nil, err
		}
		if value != nil && *value == 0 {
			value = nil
		}
		assignments = append(assignments, "initial_cell_count = ?")
		args = append(args, nullableFloat(value))
		fields = append(fields, "initial_cell_count")
		recalc = true
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
	if len(assignments) == 0 {
		return getBatch(ctx, q, batchID)
	}
	args = append(args, batchID)
	if _, err := q.ExecContext(ctx,
		"UPDATE culture_batches SET "+strings.Join(assignments, ", ")+" WHERE id = ?", args...); err != nil {
		return nil, err
	}
	if recalc {
		if _, err := recalculateBatch(ctx, q, batchID); err != nil {
			return nil, err
		}
	}
	if err := audit(ctx, q, username, "update", "batch", batchID, map[string]any{"fields": fields}); err != nil {
		return nil, err
	}
	return getBatch(ctx, q, rowInt(batch, "id"))
}

func terminateBatch(ctx context.Context, q Querier, batchID int64, reason any, username any) (Row, error) {
	batch, err := getOr404(ctx, q, "culture_batches", batchID, "培养批次")
	if err != nil {
		return nil, err
	}
	if !rowBool(batch, "is_active") {
		return nil, conflictError("该批次已经终止")
	}
	reasonValue, err := normalizeChoice(reason, endReasons, "终止原因", "其他", false)
	if err != nil {
		return nil, err
	}
	endDate := todayISO()
	if _, err := q.ExecContext(ctx,
		`UPDATE culture_batches SET is_active = 0, end_date = ?, end_reason = ? WHERE id = ?`,
		endDate, *reasonValue, batchID); err != nil {
		return nil, err
	}
	if _, err := q.ExecContext(ctx, `UPDATE culture_records SET is_active = 0 WHERE batch_id = ?`, batchID); err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "terminate", "batch", batchID, map[string]any{
		"reason": *reasonValue, "end_date": endDate,
	}); err != nil {
		return nil, err
	}
	return getBatch(ctx, q, batchID)
}

func restoreBatch(ctx context.Context, q Querier, batchID int64, username any) (Row, error) {
	batch, err := getOr404(ctx, q, "culture_batches", batchID, "培养批次")
	if err != nil {
		return nil, err
	}
	if rowBool(batch, "is_active") {
		return nil, conflictError("该批次本来就是活跃状态，无需恢复")
	}
	if _, err := q.ExecContext(ctx,
		`UPDATE culture_batches SET is_active = 1, end_date = NULL, end_reason = NULL WHERE id = ?`,
		batchID); err != nil {
		return nil, err
	}
	if _, err := refreshActiveRecord(ctx, q, batchID); err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "restore", "batch", batchID, map[string]any{
		"batch_name": rowString(batch, "batch_name"),
	}); err != nil {
		return nil, err
	}
	return getBatch(ctx, q, batchID)
}

func deleteBatch(ctx context.Context, q Querier, batchID int64, username any) (map[string]any, error) {
	batch, err := getOr404(ctx, q, "culture_batches", batchID, "培养批次")
	if err != nil {
		return nil, err
	}
	result, err := q.ExecContext(ctx, `DELETE FROM culture_records WHERE batch_id = ?`, batchID)
	if err != nil {
		return nil, err
	}
	deletedRecords, _ := result.RowsAffected()
	if _, err := q.ExecContext(ctx, `UPDATE frozen_vials SET batch_id = NULL WHERE batch_id = ?`, batchID); err != nil {
		return nil, err
	}
	if _, err := q.ExecContext(ctx, `DELETE FROM culture_batches WHERE id = ?`, batchID); err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "delete", "batch", batchID, map[string]any{
		"batch_name": rowString(batch, "batch_name"), "deleted_records": deletedRecords,
	}); err != nil {
		return nil, err
	}
	return map[string]any{"deleted_records": deletedRecords, "batch_name": rowString(batch, "batch_name")}, nil
}

func getBatchDetail(ctx context.Context, q Querier, batchID int64) (map[string]any, error) {
	batch, err := getBatch(ctx, q, batchID)
	if err != nil {
		return nil, err
	}
	records, err := queryMaps(ctx, q,
		`SELECT * FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC`, batchID)
	if err != nil {
		return nil, err
	}
	for _, record := range records {
		dishes := rowFloat(record, "inoculum_dishes")
		record["per_dish_cells"] = 0.0
		if dishes != 0 {
			record["per_dish_cells"] = roundTo(rowFloat(record, "inoculum_cells")/dishes, 2)
		}
	}
	line, err := queryOne(ctx, q, `SELECT * FROM cell_lines WHERE id = ?`, rowInt(batch, "cell_line_id"))
	if err != nil {
		return nil, err
	}
	vials, err := queryMaps(ctx, q, `SELECT * FROM frozen_vials WHERE batch_id = ? ORDER BY location`, batchID)
	if err != nil {
		return nil, err
	}
	cumulative := rowFloat(batch, "initial_pd")
	if len(records) > 0 {
		cumulative = rowFloat(records[len(records)-1], "cumulative_pd")
	}
	return map[string]any{
		"batch":     batch,
		"cell_line": line,
		"records":   records,
		"vials":     vials,
		"summary": map[string]any{
			"records_count":  len(records),
			"cumulative_pd":  cumulative,
			"current_record": batch["current_record"],
		},
	}, nil
}

func recalcAll(ctx context.Context, q Querier, username any) (map[string]any, error) {
	batches, err := queryMaps(ctx, q, `SELECT id FROM culture_batches ORDER BY id`)
	if err != nil {
		return nil, err
	}
	fixed := 0
	problems := 0
	for _, batch := range batches {
		id := rowInt(batch, "id")
		result, err := recalculateBatch(ctx, q, id)
		if err != nil {
			return nil, err
		}
		if result != nil {
			fixed++
		}
		active, err := refreshActiveRecord(ctx, q, id)
		if err != nil {
			return nil, err
		}
		if active == nil {
			current, err := queryOne(ctx, q, `SELECT is_active FROM culture_batches WHERE id = ?`, id)
			if err != nil {
				return nil, err
			}
			if current != nil && rowBool(current, "is_active") {
				problems++
			}
		}
	}
	if err := audit(ctx, q, username, "recalculate", "batch", nil, map[string]any{"batches": fixed}); err != nil {
		return nil, err
	}
	return map[string]any{"batches": fixed, "active_record_problems": problems}, nil
}

func nullableString(value *string) any {
	if value == nil {
		return nil
	}
	return *value
}

func nullableFloat(value *float64) any {
	if value == nil {
		return nil
	}
	return *value
}

func nullableInt(value *int64) any {
	if value == nil {
		return nil
	}
	return *value
}
