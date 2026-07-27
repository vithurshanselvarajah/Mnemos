"""Tests for the backend SQLite engine + session_scope."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect, text


def test_engine_uses_db_path_from_settings(backend_imports):
    from app.core.config import current_settings
    from app.db.session import _make_engine

    eng = _make_engine()
    try:
        assert eng.url.drivername == "sqlite"
        assert eng.url.database.endswith("backend.db")
        assert current_settings().db_path.endswith("backend.db")
    finally:
        eng.dispose()


def test_engine_creates_parent_dir(backend_imports, tmp_root):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import _make_engine, reset_engine

    deep = tmp_root / "a" / "b" / "c" / "db.sqlite"
    set_settings(config.Settings(db_path=str(deep)))
    reset_engine()
    eng = _make_engine()
    try:
        assert deep.parent.is_dir()
    finally:
        eng.dispose()
        reset_engine()


def test_init_db_creates_all_tables(backend_imports):
    import app.models.entities  # noqa: F401  register tables on the fresh metadata
    from app.db.session import get_engine, init_db

    init_db()
    eng = get_engine()
    names = {n.lower() for n in inspect(eng).get_table_names()}
    assert {"api_keys", "persons", "face_crops", "system_settings"}.issubset(names)


def test_init_db_is_idempotent(backend_imports):
    import app.models.entities  # noqa: F401
    from app.db.session import init_db

    init_db()
    init_db()
    init_db()


def test_migration_adds_image_sha_column(backend_imports):
    import app.models.entities  # noqa: F401
    from app.db.session import get_engine, init_db

    init_db()
    eng = get_engine()
    with eng.connect() as c:
        rows = c.execute(text("PRAGMA table_info(face_crops)")).all()
    col_names = {row[1] for row in rows}
    assert "image_sha" in col_names


def test_migration_is_safe_to_rerun(backend_imports):
    import app.models.entities  # noqa: F401
    from app.db.session import init_db

    init_db()
    init_db()


def test_session_scope_commits_on_success(backend_imports):
    from uuid import uuid4

    from sqlmodel import select

    from app.db.session import init_db, reset_engine, session_scope
    from app.models.entities import Person

    reset_engine()
    init_db()
    name = f"person-{uuid4().hex[:8]}"
    with session_scope() as s:
        s.add(Person(name=name))
    with session_scope() as s2:
        rows = s2.execute(select(Person).where(Person.name == name)).scalars().all()
    assert len(rows) == 1


def test_session_scope_rolls_back_on_exception(backend_imports):
    from uuid import uuid4

    from sqlmodel import select

    from app.db.session import init_db, reset_engine, session_scope
    from app.models.entities import Person

    reset_engine()
    init_db()
    name = f"rb-{uuid4().hex[:8]}"
    with pytest.raises(RuntimeError, match="boom"):
        with session_scope() as s:
            s.add(Person(name=name))
            raise RuntimeError("boom")
    with session_scope() as s2:
        rows = s2.execute(select(Person).where(Person.name == name)).scalars().all()
    assert rows == []


def test_reset_engine_drops_engine(backend_imports):
    from app.db import session as session_mod

    session_mod.get_engine()
    assert session_mod._engine is not None
    session_mod.reset_engine()
    assert session_mod._engine is None


def test_get_engine_is_singleton(backend_imports):
    from app.db import session as session_mod

    e1 = session_mod.get_engine()
    e2 = session_mod.get_engine()
    assert e1 is e2
    session_mod.reset_engine()
    e3 = session_mod.get_engine()
    assert e3 is not e1
