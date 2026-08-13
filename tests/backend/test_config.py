"""Tests for the backend settings proxy + pydantic-settings defaults."""

from __future__ import annotations

import os

import pytest


@pytest.fixture
def fresh(backend_imports):
    from app.core import config
    from app.core.config import set_settings

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    return config


def test_settings_defaults(fresh, backend_env):
    from app.core.config import current_settings

    s = current_settings()
    assert s.db_path.endswith("backend.db")
    assert s.crops_dir.endswith("crops")
    assert s.default_model == "buffalo_s"
    assert s.det_size == 640
    assert s.min_face_px == 30
    assert 0.0 <= s.default_threshold <= 1.0
    assert s.provider == "cpu"
    assert s.api_host == "127.0.0.1"
    assert s.api_port == int(os.environ["MNEMOS_API_PORT"])


def test_settings_proxy_returns_same_attrs(fresh):
    from app.core import config
    from app.core.config import current_settings

    proxy = config.settings
    direct = current_settings()
    assert proxy.db_path == direct.db_path
    assert proxy.default_model == direct.default_model


def test_set_settings_swaps_proxy(fresh):
    from app.core import config
    from app.core.config import current_settings, set_settings

    custom = config.Settings(default_model="buffalo_l", det_size=320, default_threshold=0.5)
    set_settings(custom)
    assert current_settings().default_model == "buffalo_l"
    assert config.settings.det_size == 320
    set_settings(None)
    assert current_settings().default_model == "buffalo_s"


def test_settings_rejects_private_attr(fresh):
    from app.core import config

    with pytest.raises(AttributeError):
        _ = config.settings._made_up_field  # type: ignore[attr-defined]


def test_settings_picks_up_env(backend_imports, monkeypatch):
    from app.core.config import current_settings, set_settings

    monkeypatch.setenv("MNEMOS_PROVIDER", "nvidia")
    monkeypatch.setenv("MNEMOS_DEFAULT_MODEL", "buffalo_m")
    set_settings(None)
    s = current_settings()
    assert s.provider == "nvidia"
    assert s.default_model == "buffalo_m"


def test_settings_validates_threshold(backend_imports):
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(default_threshold=1.5)
    with pytest.raises(ValidationError):
        Settings(default_threshold=-0.1)


def test_settings_validates_det_size(backend_imports):
    from pydantic import ValidationError

    from app.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(det_size=10)
    with pytest.raises(ValidationError):
        Settings(det_size=10000)


def test_settings_extra_env_is_ignored(backend_imports, monkeypatch):
    from app.core.config import Settings

    monkeypatch.setenv("MNEMOS_BOGUS_KEY", "ignored")
    s = Settings()
    assert not hasattr(s, "bogus_key")
