from __future__ import annotations

import pytest
from pydantic import ValidationError


@pytest.fixture
def config(frontend_imports):
    from app.core import config as config_mod

    return config_mod


def test_settings_defaults(config, monkeypatch):
    for k in (
        "MNEMOS_FE_DB_PATH",
        "MNEMOS_FE_LISTEN_HOST",
        "MNEMOS_FE_LISTEN_PORT",
        "MNEMOS_FE_SECRET",
    ):
        monkeypatch.delenv(k, raising=False)
    s = config.Settings()
    assert s.session_hours == 8
    assert s.remember_days == 30
    assert s.listen_port == 8080
    assert s.session_cookie_name == "mnemos_sid"
    assert s.session_cookie_secure is False


def test_settings_env_override(config, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_DB_PATH", "/tmp/foo.db")
    monkeypatch.setenv("MNEMOS_FE_LISTEN_PORT", "9999")
    monkeypatch.setenv("MNEMOS_FE_SECRET", "x" * 32)
    s = config.Settings()
    assert s.db_path == "/tmp/foo.db"
    assert s.listen_port == 9999
    assert len(s.secret) >= 32


def test_settings_session_hours_validation(config, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_SESSION_HOURS", "0")
    with pytest.raises(ValidationError):
        config.Settings()


def test_settings_session_hours_max_validation(config, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_SESSION_HOURS", "100000")
    with pytest.raises(ValidationError):
        config.Settings()


def test_settings_remember_days_validation(config, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_REMEMBER_DAYS", "0")
    with pytest.raises(ValidationError):
        config.Settings()


def test_settings_proxy_reads_through(config, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_LISTEN_PORT", "7777")
    config.set_settings(None)
    assert config.settings.listen_port == 7777


def test_settings_proxy_does_not_cache(config, monkeypatch):
    monkeypatch.setenv("MNEMOS_FE_LISTEN_PORT", "5555")
    config.set_settings(None)
    port1 = config.settings.listen_port
    monkeypatch.setenv("MNEMOS_FE_LISTEN_PORT", "6666")
    config.set_settings(None)
    port2 = config.settings.listen_port
    assert port1 == 5555
    assert port2 == 6666


def test_set_settings_overrides(config, monkeypatch):
    custom = config.Settings(listen_port=1234)
    config.set_settings(custom)
    assert config.settings.listen_port == 1234
    config.set_settings(None)


def test_settings_proxy_rejects_private(config):
    """Accessing a private attr on the proxy should raise AttributeError."""
    config.set_settings(None)
    with pytest.raises(AttributeError):
        _ = config.settings._private  # type: ignore[attr-defined]


def test_settings_proxy_returns_settings_instance(config):
    s = config.settings.listen_port
    assert isinstance(s, int)


def test_current_settings_returns_settings(config):
    config.set_settings(None)
    s = config.current_settings()
    assert s.__class__.__name__ == "Settings"
