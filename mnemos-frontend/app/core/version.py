"""Single source of truth for the project version.

The actual value lives in `app._version.__version__`, which is
written at image build time from the `APP_VERSION` build arg
(see `Dockerfile`). This module is a thin wrapper that adds a
safe default and a lru_cache so repeated calls stay cheap.
"""

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
