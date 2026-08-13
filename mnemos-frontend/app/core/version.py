from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def get_version() -> str:
    try:
        from app._version import __version__
    except Exception:
        return "0.0.0+unknown"
    v = (__version__ or "").strip()
    return v or "0.0.0+unknown"
