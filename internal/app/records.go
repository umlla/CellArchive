package app

import (
	"context"
	"database/sql"
	"fmt"
	"strings"
	"time"
)

func perDish(record Row) float64 {
	dishes := rowFloat(record, "inoculum_dishes")
	if dishes == 0 {
		return 0
	}
	return roundTo(rowFloat(record, "inoculum_cells")/dishes, 2)
}

func listRecords(ctx context.Context, q Querier, batchID int64) ([]Row, error) {
	if _, err := getOr404(ctx, q, "culture_batches", batchID, "培养批次"); err != nil {
		return nil, err
	}
	records, err := queryMaps(ctx, q,
		`SELECT * FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC`, batchID)
	if err != nil {
		return nil, err
	}
	for _, record := range records {
		record["per_dish_cells"] = perDish(record)
	}
	return records, nil
}

func requireActiveBatch(ctx context.Context, q Querier, batchID int64) (Row, error) {
	batch, err := getOr404(ctx, q, "culture_batches", batchID, "培养批次")
	if err != nil {
		return nil, err
	}
	if !rowBool(batch, "is_active") {
		return nil, conflictError("该批次已终止，不能再新增传代记录")
	}
	return batch, nil
}

func nextPassage(ctx context.Context, q Querier, batchID int64) (int64, error) {
	var maxPassage sql.NullInt64
	if err := q.QueryRowContext(ctx,
		`SELECT MAX(passage) FROM culture_records WHERE batch_id = ?`, batchID).Scan(&maxPassage); err != nil {
		return 0, err
	}
	if maxPassage.Valid {
		return maxPassage.Int64 + 1, nil
	}
	return 1, nil
}

type freezeConfig struct {
	Count     int64
	CellCount float64
	IncludePD bool
}

func parseFreezeConfig(payload map[string]any) (*freezeConfig, error) {
	raw, exists := payload["freeze_vials"]
	if !exists || raw == nil {
		return nil, nil
	}
	switch value := raw.(type) {
	case string:
		if strings.TrimSpace(value) == "" {
			return nil, nil
		}
	case bool:
		if !value {
			return nil, nil
		}
	}
	data, ok := raw.(map[string]any)
	if !ok {
		return nil, validationError("冻存管参数格式不正确")
	}
	if enabled, exists := data["enabled"]; exists && !asBool(enabled) {
		return nil, nil
	}
	countValue := any(1)
	if value, exists := data["count"]; exists {
		countValue = value
	}
	minimum := int64(1)
	count, err := normalizeInt(countValue, "复管数量", false, &minimum)
	if err != nil {
		return nil, err
	}
	if count == nil {
		one := int64(1)
		count = &one
	}
	if *count > 200 {
		return nil, validationError("一次最多添加 200 支冻存管")
	}
	minimumCell := 0.0001
	cellCount, err := normalizeNumber(data["cell_count_per_vial"], "每管冻存细胞数", true, &minimumCell)
	if err != nil {
		return nil, err
	}
	includePD := true
	if value, exists := data["include_pd"]; exists {
		includePD = asBool(value)
	}
	return &freezeConfig{Count: *count, CellCount: *cellCount, IncludePD: includePD}, nil
}

func createFreezeVials(ctx context.Context, q Querier, batchID, recordID int64, config *freezeConfig) ([]int64, error) {
	record, err := queryOne(ctx, q,
		`SELECT date, passage, cumulative_pd FROM culture_records WHERE id = ?`, recordID)
	if err != nil {
		return nil, err
	}
	batch, err := queryOne(ctx, q, `SELECT cell_line_id FROM culture_batches WHERE id = ?`, batchID)
	if err != nil {
		return nil, err
	}
	line, err := queryOne(ctx, q, `SELECT type FROM cell_lines WHERE id = ?`, rowInt(batch, "cell_line_id"))
	if err != nil {
		return nil, err
	}
	cumulative := rowFloat(record, "cumulative_pd")
	isPrimary := line != nil && rowString(line, "type") == "原代"
	var pdValue any
	if isPrimary || config.IncludePD {
		pdValue = cumulative
	}
	created := []int64{}
	for i := int64(0); i < config.Count; i++ {
		result, err := q.ExecContext(ctx,
			`INSERT INTO frozen_vials
			 (cell_line_id, batch_id, freeze_date, cell_count, location, pd, status, notes)
			 VALUES (?,?,?,?,?,?,?,?)`,
			rowInt(batch, "cell_line_id"), batchID, rowString(record, "date"), config.CellCount,
			"", pdValue, "在库", fmt.Sprintf("传代 P%d 时自动添加", rowInt(record, "passage")))
		if err != nil {
			return nil, err
		}
		id, _ := result.LastInsertId()
		created = append(created, id)
	}
	return created, nil
}

