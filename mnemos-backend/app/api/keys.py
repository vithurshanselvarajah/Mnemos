from __future__ import annotations

import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.api.deps import require_full_admin
from app.core.security import create_api_key
from app.db.session import session_scope
from app.models.entities import ApiKey, PermissionLevel
from app.schemas.dto import ApiKeyCreate, ApiKeyCreateResponse, ApiKeyOut

router = APIRouter(prefix="/keys", tags=["keys"])
log = logging.getLogger("mnemos.keys")


def _to_out(row: ApiKey) -> ApiKeyOut:
    return ApiKeyOut(
        id=row.id,
        name=row.name,
        key_prefix=row.key_prefix,
        permission_level=row.permission_level,
        expires_at=row.expires_at,
        created_at=row.created_at,
        revoked_at=row.revoked_at,
    )


@router.get(
    "",
    response_model=list[ApiKeyOut],
    tags=["keys"],
    summary="List API keys",
    description="Returns every API key (including revoked ones) ordered by creation time. Requires a Full-Admin API key.",
)
def list_keys(_: ApiKey = Depends(require_full_admin)) -> list[ApiKeyOut]:
    with session_scope() as s:
        rows = s.execute(select(ApiKey).order_by(ApiKey.created_at.desc())).scalars().all()
        return [_to_out(r) for r in rows]


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    tags=["keys"],
    summary="Create an API key",
    description=(
        "Mints a new API key. `raw_key` is only returned in this response — store it now, it "
        "cannot be recovered later. Permission level must be `Identify-Only` or `Full-Admin`. "
        "Requires a Full-Admin API key."
    ),
)
def create_key(req: ApiKeyCreate, _: ApiKey = Depends(require_full_admin)) -> ApiKeyCreateResponse:
    perm = req.permission_level
    if perm not in (PermissionLevel.IDENTIFY_ONLY.value, PermissionLevel.FULL_ADMIN.value):
        raise HTTPException(status_code=400, detail="invalid permission_level")
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    row, raw = create_api_key(name, perm, req.expires_at)
    return ApiKeyCreateResponse(api_key=_to_out(row), raw_key=raw)


@router.post(
    "/{key_id}/revoke",
    response_model=ApiKeyOut,
    tags=["keys"],
    summary="Revoke an API key",
    description=(
        "Marks the API key as revoked (sets `revoked_at`). The key will fail authentication on "
        "any future request. The row is kept for audit. Requires a Full-Admin API key."
    ),
)
def revoke_key(key_id: uuid.UUID, _: ApiKey = Depends(require_full_admin)) -> ApiKeyOut:
    with session_scope() as s:
        row = s.get(ApiKey, key_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        row.revoked_at = datetime.utcnow()
        s.add(row)
        s.flush()
        s.refresh(row)
        return _to_out(row)


@router.delete(
    "/{key_id}",
    tags=["keys"],
    summary="Delete an API key",
    description="Hard-deletes the API key. Requires a Full-Admin API key.",
)
def delete_key(key_id: uuid.UUID, _: ApiKey = Depends(require_full_admin)) -> dict:
    with session_scope() as s:
        row = s.get(ApiKey, key_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        s.delete(row)
    return {"ok": True}
