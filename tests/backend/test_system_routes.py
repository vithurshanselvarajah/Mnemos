"""Tests for /api/v1/system/{master,pair}."""

from __future__ import annotations

import pytest


@pytest.fixture
def api_client(backend_imports):
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
    return TestClient(create_app()), ensure_master_key()


def test_master_view_requires_admin(api_client):
    client, _ = api_client
    r = client.get("/api/v1/system/master")
    assert r.status_code == 401


def test_master_view_returns_key_after_pair(api_client):
    client, master = api_client
    pair = client.post("/api/v1/system/pair", json={"master_key": master, "name": "x"})
    key = pair.json()["raw_key"]
    r = client.get("/api/v1/system/master", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json() == master


def test_master_rotate_changes_key(api_client):
    client, master = api_client
    pair = client.post("/api/v1/system/pair", json={"master_key": master, "name": "x"})
    key = pair.json()["raw_key"]
    r = client.post("/api/v1/system/master/rotate", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json() != master


def test_master_rotate_rejects_non_admin(api_client):
    client, _ = api_client
    r = client.post("/api/v1/system/master/rotate")
    assert r.status_code == 401


def test_pair_rejects_empty_master(api_client):
    client, _ = api_client
    r = client.post("/api/v1/system/pair", json={"master_key": "", "name": "x"})
    assert r.status_code in (400, 401, 422)


def test_pair_rejects_wrong_master(api_client):
    client, _ = api_client
    r = client.post("/api/v1/system/pair", json={"master_key": "wrong", "name": "x"})
    assert r.status_code in (400, 401, 403)


def test_pair_mints_full_admin_key(api_client):
    client, master = api_client
    r = client.post("/api/v1/system/pair", json={"master_key": master, "name": "Node A"})
    assert r.status_code == 200
    body = r.json()
    assert body["raw_key"].startswith("mnemos_k_")
    assert body["key_prefix"] == body["raw_key"][:8]
    me = client.get("/api/v1/persons", headers={"X-API-Key": body["raw_key"]})
    assert me.status_code == 200


def test_pair_keys_are_marked_as_pairing(backend_imports):
    import app.models.entities  # noqa: F401
    from app.core import config
    from app.core.config import set_settings
    from app.core.security import create_api_key
    from app.db.session import init_db, reset_engine

    set_settings(config.Settings())
    reset_engine()
    init_db()
    _row, _ = create_api_key("user-key", "Identify-Only", is_pairing_key=False)
    assert _row.is_pairing_key is False

    _row2, _ = create_api_key("pair-key", "Full-Admin", is_pairing_key=True)
    assert _row2.is_pairing_key is True
