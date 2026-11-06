package app

import (
	"context"
	"database/sql"
	"fmt"
	"math"
	"regexp"
	"strconv"
	"strings"
	"time"
)

var (
	statusChoices  = []string{"良好", "一般", "较差", "污染"}
	lineTypes      = []string{"永生化", "原代"}
	vialStatuses   = []string{"在库", "已复苏", "已丢弃"}
	endReasons     = []string{"污染", "全部冻存", "丢弃", "实验结束", "其他"}
	sciNumberRE    = regexp.MustCompile(`(?i)(\d+(?:\.\d+)?)\s*[xX×*]\s*10\s*\^?\s*(\d+)`)
	datePartsRE    = regexp.MustCompile(`^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})`)
	pdTokenRE      = regexp.MustCompile(`(?i)[pP][dD]\s*[=：:]\s*(\d+(?:\.\d+)?)`)
	splitCellRE    = regexp.MustCompile(`\s{2,}|\t|,|;`)
	excelSerialMin = 20000.0
)

func todayISO() string {
	return time.Now().Format("2006-01-02")
}

func roundTo(value float64, digits int) float64 {
	pow := math.Pow(10, float64(digits))
	// Python's round() uses banker's rounding; matching it keeps the Go API
	// numerically identical to the legacy Python implementation.
	return math.RoundToEven(value*pow) / pow
}

func asFloat(value any) (float64, bool) {
	switch v := value.(type) {
	case nil:
		return 0, false
	case float64:
		if math.IsNaN(v) {
			return 0, false
		}
		return v, true
	case float32:
		return float64(v), true
	case int:
		return float64(v), true
	case int64:
		return float64(v), true
	case int32:
		return float64(v), true
	case bool:
		return 0, false
	case string:
		parsed, ok := parseNumber(v)
		return parsed, ok
	default:
		parsed, ok := parseNumber(fmt.Sprint(v))
		return parsed, ok
	}
}

func asInt(value any) (int64, bool) {
	f, ok := asFloat(value)
	if !ok {
		return 0, false
	}
	return int64(math.Round(f)), true
}

func asString(value any) string {
	if value == nil {
		return ""
	}
	if text, ok := value.(string); ok {
		return text
	}
	return fmt.Sprint(value)
}

func asBool(value any) bool {
	switch v := value.(type) {
	case bool:
		return v
	case int64:
		return v != 0
	case int:
		return v != 0
	case float64:
		return v != 0
	case string:
		switch strings.ToLower(strings.TrimSpace(v)) {
		case "1", "true", "yes", "on":
			return true
		}
	}
	return false
}

func rowString(row Row, key string) string {
	return asString(row[key])
}

func rowInt(row Row, key string) int64 {
	value, _ := asInt(row[key])
	return value
}

func rowFloat(row Row, key string) float64 {
	value, _ := asFloat(row[key])
	return value
}

func rowBool(row Row, key string) bool {
	return asBool(row[key])
}

func calcPD(harvested, inoculum any) float64 {
	h, okH := asFloat(harvested)
	i, okI := asFloat(inoculum)
	if !okH || !okI || h <= 0 || i <= 0 {
		return 0
	}
	return roundTo(math.Log2(h/i), 2)
}

func parseNumber(value any) (float64, bool) {
	if value == nil {
		return 0, false
	}
	switch v := value.(type) {
	case bool:
		return 0, false
	case float64:
		if math.IsNaN(v) {
			return 0, false
		}
		return v, true
	case float32:
		return float64(v), true
	case int:
		return float64(v), true
	case int64:
		return float64(v), true
	case int32:
		return float64(v), true
	case string:
		text := strings.TrimSpace(strings.ReplaceAll(v, ",", ""))
		text = strings.ReplaceAll(text, " ", "")
		if text == "" {
			return 0, false
		}
		if match := sciNumberRE.FindStringSubmatch(text); match != nil {
			base, err1 := strconv.ParseFloat(match[1], 64)
			exp, err2 := strconv.Atoi(match[2])
			if err1 == nil && err2 == nil {
				return base * math.Pow(10, float64(exp)), true
			}
		}
		parsed, err := strconv.ParseFloat(text, 64)
		if err != nil || math.IsNaN(parsed) {
			return 0, false
		}
		return parsed, true
	default:
		return parseNumber(fmt.Sprint(value))
	}
}