func insertRecord(ctx context.Context, q Querier, payload map[string]any) (int64, []int64, error) {
	batchID, err := normalizeInt(payload["batch_id"], "批次", true, nil)
	if err != nil {
		return 0, nil, err
	}
	if _, err := requireActiveBatch(ctx, q, *batchID); err != nil {
		return 0, nil, err
	}
	freeze, err := parseFreezeConfig(payload)
	if err != nil {
		return 0, nil, err
	}
	minimumPassage := int64(1)
	passage, err := normalizeInt(payload["passage"], "传代次数", false, &minimumPassage)
	if err != nil {
		return 0, nil, err
	}
	if passage == nil {
		value, err := nextPassage(ctx, q, *batchID)
		if err != nil {
			return 0, nil, err
		}
		passage = &value
	}
	recordDate, err := normalizeDate(payload["date"], "传代日期", false)
	if err != nil {
		return 0, nil, err
	}
	if recordDate == nil {
		today := todayISO()
		recordDate = &today
	}
	zero := 0.0
	harvested, err := normalizeNumber(payload["harvested_cells"], "收获细胞数", true, &zero)
	if err != nil {
		return 0, nil, err
	}
	one := int64(1)
	dishes, err := normalizeInt(payload["inoculum_dishes"], "种下盘数", false, &one)
	if err != nil {
		return 0, nil, err
	}
	if dishes == nil {
		dishes = &one
	}
	perDishValue, err := normalizeNumber(payload["per_dish_cells"], "每盘细胞数", false, &zero)
	if err != nil {
		return 0, nil, err
	}
	inoculum, err := normalizeNumber(payload["inoculum_cells"], "接种细胞数", false, &zero)
	if err != nil {
		return 0, nil, err
	}
	if perDishValue != nil {
		value := roundTo(float64(*dishes)*(*perDishValue), 4)
		inoculum = &value
	}
	if inoculum == nil {
		value := 0.0
		inoculum = &value
	}
	status, err := normalizeChoice(payload["status"], statusChoices, "细胞状态", "良好", false)
	if err != nil {
		return 0, nil, err
	}
	notes, err := normalizeText(payload["notes"], 2000)
	if err != nil {
		return 0, nil, err
	}
	nextDays, err := normalizeInt(payload["next_passage_days"], "下次传代间隔", false, &zeroInt)
	if err != nil {
		return 0, nil, err
	}
	var nextDate any
	if nextDays != nil && *nextDays > 0 {
		parsed, _ := time.Parse("2006-01-02", *recordDate)
		nextDate = parsed.AddDate(0, 0, int(*nextDays)).Format("2006-01-02")
	} else {
		value, err := normalizeDate(payload["next_passage_date"], "建议下次传代日期", false)
		if err != nil {
			return 0, nil, err
		}
		nextDate = nullableString(value)
	}
	result, err := q.ExecContext(ctx,
		`INSERT INTO culture_records
		 (batch_id, passage, date, inoculum_cells, inoculum_dishes, harvested_cells,
		  pd, cumulative_pd, status, next_passage_date, is_active, notes)
		 VALUES (?,?,?,?,?,?,0,0,?,?,0,?)`,
		*batchID, *passage, *recordDate, *inoculum, *dishes, *harvested, *status, nextDate, notes)
	if err != nil {
		return 0, nil, err
	}
	recordID, _ := result.LastInsertId()
	if _, err := recalculateBatch(ctx, q, *batchID); err != nil {
		return 0, nil, err
	}
	if _, err := refreshActiveRecord(ctx, q, *batchID); err != nil {
		return 0, nil, err
	}
	vialIDs := []int64{}
	if freeze != nil {
		vialIDs, err = createFreezeVials(ctx, q, *batchID, recordID, freeze)
		if err != nil {
			return 0, nil, err
		}
	}
	return recordID, vialIDs, nil
}

var zeroInt int64 = 0

