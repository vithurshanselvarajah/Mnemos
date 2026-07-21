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
    name: str
    loaded: bool = False
    embedding_dim: int
    det_size: int
    reindex_in_progress: bool
    reindex_total: int = 0
    reindex_done: int = 0
    download_active: bool = False
    download_model: str | None = None
    download_done: int = 0
    download_total: int = 0


class ModelSwitchRequest(BaseModel):
    name: str


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
    status: str
    version: str
    model: str | None = None
    model_loaded: bool = False
    db: bool
    vector_db: bool
    reindex_in_progress: bool
    reindex_done: int
    reindex_total: int