func parseDateValue(value any) *string {
	if value == nil {
		return nil
	}
	switch v := value.(type) {
	case time.Time:
		text := v.Format("2006-01-02")
		return &text
	case float64:
		if v >= excelSerialMin && v < 100000 {
			base := time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)
			text := base.AddDate(0, 0, int(v)).Format("2006-01-02")
			return &text
		}
		return nil
	case int64:
		return parseDateValue(float64(v))
	case string:
		return parseDateString(v)
	default:
		return parseDateString(fmt.Sprint(value))
	}
}

func parseDateString(raw string) *string {
	text := strings.TrimSpace(raw)
	if text == "" {
		return nil
	}
	text = strings.ReplaceAll(text, "年", "-")
	text = strings.ReplaceAll(text, "月", "-")
	text = strings.ReplaceAll(text, "日", "")
	text = strings.TrimSpace(text)
	if index := strings.IndexAny(text, " T"); index > 0 {
		// Keep the date portion of timestamps such as 2026-02-01 00:00:00.
		if len(text) > 10 {
			text = strings.TrimSpace(text[:index])
		}
	}
	layouts := []string{
		"2006-01-02", "2006/01/02", "2006.01.02", "20060102",
		"2006-1-2", "2006/1/2", "2006.1.2",
		"2006-01", "2006/01", "2006.01",
		"1/2/06", "1/2/2006", "01/02/2006",
		"1-2-06", "1-2-2006", "01-02-06", "01-02-2006",
		time.RFC3339,
	}
	for _, layout := range layouts {
		if parsed, err := time.Parse(layout, text); err == nil {
			result := parsed.Format("2006-01-02")
			return &result
		}
	}
	if match := datePartsRE.FindStringSubmatch(text); match != nil {
		year, _ := strconv.Atoi(match[1])
		month, _ := strconv.Atoi(match[2])
		day, _ := strconv.Atoi(match[3])
		parsed := time.Date(year, time.Month(month), day, 0, 0, 0, 0, time.UTC)
		if parsed.Year() == year && int(parsed.Month()) == month && parsed.Day() == day {
			result := parsed.Format("2006-01-02")
			return &result
		}
		return nil
	}
	if len(text) == 4 {
		if year, err := strconv.Atoi(text); err == nil && year >= 1900 && year <= 2099 {
			result := fmt.Sprintf("%04d-01-01", year)
			return &result
		}
	}
	// Excel dates can arrive as serial numbers when the cell has a date style.
	if serial, err := strconv.ParseFloat(text, 64); err == nil && serial >= excelSerialMin && serial < 100000 {
		base := time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)
		result := base.AddDate(0, 0, int(serial)).Format("2006-01-02")
		return &result
	}
	return nil
}

func normalizeDate(value any, field string, required bool) (*string, error) {
	if value == nil || asString(value) == "" {
		if required {
			return nil, validationError(field + "不能为空")
		}
		return nil, nil
	}
	parsed := parseDateValue(value)
	if parsed == nil {
		return nil, validationError(fmt.Sprintf("%s格式无法识别：%v，请使用 YYYY-MM-DD", field, value))
	}
	return parsed, nil
}

func normalizeNumber(value any, field string, required bool, minimum *float64) (*float64, error) {
	if value == nil || asString(value) == "" {
		if required {
			return nil, validationError(field + "不能为空")
		}
		return nil, nil
	}
	parsed, ok := parseNumber(value)
	if !ok {
		return nil, validationError(fmt.Sprintf("%s必须是数字，收到：%v", field, value))
	}
	if minimum != nil && parsed < *minimum {
		return nil, validationError(fmt.Sprintf("%s不能小于 %v", field, *minimum))
	}
	return &parsed, nil
}

func normalizeInt(value any, field string, required bool, minimum *int64) (*int64, error) {
	if value == nil || asString(value) == "" {
		if required {
			return nil, validationError(field + "不能为空")
		}
		return nil, nil
	}
	parsed, ok := parseNumber(value)
	if !ok {
		return nil, validationError(fmt.Sprintf("%s必须是数字，收到：%v", field, value))
	}
	if math.Abs(parsed-math.Round(parsed)) > 1e-9 {
		return nil, validationError(fmt.Sprintf("%s必须是整数，收到：%v", field, value))
	}
	result := int64(math.Round(parsed))
	if minimum != nil && result < *minimum {
		return nil, validationError(fmt.Sprintf("%s不能小于 %v", field, *minimum))
	}
	return &result, nil
}

