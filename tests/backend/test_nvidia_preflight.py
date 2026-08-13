"""Tests for the NVIDIA provider lockdown, preflight, and health surface.

These tests verify the contract negotiated with the user:

- The NVIDIA variant NEVER falls back to CPU — it hard-fails.
- The CPU variant never sees a CUDA provider (its active_providers is always
  exactly ``["CPUExecutionProvider"]``).
- ``preflight_provider()`` raises ``SystemExit`` with a helpful message when
  the host lacks the CUDA execution provider, missing onnxruntime, or a
  loadable libcuda.
- ``/healthz`` surfaces the NVIDIA/CUDA state through ``HealthOut.nvidia`` and
  hides it for other providers.
- ``last_error`` is a Protocol-level property on every engine; the
  CPU and NVIDIA engines expose it identically to the Rockchip engine.
"""

from __future__ import annotations

import builtins
import sys
from unittest import mock

import pytest


def _set_provider(backend_imports, monkeypatch, provider: str):
    from app.core import config
    from app.core.config import set_settings

    s = config.Settings(provider=provider)
    set_settings(s)
    monkeypatch.setattr(config, "settings", s)
    return s


def test_nvidia_select_providers_strict(backend_imports, monkeypatch):
    _set_provider(backend_imports, monkeypatch, "nvidia")

    from app.providers.nvidia import engine as nvidia_engine_mod

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        assert nvidia_engine_mod._select_providers() == ["CUDAExecutionProvider"]


def test_nvidia_select_providers_raises_when_no_cuda(backend_imports, monkeypatch):
    _set_provider(backend_imports, monkeypatch, "nvidia")

    from app.providers import base as base_mod
    from app.providers.nvidia import engine as nvidia_engine_mod

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
    with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        with pytest.raises(base_mod.ProviderNotAvailable) as ei:
            nvidia_engine_mod._select_providers()
    assert "CUDAExecutionProvider" in str(ei.value)


def test_nvidia_engine_init_raises_when_no_cuda(backend_imports, monkeypatch):
    _set_provider(backend_imports, monkeypatch, "nvidia")

    from app.providers import base as base_mod
    from app.providers.nvidia import NvidiaEngine

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
    with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        with pytest.raises(base_mod.ProviderNotAvailable):
            NvidiaEngine(model_name="buffalo_s", det_size=640)


def test_nvidia_engine_active_providers(backend_imports, monkeypatch):
    _set_provider(backend_imports, monkeypatch, "nvidia")

    from app.providers.nvidia import NvidiaEngine

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        eng = NvidiaEngine(model_name="buffalo_s", det_size=640)
    assert eng.active_providers == ["CUDAExecutionProvider"]
    assert "CPUExecutionProvider" not in eng.active_providers


def test_nvidia_engine_last_error_initially_none(backend_imports, monkeypatch):
    _set_provider(backend_imports, monkeypatch, "nvidia")

    from app.providers.nvidia import NvidiaEngine

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        eng = NvidiaEngine(model_name="buffalo_s", det_size=640)
    assert eng.last_error is None
    assert not eng.is_loaded()


def test_nvidia_engine_warmup_failure_sets_last_error(backend_imports, monkeypatch):
    _set_provider(backend_imports, monkeypatch, "nvidia")

    from app.providers.nvidia import NvidiaEngine

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]

    with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        eng = NvidiaEngine(model_name="buffalo_s", det_size=640)

    eng._ensure_loaded = mock.MagicMock(side_effect=RuntimeError("cuDNN not initialized"))  # type: ignore[assignment]
    assert eng.warmup() is False
    assert eng.last_error is not None
    assert "cuDNN not initialized" in eng.last_error


def test_cpu_engine_last_error_initially_none(backend_imports):
    from app.providers.cpu import CpuEngine

    eng = CpuEngine(model_name="buffalo_s", det_size=640)
    assert eng.last_error is None
    assert not eng.is_loaded()
    assert eng.active_providers == ["CPUExecutionProvider"]


def test_cpu_engine_warmup_failure_sets_last_error(backend_imports):
    from app.providers.cpu import CpuEngine

    eng = CpuEngine(model_name="buffalo_s", det_size=640)
    eng._ensure_loaded = mock.MagicMock(side_effect=RuntimeError("weights missing"))  # type: ignore[assignment]
    assert eng.warmup() is False
    assert eng.last_error is not None
    assert "weights missing" in eng.last_error


