from __future__ import annotations

import threading
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MNEMOS_", case_sensitive=False, extra="ignore")

    db_path: str = Field(default="/data/backend.db")
    crops_dir: str = Field(default="/data/crops")

    vector_dsn: str = Field(default="postgresql://mnemos:mnemos@localhost:5432/mnemos_vectors")

    default_model: str = Field(default="buffalo_s")
    det_size: int = Field(default=640, ge=160, le=4096)
    min_face_px: int = Field(default=30, ge=8, le=4096)
    default_threshold: float = Field(default=0.40, ge=0.0, le=1.0)

    crop_pad_fraction: float = Field(default=0.50, ge=0.0, le=2.0)

    embedding_dim: int = Field(default=512)

    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    cors_origins: str = Field(default="*")

    master_key_prefix: str = Field(default="mnemos_master_")


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