func normalizeText(value any, maxLength int) (string, error) {
	if value == nil {
		return "", nil
	}
	text := strings.TrimSpace(asString(value))
	if maxLength > 0 && len([]rune(text)) > maxLength {
		return "", validationError(fmt.Sprintf("文本过长（最多 %d 字符）", maxLength))
	}
	return text, nil
}

func normalizeChoice(value any, choices []string, field string, defaultValue string, allowEmpty bool) (*string, error) {
	text := strings.TrimSpace(asString(value))
	if text == "" {
		if defaultValue != "" {
			return &defaultValue, nil
		}
		if allowEmpty {
			return nil, nil
		}
		return nil, validationError(field + "不能为空")
	}
	for _, choice := range choices {
		if text == choice {
			return &text, nil
		}
	}
	return nil, validationError(fmt.Sprintf("%s必须是 %s 之一", field, strings.Join(choices, "/")))
}

func remainingDays(next any, today time.Time) *int64 {
	if next == nil || asString(next) == "" {
		return nil
	}
	parsed := parseDateValue(next)
	if parsed == nil {
		return nil
	}
	target, err := time.Parse("2006-01-02", *parsed)
	if err != nil {
		return nil
	}
	base := time.Date(today.Year(), today.Month(), today.Day(), 0, 0, 0, 0, time.UTC)
	days := int64(target.Sub(base).Hours() / 24)
	return &days
}

func recalculateBatch(ctx context.Context, q Querier, batchID int64) (Row, error) {
	batch, err := queryOne(ctx, q,
		`SELECT id, initial_pd, initial_cell_count FROM culture_batches WHERE id = ?`, batchID)
	if err != nil {
		return nil, err
	}
	if batch == nil {
		return nil, nil
	}
	initialPD := rowFloat(batch, "initial_pd")
	prevInoculum := batch["initial_cell_count"]
	records, err := queryMaps(ctx, q,
		`SELECT id, harvested_cells, inoculum_cells FROM culture_records
		 WHERE batch_id = ? ORDER BY date ASC, id ASC`, batchID)
	if err != nil {
		return nil, err
	}
	cumulative := initialPD
	lastPD := 0.0
	for _, record := range records {
		pd := 0.0
		if value, ok := asFloat(prevInoculum); ok && value != 0 {
			pd = calcPD(record["harvested_cells"], prevInoculum)
		}
		if pd > 0 {
			cumulative += pd
		}
		_, err = q.ExecContext(ctx,
			`UPDATE culture_records SET pd = ?, cumulative_pd = ? WHERE id = ?`,
			pd, roundTo(cumulative, 2), rowInt(record, "id"))
		if err != nil {
			return nil, err
		}
		prevInoculum = record["inoculum_cells"]
		lastPD = pd
	}
	return Row{
		"batch_id":      batchID,
		"records":       len(records),
		"cumulative_pd": roundTo(cumulative, 2),
		"last_pd":       lastPD,
	}, nil
}

func refreshActiveRecord(ctx context.Context, q Querier, batchID int64) (*int64, error) {
	batch, err := queryOne(ctx, q, `SELECT is_active FROM culture_batches WHERE id = ?`, batchID)
	if err != nil {
		return nil, err
	}
	if batch == nil || !rowBool(batch, "is_active") {
		return nil, nil
	}
	latest, err := queryOne(ctx, q,
		`SELECT id FROM culture_records WHERE batch_id = ? ORDER BY date DESC, id DESC LIMIT 1`, batchID)
	if err != nil {
		return nil, err
	}
	if latest == nil {
		_, err = q.ExecContext(ctx, `UPDATE culture_records SET is_active = 0 WHERE batch_id = ?`, batchID)
		return nil, err
	}
	id := rowInt(latest, "id")
	_, err = q.ExecContext(ctx,
		`UPDATE culture_records SET is_active = CASE WHEN id = ? THEN 1 ELSE 0 END WHERE batch_id = ?`,
		id, batchID)
	if err != nil {
		return nil, err
	}
	return &id, nil
}

