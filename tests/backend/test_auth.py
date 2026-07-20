"""Authentication middleware: API key, master key, rate limiting."""

from __future__ import annotations

import pytest


@pytest.fixture
def backend_app(backend_imports):
    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key, rotate_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    master = ensure_master_key()
    app = create_app()
    return {
        "app": app,
        "master_key": master,
        "rotate_master_key": rotate_master_key,
        "ensure_master_key": ensure_master_key,
    }


def test_master_key_round_trip(backend_imports):
    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key, rotate_master_key, view_master_key
    from app.db.session import init_db, reset_engine

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()

    first = ensure_master_key()
    assert first.startswith("mnemos_master_")
    assert ensure_master_key() == first
    new_key = rotate_master_key()
    assert new_key != first
    assert view_master_key() == new_key


def test_healthz_reports_db_state(backend_app):
    from fastapi.testclient import TestClient

    client = TestClient(backend_app["app"])
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] in ("ok", "degraded")
    assert "model" in body
    assert body["version"]


def test_pair_endpoint_exchanges_master_key_for_api_key(backend_app):
    from fastapi.testclient import TestClient

    client = TestClient(backend_app["app"])
    r = client.post(
        "/api/v1/system/pair",
        json={"master_key": backend_app["master_key"], "name": "Test Node"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["raw_key"].startswith("mnemos_k_")
    assert body["key_prefix"] == body["raw_key"][:8]


def test_pair_with_wrong_master_key_rejected(backend_app):
    from fastapi.testclient import TestClient

    client = TestClient(backend_app["app"])
    r = client.post(
        "/api/v1/system/pair",
        json={"master_key": "definitely-wrong", "name": "Bad Node"},
    )
    assert r.status_code in (401, 400, 403)


def test_api_key_required_for_protected_endpoints(backend_app):
    from fastapi.testclient import TestClient

    client = TestClient(backend_app["app"])
    r = client.get("/api/v1/persons")
    assert r.status_code == 401


def test_create_and_use_api_key(backend_app):
    from fastapi.testclient import TestClient

    client = TestClient(backend_app["app"])
    r = client.post(
        "/api/v1/system/pair",
        json={"master_key": backend_app["master_key"], "name": "Test Node"},
    )
    api_key = r.json()["raw_key"]

    r = client.get("/api/v1/persons", headers={"X-API-Key": api_key})
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_revoked_api_key_rejected(backend_app):
    from fastapi.testclient import TestClient

    client = TestClient(backend_app["app"])
    r = client.post(
        "/api/v1/system/pair",
        json={"master_key": backend_app["master_key"], "name": "Test Node"},
    )
    api_key = r.json()["raw_key"]
    key_id = r.json()["api_key_id"]

    r = client.post(
        f"/api/v1/keys/{key_id}/revoke",
        headers={"X-API-Key": api_key},
    )
    assert r.status_code == 200

    r = client.get("/api/v1/persons", headers={"X-API-Key": api_key})
    assert r.status_code == 401


def test_rate_limiter_is_initialized(backend_app):
    from app.core.middleware import APIKeyAuthMiddleware

    middleware = APIKeyAuthMiddleware(backend_app["app"])
    assert middleware._limiter.max_per_min == 600
