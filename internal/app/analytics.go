package app

import (
	"context"
	"fmt"
	"math"
	"sort"
	"strings"
	"time"
)

func dashboard(ctx context.Context, q Querier) (map[string]any, error) {
	today := time.Now()
	weekAgo := today.AddDate(0, 0, -7).Format("2006-01-02")
	scalar := func(sqlText string, args ...any) int {
		var value int
		if err := q.QueryRowContext(ctx, sqlText, args...).Scan(&value); err != nil {
			return 0
		}
		return value
	}
	activeBatches := scalar(`SELECT COUNT(*) FROM culture_batches WHERE is_active = 1`)
	activeLines := scalar(`SELECT COUNT(DISTINCT cell_line_id) FROM culture_batches WHERE is_active = 1`)
	totalLines := scalar(`SELECT COUNT(*) FROM cell_lines`)
	totalGroups := scalar(`SELECT COUNT(*) FROM cell_groups`)
	totalVials := scalar(`SELECT COUNT(*) FROM frozen_vials`)
	inStockVials := scalar(`SELECT COUNT(*) FROM frozen_vials WHERE status = '在库'`)
	totalRecords := scalar(`SELECT COUNT(*) FROM culture_records`)
	recentRecords := scalar(`SELECT COUNT(*) FROM culture_records WHERE date >= ?`, weekAgo)

	dueRows, err := queryMaps(ctx, q, `
		SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, cl.id AS cell_line_id,
		       cr.next_passage_date, cr.passage, cr.status, cr.cumulative_pd
		FROM culture_batches cb
		JOIN cell_lines cl ON cl.id = cb.cell_line_id
		JOIN culture_records cr ON cr.id = (
		    SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1
		    ORDER BY r.date DESC, r.id DESC LIMIT 1
		)
		WHERE cb.is_active = 1 AND cr.next_passage_date IS NOT NULL AND cr.next_passage_date <> ''
		ORDER BY cr.next_passage_date`)
	if err != nil {
		return nil, err
	}
	dueSoon := []Row{}
	for _, row := range dueRows {
		remaining := remainingDays(row["next_passage_date"], today)
		row["remaining_days"] = remaining
		if remaining != nil && *remaining <= 3 {
			dueSoon = append(dueSoon, row)
		}
	}

	recent, err := queryMaps(ctx, q, `
		SELECT cr.id, cr.date, cr.passage, cr.pd, cr.cumulative_pd, cr.harvested_cells,
		       cr.inoculum_cells, cr.inoculum_dishes, cr.status, cr.notes,
		       cb.id AS batch_id, cb.batch_name, cl.name AS cell_line
		FROM culture_records cr
		JOIN culture_batches cb ON cb.id = cr.batch_id
		JOIN cell_lines cl ON cl.id = cb.cell_line_id
		ORDER BY cr.date DESC, cr.id DESC LIMIT 10`)
	if err != nil {
		return nil, err
	}
	monthStart := time.Date(today.Year(), today.Month(), 1, 0, 0, 0, 0, time.UTC).
		AddDate(0, 0, -150)
	monthStart = time.Date(monthStart.Year(), monthStart.Month(), 1, 0, 0, 0, 0, time.UTC)
	monthly, err := queryMaps(ctx, q, `
		SELECT substr(date, 1, 7) AS month, COUNT(*) AS count
		FROM culture_records WHERE date >= ?
		GROUP BY month ORDER BY month`, monthStart.Format("2006-01-02"))
	if err != nil {
		return nil, err
	}
	return map[string]any{
		"stats": map[string]any{
			"active_cell_lines":   activeLines,
			"active_batches":      activeBatches,
			"total_cell_lines":    totalLines,
			"total_groups":        totalGroups,
			"total_vials":         totalVials,
			"in_stock_vials":      inStockVials,
			"total_records":       totalRecords,
			"records_last_7_days": recentRecords,
		},
		"due_soon":         dueSoon,
		"all_due":          dueRows,
		"recent_records":   recent,
		"records_by_month": monthly,
		"today":            today.Format("2006-01-02"),
	}, nil
}

