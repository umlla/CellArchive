"""Flask 应用工厂。"""

from __future__ import annotations

import logging
import sqlite3
import traceback

from flask import Flask, jsonify, request, send_file

from . import db
from .config import APP_VERSION, Config
from .errors import ApiError

logger = logging.getLogger("celltracker")

MISSING_FRONTEND_HTML = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>细胞档案 前端未构建</title>
<style>body{font-family:system-ui,"Microsoft YaHei",sans-serif;max-width:720px;margin:80px auto;
padding:0 24px;line-height:1.7;color:#1f2937}code{background:#f3f4f6;padding:2px 6px;border-radius:4px}
h1{font-size:22px}.box{background:#fff7ed;border:1px solid #fed7aa;padding:16px;border-radius:10px}</style>
</head><body>
<h1>细胞档案 CellArchive v4 后端已启动</h1>
<div class="box">
<p>前端静态文件还没有构建。<strong>推荐直接双击项目根目录的 <code>start.bat</code></strong>，
它会自动安装依赖并构建前端。</p>
<p>也可以手动执行：</p>
<pre><code>cd frontend
npm install
npm run build</code></pre>
<p>然后刷新本页。开发模式请另开终端运行 <code>npm run dev</code>（<code>http://localhost:5173</code>）。</p>
</div>
<p>API 健康检查：<a href="/api/healthz">/api/healthz</a> ｜
接口信息：<a href="/api/meta">/api/meta</a></p>
</body></html>"""


def create_app(config: Config | None = None) -> Flask:
    # 延迟导入，避免 `python -m backend.migrate` 时包初始化提前加载子模块
    from .api import api_bp, close_request_db
    from .auth import init_auth
    from .migrate import ensure_database

    config = config or Config.load()
    config.ensure_dirs()

    migration_info = ensure_database(config)
    if migration_info.get("migrated"):
        logger.info("已从旧版数据库迁移：%s", migration_info.get("source"))

    app = Flask(__name__, static_folder=None)
    app.config["CELLTRACKER_CONFIG"] = config
    app.config["MIGRATION_INFO"] = migration_info
    app.json.ensure_ascii = False
    app.json.sort_keys = False

    @app.teardown_appcontext
    def _teardown(_exception=None):
        close_request_db()

    init_auth(app, config)
    app.register_blueprint(api_bp)

    # ---------------- 错误处理 ----------------
    @app.errorhandler(ApiError)
    def _handle_api_error(error: ApiError):
        return jsonify(error.to_dict()), error.status

    @app.errorhandler(sqlite3.IntegrityError)
    def _handle_integrity(error: sqlite3.IntegrityError):
        logger.warning("数据库约束冲突：%s", error)
        message = "数据冲突：可能是名称重复或关联记录不存在"
        if "UNIQUE" in str(error).upper():
            message = "名称已存在，请换一个名称"
        return jsonify({"error": {"code": "conflict", "message": message}}), 409

    @app.errorhandler(404)
    def _handle_404(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": {"code": "not_found", "message": "接口不存在"}}), 404
        return _serve_index(config)

    @app.errorhandler(Exception)
    def _handle_unexpected(error: Exception):
        logger.error("未处理异常：%s\n%s", error, traceback.format_exc())
        return jsonify({
            "error": {
                "code": "internal_error",
                "message": f"服务器内部错误：{error}",
            }
        }), 500

    # ---------------- 前端静态资源 ----------------
    @app.get("/")
    def index():
        return _serve_index(config)

    @app.get("/<path:asset_path>")
    def frontend_assets(asset_path: str):
        if asset_path.startswith("api/"):
            return jsonify({"error": {"code": "not_found", "message": "接口不存在"}}), 404
        dist = config.frontend_dist
        candidate = (dist / asset_path).resolve()
        try:
            candidate.relative_to(dist.resolve())
        except ValueError:
            return _serve_index(config)
        if candidate.is_file():
            return send_file(candidate)
        return _serve_index(config)

    logger.info("细胞档案 CellArchive %s 启动，数据库：%s", APP_VERSION, config.db_path)
    return app


def _serve_index(config: Config):
    index_file = config.frontend_dist / "index.html"
    if index_file.is_file():
        return send_file(index_file)
    from flask import Response

    return Response(MISSING_FRONTEND_HTML, status=200, mimetype="text/html")
