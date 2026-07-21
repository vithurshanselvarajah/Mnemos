from __future__ import annotations

import hashlib
import io
import json
import logging
import uuid

import cv2
import numpy as np
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from PIL import Image
from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models.entities import FaceCrop, FaceCropStatus, Person
from app.schemas.dto import (
    BoundingBox,
    IdentifyMatch,
    IdentifyResponse,
    IdentifyUnknownFace,
)
from app.services import vector_repo, websocket_hub
from app.services.cropper import crop_and_save_padded
from app.services.engine import InsightFaceEngine
from app.services.reindex import active_model

router = APIRouter(prefix="/identify", tags=["identify"])
log = logging.getLogger("mnemos.identify")


_DEDUP_IOU = 0.80
_DEDUP_COSINE_DIST = 0.04
_CROSS_IMG_COSINE_DIST = 0.02


def _iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)
    iw = max(0.0, inter_x2 - inter_x1)
    ih = max(0.0, inter_y2 - inter_y1)
    inter = iw * ih
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def _cosine_dist(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 1.0
    sim = float(np.dot(a, b) / (na * nb))
    return 1.0 - sim


def _dedupe_within_request(dets) -> list:
    if len(dets) <= 1:
        return list(dets)
    kept: list = []
    for d in dets:
        merged = False
        for k in kept:
            if (
                _iou(d.bbox, k.bbox) >= _DEDUP_IOU
                and _cosine_dist(d.embedding, k.embedding) <= _DEDUP_COSINE_DIST
            ):
                if d.score > k.score:
                    kept.remove(k)
                    kept.append(d)
                merged = True
                break
        if not merged:
            kept.append(d)
    if len(dets) != len(kept):
        log.info("within-request dedup: %d -> %d detections", len(dets), len(kept))
    return kept


def _find_duplicate_crop(
    embedding: np.ndarray,
    image_sha: str,
    bbox: tuple[float, float, float, float],
) -> uuid.UUID | None:
    with session_scope() as s:
        if image_sha:
            existing = (
                s.query(FaceCrop)
                .filter(
                    FaceCrop.image_sha == image_sha,
                    FaceCrop.status == FaceCropStatus.UNASSIGNED.value,
                )
                .order_by(FaceCrop.created_at.desc())
                .all()
            )
            for cand in existing:
                try:
                    cand_bbox = tuple(json.loads(cand.bounding_box))
                except Exception:
                    continue
                if _iou(bbox, cand_bbox) >= _DEDUP_IOU:
                    return cand.id
    try:
        neighbors = vector_repo.search_similar(
            embedding,
            active_model(),
            limit=5,
            include_per_crop=True,
        )
    except Exception as e:
        log.debug("dedup neighbor search failed: %s", e)
        return None
    with session_scope() as s:
        for n in neighbors:
            if n.get("is_averaged"):
                continue
            crop_id_str = n.get("crop_id")
            if not crop_id_str:
                continue
            if float(n["similarity"]) >= (1.0 - _CROSS_IMG_COSINE_DIST):
                try:
                    crop_id = uuid.UUID(str(crop_id_str))
                except ValueError:
                    continue
                row = s.get(FaceCrop, crop_id)
                if row is not None and row.status == FaceCropStatus.UNASSIGNED.value:
                    return row.id
    return None


def _read_image(data: bytes) -> np.ndarray:
    arr = np.frombuffer(data, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None:
        try:
            pil = Image.open(io.BytesIO(data)).convert("RGB")
            img = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Unsupported image: {e}") from e
    return img


def _custom_threshold_for(person_id: uuid.UUID | None) -> float | None:
    if person_id is None:
        return None
    with session_scope() as s:
        p = s.get(Person, person_id)
        if p and p.custom_threshold is not None:
            return float(p.custom_threshold)
    return None


def _match(embedding: np.ndarray, model: str, base_threshold: float) -> IdentifyMatch | None:
    neighbors = vector_repo.search_similar(embedding, model, limit=3)
    if not neighbors:
        return None
    best = neighbors[0]
    sim = float(best["similarity"])
    dist = 1.0 - sim
    threshold = base_threshold
    custom = _custom_threshold_for(uuid.UUID(best["person_id"]))
    if custom is not None:
        threshold = custom
    if dist > threshold:
        return None
    with session_scope() as s:
        p = s.get(Person, uuid.UUID(best["person_id"]))
        if p is None:
            return None
        best_crop = (
            s.execute(
                select(FaceCrop)
                .where(
                    FaceCrop.person_id == p.id,
                    FaceCrop.status == FaceCropStatus.ASSIGNED.value,
                )
                .order_by(FaceCrop.det_score.desc(), FaceCrop.created_at.desc())
                .limit(1)
            )
            .scalars()
            .first()
        )
        fallback_url = f"/api/v1/crops/{best_crop.id}.jpg" if best_crop else None
        return IdentifyMatch(
            person_id=p.id,
            name=p.name,
            confidence=sim,
            image_url=fallback_url,
        )


@router.post(
    "",
    response_model=IdentifyResponse,
    tags=["identify"],
    summary="Identify faces in an image",
    description=(
        "Upload an image as `multipart/form-data` with the `file` field. Detects every face, "
        "matches each against the active model's embedding space, and returns one entry per "
        "detection. Recognized faces include the matched person, confidence, and a base64 data URL "
        "of the cropped face. Unknown faces are saved to disk and returned with a `crop_id` for "
        "later assignment via `/api/v1/faces/assign`. Within-request duplicates and re-uploads of "
        "the same image are deduplicated. The active model must be loaded (see `GET /healthz`); "
        "if not, call `GET /api/v1/models/warmup` first and wait for the `warmup.done` WebSocket event."
    ),
)
async def identify(request: Request, file: UploadFile = File(...)) -> IdentifyResponse:
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=400, detail="Empty upload")
    img = _read_image(raw)
    _h, _w = img.shape[:2]

    image_sha = hashlib.sha256(raw).hexdigest()

    model = active_model()
    engine = InsightFaceEngine.current()
    dets = engine.detect(img)
    dets = _dedupe_within_request(dets)

    recognized: list[IdentifyMatch] = []
    unknowns: list[IdentifyUnknownFace] = []
    base_threshold = float(settings.default_threshold)
    skipped_duplicates = 0

    for d in dets:
        x1, y1, x2, y2 = d.bbox
        if (x2 - x1) < settings.min_face_px and (y2 - y1) < settings.min_face_px:
            log.debug("skipping small detection: %s", d.bbox)
            continue
        m = _match(d.embedding, model, base_threshold)
        if m is not None:
            try:
                jpeg_bytes, _rel = crop_and_save_padded(img, d.bbox)
                import base64

                m.image_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
                m.image_is_data = True
            except Exception as e:
                log.debug("match crop failed: %s", e)
            recognized.append(m)
            continue
        existing_id = _find_duplicate_crop(d.embedding, image_sha, (x1, y1, x2, y2))
        if existing_id is not None:
            log.info("dedup: reusing existing crop %s", existing_id)
            skipped_duplicates += 1
            url = f"/api/v1/crops/{existing_id}.jpg"
            unknowns.append(
                IdentifyUnknownFace(
                    crop_id=existing_id,
                    image_url=url,
                    bounding_box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                    det_score=float(d.score),
                )
            )
            continue
        try:
            jpeg_bytes, rel_path = crop_and_save_padded(img, d.bbox)
        except Exception as e:
            log.warning("crop failed: %s", e)
            continue
        crop_id = uuid.uuid4()
        with session_scope() as s:
            s.add(
                FaceCrop(
                    id=crop_id,
                    person_id=None,
                    file_path=rel_path,
                    bounding_box=json.dumps([x1, y1, x2, y2]),
                    det_score=float(d.score),
                    status=FaceCropStatus.UNASSIGNED.value,
                    image_sha=image_sha,
                )
            )
        url = f"/api/v1/crops/{crop_id}.jpg"
        unknowns.append(
            IdentifyUnknownFace(
                crop_id=crop_id,
                image_url=url,
                bounding_box=BoundingBox(x1=x1, y1=y1, x2=x2, y2=y2),
                det_score=float(d.score),
            )
        )
        websocket_hub.publish(
            {
                "type": "inbox.new_face",
                "crop_id": str(crop_id),
                "image_url": url,
                "det_score": float(d.score),
            }
        )

    return IdentifyResponse(
        recognized=recognized,
        unknown_count=len(unknowns),
        unknown_faces=unknowns,
        duplicates_skipped=skipped_duplicates,
    )
