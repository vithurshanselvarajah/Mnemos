from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def fe_setup(frontend_imports):
    from fastapi.testclient import TestClient

    import app.models.entities
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    app = create_app()
    return app, TestClient(app)


@pytest.fixture
def admin_logged_in(fe_setup):
    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import BackendNode, User, UserRole

    app, tc = fe_setup
    with session_scope() as s:
        u = User(username="admin", password_hash=hash_password("password"), role=UserRole.ADMIN.value)
        s.add(u)
        s.add(BackendNode(name="b", base_url="http://b:8000", api_key="k"))
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    return app, tc


def test_proxy_identify_success(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    identify_resp = mock.Mock(status_code=200, text="{}")
    identify_resp.json.return_value = {
        "unknown_faces": [{"crop_id": "abc-123", "score": 0.9, "det_score": 0.88, "file_path": "a.jpg"}],
        "recognized": [{"name": "Alice", "confidence": 0.95, "image_url": "/api/v1/crops/xyz.jpg"}],
        "unknown_count": 1,
        "duplicates_skipped": 0,
    }
    persons_resp = mock.Mock(status_code=200, text="[]")
    persons_resp.json.return_value = []

    def _post_sync(path, files=None, **kw):
        return identify_resp

    def _get_sync(path, **kw):
        return persons_resp

    monkeypatch.setattr("app.api.backend_proxy.post_sync", _post_sync)
    monkeypatch.setattr("app.api.backend_proxy.get_sync", _get_sync)
    r = tc.post(
        "/backend/identify",
        files={"file": ("x.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 100, "image/png")},
    )
    assert r.status_code == 200
    assert "/backend/crops/abc-123.jpg" in r.text
    assert "/backend/crops/xyz.jpg" in r.text


def test_proxy_identify_backend_error_renders_partial(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _post_sync(path, files=None, **kw):
        r = mock.Mock(status_code=500)
        r.text = "internal"
        return r

    monkeypatch.setattr("app.api.backend_proxy.post_sync", _post_sync)
    r = tc.post(
        "/backend/identify",
        files={"file": ("x.png", b"\x00" * 10, "image/png")},
    )
    assert r.status_code == 500
    assert "500" in r.text or "error" in r.text.lower()


def test_proxy_identify_connection_error_returns_502(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _post_sync(path, files=None, **kw):
        raise RuntimeError("net down")

    monkeypatch.setattr("app.api.backend_proxy.post_sync", _post_sync)
    r = tc.post(
        "/backend/identify",
        files={"file": ("x.png", b"\x00" * 10, "image/png")},
    )
    assert r.status_code == 502


def test_proxy_assign_admin_only(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    resp = mock.Mock(status_code=200, content=b"{}")

    def _post_sync(path, json=None, **kw):
        return resp

    monkeypatch.setattr("app.api.backend_proxy.post_sync", _post_sync)
    r = tc.post(
        "/backend/faces/assign",
        json={"crop_ids": ["abc"], "person_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert r.status_code == 200


def test_proxy_assign_non_admin_forbidden(fe_setup, monkeypatch):
    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import BackendNode, User, UserRole

    _app, tc = fe_setup
    with session_scope() as s:
        u = User(username="op", password_hash=hash_password("password"), role=UserRole.OPERATOR.value)
        s.add(u)
        s.add(BackendNode(name="b", base_url="http://b:8000", api_key="k"))
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    r = tc.post(
        "/backend/faces/assign",
        json={"crop_ids": ["abc"], "person_id": "00000000-0000-0000-0000-000000000001"},
    )
    assert r.status_code == 403


def test_proxy_assign_invalid_uuid_returns_400(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.post(
        "/backend/faces/assign",
        data={"crop_ids_json": '["abc"]', "target": "not-a-uuid"},
    )
    assert r.status_code == 400


def test_proxy_assign_new_person_missing_name(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.post(
        "/backend/faces/assign",
        data={"crop_ids_json": '["abc"]', "target": "new"},
    )
    assert r.status_code == 400


def test_proxy_assign_new_person_with_name(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    resp = mock.Mock(status_code=200, content=b"{}")

    captured = {}

    def _post_sync(path, json=None, **kw):
        captured["payload"] = json
        return resp

    monkeypatch.setattr("app.api.backend_proxy.post_sync", _post_sync)
    r = tc.post(
        "/backend/faces/assign",
        data={"crop_ids_json": '["abc"]', "target": "new", "new_person_name": "Bob"},
    )
    assert r.status_code == 200
    assert captured["payload"]["new_person_name"] == "Bob"


def test_proxy_assign_invalid_crop_ids_json(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.post(
        "/backend/faces/assign",
        data={"crop_ids_json": "not json", "target": "new", "new_person_name": "X"},
    )
    assert r.status_code == 400


def test_proxy_identify_handles_missing_unknown_faces(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    identify_resp = mock.Mock(status_code=200, text="{}")
    identify_resp.json.return_value = {
        "recognized": [],
        "unknown_count": 0,
        "duplicates_skipped": 0,
    }
    persons_resp = mock.Mock(status_code=200, text="[]")
    persons_resp.json.return_value = []
    monkeypatch.setattr("app.api.backend_proxy.post_sync", lambda *a, **kw: identify_resp)
    monkeypatch.setattr("app.api.backend_proxy.get_sync", lambda *a, **kw: persons_resp)
    r = tc.post(
        "/backend/identify",
        files={"file": ("x.png", b"\x00" * 10, "image/png")},
    )
    assert r.status_code == 200


def test_proxy_identify_persons_unavailable_falls_back(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    identify_resp = mock.Mock(status_code=200, text="{}")
    identify_resp.json.return_value = {
        "recognized": [],
        "unknown_count": 0,
        "duplicates_skipped": 0,
    }
    persons_resp = mock.Mock(status_code=500, text="err")
    persons_resp.json.side_effect = Exception("oops")
    monkeypatch.setattr("app.api.backend_proxy.post_sync", lambda *a, **kw: identify_resp)
    monkeypatch.setattr("app.api.backend_proxy.get_sync", lambda *a, **kw: persons_resp)
    r = tc.post(
        "/backend/identify",
        files={"file": ("x.png", b"\x00" * 10, "image/png")},
    )
    assert r.status_code == 200


def test_is_admin_helper_for_non_admin(fe_setup):

    from app.api.backend_proxy import _is_admin

    class _Req:
        class state:
            user = None

    assert _is_admin(_Req()) is False


def test_is_admin_helper_for_admin(fe_setup):
    from app.api.backend_proxy import _is_admin

    class _User:
        role = "Admin"

    class _Req:
        class state:
            user = _User()

    assert _is_admin(_Req()) is True
