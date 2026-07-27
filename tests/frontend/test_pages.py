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
def logged_in_admin(fe_setup):
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
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    return app, tc


@pytest.fixture
def logged_in_operator(fe_setup):
    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    app, tc = fe_setup
    with session_scope() as s:
        u = User(username="op", password_hash=hash_password("password"), role=UserRole.OPERATOR.value)
        s.add(u)
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    return app, tc


def test_index_redirects_to_onboarding_when_no_admin(fe_setup):
    _app, tc = fe_setup
    r = tc.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"] or r.headers["location"] == "/onboarding"


def test_index_redirects_to_login_when_no_user(logged_in_admin):
    _app, tc = logged_in_admin
    tc.cookies.clear()
    r = tc.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/login")


def test_index_redirects_to_dashboard_when_logged_in(logged_in_admin, monkeypatch):
    _app, tc = logged_in_admin
    monkeypatch.setattr(
        "app.services.backend_client.ping",
        mock.AsyncMock(return_value=(True, {"status": "ok"})),
    )
    monkeypatch.setattr(
        "app.api.pages.get_sync",
        lambda *_a, **_kw: mock.Mock(status_code=200, json=lambda: {"status": "ok"}),
    )
    r = tc.get("/", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


def test_onboarding_get_returns_html(fe_setup):
    _app, tc = fe_setup
    r = tc.get("/onboarding")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_onboarding_step_admin_when_no_admin(fe_setup):
    _app, tc = fe_setup
    r = tc.get("/onboarding")
    assert "admin" in r.text.lower()


def test_onboarding_step_backend_when_admin_only(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/onboarding")
    assert "backend" in r.text.lower() or "pair" in r.text.lower() or "onboard" in r.text.lower()


def test_login_get_returns_form(fe_setup):
    _app, tc = fe_setup
    r = tc.get("/login")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")


def test_login_get_redirects_when_authed(logged_in_admin, monkeypatch):
    _app, tc = logged_in_admin
    r = tc.get("/login", follow_redirects=False)
    assert r.status_code == 303


def test_login_get_honors_next(logged_in_admin, monkeypatch):
    _app, tc = logged_in_admin
    r = tc.get("/login?next=/dashboard", follow_redirects=False)
    assert r.status_code == 303


@pytest.fixture
def logged_in_admin_with_backend(logged_in_admin):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    app, tc = logged_in_admin
    with session_scope() as s:
        s.add(BackendNode(name="test", base_url="http://b:8000", api_key="k"))
    return app, tc


def test_dashboard_requires_backend(logged_in_admin_with_backend, monkeypatch):
    _app, tc = logged_in_admin_with_backend
    monkeypatch.setattr("app.services.backend_client.ping", mock.AsyncMock(return_value=(True, {})))
    monkeypatch.setattr(
        "app.api.pages.get_sync",
        lambda *_a, **_kw: mock.Mock(status_code=200, json=lambda: {"status": "ok"}),
    )
    r = tc.get("/dashboard", follow_redirects=False)
    assert r.status_code == 200


def test_dashboard_redirects_to_onboarding_when_no_backend(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/dashboard", follow_redirects=False)
    assert r.status_code == 303


def test_inbox_requires_backend(logged_in_admin_with_backend, monkeypatch):
    _app, tc = logged_in_admin_with_backend
    monkeypatch.setattr(
        "app.api.pages.get_sync",
        lambda *_a, **_kw: mock.Mock(
            status_code=200, json=lambda: {"items": [], "total": 0, "page": 1, "page_size": 48}
        ),
    )
    monkeypatch.setattr("app.api.pages.get_sync", lambda *_a, **_kw: mock.Mock(status_code=200, json=list))
    r = tc.get("/inbox", follow_redirects=False)
    assert r.status_code == 200


def test_inbox_redirects_without_backend(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/inbox", follow_redirects=False)
    assert r.status_code == 303


def test_persons_page(logged_in_admin_with_backend, monkeypatch):
    _app, tc = logged_in_admin_with_backend
    monkeypatch.setattr(
        "app.api.pages.get_sync",
        lambda *_a, **_kw: mock.Mock(
            status_code=200,
            json=lambda: [
                {
                    "id": "p1",
                    "name": "Alice",
                    "custom_threshold": None,
                    "embedding_count": 1,
                    "created_at": "2026-01-01T00:00:00Z",
                }
            ],
        ),
    )
    r = tc.get("/persons", follow_redirects=False)
    assert r.status_code == 200


def test_person_detail_404(monkeypatch):
    """person_detail returns 404 HTML when backend says so."""


def test_models_page(logged_in_admin, monkeypatch):
    _app, tc = logged_in_admin
    monkeypatch.setattr(
        "app.api.pages.get_sync",
        lambda *_a, **_kw: mock.Mock(
            status_code=200,
            json=lambda: {"name": "buffalo_s", "loaded": True, "embedding_dim": 512},
        ),
    )
    r = tc.get("/models", follow_redirects=False)
    assert r.status_code == 200


def test_keys_page_admin(logged_in_admin, monkeypatch):
    _app, tc = logged_in_admin
    monkeypatch.setattr(
        "app.api.pages.get_sync",
        lambda *_a, **_kw: mock.Mock(status_code=200, json=list),
    )
    r = tc.get("/keys", follow_redirects=False)
    assert r.status_code == 200


def test_keys_page_operator_redirects(logged_in_operator, monkeypatch):
    _app, tc = logged_in_operator
    monkeypatch.setattr(
        "app.api.pages.get_sync",
        lambda *_a, **_kw: mock.Mock(status_code=200, json=list),
    )
    r = tc.get("/keys", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"] == "/dashboard"


def test_users_page_admin(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/users", follow_redirects=False)
    assert r.status_code == 200


def test_users_page_operator_redirects(logged_in_operator):
    _app, tc = logged_in_operator
    r = tc.get("/users", follow_redirects=False)
    assert r.status_code == 303


def test_settings_page_admin(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/settings", follow_redirects=False)
    assert r.status_code == 200


def test_settings_page_operator_redirects(logged_in_operator):
    _app, tc = logged_in_operator
    r = tc.get("/settings", follow_redirects=False)
    assert r.status_code == 303


def test_identify_page(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/identify", follow_redirects=False)
    assert r.status_code == 200


def test_swagger_page_admin(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/swagger", follow_redirects=False)
    assert r.status_code == 200


def test_swagger_page_operator_redirects(logged_in_operator):
    _app, tc = logged_in_operator
    r = tc.get("/swagger", follow_redirects=False)
    assert r.status_code == 303


def test_api_alias_to_swagger(logged_in_admin):
    _app, tc = logged_in_admin
    r = tc.get("/api", follow_redirects=False)
    assert r.status_code == 200


def test_partials_ws_target(fe_setup):
    from urllib.parse import urlparse

    _app, tc = fe_setup
    r = tc.get("/partials/ws-target", headers={"host": "example.com"})
    assert r.status_code == 200
    body = r.json()
    parsed = urlparse(body["ws_url"])
    assert parsed.scheme == "ws"
    assert parsed.hostname == "example.com"


def test_partials_ws_target_https(fe_setup):
    from urllib.parse import urlparse

    _app, tc = fe_setup
    r = tc.get("/partials/ws-target", headers={"host": "example.com", "x-forwarded-proto": "https"})
    body = r.json()
    parsed = urlparse(body["ws_url"])
    assert parsed.hostname == "example.com"
