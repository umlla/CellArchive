package app

import (
	"context"
	"fmt"
	"sort"
	"strings"
	"time"
)

func listGroups(ctx context.Context, q Querier) ([]Row, error) {
	groups, err := queryMaps(ctx, q, `SELECT * FROM cell_groups ORDER BY group_name`)
	if err != nil {
		return nil, err
	}
	if len(groups) == 0 {
		return groups, nil
	}
	members, err := queryMaps(ctx, q,
		`SELECT gm.group_id, gm.cell_line_id, gm.sort_order, cl.name, cl.type,
		  (SELECT COUNT(*) FROM culture_batches b WHERE b.cell_line_id = cl.id AND b.is_active = 1) AS active_batch_count
		 FROM cell_group_members gm JOIN cell_lines cl ON cl.id = gm.cell_line_id
		 ORDER BY gm.group_id, gm.sort_order, cl.name`)
	if err != nil {
		return nil, err
	}
	byGroup := map[int64][]Row{}
	for _, member := range members {
		groupID := rowInt(member, "group_id")
		byGroup[groupID] = append(byGroup[groupID], Row{
			"cell_line_id":       rowInt(member, "cell_line_id"),
			"name":               rowString(member, "name"),
			"type":               rowString(member, "type"),
			"sort_order":         rowInt(member, "sort_order"),
			"active_batch_count": rowInt(member, "active_batch_count"),
		})
	}
	for _, group := range groups {
		list := byGroup[rowInt(group, "id")]
		if list == nil {
			list = []Row{}
		}
		group["members"] = list
		group["member_count"] = len(list)
	}
	return groups, nil
}

func getGroup(ctx context.Context, q Querier, groupID int64) (Row, error) {
	group, err := getOr404(ctx, q, "cell_groups", groupID, "细胞组")
	if err != nil {
		return nil, err
	}
	members, err := queryMaps(ctx, q,
		`SELECT gm.cell_line_id, gm.sort_order, cl.name, cl.type
		 FROM cell_group_members gm JOIN cell_lines cl ON cl.id = gm.cell_line_id
		 WHERE gm.group_id = ? ORDER BY gm.sort_order, cl.name`, groupID)
	if err != nil {
		return nil, err
	}
	if members == nil {
		members = []Row{}
	}
	group["members"] = members
	group["member_count"] = len(members)
	return group, nil
}

func createGroup(ctx context.Context, q Querier, payload map[string]any, username any) (Row, error) {
	name, err := requireNonEmpty(payload["group_name"], "组名")
	if err != nil {
		return nil, err
	}
	notes, err := normalizeText(payload["notes"], 2000)
	if err != nil {
		return nil, err
	}
	existing, err := queryOne(ctx, q, `SELECT id FROM cell_groups WHERE group_name = ?`, name)
	if err != nil {
		return nil, err
	}
	if existing != nil {
		return nil, conflictError(fmt.Sprintf("细胞组「%s」已存在", name))
	}
	result, err := q.ExecContext(ctx, `INSERT INTO cell_groups (group_name, notes) VALUES (?,?)`, name, notes)
	if err != nil {
		return nil, err
	}
	groupID, _ := result.LastInsertId()
	if raw, ok := payload["cell_line_ids"]; ok && raw != nil {
		items, ok := raw.([]any)
		if ok && len(items) > 0 {
			if _, err := setMembers(ctx, q, groupID, items, username); err != nil {
				return nil, err
			}
		}
	}
	if err := audit(ctx, q, username, "create", "group", groupID, map[string]any{"group_name": name}); err != nil {
		return nil, err
	}
	return getGroup(ctx, q, groupID)
}

func updateGroup(ctx context.Context, q Querier, groupID int64, payload map[string]any, username any) (Row, error) {
	if _, err := getOr404(ctx, q, "cell_groups", groupID, "细胞组"); err != nil {
		return nil, err
	}
	assignments := []string{}
	args := []any{}
	fields := []string{}
	if hasKey(payload, "group_name") {
		name, err := requireNonEmpty(payload["group_name"], "组名")
		if err != nil {
			return nil, err
		}
		clash, err := queryOne(ctx, q, `SELECT id FROM cell_groups WHERE group_name = ? AND id <> ?`, name, groupID)
		if err != nil {
			return nil, err
		}
		if clash != nil {
			return nil, conflictError(fmt.Sprintf("细胞组「%s」已存在", name))
		}
		assignments = append(assignments, "group_name = ?")
		args = append(args, name)
		fields = append(fields, "group_name")
	}
	if hasKey(payload, "notes") {
		notes, err := normalizeText(payload["notes"], 2000)
		if err != nil {
			return nil, err
		}
		assignments = append(assignments, "notes = ?")
		args = append(args, notes)
		fields = append(fields, "notes")
	}
	if len(assignments) > 0 {
		args = append(args, groupID)
		if _, err := q.ExecContext(ctx,
			"UPDATE cell_groups SET "+strings.Join(assignments, ", ")+" WHERE id = ?", args...); err != nil {
			return nil, err
		}
		if err := audit(ctx, q, username, "update", "group", groupID, map[string]any{"fields": fields}); err != nil {
			return nil, err
		}
	}
	return getGroup(ctx, q, groupID)
}

