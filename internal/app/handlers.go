package app

import (
	"database/sql"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"
)

func (a *App) handleShutdown(w http.ResponseWriter, r *http.Request) {
	if r.Header.Get("X-CellTracker-Shutdown") != "1" {
		writeError(w, &APIError{Status: http.StatusForbidden, Code: "forbidden", Message: "缺少退出确认"})
		return
	}
	host, _, err := net.SplitHostPort(r.RemoteAddr)
	if err != nil {
		host = r.RemoteAddr
	}
	if host != "127.0.0.1" && host != "::1" && host != "localhost" {
		writeError(w, &APIError{Status: http.StatusForbidden, Code: "forbidden", Message: "只允许本机退出"})
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
	if a.shutdown != nil {
		go func() {
			time.Sleep(250 * time.Millisecond)
			a.shutdown()
		}()
	}
}

func (a *App) handleMeta(w http.ResponseWriter, r *http.Request) {
	counts := tableCounts(r.Context(), a.store.DB())
	backups, _ := listBackups(a.cfg)
	username, _ := a.auth.Current(r)
	payload := a.cfg.PublicMeta()
	payload["counts"] = counts
	payload["auth"] = map[string]any{
		"enabled":  a.cfg.AuthEnabled,
		"username": nullableText(username),
	}
	payload["migration"] = migrationSummary(readMigrationReport(a.cfg))
	payload["backup_count"] = len(backups)
	payload["today"] = todayISO()
	// 标签配色表：前端所有图表共用这一套颜色
	payload["species_colors"] = buildSpeciesPalette(r.Context(), a.store.DB())
	writeJSON(w, http.StatusOK, payload)
}

func migrationSummary(report any) any {
	if report == nil {
		return nil
	}
	data, ok := report.(map[string]any)
	if !ok {
		return nil
	}
	summary := map[string]any{
		"status":       data["status"],
		"source":       data["source"],
		"generated_at": data["generated_at"],
		"counts":       data["target_counts"],
	}
	if pdAudit, ok := data["pd_audit"].(map[string]any); ok {
		summary["pd_mismatch_count"] = pdAudit["mismatch_count"]
	}
	summary["checksums_equal"] = data["checksums_equal"]
	summary["report_path"] = data["report_path"]
	return summary
}

func (a *App) handleListLines(w http.ResponseWriter, r *http.Request) {
	rows, err := listLines(r.Context(), a.store.DB(), r.URL.Query().Get("search"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleCreateLine(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusCreated, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return createLine(r.Context(), tx, payload, a.username(r))
	})
}

func (a *App) handleGetLine(w http.ResponseWriter, r *http.Request) {
	lineID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	ctx := r.Context()
	line, err := getLineSummary(ctx, a.store.DB(), lineID)
	if err != nil {
		writeError(w, err)
		return
	}
	batches, err := lineBatches(ctx, a.store.DB(), lineID, queryBool(r, "include_ended", true))
	if err != nil {
		writeError(w, err)
		return
	}
	vials, err := lineVials(ctx, a.store.DB(), lineID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"cell_line": line, "batches": batches, "vials": vials})
}

func (a *App) handleUpdateLine(w http.ResponseWriter, r *http.Request) {
	lineID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return updateLine(r.Context(), tx, lineID, payload, a.username(r))
	})
}

func (a *App) handleDeleteLine(w http.ResponseWriter, r *http.Request) {
	lineID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return deleteLine(r.Context(), tx, lineID, a.username(r))
	})
}

// handleAssignSpecies 批量写标签。
//   - entries: [{id, species}] 逐行写入（界面预览后确认用）
//   - 兼容旧用法：{species, line_ids?, only_unset?} 给一批细胞株统一打同一标签
func (a *App) handleAssignSpecies(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		ctx := r.Context()

		if rawEntries, ok := payload["entries"]; ok {
			entries, ok := rawEntries.([]any)
			if !ok {
				return nil, validationError("entries 必须是数组")
			}
			updated := 0
			for _, raw := range entries {
				entry, ok := raw.(map[string]any)
				if !ok {
					continue
				}
				lineID, ok := asInt(entry["id"])
				if !ok {
					lineID, ok = asInt(entry["cell_line_id"])
				}
				if !ok || lineID <= 0 {
					continue
				}
				if _, err := updateLine(ctx, tx, lineID, map[string]any{
					"species": entry["species"],
				}, a.username(r)); err != nil {
					return nil, err
				}
				updated++
			}
			return map[string]any{"updated": updated, "entries": updated}, nil
		}

		species, _ := normalizeText(payload["species"], 40)
		if species == "" {
			return nil, validationError("标签不能为空")
		}
		var lineIDs []int64
		if rawIDs, ok := payload["line_ids"]; ok {
			list, ok := rawIDs.([]any)
			if !ok {
				return nil, validationError("line_ids 必须是数组")
			}
			for _, item := range list {
				if id, ok := asInt(item); ok {
					lineIDs = append(lineIDs, id)
				}
			}
		}
		onlyUnset := true
		if raw, ok := payload["only_unset"]; ok {
			onlyUnset = asBool(raw)
		}
		return assignSpecies(ctx, tx, species, lineIDs, onlyUnset, a.username(r))
	})
}

