from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select

from app.core.auth import hash_password
from app.core.templates import build_templates, render
from app.db.session import session_scope
from app.models.entities import BackendNode, User
from app.services.backend_client import (
    default_api_key,
    default_base_url,
    get_sync,
    post_sync,
)

router = APIRouter(prefix="/partials", tags=["partials"])
log = logging.getLogger("mnemos.frontend.partials")

templates = build_templates()


def _require_admin(request):
    user = getattr(request.state, "user", None)
    if user is None or user.role != "Admin":
        raise HTTPException(status_code=403, detail="Admin only")
    return user


@router.get("/inbox", response_class=HTMLResponse)
def partial_inbox(request: Request, page: int = 1, page_size: int = 24):
    r = get_sync(f"/api/v1/faces/unassigned?page={page}&page_size={page_size}")
    data = (
        r.json() if r.status_code == 200 else {"items": [], "total": 0, "page": page, "page_size": page_size}
    )
    for it in data.get("items", []):
        it["image_url"] = f"/backend/crops/{it['id']}.jpg"
    persons_r = get_sync("/api/v1/persons")
    persons = persons_r.json() if persons_r.status_code == 200 else []
    return render(
        templates,
        request,
        "partials/inbox_gallery.html",
        {"page": data, "persons": persons},
    )


@router.get("/inbox-count", response_class=HTMLResponse)
def partial_inbox_count(request: Request):
    r = get_sync("/api/v1/faces/unassigned?page=1&page_size=1")
    total = r.json().get("total", 0) if r.status_code == 200 else 0
    return render(templates, request, "partials/inbox_count.html", {"count": total})


@router.get("/reindex-status", response_class=HTMLResponse)
def partial_reindex_status(request: Request):
    r = get_sync("/api/v1/models")
    if r.status_code == 200:
        info = r.json()
    else:
        info = {
            "name": "unknown",
            "loaded": False,
            "reindex_in_progress": False,
            "reindex_done": 0,
            "reindex_total": 0,
            "embedding_dim": 0,
            "det_size": 0,
        }
    return render(templates, request, "partials/reindex_status.html", {"info": info})


@router.get("/backend-card", response_class=HTMLResponse)
def partial_backend_card(request: Request):
    backend_ok = True
    backend_payload: dict = {}
    try:
        r = get_sync("/healthz")
        backend_payload = r.json()
        backend_ok = r.status_code == 200
    except Exception as e:
        backend_ok = False
        backend_payload = {"error": str(e)}
    return render(
        templates,
        request,
        "partials/backend_card.html",
        {"backend_ok": backend_ok, "backend_payload": backend_payload},
    )


@router.get("/users", response_class=HTMLResponse)
def partial_users_list(request: Request):
    _require_admin(request)
    with session_scope() as s:
        users = s.execute(select(User).order_by(User.created_at.desc())).scalars().all()
    return render(templates, request, "partials/users_list.html", {"users": users})


@router.post("/users", response_class=HTMLResponse)
async def partial_users_create(request: Request):
    _require_admin(request)
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    role = form.get("role") or "Operator"
    if not username or len(password) < 8:
        return HTMLResponse(
            "<div class='error'>username required, password >= 8 chars</div>",
            status_code=400,
        )
    if role not in ("Admin", "Operator"):
        return HTMLResponse("<div class='error'>invalid role</div>", status_code=400)
    with session_scope() as s:
        existing = s.execute(select(User).where(User.username == username)).scalar_one_or_none()
        if existing:
            return HTMLResponse("<div class='error'>username already exists</div>", status_code=409)
        s.add(User(username=username, password_hash=hash_password(password), role=role))
        users = s.execute(select(User).order_by(User.created_at.desc())).scalars().all()
        return render(templates, request, "partials/users_list.html", {"users": users})


@router.delete("/users/{user_id}", response_class=HTMLResponse)
def partial_users_delete(user_id: str, request: Request):
    admin = _require_admin(request)
    from uuid import UUID

    try:
        uid = UUID(user_id)
    except ValueError:
        return HTMLResponse("<div class='error'>bad id</div>", status_code=400)
    if uid == admin.id:
        return HTMLResponse("<div class='error'>cannot delete yourself</div>", status_code=400)
    with session_scope() as s:
        u = s.get(User, uid)
        if u is not None:
            s.delete(u)
        users = s.execute(select(User).order_by(User.created_at.desc())).scalars().all()
        return render(templates, request, "partials/users_list.html", {"users": users})


