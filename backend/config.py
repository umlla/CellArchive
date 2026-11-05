"""应用配置：路径、端口、认证开关。

配置查找顺序（后者覆盖前者）：
1. 内置默认值
2. 项目根目录 config.json
3. 环境变量 CELLTRACKER_* 
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

APP_VERSION = "4.0.0"
SCHEMA_VERSION = 1

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULT_CONFIG: dict[str, Any] = {
    "host": "0.0.0.0",
    "port": 18600,
    "debug": False,
    "open_browser": True,
    "database": "data/cell_data.db",
    "backup_dir": "backups",
    "frontend_dist": "frontend/dist",
    "auth": {
        "enabled": False,
        "session_days": 30,
        # 首次开启认证时自动创建的账号（请登录后立即改密码）
        "bootstrap_username": "admin",
        "bootstrap_password": "celltracker",
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _resolve(path_str: str) -> Path:
    path = Path(os.path.expanduser(str(path_str)))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


@dataclass
class Config:
    host: str = "0.0.0.0"
    port: int = 18600
    debug: bool = False
    open_browser: bool = True
    db_path: Path = field(default_factory=lambda: PROJECT_ROOT / "data" / "cell_data.db")
    backup_dir: Path = field(default_factory=lambda: PROJECT_ROOT / "backups")
    frontend_dist: Path = field(default_factory=lambda: PROJECT_ROOT / "frontend" / "dist")
    auth_enabled: bool = False
    session_days: int = 30
    bootstrap_username: str = "admin"
    bootstrap_password: str = "celltracker"
    config_path: Path = field(default_factory=lambda: PROJECT_ROOT / "config.json")
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "Config":
        path = Path(config_path) if config_path else Path(
            os.environ.get("CELLTRACKER_CONFIG", PROJECT_ROOT / "config.json")
        )
        merged = dict(DEFAULT_CONFIG)
        if path.exists():
            try:
                # utf-8-sig 兼容记事本等编辑器可能写入的 BOM
                merged = _deep_merge(merged, json.loads(path.read_text(encoding="utf-8-sig")))
            except (OSError, ValueError) as exc:  # 配置损坏时不阻塞启动
                print(f"[config] 警告：无法读取 {path}：{exc}，使用默认配置")

        auth = merged.get("auth") or {}
        cfg = cls(
            host=str(os.environ.get("CELLTRACKER_HOST", merged.get("host", "0.0.0.0"))),
            port=int(os.environ.get("CELLTRACKER_PORT", merged.get("port", 18600))),
            debug=bool(merged.get("debug", False)),
            open_browser=bool(merged.get("open_browser", True)),
            db_path=_resolve(os.environ.get("CELLTRACKER_DB", merged.get("database", "data/cell_data.db"))),
            backup_dir=_resolve(os.environ.get("CELLTRACKER_BACKUP_DIR", merged.get("backup_dir", "backups"))),
            frontend_dist=_resolve(merged.get("frontend_dist", "frontend/dist")),
            auth_enabled=bool(auth.get("enabled", False)),
            session_days=int(auth.get("session_days", 30)),
            bootstrap_username=str(auth.get("bootstrap_username", "admin")),
            bootstrap_password=str(auth.get("bootstrap_password", "celltracker")),
            config_path=path.resolve(),
            raw=merged,
        )
        return cfg

    # ---------- 便捷属性 ----------
    @property
    def api_prefix(self) -> str:
        return "/api"

    def ensure_dirs(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "app_version": APP_VERSION,
            "schema_version": SCHEMA_VERSION,
            "database": str(self.db_path),
            "backup_dir": str(self.backup_dir),
            "auth": {
                "enabled": self.auth_enabled,
                "session_days": self.session_days,
            },
            "frontend_built": (self.frontend_dist / "index.html").exists(),
        }
