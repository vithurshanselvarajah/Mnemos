from __future__ import annotations

import uuid

import pytest


@pytest.fixture
def fe_db(frontend_imports):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.models import entities  # noqa: F401  -- side effect: registers tables on SQLModel.metadata

    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    return


def test_engine_creates_parent_dirs(fe_db, tmp_path, monkeypatch):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import get_engine, reset_engine

    db_path = tmp_path / "deeply" / "nested" / "path" / "test.db"
    monkeypatch.setenv("MNEMOS_FE_DB_PATH", str(db_path))
    config.set_settings(None)
    set_settings(None)
    reset_engine()
    get_engine()
    assert db_path.parent.is_dir()


def test_init_db_creates_tables(fe_db):
    from sqlalchemy import inspect

    from app.db.session import get_engine

    eng = get_engine()
    inspector = inspect(eng)
    tables = set(inspector.get_table_names())
    assert {"users", "sessions", "backend_nodes"} <= tables


def test_init_db_idempotent(fe_db):
    """Calling init_db twice should not raise."""
    from app.db.session import init_db

    init_db()
    init_db()


def test_session_scope_commit(fe_db):
    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="alice", password_hash="x", role=UserRole.ADMIN.value))
    with session_scope() as s:
        row = s.query(User).filter(User.username == "alice").first()
        assert row is not None
        assert row.role == "Admin"


def test_session_scope_rollback(fe_db):
    from app.db.session import session_scope
    from app.models.entities import User

    try:
        with session_scope() as s:
            s.add(User(username="bob", password_hash="x"))
            raise RuntimeError("boom")
    except RuntimeError:
        pass
    with session_scope() as s:
        row = s.query(User).filter(User.username == "bob").first()
        assert row is None


def test_get_engine_singleton(fe_db):
    from app.db.session import get_engine

    e1 = get_engine()
    e2 = get_engine()
    assert e1 is e2


def test_reset_engine_disposes(fe_db):
    from app.db.session import get_engine, reset_engine

    e1 = get_engine()
    reset_engine()
    e2 = get_engine()
    assert e1 is not e2


def test_session_create_and_query(fe_db):
    from datetime import datetime, timedelta

    from app.db.session import session_scope
    from app.models.entities import Session, User, UserRole

    user_id = uuid.uuid4()
    with session_scope() as s:
        s.add(User(id=user_id, username="carol", password_hash="x", role=UserRole.OPERATOR.value))
        s.add(
            Session(
                user_id=user_id,
                session_token="tok",
                expires_at=datetime.utcnow() + timedelta(hours=1),
            )
        )
    with session_scope() as s:
        row = s.query(Session).filter(Session.session_token == "tok").first()
        assert row is not None
        assert row.user_id == user_id


def test_user_unique_username(fe_db):
    from sqlalchemy.exc import IntegrityError

    from app.db.session import session_scope
    from app.models.entities import User, UserRole

    with session_scope() as s:
        s.add(User(username="dup", password_hash="x", role=UserRole.OPERATOR.value))
    with pytest.raises(IntegrityError):
        with session_scope() as s:
            s.add(User(username="dup", password_hash="y", role=UserRole.OPERATOR.value))


def test_backend_node_roundtrip(fe_db):
    from app.db.session import session_scope
    from app.models.entities import BackendNode

    with session_scope() as s:
        s.add(BackendNode(name="n1", base_url="http://x", api_key="k"))
    with session_scope() as s:
        row = s.query(BackendNode).filter(BackendNode.name == "n1").first()
        assert row is not None
        assert row.base_url == "http://x"
        assert row.api_key == "k"
        assert row.is_default is True
