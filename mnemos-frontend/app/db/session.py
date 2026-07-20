from __future__ import annotations

import logging
import os
from contextlib import contextmanager

from sqlalchemy.engine import Engine
from sqlmodel import Session as SQLModelSession, SQLModel, create_engine

from app.core.config import settings

log = logging.getLogger("mnemos.frontend.db")

_engine: Engine | None = None


def _make_engine() -> Engine:
    path = settings.db_path
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    return create_engine(f"sqlite:///{path}", echo=False, connect_args={"check_same_thread": False})


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _engine = _make_engine()
    return _engine


def init_db() -> None:
    eng = get_engine()
    SQLModel.metadata.create_all(eng)


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
