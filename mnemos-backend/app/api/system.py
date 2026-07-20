from __future__ import annotations

import logging
from hmac import compare_digest

from fastapi import APIRouter, HTTPException

from app.core.security import create_api_key, ensure_master_key, rotate_master_key
from app.models.entities import PermissionLevel
from app.schemas.dto import PairRequest, PairResponse

log = logging.getLogger("mnemos.system")
router = APIRouter(prefix="/system", tags=["system"])


def _require_admin(request) -> None:
    key = getattr(request.state, "api_key", None)
    if key is None or key.permission_level != PermissionLevel.FULL_ADMIN.value or key.revoked_at is not None:
        raise HTTPException(status_code=403, detail="Full-Admin API key required")


@router.get("/master", response_model=str, tags=["system"])
def view_master() -> str:
    return ensure_master_key()


@router.post("/master/rotate", response_model=str, tags=["system"])
def rotate_master() -> str:
    return rotate_master_key()


@router.post("/pair", response_model=PairResponse, tags=["system"])
def pair_with_master_key(req: PairRequest):
    expected = ensure_master_key()
    if not compare_digest(req.master_key.strip(), expected):
        raise HTTPException(status_code=401, detail="Invalid master key")
    row, raw = create_api_key(req.name, PermissionLevel.FULL_ADMIN.value)
    return PairResponse(api_key_id=row.id, key_prefix=row.key_prefix, raw_key=raw)
