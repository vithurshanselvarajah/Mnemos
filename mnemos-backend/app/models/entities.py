from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import CHAR, Column
from sqlmodel import Field, SQLModel


def _uuid32() -> str:
    return uuid4().hex


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

    id: str = Field(
        default_factory=_uuid32,

        sa_column=Column("id", CHAR(32), primary_key=True),
    )
    name: str
    key_hash: str = Field(index=True, unique=True)
    key_prefix: str
    permission_level: str = Field(default=PermissionLevel.IDENTIFY_ONLY.value)
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    revoked_at: datetime | None = None
    is_pairing_key: bool = Field(default=False)


class Person(SQLModel, table=True):
    __tablename__ = "persons"

    id: str = Field(
        default_factory=_uuid32,

        sa_column=Column("id", CHAR(32), primary_key=True),
    )
    name: str = Field(index=True)
    custom_threshold: float | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class FaceCrop(SQLModel, table=True):
    __tablename__ = "face_crops"

    id: str = Field(
        default_factory=_uuid32,

        sa_column=Column("id", CHAR(32), primary_key=True),
    )
    person_id: str | None = Field(
        default=None,
        sa_column=Column("person_id", CHAR(32), index=True),
    )
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