func groupRates(ctx context.Context, q Querier, groupID int64) ([]Row, error) {
	memberIDs, err := activeMemberIDs(ctx, q, groupID)
	if err != nil {
		return nil, err
	}
	if len(memberIDs) == 0 {
		return []Row{}, nil
	}
	args := make([]any, 0, len(memberIDs)+1)
	args = append(args, groupID)
	for _, id := range memberIDs {
		args = append(args, id)
	}
	batches, err := queryMaps(ctx, q, `
		SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, cl.id AS cell_line_id,
		       gm.sort_order
		FROM culture_batches cb
		JOIN cell_lines cl ON cl.id = cb.cell_line_id
		LEFT JOIN cell_group_members gm ON gm.group_id = ? AND gm.cell_line_id = cb.cell_line_id
		WHERE cb.is_active = 1 AND cb.cell_line_id IN (`+placeholders(len(memberIDs))+`)
		ORDER BY COALESCE(gm.sort_order, 9999), cl.name, cb.batch_name`, args...)
	if err != nil {
		return nil, err
	}
	results := []Row{}
	for _, batch := range batches {
		records, err := queryMaps(ctx, q,
			`SELECT date, pd, cumulative_pd FROM culture_records WHERE batch_id = ?
			 ORDER BY date ASC, id ASC`, rowInt(batch, "batch_id"))
		if err != nil {
			return nil, err
		}
		samples := []Row{}
		var previousDate *time.Time
		for _, record := range records {
			currentDate, err := time.Parse("2006-01-02", rowString(record, "date"))
			if err != nil {
				continue
			}
			if previousDate != nil {
				interval := int(currentDate.Sub(*previousDate).Hours() / 24)
				pdValue, ok := asFloat(record["pd"])
				if interval > 0 && ok {
					samples = append(samples, Row{
						"date":          rowString(record, "date"),
						"interval_days": interval,
						"pd":            pdValue,
						"pd_per_day":    roundTo(pdValue/float64(interval), 4),
					})
				}
			}
			copyDate := currentDate
			previousDate = &copyDate
		}
		span := 0
		var overall *float64
		if len(records) > 0 {
			first := records[0]
			last := records[len(records)-1]
			firstDate, err1 := time.Parse("2006-01-02", rowString(first, "date"))
			lastDate, err2 := time.Parse("2006-01-02", rowString(last, "date"))
			if err1 == nil && err2 == nil {
				span = int(lastDate.Sub(firstDate).Hours() / 24)
				if span > 0 {
					value := roundTo((rowFloat(last, "cumulative_pd")-rowFloat(first, "cumulative_pd"))/float64(span), 4)
					overall = &value
				}
			}
		}
		var average *float64
		if len(samples) > 0 {
			sum := 0.0
			for _, sample := range samples {
				sum += rowFloat(sample, "pd_per_day")
			}
			value := roundTo(sum/float64(len(samples)), 4)
			average = &value
		}
		var cv *float64
		if len(samples) >= 2 {
			mean := 0.0
			for _, sample := range samples {
				mean += rowFloat(sample, "pd_per_day")
			}
			mean /= float64(len(samples))
			if mean != 0 {
				variance := 0.0
				for _, sample := range samples {
					diff := rowFloat(sample, "pd_per_day") - mean
					variance += diff * diff
				}
				variance /= float64(len(samples))
				value := roundTo(math.Sqrt(variance)/math.Abs(mean), 3)
				cv = &value
			}
		}
		firstDate := any(nil)
		lastDate := any(nil)
		var cumulative any
		if len(records) > 0 {
			firstDate = records[0]["date"]
			lastDate = records[len(records)-1]["date"]
			cumulative = records[len(records)-1]["cumulative_pd"]
		}
		var overallHours, averageHours any
		if overall != nil && *overall > 0 {
			overallHours = roundTo(24 / *overall, 2)
		}
		if average != nil && *average > 0 {
			averageHours = roundTo(24 / *average, 2)
		}
		tail := samples
		if len(tail) > 3 {
			tail = tail[len(tail)-3:]
		}
		row := copyMap(batch)
		row["overall_pd_per_day"] = nullableFloat(overall)
		row["overall_doubling_hours"] = overallHours
		row["avg_pd_per_day"] = nullableFloat(average)
		row["avg_doubling_hours"] = averageHours
		row["interval_count"] = len(samples)
		row["span_days"] = span
		row["first_date"] = firstDate
		row["last_date"] = lastDate
		row["cumulative_pd"] = cumulative
		row["cv"] = nullableFloat(cv)
		row["samples"] = tail
		results = append(results, row)
	}
	return results, nil
}

