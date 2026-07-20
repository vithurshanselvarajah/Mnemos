from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.version import get_version
from app.db.session import get_engine
from app.schemas.dto import HealthOut
from app.services import vector_repo
from app.services.reindex import active_model, state

router = APIRouter()


@router.get("/healthz", response_model=HealthOut, tags=["health"])
def healthz() -> HealthOut:
    db_ok = True
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    snap = state.snapshot()
    return HealthOut(
        status="ok" if (db_ok and vector_repo.ping()) else "degraded",
        version=get_version(),
        model=active_model(),
        db=db_ok,
        vector_db=vector_repo.ping(),
        reindex_in_progress=snap["running"],
        reindex_done=snap["done"],
        reindex_total=snap["total"],
    )
