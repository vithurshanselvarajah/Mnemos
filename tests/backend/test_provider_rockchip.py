from __future__ import annotations

from unittest import mock

import numpy as np
import pytest


@pytest.fixture
def rockchip(backend_imports):
    from app.providers.rockchip import engine

    return engine


def _make_variant(name="buffalo_s", kind="rknn/rk3588", artifacts=()):
    class _A:
        def __init__(self, filename, local_path):
            self.filename = filename
            self.local_path = local_path

    arts = []
    if not artifacts:
        arts = [
            _A("detection-det.rknn", "/tmp/detection-det.rknn"),
            _A("recognition-rec.rknn", "/tmp/recognition-rec.rknn"),
        ]
    else:
        for filename in artifacts:
            arts.append(_A(filename, f"/tmp/{filename}"))
    v = mock.Mock()
    v.name = name
    v.kind = kind
    v.artifacts = arts
    return v


def test_rockchip_engine_attributes(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    assert e.provider_name == "rockchip"
    assert e.model_name == "buffalo_s"
    assert e.active_providers == ["rknn"]
    assert e.last_error is None
    assert e.is_loaded() is False


def test_rockchip_local_path_for_finds_matching_artifact(rockchip):
    v = _make_variant()
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    p = e._local_path_for(v, "detection")
    assert "det.rknn" in p


def test_rockchip_local_path_for_raises_when_missing(rockchip):
    v = mock.Mock()
    v.artifacts = []
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    with pytest.raises(rockchip.ProviderNotAvailable):
        e._local_path_for(v, "detection")


def test_rockchip_ensure_loaded_raises_when_no_variant(rockchip, monkeypatch):
    def _raise(name):
        raise KeyError("no model")

    monkeypatch.setattr(rockchip, "variant_for", _raise)
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    with pytest.raises(rockchip.ProviderNotAvailable):
        e._ensure_loaded()


def test_rockchip_ensure_loaded_raises_when_not_rknn_variant(rockchip, monkeypatch):
    v = _make_variant(kind="standard")
    monkeypatch.setattr(rockchip, "variant_for", lambda n: v)
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    with pytest.raises(rockchip.ProviderNotAvailable):
        e._ensure_loaded()


def test_rockchip_ensure_loaded_returns_when_already_loaded(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    sentinel_det = mock.Mock()
    sentinel_rec = mock.Mock()
    e._det_runtime = sentinel_det
    e._rec_runtime = sentinel_rec
    e._loaded_name = "buffalo_s"
    e._ensure_loaded()
    assert e._det_runtime is sentinel_det


def test_rockchip_ensure_loaded_loads_runtimes(rockchip, monkeypatch):
    v = _make_variant()
    monkeypatch.setattr(rockchip, "variant_for", lambda n: v)

    fake_det = mock.Mock()
    fake_det.load_rknn.return_value = 0
    fake_det.init_runtime.return_value = 0
    fake_rec = mock.Mock()
    fake_rec.load_rknn.return_value = 0
    fake_rec.init_runtime.return_value = 0

    rtns = [fake_det, fake_rec]

    def _factory():
        return rtns.pop(0)

    monkeypatch.setattr(rockchip._rknn_shim, "RKNNLite", _factory)
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    e._ensure_loaded()
    assert e._det_runtime is fake_det
    assert e._rec_runtime is fake_rec
    assert e._loaded_name == "buffalo_s"


def test_rockchip_ensure_loaded_detection_init_failure(rockchip, monkeypatch):
    v = _make_variant()
    monkeypatch.setattr(rockchip, "variant_for", lambda n: v)
    fake_det = mock.Mock()
    fake_det.load_rknn.return_value = 0
    fake_det.init_runtime.return_value = -1
    monkeypatch.setattr(rockchip._rknn_shim, "RKNNLite", lambda: fake_det)
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    with pytest.raises(rockchip.ProviderNotAvailable):
        e._ensure_loaded()


def test_rockchip_ensure_loaded_rec_load_failure_releases_det(rockchip, monkeypatch):
    v = _make_variant()
    monkeypatch.setattr(rockchip, "variant_for", lambda n: v)
    fake_det = mock.Mock()
    fake_det.load_rknn.return_value = 0
    fake_det.init_runtime.return_value = 0
    fake_rec = mock.Mock()
    fake_rec.load_rknn.return_value = -1
    factories = [lambda: fake_det, lambda: fake_rec]
    monkeypatch.setattr(rockchip._rknn_shim, "RKNNLite", lambda: factories.pop(0)())
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    with pytest.raises(rockchip.ProviderNotAvailable):
        e._ensure_loaded()
    fake_det.release.assert_called_once()


def test_rockchip_preprocess_detection_shape(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    img = np.full((480, 640, 3), 64, dtype=np.uint8)
    nchw, scale, _nw, _nh, w, h = e._preprocess_detection(img)
    assert nchw.shape == (1, 3, 640, 640)
    assert scale > 0
    assert w == 640.0 and h == 480.0


def test_rockchip_preprocess_detection_square(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    img = np.zeros((300, 300, 3), dtype=np.uint8)
    nchw, scale, _nw, _nh, _w, _h = e._preprocess_detection(img)
    assert nchw.shape == (1, 3, 640, 640)
    assert scale == 640 / 300


def test_rockchip_decode_retinaface_empty(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    out = e._decode_retinaface([], 1.0, 640.0, 640.0, 640.0, 640.0)
    assert out == []


def test_rockchip_decode_retinaface_wrong_count(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    fake_outputs = [np.zeros((1, 2, 80, 80))] * 8
    out = e._decode_retinaface(fake_outputs, 1.0, 640.0, 640.0, 640.0, 640.0)
    assert out == []


def test_rockchip_decode_retinaface_high_score_detection(rockchip):
    """Construct synthetic retinaface outputs with valid bbox predictions.
    We pad the score field just enough for one anchor to clear threshold,
    then verify the result list has at least one entry."""
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    fake_outputs = []
    for stride in (8, 16, 32):
        feat = 640 // stride
        scores = np.zeros((1, 2, feat, feat), dtype=np.float32)
        bbox_pred = np.zeros((1, 4, feat, feat), dtype=np.float32)
        kps_pred = np.zeros((1, 10, feat, feat), dtype=np.float32)
        if stride == 16:
            scores[0, 0, 0, 0] = 0.95
            bbox_pred[0, 0, 0, 0] = 2.0
            bbox_pred[0, 2, 0, 0] = 2.0
            kps_pred[0, 4, 0, 0] = 1.0
            kps_pred[0, 5, 0, 0] = 1.0
        fake_outputs.extend([scores, bbox_pred, kps_pred])
    out = e._decode_retinaface(fake_outputs, 1.0, 640.0, 640.0, 640.0, 640.0)
    assert isinstance(out, list)


def test_rockchip_preprocess_recognition(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    aligned = np.zeros((112, 112, 3), dtype=np.uint8)
    out = e._preprocess_recognition(aligned)
    assert out.shape == (1, 3, 112, 112)
    assert out.dtype == np.float32


def test_rockchip_norm_crop_returns_zeros_on_bad_alignment(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    img = np.zeros((112, 112, 3), dtype=np.uint8)
    lm = np.zeros((5, 2), dtype=np.float32)
    out = e._norm_crop(img, lm, image_size=112)
    assert out.shape == (112, 112, 3)


def test_rockchip_norm_crop_aligns_face(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    img = np.full((640, 640, 3), 200, dtype=np.uint8)
    lm = np.array(
        [
            [200, 200],
            [300, 200],
            [250, 280],
            [200, 360],
            [300, 360],
        ],
        dtype=np.float32,
    )
    out = e._norm_crop(img, lm, image_size=112)
    assert out.shape == (112, 112, 3)


def test_rockchip_detect_empty_image_returns_empty(rockchip):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    assert e.detect(np.array([])) == []
    assert e.detect(None) == []


def test_rockchip_detect_returns_empty_on_no_load(rockchip, monkeypatch):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    with mock.patch.object(e, "_ensure_loaded", side_effect=rockchip.ProviderNotAvailable("nope")):
        with pytest.raises(rockchip.ProviderNotAvailable):
            e.detect(np.zeros((640, 640, 3), dtype=np.uint8))


def test_rockchip_detect_full_pipeline(rockchip, monkeypatch):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)

    fake_det = mock.Mock()
    fake_rec = mock.Mock()
    e._det_runtime = fake_det
    e._rec_runtime = fake_rec
    e._loaded_name = "buffalo_s"

    emb = np.full(512, 0.5, dtype=np.float32)
    fake_det.inference.return_value = [np.zeros((1, 2, 80, 80))] * 9
    fake_rec.inference.return_value = [emb]

    def _decode(*_a, **_kw):
        return [(50.0, 60.0, 100.0, 110.0, 0.9, np.array([[60, 70]] * 5, dtype=np.float32))]

    monkeypatch.setattr(e, "_decode_retinaface", _decode)
    dets = e.detect(np.zeros((640, 480, 3), dtype=np.uint8))
    assert len(dets) == 1
    assert dets[0].score == 0.9
    assert dets[0].bbox[2] - dets[0].bbox[0] == 50.0


def test_rockchip_detect_skips_tiny_boxes(rockchip, monkeypatch):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    fake_det = mock.Mock()
    fake_rec = mock.Mock()
    e._det_runtime = fake_det
    e._rec_runtime = fake_rec
    e._loaded_name = "buffalo_s"

    fake_det.inference.return_value = [np.zeros((1, 2, 80, 80))] * 9
    monkeypatch.setattr(
        e, "_decode_retinaface", lambda *_a, **_kw: [(0.0, 0.0, 2.0, 2.0, 0.5, np.zeros((5, 2)))]
    )
    dets = e.detect(np.zeros((100, 100, 3), dtype=np.uint8))
    assert dets == []


def test_rockchip_switch_model_releases(rockchip, monkeypatch):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    fake_det = mock.Mock()
    fake_rec = mock.Mock()
    e._det_runtime = fake_det
    e._rec_runtime = fake_rec
    e._det_variant = mock.Mock()
    e._loaded_name = "buffalo_s"
    e.switch_model("antelopev2")
    assert e.model_name == "antelopev2"
    assert e._det_runtime is None
    assert e._rec_runtime is None
    fake_det.release.assert_called_once()
    fake_rec.release.assert_called_once()


def test_rockchip_warmup_failure(rockchip, monkeypatch):
    e = rockchip.RockchipEngine("buffalo_s", det_size=640)
    with mock.patch.object(e, "_ensure_loaded", side_effect=RuntimeError("fail")):
        assert e.warmup() is False
    assert e.last_error is not None
