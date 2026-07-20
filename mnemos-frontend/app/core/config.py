from __future__ import annotations

import threading
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MNEMOS_FE_", case_sensitive=False, extra="ignore")

    db_path: str = Field(default="/data/frontend.db")
    session_hours: int = Field(default=8, ge=1, le=24 * 30)
    remember_days: int = Field(default=30, ge=1, le=365)
    default_backend_url: str = Field(default="http://mnemos-backend:8000")
    listen_host: str = Field(default="0.0.0.0")
    listen_port: int = Field(default=8080)
    secret: str = Field(default="change-me-please-rotate-on-first-run-32bytes")
    session_cookie_name: str = Field(default="mnemos_sid")
    session_cookie_secure: bool = Field(default=False)
    backend_request_timeout: float = Field(default=10.0)
    backend_ws_timeout: float = Field(default=120.0)


_override: Settings | None = None
_override_lock = threading.RLock()


def _make() -> Settings:
    with _override_lock:
        if _override is not None:
            return _override
    return Settings()


class _SettingsProxy:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def __getattr__(self, item: str) -> Any:
        if item.startswith("_"):
            raise AttributeError(item)
        return getattr(_make(), item)


def set_settings(replacement: Settings | None = None) -> None:
    global _override
    with _override_lock:
        _override = replacement


def current_settings() -> Settings:
    return _make()


settings = _SettingsProxy()
