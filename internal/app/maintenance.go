package app

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"time"
)

func createBackup(cfg *Config) (string, error) {
	if err := cfg.EnsureDirs(); err != nil {
		return "", err
	}
	path := filepath.Join(cfg.BackupDir, defaultBackupName("cell_data"))
	if err := backupDatabase(cfg.DBPath, path); err != nil {
		return "", err
	}
	pruneBackups(cfg.BackupDir, 30)
	return path, nil
}

func listBackups(cfg *Config) ([]Row, error) {
	if !dirExists(cfg.BackupDir) {
		return []Row{}, nil
	}
	entries, err := filepath.Glob(filepath.Join(cfg.BackupDir, "*.db"))
	if err != nil {
		return nil, err
	}
	sort.Slice(entries, func(i, j int) bool { return modTime(entries[i]) > modTime(entries[j]) })
	items := make([]Row, 0, len(entries))
	for _, path := range entries {
		info, err := os.Stat(path)
		if err != nil {
			continue
		}
		items = append(items, Row{
			"name":     filepath.Base(path),
			"size":     info.Size(),
			"modified": info.ModTime().Format("2006-01-02T15:04:05"),
			"path":     path,
		})
	}
	return items, nil
}

func readMigrationReport(cfg *Config) any {
	path := filepath.Join(filepath.Dir(cfg.DBPath), "migration-report.json")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var value any
	if err := json.Unmarshal(data, &value); err != nil {
		return nil
	}
	return value
}

func auditPD(ctx context.Context, q Querier) (map[string]any, error) {
	batches, err := queryMaps(ctx, q, `SELECT id, initial_pd, initial_cell_count FROM culture_batches ORDER BY id`)
	if err != nil {
		return nil, err
	}
	checked := 0
	mismatchCount := 0
	examples := []Row{}
	for _, batch := range batches {
		cumulative := rowFloat(batch, "initial_pd")
		prevInoculum := batch["initial_cell_count"]
		rows, err := queryMaps(ctx, q,
			`SELECT id, passage, date, harvested_cells, inoculum_cells, pd, cumulative_pd
			 FROM culture_records WHERE batch_id = ? ORDER BY date ASC, id ASC`, rowInt(batch, "id"))
		if err != nil {
			return nil, err
		}
		for _, row := range rows {
			checked++
			expectedPD := 0.0
			if value, ok := asFloat(prevInoculum); ok && value != 0 {
				expectedPD = calcPD(row["harvested_cells"], prevInoculum)
			}
			if expectedPD > 0 {
				cumulative += expectedPD
			}
			expectedCumulative := roundTo(cumulative, 2)
			storedPD := rowFloat(row, "pd")
			storedCumulative := rowFloat(row, "cumulative_pd")
			if abs(storedPD-expectedPD) > 0.005 || abs(storedCumulative-expectedCumulative) > 0.01 {
				mismatchCount++
				if len(examples) < 20 {
					examples = append(examples, Row{
						"batch_id":               rowInt(batch, "id"),
						"record_id":              rowInt(row, "id"),
						"passage":                row["passage"],
						"date":                   row["date"],
						"stored_pd":              storedPD,
						"expected_pd":            expectedPD,
						"stored_cumulative_pd":   storedCumulative,
						"expected_cumulative_pd": expectedCumulative,
					})
				}
			}
			prevInoculum = row["inoculum_cells"]
		}
	}
	return map[string]any{
		"records_checked": checked, "mismatch_count": mismatchCount, "examples": examples,
	}, nil
}

func auditActiveRecords(ctx context.Context, q Querier) ([]Row, error) {
	rows, err := queryMaps(ctx, q, `
		SELECT cb.id AS batch_id, cb.batch_name,
		  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id ORDER BY r.date DESC, r.id DESC LIMIT 1) AS latest_id,
		  (SELECT id FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1 LIMIT 1) AS active_id
		FROM culture_batches cb WHERE cb.is_active = 1`)
	if err != nil {
		return nil, err
	}
	problems := []Row{}
	for _, row := range rows {
		latest := rowInt(row, "latest_id")
		active := rowInt(row, "active_id")
		if latest != 0 && latest != active {
			problems = append(problems, Row{
				"batch_id": rowInt(row, "batch_id"), "batch_name": rowString(row, "batch_name"),
				"latest_record_id": latest, "active_record_id": active,
			})
		}
	}
	return problems, nil
}

func databaseAudit(ctx context.Context, cfg *Config, q Querier) (map[string]any, error) {
	counts := tableCounts(ctx, q)
	issues := consistencyIssues(ctx, q)
	pdAudit, err := auditPD(ctx, q)
	if err != nil {
		return nil, err
	}
	activeProblems, err := auditActiveRecords(ctx, q)
	if err != nil {
		return nil, err
	}
	meta := map[string]any{}
	for _, key := range []string{"schema_version", "migrated_from", "migrated_at", "created_at"} {
		if value, ok := getMeta(q, key); ok {
			meta[key] = value
		}
	}
	return map[string]any{
		"database":               cfg.DBPath,
		"size_bytes":             fileSize(cfg.DBPath),
		"counts":                 counts,
		"issues":                 issues,
		"pd_audit":               pdAudit,
		"active_record_problems": activeProblems,
		"meta":                   meta,
	}, nil
}

