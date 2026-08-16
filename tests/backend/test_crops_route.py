"""Tests for /api/v1/crops/{filename}."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def api_client(backend_imports, tmp_root):
    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    set_settings(config.Settings(crops_dir=str(tmp_root / "crops")))
    reset_engine()
    init_db()
    tc = TestClient(create_app())
    pair = tc.post("/api/v1/system/pair", json={"master_key": ensure_master_key(), "name": "c"})
    return tc, pair.json()["raw_key"]


def _insert_crop(tmp_root, crop_id, rel_path="abc.jpg"):
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import FaceCrop, FaceCropStatus

    (tmp_root / "crops").mkdir(parents=True, exist_ok=True)
    (tmp_root / "crops" / rel_path).write_bytes(b"\xff\xd8\xffhello")
    eng = get_engine()
    with Session(eng) as s:
        s.add(
            FaceCrop(
                id=crop_id,
                file_path=rel_path,
                bounding_box="[0,0,10,10]",
                det_score=0.9,
                status=FaceCropStatus.UNASSIGNED.value,
            )
        )
        s.commit()


def test_get_crop_returns_jpeg_bytes(api_client, tmp_root, unique_name):
    from uuid import uuid4

    cid = uuid4().hex
    rel = f"{cid}.jpg"
    _insert_crop(tmp_root, cid, rel)
    tc, key = api_client
    r = tc.get(f"/api/v1/crops/{rel}", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("image/jpeg")
    assert r.content[:3] == b"\xff\xd8\xff"


def test_get_crop_404_for_unknown_id(api_client, unique_name):
    from uuid import uuid4

    tc, key = api_client
    r = tc.get(f"/api/v1/crops/{uuid4()}.jpg", headers={"X-API-Key": key})
    assert r.status_code == 404


def test_get_crop_404_when_file_missing_on_disk(api_client, tmp_root, unique_name):
    from uuid import uuid4

    cid = uuid4().hex
    _insert_crop(tmp_root, cid, f"{cid}.jpg")
    (tmp_root / "crops" / f"{cid}.jpg").unlink()
    tc, key = api_client
    r = tc.get(f"/api/v1/crops/{cid}.jpg", headers={"X-API-Key": key})
    assert r.status_code == 404


def test_get_crop_404_for_non_uuid_filename(api_client):
    tc, key = api_client
    r = tc.get("/api/v1/crops/notauuid.jpg", headers={"X-API-Key": key})
    assert r.status_code == 404


def test_get_crop_404_for_wrong_extension(api_client):
    tc, key = api_client
    r = tc.get("/api/v1/crops/something.png", headers={"X-API-Key": key})
    assert r.status_code == 404


def test_get_crop_requires_api_key(api_client, unique_name):
    from uuid import uuid4

    tc, _ = api_client
    r = tc.get(f"/api/v1/crops/{uuid4()}.jpg")
    assert r.status_code == 401


def test_get_crop_sets_cache_control(api_client, tmp_root, unique_name):
    from uuid import uuid4

    cid = uuid4().hex
    rel = f"{cid}.jpg"
    _insert_crop(tmp_root, cid, rel)
    tc, key = api_client
    r = tc.get(f"/api/v1/crops/{rel}", headers={"X-API-Key": key})
    assert "max-age" in r.headers.get("cache-control", "")
