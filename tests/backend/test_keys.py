"""Tests for the API key management endpoints."""

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

    app = create_app()
    client = TestClient(app)
    pair = client.post(
        "/api/v1/system/pair",
        json={"master_key": ensure_master_key(), "name": "pytest"},
    )
    assert pair.status_code == 200, pair.text
    api_key = pair.json()["raw_key"]
    return client, api_key


def test_create_list_revoke_api_key(api_client, unique_name):
    client, key = api_client
    r = client.post(
        "/api/v1/keys",
        json={"name": unique_name, "permission_level": "Identify-Only"},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["raw_key"].startswith("mnemos_k_")
    assert body["api_key"]["name"] == unique_name

    r = client.get("/api/v1/keys", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert any(k["name"] == unique_name for k in r.json())

    r = client.post(
        f"/api/v1/keys/{body['api_key']['id']}/revoke",
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200

    r = client.get(
        "/api/v1/persons",
        headers={"X-API-Key": body["raw_key"]},
    )
    assert r.status_code == 401


def test_create_key_rejects_blank_name(api_client):
    client, key = api_client
    r = client.post(
        "/api/v1/keys",
        json={"name": ""},
        headers={"X-API-Key": key},
    )
    assert r.status_code in (400, 422)


def test_delete_api_key(api_client, unique_name):
    client, key = api_client
    body = client.post(
        "/api/v1/keys",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    ).json()
    r = client.delete(
        f"/api/v1/keys/{body['api_key']['id']}",
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    listing = client.get("/api/v1/keys", headers={"X-API-Key": key}).json()
    assert all(k["id"] != body["api_key"]["id"] for k in listing)