func (a *App) handleLineBatches(w http.ResponseWriter, r *http.Request) {
	lineID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	rows, err := lineBatches(r.Context(), a.store.DB(), lineID, queryBool(r, "include_ended", true))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleLineVials(w http.ResponseWriter, r *http.Request) {
	lineID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	rows, err := lineVials(r.Context(), a.store.DB(), lineID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleListBatches(w http.ResponseWriter, r *http.Request) {
	cellLineID, err := queryInt(r, "cell_line_id")
	if err != nil {
		writeError(w, err)
		return
	}
	var active *bool
	if raw := strings.TrimSpace(r.URL.Query().Get("is_active")); raw != "" {
		value := strings.ToLower(raw) == "1" || strings.ToLower(raw) == "true" || strings.ToLower(raw) == "yes"
		active = &value
	}
	rows, err := listBatches(r.Context(), a.store.DB(), cellLineID, active, r.URL.Query().Get("q"))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleCreateBatch(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusCreated, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return createBatch(r.Context(), tx, payload, a.username(r))
	})
}

func (a *App) handleGetBatch(w http.ResponseWriter, r *http.Request) {
	batchID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	detail, err := getBatchDetail(r.Context(), a.store.DB(), batchID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, detail)
}

func (a *App) handleUpdateBatch(w http.ResponseWriter, r *http.Request) {
	batchID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return updateBatch(r.Context(), tx, batchID, payload, a.username(r))
	})
}

func (a *App) handleDeleteBatch(w http.ResponseWriter, r *http.Request) {
	batchID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return deleteBatch(r.Context(), tx, batchID, a.username(r))
	})
}

func (a *App) handleTerminateBatch(w http.ResponseWriter, r *http.Request) {
	batchID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBodyOptional(r)
		if err != nil {
			return nil, err
		}
		reason := any("其他")
		if value, ok := payload["reason"]; ok {
			reason = value
		}
		return terminateBatch(r.Context(), tx, batchID, reason, a.username(r))
	})
}

func (a *App) handleRestoreBatch(w http.ResponseWriter, r *http.Request) {
	batchID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return restoreBatch(r.Context(), tx, batchID, a.username(r))
	})
}

func (a *App) handleBatchRecords(w http.ResponseWriter, r *http.Request) {
	batchID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	rows, err := listRecords(r.Context(), a.store.DB(), batchID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleBatchCSV(w http.ResponseWriter, r *http.Request) {
	batchID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	data, filename, err := batchRecordsCSV(r.Context(), a.store.DB(), batchID)
	if err != nil {
		writeError(w, err)
		return
	}
	sendBytes(w, data, "text/csv; charset=utf-8", filename)
}

func (a *App) handleCreateRecord(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusCreated, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return createRecord(r.Context(), tx, payload, a.username(r))
	})
}

func (a *App) handleBulkCreateRecords(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		entries, ok := payload["entries"].([]any)
		if !ok {
			entries, ok = payload["records"].([]any)
		}
		if !ok {
			return nil, validationError("entries 必须是数组")
		}
		return bulkCreate(r.Context(), tx, entries, a.username(r))
	})
}

func (a *App) handleBulkUpdateRecords(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		entries, ok := payload["entries"].([]any)
		if !ok {
			entries, ok = payload["records"].([]any)
		}
		if !ok {
			return nil, validationError("entries 必须是数组")
		}
		return bulkUpdate(r.Context(), tx, entries, a.username(r))
	})
}

func (a *App) handleUpdateRecord(w http.ResponseWriter, r *http.Request) {
	recordID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return updateRecord(r.Context(), tx, recordID, payload, a.username(r))
	})
}

func (a *App) handleDeleteRecord(w http.ResponseWriter, r *http.Request) {
	recordID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return deleteRecord(r.Context(), tx, recordID, a.username(r))
	})
}

