from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class IdentifyMatch(BaseModel):
    person_id: str
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    image_url: str | None = None
    image_is_data: bool = False


class IdentifyUnknownFace(BaseModel):
    crop_id: str
    image_url: str
    bounding_box: BoundingBox
    det_score: float


class IdentifyResponse(BaseModel):
    recognized: list[IdentifyMatch] = []
    unknown_count: int = 0
    unknown_faces: list[IdentifyUnknownFace] = []
    duplicates_skipped: int = 0


class PersonOut(BaseModel):
    id: str
    name: str
    custom_threshold: float | None = None
    sample_count: int = 0
    thumbnail_url: str | None = None
    best_det_score: float = 0.0
    created_at: datetime
    updated_at: datetime


class PersonCreate(BaseModel):
    name: str
    custom_threshold: float | None = None


class PersonUpdate(BaseModel):
    name: str | None = None
    custom_threshold: float | None = None


class FaceCropOut(BaseModel):
    id: str
    person_id: str | None = None
    image_url: str
    bounding_box: list[float]
    det_score: float
    status: str
    created_at: datetime


class UnassignedPage(BaseModel):
    total: int
    page: int
    page_size: int
    items: list[FaceCropOut]


class AssignRequest(BaseModel):
    crop_ids: list[str]
    person_id: str | None = None
    new_person_name: str | None = None


class MarkNonFaceRequest(BaseModel):
    crop_ids: list[str]


class IgnoreRequest(BaseModel):
    crop_ids: list[str]


class ModelInfo(BaseModel):
    name: str = Field(description="Currently persisted model name (e.g. `buffalo_s`).")
    loaded: bool = Field(description="True when the model weights are loaded into memory and ready to embed.")
    embedding_dim: int = Field(description="Dimensionality of the embedding vectors produced by the model.")
    det_size: int = Field(description="Detector input side length in pixels (e.g. 640).")
    reindex_in_progress: bool = Field(description="True while a switch-and-reindex job is running.")
    reindex_total: int = Field(description="Total number of crops that will be re-embedded.")
    reindex_done: int = Field(description="Number of crops already re-embedded.")
    download_active: bool = Field(description="True while model weights are being downloaded.")
    download_model: str | None = Field(description="Name of the model currently being downloaded, if any.")
    download_artifact: str | None = Field(
        description="Filename of the artifact currently being downloaded, if any."
    )
    download_done: int = Field(description="Bytes downloaded so far for the current download.")
    download_total: int = Field(description="Total bytes to download for the current model.")


class ModelSwitchRequest(BaseModel):
    name: str = Field(description="Target model name. One of `buffalo_s`, `buffalo_m`, or `buffalo_l`.")


class ModelArtifactOut(BaseModel):
    filename: str
    size_bytes: int
    sha256: str
    local_path: str
    present: bool


class ModelAvailable(BaseModel):
    name: str
    kind: str
    ready: bool
    artifacts: list[ModelArtifactOut]


class ApiKeyOut(BaseModel):
    id: str
    name: str
    key_prefix: str
    permission_level: str
    expires_at: datetime | None = None
    created_at: datetime
    revoked_at: datetime | None = None
    is_pairing_key: bool = Field(
        default=False,
        description=(
            "True when this key was minted by /system/pair to bootstrap the "
            "frontend↔backend link. Pairing keys are filtered out of the keys list."
        ),
    )


class ApiKeyCreate(BaseModel):
    name: str
    permission_level: str = "Identify-Only"
    expires_at: datetime | None = None


class ApiKeyCreateResponse(BaseModel):
    api_key: ApiKeyOut
    raw_key: str


class PairRequest(BaseModel):
    master_key: str
    name: str = "Frontend"


class PairResponse(BaseModel):
    api_key_id: str
    key_prefix: str
    raw_key: str


class NvidiaGpuInfo(BaseModel):
    onnxruntime_available: bool = Field(
        description="True when the onnxruntime package could be imported in this process."
    )
    cuda_available: bool = Field(
        description="True when onnxruntime reports the CUDAExecutionProvider is available."
    )
    device_count: int = Field(
        description="Number of NVIDIA GPUs that successfully exposed a libcuda handle at boot. 0 when not detectable."
    )
    available_providers: list[str] = Field(
        description="All execution providers reported by onnxruntime at startup."
    )
    active_providers: list[str] = Field(
        description="The execution providers actually bound to the running engine. "
        'For the NVIDIA variant this is always exactly `["CUDAExecutionProvider"]` — '
        "the engine is hard-locked and never falls back to CPU."
    )
    last_error: str | None = Field(
        description="Most recent CUDA-side error, or null if everything is healthy."
    )


class HealthOut(BaseModel):
    status: str = Field(
        description="`ok` only when the database, vector DB, and model are all healthy. "
        "`degraded` otherwise (e.g. model not loaded)."
    )
    version: str = Field(description="Backend version string.")
    model: str | None = Field(description="Currently persisted model name, or null if unset.")
    model_loaded: bool = Field(
        description="True when the detection model is loaded into memory. "
        "False after a failed download or while a warmup is pending."
    )
    db: bool = Field(description="True if the local SQLite database is reachable.")
    vector_db: bool = Field(description="True if the pgvector database is reachable.")
    reindex_in_progress: bool = Field(description="True while a switch-and-reindex is running.")
    reindex_done: int = Field(description="Crops re-embedded so far.")
    reindex_total: int = Field(description="Total crops to re-embed, or 0 when idle.")
    provider: str = Field(description="Active inference provider: `cpu`, `nvidia`, or `rockchip`.")
    rockchip_soc: str | None = Field(
        description="Detected (or overridden) Rockchip SoC. `null` when the provider is not Rockchip."
    )
    nvidia: NvidiaGpuInfo | None = Field(
        description="Detailed NVIDIA / CUDA status. `null` when the active provider is not `nvidia`."
    )
