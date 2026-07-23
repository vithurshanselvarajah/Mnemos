from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import settings
from app.core.version import get_version
from app.db.session import get_engine
from app.schemas.dto import HealthOut
from app.services import vector_repo
from app.services.engine import InsightFaceEngine
from app.services.model_manifest import _detect_rockchip_soc
from app.services.reindex import active_model, state

router = APIRouter()


@router.get(
    "/healthz",
    response_model=HealthOut,
    tags=["health"],
    summary="Service health check",
    description=(
        "Returns the overall service status and per-dependency liveness. "
        "Status is `ok` only when the database, vector DB, **and** model are all reachable. "
        "If the model isn't loaded (e.g. weights download failed), the status is `degraded` "
        "and `model_loaded` is false."
    ),
)
def healthz() -> HealthOut:
    db_ok = True
    try:
        with get_engine().connect() as c:
            c.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    snap = state.snapshot()
    model_loaded = InsightFaceEngine.current().is_loaded()
    vector_ok = vector_repo.ping()
    return HealthOut(
        status="ok" if (db_ok and vector_ok and model_loaded) else "degraded",
        version=get_version(),
        model=active_model(),
        model_loaded=model_loaded,
        db=db_ok,
        vector_db=vector_ok,
        reindex_in_progress=snap["running"],
        reindex_done=snap["done"],
        reindex_total=snap["total"],
        provider=settings.provider,
        rockchip_soc=_detect_rockchip_soc() if settings.provider == "rockchip" else None,
    )
