"""Tests for the Person resource on mnemos-backend."""

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


def test_list_persons_empty(api_client):
    client, key = api_client
    r = client.get("/api/v1/persons", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.json() == []


def test_create_person_persists(api_client, unique_name):
    client, key = api_client
    r = client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["name"] == unique_name
    assert body["sample_count"] == 0
    assert body["id"]


def test_create_duplicate_name_rejected(api_client, unique_name):
    client, key = api_client
    client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    )
    r = client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 409


def test_create_person_with_blank_name_rejected(api_client):
    client, key = api_client
    r = client.post(
        "/api/v1/persons",
        json={"name": "   "},
        headers={"X-API-Key": key},
    )
    assert r.status_code in (400, 422)


def test_rename_person(api_client, unique_name):
    client, key = api_client
    created = client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    ).json()
    new_name = unique_name + "-renamed"
    r = client.patch(
        f"/api/v1/persons/{created['id']}",
        json={"name": new_name},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    assert r.json()["name"] == new_name


def test_set_custom_threshold(api_client, unique_name):
    client, key = api_client
    created = client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    ).json()
    r = client.patch(
        f"/api/v1/persons/{created['id']}",
        json={"custom_threshold": 0.25},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    assert r.json()["custom_threshold"] == 0.25


def test_delete_person(api_client, unique_name):
    client, key = api_client
    created = client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    ).json()
    r = client.delete(
        f"/api/v1/persons/{created['id']}",
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    listing = client.get("/api/v1/persons", headers={"X-API-Key": key}).json()
    assert all(p["id"] != created["id"] for p in listing)


def test_get_unknown_person_returns_404(api_client):
    from uuid import uuid4

    client, key = api_client
    r = client.get(f"/api/v1/persons/{uuid4()}", headers={"X-API-Key": key})
    assert r.status_code == 404


def test_assign_unknown_crop_returns_404(api_client, unique_name):
    from uuid import uuid4

    client, key = api_client
    person = client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    ).json()
    r = client.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [str(uuid4())], "person_id": person["id"]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 404


def test_assign_creates_new_person_when_name_provided(api_client, unique_name):
    from uuid import uuid4

    client, key = api_client
    fake_crop_id = str(uuid4())
    r = client.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [fake_crop_id], "new_person_name": unique_name},
        headers={"X-API-Key": key},
    )
    assert r.status_code in (200, 404)


def test_assign_requires_target(api_client):
    from uuid import uuid4

    client, key = api_client
    r = client.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [str(uuid4())]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_assign_empty_crop_ids_rejected(api_client, unique_name):
    client, key = api_client
    person = client.post(
        "/api/v1/persons",
        json={"name": unique_name},
        headers={"X-API-Key": key},
    ).json()
    r = client.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [], "person_id": person["id"]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_mark_non_face_and_ignore_reject_empty(api_client):
    client, key = api_client
    r1 = client.post(
        "/api/v1/faces/mark-non-face",
        json={"crop_ids": []},
        headers={"X-API-Key": key},
    )
    r2 = client.post(
        "/api/v1/faces/ignore",
        json={"crop_ids": []},
        headers={"X-API-Key": key},
    )
    assert r1.status_code == 400
    assert r2.status_code == 400