func createRecord(ctx context.Context, q Querier, payload map[string]any, username any) (Row, error) {
	recordID, vialIDs, err := insertRecord(ctx, q, payload)
	if err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "create", "record", recordID, map[string]any{
		"batch_id": payload["batch_id"], "vials": len(vialIDs),
	}); err != nil {
		return nil, err
	}
	record, err := queryOne(ctx, q, `SELECT * FROM culture_records WHERE id = ?`, recordID)
	if err != nil {
		return nil, err
	}
	if record == nil {
		return nil, notFoundError("传代记录不存在")
	}
	record["vials_created"] = vialIDs
	record["vials_count"] = len(vialIDs)
	return record, nil
}

func bulkCreate(ctx context.Context, q Querier, entries []any, username any) (map[string]any, error) {
	if len(entries) == 0 {
		return nil, validationError("提交内容为空")
	}
	results := make([]map[string]any, 0, len(entries))
	success := 0
	vialsTotal := 0
	for index, raw := range entries {
		entry, ok := raw.(map[string]any)
		if !ok {
			results = append(results, map[string]any{"index": index, "ok": false, "error": "条目格式不正确"})
			continue
		}
		var recordID int64
		var vialIDs []int64
		err := savepoint(ctx, q.(*sql.Tx), fmt.Sprintf("rec%d", index), func() error {
			var innerErr error
			recordID, vialIDs, innerErr = insertRecord(ctx, q, entry)
			return innerErr
		})
		if err != nil {
			results = append(results, map[string]any{
				"index": index, "ok": false, "batch_id": entry["batch_id"], "error": err.Error(),
			})
			continue
		}
		success++
		vialsTotal += len(vialIDs)
		results = append(results, map[string]any{
			"index": index, "ok": true, "record_id": recordID,
			"batch_id": entry["batch_id"], "vials_created": len(vialIDs),
		})
	}
	if err := audit(ctx, q, username, "create_bulk", "record", nil, map[string]any{
		"success": success, "failed": len(results) - success, "vials": vialsTotal,
	}); err != nil {
		return nil, err
	}
	return map[string]any{
		"success": success, "failed": len(results) - success,
		"vials_created": vialsTotal, "results": results,
	}, nil
}

func updateRecord(ctx context.Context, q Querier, recordID int64, payload map[string]any, username any) (Row, error) {
	record, err := getOr404(ctx, q, "culture_records", recordID, "传代记录")
	if err != nil {
		return nil, err
	}
	batchID := rowInt(record, "batch_id")
	assignments := []string{}
	args := []any{}
	fields := []string{}
	if hasKey(payload, "passage") {
		minimum := int64(1)
		value, err := normalizeInt(payload["passage"], "传代次数", true, &minimum)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "passage = ?")
		args = append(args, *value)
		fields = append(fields, "passage")
	}
	if hasKey(payload, "date") {
		value, err := normalizeDate(payload["date"], "传代日期", true)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "date = ?")
		args = append(args, *value)
		fields = append(fields, "date")
	}
	if hasKey(payload, "harvested_cells") {
		zero := 0.0
		value, err := normalizeNumber(payload["harvested_cells"], "收获细胞数", true, &zero)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "harvested_cells = ?")
		args = append(args, *value)
		fields = append(fields, "harvested_cells")
	}
	if hasKey(payload, "inoculum_dishes") {
		one := int64(1)
		value, err := normalizeInt(payload["inoculum_dishes"], "种下盘数", true, &one)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "inoculum_dishes = ?")
		args = append(args, *value)
		fields = append(fields, "inoculum_dishes")
	}
	if hasKey(payload, "per_dish_cells") {
		zero := 0.0
		value, err := normalizeNumber(payload["per_dish_cells"], "每盘细胞数", false, &zero)
		if err != nil {
			return nil, err
		}
		if value == nil {
			value = &zero
		}
		dishes := rowInt(record, "inoculum_dishes")
		if dishes == 0 {
			dishes = 1
		}
		// If the request also changed dishes, use the new value.
		for i, field := range fields {
			if field == "inoculum_dishes" {
				dishes = args[i].(int64)
				break
			}
		}
		inoculum := roundTo(float64(dishes)*(*value), 4)
		assignments = append(assignments, "inoculum_cells = ?")
		args = append(args, inoculum)
		fields = append(fields, "per_dish_cells")
	} else if hasKey(payload, "inoculum_cells") {
		zero := 0.0
		value, err := normalizeNumber(payload["inoculum_cells"], "接种细胞数", false, &zero)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "inoculum_cells = ?")
		args = append(args, nullableFloat(value))
		fields = append(fields, "inoculum_cells")
	}
	if hasKey(payload, "status") {
		value, err := normalizeChoice(payload["status"], statusChoices, "细胞状态", "", false)
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
	recordDate := rowString(record, "date")
	for i, field := range fields {
		if field == "date" {
			recordDate = args[i].(string)
			break
		}
	}
	if hasKey(payload, "next_passage_days") {
		zero := int64(0)
		days, err := normalizeInt(payload["next_passage_days"], "下次传代间隔", false, &zero)
		if err != nil {
			return nil, err
		}
		if days != nil && *days > 0 {
			parsed, _ := time.Parse("2006-01-02", recordDate)
			assignments = append(assignments, "next_passage_date = ?")
			args = append(args, parsed.AddDate(0, 0, int(*days)).Format("2006-01-02"))
			fields = append(fields, "next_passage_date")
		}
	} else if hasKey(payload, "next_passage_date") {
		value, err := normalizeDate(payload["next_passage_date"], "建议下次传代日期", false)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "next_passage_date = ?")
		args = append(args, nullableString(value))
		fields = append(fields, "next_passage_date")
	}
	if len(assignments) > 0 {
		args = append(args, recordID)
		if _, err := q.ExecContext(ctx,
			"UPDATE culture_records SET "+strings.Join(assignments, ", ")+" WHERE id = ?", args...); err != nil {
			return nil, err
		}
		if _, err := recalculateBatch(ctx, q, batchID); err != nil {
			return nil, err
		}
		if _, err := refreshActiveRecord(ctx, q, batchID); err != nil {
			return nil, err
		}
		if err := audit(ctx, q, username, "update", "record", recordID, map[string]any{"fields": fields}); err != nil {
			return nil, err
		}
	}
	updated, err := queryOne(ctx, q, `SELECT * FROM culture_records WHERE id = ?`, recordID)
	if err != nil {
		return nil, err
	}
	if updated == nil {
		return nil, notFoundError("传代记录已被删除")
	}
	updated["per_dish_cells"] = perDish(updated)
	return updated, nil
}