type ParsedCell struct {
	CellName    string
	CellCount   *float64
	PD          *float64
	FreezeDate  *string
	RevivedDate *string
	Status      string
	Notes       string
}

func parseCellText(value any) *ParsedCell {
	raw := strings.TrimSpace(asString(value))
	if raw == "" {
		return nil
	}
	lines := []string{}
	for _, line := range strings.Split(raw, "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			lines = append(lines, line)
		}
	}
	if len(lines) == 0 {
		return nil
	}
	if len(lines) == 1 && strings.Contains(lines[0], " ") {
		parts := splitCellRE.Split(lines[0], -1)
		if len(parts) > 1 {
			lines = parts
		} else {
			lines = strings.Fields(lines[0])
		}
	}
	if len(lines) == 0 || strings.TrimSpace(lines[0]) == "" {
		return nil
	}
	parsed := &ParsedCell{CellName: strings.TrimSpace(lines[0])}
	numbers := []float64{}
	dates := []string{}
	others := []string{}
	for _, token := range lines[1:] {
		token = strings.TrimSpace(token)
		if token == "" {
			continue
		}
		if match := pdTokenRE.FindStringSubmatch(token); match != nil {
			if value, err := strconv.ParseFloat(match[1], 64); err == nil {
				numbers = append(numbers, value)
				continue
			}
		}
		if date := parseDateValue(token); date != nil {
			dates = append(dates, *date)
			continue
		}
		if number, ok := parseNumber(token); ok {
			numbers = append(numbers, number)
		} else {
			others = append(others, token)
		}
	}
	if len(numbers) > 0 {
		parsed.CellCount = &numbers[0]
	}
	if len(numbers) > 1 {
		parsed.PD = &numbers[1]
	}
	if len(dates) > 0 {
		parsed.FreezeDate = &dates[0]
	}
	if len(dates) > 1 {
		parsed.RevivedDate = &dates[1]
	}
	parsed.Status = "在库"
	if parsed.RevivedDate != nil {
		parsed.Status = "已复苏"
	}
	parsed.Notes = strings.Join(others, " ")
	return parsed
}

// ---- small SQL helpers ----

func getOr404(ctx context.Context, q Querier, table string, id int64, label string) (Row, error) {
	row, err := queryOne(ctx, q, fmt.Sprintf(`SELECT * FROM "%s" WHERE id = ?`, table), id)
	if err != nil {
		return nil, err
	}
	if row == nil {
		return nil, notFoundError(fmt.Sprintf("%s不存在（id=%d）", label, id))
	}
	return row, nil
}

func placeholders(count int) string {
	if count <= 0 {
		return ""
	}
	return strings.TrimRight(strings.Repeat("?,", count), ",")
}

func audit(ctx context.Context, q Querier, username any, action, entity string, entityID any, detail any) error {
	var detailJSON any
	if detail != nil {
		encoded, err := jsonMarshalNoEscape(detail)
		if err != nil {
			return err
		}
		detailJSON = encoded
	}
	_, err := q.ExecContext(ctx,
		`INSERT INTO audit_log(ts, username, action, entity, entity_id, detail) VALUES(?,?,?,?,?,?)`,
		time.Now().Format("2006-01-02T15:04:05"), username, action, entity, entityID, detailJSON)
	return err
}

func jsonMarshalNoEscape(value any) (string, error) {
	var builder strings.Builder
	encoder := newJSONEncoder(&builder)
	if err := encoder.Encode(value); err != nil {
		return "", err
	}
	return strings.TrimSuffix(builder.String(), "\n"), nil
}

func nullableText(value string) any {
	if strings.TrimSpace(value) == "" {
		return nil
	}
	return value
}

func savepoint(ctx context.Context, tx *sql.Tx, name string, fn func() error) error {
	if _, err := tx.ExecContext(ctx, "SAVEPOINT "+name); err != nil {
		return err
	}
	if err := fn(); err != nil {
		_, _ = tx.ExecContext(ctx, "ROLLBACK TO "+name)
		_, _ = tx.ExecContext(ctx, "RELEASE "+name)
		return err
	}
	_, err := tx.ExecContext(ctx, "RELEASE "+name)
	return err
}