@router.get("/keys", response_class=HTMLResponse)
def partial_keys_list(request: Request):
    _require_admin(request)
    r = get_sync("/api/v1/keys")
    keys = r.json() if r.status_code == 200 else []
    return render(
        templates,
        request,
        "partials/keys_list.html",
        {"keys": keys, "is_admin": True},
    )


@router.post("/keys", response_class=HTMLResponse)
async def partial_keys_create(request: Request):
    _require_admin(request)
    form = await request.form()
    payload = {
        "name": (form.get("name") or "").strip(),
        "permission_level": (form.get("permission_level") or "Identify-Only").strip(),
    }
    if not payload["name"]:
        return HTMLResponse("<div class='error'>name is required</div>", status_code=400)
    r = post_sync("/api/v1/keys", json=payload)
    if r.status_code >= 400:
        return HTMLResponse(f"<div class='error'>{r.text}</div>", status_code=r.status_code)
    return partial_keys_list(request)


@router.post("/keys/{key_id}/revoke", response_class=HTMLResponse)
def partial_keys_revoke(key_id: str, request: Request):
    _require_admin(request)
    from app.services.backend_client import request as _req

    r = _req("POST", f"/api/v1/keys/{key_id}/revoke")
    if r.status_code >= 400:
        return HTMLResponse(f"<div class='error'>{r.text}</div>", status_code=r.status_code)
    return partial_keys_list(request)


@router.delete("/keys/{key_id}", response_class=HTMLResponse)
def partial_keys_delete(key_id: str, request: Request):
    _require_admin(request)
    from app.services.backend_client import request as _req

    r = _req("DELETE", f"/api/v1/keys/{key_id}")
    if r.status_code >= 400:
        return HTMLResponse(f"<div class='error'>{r.text}</div>", status_code=r.status_code)
    return partial_keys_list(request)


@router.get("/persons", response_class=HTMLResponse)
def partial_persons_list(request: Request):
    r = get_sync("/api/v1/persons")
    persons = r.json() if r.status_code == 200 else []
    user = getattr(request.state, "user", None)
    is_admin = bool(user) and user.role == "Admin"
    return render(
        templates,
        request,
        "partials/persons_list.html",
        {"persons": persons, "is_admin": is_admin},
    )


@router.post("/persons", response_class=HTMLResponse)
async def partial_persons_create(request: Request):
    _require_admin(request)
    form = await request.form()
    name = (form.get("name") or "").strip()
    threshold = form.get("custom_threshold") or None
    payload: dict = {"name": name}
    if threshold:
        try:
            payload["custom_threshold"] = float(threshold)
        except ValueError:
            return HTMLResponse("<div class='error'>invalid threshold</div>", status_code=400)
    r = post_sync("/api/v1/persons", json=payload)
    if r.status_code >= 400:
        return HTMLResponse(f"<div class='error'>{r.text}</div>", status_code=r.status_code)
    return partial_persons_list(request)


@router.patch("/persons/{person_id}", response_class=HTMLResponse)
async def partial_persons_patch(person_id: str, request: Request):
    _require_admin(request)
    from app.services.backend_client import request as _req

    form = await request.form()
    name = (form.get("name") or "").strip()
    threshold = form.get("custom_threshold")
    payload: dict = {}
    if name:
        payload["name"] = name
    if threshold not in (None, ""):
        try:
            payload["custom_threshold"] = float(threshold)
        except ValueError:
            return HTMLResponse("<div class='error'>invalid threshold</div>", status_code=400)
    r = _req("PATCH", f"/api/v1/persons/{person_id}", json=payload)
    if r.status_code >= 400:
        return HTMLResponse(f"<div class='error'>{r.text}</div>", status_code=r.status_code)
    return partial_persons_list(request)


@router.delete("/persons/{person_id}", response_class=HTMLResponse)
def partial_persons_delete(person_id: str, request: Request):
    _require_admin(request)
    from app.services.backend_client import request as _req

    r = _req("DELETE", f"/api/v1/persons/{person_id}")
    if r.status_code >= 400:
        return HTMLResponse(f"<div class='error'>{r.text}</div>", status_code=r.status_code)
    return partial_persons_list(request)


@router.get("/settings/backend", response_class=HTMLResponse)
def partial_settings_backend(request: Request):
    _require_admin(request)
    with session_scope() as s:
        node = s.execute(select(BackendNode).order_by(BackendNode.created_at.asc())).scalars().first()
    return render(
        templates,
        request,
        "partials/settings_backend.html",
        {
            "node": node,
            "backend_url": default_base_url(),
            "has_key": default_api_key() is not None,
        },
    )