func compareCurves(ctx context.Context, q Querier, lineIDs []int64, batchIDs []int64, includeEnded, normalize bool, startDate, basis string) (map[string]any, error) {
	if len(lineIDs) == 0 {
		return map[string]any{"series": []Row{}, "dates": []string{}, "skipped": []Row{},
			"normalize": normalize, "start_date": startDate, "basis": basis}, nil
	}
	if normalize && startDate == "" {
		return nil, validationError("标准化模式必须提供起始日期")
	}
	if basis != "date" && basis != "elapsed" {
		return nil, validationError("basis 必须是 date 或 elapsed")
	}
	args := make([]any, len(lineIDs))
	for i, id := range lineIDs {
		args[i] = id
	}
	rows, err := queryMaps(ctx, q, `
		SELECT cb.id AS batch_id, cb.batch_name, cb.revival_date, cb.is_active,
		       cl.id AS cell_line_id, cl.name AS cell_line
		FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
		WHERE cl.id IN (`+placeholders(len(lineIDs))+`)
		ORDER BY cl.name, cb.revival_date DESC, cb.id DESC`, args...)
	if err != nil {
		return nil, err
	}
	wanted := map[int64]bool{}
	for _, id := range batchIDs {
		wanted[id] = true
	}
	candidates := []Row{}
	for _, row := range rows {
		if len(wanted) > 0 {
			if wanted[rowInt(row, "batch_id")] {
				candidates = append(candidates, row)
			}
		} else if includeEnded || rowBool(row, "is_active") {
			candidates = append(candidates, row)
		}
	}
	order := map[int64]int{}
	for index, id := range lineIDs {
		order[id] = index
	}
	sort.SliceStable(candidates, func(i, j int) bool {
		a, b := candidates[i], candidates[j]
		ai, bi := order[rowInt(a, "cell_line_id")], order[rowInt(b, "cell_line_id")]
		if ai != bi {
			return ai < bi
		}
		if rowString(a, "revival_date") != rowString(b, "revival_date") {
			return rowString(a, "revival_date") < rowString(b, "revival_date")
		}
		return rowInt(a, "batch_id") < rowInt(b, "batch_id")
	})
	series := []Row{}
	skipped := []Row{}
	dateSet := map[string]bool{}
	for _, batch := range candidates {
		records, err := queryMaps(ctx, q,
			`SELECT date, passage, pd, cumulative_pd, harvested_cells FROM culture_records
			 WHERE batch_id = ? ORDER BY date ASC, id ASC`, rowInt(batch, "batch_id"))
		if err != nil {
			return nil, err
		}
		if len(records) == 0 {
			skipped = append(skipped, Row{
				"batch_id": rowInt(batch, "batch_id"), "name": rowString(batch, "batch_name"),
				"reason": "没有传代记录",
			})
			continue
		}
		for _, record := range records {
			dateSet[rowString(record, "date")] = true
		}
		firstDate, _ := time.Parse("2006-01-02", rowString(records[0], "date"))
		points := []Row{}
		var previous *Row
		for _, record := range records {
			recordDate, _ := time.Parse("2006-01-02", rowString(record, "date"))
			day := int(recordDate.Sub(firstDate).Hours() / 24)
			var interval any
			if previous != nil {
				prevDate, _ := time.Parse("2006-01-02", rowString(*previous, "date"))
				interval = int(recordDate.Sub(prevDate).Hours() / 24)
			}
			singlePD := rowFloat(record, "pd")
			var pdPerDay any
			if interval != nil && interval.(int) > 0 {
				pdPerDay = roundTo(singlePD/float64(interval.(int)), 4)
			}
			var doubling any
			if pdPerDay != nil && pdPerDay.(float64) > 0 {
				doubling = roundTo(24/pdPerDay.(float64), 2)
			}
			point := Row{
				"date":            rowString(record, "date"),
				"day":             day,
				"interval_days":   interval,
				"passage":         record["passage"],
				"value":           record["cumulative_pd"],
				"cumulative_pd":   record["cumulative_pd"],
				"pd":              record["pd"],
				"pd_per_day":      pdPerDay,
				"doubling_hours":  doubling,
				"harvested_cells": record["harvested_cells"],
			}
			points = append(points, point)
			copyRecord := record
			previous = &copyRecord
		}
		if normalize {
			baseline := findBaseline(points, startDate)
			if baseline == nil {
				skipped = append(skipped, Row{
					"batch_id": rowInt(batch, "batch_id"), "name": rowString(batch, "batch_name"),
					"reason": fmt.Sprintf("%s 之后没有记录", startDate),
				})
				continue
			}
			base := rowFloat(*baseline, "cumulative_pd")
			baselineDate := rowString(*baseline, "date")
			filtered := []Row{}
			for _, point := range points {
				if rowString(point, "date") >= baselineDate {
					filtered = append(filtered, point)
				}
			}
			points = filtered
			baselineDay := rowInt(*baseline, "day")
			for _, point := range points {
				value := normalizedValue(rowFloat(point, "cumulative_pd"), base)
				point["value"] = value
				point["fold"] = value
				point["day"] = rowInt(point, "day") - baselineDay
			}
		}
		rates := []float64{}
		for _, point := range points {
			if point["pd_per_day"] != nil {
				rates = append(rates, point["pd_per_day"].(float64))
			}
		}
		var average *float64
		if len(rates) > 0 {
			sum := 0.0
			for _, rate := range rates {
				sum += rate
			}
			value := roundTo(sum/float64(len(rates)), 4)
			average = &value
		}
		span := 0
		if len(points) > 1 {
			first, _ := time.Parse("2006-01-02", rowString(points[0], "date"))
			last, _ := time.Parse("2006-01-02", rowString(points[len(points)-1], "date"))
			span = int(last.Sub(first).Hours() / 24)
		}
		var overall, rawOverall *float64
		if span > 0 && len(points) > 0 {
			raw := (rowFloat(points[len(points)-1], "cumulative_pd") - rowFloat(points[0], "cumulative_pd")) / float64(span)
			rounded := roundTo(raw, 4)
			overall = &rounded
			rawOverall = &raw
		}
		var avgHours, overallHours any
		if average != nil && *average > 0 {
			avgHours = roundTo(24 / *average, 2)
		}
		if rawOverall != nil && *rawOverall > 0 {
			overallHours = roundTo(24 / *rawOverall, 2)
		}
		series = append(series, Row{
			"batch_id":               rowInt(batch, "batch_id"),
			"batch_name":             rowString(batch, "batch_name"),
			"cell_line":              rowString(batch, "cell_line"),
			"cell_line_id":           rowInt(batch, "cell_line_id"),
			"ended":                  !rowBool(batch, "is_active"),
			"name":                   rowString(batch, "batch_name"),
			"points":                 points,
			"avg_pd_per_day":         nullableFloat(average),
			"avg_doubling_hours":     avgHours,
			"overall_pd_per_day":     nullableFloat(overall),
			"overall_doubling_hours": overallHours,
		})
	}
	dates := make([]string, 0, len(dateSet))
	for date := range dateSet {
		dates = append(dates, date)
	}
	sort.Strings(dates)
	return map[string]any{
		"series": series, "dates": dates, "normalize": normalize,
		"start_date": nullableText(startDate), "basis": basis, "skipped": skipped,
	}, nil
}

