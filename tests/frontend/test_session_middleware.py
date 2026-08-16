from __future__ import annotations

import uuid
from datetime import datetime, timedelta

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
def admin_user(fe_setup):
    from app.core.auth import hash_password
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        u = User(username="admin", password_hash=hash_password("password"), role=UserRole.ADMIN.value)
        s.add(u)
        s.flush()
        return u.id, "admin"


def test_login_success_sets_cookie(fe_setup, admin_user):
    _app, tc = fe_setup
    r = tc.post("/login", data={"username": "admin", "password": "password"}, follow_redirects=False)
    assert r.status_code == 303
    assert "mnemos_sid" in tc.cookies


def test_login_wrong_password_returns_401(fe_setup, admin_user):
    _app, tc = fe_setup
    r = tc.post(
        "/login",
        data={"username": "admin", "password": "wrong"},
        follow_redirects=False,
    )
    assert r.status_code == 401


def test_logout_clears_session(fe_setup, admin_user):
    _app, tc = fe_setup
    tc.post("/login", data={"username": "admin", "password": "password"}, follow_redirects=False)
    assert "mnemos_sid" in tc.cookies
    r = tc.get("/logout", follow_redirects=False)
    assert r.status_code == 303


def test_issue_session_returns_token(fe_setup, admin_user):
    from app.core.middleware import issue_session

    user_id, _ = admin_user
    token, max_age = issue_session(user_id, remember=False)
    assert isinstance(token, str) and len(token) >= 32
    assert max_age > 0


def test_issue_session_remember_extends(fe_setup, admin_user):
    from app.core.config import settings
    from app.core.middleware import issue_session

    user_id, _ = admin_user
    _, max_age_short = issue_session(user_id, remember=False)
    _, max_age_long = issue_session(user_id, remember=True)
    assert max_age_long > max_age_short
    assert max_age_long >= settings.remember_days * 24 * 3600


def test_revoke_session_removes_token(fe_setup, admin_user):
    from app.core.middleware import issue_session, revoke_session

    user_id, _ = admin_user
    token, _ = issue_session(user_id, remember=False)
    revoke_session(token)
    revoke_session("")


def test_revoke_session_unknown_token_is_noop(fe_setup):
    from app.core.middleware import revoke_session

    revoke_session("definitely-not-a-token")


def test_require_admin_raises_for_non_admin(fe_setup):
    from fastapi import HTTPException

    from app.core.auth import hash_password
    from app.core.middleware import require_admin
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    op_id = uuid.uuid4().hex
    with session_scope() as s:
        s.add(User(id=op_id, username="op", password_hash=hash_password("op"), role=UserRole.OPERATOR.value))

    class _Req:
        class state:
            user = None

    with pytest.raises(HTTPException):
        require_admin(_Req())


def test_user_by_session_returns_none_for_expired(fe_setup, admin_user):

    from app.core.middleware import _user_by_session, issue_session

    user_id, _ = admin_user
    token, _ = issue_session(user_id, remember=False)
    from app.db.session import session_scope
    from app.models.entities import Session

    with session_scope() as s:
        row = s.query(Session).filter(Session.session_token == token).first()
        row.expires_at = datetime.utcnow() - timedelta(hours=1)
    assert _user_by_session(token) is None


def test_user_by_session_returns_user(fe_setup, admin_user):
    from app.core.middleware import _user_by_session, issue_session

    user_id, _ = admin_user
    token, _ = issue_session(user_id, remember=False)
    user = _user_by_session(token)
    assert user is not None
    assert user.username == "admin"


def test_user_by_session_returns_none_for_empty_token(fe_setup):
    from app.core.middleware import _user_by_session

    assert _user_by_session("") is None


def test_set_session_cookie_attributes(fe_setup, admin_user):
    from fastapi import Response

    from app.core.middleware import _set_session_cookie

    resp = Response()
    _set_session_cookie(resp, "tok", 60)
    set_cookie = next((v for k, v in resp.headers.items() if k.lower() == "set-cookie"), "")
    assert "mnemos_sid=tok" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "SameSite=lax" in set_cookie


def test_clear_session_cookie(fe_setup):
    from fastapi import Response

    from app.core.middleware import _clear_session_cookie

    resp = Response()
    _clear_session_cookie(resp)
    set_cookie = next((v for k, v in resp.headers.items() if k.lower() == "set-cookie"), "")
    assert "mnemos_sid" in set_cookie.lower()
    assert "max-age" in set_cookie.lower() or "expires" in set_cookie.lower()


def test_session_middleware_exempt_paths(fe_setup):
    """Test all paths listed in EXEMPT_PATHS."""
    from app.core.middleware import EXEMPT_PATHS

    for path in EXEMPT_PATHS:
        assert path.startswith("/"), f"exempt path {path!r} must start with /"
