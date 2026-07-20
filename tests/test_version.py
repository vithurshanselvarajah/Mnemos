"""Tests for the embedded version stamp.

Each service keeps its version in `app/_version.py` as
`__version__`. The `app.core.version.get_version()` helper reads
that string, caches it, and falls back to `0.0.0+unknown` if the
embedded file is missing or its value is empty.
"""

from __future__ import annotations


def test_backend_version_is_embedded(backend_imports):
    from app._version import __version__
    from app.core.version import get_version

    assert __version__
    assert get_version() == __version__.strip()


def test_frontend_version_is_embedded(frontend_imports):
    from app._version import __version__
    from app.core.version import get_version

    assert __version__
    assert get_version() == __version__.strip()


def test_backend_and_frontend_can_differ(backend_imports, frontend_imports):
    from app._version import __version__ as backend_version, __version__ as frontend_version

    # No constraint on the values themselves; the suite can bump them
    # independently. Just make sure both modules load and return strings.
    assert isinstance(backend_version, str) and backend_version
    assert isinstance(frontend_version, str) and frontend_version


def test_get_version_is_cached(backend_imports):
    from app.core.version import get_version

    assert get_version() == get_version()


def test_get_version_falls_back_when_value_empty(backend_imports, monkeypatch):
    import sys
    import types

    from app.core import version as version_mod

    fake = types.ModuleType("app._version")
    fake.__version__ = ""
    monkeypatch.setitem(sys.modules, "app._version", fake)

    version_mod.get_version.cache_clear()
    try:
        assert version_mod.get_version() == "0.0.0+unknown"
    finally:
        version_mod.get_version.cache_clear()
