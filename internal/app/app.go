package app

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"mime"
	"net/http"
	"strconv"
	"strings"
)

type App struct {
	cfg      *Config
	store    *Store
	auth     *Auth
	shutdown func()
}

// SetShutdown installs the callback used by POST /api/shutdown.
func (a *App) SetShutdown(fn func()) {
	a.shutdown = fn
}

func New(cfg *Config, store *Store) (*App, error) {
	auth, err := NewAuth(cfg, store)
	if err != nil {
		return nil, err
	}
	app := &App{cfg: cfg, store: store, auth: auth}
	if err := auth.Bootstrap(context.Background()); err != nil {
		return nil, err
	}
	return app, nil
}

func (a *App) Handler() http.Handler {
	mux := http.NewServeMux()

	mux.HandleFunc("GET /api/healthz", func(w http.ResponseWriter, r *http.Request) {
		writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	})
	mux.HandleFunc("GET /api/meta", a.handleMeta)
	mux.HandleFunc("GET /api/auth/status", a.auth.HandleStatus)
	mux.HandleFunc("GET /api/auth/me", a.auth.HandleMe)
	mux.HandleFunc("POST /api/auth/login", a.auth.HandleLogin)
	mux.HandleFunc("POST /api/auth/logout", a.auth.HandleLogout)
	mux.HandleFunc("POST /api/shutdown", a.handleShutdown)

	mux.HandleFunc("GET /api/cell-lines", a.handleListLines)
	mux.HandleFunc("POST /api/cell-lines", a.handleCreateLine)
	mux.HandleFunc("GET /api/cell-lines/{id}", a.handleGetLine)
	mux.HandleFunc("PATCH /api/cell-lines/{id}", a.handleUpdateLine)
	mux.HandleFunc("DELETE /api/cell-lines/{id}", a.handleDeleteLine)
	mux.HandleFunc("POST /api/cell-lines/species", a.handleAssignSpecies)
	mux.HandleFunc("GET /api/cell-lines/{id}/batches", a.handleLineBatches)
	mux.HandleFunc("GET /api/cell-lines/{id}/vials", a.handleLineVials)

	mux.HandleFunc("GET /api/batches", a.handleListBatches)
	mux.HandleFunc("POST /api/batches", a.handleCreateBatch)
	mux.HandleFunc("GET /api/batches/{id}", a.handleGetBatch)
	mux.HandleFunc("PATCH /api/batches/{id}", a.handleUpdateBatch)
	mux.HandleFunc("DELETE /api/batches/{id}", a.handleDeleteBatch)
	mux.HandleFunc("POST /api/batches/{id}/terminate", a.handleTerminateBatch)
	mux.HandleFunc("POST /api/batches/{id}/restore", a.handleRestoreBatch)
	mux.HandleFunc("GET /api/batches/{id}/records", a.handleBatchRecords)
	mux.HandleFunc("GET /api/batches/{id}/records.csv", a.handleBatchCSV)

	mux.HandleFunc("POST /api/records", a.handleCreateRecord)
	mux.HandleFunc("POST /api/records/bulk", a.handleBulkCreateRecords)
	mux.HandleFunc("POST /api/records/bulk-update", a.handleBulkUpdateRecords)
	mux.HandleFunc("PATCH /api/records/{id}", a.handleUpdateRecord)
	mux.HandleFunc("DELETE /api/records/{id}", a.handleDeleteRecord)

	mux.HandleFunc("GET /api/vials", a.handleListVials)
	mux.HandleFunc("POST /api/vials", a.handleCreateVials)
	mux.HandleFunc("GET /api/vials/boxes", a.handleListBoxes)
	mux.HandleFunc("GET /api/vials/boxes/detail", a.handleBoxDetail)
	mux.HandleFunc("DELETE /api/vials/boxes", a.handleClearBox)
	mux.HandleFunc("PATCH /api/vials/{id}", a.handleUpdateVial)
	mux.HandleFunc("DELETE /api/vials/{id}", a.handleDeleteVial)
	mux.HandleFunc("POST /api/vials/import", a.handleImportVials)

	mux.HandleFunc("GET /api/groups", a.handleListGroups)
	mux.HandleFunc("POST /api/groups", a.handleCreateGroup)
	mux.HandleFunc("GET /api/groups/{id}", a.handleGetGroup)
	mux.HandleFunc("PATCH /api/groups/{id}", a.handleUpdateGroup)
	mux.HandleFunc("DELETE /api/groups/{id}", a.handleDeleteGroup)
	mux.HandleFunc("PUT /api/groups/{id}/members", a.handleSetMembers)
	mux.HandleFunc("GET /api/groups/{id}/status", a.handleGroupStatus)
	mux.HandleFunc("GET /api/groups/{id}/records", a.handleGroupRecords)
	mux.HandleFunc("GET /api/groups/{id}/rates", a.handleGroupRates)
	mux.HandleFunc("GET /api/groups/{id}/curves", a.handleGroupCurves)
	mux.HandleFunc("POST /api/groups/{id}/batches", a.handleGroupCreateBatches)
	mux.HandleFunc("POST /api/groups/{id}/terminate", a.handleGroupTerminate)
	mux.HandleFunc("GET /api/groups/{id}/export", a.handleGroupExport)

	mux.HandleFunc("GET /api/dashboard", a.handleDashboard)
	mux.HandleFunc("GET /api/compare/curves", a.handleCompareCurves)

	mux.HandleFunc("GET /api/maintenance/audit", a.handleAudit)
	mux.HandleFunc("POST /api/maintenance/recalculate", a.handleRecalculate)
	mux.HandleFunc("GET /api/maintenance/backups", a.handleListBackups)
	mux.HandleFunc("GET /api/maintenance/migration-report", a.handleMigrationReport)
	mux.HandleFunc("GET /api/maintenance/backup", a.handleDownloadBackup)
	mux.HandleFunc("POST /api/maintenance/restore", a.handleRestore)
	mux.HandleFunc("POST /api/maintenance/import-legacy", a.handleImportLegacy)
	mux.HandleFunc("GET /api/export/full", a.handleFullExport)

	mux.HandleFunc("/", a.serveFrontend)
	return a.recover(a.auth.Guard(mux))
}