func bulkUpdate(ctx context.Context, q Querier, entries []any, username any) (map[string]any, error) {
	if len(entries) == 0 {
		return nil, validationError("提交内容为空")
	}
	results := make([]map[string]any, 0, len(entries))
	success := 0
	for index, raw := range entries {
		entry, ok := raw.(map[string]any)
		if !ok {
			results = append(results, map[string]any{"index": index, "ok": false, "error": "条目格式不正确"})
			continue
		}
		recordIDValue := entry["id"]
		if recordIDValue == nil {
			recordIDValue = entry["record_id"]
		}
		recordID, ok := asInt(recordIDValue)
		if !ok || recordID == 0 {
			results = append(results, map[string]any{"index": index, "ok": false, "error": "缺少记录 id"})
			continue
		}
		err := savepoint(ctx, q.(*sql.Tx), fmt.Sprintf("upd%d", index), func() error {
			_, innerErr := updateRecord(ctx, q, recordID, entry, username)
			return innerErr
		})
		if err != nil {
			results = append(results, map[string]any{
				"index": index, "ok": false, "record_id": recordID, "error": err.Error(),
			})
			continue
		}
		success++
		results = append(results, map[string]any{"index": index, "ok": true, "record_id": recordID})
	}
	return map[string]any{"success": success, "failed": len(results) - success, "results": results}, nil
}

func deleteRecord(ctx context.Context, q Querier, recordID int64, username any) (map[string]any, error) {
	record, err := getOr404(ctx, q, "culture_records", recordID, "传代记录")
	if err != nil {
		return nil, err
	}
	batchID := rowInt(record, "batch_id")
	if _, err := q.ExecContext(ctx, `DELETE FROM culture_records WHERE id = ?`, recordID); err != nil {
		return nil, err
	}
	if _, err := recalculateBatch(ctx, q, batchID); err != nil {
		return nil, err
	}
	if _, err := refreshActiveRecord(ctx, q, batchID); err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "delete", "record", recordID, map[string]any{"batch_id": batchID}); err != nil {
		return nil, err
	}
	return map[string]any{"deleted": recordID, "batch_id": batchID}, nil
}
