from __future__ import annotations

import hmac
import secrets
from hashlib import sha256

from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models.entities import ApiKey, SystemSetting


def _key_hash(raw: str) -> str:
    salt = (settings.master_key_prefix + "hmac").encode()
    return hmac.new(salt, raw.encode("utf-8"), sha256).hexdigest()


def new_random_key() -> str:
    return "mnemos_k_" + secrets.token_urlsafe(32)


def new_master_key() -> str:
    return settings.master_key_prefix + secrets.token_urlsafe(32)


def _read_master_key_from_db() -> str | None:
    with session_scope() as s:
        row = s.execute(select(SystemSetting).where(SystemSetting.key == "master_key")).scalar_one_or_none()
        return row.value if row else None


def _write_master_key_to_db(value: str) -> None:
    with session_scope() as s:
        row = s.execute(select(SystemSetting).where(SystemSetting.key == "master_key")).scalar_one_or_none()
        if row is None:
            s.add(SystemSetting(key="master_key", value=value))
        else:
            row.value = value


def ensure_master_key() -> str:
    existing = _read_master_key_from_db()
    if existing:
        return existing
    fresh = new_master_key()
    _write_master_key_to_db(fresh)
    return fresh


def rotate_master_key() -> str:
    fresh = new_master_key()
    _write_master_key_to_db(fresh)
    return fresh


def view_master_key() -> str:
    return ensure_master_key()


def create_api_key(name: str, permission_level: str, expires_at=None) -> tuple[ApiKey, str]:
    raw = new_random_key()
    row = ApiKey(
        name=name,
        key_hash=_key_hash(raw),
        key_prefix=raw[:8],
        permission_level=permission_level,
        expires_at=expires_at,
    )
    with session_scope() as s:
        s.add(row)
        s.flush()
        s.refresh(row)
        return row, raw


def find_api_key_by_raw(raw: str) -> ApiKey | None:
    h = _key_hash(raw)
    with session_scope() as s:
        return s.execute(select(ApiKey).where(ApiKey.key_hash == h)).scalar_one_or_none()