func (a *App) recover(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if recovered := recover(); recovered != nil {
				log.Printf("未处理异常：%v", recovered)
				writeError(w, fmt.Errorf("服务器内部错误：%v", recovered))
			}
		}()
		next.ServeHTTP(w, r)
	})
}

func (a *App) username(r *http.Request) any {
	username, _ := a.auth.Current(r)
	if username == "" {
		return nil
	}
	return username
}

func (a *App) runWrite(w http.ResponseWriter, r *http.Request, status int, fn func(*sql.Tx) (any, error)) {
	var result any
	err := a.store.Write(r.Context(), func(tx *sql.Tx) error {
		var innerErr error
		result, innerErr = fn(tx)
		return innerErr
	})
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, status, result)
}

func readBody(r *http.Request) (map[string]any, error) {
	var payload map[string]any
	decoder := json.NewDecoder(io.LimitReader(r.Body, 32<<20))
	if err := decoder.Decode(&payload); err != nil {
		return nil, validationError("请求体必须是 JSON 对象")
	}
	if payload == nil {
		return nil, validationError("请求体必须是 JSON 对象")
	}
	return payload, nil
}

func readBodyOptional(r *http.Request) (map[string]any, error) {
	var payload map[string]any
	decoder := json.NewDecoder(io.LimitReader(r.Body, 32<<20))
	if err := decoder.Decode(&payload); err != nil {
		if err == io.EOF {
			return map[string]any{}, nil
		}
		return nil, validationError("请求体必须是 JSON 对象")
	}
	if payload == nil {
		return map[string]any{}, nil
	}
	return payload, nil
}

func readBodyAny(r *http.Request) (map[string]any, error) {
	contentType := strings.ToLower(r.Header.Get("Content-Type"))
	if strings.Contains(contentType, "application/x-www-form-urlencoded") ||
		strings.Contains(contentType, "multipart/form-data") {
		if err := r.ParseForm(); err != nil {
			return nil, validationError("无法解析表单")
		}
		payload := map[string]any{}
		for key, values := range r.PostForm {
			if len(values) > 0 {
				payload[key] = values[0]
			}
		}
		return payload, nil
	}
	return readBody(r)
}

func pathID(r *http.Request) (int64, error) {
	raw := r.PathValue("id")
	value, err := strconv.ParseInt(raw, 10, 64)
	if err != nil {
		return 0, validationError("无效的 id：" + raw)
	}
	return value, nil
}

func queryInt(r *http.Request, name string) (*int64, error) {
	raw := strings.TrimSpace(r.URL.Query().Get(name))
	if raw == "" {
		return nil, nil
	}
	value, err := strconv.ParseInt(raw, 10, 64)
	if err != nil {
		return nil, validationError(fmt.Sprintf("参数 %s 必须是整数", name))
	}
	return &value, nil
}

func queryBool(r *http.Request, name string, defaultValue bool) bool {
	raw := strings.TrimSpace(r.URL.Query().Get(name))
	if raw == "" {
		return defaultValue
	}
	switch strings.ToLower(raw) {
	case "1", "true", "yes", "on":
		return true
	}
	return false
}

func sendBytes(w http.ResponseWriter, data []byte, contentType, filename string) {
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Content-Disposition", mime.FormatMediaType("attachment", map[string]string{"filename": filename}))
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(data)
}
