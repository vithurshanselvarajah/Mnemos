from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture
def providers(backend_imports):
    from app.providers import base

    return base


def test_detection_dataclass_constructs(providers):
    emb = np.ones(512, dtype=np.float32)
    d = providers.Detection(bbox=(0.0, 0.0, 10.0, 10.0), score=0.9, embedding=emb)
    assert d.bbox == (0.0, 0.0, 10.0, 10.0)
    assert d.score == 0.9
    assert d.embedding is emb


def test_detection_is_frozen(providers):
    d = providers.Detection(bbox=(0.0, 0.0, 1.0, 1.0), score=0.5, embedding=np.zeros(4))
    with pytest.raises((AttributeError, Exception)):
        d.score = 0.9  # type: ignore[misc]


def test_provider_not_available_is_runtime_error(providers):
    with pytest.raises(providers.ProviderNotAvailable):
        raise providers.ProviderNotAvailable("nope")


def test_inference_engine_protocol_has_required_members(providers):
    members = [m for m in dir(providers.InferenceEngine) if not m.startswith("__")]
    assert "provider_name" in members
    assert "model_name" in members
    assert "active_providers" in members
    assert "warmup" in members
    assert "is_loaded" in members
    assert "detect" in members
    assert "switch_model" in members
    assert "last_error" in members
