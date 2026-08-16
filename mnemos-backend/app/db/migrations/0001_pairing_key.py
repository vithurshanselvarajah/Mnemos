from __future__ import annotations

from sqlalchemy import text

VERSION = 1
NAME = "add api_keys.is_pairing_key"


def upgrade(conn) -> None:
    conn.execute(text("ALTER TABLE api_keys ADD COLUMN is_pairing_key BOOLEAN NOT NULL DEFAULT 0"))
