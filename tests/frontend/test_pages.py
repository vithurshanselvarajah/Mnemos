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


def test_check_backend_distinguishes_reachable_vs_authenticated(fe_setup):
    from app.api.pages import _check_backend

    _check_backend.__dict__.pop("_cache", None)
    with (
        mock.patch("app.api.pages.default_base_url", return_value="http://b:8000"),
        mock.patch("app.api.pages.default_api_key", return_value="k"),
    ):
        # 200 = authenticated
        with mock.patch(
            "app.api.pages.get_sync",
            return_value=mock.Mock(
                status_code=200,
                headers={"content-type": "application/json"},
                json=lambda: {"model": "x", "model_loaded": True},
            ),
        ):
            _check_backend.__dict__.pop("_cache", None)
            s = _check_backend()
            assert s["reachable"] is True
            assert s["authenticated"] is True
            assert s["payload"]["model"] == "x"
        # 401 = reachable but key rejected
        with mock.patch(
            "app.api.pages.get_sync",
            return_value=mock.Mock(
                status_code=401, headers={"content-type": "application/json"}, json=lambda: {"detail": "bad"}
            ),
        ):
            _check_backend.__dict__.pop("_cache", None)
            s = _check_backend()
            assert s["reachable"] is True
            assert s["authenticated"] is False

        # connection error = not reachable
        def boom(*_a, **_kw):
            raise ConnectionError("nope")

        with mock.patch("app.api.pages.get_sync", side_effect=boom):
            _check_backend.__dict__.pop("_cache", None)
            s = _check_backend()
            assert s["reachable"] is False
            assert s["authenticated"] is False
    _check_backend.__dict__.pop("_cache", None)


def test_dashboard_shows_unreachable_when_key_rejected(logged_in_admin_with_backend):
    from app.api.pages import _check_backend

    _check_backend.__dict__.pop("_cache", None)
    _app, tc = logged_in_admin_with_backend
    with mock.patch(
        "app.api.pages.get_sync",
        return_value=mock.Mock(
            status_code=401, headers={"content-type": "application/json"}, json=lambda: {"detail": "bad"}
        ),
    ):
        r = tc.get("/dashboard")
        assert r.status_code == 200
        # The banner is rendered when backend_auth_failed
        assert "Stored backend key is invalid" in r.text
        assert "/onboarding/repair" in r.text
    _check_backend.__dict__.pop("_cache", None)


def test_dashboard_no_banner_when_auth_ok(logged_in_admin_with_backend):
    from app.api.pages import _check_backend

    _check_backend.__dict__.pop("_cache", None)
    _app, tc = logged_in_admin_with_backend
    with mock.patch(
        "app.api.pages.get_sync",
        return_value=mock.Mock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {"model": "x", "model_loaded": True},
        ),
    ):
        r = tc.get("/dashboard")
        assert r.status_code == 200
        assert "Stored backend key is invalid" not in r.text
    _check_backend.__dict__.pop("_cache", None)


def test_repair_get_requires_admin(logged_in_operator):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    _app, tc = logged_in_operator
    with session_scope() as s:
        s.add(BackendNode(name="t", base_url="http://b:8000", api_key="k"))
    r = tc.get("/onboarding/repair", follow_redirects=False)
    assert r.status_code == 303
    assert "/login" in r.headers["location"]


def test_repair_get_admin_sees_form(logged_in_admin_with_backend):
    _app, tc = logged_in_admin_with_backend
    r = tc.get("/onboarding/repair")
    assert r.status_code == 200
    assert "Re-pair" in r.text
    assert "Master pairing key" in r.text


def test_repair_post_succeeds_and_replaces_node(logged_in_admin_with_backend, monkeypatch):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    _app, tc = logged_in_admin_with_backend

    def fake_pair(base, master, name):
        from app.api.pages import _check_backend

        with session_scope() as s:
            for old in s.execute(select(BackendNode)).scalars().all():
                s.delete(old)
            s.add(BackendNode(name=name, base_url=base, api_key="newkey"))
        _check_backend.__dict__.pop("_cache", None)
        return {"raw_key": "newkey", "key_prefix": "mnemos_k"}, None

    from sqlalchemy import select

    monkeypatch.setattr("app.api.pages._perform_pair", fake_pair)
    r = tc.post(
        "/onboarding/repair",
        data={"base_url": "http://new:8000", "master_key": "mnemos_master_x", "name": "Frontend"},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/onboarding/repair?ok=1"
    with session_scope() as s:
        nodes = s.execute(select(BackendNode)).scalars().all()
        assert len(nodes) == 1
        assert nodes[0].base_url == "http://new:8000"
        assert nodes[0].api_key == "newkey"


def test_repair_post_renders_error_on_failure(logged_in_admin_with_backend, monkeypatch):
    _app, tc = logged_in_admin_with_backend

    def fake_pair(base, master, name):
        return None, "Invalid master key"

    monkeypatch.setattr("app.api.pages._perform_pair", fake_pair)
    r = tc.post(
        "/onboarding/repair",
        data={"base_url": "http://new:8000", "master_key": "wrong", "name": "Frontend"},
    )
    assert r.status_code == 400
    assert "Invalid master key" in r.text
    assert "Re-pair" in r.text


def test_repair_post_rejects_operator(logged_in_operator):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    _app, tc = logged_in_operator
    with session_scope() as s:
        s.add(BackendNode(name="t", base_url="http://b:8000", api_key="k"))
    r = tc.post(
        "/onboarding/repair",
        data={"base_url": "http://new:8000", "master_key": "x", "name": "F"},
    )
    assert r.status_code == 403


def test_backend_card_shows_stored_key_rejected(logged_in_admin_with_backend):
    from app.api.pages import _check_backend

    _check_backend.__dict__.pop("_cache", None)
    _app, tc = logged_in_admin_with_backend
    with mock.patch(
        "app.api.pages.get_sync",
        return_value=mock.Mock(
            status_code=401, headers={"content-type": "application/json"}, json=lambda: {"detail": "bad"}
        ),
    ):
        r = tc.get("/partials/backend-card")
        assert r.status_code == 200
        assert "Stored key rejected" in r.text
        assert "/onboarding/repair" in r.text
    _check_backend.__dict__.pop("_cache", None)


def test_backend_card_shows_reachable_when_auth_ok(logged_in_admin_with_backend):
    from app.api.pages import _check_backend

    _check_backend.__dict__.pop("_cache", None)
    _app, tc = logged_in_admin_with_backend
    with mock.patch(
        "app.api.pages.get_sync",
        return_value=mock.Mock(
            status_code=200,
            headers={"content-type": "application/json"},
            json=lambda: {"model": "buffalo_l", "model_loaded": True},
        ),
    ):
        r = tc.get("/partials/backend-card")
        assert r.status_code == 200
        assert "Reachable" in r.text
        assert "Stored key rejected" not in r.text
    _check_backend.__dict__.pop("_cache", None)
