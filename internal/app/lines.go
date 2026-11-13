package app

import (
	"context"
	"fmt"
	"strings"
)

const lineSummarySQL = `
SELECT cl.*,
    (SELECT COUNT(*) FROM culture_batches b WHERE b.cell_line_id = cl.id AND b.is_active = 1) AS active_batch_count,
    (SELECT COUNT(*) FROM culture_batches b WHERE b.cell_line_id = cl.id) AS batch_count,
    (SELECT COUNT(*) FROM frozen_vials v WHERE v.cell_line_id = cl.id) AS total_vials,
    (SELECT COUNT(*) FROM frozen_vials v WHERE v.cell_line_id = cl.id AND v.status = '在库') AS in_stock_vials,
    (SELECT cr.cumulative_pd FROM culture_records cr
        JOIN culture_batches b3 ON b3.id = cr.batch_id
        WHERE b3.cell_line_id = cl.id
        ORDER BY cr.date DESC, cr.id DESC LIMIT 1) AS latest_pd,
    (SELECT cr.date FROM culture_records cr
        JOIN culture_batches b4 ON b4.id = cr.batch_id
        WHERE b4.cell_line_id = cl.id
        ORDER BY cr.date DESC, cr.id DESC LIMIT 1) AS latest_record_date
FROM cell_lines cl
`

type linePayload struct {
	Name                   *string
	Type                   *string
	RevivalDate            *string
	DefaultPassageInterval *int64
	Notes                  *string
	Species                *string
}

func cleanLinePayload(payload map[string]any, partial bool) (linePayload, error) {
	var data linePayload
	if !partial || hasKey(payload, "name") {
		name, err := requireNonEmpty(payload["name"], "细胞株名称")
		if err != nil {
			return data, err
		}
		if len([]rune(name)) > 120 {
			return data, validationError("细胞株名称过长（最多 120 字）")
		}
		data.Name = &name
	}
	if !partial || hasKey(payload, "type") {
		value, err := normalizeChoice(payload["type"], lineTypes, "细胞类型", "永生化", false)
		if err != nil {
			return data, err
		}
		data.Type = value
	}
	if !partial || hasKey(payload, "revival_date") {
		value, err := normalizeDate(payload["revival_date"], "复苏日期", false)
		if err != nil {
			return data, err
		}
		data.RevivalDate = value
	}
	if !partial || hasKey(payload, "default_passage_interval") {
		zero := int64(0)
		value, err := normalizeInt(payload["default_passage_interval"], "默认传代间隔", false, &zero)
		if err != nil {
			return data, err
		}
		if value == nil {
			value = &zero
		}
		data.DefaultPassageInterval = value
	}
	if !partial || hasKey(payload, "notes") {
		value, err := normalizeText(payload["notes"], 2000)
		if err != nil {
			return data, err
		}
		data.Notes = &value
	}
	// 标签是自由文本：不预设任何选项，用户填什么就是什么
	if !partial || hasKey(payload, "species") {
		value, err := normalizeText(payload["species"], 40)
		if err != nil {
			return data, err
		}
		data.Species = &value
	}
	return data, nil
}

func listLines(ctx context.Context, q Querier, search string) ([]Row, error) {
	if strings.TrimSpace(search) != "" {
		like := "%" + strings.TrimSpace(search) + "%"
		return queryMaps(ctx, q, lineSummarySQL+" WHERE cl.name LIKE ? OR cl.notes LIKE ? ORDER BY cl.name", like, like)
	}
	return queryMaps(ctx, q, lineSummarySQL+" ORDER BY cl.name")
}

func getLineSummary(ctx context.Context, q Querier, lineID int64) (Row, error) {
	row, err := queryOne(ctx, q, lineSummarySQL+" WHERE cl.id = ?", lineID)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, notFoundError(fmt.Sprintf("细胞株不存在（id=%d）", lineID))
	}
	return row, nil
}

