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
from typing import Any

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


class FakeVectorRepo:
    """In-memory replacement for app.services.vector_repo so tests
    can drive the identify / faces / reindex code paths without a
    live pgvector instance. Tracks all writes so tests can assert
    on them."""

    def __init__(self) -> None:
        self.embeddings: list[dict] = []
        self.search_calls: list[tuple[float, ...]] = []
        self.deleted_for_crop: list[str] = []
        self.deleted_for_person_model: list[tuple[str, str]] = []
        self.delete_all_calls: int = 0
        self.upsert_averaged_calls: list[tuple[str, float, str]] = []
        self.ping_returns: bool = True
        self.search_results: list[list[dict]] = []
        self.search_call_index: int = 0

    def reset(self) -> None:
        self.embeddings.clear()
        self.search_calls.clear()
        self.deleted_for_crop.clear()
        self.deleted_for_person_model.clear()
        self.delete_all_calls = 0
        self.upsert_averaged_calls.clear()
        self.ping_returns = True
        self.search_results.clear()
        self.search_call_index = 0

    def install(self) -> dict[str, Any]:
        repo = self

        def ping() -> bool:
            return repo.ping_returns

        def search_similar(embedding, model_name, limit=5, include_per_crop=True):
            arr = tuple(round(float(x), 6) for x in embedding.tolist())
            repo.search_calls.append(arr)
            if repo.search_results:
                idx = min(repo.search_call_index, len(repo.search_results) - 1)
                repo.search_call_index += 1
                return repo.search_results[idx]
            out = []
            for e in repo.embeddings:
                if e["model_name"] != model_name:
                    continue
                if not include_per_crop and not e["is_averaged"]:
                    continue
                out.append(
                    {
                        "person_id": e["person_id"],
                        "crop_id": e["crop_id"],
                        "is_averaged": e["is_averaged"],
                        "similarity": e.get("similarity", 0.99),
                    }
                )
            out.sort(key=lambda d: d["similarity"], reverse=True)
            return out[:limit]

        def insert_embedding(*, embed_id, crop_id, person_id, embedding, model_name, is_averaged):
            repo.embeddings.append(
                {
                    "embed_id": str(embed_id),
                    "crop_id": str(crop_id),
                    "person_id": str(person_id),
                    "model_name": model_name,
                    "is_averaged": is_averaged,
                    "similarity": 0.99,
                }
            )

        def delete_for_crop(crop_id):
            repo.deleted_for_crop.append(str(crop_id))
            repo.embeddings = [e for e in repo.embeddings if e["crop_id"] != str(crop_id)]

        def delete_for_person_model(person_id, model_name):
            key = (str(person_id), model_name)
            repo.deleted_for_person_model.append(key)
            repo.embeddings = [
                e
                for e in repo.embeddings
                if not (e["person_id"] == str(person_id) and e["model_name"] == model_name)
            ]

        def delete_all():
            repo.delete_all_calls += 1
            repo.embeddings.clear()

        def upsert_averaged(person_id, embedding, model_name):
            arr = [float(x) for x in embedding.tolist()[:3]]
            repo.upsert_averaged_calls.append((str(person_id), arr[0] if arr else 0.0, model_name))
            repo.embeddings = [
                e
                for e in repo.embeddings
                if not (
                    e["person_id"] == str(person_id) and e["model_name"] == model_name and e["is_averaged"]
                )
            ]
            repo.embeddings.append(
                {
                    "embed_id": f"avg-{person_id}-{model_name}",
                    "crop_id": str(person_id),
                    "person_id": str(person_id),
                    "model_name": model_name,
                    "is_averaged": True,
                    "similarity": 0.99,
                }
            )

        def reindex_hnsw():
            return None

        def reset_for_tests():
            repo.reset()

        return {
            "ping": ping,
            "search_similar": search_similar,
            "insert_embedding": insert_embedding,
            "delete_for_crop": delete_for_crop,
            "delete_for_person_model": delete_for_person_model,
            "delete_all": delete_all,
            "upsert_averaged": upsert_averaged,
            "reindex_hnsw": reindex_hnsw,
            "reset_for_tests": reset_for_tests,
        }


@pytest.fixture
def fake_vector_repo(backend_imports):
    """Installs a FakeVectorRepo over the real module. The original
    module attributes are restored on teardown so each test starts
    from a clean slate."""
    from app.services import vector_repo

    fake = FakeVectorRepo()
    overrides = fake.install()
    originals = {name: getattr(vector_repo, name) for name in overrides}
    for name, fn in overrides.items():
        setattr(vector_repo, name, fn)
    try:
        yield fake
    finally:
        for name, value in originals.items():
            setattr(vector_repo, name, value)


def _make_fake_inner(
    *,
    active_providers: list[str] | None = None,
    last_error: str | None = None,
    loaded: bool = True,
    detections: list[Any] | None = None,
    warmup_result: bool = True,
):
    import numpy as np

    from app.providers.base import Detection

    dets: list[Detection] = []
    for d in detections or []:
        bbox = tuple(d["bbox"])
        score = float(d.get("score", 1.0))
        emb_value = d.get("embedding")
        if emb_value is None:
            emb_value = np.zeros(512, dtype=np.float32)
        emb = np.asarray(emb_value, dtype=np.float32)
        dets.append(Detection(bbox=bbox, score=score, embedding=emb))

    class _FakeInner:
        def __init__(self) -> None:
            self._active = list(active_providers or ["CPUExecutionProvider"])
            self._last_error = last_error
            self._loaded = loaded
            self._model_name: str | None = None
            self.detect_calls: int = 0

        @property
        def provider_name(self) -> str:
            return "fake"

        @property
        def model_name(self) -> str:
            return self._model_name or "fake"

        @property
        def active_providers(self) -> list[str]:
            return list(self._active)

        @property
        def last_error(self) -> str | None:
            return self._last_error

        def is_loaded(self) -> bool:
            return self._loaded

        def warmup(self) -> bool:
            if warmup_result:
                self._last_error = None
                self._loaded = True
                return True
            self._last_error = "fake warmup failed"
            return False

        def detect(self, _bgr_image) -> list[Detection]:
            self.detect_calls += 1
            return list(dets)

        def switch_model(self, new_name: str) -> None:
            self._model_name = new_name
            self._loaded = False

    return _FakeInner()


@pytest.fixture
def mock_engine(backend_imports):
    """Replaces `_load_provider` in app.services.engine with a
    factory that returns a fake inner engine. The yielded value is
    a callable: invoke it with the kwargs for `_make_fake_inner` to
    configure the next inner the engine will pick up. The lambda
    bound to `_load_provider` always returns the most recently
    configured inner."""

    from app.services import engine as engine_mod

    class _Box:
        def __init__(self) -> None:
            self.next_inner: Any = None
            self.built: list = []

        def __call__(self, **kwargs) -> Any:
            inner = _make_fake_inner(**kwargs)
            self.built.append(inner)
            self.next_inner = inner
            return inner

        def install(self) -> None:
            box = self

            def _loader(*_a, **_kw):
                return box.next_inner

            self._original = engine_mod._load_provider
            engine_mod._load_provider = _loader
            engine_mod.InsightFaceEngine.reset()

        def uninstall(self) -> None:
            engine_mod._load_provider = self._original
            engine_mod.InsightFaceEngine.reset()

    box = _Box()
    box.install()
    try:
        yield box
    finally:
        box.uninstall()
