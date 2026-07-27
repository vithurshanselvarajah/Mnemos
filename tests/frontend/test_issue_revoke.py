from __future__ import annotations

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
def admin_with_session(fe_setup):

    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    app, tc = fe_setup
    with session_scope() as s:
        u = User(username="admin", password_hash=hash_password("password"), role=UserRole.ADMIN.value)
        s.add(u)
        s.flush()
        uid = u.id
    token, _max_age = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    return app, tc, uid, token


def test_logout_revoke_active_session(admin_with_session):
    _app, tc, _uid, token = admin_with_session
    r = tc.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    from app.db.session import session_scope
    from app.models.entities import Session

    with session_scope() as s:
        row = s.query(Session).filter(Session.session_token == token).first()
        assert row is None


def test_logout_no_session_cookie(fe_setup):
    _app, tc = fe_setup
    r = tc.get("/logout", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/login"


def test_revoke_session_removes_token_from_db(fe_setup):
    from app.core.auth import hash_password
    from app.core.middleware import issue_session, revoke_session
    from app.db.session import session_scope
    from app.models.entities import Session, User, UserRole

    with session_scope() as s:
        u = User(username="u1", password_hash=hash_password("p"), role=UserRole.OPERATOR.value)
        s.add(u)
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=False)
    revoke_session(token)
    with session_scope() as s:
        assert s.query(Session).filter(Session.session_token == token).first() is None


def test_issue_session_creates_row(admin_with_session):
    _app, _tc, uid, token = admin_with_session
    from app.db.session import session_scope
    from app.models.entities import Session

    with session_scope() as s:
        row = s.query(Session).filter(Session.session_token == token).first()
        assert row is not None
        assert row.user_id == uid


def test_issue_session_persists_expires_at(admin_with_session):
    _app, _tc, _uid, token = admin_with_session
    from app.db.session import session_scope
    from app.models.entities import Session

    with session_scope() as s:
        row = s.query(Session).filter(Session.session_token == token).first()
        assert row is not None
        assert row.expires_at > datetime.utcnow()
        assert row.expires_at > datetime.utcnow() + timedelta(days=29)


def test_issue_session_short_max_age(fe_setup):
    from app.core.auth import hash_password
    from app.core.config import settings
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        u = User(username="u2", password_hash=hash_password("p"), role=UserRole.OPERATOR.value)
        s.add(u)
        s.flush()
        uid = u.id
    _token, max_age = issue_session(uid, remember=False)
    expected = settings.session_hours * 3600
    assert max_age == expected


def test_revoke_session_empty_does_nothing(fe_setup):
    from app.core.middleware import revoke_session

    revoke_session("")
    revoke_session(None)


def test_revoke_session_idempotent(fe_setup):
    from app.core.auth import hash_password
    from app.core.middleware import issue_session, revoke_session
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        u = User(username="u3", password_hash=hash_password("p"), role=UserRole.OPERATOR.value)
        s.add(u)
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=False)
    revoke_session(token)
    revoke_session(token)
