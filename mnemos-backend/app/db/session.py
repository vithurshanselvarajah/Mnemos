from __future__ import annotations

import os
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlmodel import Session as SQLModelSession, SQLModel, create_engine

from app.core.config import settings

_engine: Engine | None = None


def _make_engine() -> Engine:
    path = settings.db_path
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    url = f"sqlite:///{path}"
    eng = create_engine(
        url,
        echo=False,
        connect_args={"check_same_thread": False},
    )
    return eng


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def init_db() -> None:
    eng = get_engine()
    SQLModel.metadata.create_all(eng)
    from app.db.migrations import runner

    migrations = runner.discover("app.db.migrations")
    runner.run(eng, migrations)


def reset_engine() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


@contextmanager
def session_scope():
    eng = get_engine()
    sess = SQLModelSession(eng, expire_on_commit=False)
    try:
        yield sess
        sess.commit()
    except Exception:
        sess.rollback()
        raise
    finally:
        sess.close()
