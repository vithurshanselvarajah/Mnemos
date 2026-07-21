from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.api.deps import require_full_admin
from app.core.config import settings
from app.models.entities import ApiKey
from app.schemas.dto import ModelInfo, ModelSwitchRequest
from app.services.engine import InsightFaceEngine
from app.services.reindex import active_model, start_reindex, start_warmup, state

router = APIRouter(prefix="/models", tags=["models"])
log = logging.getLogger("mnemos.models")


class WarmupOut(BaseModel):
    name: str
    loaded: bool
    already_loaded: bool


@router.get("", response_model=ModelInfo, tags=["models"])
def current_model_info() -> ModelInfo:
    snap = state.snapshot()
    return ModelInfo(
        name=active_model(),
        loaded=InsightFaceEngine.current().is_loaded(),
        embedding_dim=settings.embedding_dim,
        det_size=settings.det_size,
        reindex_in_progress=snap["running"],
        reindex_total=snap["total"],
        reindex_done=snap["done"],
        download_active=snap["download_active"],
        download_model=snap["download_model"] or None,
        download_done=snap["download_done"],
        download_total=snap["download_total"],
    )


@router.get("/warmup", response_model=WarmupOut, tags=["models"])
def warmup_model() -> WarmupOut:
    name = active_model()
    engine = InsightFaceEngine.current()
    if engine.is_loaded() and engine.model_name == name:
        return WarmupOut(name=name, loaded=True, already_loaded=True)
    started = start_warmup(name)
    return WarmupOut(name=name, loaded=False, already_loaded=False) if started else WarmupOut(name=name, loaded=False, already_loaded=False)


@router.post("/switch", response_model=ModelInfo, tags=["models"])
def switch_model(req: ModelSwitchRequest, _: ApiKey = Depends(require_full_admin)) -> ModelInfo:
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    if name not in {"buffalo_s", "buffalo_l"}:
        raise HTTPException(status_code=400, detail="unsupported model")
    if not start_reindex(name):
        raise HTTPException(status_code=409, detail="reindex already in progress")
    snap = state.snapshot()
    return ModelInfo(
        name=name,
        embedding_dim=settings.embedding_dim,
        det_size=settings.det_size,
        reindex_in_progress=True,
        reindex_total=snap["total"],
        reindex_done=0,
    )