def test_cpu_engine_warmup_success_clears_last_error(backend_imports):
    from app.providers.cpu import CpuEngine

    eng = CpuEngine(model_name="buffalo_s", det_size=640)
    eng._last_error = "stale"
    eng._ensure_loaded = mock.MagicMock()  # type: ignore[assignment]
    assert eng.warmup() is True
    assert eng.last_error is None


def test_preflight_provider_cpu_is_noop(backend_imports, monkeypatch):
    from app.services import model_manifest

    _set_provider(backend_imports, monkeypatch, "cpu")
    model_manifest.preflight_provider()


def test_preflight_provider_nvidia_happy_path(backend_imports, monkeypatch):
    from app.providers import nvidia as nvidia_mod
    from app.services import model_manifest

    _set_provider(backend_imports, monkeypatch, "nvidia")

    info = {
        "onnxruntime_available": True,
        "cuda_available": True,
        "device_count": 1,
        "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "active_providers": ["CUDAExecutionProvider"],
        "last_error": None,
    }
    with mock.patch.object(nvidia_mod, "detect_cuda_provider", return_value=info):
        model_manifest.preflight_provider()


def test_preflight_provider_nvidia_no_onnxruntime(backend_imports, monkeypatch):
    from app.providers import nvidia as nvidia_mod
    from app.services import model_manifest

    _set_provider(backend_imports, monkeypatch, "nvidia")

    info = {
        "onnxruntime_available": False,
        "cuda_available": False,
        "device_count": 0,
        "available_providers": [],
        "active_providers": [],
        "last_error": "ImportError: No module named onnxruntime",
    }
    with mock.patch.object(nvidia_mod, "detect_cuda_provider", return_value=info):
        with pytest.raises(SystemExit) as ei:
            model_manifest.preflight_provider()
    assert "onnxruntime" in str(ei.value).lower()


def test_preflight_provider_nvidia_no_cuda_ep(backend_imports, monkeypatch):
    from app.providers import nvidia as nvidia_mod
    from app.services import model_manifest

    _set_provider(backend_imports, monkeypatch, "nvidia")

    info = {
        "onnxruntime_available": True,
        "cuda_available": False,
        "device_count": 0,
        "available_providers": ["CPUExecutionProvider"],
        "active_providers": [],
        "last_error": None,
    }
    with mock.patch.object(nvidia_mod, "detect_cuda_provider", return_value=info):
        with pytest.raises(SystemExit) as ei:
            model_manifest.preflight_provider()
    msg = str(ei.value)
    assert "CUDAExecutionProvider" in msg
    assert "onnxruntime-gpu" in msg
    assert "provider=cpu" in msg


def test_preflight_provider_nvidia_no_libcuda(backend_imports, monkeypatch):
    from app.providers import nvidia as nvidia_mod
    from app.services import model_manifest

    _set_provider(backend_imports, monkeypatch, "nvidia")

    info = {
        "onnxruntime_available": True,
        "cuda_available": True,
        "device_count": 0,
        "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "active_providers": [],
        "last_error": None,
    }
    with mock.patch.object(nvidia_mod, "detect_cuda_provider", return_value=info):
        with pytest.raises(SystemExit) as ei:
            model_manifest.preflight_provider()
    assert "libcuda" in str(ei.value)


def test_detect_cuda_provider_when_ort_missing(backend_imports, monkeypatch):
    from app.providers import nvidia

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "onnxruntime":
            raise ImportError("No module named onnxruntime")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    info = nvidia.detect_cuda_provider()
    assert info["onnxruntime_available"] is False
    assert info["cuda_available"] is False
    assert info["device_count"] == 0
    assert info["available_providers"] == []
    assert info["last_error"] is not None


def test_detect_cuda_provider_when_cuda_present(backend_imports, monkeypatch):
    from app.providers import nvidia

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]
    with mock.patch.dict(sys.modules, {"onnxruntime": fake_ort}):
        info = nvidia.detect_cuda_provider()
    assert info["onnxruntime_available"] is True
    assert info["cuda_available"] is True
    assert info["available_providers"] == [
        "CUDAExecutionProvider",
        "CPUExecutionProvider",
    ]


