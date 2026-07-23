from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import require_full_admin
from app.core.config import settings
from app.models.entities import ApiKey
from app.schemas.dto import ModelArtifactOut, ModelAvailable, ModelInfo, ModelSwitchRequest
from app.services.engine import InsightFaceEngine
from app.services.model_downloader import variant_files_present
from app.services.model_manifest import available_models
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


def _model_info_from_snap(snap: dict, name: str) -> ModelInfo:
    return ModelInfo(
        name=name,
        loaded=InsightFaceEngine.current().is_loaded(),
        embedding_dim=settings.embedding_dim,
        det_size=settings.det_size,
        reindex_in_progress=snap["running"],
        reindex_total=snap["total"],
        reindex_done=snap["done"],
        download_active=snap["download_active"],
        download_model=snap["download_model"] or None,
        download_artifact=snap.get("download_artifact"),
        download_done=snap["download_done"],
        download_total=snap["download_total"],
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
        "`download_active=true` while weights are being fetched; `download_artifact` carries the "
        "filename currently being fetched, and `download_done`/`download_total` expose byte progress."
    ),
)
def current_model_info() -> ModelInfo:
    return _model_info_from_snap(state.snapshot(), active_model())


@router.get(
    "/warmup",
    response_model=WarmupOut,
    tags=["models"],
    summary="Warmup the active model",
    description=(
        "Loads the persisted active model into memory if it isn't already. If the model weights "
        "aren't on disk, they are downloaded from the upstream manifest (≈300MB for buffalo_s, "
        "≈1GB for buffalo_l, ≈10MB for the Rockchip RKNN variant). Returns immediately and runs "
        "the load in a background thread; subscribe to `ws://<host>/ws/events` for `warmup.download` "
        "(with `artifact` filename), `warmup.done`, and `warmup.error` events. If the model is "
        "already loaded, returns `already_loaded=true`."
    ),
)
def warmup_model() -> WarmupOut:
    name = active_model()
    engine = InsightFaceEngine.current()
    if engine.is_loaded() and engine.model_name == name:
        return WarmupOut(name=name, loaded=True, already_loaded=True)
    start_warmup(name)
    return WarmupOut(name=name, loaded=False, already_loaded=False)


@router.get(
    "/available",
    response_model=list[ModelAvailable],
    tags=["models"],
    summary="List models available for the current provider",
    description=(
        "Fetches the upstream model manifest and returns the entries that are applicable for the "
        "active provider. CPU and NVIDIA see the `standard` ONNX variants; Rockchip sees only the "
        "`rknn/<soc>` variant that matches either `/proc/device-tree/compatible` or the "
        "`MNEMOS_RK_SOC` override. Each model includes its artifact list with sizes, sha256, and "
        "whether the file is already on disk and verified."
    ),
)
def list_available_models() -> list[ModelAvailable]:
    out: list[ModelAvailable] = []
    for v in available_models():
        ready = variant_files_present(v)
        out.append(
            ModelAvailable(
                name=v.name,
                kind=v.kind,
                ready=ready,
                artifacts=[
                    ModelArtifactOut(
                        filename=a.filename,
                        size_bytes=a.size_bytes,
                        sha256=a.sha256,
                        local_path=a.local_path,
                        present=os.path.isfile(a.local_path),
                    )
                    for a in v.artifacts
                ],
            )
        )
    return out


@router.post(
    "/switch",
    response_model=ModelInfo,
    tags=["models"],
    summary="Switch the active detection model",
    description=(
        "Switches the active model to one of the entries returned by `GET /models/available` "
        "and re-embedds every stored face under the new embedding space. The download (if needed) "
        "and reindex run in a background thread; progress is published over WebSocket as "
        "`reindex.preparing`, `reindex.download` (with `artifact` filename), `reindex.start`, "
        "`reindex.progress`, and `reindex.done`. Requires a Full-Admin API key. Returns 409 if a "
        "reindex is already in progress."
    ),
)
def switch_model(req: ModelSwitchRequest, _: ApiKey = Depends(require_full_admin)) -> ModelInfo:
    name = (req.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    available = {v.name for v in available_models()}
    if name not in available:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported model {name!r}; available for provider={settings.provider}: {sorted(available)}",
        )
    if not start_reindex(name):
        raise HTTPException(status_code=409, detail="reindex already in progress")
    return _model_info_from_snap(state.snapshot(), name)
