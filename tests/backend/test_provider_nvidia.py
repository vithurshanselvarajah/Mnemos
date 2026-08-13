from __future__ import annotations

from unittest import mock

import numpy as np
import pytest


@pytest.fixture
def nvidia_engine_module(backend_imports):
    from app.providers.nvidia import engine

    return engine


def test_detect_cuda_provider_onnxruntime_missing(nvidia_engine_module, monkeypatch):
    """When onnxruntime cannot be imported, last_error is populated."""
    import sys

    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = []
    fake_ort.get_available_providers.side_effect = ImportError("no onnx")
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    info = nvidia_engine_module.detect_cuda_provider()
    assert info["onnxruntime_available"] is True
    assert info["last_error"]


def test_detect_cuda_provider_no_cuda(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)
    info = nvidia_engine_module.detect_cuda_provider()
    assert info["onnxruntime_available"] is True
    assert info["cuda_available"] is False
    assert info["available_providers"] == ["CPUExecutionProvider"]


def test_detect_cuda_provider_with_cuda_no_driver(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider", "CPUExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)

    def _raise(_path):
        raise OSError("no cuda driver")

    monkeypatch.setattr("ctypes.CDLL", _raise)
    info = nvidia_engine_module.detect_cuda_provider()
    assert info["cuda_available"] is True
    assert info["device_count"] == 0


def test_detect_cuda_provider_with_cuda_and_driver(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)

    fake_cdll = mock.MagicMock()
    monkeypatch.setattr("ctypes.CDLL", lambda p: fake_cdll)
    info = nvidia_engine_module.detect_cuda_provider()
    assert info["cuda_available"] is True
    assert info["device_count"] == 1


def test_select_providers_no_onnx(nvidia_engine_module, monkeypatch):
    import sys

    saved = sys.modules.get("onnxruntime")
    sys.modules["onnxruntime"] = mock.MagicMock(side_effect=ImportError("nope"))
    try:
        with pytest.raises(nvidia_engine_module.ProviderNotAvailable):
            nvidia_engine_module._select_providers()
    finally:
        if saved is not None:
            sys.modules["onnxruntime"] = saved
        else:
            sys.modules.pop("onnxruntime", None)


def test_select_providers_no_cuda(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CPUExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)
    with pytest.raises(nvidia_engine_module.ProviderNotAvailable):
        nvidia_engine_module._select_providers()


def test_select_providers_with_cuda(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)
    providers = nvidia_engine_module._select_providers()
    assert "CUDAExecutionProvider" in providers


def test_nvidia_engine_attributes(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)
    e = nvidia_engine_module.NvidiaEngine("buffalo_s", det_size=640)
    assert e.provider_name == "nvidia"
    assert e.model_name == "buffalo_s"
    assert "CUDAExecutionProvider" in e.active_providers
    assert e.is_loaded() is False


def test_nvidia_engine_warmup_success(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)
    fake_app = mock.Mock()
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = nvidia_engine_module.NvidiaEngine("buffalo_s", det_size=640)
    assert e.warmup() is True
    assert e.is_loaded() is True


def test_nvidia_engine_warmup_failure(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)

    def _explode(**kw):
        raise RuntimeError("cuda oom")

    monkeypatch.setattr("insightface.app.FaceAnalysis", _explode)
    e = nvidia_engine_module.NvidiaEngine("buffalo_s", det_size=640)
    assert e.warmup() is False
    assert e.last_error is not None


def test_nvidia_engine_switch_model(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)
    fake_app = mock.Mock()
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = nvidia_engine_module.NvidiaEngine("buffalo_s", det_size=640)
    e.warmup()
    e.switch_model("antelopev2")
    assert e.model_name == "antelopev2"
    assert e.is_loaded() is False


def test_nvidia_engine_detect_with_faces(nvidia_engine_module, monkeypatch):
    fake_ort = mock.MagicMock()
    fake_ort.get_available_providers.return_value = ["CUDAExecutionProvider"]
    monkeypatch.setitem(__import__("sys").modules, "onnxruntime", fake_ort)
    fake_app = mock.Mock()
    emb = np.ones(512, dtype=np.float32)
    emb = emb / np.linalg.norm(emb)
    f = mock.Mock()
    f.bbox = [0, 0, 10, 10]
    f.det_score = 0.9
    f.normed_embedding = emb
    fake_app.get.return_value = [f]
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = nvidia_engine_module.NvidiaEngine("buffalo_s", det_size=640)
    dets = e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert len(dets) == 1
    assert dets[0].score == 0.9
