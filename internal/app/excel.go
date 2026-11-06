package app

import (
	"bytes"
	"context"
	"encoding/csv"
	"fmt"
	"time"

	"github.com/xuri/excelize/v2"
)

func writeSheet(f *excelize.File, title string, headers []string, rows [][]any, first bool) error {
	var sheet string
	if first {
		sheet = f.GetSheetName(0)
		if err := f.SetSheetName(sheet, title); err != nil {
			return err
		}
		sheet = title
	} else {
		index, err := f.NewSheet(title)
		if err != nil {
			return err
		}
		sheet = f.GetSheetName(index)
	}
	for col, header := range headers {
		cell, _ := excelize.CoordinatesToCellName(col+1, 1)
		if err := f.SetCellValue(sheet, cell, header); err != nil {
			return err
		}
	}
	for rowIndex, row := range rows {
		for col, value := range row {
			cell, _ := excelize.CoordinatesToCellName(col+1, rowIndex+2)
			if value == nil {
				value = ""
			}
			if err := f.SetCellValue(sheet, cell, value); err != nil {
				return err
			}
		}
	}
	if len(headers) > 0 {
		lastCell, _ := excelize.CoordinatesToCellName(len(headers), 1)
		style, err := f.NewStyle(&excelize.Style{
			Font: &excelize.Font{Bold: true},
			Fill: excelize.Fill{Type: "pattern", Color: []string{"E8F1FB"}, Pattern: 1},
			Alignment: &excelize.Alignment{
				Horizontal: "center", Vertical: "center", WrapText: true,
			},
		})
		if err == nil {
			_ = f.SetCellStyle(sheet, "A1", lastCell, style)
		}
	}
	_ = f.SetPanes(sheet, &excelize.Panes{
		Freeze: true, YSplit: 1, TopLeftCell: "A2", ActivePane: "bottomLeft",
	})
	for col := range headers {
		width := 8
		for _, row := range rows {
			if col >= len(row) {
				continue
			}
			value := fmt.Sprint(row[col])
			display := 0
			for _, char := range value {
				if char > 127 {
					display += 2
				} else {
					display++
				}
			}
			if display+2 > width {
				width = display + 2
			}
			if width > 48 {
				width = 48
			}
		}
		_ = f.SetColWidth(sheet, columnLetter(col+1), columnLetter(col+1), float64(width))
	}
	return nil
}

func columnLetter(index int) string {
	letter, _ := excelize.ColumnNumberToName(index)
	return letter
}

func rowsFromMaps(rows []Row, columns []string) [][]any {
	result := make([][]any, 0, len(rows))
	for _, row := range rows {
		values := make([]any, len(columns))
		for i, column := range columns {
			values[i] = row[column]
		}
		result = append(result, values)
	}
	return result
}

