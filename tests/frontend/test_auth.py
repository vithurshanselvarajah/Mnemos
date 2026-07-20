"""Tests for the session middleware, login, and protected routes."""

from __future__ import annotations

import pytest


@pytest.fixture
def fe_client(frontend_imports):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    app = create_app()
    return TestClient(app)


def test_unauthenticated_get_to_protected_page_redirects(fe_client):
    r = fe_client.get("/inbox", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_unauthenticated_get_to_json_endpoint_returns_401(fe_client):
    r = fe_client.get("/backend/persons")
    assert r.status_code == 401
    assert r.json() == {"detail": "Auth required"}


def test_static_assets_are_exempt(fe_client):
    r = fe_client.get("/static/css/app.css", follow_redirects=False)
    assert r.status_code in (200, 404)


def test_healthz_is_exempt(fe_client):
    r = fe_client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert "status" in body
    assert "user" in body
    assert body["user"] is None


def test_onboarding_warmup_partial_is_exempt(fe_client):
    r = fe_client.get("/partials/onboarding-warmup", follow_redirects=False)
    assert r.status_code == 200
    body = r.json()
    assert "done" in body
    assert "running" in body
    assert "error" in body


def test_root_redirects_to_login_when_admin_exists_but_user_anonymous(frontend_imports):
    from app.core import config
    from app.core.auth import hash_password
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine, session_scope
    from app.models.entities import User, UserRole

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()

    with session_scope() as s:
        s.add(
            User(
                username="admin",
                password_hash=hash_password("admin-pass-1234"),
                role=UserRole.ADMIN.value,
            )
        )

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    r = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_root_redirects_to_onboarding_when_no_admin(frontend_imports):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    client = TestClient(create_app())
    r = client.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_login_with_valid_credentials_issues_session(frontend_imports):
    from app.core import config
    from app.core.auth import hash_password
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine, session_scope
    from app.models.entities import User, UserRole

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()

    with session_scope() as s:
        s.add(
            User(
                username="admin",
                password_hash=hash_password("admin-pass-1234"),
                role=UserRole.ADMIN.value,
            )
        )

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    r = client.post(
        "/login",
        data={
            "username": "admin",
            "password": "admin-pass-1234",
            "next": "/dashboard",
        },
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert "mnemos_sid" in r.cookies or "set-cookie" in {k.lower() for k in r.headers}


def test_login_with_invalid_credentials_renders_error(frontend_imports):
    from app.core import config
    from app.core.auth import hash_password
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine, session_scope
    from app.models.entities import User, UserRole

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()

    with session_scope() as s:
        s.add(
            User(
                username="admin",
                password_hash=hash_password("admin-pass-1234"),
                role=UserRole.ADMIN.value,
            )
        )

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    r = client.post(
        "/login",
        data={"username": "admin", "password": "wrong", "next": "/dashboard"},
    )
    assert r.status_code == 401
    assert "Invalid username or password" in r.text


def test_logged_in_user_can_access_dashboard(frontend_imports):
    from app.core import config
    from app.core.auth import hash_password
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine, session_scope
    from app.models.entities import User, UserRole

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()

    with session_scope() as s:
        s.add(
            User(
                username="admin",
                password_hash=hash_password("admin-pass-1234"),
                role=UserRole.ADMIN.value,
            )
        )

    from fastapi.testclient import TestClient

    from app.main import create_app

    client = TestClient(create_app())
    login = client.post(
        "/login",
        data={"username": "admin", "password": "admin-pass-1234", "next": "/dashboard"},
        follow_redirects=False,
    )
    assert login.status_code == 303
    cookie = login.cookies.get("mnemos_sid")
    assert cookie
    r = client.get("/dashboard", cookies={"mnemos_sid": cookie})
    assert r.status_code == 200
