package app

import (
	"encoding/json"
	"fmt"
	"io/fs"
	"os"
	"path/filepath"
	"runtime"
	"strconv"
	"strings"

	"celltracker/web"
)

const (
	AppVersion    = "4.0.0"
	SchemaVersion = 1
)

// Config mirrors the Python application's config.json so existing deployments
// keep working without edits.
type Config struct {
	Host          string
	Port          int
	Debug         bool
	OpenBrowser   bool
	DBPath        string
	BackupDir     string
	FrontendDist  string
	AuthEnabled   bool
	SessionDays   int
	BootstrapUser string
	BootstrapPass string
	ConfigPath    string
	BaseDir       string
}

type fileConfig struct {
	Host         string          `json:"host"`
	Port         *int            `json:"port"`
	Debug        *bool           `json:"debug"`
	OpenBrowser  *bool           `json:"open_browser"`
	Database     string          `json:"database"`
	BackupDir    string          `json:"backup_dir"`
	FrontendDist string          `json:"frontend_dist"`
	Auth         *authFileConfig `json:"auth"`
}

type authFileConfig struct {
	Enabled           *bool  `json:"enabled"`
	SessionDays       *int   `json:"session_days"`
	BootstrapUsername string `json:"bootstrap_username"`
	BootstrapPassword string `json:"bootstrap_password"`
}

func userConfigDir() string {
	if runtime.GOOS == "darwin" {
		home, err := os.UserHomeDir()
		if err == nil {
			return filepath.Join(home, "Library", "Application Support", "CellTracker")
		}
	}
	if dir, err := os.UserConfigDir(); err == nil {
		return filepath.Join(dir, "CellTracker")
	}
	return "."
}

// baseDir is where config.json, data/ and backups/ live.
//
// Development runs (`go run`) are detected by go.mod + frontend/ in the current
// directory so the existing Python database can be opened directly. Packaged
// builds use the executable's directory (portable Windows layout), except for
// macOS .app bundles where user data belongs in Application Support.
func baseDir() string {
	if value := strings.TrimSpace(os.Getenv("CELLTRACKER_HOME")); value != "" {
		abs, err := filepath.Abs(value)
		if err == nil {
			return abs
		}
	}
	cwd, _ := os.Getwd()
	if fileExists(filepath.Join(cwd, "go.mod")) && dirExists(filepath.Join(cwd, "frontend")) {
		return cwd
	}
	exe, err := os.Executable()
	if err == nil {
		exe, _ = filepath.EvalSymlinks(exe)
		dir := filepath.Dir(exe)
		if runtime.GOOS == "darwin" && strings.Contains(filepath.ToSlash(dir), ".app/Contents/MacOS") {
			return userConfigDir()
		}
		return dir
	}
	return cwd
}

func resolvePath(base, value string) string {
	value = strings.TrimSpace(value)
	if value == "" {
		return ""
	}
	if strings.HasPrefix(value, "~/") || value == "~" {
		if home, err := os.UserHomeDir(); err == nil {
			value = filepath.Join(home, strings.TrimPrefix(value, "~/"))
		}
	}
	if !filepath.IsAbs(value) {
		value = filepath.Join(base, value)
	}
	abs, err := filepath.Abs(value)
	if err != nil {
		return value
	}
	return abs
}

func defaultConfig() Config {
	base := baseDir()
	return Config{
		Host:          "127.0.0.1",
		Port:          18600,
		Debug:         false,
		OpenBrowser:   true,
		DBPath:        filepath.Join(base, "data", "cell_data.db"),
		BackupDir:     filepath.Join(base, "backups"),
		FrontendDist:  filepath.Join(base, "frontend", "dist"),
		AuthEnabled:   false,
		SessionDays:   30,
		BootstrapUser: "admin",
		BootstrapPass: "celltracker",
		BaseDir:       base,
	}
}