def test_healthz_includes_nvidia_when_provider_nvidia(backend_imports, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app
    from app.providers import nvidia as nvidia_mod
    from app.schemas.dto import HealthOut
    from app.services import engine as engine_mod, vector_repo

    info = {
        "onnxruntime_available": True,
        "cuda_available": True,
        "device_count": 1,
        "available_providers": ["CUDAExecutionProvider", "CPUExecutionProvider"],
        "active_providers": ["CUDAExecutionProvider"],
        "last_error": None,
    }

    monkeypatch.setattr(nvidia_mod, "detect_cuda_provider", lambda: info)
    monkeypatch.setattr(
        engine_mod,
        "_load_provider",
        lambda *_a, **_kw: mock.MagicMock(
            is_loaded=lambda: True,
            detect=lambda *_a, **_kw: [],
            switch_model=lambda *_a, **_kw: None,
            warmup=lambda: True,
            active_providers=["CUDAExecutionProvider"],
            last_error=None,
        ),
    )
    monkeypatch.setattr(vector_repo, "ping", lambda: True)
    engine_mod.InsightFaceEngine.reset()

    s = config.Settings(provider="nvidia")
    set_settings(s)
    config.set_settings(s)
    reset_engine()
    init_db()

    app = create_app()
    client = TestClient(app)
    pair = client.post(
        "/api/v1/system/pair",
        json={"master_key": ensure_master_key(), "name": "pytest"},
    )
    assert pair.status_code == 200, pair.text
    key = pair.json()["raw_key"]

    r = client.get("/healthz", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "nvidia"
    assert body["nvidia"] is not None
    assert body["nvidia"]["cuda_available"] is True
    assert body["nvidia"]["active_providers"] == ["CUDAExecutionProvider"]
    assert "CPUExecutionProvider" not in body["nvidia"]["active_providers"]
    HealthOut.model_validate(body)


def test_healthz_omits_nvidia_when_provider_cpu(backend_imports, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.core.security import ensure_master_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    s = config.Settings(provider="cpu")
    set_settings(s)
    config.set_settings(s)
    reset_engine()
    init_db()

    app = create_app()
    client = TestClient(app)
    pair = client.post(
        "/api/v1/system/pair",
        json={"master_key": ensure_master_key(), "name": "pytest"},
    )
    assert pair.status_code == 200, pair.text
    key = pair.json()["raw_key"]

    from app.services import engine as engine_mod, vector_repo

    monkeypatch.setattr(engine_mod.InsightFaceEngine, "is_loaded", lambda self: True)
    monkeypatch.setattr(vector_repo, "ping", lambda: True)

    r = client.get("/healthz", headers={"X-API-Key": key})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["provider"] == "cpu"
    assert body["nvidia"] is None
    assert body["rockchip_soc"] is None


def test_insightface_engine_surfaces_last_error_on_init_failure(backend_imports):
    from app.services import engine as engine_mod

    engine_mod.InsightFaceEngine.reset()
    inner = mock.MagicMock()
    inner.active_providers = ["CUDAExecutionProvider"]
    inner.last_error = "boom"
    with mock.patch.object(engine_mod, "_load_provider", return_value=inner):
        e = engine_mod.InsightFaceEngine(model_name="buffalo_s", det_size=640, provider="nvidia")
        assert e.active_providers() == ["CUDAExecutionProvider"]
        assert e.last_error() == "boom"
    engine_mod.InsightFaceEngine.reset()


def test_insightface_engine_active_providers_when_provider_missing(backend_imports):
    from app.providers import base as base_mod
    from app.services import engine as engine_mod

    engine_mod.InsightFaceEngine.reset()
    with mock.patch.object(engine_mod, "_load_provider", side_effect=base_mod.ProviderNotAvailable("nope")):
        e = engine_mod.InsightFaceEngine(model_name="buffalo_s", det_size=640, provider="nvidia")
        assert e.active_providers() == []
        err = e.last_error()
        assert err is not None
        assert "nope" in err
    engine_mod.InsightFaceEngine.reset()
