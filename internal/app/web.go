package app

import (
	"io/fs"
	"mime"
	"net/http"
	"os"
	"path"
	"path/filepath"
	"strconv"
	"strings"

	"celltracker/web"
)

const missingFrontendHTML = `<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>CellTracker 前端未构建</title>
<style>body{font-family:system-ui,"Microsoft YaHei",sans-serif;max-width:720px;margin:80px auto;
padding:0 24px;line-height:1.7;color:#1f2937}code{background:#f3f4f6;padding:2px 6px;border-radius:4px}
h1{font-size:22px}.box{background:#fff7ed;border:1px solid #fed7aa;padding:16px;border-radius:10px}</style>
</head><body>
<h1>🧬 CellTracker 后端已启动</h1>
<div class="box">
<p>前端静态文件还没有构建。运行 <code>build.ps1</code> 会把 Vue 页面打包进程序。</p>
<p>开发模式可以执行 <code>npm run build</code>（目录 <code>frontend</code>），或使用 <code>npm run dev</code>。</p>
</div>
<p>API 健康检查：<a href="/api/healthz">/api/healthz</a></p>
</body></html>`

func (a *App) serveFrontend(w http.ResponseWriter, r *http.Request) {
	if strings.HasPrefix(r.URL.Path, "/api/") {
		writeJSON(w, http.StatusNotFound, map[string]any{
			"error": map[string]any{"code": "not_found", "message": "接口不存在"},
		})
		return
	}
	requestPath := strings.TrimPrefix(r.URL.Path, "/")
	if requestPath == "" {
		requestPath = "index.html"
	}
	requestPath = path.Clean("/" + requestPath)
	requestPath = strings.TrimPrefix(requestPath, "/")
	if strings.HasPrefix(requestPath, "..") {
		requestPath = "index.html"
	}

	if data, name, ok := readDiskAsset(a.cfg.FrontendDist, requestPath); ok {
		writeAsset(w, name, data)
		return
	}
	if data, ok := readEmbeddedAsset(requestPath); ok {
		writeAsset(w, requestPath, data)
		return
	}
	if data, ok := readEmbeddedAsset("index.html"); ok {
		writeAsset(w, "index.html", data)
		return
	}
	w.Header().Set("Content-Type", "text/html; charset=utf-8")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(missingFrontendHTML))
}

func readDiskAsset(dist, requestPath string) ([]byte, string, bool) {
	if !dirExists(dist) || !fileExists(filepath.Join(dist, "index.html")) {
		return nil, "", false
	}
	clean := filepath.Clean(filepath.FromSlash(requestPath))
	candidate := filepath.Join(dist, clean)
	absoluteDist, _ := filepath.Abs(dist)
	absoluteCandidate, _ := filepath.Abs(candidate)
	if !strings.HasPrefix(strings.ToLower(absoluteCandidate), strings.ToLower(absoluteDist)+string(os.PathSeparator)) {
		return nil, "", false
	}
	if !fileExists(candidate) {
		return nil, "", false
	}
	data, err := os.ReadFile(candidate)
	if err != nil {
		return nil, "", false
	}
	return data, requestPath, true
}

func readEmbeddedAsset(requestPath string) ([]byte, bool) {
	clean := path.Clean("/" + requestPath)
	clean = strings.TrimPrefix(clean, "/")
	data, err := fs.ReadFile(web.Assets, "dist/"+clean)
	if err != nil {
		return nil, false
	}
	return data, true
}

func writeAsset(w http.ResponseWriter, name string, data []byte) {
	contentType := mime.TypeByExtension(strings.ToLower(filepath.Ext(name)))
	if contentType == "" {
		contentType = "application/octet-stream"
	}
	if (strings.HasPrefix(contentType, "text/") || contentType == "application/javascript") &&
		!strings.Contains(strings.ToLower(contentType), "charset=") {
		contentType += "; charset=utf-8"
	}
	w.Header().Set("Content-Type", contentType)
	w.Header().Set("Cache-Control", "no-cache")
	w.Header().Set("Content-Length", strconv.Itoa(len(data)))
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write(data)
}
