"""Tests for /api/v1/identify (multipart image upload)."""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image


def _png_bytes(size=(128, 128), color=(120, 120, 120)):
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def api_client(backend_imports, mock_engine, fake_vector_repo, tmp_root):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app
    from app.services.engine import InsightFaceEngine

    set_settings(config.Settings(crops_dir=str(tmp_root / "crops")))
    reset_engine()
    init_db()
    mock_engine()
    InsightFaceEngine.reset()
    tc = TestClient(create_app())
    pair = tc.post("/api/v1/system/pair", json={"master_key": ensure_master_key(), "name": "i"})
    return tc, pair.json()["raw_key"]


def test_identify_rejects_empty_upload(api_client):
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.jpg", b"", "image/jpeg")},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_identify_rejects_bad_image(api_client):
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.jpg", b"not an image at all", "image/jpeg")},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_identify_with_no_detections(api_client, mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(detections=[])
    InsightFaceEngine.reset()
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recognized"] == []
    assert body["unknown_count"] == 0
    assert body["duplicates_skipped"] == 0


def test_identify_unknown_face_persists_and_emits_event(api_client, mock_engine, tmp_root):
    from app.core.config import current_settings
    from app.services.engine import InsightFaceEngine

    mock_engine(
        detections=[
            {
                "bbox": (10.0, 20.0, 60.0, 90.0),
                "score": 0.95,
                "embedding": np.zeros(512, dtype=np.float32),
            }
        ]
    )
    InsightFaceEngine.reset()
    tc, key = api_client
    crops_dir = current_settings().crops_dir
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["unknown_count"] == 1
    crop_id = body["unknown_faces"][0]["crop_id"]
    assert body["unknown_faces"][0]["det_score"] == pytest.approx(0.95)
    assert body["unknown_faces"][0]["bounding_box"]["x1"] == 10.0
    assert body["unknown_faces"][0]["image_url"] == f"/api/v1/crops/{crop_id}.jpg"
    from sqlmodel import select

    from app.db.session import session_scope
    from app.models.entities import FaceCrop

    with session_scope() as s:
        rows = s.execute(select(FaceCrop)).scalars().all()
    assert any(str(r.id) == crop_id for r in rows)
    crops_path = type(tmp_root)(crops_dir)
    assert any((crops_path / r.file_path).is_file() for r in rows)


def test_identify_recognized_face_with_match(api_client, mock_engine, fake_vector_repo, unique_name):
    from app.services.engine import InsightFaceEngine

    fake_vector_repo.search_results = [
        [
            {
                "person_id": "11111111-1111-1111-1111-111111111111",
                "crop_id": "22222222-2222-2222-2222-222222222222",
                "is_averaged": True,
                "similarity": 0.99,
            }
        ]
    ]
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import Person

    eng = get_engine()
    with Session(eng) as s:
        p = Person(name=unique_name)
        s.add(p)
        s.commit()
        s.refresh(p)
        real_pid = str(p.id)

    fake_vector_repo.search_results = [
        [
            {
                "person_id": real_pid,
                "crop_id": "22222222-2222-2222-2222-222222222222",
                "is_averaged": True,
                "similarity": 0.99,
            }
        ]
    ]

    mock_engine(
        detections=[
            {
                "bbox": (10.0, 20.0, 60.0, 90.0),
                "score": 0.95,
                "embedding": np.zeros(512, dtype=np.float32),
            }
        ]
    )
    InsightFaceEngine.reset()
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["recognized"]
    assert body["recognized"][0]["name"] == unique_name
    assert body["recognized"][0]["confidence"] == pytest.approx(0.99)
    assert body["recognized"][0]["image_is_data"] is True


def test_identify_skips_small_detections(api_client, mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(
        detections=[
            {
                "bbox": (10.0, 20.0, 12.0, 22.0),
                "score": 0.5,
                "embedding": np.zeros(512, dtype=np.float32),
            }
        ]
    )
    InsightFaceEngine.reset()
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["unknown_count"] == 0


def test_identify_dedupes_within_request(api_client, mock_engine):
    from app.services.engine import InsightFaceEngine

    rng = np.random.default_rng(42)
    emb = rng.standard_normal(512).astype(np.float32)
    emb = emb / float(np.linalg.norm(emb))
    det = {"bbox": (10.0, 20.0, 60.0, 90.0), "score": 0.95, "embedding": emb.copy()}
    mock_engine(detections=[det, {"bbox": (10.0, 20.0, 60.0, 90.0), "score": 0.95, "embedding": emb.copy()}])
    InsightFaceEngine.reset()
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        headers={"X-API-Key": key},
    )
    body = r.json()
    assert body["unknown_count"] == 1


def test_identify_requires_api_key(api_client):
    tc, _ = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
    )
    assert r.status_code == 401


def test_identify_uses_custom_threshold(api_client, mock_engine, fake_vector_repo, unique_name):
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import Person
    from app.services.engine import InsightFaceEngine

    eng = get_engine()
    with Session(eng) as s:
        p = Person(name=unique_name, custom_threshold=0.5)
        s.add(p)
        s.commit()
        s.refresh(p)
        real_pid = str(p.id)

    fake_vector_repo.search_results = [
        [
            {
                "person_id": real_pid,
                "crop_id": "22222222-2222-2222-2222-222222222222",
                "is_averaged": True,
                "similarity": 0.6,
            }
        ]
    ]
    mock_engine(
        detections=[
            {
                "bbox": (10.0, 20.0, 60.0, 90.0),
                "score": 0.95,
                "embedding": np.zeros(512, dtype=np.float32),
            }
        ]
    )
    InsightFaceEngine.reset()
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        headers={"X-API-Key": key},
    )
    body = r.json()
    assert body["recognized"]


def test_identify_does_not_match_below_threshold(api_client, mock_engine, fake_vector_repo, unique_name):
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import Person
    from app.services.engine import InsightFaceEngine

    eng = get_engine()
    with Session(eng) as s:
        p = Person(name=unique_name)
        s.add(p)
        s.commit()
        s.refresh(p)
        real_pid = str(p.id)

    fake_vector_repo.search_results = [
        [
            {
                "person_id": real_pid,
                "crop_id": "22222222-2222-2222-2222-222222222222",
                "is_averaged": True,
                "similarity": 0.3,
            }
        ]
    ]
    mock_engine(
        detections=[
            {
                "bbox": (10.0, 20.0, 60.0, 90.0),
                "score": 0.95,
                "embedding": np.zeros(512, dtype=np.float32),
            }
        ]
    )
    InsightFaceEngine.reset()
    tc, key = api_client
    r = tc.post(
        "/api/v1/identify",
        files={"file": ("x.png", _png_bytes(), "image/png")},
        headers={"X-API-Key": key},
    )
    body = r.json()
    assert body["recognized"] == []
    assert body["unknown_count"] == 1
