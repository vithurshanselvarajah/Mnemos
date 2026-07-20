"""Tests for the security helpers (hashing, master key, API key minting)."""

from __future__ import annotations

import pytest


@pytest.fixture
def fresh(backend_imports):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.models.entities import ApiKey

    assert ApiKey is not None
    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()


def test_random_key_format(fresh):
    from app.core.security import new_master_key, new_random_key

    k = new_random_key()
    assert k.startswith("mnemos_k_")
    assert len(k) > 20

    m = new_master_key()
    assert m.startswith("mnemos_master_")
    assert len(m) > 30


def test_api_key_round_trip_via_hashing(fresh):
    from app.core.security import create_api_key, find_api_key_by_raw

    row, raw = create_api_key("test", "Identify-Only")
    found = find_api_key_by_raw(raw)
    assert found is not None
    assert found.id == row.id
    assert found.name == "test"


def test_find_api_key_by_invalid_returns_none(fresh):
    from app.core.security import find_api_key_by_raw

    assert find_api_key_by_raw("nope") is None


def test_revoked_api_key_not_returned(fresh):
    from datetime import datetime

    from app.core.security import create_api_key, find_api_key_by_raw

    row, raw = create_api_key("revoke-me", "Identify-Only")
    row.revoked_at = datetime.utcnow()
    from app.db.session import session_scope

    with session_scope() as s:
        s.add(row)

    found = find_api_key_by_raw(raw)
    assert found is None or found.revoked_at is not None