func deleteGroup(ctx context.Context, q Querier, groupID int64, username any) (map[string]any, error) {
	group, err := getOr404(ctx, q, "cell_groups", groupID, "细胞组")
	if err != nil {
		return nil, err
	}
	if _, err := q.ExecContext(ctx, `DELETE FROM cell_group_members WHERE group_id = ?`, groupID); err != nil {
		return nil, err
	}
	if _, err := q.ExecContext(ctx, `DELETE FROM cell_groups WHERE id = ?`, groupID); err != nil {
		return nil, err
	}
	if err := audit(ctx, q, username, "delete", "group", groupID, map[string]any{
		"group_name": rowString(group, "group_name"),
	}); err != nil {
		return nil, err
	}
	return map[string]any{"deleted": groupID}, nil
}

func setMembers(ctx context.Context, q Querier, groupID int64, members []any, username any) (Row, error) {
	if _, err := getOr404(ctx, q, "cell_groups", groupID, "细胞组"); err != nil {
		return nil, err
	}
	normalized := []int64{}
	seen := map[int64]bool{}
	for _, item := range members {
		var raw any = item
		if object, ok := item.(map[string]any); ok {
			if value, exists := object["cell_line_id"]; exists {
				raw = value
			} else {
				raw = object["id"]
			}
		}
		lineID, ok := asInt(raw)
		if !ok {
			return nil, validationError(fmt.Sprintf("无效的细胞株 id：%v", raw))
		}
		if !seen[lineID] {
			seen[lineID] = true
			normalized = append(normalized, lineID)
		}
	}
	if len(normalized) > 0 {
		marks := placeholders(len(normalized))
		args := make([]any, len(normalized))
		for i, id := range normalized {
			args[i] = id
		}
		found, err := queryMaps(ctx, q,
			`SELECT id FROM cell_lines WHERE id IN (`+marks+`)`, args...)
		if err != nil {
			return nil, err
		}
		foundSet := map[int64]bool{}
		for _, row := range found {
			foundSet[rowInt(row, "id")] = true
		}
		missing := []int64{}
		for _, id := range normalized {
			if !foundSet[id] {
				missing = append(missing, id)
			}
		}
		if len(missing) > 0 {
			sort.Slice(missing, func(i, j int) bool { return missing[i] < missing[j] })
			return nil, validationError(fmt.Sprintf("细胞株不存在：%v", missing))
		}
	}
	if _, err := q.ExecContext(ctx, `DELETE FROM cell_group_members WHERE group_id = ?`, groupID); err != nil {
		return nil, err
	}
	for index, lineID := range normalized {
		if _, err := q.ExecContext(ctx,
			`INSERT INTO cell_group_members (group_id, cell_line_id, sort_order) VALUES (?,?,?)`,
			groupID, lineID, index+1); err != nil {
			return nil, err
		}
	}
	if err := audit(ctx, q, username, "set_members", "group", groupID, map[string]any{
		"member_ids": normalized,
	}); err != nil {
		return nil, err
	}
	return getGroup(ctx, q, groupID)
}

func activeMemberIDs(ctx context.Context, q Querier, groupID int64) ([]int64, error) {
	if _, err := getOr404(ctx, q, "cell_groups", groupID, "细胞组"); err != nil {
		return nil, err
	}
	rows, err := queryMaps(ctx, q,
		`SELECT cell_line_id FROM cell_group_members WHERE group_id = ? ORDER BY sort_order, cell_line_id`,
		groupID)
	if err != nil {
		return nil, err
	}
	ids := make([]int64, 0, len(rows))
	for _, row := range rows {
		ids = append(ids, rowInt(row, "cell_line_id"))
	}
	return ids, nil
}

func groupStatus(ctx context.Context, q Querier, groupID int64) ([]Row, error) {
	group, err := getGroup(ctx, q, groupID)
	if err != nil {
		return nil, err
	}
	members := group["members"].([]Row)
	if len(members) == 0 {
		return []Row{}, nil
	}
	ids := make([]int64, 0, len(members))
	for _, member := range members {
		ids = append(ids, rowInt(member, "cell_line_id"))
	}
	args := make([]any, 0, len(ids)+1)
	args = append(args, groupID)
	for _, id := range ids {
		args = append(args, id)
	}
	rows, err := queryMaps(ctx, q, `
		SELECT cb.id AS batch_id, cb.batch_name, cb.revival_date, cb.initial_pd,
		       cl.id AS cell_line_id, cl.name AS cell_name, cl.type, cl.default_passage_interval,
		       gm.sort_order,
		       cr.id AS record_id, cr.passage, cr.date AS last_passage,
		       cr.inoculum_cells, cr.inoculum_dishes, cr.harvested_cells,
		       cr.pd, cr.cumulative_pd, cr.status, cr.next_passage_date, cr.notes
		FROM culture_batches cb
		JOIN cell_lines cl ON cl.id = cb.cell_line_id
		LEFT JOIN cell_group_members gm ON gm.group_id = ? AND gm.cell_line_id = cb.cell_line_id
		LEFT JOIN culture_records cr ON cr.id = (
		    SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
		    ORDER BY r.date DESC, r.id DESC LIMIT 1
		)
		WHERE cb.is_active = 1 AND cb.cell_line_id IN (`+placeholders(len(ids))+`)
		ORDER BY COALESCE(gm.sort_order, 9999), cl.name, cb.batch_name, cb.id`, args...)
	if err != nil {
		return nil, err
	}
	today := time.Now()
	for _, row := range rows {
		row["remaining_days"] = remainingDays(row["next_passage_date"], today)
		if row["cumulative_pd"] == nil {
			row["cumulative_pd"] = row["initial_pd"]
		}
	}
	return rows, nil
}

