from __future__ import annotations

import logging

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy import select

from app.core.auth import hash_password, verify_password
from app.core.config import settings
from app.core.middleware import (
    _clear_session_cookie,
    _set_session_cookie,
    issue_session,
    revoke_session,
)
from app.core.templates import build_templates, render
from app.core.version import get_version
from app.db.session import session_scope
from app.models.entities import BackendNode, User, UserRole
from app.services.backend_client import default_api_key, default_base_url, get_sync

router = APIRouter()
log = logging.getLogger("mnemos.frontend.pages")

templates = build_templates()


def _has_admin() -> bool:
    with session_scope() as s:
        row = s.execute(select(User).where(User.role == UserRole.ADMIN.value)).scalars().first()
        return row is not None


def _has_backend() -> bool:
    return default_api_key() is not None


def _check_backend() -> dict:
    import time

    now = time.time()
    cached = _check_backend.__dict__.get("_cache")
    if cached and now - cached["at"] < 5:
        return cached["value"]
    base = default_base_url()
    key = default_api_key()
    result: dict = {"reachable": False, "authenticated": False, "payload": {}}
    if not base or not key:
        _check_backend._cache = {"at": now, "value": result}
        return result
    try:
        r = get_sync("/api/v1/models", timeout=3.0)
        result["reachable"] = r.status_code in (200, 401, 403)
        result["authenticated"] = r.status_code == 200
        try:
            payload = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        except Exception:
            payload = {}
        # Normalize: /api/v1/models returns "loaded", /healthz returns
        # "model_loaded". Templates and tests use both keys; expose both.
        if "loaded" in payload and "model_loaded" not in payload:
            payload["model_loaded"] = payload["loaded"]
        if "name" in payload and "model" not in payload:
            payload["model"] = payload["name"]
        result["payload"] = payload
    except Exception as e:
        result["payload"] = {"error": str(e)}
    _check_backend._cache = {"at": now, "value": result}
    return result


def _admin_or_redirect(request: Request):
    user = getattr(request.state, "user", None)
    if user is not None and user.role == "Admin":
        return None
    return RedirectResponse("/dashboard", status_code=303)


def _ctx(request: Request, **extra) -> dict:
    user = getattr(request.state, "user", None)
    backend_state = (
        _check_backend() if _has_backend() else {"reachable": False, "authenticated": False, "payload": {}}
    )
    return {
        "request": request,
        "user": user,
        "is_admin": user is not None and user.role == "Admin",
        "backend_configured": _has_backend(),
        "backend_reachable": backend_state["reachable"],
        "backend_auth_ok": backend_state["authenticated"],
        "backend_auth_failed": _has_backend() and not backend_state["authenticated"],
        "has_admin": _has_admin(),
        "settings": settings,
        "app_version": get_version(),
        **extra,
    }


