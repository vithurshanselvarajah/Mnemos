from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.version import get_version
from app.db.session import get_engine
from app.services.backend_client import default_base_url, ping

router = APIRouter()
log = logging.getLogger("mnemos.frontend.health")


@router.get("/healthz")
async def healthz(request: Request) -> dict:
    db_ok = True
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    user = getattr(request.state, "user", None)
    user_payload = {"username": user.username, "role": user.role} if user is not None else None

    backend_ok, backend_payload = await ping()
    return {
        "status": "ok" if db_ok else "degraded",
        "version": get_version(),
        "db": db_ok,
        "backend_url": default_base_url(),
        "backend_reachable": backend_ok,
        "backend": backend_payload,
        "user": user_payload,
    }