func createLine(ctx context.Context, q Querier, payload map[string]any, username any) (Row, error) {
	data, err := cleanLinePayload(payload, false)
	if err != nil {
		return nil, err
	}
	existing, err := queryOne(ctx, q, `SELECT id FROM cell_lines WHERE name = ?`, *data.Name)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		return nil, conflictError(fmt.Sprintf("细胞株「%s」已存在", *data.Name))
	}
	revival := todayISO()
	if data.RevivalDate != nil {
		revival = *data.RevivalDate
	}
	interval := int64(0)
	if data.DefaultPassageInterval != nil {
		interval = *data.DefaultPassageInterval
	}
	notes := ""
	if data.Notes != nil {
		notes = *data.Notes
	}
	species := ""
	if data.Species != nil {
		species = *data.Species
	}
	result, err := q.ExecContext(ctx,
		`INSERT INTO cell_lines (name, revival_date, type, default_passage_interval, notes, species)
		 VALUES (?,?,?,?,?,?)`, *data.Name, revival, *data.Type, interval, notes, species)
	if err != nil {
		return nil, err
	}
	id, _ := result.LastInsertId()
	if err := audit(ctx, q, username, "create", "cell_line", id, map[string]any{
		"name": *data.Name, "type": *data.Type, "revival_date": revival,
		"default_passage_interval": interval, "notes": notes, "species": species,
	}); err != nil {
		return nil, err
	}
	return getLineSummary(ctx, q, id)
}

func updateLine(ctx context.Context, q Querier, lineID int64, payload map[string]any, username any) (Row, error) {
	if _, err := getOr404(ctx, q, "cell_lines", lineID, "细胞株"); err != nil {
		return nil, err
	}
	data, err := cleanLinePayload(payload, true)
	if err != nil {
		return nil, err
	}
	assignments := []string{}
	args := []any{}
	if data.Name != nil {
		existing, err := queryOne(ctx, q, `SELECT id FROM cell_lines WHERE name = ? AND id <> ?`, *data.Name, lineID)
		if err != nil {
			return nil, err
		}
		if existing != nil {
			return nil, conflictError(fmt.Sprintf("细胞株名称「%s」已被占用", *data.Name))
		}
		assignments = append(assignments, "name = ?")
		args = append(args, *data.Name)
	}
	if data.Type != nil {
		assignments = append(assignments, "type = ?")
		args = append(args, *data.Type)
	}
	if data.RevivalDate != nil {
		assignments = append(assignments, "revival_date = ?")
		args = append(args, *data.RevivalDate)
	}
	if data.DefaultPassageInterval != nil {
		assignments = append(assignments, "default_passage_interval = ?")
		args = append(args, *data.DefaultPassageInterval)
	}
	if data.Notes != nil {
		assignments = append(assignments, "notes = ?")
		args = append(args, *data.Notes)
	}
	if data.Species != nil {
		assignments = append(assignments, "species = ?")
		args = append(args, *data.Species)
	}
	if len(assignments) > 0 {
		args = append(args, lineID)
		if _, err := q.ExecContext(ctx,
			"UPDATE cell_lines SET "+strings.Join(assignments, ", ")+" WHERE id = ?", args...); err != nil {
			return nil, err
		}
		if err := audit(ctx, q, username, "update", "cell_line", lineID, payload); err != nil {
			return nil, err
		}
	}
	return getLineSummary(ctx, q, lineID)
}

func deleteLine(ctx context.Context, q Querier, lineID int64, username any) (map[string]any, error) {
	if _, err := getOr404(ctx, q, "cell_lines", lineID, "细胞株"); err != nil {
		return nil, err
	}
	deleted := map[string]any{}
	if result, err := q.ExecContext(ctx, `DELETE FROM frozen_vials WHERE cell_line_id = ?`, lineID); err == nil {
		count, _ := result.RowsAffected()
		deleted["vials"] = count
	}
	if result, err := q.ExecContext(ctx,
		`DELETE FROM culture_records WHERE batch_id IN (SELECT id FROM culture_batches WHERE cell_line_id = ?)`,
		lineID); err == nil {
		count, _ := result.RowsAffected()
		deleted["records"] = count
	}
	if result, err := q.ExecContext(ctx, `DELETE FROM culture_batches WHERE cell_line_id = ?`, lineID); err == nil {
		count, _ := result.RowsAffected()
		deleted["batches"] = count
	}
	if result, err := q.ExecContext(ctx, `DELETE FROM cell_group_members WHERE cell_line_id = ?`, lineID); err == nil {
		count, _ := result.RowsAffected()
		deleted["group_links"] = count
	}
	if _, err := q.ExecContext(ctx, `DELETE FROM cell_lines WHERE id = ?`, lineID); err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "delete", "cell_line", lineID, deleted); err != nil {
		return nil, err
	}
	return deleted, nil
}

