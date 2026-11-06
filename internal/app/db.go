package app

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"sort"
	"strings"
	"sync"
	"time"

	_ "modernc.org/sqlite"
)

var coreTables = []string{
	"cell_lines",
	"culture_batches",
	"culture_records",
	"frozen_vials",
	"cell_groups",
	"cell_group_members",
}

var schemaStatements = []string{
	`CREATE TABLE IF NOT EXISTS cell_lines (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		name TEXT NOT NULL UNIQUE,
		revival_date TEXT,
		type TEXT,
		default_passage_interval INTEGER DEFAULT 0,
		notes TEXT
	)`,
	`CREATE TABLE IF NOT EXISTS culture_batches (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		cell_line_id INTEGER,
		batch_name TEXT NOT NULL,
		revival_date TEXT,
		source_freeze_date TEXT,
		initial_pd REAL DEFAULT 0,
		initial_cell_count REAL,
		is_active INTEGER DEFAULT 1,
		end_date TEXT,
		end_reason TEXT,
		notes TEXT,
		FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id)
	)`,
	`CREATE TABLE IF NOT EXISTS culture_records (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		batch_id INTEGER,
		passage INTEGER,
		date TEXT,
		inoculum_cells REAL,
		inoculum_dishes INTEGER,
		harvested_cells REAL,
		pd REAL,
		cumulative_pd REAL,
		status TEXT,
		next_passage_date TEXT,
		is_active INTEGER DEFAULT 1,
		notes TEXT,
		FOREIGN KEY(batch_id) REFERENCES culture_batches(id)
	)`,
	`CREATE TABLE IF NOT EXISTS frozen_vials (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		cell_line_id INTEGER,
		batch_id INTEGER,
		freeze_date TEXT,
		cell_count REAL,
		location TEXT DEFAULT '',
		pd REAL,
		status TEXT DEFAULT '在库',
		notes TEXT,
		FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id),
		FOREIGN KEY(batch_id) REFERENCES culture_batches(id)
	)`,
	`CREATE TABLE IF NOT EXISTS cell_groups (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		group_name TEXT NOT NULL UNIQUE,
		notes TEXT
	)`,
	`CREATE TABLE IF NOT EXISTS cell_group_members (
		group_id INTEGER,
		cell_line_id INTEGER,
		sort_order INTEGER DEFAULT 0,
		FOREIGN KEY(group_id) REFERENCES cell_groups(id),
		FOREIGN KEY(cell_line_id) REFERENCES cell_lines(id),
		PRIMARY KEY(group_id, cell_line_id)
	)`,
	`CREATE TABLE IF NOT EXISTS _schema_meta (
		key TEXT PRIMARY KEY,
		value TEXT
	)`,
	`CREATE TABLE IF NOT EXISTS users (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		username TEXT NOT NULL UNIQUE,
		password_hash TEXT NOT NULL,
		display_name TEXT,
		is_active INTEGER DEFAULT 1,
		created_at TEXT
	)`,
	`CREATE TABLE IF NOT EXISTS audit_log (
		id INTEGER PRIMARY KEY AUTOINCREMENT,
		ts TEXT NOT NULL,
		username TEXT,
		action TEXT NOT NULL,
		entity TEXT,
		entity_id INTEGER,
		detail TEXT
	)`,
}

var indexStatements = []string{
	`CREATE INDEX IF NOT EXISTS idx_records_batch_date ON culture_records(batch_id, date)`,
	`CREATE INDEX IF NOT EXISTS idx_records_batch_active ON culture_records(batch_id, is_active)`,
	`CREATE INDEX IF NOT EXISTS idx_batches_line ON culture_batches(cell_line_id, is_active)`,
	`CREATE INDEX IF NOT EXISTS idx_vials_line ON frozen_vials(cell_line_id)`,
	`CREATE INDEX IF NOT EXISTS idx_vials_location ON frozen_vials(location)`,
	`CREATE INDEX IF NOT EXISTS idx_group_members_group ON cell_group_members(group_id, sort_order)`,
}

