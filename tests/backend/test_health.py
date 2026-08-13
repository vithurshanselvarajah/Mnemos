"""Tests for the /healthz endpoint."""

from __future__ import annotations

import pytest


@pytest.fixture
def client(backend_imports, mock_engine, fake_vector_repo):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    app = create_app()
    tc = TestClient(app)
    pair = tc.post("/api/v1/system/pair", json={"master_key": ensure_master_key(), "name": "h"})
    key = pair.json()["raw_key"]
    return tc, key


def test_healthz_reports_ok_when_loaded(client, mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(active_providers=["CPUExecutionProvider"], loaded=True)
    InsightFaceEngine.reset()
    tc, key = client
    r = tc.get("/healthz", headers={"X-API-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "version" in body
    assert "model" in body


def test_healthz_reports_degraded_when_engine_unloaded(client, mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(loaded=False)
    InsightFaceEngine.reset()
    tc, key = client
    r = tc.get("/healthz", headers={"X-API-Key": key})
    body = r.json()
    assert body["status"] == "degraded"


def test_healthz_reports_degraded_when_vector_down(client, fake_vector_repo):
    fake_vector_repo.ping_returns = False
    tc, key = client
    r = tc.get("/healthz", headers={"X-API-Key": key})
    body = r.json()
    assert body["status"] == "degraded"
    assert body["vector_db"] is False


def test_healthz_reports_provider_field(client):
    tc, key = client
    r = tc.get("/healthz", headers={"X-API-Key": key})
    body = r.json()
    assert body["provider"] in ("cpu", "nvidia", "rockchip")
    assert body["rockchip_soc"] is None or isinstance(body["rockchip_soc"], str)


def test_healthz_nvidia_block_only_when_nvidia(backend_imports, monkeypatch):
    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app
    from app.providers import nvidia as nvidia_mod
    from app.services import engine as engine_mod, vector_repo

    s = config.Settings(provider="nvidia")
    set_settings(s)
    config.set_settings(s)
    reset_engine()
    init_db()

    info = {
        "onnxruntime_available": True,
        "cuda_available": True,
        "device_count": 1,
        "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "active_providers": ["CUDAExecutionProvider"],
        "last_error": None,
    }
    monkeypatch.setattr(nvidia_mod, "detect_cuda_provider", lambda: info)

    def _loader(*_a, **_kw):
        class Inner:
            active_providers = ["CUDAExecutionProvider"]
            last_error = None

            def is_loaded(self_inner):
                return True

            def detect(self_inner, *_a, **_kw):
                return []

            def switch_model(self_inner, *_a, **_kw):
                return None

            def warmup(self_inner):
                return True

        return Inner()

    monkeypatch.setattr(engine_mod, "_load_provider", _loader)
    monkeypatch.setattr(vector_repo, "ping", lambda: True)
    engine_mod.InsightFaceEngine.reset()

    from fastapi.testclient import TestClient

    tc = TestClient(create_app())
    pair = tc.post("/api/v1/system/pair", json={"master_key": ensure_master_key(), "name": "h"})
    key = pair.json()["raw_key"]
    r = tc.get("/healthz", headers={"X-API-Key": key})
    body = r.json()
    assert body["provider"] == "nvidia"
    assert body["nvidia"] is not None
    assert body["nvidia"]["cuda_available"] is True
    engine_mod.InsightFaceEngine.reset()
    set_settings(None)


def test_healthz_reindex_fields_present(client):
    tc, key = client
    r = tc.get("/healthz", headers={"X-API-Key": key})
    body = r.json()
    assert "reindex_in_progress" in body
    assert "reindex_done" in body
    assert "reindex_total" in body


def test_healthz_does_not_require_api_key(backend_imports, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    s = config.Settings()
    set_settings(s)
    config.set_settings(s)
    reset_engine()
    init_db()
    tc = TestClient(create_app())
    r = tc.get("/healthz")
    assert r.status_code == 200


def test_healthz_validates_schema(client):
    from app.schemas.dto import HealthOut

    tc, key = client
    r = tc.get("/healthz", headers={"X-API-Key": key})
    HealthOut.model_validate(r.json())