func groupExport(ctx context.Context, q Querier, groupID int64, includeAll bool) (*bytes.Buffer, string, error) {
	group, err := getGroup(ctx, q, groupID)
	if err != nil {
		return nil, "", err
	}
	members := group["members"].([]Row)
	if len(members) == 0 {
		return nil, "", notFoundError("该细胞组没有成员，无法导出")
	}
	ids := make([]any, len(members))
	for i, member := range members {
		ids[i] = rowInt(member, "cell_line_id")
	}
	marks := placeholders(len(ids))
	lines, err := queryMaps(ctx, q, `
		SELECT id AS "ID", name AS "细胞名称", type AS "类型", revival_date AS "复苏日期",
		       default_passage_interval AS "默认传代间隔", notes AS "备注"
		FROM cell_lines WHERE id IN (`+marks+`) ORDER BY name`, ids...)
	if err != nil {
		return nil, "", err
	}
	batchFilter := ""
	if !includeAll {
		batchFilter = " AND cb.is_active = 1"
	}
	batches, err := queryMaps(ctx, q, `
		SELECT cb.id AS "ID", cl.name AS "细胞名称", cb.batch_name AS "批次名称",
		       cb.revival_date AS "复苏日期", cb.source_freeze_date AS "冻存来源日期",
		       cb.initial_pd AS "初始PD", cb.initial_cell_count AS "初始细胞数",
		       CASE cb.is_active WHEN 1 THEN '是' ELSE '否' END AS "是否活跃",
		       cb.end_date AS "终止日期", cb.end_reason AS "终止原因", cb.notes AS "备注"
		FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
		WHERE cl.id IN (`+marks+`)`+batchFilter+`
		ORDER BY cl.name, cb.revival_date, cb.id`, ids...)
	if err != nil {
		return nil, "", err
	}
	recordFilter := ""
	if !includeAll {
		recordFilter = " AND cr.is_active = 1"
	}
	records, err := queryMaps(ctx, q, `
		SELECT cr.id AS "ID", cl.name AS "细胞名称", cb.batch_name AS "批次名称",
		       cr.passage AS "代次", cr.date AS "日期",
		       cr.inoculum_cells AS "接种细胞数", cr.inoculum_dishes AS "盘数",
		       cr.harvested_cells AS "收获细胞数", cr.pd AS "本次PD",
		       cr.cumulative_pd AS "累计PD", cr.status AS "状态",
		       cr.next_passage_date AS "建议下次传代", cr.notes AS "备注"
		FROM culture_records cr
		JOIN culture_batches cb ON cb.id = cr.batch_id
		JOIN cell_lines cl ON cl.id = cb.cell_line_id
		WHERE cl.id IN (`+marks+`)`+recordFilter+`
		ORDER BY cl.name, cb.batch_name, cr.date, cr.id`, ids...)
	if err != nil {
		return nil, "", err
	}
	vials, err := queryMaps(ctx, q, `
		SELECT fv.id AS "ID", cl.name AS "细胞名称", fv.freeze_date AS "冻存日期",
		       fv.cell_count AS "细胞数", fv.location AS "位置", fv.pd AS "PD",
		       fv.status AS "状态", fv.notes AS "备注"
		FROM frozen_vials fv JOIN cell_lines cl ON cl.id = fv.cell_line_id
		WHERE cl.id IN (`+marks+`)
		ORDER BY cl.name, fv.location`, ids...)
	if err != nil {
		return nil, "", err
	}
	f := excelize.NewFile()
	defer f.Close()
	if err := writeSheet(f, "细胞株信息",
		[]string{"ID", "细胞名称", "类型", "复苏日期", "默认传代间隔", "备注"},
		rowsFromMaps(lines, []string{"ID", "细胞名称", "类型", "复苏日期", "默认传代间隔", "备注"}), true); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "培养批次",
		[]string{"ID", "细胞名称", "批次名称", "复苏日期", "冻存来源日期", "初始PD", "初始细胞数", "是否活跃", "终止日期", "终止原因", "备注"},
		rowsFromMaps(batches, []string{"ID", "细胞名称", "批次名称", "复苏日期", "冻存来源日期", "初始PD", "初始细胞数", "是否活跃", "终止日期", "终止原因", "备注"}), false); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "传代记录",
		[]string{"ID", "细胞名称", "批次名称", "代次", "日期", "接种细胞数", "盘数", "收获细胞数", "本次PD", "累计PD", "状态", "建议下次传代", "备注"},
		rowsFromMaps(records, []string{"ID", "细胞名称", "批次名称", "代次", "日期", "接种细胞数", "盘数", "收获细胞数", "本次PD", "累计PD", "状态", "建议下次传代", "备注"}), false); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "冻存管",
		[]string{"ID", "细胞名称", "冻存日期", "细胞数", "位置", "PD", "状态", "备注"},
		rowsFromMaps(vials, []string{"ID", "细胞名称", "冻存日期", "细胞数", "位置", "PD", "状态", "备注"}), false); err != nil {
		return nil, "", err
	}
	buffer, err := f.WriteToBuffer()
	if err != nil {
		return nil, "", err
	}
	return buffer, fmt.Sprintf("细胞组数据_%s.xlsx", rowString(group, "group_name")), nil
}

