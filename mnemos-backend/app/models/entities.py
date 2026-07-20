from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class PermissionLevel(StrEnum):
    IDENTIFY_ONLY = "Identify-Only"
    FULL_ADMIN = "Full-Admin"


class FaceCropStatus(StrEnum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    NON_FACE = "NON_FACE"
    IGNORED = "IGNORED"


class ApiKey(SQLModel, table=True):
    __tablename__ = "api_keys"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    key_hash: str = Field(index=True, unique=True)
    key_prefix: str
    permission_level: str = Field(default=PermissionLevel.IDENTIFY_ONLY.value)
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: datetime | None = None


class Person(SQLModel, table=True):
    __tablename__ = "persons"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str = Field(index=True)
    custom_threshold: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FaceCrop(SQLModel, table=True):
    __tablename__ = "face_crops"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    person_id: UUID | None = Field(default=None, index=True, foreign_key="persons.id")
    file_path: str
    bounding_box: str
    det_score: float = Field(default=0.0)
    status: str = Field(default=FaceCropStatus.UNASSIGNED.value, index=True)
    image_sha: str | None = Field(default=None, index=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class SystemSetting(SQLModel, table=True):
    __tablename__ = "system_settings"

    key: str = Field(primary_key=True)
    value: str
    updated_at: datetime = Field(default_factory=datetime.utcnow)