// LoadConfig reads config.json from an explicit path, CELLTRACKER_CONFIG, the
// data directory, or the executable/current directory (in that order).
func LoadConfig(explicit string) (*Config, error) {
	cfg := defaultConfig()
	base := cfg.BaseDir

	candidates := []string{}
	if explicit != "" {
		candidates = append(candidates, explicit)
	} else if env := strings.TrimSpace(os.Getenv("CELLTRACKER_CONFIG")); env != "" {
		candidates = append(candidates, env)
	} else {
		candidates = append(candidates,
			filepath.Join(base, "config.json"),
			filepath.Join(userConfigDir(), "config.json"),
		)
		if cwd, err := os.Getwd(); err == nil {
			candidates = append(candidates, filepath.Join(cwd, "config.json"))
		}
	}

	for _, candidate := range candidates {
		if !fileExists(candidate) {
			continue
		}
		raw, err := os.ReadFile(candidate)
		if err != nil {
			return nil, fmt.Errorf("读取配置 %s 失败：%w", candidate, err)
		}
		raw = []byte(strings.TrimPrefix(string(raw), "\ufeff"))
		var fc fileConfig
		if err := json.Unmarshal(raw, &fc); err != nil {
			// A broken config should not prevent startup, matching Python.
			fmt.Fprintf(os.Stderr, "[config] 警告：无法解析 %s：%v，使用默认配置\n", candidate, err)
			continue
		}
		cfg.ConfigPath = candidate
		applyFileConfig(&cfg, fc, base)
		break
	}

	if cfg.ConfigPath == "" {
		for _, candidate := range candidates {
			if fileExists(candidate) {
				cfg.ConfigPath = candidate
				break
			}
		}
	}

	if v := strings.TrimSpace(os.Getenv("CELLTRACKER_HOST")); v != "" {
		cfg.Host = v
	}
	if v := strings.TrimSpace(os.Getenv("CELLTRACKER_PORT")); v != "" {
		if port, err := strconv.Atoi(v); err == nil {
			cfg.Port = port
		}
	}
	if v := strings.TrimSpace(os.Getenv("CELLTRACKER_DB")); v != "" {
		cfg.DBPath = resolvePath(base, v)
	}
	if v := strings.TrimSpace(os.Getenv("CELLTRACKER_BACKUP_DIR")); v != "" {
		cfg.BackupDir = resolvePath(base, v)
	}
	if cfg.Port < 1 || cfg.Port > 65535 {
		cfg.Port = 18600
	}
	if cfg.SessionDays < 1 {
		cfg.SessionDays = 30
	}
	return &cfg, nil
}

func applyFileConfig(cfg *Config, fc fileConfig, base string) {
	if fc.Host != "" {
		cfg.Host = fc.Host
	}
	if fc.Port != nil {
		cfg.Port = *fc.Port
	}
	if fc.Debug != nil {
		cfg.Debug = *fc.Debug
	}
	if fc.OpenBrowser != nil {
		cfg.OpenBrowser = *fc.OpenBrowser
	}
	if fc.Database != "" {
		cfg.DBPath = resolvePath(base, fc.Database)
	}
	if fc.BackupDir != "" {
		cfg.BackupDir = resolvePath(base, fc.BackupDir)
	}
	if fc.FrontendDist != "" {
		cfg.FrontendDist = resolvePath(base, fc.FrontendDist)
	}
	if fc.Auth != nil {
		if fc.Auth.Enabled != nil {
			cfg.AuthEnabled = *fc.Auth.Enabled
		}
		if fc.Auth.SessionDays != nil && *fc.Auth.SessionDays > 0 {
			cfg.SessionDays = *fc.Auth.SessionDays
		}
		if fc.Auth.BootstrapUsername != "" {
			cfg.BootstrapUser = fc.Auth.BootstrapUsername
		}
		if fc.Auth.BootstrapPassword != "" {
			cfg.BootstrapPass = fc.Auth.BootstrapPassword
		}
	}
}

// ApplyDataDir switches the whole application to a portable data directory.
func ApplyDataDir(c *Config, dir string) {
	abs, err := filepath.Abs(dir)
	if err != nil {
		abs = dir
	}
	c.BaseDir = abs
	c.DBPath = filepath.Join(abs, "data", "cell_data.db")
	c.BackupDir = filepath.Join(abs, "backups")
	c.FrontendDist = filepath.Join(abs, "frontend", "dist")
}

func (c *Config) EnsureDirs() error {
	if err := os.MkdirAll(filepath.Dir(c.DBPath), 0o755); err != nil {
		return err
	}
	return os.MkdirAll(c.BackupDir, 0o755)
}

func (c *Config) PublicMeta() map[string]any {
	frontendBuilt := fileExists(filepath.Join(c.FrontendDist, "index.html"))
	if !frontendBuilt {
		if _, err := fs.Stat(web.Assets, "dist/index.html"); err == nil {
			frontendBuilt = true
		}
	}
	return map[string]any{
		"app_version":    AppVersion,
		"schema_version": SchemaVersion,
		"database":       c.DBPath,
		"backup_dir":     c.BackupDir,
		"auth": map[string]any{
			"enabled":      c.AuthEnabled,
			"session_days": c.SessionDays,
		},
		"frontend_built": frontendBuilt,
	}
}

func fileExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && !info.IsDir()
}

func dirExists(path string) bool {
	info, err := os.Stat(path)
	return err == nil && info.IsDir()
}
