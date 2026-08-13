"""Tests for the cropper service (padded bbox + save/load/delete)."""

from __future__ import annotations

import io

import numpy as np
from PIL import Image


def test_padded_bbox_zero_pad(backend_imports):
    from app.services.cropper import padded_bbox

    out = padded_bbox((10, 20, 30, 40), (100, 100), pad_fraction=0.0)
    assert out == (10, 20, 30, 40)


def test_padded_bbox_grows_uniformly(backend_imports):
    from app.services.cropper import padded_bbox

    out = padded_bbox((20, 30, 60, 90), (200, 200), pad_fraction=0.5)
    assert out == (0, 0, 80, 120)


def test_padded_bbox_clamps_to_image(backend_imports):
    from app.services.cropper import padded_bbox

    out = padded_bbox((0, 0, 10, 10), (50, 50), pad_fraction=1.0)
    assert out == (0, 0, 20, 20)

    out = padded_bbox((45, 45, 50, 50), (50, 50), pad_fraction=0.5)
    assert out == (42, 42, 50, 50)


def test_padded_bbox_uses_default_pad_from_settings(backend_imports):
    from app.core import config
    from app.core.config import set_settings
    from app.services.cropper import padded_bbox

    set_settings(config.Settings(crop_pad_fraction=0.1))
    out = padded_bbox((10, 20, 30, 40), (100, 100))
    assert out[0] == 8
    assert out[1] == 18
    assert out[2] == 32
    assert out[3] == 42
    set_settings(None)


def test_crop_and_save_padded_writes_jpeg(backend_imports, tmp_root):
    from app.core import config
    from app.core.config import set_settings
    from app.services.cropper import crop_and_save_padded, load_crop_jpeg

    set_settings(config.Settings(crops_dir=str(tmp_root / "crops")))
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    img[:, :] = (255, 0, 0)
    data, rel = crop_and_save_padded(img, (10, 10, 50, 50))
    assert data[:3] == b"\xff\xd8\xff"
    assert rel.endswith(".jpg")
    out = load_crop_jpeg(rel)
    assert out[:3] == b"\xff\xd8\xff"
    assert out == data
    set_settings(None)


def test_crop_and_save_padded_creates_crops_dir(backend_imports, tmp_root):
    from app.core import config
    from app.core.config import set_settings
    from app.services.cropper import crop_and_save_padded

    target = tmp_root / "new_crops"
    set_settings(config.Settings(crops_dir=str(target)))
    img = np.zeros((40, 40, 3), dtype=np.uint8)
    _data, rel = crop_and_save_padded(img, (5, 5, 15, 15))
    assert (target / rel).is_file()
    set_settings(None)


def test_crop_and_save_padded_rejects_invalid_bbox(backend_imports, tmp_root):
    import pytest

    from app.core import config
    from app.core.config import set_settings
    from app.services.cropper import crop_and_save_padded

    set_settings(config.Settings(crops_dir=str(tmp_root / "crops")))
    img = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        crop_and_save_padded(img, (10, 10, 5, 5))
    set_settings(None)


def test_delete_crop_files_removes_main_and_thumbs(backend_imports, tmp_root):
    from app.core import config
    from app.core.config import set_settings
    from app.services.cropper import delete_crop_files

    set_settings(config.Settings(crops_dir=str(tmp_root / "crops")))
    rel = "abc.jpg"
    (tmp_root / "crops").mkdir(parents=True, exist_ok=True)
    (tmp_root / "crops" / rel).write_bytes(b"hello")
    (tmp_root / "crops" / "abc.cropped.jpg").write_bytes(b"x")
    (tmp_root / "crops" / "abc_thumb.jpg").write_bytes(b"x")
    (tmp_root / "crops" / "abc.thumb.jpg").write_bytes(b"x")
    delete_crop_files(rel)
    assert not (tmp_root / "crops" / rel).exists()
    assert not (tmp_root / "crops" / "abc.cropped.jpg").exists()
    assert not (tmp_root / "crops" / "abc_thumb.jpg").exists()
    assert not (tmp_root / "crops" / "abc.thumb.jpg").exists()
    set_settings(None)


def test_delete_crop_files_handles_missing_gracefully(backend_imports, tmp_root):
    from app.core import config
    from app.core.config import set_settings
    from app.services.cropper import delete_crop_files

    set_settings(config.Settings(crops_dir=str(tmp_root / "crops")))
    (tmp_root / "crops").mkdir(parents=True, exist_ok=True)
    delete_crop_files("does-not-exist.jpg")
    delete_crop_files("")
    set_settings(None)


def test_cropped_jpeg_is_valid_image(backend_imports, tmp_root):
    from app.core import config
    from app.core.config import set_settings
    from app.services.cropper import crop_and_save_padded

    set_settings(config.Settings(crops_dir=str(tmp_root / "crops")))
    img = np.full((80, 80, 3), 128, dtype=np.uint8)
    data, _rel = crop_and_save_padded(img, (10, 10, 70, 70))
    pil = Image.open(io.BytesIO(data))
    assert pil.format == "JPEG"
    assert pil.size[0] > 0
    assert pil.size[1] > 0
    set_settings(None)
