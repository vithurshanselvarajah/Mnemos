from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select

from app.api.deps import require_full_admin
from app.db.session import session_scope
from app.models.entities import ApiKey, FaceCrop, FaceCropStatus, Person
from app.schemas.dto import FaceCropOut, PersonCreate, PersonOut, PersonUpdate
from app.services import vector_repo
from app.services.cropper import delete_crop_files

router = APIRouter(prefix="/persons", tags=["persons"])
log = logging.getLogger("mnemos.persons")


def _best_crop_for(s, person_id: uuid.UUID) -> FaceCrop | None:
    return (
        s.execute(
            select(FaceCrop)
            .where(
                FaceCrop.person_id == person_id,
                FaceCrop.status == FaceCropStatus.ASSIGNED.value,
            )
            .order_by(FaceCrop.det_score.desc(), FaceCrop.created_at.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def _to_out(s, p: Person) -> PersonOut:
    count = int(
        s.execute(
            select(func.count(FaceCrop.id)).where(
                FaceCrop.person_id == p.id,
                FaceCrop.status == FaceCropStatus.ASSIGNED.value,
            )
        ).scalar_one()
    )
    best = _best_crop_for(s, p.id)
    return PersonOut(
        id=p.id,
        name=p.name,
        custom_threshold=p.custom_threshold,
        sample_count=count,
        thumbnail_url=f"/api/v1/crops/{best.id}.jpg" if best else None,
        best_det_score=float(best.det_score) if best else 0.0,
        created_at=p.created_at,
        updated_at=p.updated_at,
    )


@router.get("", response_model=list[PersonOut], tags=["persons"])
def list_persons() -> list[PersonOut]:
    with session_scope() as s:
        rows = s.execute(select(Person).order_by(Person.name.asc())).scalars().all()
        return [_to_out(s, p) for p in rows]


@router.post("", response_model=PersonOut, tags=["persons"])
def create_person(req: PersonCreate, _: ApiKey = Depends(require_full_admin)) -> PersonOut:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    with session_scope() as s:
        existing = s.execute(select(Person).where(func.lower(Person.name) == name.lower())).scalars().first()
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A person named '{existing.name}' already exists.",
            )
        p = Person(name=name, custom_threshold=req.custom_threshold)
        s.add(p)
        s.flush()
        s.refresh(p)
        return _to_out(s, p)


@router.patch("/{person_id}", response_model=PersonOut, tags=["persons"])
def update_person(
    person_id: uuid.UUID, req: PersonUpdate, _: ApiKey = Depends(require_full_admin)
) -> PersonOut:
    with session_scope() as s:
        p = s.get(Person, person_id)
        if p is None:
            raise HTTPException(status_code=404, detail="person not found")
        if req.name is not None:
            new_name = req.name.strip()
            if not new_name:
                raise HTTPException(status_code=400, detail="name cannot be empty")
            collision = (
                s.execute(
                    select(Person).where(
                        func.lower(Person.name) == new_name.lower(),
                        Person.id != p.id,
                    )
                )
                .scalars()
                .first()
            )
            if collision is not None:
                raise HTTPException(
                    status_code=409,
                    detail=f"A person named '{collision.name}' already exists.",
                )
            p.name = new_name
        if req.custom_threshold is not None:
            p.custom_threshold = float(req.custom_threshold)
        s.add(p)
        s.flush()
        s.refresh(p)
        return _to_out(s, p)


@router.delete("/{person_id}", tags=["persons"])
def delete_person(person_id: uuid.UUID, _: ApiKey = Depends(require_full_admin)) -> dict:
    with session_scope() as s:
        p = s.get(Person, person_id)
        if p is None:
            raise HTTPException(status_code=404, detail="person not found")
        crops = s.execute(select(FaceCrop).where(FaceCrop.person_id == person_id)).scalars().all()
        for c in crops:
            c.person_id = None
            c.status = FaceCropStatus.UNASSIGNED.value
        s.delete(p)
    try:
        for model_name in ("buffalo_s", "buffalo_l"):
            vector_repo.delete_for_person_model(person_id, model_name)
    except Exception:
        pass
    return {"ok": True}


def _crop_to_out(c: FaceCrop) -> FaceCropOut:
    try:
        bbox = json.loads(c.bounding_box) if c.bounding_box else []
    except Exception:
        bbox = []
    return FaceCropOut(
        id=c.id,
        person_id=c.person_id,
        image_url=f"/api/v1/crops/{c.id}.jpg",
        bounding_box=bbox,
        det_score=float(c.det_score or 0.0),
        status=c.status,
        created_at=c.created_at,
    )


@router.get("/{person_id}", response_model=PersonOut, tags=["persons"])
def get_person(person_id: uuid.UUID) -> PersonOut:
    with session_scope() as s:
        p = s.get(Person, person_id)
        if p is None:
            raise HTTPException(status_code=404, detail="person not found")
        return _to_out(s, p)


@router.get("/{person_id}/crops", response_model=list[FaceCropOut], tags=["persons"])
def list_person_crops(person_id: uuid.UUID) -> list[FaceCropOut]:
    with session_scope() as s:
        p = s.get(Person, person_id)
        if p is None:
            raise HTTPException(status_code=404, detail="person not found")
        rows = (
            s.execute(
                select(FaceCrop)
                .where(
                    FaceCrop.person_id == person_id,
                    FaceCrop.status == FaceCropStatus.ASSIGNED.value,
                )
                .order_by(FaceCrop.det_score.desc(), FaceCrop.created_at.desc())
            )
            .scalars()
            .all()
        )
        return [_crop_to_out(c) for c in rows]


@router.delete("/{person_id}/crops/{crop_id}", tags=["persons"])
def delete_person_crop(
    person_id: uuid.UUID,
    crop_id: uuid.UUID,
    _: ApiKey = Depends(require_full_admin),
) -> dict:
    with session_scope() as s:
        c = s.get(FaceCrop, crop_id)
        if c is None or c.person_id != person_id:
            raise HTTPException(status_code=404, detail="crop not found for this person")
        rel_path = c.file_path
        s.delete(c)
    try:
        if rel_path:
            delete_crop_files(rel_path)
    except Exception as e:
        log.warning("failed to delete crop files for %s: %s", crop_id, e)
    try:
        from app.api.faces import _rebuild_person_averaged
        from app.services.reindex import active_model

        _rebuild_person_averaged(person_id, active_model())
    except Exception as e:
        log.warning("rebuild averaged failed after crop delete: %s", e)
    return {"ok": True, "deleted": str(crop_id)}
