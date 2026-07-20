from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from sqlmodel import Field, SQLModel


class UserRole(StrEnum):
    ADMIN = "Admin"
    OPERATOR = "Operator"


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    username: str = Field(index=True, unique=True)
    password_hash: str
    role: str = Field(default=UserRole.OPERATOR.value)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Session(SQLModel, table=True):
    __tablename__ = "sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_id: UUID = Field(foreign_key="users.id", index=True)
    session_token: str = Field(index=True, unique=True)
    expires_at: datetime
    created_at: datetime = Field(default_factory=datetime.utcnow)


class BackendNode(SQLModel, table=True):
    __tablename__ = "backend_nodes"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    name: str
    base_url: str
    api_key: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    is_default: bool = Field(default=True)
