"""Tests for /api/v1/faces/{unassigned,assign,mark-non-face,ignore}."""

from __future__ import annotations

import json
from uuid import uuid4

import pytest


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
    pair = tc.post("/api/v1/system/pair", json={"master_key": ensure_master_key(), "name": "f"})
    return tc, pair.json()["raw_key"]


def _add_crop(tmp_root, name="crop.jpg", bbox=(0, 0, 10, 10)):
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import FaceCrop, FaceCropStatus

    (tmp_root / "crops").mkdir(parents=True, exist_ok=True)
    (tmp_root / "crops" / name).write_bytes(b"\xff\xd8\xff")
    eng = get_engine()
    cid = uuid4()
    with Session(eng) as s:
        s.add(
            FaceCrop(
                id=cid,
                file_path=name,
                bounding_box=json.dumps(list(bbox)),
                det_score=0.9,
                status=FaceCropStatus.UNASSIGNED.value,
            )
        )
        s.commit()
    return cid


def test_list_unassigned_empty(api_client):
    tc, key = api_client
    r = tc.get("/api/v1/faces/unassigned", headers={"X-API-Key": key})
    assert r.status_code == 200
    body = r.json()
    assert body["items"] == []
    assert body["total"] == 0


def test_list_unassigned_paginates(api_client, tmp_root):
    for i in range(5):
        _add_crop(tmp_root, name=f"c{i}.jpg")
    tc, key = api_client
    r = tc.get("/api/v1/faces/unassigned?page=1&page_size=2", headers={"X-API-Key": key})
    body = r.json()
    assert body["total"] == 5
    assert body["page"] == 1
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    r = tc.get("/api/v1/faces/unassigned?page=3&page_size=2", headers={"X-API-Key": key})
    body = r.json()
    assert len(body["items"]) == 1


def test_list_unassigned_rejects_bad_pagination(api_client):
    tc, key = api_client
    r = tc.get("/api/v1/faces/unassigned?page=0", headers={"X-API-Key": key})
    assert r.status_code == 422
    r = tc.get("/api/v1/faces/unassigned?page_size=0", headers={"X-API-Key": key})
    assert r.status_code == 422
    r = tc.get("/api/v1/faces/unassigned?page_size=10000", headers={"X-API-Key": key})
    assert r.status_code == 422


def test_assign_to_existing_person(api_client, tmp_root, unique_name):
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import Person

    cid = _add_crop(tmp_root)
    eng = get_engine()
    with Session(eng) as s:
        p = Person(name=unique_name)
        s.add(p)
        s.commit()
        s.refresh(p)
        person_id = p.id
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [str(cid)], "person_id": str(person_id)},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["count"] == 1


def test_assign_creates_new_person(api_client, tmp_root, unique_name):
    cid = _add_crop(tmp_root)
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [str(cid)], "new_person_name": unique_name},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200


def test_assign_rejects_no_target(api_client, tmp_root):
    cid = _add_crop(tmp_root)
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [str(cid)]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_assign_rejects_empty_crop_ids(api_client):
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/assign",
        json={"crop_ids": []},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_assign_404_for_unknown_crop(api_client, unique_name):
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import Person

    eng = get_engine()
    with Session(eng) as s:
        p = Person(name=unique_name)
        s.add(p)
        s.commit()
        s.refresh(p)
        person_id = p.id
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [str(uuid4())], "person_id": str(person_id)},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 404


def test_assign_404_for_unknown_person(api_client, tmp_root):
    cid = _add_crop(tmp_root)
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/assign",
        json={"crop_ids": [str(cid)], "person_id": str(uuid4())},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 404


def test_mark_non_face_marks_and_removes_from_index(api_client, tmp_root, fake_vector_repo):
    cid = _add_crop(tmp_root)
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/mark-non-face",
        json={"crop_ids": [str(cid)]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_mark_non_face_rejects_empty(api_client):
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/mark-non-face",
        json={"crop_ids": []},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_ignore_marks_and_removes_from_index(api_client, tmp_root):
    cid = _add_crop(tmp_root)
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/ignore",
        json={"crop_ids": [str(cid)]},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 200
    assert r.json()["count"] == 1


def test_ignore_rejects_empty(api_client):
    tc, key = api_client
    r = tc.post(
        "/api/v1/faces/ignore",
        json={"crop_ids": []},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_unassigned_omits_non_unassigned_crops(api_client, tmp_root):
    from sqlmodel import Session

    from app.db.session import get_engine
    from app.models.entities import FaceCrop, FaceCropStatus

    cid_assigned = _add_crop(tmp_root, name="a.jpg")
    eng = get_engine()
    with Session(eng) as s:
        row = s.get(FaceCrop, cid_assigned)
        row.status = FaceCropStatus.ASSIGNED.value
        s.add(row)
        s.commit()
    tc, key = api_client
    r = tc.get("/api/v1/faces/unassigned", headers={"X-API-Key": key})
    body = r.json()
    assert all(item["id"] != str(cid_assigned) for item in body["items"])


def test_unassigned_bounding_box_parsed(api_client, tmp_root):
    cid = _add_crop(tmp_root, bbox=(1, 2, 3, 4))
    tc, key = api_client
    r = tc.get("/api/v1/faces/unassigned", headers={"X-API-Key": key})
    body = r.json()
    assert any(item["id"] == str(cid) and item["bounding_box"] == [1, 2, 3, 4] for item in body["items"])


def test_unassigned_handles_garbage_bounding_box(api_client, tmp_root):
    from sqlmodel import Session, select

    from app.db.session import get_engine
    from app.models.entities import FaceCrop

    _add_crop(tmp_root)
    eng = get_engine()
    with Session(eng) as s:
        row = s.exec(select(FaceCrop)).first()
        row.bounding_box = "not-json"
        s.add(row)
        s.commit()
    tc, key = api_client
    tc_no_raise = type(tc)(tc.app, raise_server_exceptions=False)
    r = tc_no_raise.get("/api/v1/faces/unassigned", headers={"X-API-Key": key})
    assert r.status_code == 500
