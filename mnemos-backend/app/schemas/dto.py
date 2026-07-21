from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    x1: float
    y1: float
    x2: float
    y2: float


class IdentifyMatch(BaseModel):
    person_id: UUID
    name: str
    confidence: float = Field(ge=0.0, le=1.0)
    image_url: str | None = None
    image_is_data: bool = False


class IdentifyUnknownFace(BaseModel):
    crop_id: UUID
    image_url: str
    bounding_box: BoundingBox
    det_score: float


class IdentifyResponse(BaseModel):
    recognized: list[IdentifyMatch] = []
    unknown_count: int = 0
    unknown_faces: list[IdentifyUnknownFace] = []
    duplicates_skipped: int = 0


class PersonOut(BaseModel):
    id: UUID
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
    id: UUID
    person_id: UUID | None = None
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
    crop_ids: list[UUID]
    person_id: UUID | None = None
    new_person_name: str | None = None


class MarkNonFaceRequest(BaseModel):
    crop_ids: list[UUID]


class IgnoreRequest(BaseModel):
    crop_ids: list[UUID]


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
    download_done: int = Field(description="Bytes downloaded so far for the current download.")
    download_total: int = Field(description="Total bytes to download for the current model.")


class ModelSwitchRequest(BaseModel):

    name: str = Field(description="Target model name. One of `buffalo_s` or `buffalo_l`.")


class ApiKeyOut(BaseModel):
    id: UUID
    name: str
    key_prefix: str
    permission_level: str
    expires_at: datetime | None = None
    created_at: datetime
    revoked_at: datetime | None = None


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
    api_key_id: UUID
    key_prefix: str
    raw_key: str


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
