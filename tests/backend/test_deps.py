"""Tests for the require_full_admin FastAPI dependency."""

from __future__ import annotations

from datetime import datetime


def _make_key(*, perm: str = "Full-Admin", revoked: bool = False):
    class _K:
        pass

    k = _K()
    k.permission_level = perm
    k.revoked_at = datetime.utcnow() if revoked else None
    return k


def test_require_full_admin_passes_with_admin_key(backend_imports):
    from app.api.deps import require_full_admin

    class _R:
        state: object

    r = _R()
    r.state = type("S", (), {"api_key": _make_key(perm="Full-Admin")})()
    out = require_full_admin(r)
    assert out.permission_level == "Full-Admin"


def test_require_full_admin_rejects_identify_only(backend_imports):
    import pytest
    from fastapi import HTTPException

    from app.api.deps import require_full_admin

    class _R:
        state: object

    r = _R()
    r.state = type("S", (), {"api_key": _make_key(perm="Identify-Only")})()
    with pytest.raises(HTTPException) as ei:
        require_full_admin(r)
    assert ei.value.status_code == 403


def test_require_full_admin_rejects_revoked_key(backend_imports):
    import pytest
    from fastapi import HTTPException

    from app.api.deps import require_full_admin

    class _R:
        state: object

    r = _R()
    r.state = type("S", (), {"api_key": _make_key(perm="Full-Admin", revoked=True)})()
    with pytest.raises(HTTPException) as ei:
        require_full_admin(r)
    assert ei.value.status_code == 403


def test_require_full_admin_rejects_missing_key(backend_imports):
    import pytest
    from fastapi import HTTPException

    from app.api.deps import require_full_admin

    class _R:
        state: object

    r = _R()
    r.state = type("S", (), {"api_key": None})()
    with pytest.raises(HTTPException) as ei:
        require_full_admin(r)
    assert ei.value.status_code == 403
