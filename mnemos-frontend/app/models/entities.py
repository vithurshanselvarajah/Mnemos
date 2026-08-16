from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import uuid4

from sqlalchemy import CHAR, Column
from sqlmodel import Field, SQLModel


def _uuid32() -> str:
    return uuid4().hex


class UserRole(StrEnum):
    ADMIN = "Admin"
    OPERATOR = "Operator"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: str = Field(
        default_factory=_uuid32,

        sa_column=Column("id", CHAR(32), primary_key=True),
    )
    username: str = Field(index=True, unique=True)
    password_hash: str
    role: str = Field(default=UserRole.OPERATOR.value)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: str = Field(
        default_factory=_uuid32,

        sa_column=Column("id", CHAR(32), primary_key=True),
    )
    user_id: str = Field(
        sa_column=Column("user_id", CHAR(32), index=True),
    )
    session_token: str = Field(index=True, unique=True)
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BackendNode(SQLModel, table=True):
    __tablename__ = "backend_nodes"

    id: str = Field(
        default_factory=_uuid32,

        sa_column=Column("id", CHAR(32), primary_key=True),
    )
    name: str
    base_url: str
    api_key: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_default: bool = Field(default=True)


class BackupCadence(StrEnum):
    DAILY = "daily"
    WEEKLY = "weekly"


class BackupSettings(SQLModel, table=True):
    __tablename__ = "backup_settings"

    id: str = Field(
        default_factory=_uuid32,

        sa_column=Column("id", CHAR(32), primary_key=True),
    )
    enabled: bool = Field(default=False)
    cadence: str = Field(default=BackupCadence.DAILY.value)
    hour_utc: int = Field(default=3, ge=0, le=23)
    weekday_utc: int = Field(default=0, ge=0, le=6)
    retention_count: int = Field(default=7, ge=1, le=365)
    next_run_at: datetime | None = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BackupJobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


class BackupJob(SQLModel, table=True):
    __tablename__ = "backup_jobs"

    id: str = Field(primary_key=True)
    kind: str = Field(default="restore")
    filename: str | None = Field(default=None)
    status: str = Field(default=BackupJobStatus.PENDING.value)
    started_at: datetime = Field(default_factory=datetime.utcnow)
    finished_at: datetime | None = Field(default=None)
    log: str = Field(default="")
    error: str | None = Field(default=None)


class BackupFileSource(StrEnum):
    LOCAL = "local"
    UPLOADED = "uploaded"


class BackupFile(SQLModel, table=True):
    __tablename__ = "backup_files"

    filename: str = Field(primary_key=True)
    size_bytes: int = Field(default=0)
    sha256: str = Field(default="")
    source: str = Field(default=BackupFileSource.LOCAL.value)
    created_at: datetime = Field(default_factory=datetime.utcnow)
