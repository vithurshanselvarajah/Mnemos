from __future__ import annotations

import logging
import os
import uuid

import numpy as np
from PIL import Image

from app.core.config import settings

log = logging.getLogger("mnemos.cropper")


def padded_bbox(
    bbox: tuple[float, float, float, float],
    image_size: tuple[int, int],
    pad_fraction: float | None = None,
) -> tuple[int, int, int, int]:
    if pad_fraction is None:
        pad_fraction = settings.crop_pad_fraction
    x1, y1, x2, y2 = bbox
    w, h = image_size
    width = x2 - x1
    height = y2 - y1
    pad_x = pad_fraction * width
    pad_y = pad_fraction * height
    nx1 = max(0, round(x1 - pad_x))
    ny1 = max(0, round(y1 - pad_y))
    nx2 = min(w, round(x2 + pad_x))
    ny2 = min(h, round(y2 + pad_y))
    return nx1, ny1, nx2, ny2


def crop_and_save_padded(bgr_image: np.ndarray, bbox) -> tuple[bytes, str]:
    h, w = bgr_image.shape[:2]
    px1, py1, px2, py2 = padded_bbox(tuple(map(float, bbox)), (w, h))
    if px2 <= px1 or py2 <= py1:
        raise ValueError("Invalid padded crop area")

    rgb = bgr_image[:, :, ::-1]
    pil = Image.fromarray(rgb)
    cropped = pil.crop((px1, py1, px2, py2))

    crop_id = uuid.uuid4()
    rel_path = f"{crop_id}.jpg"
    abs_path = os.path.join(settings.crops_dir, rel_path)
    os.makedirs(settings.crops_dir, exist_ok=True)
    cropped.save(abs_path, format="JPEG", quality=92, optimize=True)
    with open(abs_path, "rb") as f:
        data = f.read()
    return data, rel_path


def load_crop_jpeg(rel_path: str) -> bytes:
    abs_path = os.path.join(settings.crops_dir, rel_path)
    with open(abs_path, "rb") as f:
        return f.read()


def delete_crop_files(rel_path: str) -> None:
    if not rel_path:
        return
    crop_abs = os.path.join(settings.crops_dir, rel_path)
    try:
        if os.path.isfile(crop_abs):
            os.remove(crop_abs)
    except OSError as e:
        log.warning("failed to remove crop %s: %s", crop_abs, e)
    stem, _ = os.path.splitext(rel_path)
    for ext in (".cropped.jpg", "_thumb.jpg", ".thumb.jpg"):
        thumb_rel = f"{stem}{ext}"
        thumb_abs = os.path.join(settings.crops_dir, thumb_rel)
        try:
            if os.path.isfile(thumb_abs):
                os.remove(thumb_abs)
        except OSError:
            pass
