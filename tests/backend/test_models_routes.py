"""Tests for /api/v1/models/*."""

from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def api_client(backend_imports, mock_engine, fake_vector_repo):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app
    from app.services.engine import InsightFaceEngine
    from app.services.reindex import state

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    mock_engine()
    InsightFaceEngine.reset()
    state.running = False
    tc = TestClient(create_app())
    pair = tc.post("/api/v1/system/pair", json={"master_key": ensure_master_key(), "name": "m"})
    return tc, pair.json()["raw_key"]


def test_get_active_model_info(api_client):
    tc, key = api_client
    r = tc.get("/api/v1/models", headers={"X-API-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "buffalo_s"
    assert body["embedding_dim"] == 512
    assert body["det_size"] == 640


def test_warmup_already_loaded(api_client, mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(loaded=True)
    InsightFaceEngine.reset()
    e = InsightFaceEngine.current()
    e.warmup()
    tc, key = api_client
    r = tc.get("/api/v1/models/warmup", headers={"X-API-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["already_loaded"] is True
    assert body["loaded"] is True


def test_warmup_kicks_off_background(api_client, mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(loaded=False)
    InsightFaceEngine.reset()

    with mock.patch("app.api.models_routes.start_warmup") as m:
        m.return_value = True
        tc, key = api_client
        r = tc.get("/api/v1/models/warmup", headers={"X-API-Key": key})
        assert r.status_code == 200
        body = r.json()
        assert body["already_loaded"] is False
        assert m.called


def test_switch_model_rejects_unknown(api_client):
    tc, key = api_client
    r = tc.post("/api/v1/models/switch", json={"name": "totally-fake"}, headers={"X-API-Key": key})
    assert r.status_code in (400, 422)


def test_switch_model_rejects_empty_name(api_client):
    tc, key = api_client
    r = tc.post("/api/v1/models/switch", json={"name": ""}, headers={"X-API-Key": key})
    assert r.status_code in (400, 422)


def test_switch_model_409_when_reindex_running(api_client):
    from app.services.reindex import state

    state.running = True
    try:
        with mock.patch("app.api.models_routes.available_models") as m:
            from dataclasses import dataclass

            @dataclass
            class V:
                name: str = "buffalo_s"
                kind: str = "standard"
                artifacts: tuple = ()

            m.return_value = [V()]
            tc, key = api_client
            r = tc.post(
                "/api/v1/models/switch",
                json={"name": "buffalo_s"},
                headers={"X-API-Key": key},
            )
            assert r.status_code == 409
    finally:
        state.running = False


def test_switch_model_kicks_off_reindex(api_client):
    from dataclasses import dataclass

    from app.services.reindex import state

    @dataclass
    class V:
        name: str = "buffalo_s"
        kind: str = "standard"
        artifacts: tuple = ()

    with mock.patch("app.api.models_routes.available_models", return_value=[V()]):
        with mock.patch("app.api.models_routes.start_reindex") as m:
            m.return_value = True
            tc, key = api_client
            r = tc.post(
                "/api/v1/models/switch",
                json={"name": "buffalo_s"},
                headers={"X-API-Key": key},
            )
            assert r.status_code == 200
            assert m.called
            state.running = False


def test_available_models_returns_list(api_client):
    tc, key = api_client
    r = tc.get("/api/v1/models/available", headers={"X-API-Key": key})
    assert r.status_code in (200, 502)


def test_available_models_502_on_manifest_error(api_client):
    from app.api import models_routes

    tc, key = api_client
    tc_no_raise = type(tc)(tc.app, raise_server_exceptions=False)
    with mock.patch.object(models_routes, "available_models", side_effect=RuntimeError("net down")):
        r = tc_no_raise.get("/api/v1/models/available", headers={"X-API-Key": key})
        assert r.status_code in (500, 502)


def test_models_routes_require_admin(api_client):
    from app.core import config
    from app.core.config import set_settings
    from app.core.security import create_api_key

    set_settings(config.Settings())
    _row, raw = create_api_key("io", "Identify-Only")
    tc, _ = api_client
    r = tc.post("/api/v1/models/switch", json={"name": "buffalo_s"}, headers={"X-API-Key": raw})
    assert r.status_code == 403