func (a *App) handleListVials(w http.ResponseWriter, r *http.Request) {
	cellLineID, err := queryInt(r, "cell_line_id")
	if err != nil {
		writeError(w, err)
		return
	}
	limit := 500
	if value, err := queryInt(r, "limit"); err != nil {
		writeError(w, err)
		return
	} else if value != nil {
		limit = int(*value)
	}
	rows, err := listVials(r.Context(), a.store.DB(), r.URL.Query().Get("q"), cellLineID,
		r.URL.Query().Get("status"), limit, queryBool(r, "unplaced", false))
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleCreateVials(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusCreated, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return createVials(r.Context(), tx, payload, a.username(r))
	})
}

func (a *App) handleListBoxes(w http.ResponseWriter, r *http.Request) {
	rows, err := listBoxes(r.Context(), a.store.DB())
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleBoxDetail(w http.ResponseWriter, r *http.Request) {
	box := strings.TrimSpace(r.URL.Query().Get("box"))
	if box == "" {
		writeError(w, validationError("缺少 box 参数"))
		return
	}
	detail, err := boxDetail(r.Context(), a.store.DB(), box)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, detail)
}

func (a *App) handleClearBox(w http.ResponseWriter, r *http.Request) {
	box := strings.TrimSpace(r.URL.Query().Get("box"))
	if box == "" {
		writeError(w, validationError("缺少 box 参数"))
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return clearBox(r.Context(), tx, box, a.username(r))
	})
}

func (a *App) handleUpdateVial(w http.ResponseWriter, r *http.Request) {
	vialID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return updateVial(r.Context(), tx, vialID, payload, a.username(r))
	})
}

func (a *App) handleDeleteVial(w http.ResponseWriter, r *http.Request) {
	vialID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return deleteVial(r.Context(), tx, vialID, a.username(r))
	})
}

func (a *App) handleImportVials(w http.ResponseWriter, r *http.Request) {
	if err := r.ParseMultipartForm(32 << 20); err != nil {
		writeError(w, validationError("请上传 Excel 文件"))
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil || header == nil {
		writeError(w, validationError("请上传 Excel 文件"))
		return
	}
	defer file.Close()
	mode := r.FormValue("mode")
	if mode == "" {
		mode = "append"
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return importFromWorkbook(r.Context(), tx, file, mode, a.username(r))
	})
}

func (a *App) handleListGroups(w http.ResponseWriter, r *http.Request) {
	rows, err := listGroups(r.Context(), a.store.DB())
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleCreateGroup(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusCreated, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return createGroup(r.Context(), tx, payload, a.username(r))
	})
}

func (a *App) handleGetGroup(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	group, err := getGroup(r.Context(), a.store.DB(), groupID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, group)
}

func (a *App) handleUpdateGroup(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return updateGroup(r.Context(), tx, groupID, payload, a.username(r))
	})
}

func (a *App) handleDeleteGroup(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		return deleteGroup(r.Context(), tx, groupID, a.username(r))
	})
}

func (a *App) handleSetMembers(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		raw, ok := payload["members"]
		if !ok {
			raw = payload["cell_line_ids"]
		}
		members, ok := raw.([]any)
		if !ok {
			return nil, validationError("members 必须是数组")
		}
		return setMembers(r.Context(), tx, groupID, members, a.username(r))
	})
}

