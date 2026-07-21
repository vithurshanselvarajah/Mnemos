from __future__ import annotations

import logging
import os
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from app.core.config import settings
from app.db.session import session_scope
from app.models.entities import FaceCrop
from app.services.cropper import load_crop_jpeg

router = APIRouter(prefix="/crops", tags=["crops"])
log = logging.getLogger("mnemos.crops")


@router.get(
    "/{filename}",
    tags=["crops"],
    summary="Get a face crop image",
    description=(
        "Returns the stored JPEG for a face crop. The `filename` is the crop UUID with a `.jpg` "
        "extension (e.g. `7c4a8d09-ca38-4e2e-b27a-2c0e6a2c5e1f.jpg`). Returns 404 if the crop "
        "doesn't exist or the file is missing from disk."
    ),
    responses={
        200: {"content": {"image/jpeg": {}}, "description": "The crop JPEG"},
        404: {"description": "Crop not found or file missing"},
    },
)
def get_crop(filename: str) -> Response:
    if not filename.endswith(".jpg"):
        raise HTTPException(status_code=404, detail="not found")
    try:
        crop_id = uuid.UUID(filename[:-4])
    except ValueError:
        raise HTTPException(status_code=404, detail="not found")
    with session_scope() as s:
        row = s.get(FaceCrop, crop_id)
        if row is None:
            raise HTTPException(status_code=404, detail="not found")
        rel_path = row.file_path
    abs_path = os.path.join(settings.crops_dir, rel_path)
    if not os.path.isfile(abs_path):
        raise HTTPException(status_code=404, detail="crop file missing on disk")
    data = load_crop_jpeg(rel_path)
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=300"})
