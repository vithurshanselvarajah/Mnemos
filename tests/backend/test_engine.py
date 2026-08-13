"""Tests for the InsightFaceEngine wrapper that selects providers."""

from __future__ import annotations

from unittest import mock

import pytest


def test_current_constructs_with_defaults(backend_imports):
    from app.core.config import current_settings
    from app.services.engine import InsightFaceEngine

    InsightFaceEngine.reset()
    e = InsightFaceEngine.current()
    assert e.model_name == current_settings().default_model
    assert e.provider_name == current_settings().provider
    InsightFaceEngine.reset()


def test_current_is_singleton(backend_imports):
    from app.services.engine import InsightFaceEngine

    InsightFaceEngine.reset()
    a = InsightFaceEngine.current()
    b = InsightFaceEngine.current()
    assert a is b
    InsightFaceEngine.reset()


def test_reset_clears_instance(backend_imports):
    from app.services.engine import InsightFaceEngine

    InsightFaceEngine.reset()
    a = InsightFaceEngine.current()
    InsightFaceEngine.reset()
    b = InsightFaceEngine.current()
    assert a is not b
    InsightFaceEngine.reset()


def test_load_provider_dispatches_to_cpu(backend_imports):
    from app.services.engine import _load_provider

    with mock.patch("app.providers.cpu.CpuEngine") as m:
        _load_provider("cpu", "buffalo_s", 640)
        m.assert_called_once_with(model_name="buffalo_s", det_size=640)


def test_load_provider_dispatches_to_nvidia(backend_imports):
    from app.services.engine import _load_provider

    with mock.patch("app.providers.nvidia.NvidiaEngine") as m:
        _load_provider("nvidia", "buffalo_l", 320)
        m.assert_called_once_with(model_name="buffalo_l", det_size=320)


def test_load_provider_dispatches_to_rockchip(backend_imports):
    from app.services.engine import _load_provider

    with mock.patch("app.providers.rockchip.RockchipEngine") as m:
        _load_provider("rockchip", "buffalo_s", 640)
        m.assert_called_once_with(model_name="buffalo_s", det_size=640)


def test_load_provider_raises_for_unknown(backend_imports):
    from app.providers.base import ProviderNotAvailable
    from app.services.engine import _load_provider

    with pytest.raises(ProviderNotAvailable):
        _load_provider("tpu", "buffalo_s", 640)


def test_active_providers_returns_inner_list(mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(active_providers=["CPUExecutionProvider"])
    InsightFaceEngine.reset()
    e = InsightFaceEngine.current()
    assert e.active_providers() == ["CPUExecutionProvider"]
    InsightFaceEngine.reset()


def test_active_providers_empty_when_provider_unavailable(backend_imports):
    from app.providers.base import ProviderNotAvailable
    from app.services.engine import InsightFaceEngine

    with mock.patch("app.services.engine._load_provider", side_effect=ProviderNotAvailable("nope")):
        e = InsightFaceEngine(model_name="x", det_size=640, provider="bogus")
        assert e.active_providers() == []


def test_last_error_returns_inner_value(mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(last_error="cuDNN not initialized")
    InsightFaceEngine.reset()
    e = InsightFaceEngine.current()
    assert e.last_error() == "cuDNN not initialized"
    InsightFaceEngine.reset()


def test_last_error_when_provider_unavailable(backend_imports):
    from app.providers.base import ProviderNotAvailable
    from app.services.engine import InsightFaceEngine

    with mock.patch("app.services.engine._load_provider", side_effect=ProviderNotAvailable("nope")):
        e = InsightFaceEngine(model_name="x", det_size=640, provider="bogus")
        err = e.last_error()
        assert err is not None
        assert "nope" in err


def test_warmup_returns_true_on_success(mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine(warmup_result=True)
    InsightFaceEngine.reset()
    e = InsightFaceEngine.current()
    assert e.warmup() is True
    InsightFaceEngine.reset()


def test_warmup_returns_false_on_provider_failure(backend_imports):
    from app.providers.base import ProviderNotAvailable
    from app.services.engine import InsightFaceEngine

    with mock.patch("app.services.engine._load_provider", side_effect=ProviderNotAvailable("nope")):
        e = InsightFaceEngine(model_name="x", det_size=640, provider="bogus")
        assert e.warmup() is False


def test_detect_delegates_to_inner(mock_engine):
    import numpy as np

    from app.services.engine import InsightFaceEngine

    mock_engine(
        detections=[
            {"bbox": (1.0, 2.0, 3.0, 4.0), "score": 0.9, "embedding": np.zeros(512, dtype=np.float32)}
        ]
    )
    InsightFaceEngine.reset()
    e = InsightFaceEngine.current()
    out = e.detect(np.zeros((640, 640, 3), dtype=np.uint8))
    assert len(out) == 1
    assert out[0].bbox == (1.0, 2.0, 3.0, 4.0)
    InsightFaceEngine.reset()


def test_switch_model_updates_name(mock_engine):
    from app.services.engine import InsightFaceEngine

    mock_engine()
    InsightFaceEngine.reset()
    e = InsightFaceEngine.current()
    e.switch_model("buffalo_l")
    assert e.model_name == "buffalo_l"
    InsightFaceEngine.reset()


def test_provider_name_attribute(backend_imports):
    from app.core.config import Settings, set_settings
    from app.services.engine import InsightFaceEngine

    s = Settings(provider="nvidia")
    set_settings(s)
    e = InsightFaceEngine(model_name="buffalo_s", det_size=640, provider="nvidia")
    assert e.provider_name == "nvidia"
    InsightFaceEngine.reset()
    set_settings(None)
