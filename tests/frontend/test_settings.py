"""Tests for the settings proxy pattern (pydantic-settings 3.14 quirks)."""

from __future__ import annotations

import pytest


@pytest.fixture
def proxy(frontend_imports):
    from app.core import config

    config.set_settings(config.Settings())
    return config.settings


def test_settings_proxy_reads_env_values(proxy):
    assert proxy.db_path.endswith("frontend.db")
    assert proxy.session_hours > 0
    assert proxy.remember_days > 0


def test_settings_proxy_can_be_swapped_for_tests(frontend_imports):
    from app.core import config
    from app.core.config import current_settings, set_settings

    custom = config.Settings(db_path="/tmp/custom.db", session_hours=2)
    set_settings(custom)
    assert current_settings().db_path == "/tmp/custom.db"
    assert config.settings.db_path == "/tmp/custom.db"
    set_settings(None)
    assert config.settings.db_path.endswith("frontend.db")