func lineBatches(ctx context.Context, q Querier, lineID int64, includeEnded bool) ([]Row, error) {
	if _, err := getOr404(ctx, q, "cell_lines", lineID, "细胞株"); err != nil {
		return nil, err
	}
	sqlText := `SELECT cb.*,
	  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
	   ORDER BY r.date DESC, r.id DESC LIMIT 1) AS active_record_id,
	  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id
	   ORDER BY r.date DESC, r.id DESC LIMIT 1) AS latest_record_id,
	  (SELECT COUNT(*) FROM culture_records r WHERE r.batch_id = cb.id) AS records_count
	FROM culture_batches cb WHERE cb.cell_line_id = ?`
	args := []any{lineID}
	if !includeEnded {
		sqlText += " AND cb.is_active = 1"
	}
	sqlText += " ORDER BY cb.is_active DESC, COALESCE(cb.revival_date, '') DESC, cb.id DESC"
	batches, err := queryMaps(ctx, q, sqlText, args...)
	if err != nil {
		return nil, err
	}
	for _, batch := range batches {
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
	}
	return batches, nil
}

func lineVials(ctx context.Context, q Querier, lineID int64) ([]Row, error) {
	if _, err := getOr404(ctx, q, "cell_lines", lineID, "细胞株"); err != nil {
		return nil, err
	}
	return queryMaps(ctx, q,
		`SELECT * FROM frozen_vials WHERE cell_line_id = ?
		 ORDER BY COALESCE(freeze_date, '') DESC, location`, lineID)
}

// assignSpecies 批量给细胞株打标签。
// onlyUnset 为真时只处理还没打标签的细胞株，不会覆盖已单独设置的值。
func assignSpecies(ctx context.Context, q Querier, species string, lineIDs []int64,
	onlyUnset bool, username any) (map[string]any, error) {
	value := strings.TrimSpace(species)
	if value == "" {
		return nil, validationError("标签不能为空")
	}

	sql := `SELECT id, name FROM cell_lines WHERE 1 = 1`
	args := []any{}
	if len(lineIDs) > 0 {
		placeholders := make([]string, len(lineIDs))
		for i, id := range lineIDs {
			placeholders[i] = "?"
			args = append(args, id)
		}
		sql += " AND id IN (" + strings.Join(placeholders, ",") + ")"
	}
	if onlyUnset {
		sql += " AND (species IS NULL OR TRIM(species) = '')"
	}
	sql += " ORDER BY id"

	rows, err := queryMaps(ctx, q, sql, args...)
	if err != nil {
		return nil, err
	}
	names := make([]string, 0, len(rows))
	for _, row := range rows {
		lineID := rowInt(row, "id")
		if _, err := q.ExecContext(ctx, `UPDATE cell_lines SET species = ? WHERE id = ?`, value, lineID); err != nil {
			return nil, err
		}
		names = append(names, rowString(row, "name"))
	}
	if err := audit(ctx, q, username, "assign_species", "cell_line", nil, map[string]any{
		"species": value, "updated": len(rows), "only_unset": onlyUnset,
	}); err != nil {
		return nil, err
	}
	return map[string]any{"species": value, "updated": len(rows), "names": names}, nil
}

func hasKey(payload map[string]any, key string) bool {
	_, ok := payload[key]
	return ok
}

func requireNonEmpty(value any, field string) (string, error) {
	text := strings.TrimSpace(asString(value))
	if text == "" {
		return "", validationError(field + "不能为空")
	}
	return text, nil
}