// Store wraps the SQLite pool. Writes are serialized because SQLite only allows
// one writer and this keeps "database is locked" errors out of the UI.
type Store struct {
	db      *sql.DB
	path    string
	writeMu sync.Mutex
	dbMu    sync.RWMutex
}

type Row = map[string]any

type Querier interface {
	ExecContext(ctx context.Context, query string, args ...any) (sql.Result, error)
	QueryContext(ctx context.Context, query string, args ...any) (*sql.Rows, error)
	QueryRowContext(ctx context.Context, query string, args ...any) *sql.Row
}

func sqliteDSN(path string, readonly bool) string {
	slash := filepath.ToSlash(path)
	mode := "rwc"
	if readonly {
		mode = "ro"
	}
	dsn := "file:" + slash + "?mode=" + mode + "&_pragma=busy_timeout(15000)&_pragma=foreign_keys(1)"
	if !readonly {
		dsn += "&_pragma=journal_mode(WAL)&_pragma=synchronous(NORMAL)"
	}
	return dsn
}

func openDB(path string, readonly bool) (*sql.DB, error) {
	db, err := sql.Open("sqlite", sqliteDSN(path, readonly))
	if err != nil {
		return nil, err
	}
	if readonly {
		db.SetMaxOpenConns(1)
	} else {
		db.SetMaxOpenConns(4)
	}
	db.SetMaxIdleConns(2)
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := db.PingContext(ctx); err != nil {
		db.Close()
		return nil, err
	}
	return db, nil
}

func EnsureDatabase(cfg *Config) (map[string]any, error) {
	if err := cfg.EnsureDirs(); err != nil {
		return nil, err
	}
	created := false
	migrated := false
	source := ""
	if !fileExists(cfg.DBPath) || fileSize(cfg.DBPath) == 0 {
		for _, candidate := range []string{
			filepath.Join(cfg.BaseDir, "cell_data.db"),
			filepath.Join(cfg.BaseDir, "cell_data.sqlite"),
			filepath.Join(cfg.BaseDir, "data", "legacy.db"),
		} {
			if fileExists(candidate) && fileSize(candidate) > 0 && !samePath(candidate, cfg.DBPath) {
				if err := backupDatabase(candidate, cfg.DBPath); err != nil {
					return nil, fmt.Errorf("从旧版数据库复制失败：%w", err)
				}
				migrated = true
				source = candidate
				created = true
				break
			}
		}
	}
	if !fileExists(cfg.DBPath) {
		created = true
	}
	db, err := openDB(cfg.DBPath, false)
	if err != nil {
		return nil, err
	}
	defer db.Close()
	if err := initSchema(db); err != nil {
		return nil, err
	}
	if created && !migrated {
		_ = setMeta(db, "created_at", time.Now().Format("2006-01-02T15:04:05"))
	}
	if migrated {
		_ = setMeta(db, "migrated_from", source)
		_ = setMeta(db, "migrated_at", time.Now().Format("2006-01-02T15:04:05"))
	}
	return map[string]any{
		"created":  created,
		"migrated": migrated,
		"source":   source,
		"db_path":  cfg.DBPath,
	}, nil
}

func OpenStore(path string) (*Store, error) {
	db, err := openDB(path, false)
	if err != nil {
		return nil, err
	}
	s := &Store{db: db, path: path}
	if err := initSchema(db); err != nil {
		db.Close()
		return nil, err
	}
	return s, nil
}

func (s *Store) DB() *sql.DB {
	s.dbMu.RLock()
	defer s.dbMu.RUnlock()
	return s.db
}

func (s *Store) Path() string { return s.path }

func (s *Store) Close() error {
	s.dbMu.Lock()
	defer s.dbMu.Unlock()
	if s.db != nil {
		return s.db.Close()
	}
	return nil
}

