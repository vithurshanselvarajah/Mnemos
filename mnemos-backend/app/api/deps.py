from __future__ import annotations

from fastapi import HTTPException, Request


def require_full_admin(request: Request):
    key = getattr(request.state, "api_key", None)
    if key is None or key.revoked_at is not None or key.permission_level != "Full-Admin":
        raise HTTPException(status_code=403, detail="Full-Admin API key required")
    return key