func groupRecords(ctx context.Context, q Querier, groupID int64) ([]Row, error) {
	group, err := getGroup(ctx, q, groupID)
	if err != nil {
		return nil, err
	}
	members := group["members"].([]Row)
	if len(members) == 0 {
		return []Row{}, nil
	}
	ids := make([]int64, 0, len(members))
	for _, member := range members {
		ids = append(ids, rowInt(member, "cell_line_id"))
	}
	args := make([]any, len(ids))
	for i, id := range ids {
		args[i] = id
	}
	rows, err := queryMaps(ctx, q, `
		SELECT cr.*, cb.batch_name, cb.initial_pd, cb.initial_cell_count,
		       cl.name AS cell_line, cl.type AS cell_type
		FROM culture_records cr
		JOIN culture_batches cb ON cb.id = cr.batch_id
		JOIN cell_lines cl ON cl.id = cb.cell_line_id
		WHERE cb.is_active = 1 AND cb.cell_line_id IN (`+placeholders(len(ids))+`)
		ORDER BY cl.name, cb.batch_name, cr.date, cr.id`, args...)
	if err != nil {
		return nil, err
	}
	for _, row := range rows {
		row["per_dish_cells"] = perDish(row)
	}
	return rows, nil
}

func groupCreateBatches(ctx context.Context, q Querier, groupID int64, payload map[string]any, username any) (map[string]any, error) {
	group, err := getGroup(ctx, q, groupID)
	if err != nil {
		return nil, err
	}
	members := group["members"].([]Row)
	if len(members) == 0 {
		return nil, validationError("该细胞组还没有成员")
	}
	created := []map[string]any{}
	errorsList := []map[string]any{}
	for _, member := range members {
		lineID := rowInt(member, "cell_line_id")
		entry := copyMap(payload)
		entry["cell_line_id"] = lineID
		batch, err := createBatch(ctx, q, entry, username)
		if err != nil {
			errorsList = append(errorsList, map[string]any{
				"cell_line_id": lineID, "name": rowString(member, "name"), "error": err.Error(),
			})
			continue
		}
		created = append(created, map[string]any{
			"cell_line_id": lineID, "batch_id": rowInt(batch, "id"), "batch_name": rowString(batch, "batch_name"),
		})
	}
	if err := audit(ctx, q, username, "create_bulk", "batch", nil, map[string]any{
		"group_id": groupID, "created": len(created), "failed": len(errorsList),
	}); err != nil {
		return nil, err
	}
	return map[string]any{"created": created, "errors": errorsList, "group": rowString(group, "group_name")}, nil
}

func groupTerminate(ctx context.Context, q Querier, groupID int64, reason any, username any) (map[string]any, error) {
	group, err := getGroup(ctx, q, groupID)
	if err != nil {
		return nil, err
	}
	reasonValue, err := normalizeChoice(reason, endReasons, "终止原因", "其他", false)
	if err != nil {
		return nil, err
	}
	members := group["members"].([]Row)
	if len(members) == 0 {
		return nil, validationError("该细胞组还没有成员")
	}
	ids := make([]int64, 0, len(members))
	for _, member := range members {
		ids = append(ids, rowInt(member, "cell_line_id"))
	}
	args := make([]any, len(ids))
	for i, id := range ids {
		args[i] = id
	}
	rows, err := queryMaps(ctx, q,
		`SELECT id FROM culture_batches WHERE is_active = 1 AND cell_line_id IN (`+placeholders(len(ids))+`)`,
		args...)
	if err != nil {
		return nil, err
	}
	terminated := []int64{}
	for _, row := range rows {
		batchID := rowInt(row, "id")
		if _, err := terminateBatch(ctx, q, batchID, *reasonValue, username); err != nil {
			if apiErr, ok := err.(*APIError); ok && apiErr.Status == 409 {
				continue
			}
			return nil, err
		}
		terminated = append(terminated, batchID)
	}
	if err := audit(ctx, q, username, "terminate_bulk", "batch", nil, map[string]any{
		"group_id": groupID, "reason": *reasonValue, "count": len(terminated),
	}); err != nil {
		return nil, err
	}
	return map[string]any{"terminated": terminated, "count": len(terminated), "reason": *reasonValue}, nil
}

func copyMap(source map[string]any) map[string]any {
	target := make(map[string]any, len(source))
	for key, value := range source {
		target[key] = value
	}
	return target
}