func (s *Store) Write(ctx context.Context, fn func(*sql.Tx) error) error {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	s.dbMu.RLock()
	db := s.db
	s.dbMu.RUnlock()
	tx, err := db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	if err := fn(tx); err != nil {
		_ = tx.Rollback()
		return err
	}
	return tx.Commit()
}

// Swap replaces the database file and reopens the pool. The caller is
// responsible for taking a backup first.
func (s *Store) Swap(newFile string) error {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	s.dbMu.Lock()
	defer s.dbMu.Unlock()

	if s.db != nil {
		_ = s.db.Close()
	}
	staging := s.path + ".incoming"
	_ = os.Remove(staging)
	if err := copyFile(newFile, staging); err != nil {
		return err
	}
	stagingDB, err := openDB(staging, false)
	if err != nil {
		_ = os.Remove(staging)
		return err
	}
	if err := initSchema(stagingDB); err != nil {
		stagingDB.Close()
		_ = os.Remove(staging)
		return err
	}
	_ = stagingDB.Close()
	_ = os.Remove(s.path + "-wal")
	_ = os.Remove(s.path + "-shm")
	if err := os.Rename(staging, s.path); err != nil {
		// Windows can refuse to replace a file that another handle still owns.
		_ = os.Remove(s.path)
		if err := os.Rename(staging, s.path); err != nil {
			return err
		}
	}
	db, err := openDB(s.path, false)
	if err != nil {
		return err
	}
	s.db = db
	return nil
}

func initSchema(db *sql.DB) error {
	ctx := context.Background()
	for _, statement := range schemaStatements {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("建表失败：%w", err)
		}
	}
	rows, err := db.QueryContext(ctx, `PRAGMA table_info(cell_group_members)`)
	if err != nil {
		return err
	}
	hasSort := false
	for rows.Next() {
		var cid int
		var name, typ string
		var notnull, pk int
		var dflt any
		if err := rows.Scan(&cid, &name, &typ, &notnull, &dflt, &pk); err != nil {
			rows.Close()
			return err
		}
		if name == "sort_order" {
			hasSort = true
		}
	}
	rows.Close()
	if !hasSort {
		if _, err := db.ExecContext(ctx, `ALTER TABLE cell_group_members ADD COLUMN sort_order INTEGER DEFAULT 0`); err != nil {
			return err
		}
	}
	for _, statement := range indexStatements {
		if _, err := db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("建索引失败：%w", err)
		}
	}
	_, err = db.ExecContext(ctx,
		`INSERT INTO _schema_meta(key, value) VALUES('schema_version', ?)
		 ON CONFLICT(key) DO UPDATE SET value = excluded.value`, fmt.Sprint(SchemaVersion))
	return err
}

func setMeta(q Querier, key, value string) error {
	_, err := q.ExecContext(context.Background(),
		`INSERT INTO _schema_meta(key, value) VALUES(?, ?)
		 ON CONFLICT(key) DO UPDATE SET value = excluded.value`, key, value)
	return err
}

func getMeta(q Querier, key string) (string, bool) {
	var value string
	err := q.QueryRowContext(context.Background(), `SELECT value FROM _schema_meta WHERE key = ?`, key).Scan(&value)
	if err != nil {
		return "", false
	}
	return value, true
}

func queryMaps(ctx context.Context, q Querier, query string, args ...any) ([]Row, error) {
	rows, err := q.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	columns, err := rows.Columns()
	if err != nil {
		return nil, err
	}
	result := make([]Row, 0, 16)
	for rows.Next() {
		values := make([]any, len(columns))
		pointers := make([]any, len(columns))
		for i := range values {
			pointers[i] = &values[i]
		}
		if err := rows.Scan(pointers...); err != nil {
			return nil, err
		}
		row := make(Row, len(columns))
		for i, column := range columns {
			row[column] = normalizeSQLValue(values[i])
		}
		result = append(result, row)
	}
	return result, rows.Err()
}