func (a *App) handleGroupStatus(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	rows, err := groupStatus(r.Context(), a.store.DB(), groupID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleGroupRecords(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	rows, err := groupRecords(r.Context(), a.store.DB(), groupID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleGroupRates(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	rows, err := groupRates(r.Context(), a.store.DB(), groupID)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, rows)
}

func (a *App) handleGroupCurves(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	endedIDs := parseIntList(r.URL.Query().Get("ended_ids"))
	payload, err := groupCurves(r.Context(), a.store.DB(), groupID,
		queryBool(r, "normalize", false), r.URL.Query().Get("start_date"), endedIDs)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func (a *App) handleGroupCreateBatches(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusCreated, func(tx *sqlTx) (any, error) {
		payload, err := readBody(r)
		if err != nil {
			return nil, err
		}
		return groupCreateBatches(r.Context(), tx, groupID, payload, a.username(r))
	})
}

func (a *App) handleGroupTerminate(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		payload, err := readBodyOptional(r)
		if err != nil {
			return nil, err
		}
		reason := any("其他")
		if value, ok := payload["reason"]; ok {
			reason = value
		}
		return groupTerminate(r.Context(), tx, groupID, reason, a.username(r))
	})
}

func (a *App) handleGroupExport(w http.ResponseWriter, r *http.Request) {
	groupID, err := pathID(r)
	if err != nil {
		writeError(w, err)
		return
	}
	buffer, filename, err := groupExport(r.Context(), a.store.DB(), groupID, queryBool(r, "include_all", true))
	if err != nil {
		writeError(w, err)
		return
	}
	sendBytes(w, buffer.Bytes(),
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename)
}

func (a *App) handleDashboard(w http.ResponseWriter, r *http.Request) {
	payload, err := dashboard(r.Context(), a.store.DB())
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func (a *App) handleCompareCurves(w http.ResponseWriter, r *http.Request) {
	lineIDs := parseIntList(r.URL.Query().Get("line_ids"))
	if len(lineIDs) == 0 {
		writeError(w, validationError("请至少选择一个细胞株"))
		return
	}
	batchIDs := parseIntList(r.URL.Query().Get("batch_ids"))
	basis := r.URL.Query().Get("basis")
	if basis == "" {
		basis = "date"
	}
	payload, err := compareCurves(r.Context(), a.store.DB(), lineIDs, batchIDs,
		queryBool(r, "include_ended", false), queryBool(r, "normalize", false),
		r.URL.Query().Get("start_date"), basis)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func (a *App) handleAudit(w http.ResponseWriter, r *http.Request) {
	payload, err := databaseAudit(r.Context(), a.cfg, a.store.DB())
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, payload)
}

func (a *App) handleRecalculate(w http.ResponseWriter, r *http.Request) {
	a.runWrite(w, r, http.StatusOK, func(tx *sqlTx) (any, error) {
		result, err := recalcAll(r.Context(), tx, a.username(r))
		if err != nil {
			return nil, err
		}
		result["remaining_issues"] = consistencyIssues(r.Context(), tx)
		return result, nil
	})
}

func (a *App) handleListBackups(w http.ResponseWriter, r *http.Request) {
	items, err := listBackups(a.cfg)
	if err != nil {
		writeError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, items)
}

func (a *App) handleMigrationReport(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, http.StatusOK, readMigrationReport(a.cfg))
}

func (a *App) handleDownloadBackup(w http.ResponseWriter, r *http.Request) {
	path, err := copyForDownload(a.cfg)
	if err != nil {
		writeError(w, err)
		return
	}
	data, err := os.ReadFile(path)
	if err != nil {
		writeError(w, err)
		return
	}
	sendBytes(w, data, "application/octet-stream", filepathBase(path))
}

func (a *App) handleRestore(w http.ResponseWriter, r *http.Request) {
	path, original, err := a.receiveDatabaseUpload(r)
	if err != nil {
		writeError(w, err)
		return
	}
	defer cleanupUpload(path)
	result, err := restoreDatabase(r.Context(), a.cfg, a.store, path)
	if err != nil {
		writeError(w, err)
		return
	}
	result["uploaded_name"] = original
	writeJSON(w, http.StatusOK, result)
}

func (a *App) handleImportLegacy(w http.ResponseWriter, r *http.Request) {
	path, original, err := a.receiveDatabaseUpload(r)
	if err != nil {
		writeError(w, err)
		return
	}
	defer cleanupUpload(path)
	result, err := importLegacyDatabase(r.Context(), a.cfg, a.store, path)
	if err != nil {
		writeError(w, err)
		return
	}
	result["uploaded_name"] = original
	writeJSON(w, http.StatusOK, result)
}

func (a *App) receiveDatabaseUpload(r *http.Request) (string, string, error) {
	if err := r.ParseMultipartForm(64 << 20); err != nil {
		return "", "", validationError("请上传数据库文件（.db）")
	}
	file, header, err := r.FormFile("file")
	if err != nil || header == nil {
		return "", "", validationError("请上传数据库文件（.db）")
	}
	defer file.Close()
	name := header.Filename
	lower := strings.ToLower(name)
	if !strings.HasSuffix(lower, ".db") && !strings.HasSuffix(lower, ".sqlite") && !strings.HasSuffix(lower, ".sqlite3") {
		return "", "", validationError("只接受 .db / .sqlite / .sqlite3 文件")
	}
	path, err := saveUpload(a.cfg, file, name)
	if err != nil {
		return "", "", err
	}
	return path, name, nil
}

func (a *App) handleFullExport(w http.ResponseWriter, r *http.Request) {
	buffer, filename, err := fullExport(r.Context(), a.store.DB())
	if err != nil {
		writeError(w, err)
		return
	}
	sendBytes(w, buffer.Bytes(),
		"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", filename)
}

func parseIntList(raw string) []int64 {
	result := []int64{}
	for _, part := range strings.Split(raw, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		value, err := strconv.ParseInt(part, 10, 64)
		if err == nil {
			result = append(result, value)
		}
	}
	return result
}

func filepathBase(path string) string {
	path = strings.ReplaceAll(path, "\\", "/")
	if index := strings.LastIndex(path, "/"); index >= 0 {
		return path[index+1:]
	}
	return path
}

// sqlTx is an alias so handler signatures stay readable while still accepting
// *sql.Tx (the concrete type used by Store.Write).
type sqlTx = sql.Tx
