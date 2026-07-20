from __future__ import annotations

import json
import logging
import uuid
from contextlib import suppress
from datetime import datetime

import cv2
import numpy as np
from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import select

from app.db.session import session_scope
from app.models.entities import FaceCrop, FaceCropStatus, Person
from app.schemas.dto import (
    AssignRequest,
    FaceCropOut,
    IgnoreRequest,
    MarkNonFaceRequest,
    UnassignedPage,
)
from app.services import vector_repo, websocket_hub
from app.services.cropper import load_crop_jpeg
from app.services.engine import InsightFaceEngine
from app.services.reindex import active_model

router = APIRouter(prefix="/faces", tags=["faces"])
log = logging.getLogger("mnemos.faces")


def _to_out(c: FaceCrop) -> FaceCropOut:
    return FaceCropOut(
        id=c.id,
        person_id=c.person_id,
        image_url=f"/api/v1/crops/{c.id}.jpg",
        bounding_box=json.loads(c.bounding_box) if c.bounding_box else [],
        det_score=c.det_score,
        status=c.status,
        created_at=c.created_at,
    )


@router.get("/unassigned", response_model=UnassignedPage, tags=["faces"])
def list_unassigned(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=24, ge=1, le=200),
) -> UnassignedPage:
    with session_scope() as s:
        total = (
            s.execute(select(FaceCrop).where(FaceCrop.status == FaceCropStatus.UNASSIGNED.value))
            .scalars()
            .all()
        )
        n = len(total)
        start = (page - 1) * page_size
        rows = total[start : start + page_size]
        return UnassignedPage(total=n, page=page, page_size=page_size, items=[_to_out(r) for r in rows])


def _resolve_person(req: AssignRequest, s) -> Person:
    if req.person_id is not None:
        p = s.get(Person, req.person_id)
        if p is None:
            raise HTTPException(status_code=404, detail="person_id not found")
        return p
    if req.new_person_name:
        p = Person(name=req.new_person_name.strip())
        s.add(p)
        s.flush()
        s.refresh(p)
        return p
    raise HTTPException(status_code=400, detail="Provide person_id or new_person_name")


@router.post("/assign", tags=["faces"])
def assign_faces(req: AssignRequest):
    if not req.crop_ids:
        raise HTTPException(status_code=400, detail="crop_ids is required")
    with session_scope() as s:
        person = _resolve_person(req, s)
        crops = s.execute(select(FaceCrop).where(FaceCrop.id.in_(req.crop_ids))).scalars().all()
        if len(crops) != len(req.crop_ids):
            raise HTTPException(status_code=404, detail="one or more crop_ids not found")
        for c in crops:
            c.person_id = person.id
            c.status = FaceCropStatus.ASSIGNED.value
        person.updated_at = datetime.utcnow()
        person_payload = {"id": str(person.id), "name": person.name}

    model = active_model()
    _rebuild_person_averaged(person.id, model)

    websocket_hub.publish(
        {
            "type": "inbox.bulk_changed",
            "person_id": str(person.id),
            "count": len(req.crop_ids),
        }
    )
    return {
        "ok": True,
        "person_id": str(person.id),
        "count": len(req.crop_ids),
        "person": person_payload,
    }


def _rebuild_person_averaged(person_id: uuid.UUID, model_name: str) -> None:
    with session_scope() as s:
        crops = (
            s.execute(
                select(FaceCrop).where(
                    FaceCrop.person_id == person_id,
                    FaceCrop.status == FaceCropStatus.ASSIGNED.value,
                )
            )
            .scalars()
            .all()
        )
        if not crops:
            try:
                vector_repo.delete_for_person_model(person_id, model_name)
            except Exception as e:
                log.warning("vector delete failed: %s", e)
            return
        engine = InsightFaceEngine.current()
        embs: list[np.ndarray] = []
        for c in crops:
            try:
                jpeg = load_crop_jpeg(c.file_path)
            except FileNotFoundError:
                continue
            arr = np.frombuffer(jpeg, dtype=np.uint8)
            img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if img is None:
                continue
            dets = engine.detect(img)
            if not dets:
                continue
            best = max(dets, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
            embs.append(best.embedding)
        if not embs:
            try:
                vector_repo.delete_for_person_model(person_id, model_name)
            except Exception as e:
                log.warning("vector delete failed: %s", e)
            return
        avg = np.mean(np.stack(embs, axis=0), axis=0)
        n = float(np.linalg.norm(avg))
        if n > 0:
            avg = avg / n
        vector_repo.upsert_averaged(person_id, avg, model_name)


@router.post("/mark-non-face", tags=["faces"])
def mark_non_face(req: MarkNonFaceRequest):
    if not req.crop_ids:
        raise HTTPException(status_code=400, detail="crop_ids is required")
    with session_scope() as s:
        crops = s.execute(select(FaceCrop).where(FaceCrop.id.in_(req.crop_ids))).scalars().all()
        for c in crops:
            c.status = FaceCropStatus.NON_FACE.value
            with suppress(Exception):
                vector_repo.delete_for_crop(c.id)
    websocket_hub.publish({"type": "inbox.bulk_changed", "count": len(req.crop_ids)})
    return {"ok": True, "count": len(req.crop_ids)}


@router.post("/ignore", tags=["faces"])
def ignore_crops(req: IgnoreRequest):
    if not req.crop_ids:
        raise HTTPException(status_code=400, detail="crop_ids is required")
    with session_scope() as s:
        crops = s.execute(select(FaceCrop).where(FaceCrop.id.in_(req.crop_ids))).scalars().all()
        for c in crops:
            c.status = FaceCropStatus.IGNORED.value
            with suppress(Exception):
                vector_repo.delete_for_crop(c.id)
    websocket_hub.publish({"type": "inbox.bulk_changed", "count": len(req.crop_ids)})
    return {"ok": True, "count": len(req.crop_ids)}
