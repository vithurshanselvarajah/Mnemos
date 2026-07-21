from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import require_full_admin
from app.core.config import settings
from app.models.entities import ApiKey
from app.schemas.dto import ModelInfo, ModelSwitchRequest
from app.services.engine import InsightFaceEngine
from app.services.reindex import active_model, start_reindex, start_warmup, state

router = APIRouter(prefix="/models", tags=["models"])
log = logging.getLogger("mnemos.models")


class WarmupOut(BaseModel):

    name: str = Field(description="Model name that was requested to load.")
    loaded: bool = Field(
        description="True if the model is already loaded and ready to embed. "
        "False means a background warmup was started; subscribe to the WebSocket "
        "for `warmup.done` / `warmup.error`."
    )
    already_loaded: bool = Field(
        description="True when the model was already in memory at request time (no background work scheduled)."
    )


@router.get(
    "",
    response_model=ModelInfo,
    tags=["models"],
    summary="Get active model info",
    description=(
        "Returns the currently persisted model name, whether it is loaded into memory, "
        "embedding dimension, detector input size, and live reindex/download progress. "
        "Used by the dashboard to surface health and by the models page to render status. "
        "`loaded=false` means the model needs a warmup before `/identify` can be served. "
        "`download_active=true` while weights are being fetched; `download_done`/`download_total` "
        "expose byte progress."
    ),
)
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


@router.get(
    "/warmup",
    response_model=WarmupOut,
    tags=["models"],
    summary="Warmup the active model",
    description=(
        "Loads the persisted active model into memory if it isn't already. If the model weights "
        "aren't on disk, they are downloaded from the InsightFace releases (≈300MB for buffalo_s, "
        "≈1GB for buffalo_l). Returns immediately and runs the load in a background thread; "
        "subscribe to `ws://<host>/ws/events` for `warmup.download`, `warmup.done`, and `warmup.error` "
        "events. If the model is already loaded, returns `already_loaded=true`."
    ),
)
def warmup_model() -> WarmupOut:
    name = active_model()
    engine = InsightFaceEngine.current()
    if engine.is_loaded() and engine.model_name == name:
        return WarmupOut(name=name, loaded=True, already_loaded=True)
    start_warmup(name)
    return WarmupOut(name=name, loaded=False, already_loaded=False)


@router.post(
    "/switch",
    response_model=ModelInfo,
    tags=["models"],
    summary="Switch the active detection model",
    description=(
        "Switches the active model to `buffalo_s` or `buffalo_l` and re-embedds every stored face "
        "under the new embedding space. The download (if needed) and reindex run in a background "
        "thread; progress is published over WebSocket as `reindex.preparing`, `reindex.download`, "
        "`reindex.start`, `reindex.progress`, and `reindex.done`. Requires a Full-Admin API key. "
        "Returns 409 if a reindex is already in progress."
    ),
)
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
