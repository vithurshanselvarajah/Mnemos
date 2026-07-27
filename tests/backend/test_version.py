"""Tests for the embedded version stamp + cached get_version."""

from __future__ import annotations

import sys
import types


def test_get_version_returns_embedded(backend_imports):
    from app._version import __version__
    from app.core.version import get_version

    get_version.cache_clear()
    try:
        assert get_version() == __version__.strip()
    finally:
        get_version.cache_clear()


def test_get_version_is_cached(backend_imports):
    from app.core.version import get_version

    get_version.cache_clear()
    try:
        v1 = get_version()
        v2 = get_version()
        assert v1 == v2
    finally:
        get_version.cache_clear()


def test_get_version_falls_back_when_module_missing(backend_imports, monkeypatch):
    from app.core import version as version_mod

    monkeypatch.setitem(sys.modules, "app._version", None)
    version_mod.get_version.cache_clear()
    try:
        assert version_mod.get_version() == "0.0.0+unknown"
    finally:
        version_mod.get_version.cache_clear()


def test_get_version_falls_back_when_value_empty(backend_imports, monkeypatch):
    from app.core import version as version_mod

    fake = types.ModuleType("app._version")
    fake.__version__ = ""
    monkeypatch.setitem(sys.modules, "app._version", fake)

    version_mod.get_version.cache_clear()
    try:
        assert version_mod.get_version() == "0.0.0+unknown"
    finally:
        version_mod.get_version.cache_clear()


def test_get_version_falls_back_when_value_whitespace(backend_imports, monkeypatch):
    from app.core import version as version_mod

    fake = types.ModuleType("app._version")
    fake.__version__ = "   \n  "
    monkeypatch.setitem(sys.modules, "app._version", fake)

    version_mod.get_version.cache_clear()
    try:
        assert version_mod.get_version() == "0.0.0+unknown"
    finally:
        version_mod.get_version.cache_clear()
