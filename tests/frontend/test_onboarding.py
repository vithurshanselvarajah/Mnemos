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


def test_onboarding_admin_step_when_no_admin(fe_setup):
    _app, tc = fe_setup
    r = tc.get("/onboarding")
    assert "admin" in r.text.lower()


def test_onboarding_create_admin(fe_setup):
    _app, tc = fe_setup
    r = tc.post(
        "/onboarding/admin",
        data={"username": "admin", "password": "longpassword", "password_confirm": "longpassword"},
        follow_redirects=False,
    )
    assert r.status_code == 303


def test_onboarding_password_mismatch(fe_setup):
    _app, tc = fe_setup
    r = tc.post(
        "/onboarding/admin",
        data={"username": "admin", "password": "longpassword", "password_confirm": "different"},
    )
    assert r.status_code == 400


def test_onboarding_password_too_short(fe_setup):
    _app, tc = fe_setup
    r = tc.post(
        "/onboarding/admin",
        data={"username": "admin", "password": "x", "password_confirm": "x"},
    )
    assert r.status_code == 400


def test_onboarding_admin_already_exists(fe_setup):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password("longpassword"), role=UserRole.ADMIN.value))
    r = tc.post(
        "/onboarding/admin",
        data={"username": "admin", "password": "longpassword", "password_confirm": "longpassword"},
    )
    assert r.status_code == 400


def test_onboarding_backend_success(fe_setup, monkeypatch):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password("longpassword"), role=UserRole.ADMIN.value))

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"raw_key": "test-key-12345"}

    monkeypatch.setattr(
        "httpx2.Client",
        lambda *a, **kw: mock.MagicMock(
            __enter__=lambda s: s,
            __exit__=lambda s, *a: False,
            post=mock.Mock(return_value=_Resp()),
        ),
    )
    r = tc.post(
        "/onboarding/backend",
        data={"base_url": "http://b:8000", "master_key": "master", "name": "b"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    from app.db.session import session_scope as ss
    from app.models.entities import BackendNode

    with ss() as s:
        nodes = s.query(BackendNode).all()
        assert len(nodes) == 1
        assert nodes[0].api_key == "test-key-12345"


def test_onboarding_backend_pairing_failed(fe_setup, monkeypatch):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password("longpassword"), role=UserRole.ADMIN.value))

    class _Resp:
        status_code = 401
        text = '{"detail": "bad master key"}'

        def json(self):
            return {"detail": "bad master key"}

    monkeypatch.setattr(
        "httpx2.Client",
        lambda *a, **kw: mock.MagicMock(
            __enter__=lambda s: s,
            __exit__=lambda s, *a: False,
            post=mock.Mock(return_value=_Resp()),
        ),
    )
    r = tc.post(
        "/onboarding/backend",
        data={"base_url": "http://b:8000", "master_key": "wrong", "name": "b"},
    )
    assert r.status_code == 400


def test_onboarding_backend_pairing_unreachable(fe_setup, monkeypatch):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password("longpassword"), role=UserRole.ADMIN.value))

    def _explode(*a, **kw):
        raise RuntimeError("dns down")

    monkeypatch.setattr("httpx2.Client", _explode)
    r = tc.post(
        "/onboarding/backend",
        data={"base_url": "http://b:8000", "master_key": "wrong", "name": "b"},
    )
    assert r.status_code == 400


def test_onboarding_backend_replaces_existing_node(fe_setup, monkeypatch):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import BackendNode, User, UserRole

    with session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password("longpassword"), role=UserRole.ADMIN.value))
        s.add(BackendNode(name="old", base_url="http://old", api_key="old"))

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {"raw_key": "new-key"}

    monkeypatch.setattr(
        "httpx2.Client",
        lambda *a, **kw: mock.MagicMock(
            __enter__=lambda s: s,
            __exit__=lambda s, *a: False,
            post=mock.Mock(return_value=_Resp()),
        ),
    )
    tc.post(
        "/onboarding/backend",
        data={"base_url": "http://new:8000", "master_key": "master", "name": "new"},
        follow_redirects=False,
    )
    with session_scope() as s:
        nodes = s.query(BackendNode).all()
        assert len(nodes) == 1
        assert nodes[0].name == "new"
        assert nodes[0].api_key == "new-key"


def test_partial_onboarding_warmup_initial(fe_setup):
    _app, tc = fe_setup
    r = tc.get("/partials/onboarding-warmup")
    assert r.status_code == 200
    body = r.json()
    assert body["done"] is False
    assert body["running"] is False
    assert body["error"] is None


def test_onboarding_done_step(fe_setup):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import BackendNode, User, UserRole

    with session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password("longpassword"), role=UserRole.ADMIN.value))
        s.add(BackendNode(name="b", base_url="http://b:8000", api_key="k"))
    r = tc.get("/onboarding")
    assert r.status_code == 200


def test_login_get_redirects_when_authed(fe_setup):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        u = User(username="admin", password_hash=hash_password("password"), role=UserRole.ADMIN.value)
        s.add(u)
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    r = tc.get("/login?next=/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


def test_login_post_invalid_creds(fe_setup):
    _app, tc = fe_setup
    r = tc.post("/login", data={"username": "x", "password": "y"}, follow_redirects=False)
    assert r.status_code == 401


def test_login_post_success_sets_cookie(fe_setup):
    _app, tc = fe_setup
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="admin", password_hash=hash_password("password"), role=UserRole.ADMIN.value))
    r = tc.post(
        "/login",
        data={"username": "admin", "password": "password", "remember_me": "on"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "mnemos_sid" in tc.cookies