@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    if not _has_admin():
        return RedirectResponse("/onboarding", status_code=303)
    if request.state.user is None:
        return RedirectResponse("/login", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/onboarding", response_class=HTMLResponse)
def onboarding_get(request: Request):
    step = "admin" if not _has_admin() else ("backend" if not _has_backend() else "done")
    return render(
        templates,
        request,
        "onboarding.html",
        _ctx(request, step=step, warmup=dict(_warmup_state)),
    )


@router.get("/partials/onboarding-warmup")
def partial_onboarding_warmup():
    return JSONResponse(dict(_warmup_state))


@router.post("/onboarding/admin")
def onboarding_admin(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    if _has_admin():
        raise HTTPException(status_code=400, detail="Admin already exists")
    if password != password_confirm:
        return render(
            templates,
            request,
            "onboarding.html",
            _ctx(request, step="admin", error="Passwords do not match", warmup=dict(_warmup_state)),
            status_code=400,
        )
    if len(password) < 8:
        return render(
            templates,
            request,
            "onboarding.html",
            _ctx(
                request,
                step="admin",
                error="Password must be at least 8 characters",
                warmup=dict(_warmup_state),
            ),
            status_code=400,
        )
    with session_scope() as s:
        s.add(
            User(
                username=username.strip(),
                password_hash=hash_password(password),
                role=UserRole.ADMIN.value,
            )
        )
    return RedirectResponse("/onboarding", status_code=303)


@router.post("/onboarding/backend")
def onboarding_backend(
    request: Request,
    base_url: str = Form(...),
    master_key: str = Form(...),
    name: str = Form(default="Frontend"),
):
    _data, err = _perform_pair(base_url, master_key, name)
    if err is not None:
        return render(
            templates,
            request,
            "onboarding.html",
            _ctx(
                request,
                step="backend",
                error=err,
                form_values={"base_url": base_url, "master_key": master_key, "name": name},
                warmup=dict(_warmup_state),
            ),
            status_code=400,
        )
    return RedirectResponse("/onboarding", status_code=303)


def _perform_pair(base_url: str, master_key: str, name: str) -> tuple[dict | None, str | None]:
    import httpx2 as httpx

    base = base_url.strip().rstrip("/")
    try:
        with httpx.Client(timeout=10) as client:
            r = client.post(
                f"{base}/api/v1/system/pair",
                json={"master_key": master_key.strip(), "name": name},
            )
        if r.status_code != 200:
            try:
                payload = r.json()
                err = (
                    payload.get("detail")
                    if isinstance(payload, dict) and isinstance(payload.get("detail"), str)
                    else f"Pairing failed (HTTP {r.status_code})"
                )
            except Exception:
                err = f"Pairing failed (HTTP {r.status_code})"
            return None, err
        data = r.json()
    except Exception as e:
        return None, f"Pairing failed: {e}"

    with session_scope() as s:
        for old in s.execute(select(BackendNode)).scalars().all():
            s.delete(old)
        s.add(
            BackendNode(
                name=name,
                base_url=base,
                api_key=data["raw_key"],
            )
        )

    _check_backend.__dict__.pop("_cache", None)

    api_key = data["raw_key"]

    def _warmup() -> None:
        _warmup_state["running"] = True
        _warmup_state["done"] = False
        _warmup_state["error"] = None
        try:
            with httpx.Client(timeout=180) as client:
                wr = client.get(
                    f"{base}/api/v1/models/warmup",
                    headers={"X-API-Key": api_key},
                )
                if wr.status_code != 200:
                    _warmup_state["error"] = f"warmup {wr.status_code}: {wr.text}"
        except Exception as e:
            _warmup_state["error"] = str(e)
        finally:
            _warmup_state["running"] = False
            _warmup_state["done"] = True

    import threading

    t = threading.Thread(target=_warmup, name="mnemos-repair-warmup", daemon=True)
    t.start()
    return data, None


@router.get("/onboarding/repair", response_class=HTMLResponse)
def onboarding_repair_get(request: Request):
    user = getattr(request.state, "user", None)
    if user is None or user.role != UserRole.ADMIN.value:
        return RedirectResponse("/login?next=/onboarding/repair", status_code=303)
    with session_scope() as s:
        node = s.execute(select(BackendNode).order_by(BackendNode.created_at.asc())).scalars().first()
    return render(
        templates,
        request,
        "onboarding_repair.html",
        _ctx(request, current_node=node, warmup=dict(_warmup_state)),
    )


@router.post("/onboarding/repair")
def onboarding_repair_post(
    request: Request,
    base_url: str = Form(...),
    master_key: str = Form(...),
    name: str = Form(default="Frontend"),
):
    user = getattr(request.state, "user", None)
    if user is None or user.role != UserRole.ADMIN.value:
        raise HTTPException(status_code=403, detail="Admin only")
    _data, err = _perform_pair(base_url, master_key, name)
    if err is not None:
        return render(
            templates,
            request,
            "onboarding_repair.html",
            _ctx(
                request,
                error=err,
                form_values={"base_url": base_url, "master_key": master_key, "name": name},
                warmup=dict(_warmup_state),
            ),
            status_code=400,
        )
    return RedirectResponse("/onboarding/repair?ok=1", status_code=303)


_warmup_state: dict = {"running": False, "done": False, "error": None}


@router.get("/login", response_class=HTMLResponse)
def login_get(request: Request, next: str | None = None):
    if request.state.user is not None:
        return RedirectResponse(next or "/dashboard", status_code=303)
    return render(templates, request, "login.html", _ctx(request, next=next or "/dashboard"))


@router.post("/login")
def login_post(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    remember_me: str | None = Form(default=None),
    next: str = Form(default="/dashboard"),
):
    with session_scope() as s:
        row = s.execute(select(User).where(User.username == username.strip())).scalar_one_or_none()
        if row is None or not verify_password(row.password_hash, password):
            return render(
                templates,
                request,
                "login.html",
                _ctx(request, error="Invalid username or password", next=next),
                status_code=401,
            )
        token, max_age = issue_session(row.id, remember=bool(remember_me))
    target = next or "/dashboard"
    resp = RedirectResponse(target, status_code=303)
    _set_session_cookie(resp, token, max_age)
    return resp


@router.get("/logout")
def logout(request: Request):
    token = getattr(request.state, "session_token", None)
    if token:
        revoke_session(token)
    resp = RedirectResponse("/login", status_code=303)
    _clear_session_cookie(resp)
    return resp


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    if not _has_backend():
        return RedirectResponse("/onboarding", status_code=303)
    backend_state = _check_backend()
    backend_ok = backend_state["authenticated"]
    backend_payload = backend_state["payload"] or {}
    if not backend_state["reachable"]:
        backend_ok = False
        backend_payload = {"error": "Backend unreachable"}
    return render(
        templates,
        request,
        "dashboard.html",
        _ctx(request, backend_ok=backend_ok, backend_payload=backend_payload),
    )


@router.get("/inbox", response_class=HTMLResponse)
def inbox(request: Request):
    if not _has_backend():
        return RedirectResponse("/onboarding", status_code=303)
    r = get_sync("/api/v1/faces/unassigned?page=1&page_size=48")
    page = r.json() if r.status_code == 200 else {"items": [], "total": 0, "page": 1, "page_size": 48}
    r2 = get_sync("/api/v1/persons")
    persons = r2.json() if r2.status_code == 200 else []
    return render(templates, request, "inbox.html", _ctx(request, page=page, persons=persons))


@router.get("/persons", response_class=HTMLResponse)
def persons_page(request: Request):
    r = get_sync("/api/v1/persons")
    persons = r.json() if r.status_code == 200 else []
    return render(templates, request, "persons.html", _ctx(request, persons=persons))


@router.get("/persons/{person_id}", response_class=HTMLResponse)
def person_detail_page(person_id: str, request: Request):
    r = get_sync(f"/api/v1/persons/{person_id}")
    if r.status_code == 404:
        return Response("<h1>Person not found</h1>", status_code=404, media_type="text/html")
    person = r.json() if r.status_code == 200 else None
    rc = get_sync(f"/api/v1/persons/{person_id}/crops")
    crops = rc.json() if rc.status_code == 200 else []
    for c in crops:
        if c.get("image_url", "").startswith("/api/v1/crops/"):
            c["image_url"] = "/backend/crops/" + c["image_url"].rsplit("/", 1)[-1]
    return render(
        templates,
        request,
        "person_detail.html",
        _ctx(request, person=person, crops=crops),
    )


@router.get("/models", response_class=HTMLResponse)
def models_page(request: Request):
    r = get_sync("/api/v1/models")
    info = r.json() if r.status_code == 200 else {}
    return render(templates, request, "models.html", _ctx(request, info=info))


@router.get("/keys", response_class=HTMLResponse)
def keys_page(request: Request):
    if (resp := _admin_or_redirect(request)) is not None:
        return resp
    r = get_sync("/api/v1/keys")
    keys = r.json() if r.status_code == 200 else []
    return render(templates, request, "keys.html", _ctx(request, keys=keys))


@router.get("/users", response_class=HTMLResponse)
def users_page(request: Request):
    if (resp := _admin_or_redirect(request)) is not None:
        return resp
    with session_scope() as s:
        users = s.execute(select(User)).scalars().all()
    return render(templates, request, "users.html", _ctx(request, users=users))


@router.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    if (resp := _admin_or_redirect(request)) is not None:
        return resp
    return render(
        templates,
        request,
        "settings.html",
        _ctx(request, backend_url=default_base_url(), has_key=default_api_key() is not None),
    )


@router.get("/identify", response_class=HTMLResponse)
def identify_page(request: Request):
    return render(templates, request, "identify.html", _ctx(request))


@router.get("/swagger", response_class=HTMLResponse)
def swagger_page(request: Request):
    if (resp := _admin_or_redirect(request)) is not None:
        return resp
    return render(templates, request, "swagger.html", _ctx(request))


@router.get("/backup", response_class=HTMLResponse)
def backup_page(request: Request):
    if (resp := _admin_or_redirect(request)) is not None:
        return resp
    from sqlalchemy import select

    from app.models.entities import BackupSettings

    with session_scope() as s:
        sched = s.execute(select(BackupSettings).order_by(BackupSettings.id)).scalars().first()
    return render(templates, request, "backup.html", _ctx(request, sched=sched))


@router.get("/api", response_class=HTMLResponse)
def api_alias(request: Request):
    return swagger_page(request)