func fullExport(ctx context.Context, q Querier) (*bytes.Buffer, string, error) {
	lines, err := queryMaps(ctx, q,
		`SELECT id AS "ID", name AS "细胞名称", type AS "类型", revival_date AS "复苏日期",
		        default_passage_interval AS "默认传代间隔", notes AS "备注"
		 FROM cell_lines ORDER BY name`)
	if err != nil {
		return nil, "", err
	}
	batches, err := queryMaps(ctx, q, `
		SELECT cb.id AS "ID", cl.name AS "细胞名称", cb.batch_name AS "批次名称",
		       cb.revival_date AS "复苏日期", cb.source_freeze_date AS "冻存来源日期",
		       cb.initial_pd AS "初始PD", cb.initial_cell_count AS "初始细胞数",
		       CASE cb.is_active WHEN 1 THEN '是' ELSE '否' END AS "是否活跃",
		       cb.end_date AS "终止日期", cb.end_reason AS "终止原因", cb.notes AS "备注"
		FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
		ORDER BY cl.name, cb.revival_date, cb.id`)
	if err != nil {
		return nil, "", err
	}
	records, err := queryMaps(ctx, q, `
		SELECT cr.id AS "ID", cl.name AS "细胞名称", cb.batch_name AS "批次名称",
		       cr.passage AS "代次", cr.date AS "日期", cr.inoculum_cells AS "接种细胞数",
		       cr.inoculum_dishes AS "盘数", cr.harvested_cells AS "收获细胞数",
		       cr.pd AS "本次PD", cr.cumulative_pd AS "累计PD", cr.status AS "状态",
		       cr.next_passage_date AS "建议下次传代", cr.notes AS "备注"
		FROM culture_records cr
		JOIN culture_batches cb ON cb.id = cr.batch_id
		JOIN cell_lines cl ON cl.id = cb.cell_line_id
		ORDER BY cl.name, cb.batch_name, cr.date, cr.id`)
	if err != nil {
		return nil, "", err
	}
	vials, err := queryMaps(ctx, q, `
		SELECT fv.id AS "ID", cl.name AS "细胞名称", fv.freeze_date AS "冻存日期",
		       fv.cell_count AS "细胞数", fv.location AS "位置", fv.pd AS "PD",
		       fv.status AS "状态", fv.notes AS "备注"
		FROM frozen_vials fv JOIN cell_lines cl ON cl.id = fv.cell_line_id
		ORDER BY cl.name, fv.location`)
	if err != nil {
		return nil, "", err
	}
	groups, err := queryMaps(ctx, q,
		`SELECT id AS "ID", group_name AS "组名", notes AS "备注" FROM cell_groups ORDER BY group_name`)
	if err != nil {
		return nil, "", err
	}
	members, err := queryMaps(ctx, q, `
		SELECT gm.group_id AS "组ID", g.group_name AS "组名", cl.name AS "细胞名称", gm.sort_order AS "排序"
		FROM cell_group_members gm
		JOIN cell_groups g ON g.id = gm.group_id
		JOIN cell_lines cl ON cl.id = gm.cell_line_id
		ORDER BY g.group_name, gm.sort_order`)
	if err != nil {
		return nil, "", err
	}
	f := excelize.NewFile()
	defer f.Close()
	if err := writeSheet(f, "细胞株信息",
		[]string{"ID", "细胞名称", "类型", "复苏日期", "默认传代间隔", "备注"},
		rowsFromMaps(lines, []string{"ID", "细胞名称", "类型", "复苏日期", "默认传代间隔", "备注"}), true); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "培养批次",
		[]string{"ID", "细胞名称", "批次名称", "复苏日期", "冻存来源日期", "初始PD", "初始细胞数", "是否活跃", "终止日期", "终止原因", "备注"},
		rowsFromMaps(batches, []string{"ID", "细胞名称", "批次名称", "复苏日期", "冻存来源日期", "初始PD", "初始细胞数", "是否活跃", "终止日期", "终止原因", "备注"}), false); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "传代记录",
		[]string{"ID", "细胞名称", "批次名称", "代次", "日期", "接种细胞数", "盘数", "收获细胞数", "本次PD", "累计PD", "状态", "建议下次传代", "备注"},
		rowsFromMaps(records, []string{"ID", "细胞名称", "批次名称", "代次", "日期", "接种细胞数", "盘数", "收获细胞数", "本次PD", "累计PD", "状态", "建议下次传代", "备注"}), false); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "冻存管",
		[]string{"ID", "细胞名称", "冻存日期", "细胞数", "位置", "PD", "状态", "备注"},
		rowsFromMaps(vials, []string{"ID", "细胞名称", "冻存日期", "细胞数", "位置", "PD", "状态", "备注"}), false); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "细胞组",
		[]string{"ID", "组名", "备注"},
		rowsFromMaps(groups, []string{"ID", "组名", "备注"}), false); err != nil {
		return nil, "", err
	}
	if err := writeSheet(f, "组成员",
		[]string{"组ID", "组名", "细胞名称", "排序"},
		rowsFromMaps(members, []string{"组ID", "组名", "细胞名称", "排序"}), false); err != nil {
		return nil, "", err
	}
	buffer, err := f.WriteToBuffer()
	if err != nil {
		return nil, "", err
	}
	return buffer, fmt.Sprintf("CellTracker_全量数据_%s.xlsx", time.Now().Format("20060102")), nil
}

func batchRecordsCSV(ctx context.Context, q Querier, batchID int64) ([]byte, string, error) {
	batch, err := queryOne(ctx, q, `
		SELECT cb.batch_name, cl.name AS cell_line
		FROM culture_batches cb JOIN cell_lines cl ON cl.id = cb.cell_line_id
		WHERE cb.id = ?`, batchID)
	if err != nil {
		return nil, "", err
	}
	if batch == nil {
		return nil, "", notFoundError(fmt.Sprintf("培养批次不存在（id=%d）", batchID))
	}
	rows, err := queryMaps(ctx, q,
		`SELECT passage, date, inoculum_cells, inoculum_dishes, harvested_cells, pd,
		        cumulative_pd, status, next_passage_date, notes
		 FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC`, batchID)
	if err != nil {
		return nil, "", err
	}
	headers := []string{"passage", "date", "inoculum_cells", "inoculum_dishes", "harvested_cells",
		"pd", "cumulative_pd", "status", "next_passage_date", "notes"}
	var buffer bytes.Buffer
	buffer.WriteString("\ufeff")
	writer := csv.NewWriter(&buffer)
	if err := writer.Write(headers); err != nil {
		return nil, "", err
	}
	for _, row := range rows {
		values := make([]string, len(headers))
		for i, header := range headers {
			if row[header] == nil {
				values[i] = ""
			} else {
				values[i] = fmt.Sprint(row[header])
			}
		}
		if err := writer.Write(values); err != nil {
			return nil, "", err
		}
	}
	writer.Flush()
	if err := writer.Error(); err != nil {
		return nil, "", err
	}
	filename := fmt.Sprintf("%s_records_%s.csv", rowString(batch, "batch_name"), time.Now().Format("20060102"))
	return buffer.Bytes(), filename, nil
}
