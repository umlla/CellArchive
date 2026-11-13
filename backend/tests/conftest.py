"""pytest 公共 fixture。"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import create_app  # noqa: E402
from backend import db  # noqa: E402
from backend.config import Config  # noqa: E402


@pytest.fixture()
def tmp_path() -> Path:
    """使用工作区内的独立临时目录（避免系统临时目录的权限限制）。"""
    path = ROOT / ".test-tmp" / f"run-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.fixture()
def config(tmp_path: Path) -> Config:
    cfg = Config(
        host="127.0.0.1",
        port=0,
        debug=False,
        open_browser=False,
        db_path=tmp_path / "data" / "cell_data.db",
        backup_dir=tmp_path / "backups",
        frontend_dist=tmp_path / "dist",
        auth_enabled=False,
    )
    cfg.ensure_dirs()
    conn = db.connect(cfg.db_path)
    try:
        db.init_schema(conn)
    finally:
        conn.close()
    return cfg


@pytest.fixture()
def app(config: Config):
    application = create_app(config)
    application.config.update(TESTING=True)
    return application


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def auth_config(config: Config) -> Config:
    config.auth_enabled = True
    return config


@pytest.fixture()
def auth_app(auth_config: Config):
    application = create_app(auth_config)
    application.config.update(TESTING=True)
    return application


# --------------------------------------------------------------------------
# 常用构造助手
# --------------------------------------------------------------------------
def create_line(client, name="测试细胞", type_="永生化", interval=2, revival_date="2026-01-01",
                species=None):
    payload = {
        "name": name,
        "type": type_,
        "revival_date": revival_date,
        "default_passage_interval": interval,
        "notes": "测试",
    }
    if species is not None:
        payload["species"] = species
    response = client.post("/api/cell-lines", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def create_batch(client, line_id, **overrides):
    payload = {
        "cell_line_id": line_id,
        "revival_date": "2026-02-01",
        "initial_pd": 1.0,
        "initial_cell_count": 2.0,
        "notes": "",
    }
    payload.update(overrides)
    response = client.post("/api/batches", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()


def add_record(client, batch_id, **overrides):
    payload = {
        "batch_id": batch_id,
        "date": "2026-02-02",
        "harvested_cells": 4.0,
        "inoculum_dishes": 2,
        "per_dish_cells": 1.0,
        "status": "良好",
        "next_passage_days": 2,
        "notes": "",
    }
    payload.update(overrides)
    response = client.post("/api/records", json=payload)
    assert response.status_code == 201, response.get_json()
    return response.get_json()
