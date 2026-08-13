from __future__ import annotations

import pytest


@pytest.fixture
def fe_setup(frontend_imports):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.services import backend_client

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    return backend_client


def test_default_base_url_falls_back_to_settings(fe_setup, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_DEFAULT_BACKEND_URL", "http://fallback:8000")
    from app.core import config
    from app.core.config import set_settings

    config.set_settings(None)
    set_settings(None)
    assert fe_setup.default_base_url() == "http://fallback:8000"


def test_default_base_url_from_db_node(fe_setup):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="primary", base_url="http://primary:8000/", api_key="k"))
    assert fe_setup.default_base_url() == "http://primary:8000"


def test_default_api_key_from_db_node(fe_setup):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="primary", base_url="http://primary:8000", api_key="my-key"))
    assert fe_setup.default_api_key() == "my-key"


def test_default_api_key_returns_none_when_no_node(fe_setup):
    assert fe_setup.default_api_key() is None


def test_request_uses_x_api_key_header(fe_setup, monkeypatch):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="p", base_url="http://b:1234", api_key="secret-key"))

    captured = {}

    class _Resp:
        status_code = 200
        text = "{}"

        def json(self):
            return {}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def request(self, method, url, headers=None, **_kw):
            captured["method"] = method
            captured["url"] = url
            captured["headers"] = headers
            return _Resp()

    monkeypatch.setattr("httpx2.Client", lambda *a, **kw: _Client())
    fe_setup.get_sync("/api/v1/keys")
    assert captured["headers"].get("X-API-Key") == "secret-key"


def test_request_url_building(fe_setup, monkeypatch):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="p", base_url="http://b:8000/", api_key=""))

    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def request(self, method, url, headers=None, **_kw):
            captured["url"] = url
            return _Resp()

    monkeypatch.setattr("httpx2.Client", lambda *a, **kw: _Client())
    fe_setup.get_sync("/healthz")
    assert captured["url"] == "http://b:8000/healthz"


def test_request_url_with_leading_slash(fe_setup, monkeypatch):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="p", base_url="http://b:8000", api_key=""))

    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {}

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def request(self, method, url, headers=None, **_kw):
            captured["url"] = url
            return _Resp()

    monkeypatch.setattr("httpx2.Client", lambda *a, **kw: _Client())
    fe_setup.get_sync("/api/v1/models")
    assert captured["url"] == "http://b:8000/api/v1/models"


def test_async_get_uses_async_client(fe_setup, monkeypatch):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="p", base_url="http://b:8000", api_key=""))

    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {}

    class _AsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, headers=None, **_kw):
            captured["url"] = url
            return _Resp()

    monkeypatch.setattr("httpx2.AsyncClient", _AsyncClient)
    import asyncio

    async def _run():
        return await fe_setup.get("/healthz")

    asyncio.run(_run())
    assert captured["url"] == "http://b:8000/healthz"


def test_post_async(fe_setup, monkeypatch):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="p", base_url="http://b:8000", api_key=""))

    captured = {}

    class _Resp:
        status_code = 200
        text = ""

        def json(self):
            return {}

    class _AsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def request(self, method, url, **kw):
            captured["method"] = method
            captured["url"] = url
            return _Resp()

    monkeypatch.setattr("httpx2.AsyncClient", _AsyncClient)
    import asyncio

    async def _run():
        return await fe_setup.post("/api/v1/identify", files={"file": ("x", b"")})

    asyncio.run(_run())
    assert captured["method"] == "POST"


def test_ping_success(fe_setup, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_DEFAULT_BACKEND_URL", "http://b:8000")
    from app.core import config
    from app.core.config import set_settings

    config.set_settings(None)
    set_settings(None)

    class _Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"status": "ok"}

    class _AsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            return _Resp()

    monkeypatch.setattr("httpx2.AsyncClient", _AsyncClient)
    import asyncio

    async def _run():
        return await fe_setup.ping()

    ok, payload = asyncio.run(_run())
    assert ok is True
    assert payload["status"] == "ok"


def test_ping_failure_returns_error(fe_setup, monkeypatch):
    class _AsyncClient:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url):
            raise RuntimeError("net down")

    monkeypatch.setattr("httpx2.AsyncClient", _AsyncClient)
    import asyncio

    async def _run():
        return await fe_setup.ping()

    ok, payload = asyncio.run(_run())
    assert ok is False
    assert "error" in payload


def test_default_base_url_uses_oldest_node(fe_setup):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="old", base_url="http://old:8000", api_key=""))
        s.add(BackendNode(name="new", base_url="http://new:8000", api_key=""))
    assert fe_setup.default_base_url() == "http://old:8000"
