from __future__ import annotations

import importlib
import logging
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import OperationalError, ProgrammingError

log = logging.getLogger("mnemos.frontend.db.migrations")

VERSION_TABLE_DDL = (
    "CREATE TABLE IF NOT EXISTS schema_version ("
    "  version INTEGER PRIMARY KEY,"
    "  name TEXT NOT NULL,"
    "  applied_at TEXT NOT NULL"
    ")"
)


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    upgrade: Callable[[object], None]


def discover(package_path: str) -> list[Migration]:
    migrations: list[Migration] = []
    package = importlib.import_module(package_path)
    for mod_info in pkgutil.iter_modules(package.__path__):
        if not mod_info.name[:4].isdigit() or mod_info.name[4:5] != "_":
            continue
        module = importlib.import_module(f"{package_path}.{mod_info.name}")
        version = getattr(module, "VERSION", None)
        name = getattr(module, "NAME", None)
        upgrade = getattr(module, "upgrade", None)
        if version is None or name is None or upgrade is None:
            raise RuntimeError(f"migration module {mod_info.name} must define VERSION, NAME, upgrade()")
        migrations.append(Migration(version=int(version), name=str(name), upgrade=upgrade))
    migrations.sort(key=lambda m: m.version)
    return migrations


def _applied_versions(conn) -> set[int]:
    rows = conn.execute(text("SELECT version FROM schema_version")).all()
    return {int(r[0]) for r in rows}


def _is_already_applied_error(err: Exception) -> bool:
    msg = str(err).lower()
    return "duplicate column" in msg or "already exists" in msg


def run(eng: Engine, migrations: list[Migration]) -> list[int]:
    with eng.begin() as conn:
        conn.execute(text(VERSION_TABLE_DDL))
        already = _applied_versions(conn)
    pending = [m for m in migrations if m.version not in already]
    if not pending:
        log.info("migrations: schema already at version %s", max((m.version for m in migrations), default=0))
        return []
    applied: list[int] = []
    for m in pending:
        log.info("migrations: applying %04d %s", m.version, m.name)
        try:
            with eng.begin() as conn:
                m.upgrade(conn)
        except (OperationalError, ProgrammingError) as e:
            if not _is_already_applied_error(e):
                raise
            log.info("migrations: %04d %s already applied (create_all did it)", m.version, m.name)
        with eng.begin() as conn:
            conn.execute(
                text("INSERT INTO schema_version (version, name, applied_at) VALUES (:v, :n, :t)"),
                {"v": m.version, "n": m.name, "t": datetime.now(UTC).isoformat()},
            )
        applied.append(m.version)
    log.info("migrations: applied %s", applied)
    return applied