func queryOne(ctx context.Context, q Querier, query string, args ...any) (Row, error) {
	rows, err := queryMaps(ctx, q, query, args...)
	if err != nil {
		return nil, err
	}
	if len(rows) == 0 {
		return nil, nil
	}
	return rows[0], nil
}

func normalizeSQLValue(value any) any {
	switch v := value.(type) {
	case nil:
		return nil
	case []byte:
		return string(v)
	case time.Time:
		if v.Hour() == 0 && v.Minute() == 0 && v.Second() == 0 {
			return v.Format("2006-01-02")
		}
		return v.Format("2006-01-02 15:04:05")
	default:
		return v
	}
}

func tableCounts(ctx context.Context, q Querier) map[string]int {
	counts := make(map[string]int, len(coreTables))
	for _, table := range coreTables {
		var count int
		err := q.QueryRowContext(ctx, fmt.Sprintf(`SELECT COUNT(*) FROM "%s"`, table)).Scan(&count)
		if err != nil {
			count = 0
		}
		counts[table] = count
	}
	return counts
}

func tableChecksum(ctx context.Context, q Querier, table string) (string, error) {
	rows, err := queryMaps(ctx, q, fmt.Sprintf(`SELECT * FROM "%s" ORDER BY rowid`, table))
	if err != nil {
		return "", err
	}
	digest := sha256.New()
	encoder := json.NewEncoder(digest)
	encoder.SetEscapeHTML(false)
	for _, row := range rows {
		keys := make([]string, 0, len(row))
		for key := range row {
			keys = append(keys, key)
		}
		sort.Strings(keys)
		values := make([]any, 0, len(keys))
		for _, key := range keys {
			values = append(values, row[key])
		}
		if err := encoder.Encode(values); err != nil {
			return "", err
		}
	}
	return hex.EncodeToString(digest.Sum(nil)), nil
}

func dataFingerprint(ctx context.Context, q Querier) map[string]any {
	counts := tableCounts(ctx, q)
	checksums := map[string]string{}
	for _, table := range coreTables {
		if counts[table] == 0 {
			continue
		}
		if checksum, err := tableChecksum(ctx, q, table); err == nil {
			checksums[table] = checksum
		}
	}
	return map[string]any{"counts": counts, "checksums": checksums}
}

func consistencyIssues(ctx context.Context, q Querier) []string {
	queries := []struct {
		label string
		sql   string
	}{
		{"存在没有对应细胞株的批次", "SELECT COUNT(*) FROM culture_batches WHERE cell_line_id NOT IN (SELECT id FROM cell_lines)"},
		{"存在没有对应批次的传代记录", "SELECT COUNT(*) FROM culture_records WHERE batch_id NOT IN (SELECT id FROM culture_batches)"},
		{"存在没有对应细胞株的冻存管", "SELECT COUNT(*) FROM frozen_vials WHERE cell_line_id NOT IN (SELECT id FROM cell_lines)"},
		{"同一批次存在多条活跃记录", "SELECT COUNT(*) FROM (SELECT batch_id FROM culture_records WHERE is_active = 1 GROUP BY batch_id HAVING COUNT(*) > 1)"},
		{"已终止批次仍有活跃记录", "SELECT COUNT(*) FROM culture_records cr JOIN culture_batches cb ON cb.id = cr.batch_id WHERE cr.is_active = 1 AND cb.is_active = 0"},
		{"活跃批次没有活跃记录", "SELECT COUNT(*) FROM culture_batches cb WHERE cb.is_active = 1 AND NOT EXISTS (SELECT 1 FROM culture_records r WHERE r.batch_id = cb.id AND r.is_active = 1)"},
		{"日期格式不是 YYYY-MM-DD", "SELECT COUNT(*) FROM culture_records WHERE date NOT GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'"},
	}
	issues := []string{}
	for _, item := range queries {
		var count int
		if err := q.QueryRowContext(ctx, item.sql).Scan(&count); err != nil {
			continue
		}
		if count > 0 {
			issues = append(issues, fmt.Sprintf("%s：%d", item.label, count))
		}
	}
	return issues
}

