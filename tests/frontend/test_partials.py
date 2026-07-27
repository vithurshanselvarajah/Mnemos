from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def fe_setup(frontend_imports, tmp_path):
    from fastapi.testclient import TestClient

    import app.models.entities
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    db_path = tmp_path / "fe.db"
    import os

    os.environ["MNEMOS_FE_DB_PATH"] = str(db_path)
    config.set_settings(None)
    set_settings(None)
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


def test_partial_inbox(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        if "unassigned" in path:
            r = mock.Mock(status_code=200)
            r.json.return_value = {
                "items": [
                    {"id": "c1", "image_url": "/api/v1/crops/c1.jpg", "score": 0.9, "det_score": 0.88},
                    {"id": "c2", "image_url": "/api/v1/crops/c2.jpg", "score": 0.8, "det_score": 0.78},
                ],
                "total": 2,
                "page": 1,
                "page_size": 24,
            }
            return r
        if "persons" in path:
            r = mock.Mock(status_code=200)
            r.json.return_value = []
            return r
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/inbox")
    assert r.status_code == 200
    assert "/backend/crops/c1.jpg" in r.text
    assert "/backend/crops/c2.jpg" in r.text


def test_partial_inbox_handles_500(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=500)
        r.json.return_value = {}
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/inbox")
    assert r.status_code == 200


def test_partial_inbox_count(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    captured = {}

    def _get_sync(path, **kw):
        captured["path"] = path
        r = mock.Mock(status_code=200)
        r.json.return_value = {"total": 5}
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/inbox-count")
    assert r.status_code == 200
    assert "5" in r.text


def test_partial_inbox_count_handles_500(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=500)
        r.json.return_value = {}
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/inbox-count")
    assert r.status_code == 200


def test_partial_reindex_status_ok(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = {
            "name": "buffalo_s",
            "loaded": True,
            "reindex_in_progress": False,
            "reindex_done": 0,
            "reindex_total": 0,
            "embedding_dim": 512,
            "det_size": 640,
        }
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/reindex-status")
    assert r.status_code == 200


def test_partial_reindex_status_fallback(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=500)
        r.json.return_value = {}
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/reindex-status")
    assert r.status_code == 200


def test_partial_provider_runtime_ok(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = {"status": "ok", "provider": "cpu", "model": "buffalo_s", "rockchip_soc": None}
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/provider-runtime")
    assert r.status_code == 200


def test_partial_provider_runtime_fallback(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=500)
        r.json.return_value = {}
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/provider-runtime")
    assert r.status_code == 200


def test_partial_backend_card_ok(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = {"status": "ok"}
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/backend-card")
    assert r.status_code == 200


def test_partial_backend_card_unreachable(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        raise RuntimeError("no backend")

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/backend-card")
    assert r.status_code == 200


def test_partial_users_requires_admin(fe_setup):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        u = User(username="op", password_hash=hash_password("password"), role=UserRole.OPERATOR.value)
        s.add(u)
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    r = tc.get("/partials/users")
    assert r.status_code == 403


def test_partial_users_list_admin(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.get("/partials/users")
    assert r.status_code == 200


def test_partial_users_create(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.post(
        "/partials/users",
        data={"username": "alice", "password": "longpassword", "role": "Operator"},
    )
    assert r.status_code == 200


def test_partial_users_create_short_password(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.post(
        "/partials/users",
        data={"username": "alice", "password": "x", "role": "Operator"},
    )
    assert r.status_code == 400


def test_partial_users_create_invalid_role(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.post(
        "/partials/users",
        data={"username": "alice", "password": "longpassword", "role": "Superuser"},
    )
    assert r.status_code == 400


def test_partial_users_create_duplicate(admin_logged_in):
    _app, tc = admin_logged_in
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="dup", password_hash=hash_password("longpassword"), role=UserRole.OPERATOR.value))
    r = tc.post(
        "/partials/users",
        data={"username": "dup", "password": "longpassword", "role": "Operator"},
    )
    assert r.status_code == 409


def test_partial_users_delete_other(admin_logged_in):
    _app, tc = admin_logged_in
    import uuid as uuid_mod

    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(
            User(
                id=uuid_mod.uuid4(),
                username="victim",
                password_hash=hash_password("longpassword"),
                role=UserRole.OPERATOR.value,
            )
        )
    r = tc.delete(f"/partials/users/{uuid_mod.uuid4()}")
    assert r.status_code == 200


def test_partial_users_delete_self_rejected(admin_logged_in):
    _app, tc = admin_logged_in
    from app.db.session import session_scope
    from app.models.entities import User

    with session_scope() as s:
        admin = s.query(User).filter(User.username == "admin").first()
        uid = admin.id
    r = tc.delete(f"/partials/users/{uid}")
    assert r.status_code == 400


def test_partial_users_delete_bad_id(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.delete("/partials/users/not-a-uuid")
    assert r.status_code == 400


def test_partial_keys_list_admin(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = [{"id": "k1", "name": "k1", "permission_level": "Identify-Only"}]
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/keys")
    assert r.status_code == 200


def test_partial_keys_create(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    captured = {}

    def _post_sync(path, json=None, **kw):
        captured["payload"] = json
        r = mock.Mock(status_code=200)
        r.text = "{}"
        return r

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.api.partials.post_sync", _post_sync)
    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.post("/partials/keys", data={"name": "mykey", "permission_level": "Identify-Only"})
    assert r.status_code == 200
    assert captured["payload"]["name"] == "mykey"


def test_partial_keys_create_missing_name(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.post("/partials/keys", data={"name": "", "permission_level": "Identify-Only"})
    assert r.status_code == 400


def test_partial_keys_revoke(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _req(method, path, **kw):
        r = mock.Mock(status_code=200)
        r.text = "{}"
        return r

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.services.backend_client.request", _req)
    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    import uuid as uuid_mod

    r = tc.post(f"/partials/keys/{uuid_mod.uuid4()}/revoke")
    assert r.status_code == 200


def test_partial_keys_delete(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _req(method, path, **kw):
        r = mock.Mock(status_code=200)
        r.text = "{}"
        return r

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.services.backend_client.request", _req)
    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    import uuid as uuid_mod

    r = tc.delete(f"/partials/keys/{uuid_mod.uuid4()}")
    assert r.status_code == 200


def test_partial_persons_list(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.get("/partials/persons")
    assert r.status_code == 200


def test_partial_persons_create(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    captured = {}

    def _post_sync(path, json=None, **kw):
        captured["payload"] = json
        r = mock.Mock(status_code=200)
        r.text = "{}"
        return r

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.api.partials.post_sync", _post_sync)
    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.post("/partials/persons", data={"name": "Alice"})
    assert r.status_code == 200
    assert captured["payload"]["name"] == "Alice"


def test_partial_persons_create_invalid_threshold(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    r = tc.post("/partials/persons", data={"name": "Alice", "custom_threshold": "not-a-number"})
    assert r.status_code == 400


def test_partial_persons_patch(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in
    captured = {}

    def _req(method, path, json=None, **kw):
        captured["payload"] = json
        r = mock.Mock(status_code=200)
        r.text = "{}"
        return r

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.services.backend_client.request", _req)
    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    import uuid as uuid_mod

    r = tc.patch(f"/partials/persons/{uuid_mod.uuid4()}", data={"name": "Bob"})
    assert r.status_code == 200
    assert captured["payload"]["name"] == "Bob"


def test_partial_persons_delete(admin_logged_in, monkeypatch):
    _app, tc = admin_logged_in

    def _req(method, path, **kw):
        r = mock.Mock(status_code=200)
        r.text = "{}"
        return r

    def _get_sync(path, **kw):
        r = mock.Mock(status_code=200)
        r.json.return_value = []
        return r

    monkeypatch.setattr("app.services.backend_client.request", _req)
    monkeypatch.setattr("app.api.partials.get_sync", _get_sync)
    import uuid as uuid_mod

    r = tc.delete(f"/partials/persons/{uuid_mod.uuid4()}")
    assert r.status_code == 200


def test_partial_settings_backend(admin_logged_in):
    _app, tc = admin_logged_in
    r = tc.get("/partials/settings/backend")
    assert r.status_code == 200
