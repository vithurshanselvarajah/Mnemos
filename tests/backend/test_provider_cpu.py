from __future__ import annotations

from unittest import mock

import numpy as np
import pytest


@pytest.fixture
def cpu_engine_module(backend_imports):
    from app.providers.cpu import engine

    return engine


def _fake_face(bbox, score=0.95, norm_emb=None, raw_emb=None):
    f = mock.Mock()
    f.bbox = list(bbox)
    f.det_score = score
    if norm_emb is not None:
        f.normed_embedding = norm_emb
        f.embedding = None
    else:
        f.normed_embedding = None
        f.embedding = raw_emb if raw_emb is not None else np.zeros(512, dtype=np.float32)
    return f


def test_cpu_engine_attributes(cpu_engine_module):
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    assert e.provider_name == "cpu"
    assert e.model_name == "buffalo_s"
    assert e.active_providers == ["CPUExecutionProvider"]
    assert e.last_error is None
    assert e.is_loaded() is False


def test_cpu_engine_warmup_success(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    assert e.warmup() is True
    assert e.is_loaded() is True
    assert e.last_error is None


def test_cpu_engine_warmup_failure_sets_error(cpu_engine_module, monkeypatch):
    def _explode(**kw):
        raise RuntimeError("onnx missing")

    monkeypatch.setattr("insightface.app.FaceAnalysis", _explode)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    assert e.warmup() is False
    assert e.is_loaded() is False
    assert e.last_error is not None
    assert "RuntimeError" in e.last_error or "onnx" in e.last_error


def test_cpu_engine_detect_uses_normed_embedding(cpu_engine_module, monkeypatch):
    emb = np.ones(512, dtype=np.float32)
    emb = emb / np.linalg.norm(emb)
    fake_app = mock.Mock()
    fake_app.get.return_value = [_fake_face((0, 0, 10, 10), norm_emb=emb)]
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()
    dets = e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert len(dets) == 1
    assert dets[0].score == 0.95
    assert np.allclose(dets[0].embedding, emb)


def test_cpu_engine_detect_normalizes_raw_embedding(cpu_engine_module, monkeypatch):
    raw = np.full(512, 3.0, dtype=np.float32)
    fake_app = mock.Mock()
    fake_app.get.return_value = [_fake_face((0, 0, 10, 10), raw_emb=raw)]
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()
    dets = e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    n = float(np.linalg.norm(dets[0].embedding))
    assert abs(n - 1.0) < 1e-5


def test_cpu_engine_detect_handles_zero_norm_embedding(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    fake_app.get.return_value = [_fake_face((0, 0, 10, 10), raw_emb=np.zeros(512, dtype=np.float32))]
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()
    dets = e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert np.linalg.norm(dets[0].embedding) == 0


def test_cpu_engine_detect_empty(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    fake_app.get.return_value = []
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()
    dets = e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert dets == []


def test_cpu_engine_switch_model_clears_state(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()
    assert e.is_loaded() is True
    e.switch_model("antelopev2")
    assert e.model_name == "antelopev2"
    assert e.is_loaded() is False


def test_cpu_engine_switch_model_triggers_reload_on_next_detect(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    fake_app.get.return_value = []
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()
    e.switch_model("antelopev2")
    e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert e.is_loaded() is True
    assert e.model_name == "antelopev2"


def test_cpu_engine_detect_lazily_loads(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    fake_app.get.return_value = []
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    assert e.is_loaded() is False
    e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert e.is_loaded() is True


def test_cpu_engine_rw_lock_blocks_writers_during_detect(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    fake_app.get.return_value = []
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()

    cpu_engine_module.CpuEngine._readers = 0
    cpu_engine_module.CpuEngine._writers = 0
    cpu_engine_module.CpuEngine._acquire_read()
    try:
        assert cpu_engine_module.CpuEngine._readers == 1
        assert cpu_engine_module.CpuEngine._writers == 0
    finally:
        cpu_engine_module.CpuEngine._release_read()
    assert cpu_engine_module.CpuEngine._readers == 0


def test_cpu_engine_rw_lock_blocks_readers_during_switch(cpu_engine_module, monkeypatch):
    fake_app = mock.Mock()
    monkeypatch.setattr("insightface.app.FaceAnalysis", lambda **kw: fake_app)
    e = cpu_engine_module.CpuEngine("buffalo_s", det_size=640)
    e.warmup()

    cpu_engine_module.CpuEngine._readers = 0
    cpu_engine_module.CpuEngine._writers = 0
    cpu_engine_module.CpuEngine._acquire_write()
    try:
        assert cpu_engine_module.CpuEngine._writers == 1
    finally:
        cpu_engine_module.CpuEngine._release_write()
    assert cpu_engine_module.CpuEngine._writers == 0