func validateDatabaseFile(path string) map[string]any {
	if !fileExists(path) {
		return map[string]any{"ok": false, "reason": "文件不存在"}
	}
	if fileSize(path) == 0 {
		return map[string]any{"ok": false, "reason": "文件为空"}
	}
	db, err := openDB(path, true)
	if err != nil {
		return map[string]any{"ok": false, "reason": "无法打开为 SQLite：" + err.Error()}
	}
	defer db.Close()
	ctx := context.Background()
	rows, err := db.QueryContext(ctx, `SELECT name FROM sqlite_master WHERE type = 'table'`)
	if err != nil {
		return map[string]any{"ok": false, "reason": "读取失败：" + err.Error()}
	}
	tables := map[string]bool{}
	for rows.Next() {
		var name string
		if err := rows.Scan(&name); err == nil {
			tables[name] = true
		}
	}
	rows.Close()
	missing := []string{}
	coreSet := map[string]bool{}
	for _, table := range coreTables {
		coreSet[table] = true
		if !tables[table] {
			missing = append(missing, table)
		}
	}
	if len(missing) > 0 {
		return map[string]any{
			"ok":     false,
			"reason": "缺少数据表：" + strings.Join(missing, ", "),
		}
	}
	tableNames := make([]string, 0, len(coreSet))
	for table := range coreSet {
		tableNames = append(tableNames, table)
	}
	sort.Strings(tableNames)
	version, _ := getMeta(db, "schema_version")
	return map[string]any{
		"ok":             true,
		"tables":         tableNames,
		"counts":         tableCounts(ctx, db),
		"fingerprint":    dataFingerprint(ctx, db),
		"schema_version": version,
		"issues":         consistencyIssues(ctx, db),
	}
}

func backupDatabase(dbPath, dest string) error {
	if err := os.MkdirAll(filepath.Dir(dest), 0o755); err != nil {
		return err
	}
	_ = os.Remove(dest)
	db, err := openDB(dbPath, false)
	if err != nil {
		return err
	}
	defer db.Close()
	ctx := context.Background()
	if _, err := db.ExecContext(ctx, `VACUUM INTO ?`, dest); err == nil {
		return nil
	}
	// Fallback: checkpoint WAL and copy the main file.
	_, _ = db.ExecContext(ctx, `PRAGMA wal_checkpoint(TRUNCATE)`)
	return copyFile(dbPath, dest)
}

func defaultBackupName(prefix string) string {
	return fmt.Sprintf("%s-%s.db", prefix, time.Now().Format("20060102-150405"))
}

func pruneBackups(dir string, keep int) {
	entries, err := filepath.Glob(filepath.Join(dir, "*.db"))
	if err != nil {
		return
	}
	sort.Slice(entries, func(i, j int) bool {
		return modTime(entries[i]) > modTime(entries[j])
	})
	for _, stale := range entries[min(len(entries), keep):] {
		_ = os.Remove(stale)
	}
}

func copyFile(source, target string) error {
	if err := os.MkdirAll(filepath.Dir(target), 0o755); err != nil {
		return err
	}
	in, err := os.Open(source)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(target)
	if err != nil {
		return err
	}
	if _, err := io.Copy(out, in); err != nil {
		out.Close()
		return err
	}
	if err := out.Sync(); err != nil {
		out.Close()
		return err
	}
	return out.Close()
}

func fileSize(path string) int64 {
	info, err := os.Stat(path)
	if err != nil {
		return 0
	}
	return info.Size()
}

func modTime(path string) int64 {
	info, err := os.Stat(path)
	if err != nil {
		return 0
	}
	return info.ModTime().UnixNano()
}

func samePath(a, b string) bool {
	aa, _ := filepath.Abs(a)
	bb, _ := filepath.Abs(b)
	return strings.EqualFold(filepath.Clean(aa), filepath.Clean(bb))
}
