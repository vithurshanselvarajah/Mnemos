# Shared pytest fixtures for Mnemos V2.
#
# The backend and frontend each have their own `app.*` Python
# package, so they cannot both be on `sys.path` at the same time
# (Python would resolve `app` to whichever one was added first,
# and the other would shadow / collide). Each per-service fixture
# here swaps the active sys.path so only the relevant package
# is importable during that test.

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = REPO_ROOT / "mnemos-backend"
FRONTEND_ROOT = REPO_ROOT / "mnemos-frontend"


def _isolate_env(tmp_path: Path) -> dict:
    db_path = tmp_path / "backend.db"
    crops_dir = tmp_path / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    fe_db_path = tmp_path / "frontend.db"
    return {
        "MNEMOS_DB_PATH": str(db_path),
        "MNEMOS_CROPS_DIR": str(crops_dir),
        "MNEMOS_VECTOR_DSN": "postgresql://mnemos:mnemos@127.0.0.1:1/mnemos_vectors",
        "MNEMOS_API_HOST": "127.0.0.1",
        "MNEMOS_API_PORT": "0",
        "MNEMOS_FE_DB_PATH": str(fe_db_path),
        "MNEMOS_FE_DEFAULT_BACKEND_URL": "http://mnemos-backend-test:8000",
        "MNEMOS_FE_LISTEN_HOST": "127.0.0.1",
        "MNEMOS_FE_LISTEN_PORT": "0",
        "MNEMOS_FE_SECRET": "test-secret-do-not-use-in-prod-32-bytes-min",
    }


@contextmanager
def _swap_sys_path(new_path: str):
    """Temporarily put `new_path` at the front of sys.path and
    evict any pre-existing `app` package from sys.modules so the
    next import resolves to the new path. Also swaps in a fresh
    `SQLModel.metadata` so the SQLModel class registry doesn't
    accumulate duplicate tables across tests."""
    from sqlalchemy import MetaData

    try:
        from sqlmodel import SQLModel
    except ImportError:
        SQLModel = None
    if SQLModel is not None:
        saved_metadata = SQLModel.metadata
        SQLModel.metadata = MetaData()
    old_modules = {k: v for k, v in list(sys.modules.items()) if k == "app" or k.startswith("app.")}
    for k in old_modules:
        del sys.modules[k]
    had_path = new_path in sys.path
    if not had_path:
        sys.path.insert(0, new_path)
    try:
        yield
    finally:
        if not had_path:
            try:
                sys.path.remove(new_path)
            except ValueError:
                pass
        for k in old_modules:
            sys.modules.pop(k, None)
        for k in [m for m in sys.modules if m == "app" or m.startswith("app.")]:
            sys.modules.pop(k, None)
        if SQLModel is not None:
            SQLModel.metadata = saved_metadata


@pytest.fixture
def tmp_root() -> Iterator[Path]:
    base = Path(tempfile.mkdtemp(prefix="mnemos-pytest-"))
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


@pytest.fixture
def chdir_backend() -> Iterator[Path]:
    saved = os.getcwd()
    os.chdir(BACKEND_ROOT)
    try:
        yield BACKEND_ROOT
    finally:
        os.chdir(saved)


@pytest.fixture
def chdir_frontend() -> Iterator[Path]:
    saved = os.getcwd()
    os.chdir(FRONTEND_ROOT)
    try:
        yield FRONTEND_ROOT
    finally:
        os.chdir(saved)


@pytest.fixture
def backend_env(tmp_root: Path) -> Iterator[dict]:
    env = _isolate_env(tmp_root)
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield env
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture
def frontend_env(tmp_root: Path) -> Iterator[dict]:
    env = _isolate_env(tmp_root)
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield env
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


@pytest.fixture
def backend_imports(backend_env, chdir_backend) -> Iterator[Path]:
    """Sets up env + cwd + sys.path so the backend's `app.*` is
    the only thing importable. Use this in any backend test that
    imports the FastAPI app or its services."""
    with _swap_sys_path(str(BACKEND_ROOT)):
        yield BACKEND_ROOT


@pytest.fixture
def frontend_imports(frontend_env, chdir_frontend) -> Iterator[Path]:
    """Sets up env + cwd + sys.path so the frontend's `app.*` is
    the only thing importable. Use this in any frontend test that
    imports the FastAPI app or its services."""
    with _swap_sys_path(str(FRONTEND_ROOT)):
        yield FRONTEND_ROOT


@pytest.fixture
def unique_name() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"