func groupCurves(ctx context.Context, q Querier, groupID int64, normalize bool, startDate string, endedIDs []int64) (map[string]any, error) {
	memberIDs, err := activeMemberIDs(ctx, q, groupID)
	if err != nil {
		return nil, err
	}
	if len(memberIDs) == 0 {
		return map[string]any{"series": []Row{}, "dates": []string{}, "normalize": normalize,
			"start_date": startDate, "ended_batches": []Row{}, "skipped": []Row{}}, nil
	}
	args := make([]any, len(memberIDs))
	for i, id := range memberIDs {
		args[i] = id
	}
	activeBatches, err := queryMaps(ctx, q, `
		SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, 0 AS ended
		FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
		WHERE cb.is_active = 1 AND cb.cell_line_id IN (`+placeholders(len(memberIDs))+`)
		ORDER BY cl.name, cb.batch_name, cb.id`, args...)
	if err != nil {
		return nil, err
	}
	endedBatches, err := queryMaps(ctx, q, `
		SELECT cb.id AS batch_id, cb.batch_name, cl.name AS cell_line, 1 AS ended
		FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
		WHERE cb.is_active = 0 AND cb.cell_line_id IN (`+placeholders(len(memberIDs))+`)
		ORDER BY cl.name, cb.batch_name, cb.id`, args...)
	if err != nil {
		return nil, err
	}
	endedLookup := map[int64]Row{}
	for _, row := range endedBatches {
		endedLookup[rowInt(row, "batch_id")] = row
	}
	selectedEnded := []Row{}
	for _, id := range endedIDs {
		if row, ok := endedLookup[id]; ok {
			selectedEnded = append(selectedEnded, row)
		}
	}
	allBatches := append(append([]Row{}, activeBatches...), selectedEnded...)
	series := []Row{}
	skipped := []Row{}
	dateSet := map[string]bool{}
	for _, batch := range allBatches {
		records, err := queryMaps(ctx, q,
			`SELECT date, pd, cumulative_pd, harvested_cells, passage FROM culture_records
			 WHERE batch_id = ? ORDER BY date ASC, id ASC`, rowInt(batch, "batch_id"))
		if err != nil {
			return nil, err
		}
		if len(records) == 0 {
			skipped = append(skipped, Row{"batch_id": rowInt(batch, "batch_id"), "reason": "没有传代记录"})
			continue
		}
		for _, record := range records {
			dateSet[rowString(record, "date")] = true
		}
		points := make([]Row, 0, len(records))
		for _, record := range records {
			points = append(points, Row{
				"date":            rowString(record, "date"),
				"passage":         record["passage"],
				"value":           record["cumulative_pd"],
				"cumulative_pd":   record["cumulative_pd"],
				"pd":              record["pd"],
				"harvested_cells": record["harvested_cells"],
			})
		}
		if normalize {
			if startDate == "" {
				return nil, validationError("标准化模式必须提供起始日期")
			}
			baseline := findBaselineRecords(records, startDate)
			if baseline == nil {
				skipped = append(skipped, Row{
					"batch_id": rowInt(batch, "batch_id"),
					"reason":   fmt.Sprintf("%s 之后没有记录", startDate),
				})
				continue
			}
			base := rowFloat(*baseline, "cumulative_pd")
			baselineDate := rowString(*baseline, "date")
			filtered := []Row{}
			for _, point := range points {
				if rowString(point, "date") >= baselineDate {
					filtered = append(filtered, point)
				}
			}
			points = filtered
			for _, point := range points {
				value := normalizedValue(rowFloat(point, "cumulative_pd"), base)
				point["value"] = value
				point["fold"] = value
			}
		}
		series = append(series, Row{
			"batch_id":   rowInt(batch, "batch_id"),
			"batch_name": rowString(batch, "batch_name"),
			"cell_line":  rowString(batch, "cell_line"),
			"name":       rowString(batch, "batch_name"),
			"ended":      rowBool(batch, "ended"),
			"points":     points,
		})
	}
	dates := make([]string, 0, len(dateSet))
	for date := range dateSet {
		dates = append(dates, date)
	}
	sort.Strings(dates)
	endedList := make([]Row, 0, len(endedBatches))
	for _, row := range endedBatches {
		endedList = append(endedList, Row{
			"batch_id": rowInt(row, "batch_id"), "batch_name": rowString(row, "batch_name"),
			"cell_line": rowString(row, "cell_line"),
		})
	}
	return map[string]any{
		"series": series, "dates": dates, "normalize": normalize,
		"start_date": nullableText(startDate), "ended_batches": endedList, "skipped": skipped,
	}, nil
}

func findBaseline(points []Row, startDate string) *Row {
	for i := range points {
		if rowString(points[i], "date") >= startDate {
			return &points[i]
		}
	}
	return nil
}

func findBaselineRecords(records []Row, startDate string) *Row {
	for i := range records {
		if rowString(records[i], "date") >= startDate {
			return &records[i]
		}
	}
	return nil
}

func normalizedValue(cumulativePD, base float64) float64 {
	return roundTo(math.Pow(2, cumulativePD-base), 3)
}

func sortDates(dates map[string]bool) []string {
	result := make([]string, 0, len(dates))
	for date := range dates {
		result = append(result, date)
	}
	sort.Strings(result)
	return result
}

func trimComma(value string) string {
	return strings.TrimSpace(strings.Trim(value, ","))
}