func restoreDatabase(ctx context.Context, cfg *Config, store *Store, uploadedPath string) (map[string]any, error) {
	info := validateDatabaseFile(uploadedPath)
	if ok, _ := info["ok"].(bool); !ok {
		return nil, validationError(fmt.Sprintf("备份文件无效：%v", info["reason"]))
	}
	previous := ""
	if fileExists(cfg.DBPath) {
		previous = filepath.Join(cfg.BackupDir, defaultBackupName("before-restore"))
		if err := backupDatabase(cfg.DBPath, previous); err != nil {
			return nil, err
		}
	}
	if err := store.Swap(uploadedPath); err != nil {
		return nil, err
	}
	return map[string]any{
		"restored_from":   uploadedPath,
		"previous_backup": previous,
		"source_counts":   info["counts"],
	}, nil
}

func importLegacyDatabase(ctx context.Context, cfg *Config, store *Store, uploadedPath string) (map[string]any, error) {
	info := validateDatabaseFile(uploadedPath)
	if ok, _ := info["ok"].(bool); !ok {
		return nil, validationError(fmt.Sprintf("旧版数据库无效：%v", info["reason"]))
	}
	sourceDB, err := openDB(uploadedPath, true)
	if err != nil {
		return nil, err
	}
	sourceCounts := tableCounts(ctx, sourceDB)
	sourceChecksums := map[string]string{}
	for _, table := range coreTables {
		checksum, err := tableChecksum(ctx, sourceDB, table)
		if err != nil {
			sourceDB.Close()
			return nil, err
		}
		sourceChecksums[table] = checksum
	}
	sourceDB.Close()

	previous := ""
	if fileExists(cfg.DBPath) {
		previous = filepath.Join(cfg.BackupDir, defaultBackupName("before-import"))
		if err := backupDatabase(cfg.DBPath, previous); err != nil {
			return nil, err
		}
	}
	if err := store.Swap(uploadedPath); err != nil {
		return nil, err
	}
	targetCounts := tableCounts(ctx, store.DB())
	targetChecksums := map[string]string{}
	for _, table := range coreTables {
		checksum, err := tableChecksum(ctx, store.DB(), table)
		if err != nil {
			return nil, err
		}
		targetChecksums[table] = checksum
	}
	countsEqual := equalIntMaps(sourceCounts, targetCounts)
	checksumsEqual := equalStringMaps(sourceChecksums, targetChecksums)
	if !countsEqual || !checksumsEqual {
		if previous != "" {
			_ = store.Swap(previous)
		}
		return nil, validationError("导入后校验失败，已回滚到导入前的数据库，请检查源文件")
	}
	pdAudit, err := auditPD(ctx, store.DB())
	if err != nil {
		return nil, err
	}
	activeProblems, err := auditActiveRecords(ctx, store.DB())
	if err != nil {
		return nil, err
	}
	status := "ok"
	if count, _ := pdAudit["mismatch_count"].(int); count != 0 || len(activeProblems) > 0 {
		status = "ok_with_warnings"
	}
	report := map[string]any{
		"generated_at":           time.Now().Format("2006-01-02T15:04:05"),
		"source":                 uploadedPath,
		"target":                 cfg.DBPath,
		"source_counts":          sourceCounts,
		"target_counts":          targetCounts,
		"counts_equal":           countsEqual,
		"checksums_equal":        checksumsEqual,
		"pd_audit":               pdAudit,
		"active_record_problems": activeProblems,
		"previous_backup":        previous,
		"status":                 status,
	}
	reportPath := filepath.Join(filepath.Dir(cfg.DBPath), "migration-report.json")
	if data, err := json.MarshalIndent(report, "", "  "); err == nil {
		_ = os.WriteFile(reportPath, data, 0o644)
	}
	report["report_path"] = reportPath
	return report, nil
}

func saveUpload(cfg *Config, reader io.Reader, filename string) (string, error) {
	dir := filepath.Join(filepath.Dir(cfg.DBPath), "uploads")
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", err
	}
	safeName := filepath.Base(filename)
	if safeName == "" || safeName == "." {
		safeName = "upload.db"
	}
	target := filepath.Join(dir, fmt.Sprintf("%s-%s", time.Now().Format("20060102-150405"), safeName))
	out, err := os.Create(target)
	if err != nil {
		return "", err
	}
	if _, err := io.Copy(out, reader); err != nil {
		out.Close()
		return "", err
	}
	if err := out.Close(); err != nil {
		return "", err
	}
	return target, nil
}

func cleanupUpload(path string) {
	if strings.TrimSpace(path) != "" {
		_ = os.Remove(path)
	}
}

func copyForDownload(cfg *Config) (string, error) {
	if err := cfg.EnsureDirs(); err != nil {
		return "", err
	}
	path := filepath.Join(cfg.BackupDir, defaultBackupName("cell_data-download"))
	if err := backupDatabase(cfg.DBPath, path); err != nil {
		return "", err
	}
	pruneBackups(cfg.BackupDir, 30)
	return path, nil
}

func abs(value float64) float64 {
	if value < 0 {
		return -value
	}
	return value
}

func equalIntMaps(a, b map[string]int) bool {
	if len(a) != len(b) {
		return false
	}
	for key, value := range a {
		if b[key] != value {
			return false
		}
	}
	return true
}

func equalStringMaps(a, b map[string]string) bool {
	if len(a) != len(b) {
		return false
	}
	for key, value := range a {
		if b[key] != value {
			return false
		}
	}
	return true
}
