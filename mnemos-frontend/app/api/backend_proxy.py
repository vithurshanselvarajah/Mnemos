from __future__ import annotations

import json
import logging
from uuid import UUID

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.core.config import settings
from app.core.middleware import require_admin
from app.core.templates import build_templates, render
from app.services.backend_client import default_api_key, default_base_url, get_sync, post_sync

router = APIRouter()
log = logging.getLogger("mnemos.frontend.proxy")

templates = build_templates()


def _is_admin(request: Request) -> bool:
    user = getattr(request.state, "user", None)
    return user is not None and getattr(user, "role", None) == "Admin"


@router.post("/identify")
async def proxy_identify(request: Request, file: UploadFile = File(...)):
    body = await file.read()
    files = {"file": (file.filename or "snapshot.jpg", body, file.content_type or "image/jpeg")}
    try:
        r = post_sync("/api/v1/identify", files=files)
        if r.status_code >= 400:
            return render(
                templates,
                request,
                "partials/identify_result.html",
                {"error": f"{r.status_code}: {r.text}"},
                status_code=r.status_code,
            )
        data = r.json()
        for u in data.get("unknown_faces") or []:
            u["image_url"] = f"/backend/crops/{u['crop_id']}.jpg"
        for m in data.get("recognized") or []:
            if m.get("image_url") and m["image_url"].startswith("/api/v1/crops/"):
                m["image_url"] = "/backend/crops/" + m["image_url"].rsplit("/", 1)[-1]
        persons = []
        try:
            pr = get_sync("/api/v1/persons")
            if pr.status_code == 200:
                persons = pr.json() or []
        except Exception:
            persons = []
        return render(
            templates,
            request,
            "partials/identify_result.html",
            {"result": data, "persons": persons, "is_admin": _is_admin(request)},
        )
    except Exception as e:
        return render(
            templates,
            request,
            "partials/identify_result.html",
            {"error": f"backend error: {e}"},
            status_code=502,
        )


@router.post("/faces/assign")
async def proxy_assign(request: Request):
    require_admin(request)
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        try:
            crop_ids = json.loads(form.get("crop_ids_json") or "[]")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="crop_ids_json is not valid JSON")
        payload = {"crop_ids": crop_ids}
        name_input = (form.get("name_input") or "").strip()
        if name_input:
            _resolve_name_input(payload, name_input)
        else:
            target = (form.get("target") or "new").strip()
            if target == "new":
                name = (form.get("new_person_name") or "").strip()
                if not name:
                    raise HTTPException(
                        status_code=400,
                        detail="new_person_name is required when target='new'",
                    )
                payload["new_person_name"] = name
            else:
                try:
                    payload["person_id"] = str(UUID(target))
                except ValueError:
                    raise HTTPException(status_code=400, detail="target is not a valid UUID")
    r = post_sync("/api/v1/faces/assign", json=payload)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


def _resolve_name_input(payload: dict, name_input: str) -> None:
    if not name_input:
        raise HTTPException(status_code=400, detail="name_input is required")
    try:
        pr = get_sync("/api/v1/persons")
    except Exception:
        pr = None
    if pr is not None and pr.status_code == 200:
        try:
            persons = pr.json() or []
        except Exception:
            persons = []
        for p in persons:
            if isinstance(p, dict) and (p.get("name") or "").strip().lower() == name_input.lower():
                payload["person_id"] = str(p.get("id"))
                return
    payload["new_person_name"] = name_input


@router.post("/faces/mark-non-face")
async def proxy_mark_non_face(request: Request):
    require_admin(request)
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        try:
            crop_ids = json.loads(form.get("crop_ids_json") or "[]")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="crop_ids_json is not valid JSON")
        payload = {"crop_ids": crop_ids}
    r = post_sync("/api/v1/faces/mark-non-face", json=payload)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.post("/faces/ignore")
async def proxy_ignore(request: Request):
    require_admin(request)
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/json" in content_type:
        payload = await request.json()
    else:
        form = await request.form()
        try:
            crop_ids = json.loads(form.get("crop_ids_json") or "[]")
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="crop_ids_json is not valid JSON")
        payload = {"crop_ids": crop_ids}
    r = post_sync("/api/v1/faces/ignore", json=payload)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.post("/models/switch")
async def proxy_model_switch(request: Request):
    require_admin(request)
    payload = await request.json()
    r = post_sync("/api/v1/models/switch", json=payload)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.get("/models/warmup")
def proxy_model_warmup():
    r = get_sync("/api/v1/models/warmup")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.get("/inbox")
def proxy_inbox(page: int = 1, page_size: int = 24):
    r = get_sync(f"/api/v1/faces/unassigned?page={page}&page_size={page_size}")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.get("/persons")
def proxy_persons():
    r = get_sync("/api/v1/persons")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.post("/persons")
async def proxy_persons_post(request: Request):
    require_admin(request)
    payload = await request.json()
    payload = {k: v for k, v in payload.items() if v not in ("", None)}
    r = post_sync("/api/v1/persons", json=payload)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.patch("/persons/{person_id}")
async def proxy_persons_patch(person_id: UUID, request: Request):
    require_admin(request)
    payload = await request.json()
    from app.services.backend_client import request

    r = request("PATCH", f"/api/v1/persons/{person_id}", json=payload)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.delete("/persons/{person_id}")
def proxy_persons_delete(person_id: UUID, request: Request):
    require_admin(request)
    from app.services.backend_client import request

    r = request("DELETE", f"/api/v1/persons/{person_id}")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.delete("/persons/{person_id}/crops/{crop_id}")
def proxy_person_crop_delete(person_id: UUID, crop_id: UUID, request: Request):
    require_admin(request)
    from app.services.backend_client import request

    r = request("DELETE", f"/api/v1/persons/{person_id}/crops/{crop_id}")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.get("/keys")
def proxy_keys_get():
    r = get_sync("/api/v1/keys")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.get("/partials/keys", response_class=HTMLResponse)
def proxy_keys_partial(request: Request):
    r = get_sync("/api/v1/keys")
    if r.status_code != 200:
        return Response(
            content=f"<p class='error'>Failed to load keys: {r.status_code}</p>",
            status_code=r.status_code,
            media_type="text/html",
        )
    keys = r.json()
    return render(
        templates,
        request,
        "partials/keys_list.html",
        {"keys": keys, "is_admin": _is_admin(request)},
    )


@router.get("/partials/persons", response_class=HTMLResponse)
def proxy_persons_partial(request: Request):
    r = get_sync("/api/v1/persons")
    if r.status_code != 200:
        return Response(
            content=f"<p class='error'>Failed to load persons: {r.status_code}</p>",
            status_code=r.status_code,
            media_type="text/html",
        )
    persons = r.json()
    return render(
        templates,
        request,
        "partials/persons_list.html",
        {"persons": persons, "is_admin": _is_admin(request)},
    )


@router.post("/keys")
async def proxy_keys_post(request: Request):
    payload = await request.json()
    r = post_sync("/api/v1/keys", json=payload)
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.post("/keys/{key_id}/revoke")
def proxy_keys_revoke(key_id: UUID):
    from app.services.backend_client import request

    r = request("POST", f"/api/v1/keys/{key_id}/revoke")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.delete("/keys/{key_id}")
def proxy_keys_delete(key_id: UUID):
    from app.services.backend_client import request

    r = request("DELETE", f"/api/v1/keys/{key_id}")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.get("/models")
def proxy_models_get():
    r = get_sync("/api/v1/models")
    return Response(content=r.content, status_code=r.status_code, media_type="application/json")


@router.get("/openapi.json")
def proxy_openapi(request: Request):
    require_admin(request)
    r = get_sync("/openapi.json")
    if r.status_code != 200:
        return Response(
            content=r.content,
            status_code=r.status_code,
            media_type="application/json",
        )
    try:
        schema = r.json()
    except Exception:
        return Response(
            content=r.content,
            status_code=200,
            media_type="application/json",
            headers={"Cache-Control": "no-store"},
        )
    public_base = f"{request.url.scheme}://{request.url.netloc}/backend"
    schema["servers"] = [{"url": public_base, "description": "Mnemos backend (via frontend proxy)"}]
    return Response(
        content=json.dumps(schema),
        status_code=200,
        media_type="application/json",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/crops/{filename}")
def proxy_crop(filename: str):
    import httpx

    from app.services.backend_client import default_api_key, default_base_url

    headers = {}
    key = default_api_key()
    if key:
        headers["X-API-Key"] = key
    base = default_base_url()
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.get(f"{base}/api/v1/crops/{filename}", headers=headers)
        return Response(content=r.content, status_code=r.status_code, media_type="image/jpeg")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"backend error: {e}")


@router.api_route("/api/v1/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_catch_all(full_path: str, request: Request):
    require_admin(request)
    return await _proxy_passthrough(f"/api/v1/{full_path}", request)


@router.api_route("/{full_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy_root_paths(full_path: str, request: Request):
    """Catch-all for backend paths that don't live under /api/v1
    (e.g. /healthz, /readyz). Falls through to backend's same path.
    """
    require_admin(request)
    return await _proxy_passthrough("/" + full_path, request)


async def _proxy_passthrough(backend_path: str, request: Request) -> Response:
    skip = {"host", "content-length", "connection", "accept-encoding"}
    headers = {k: v for k, v in request.headers.items() if k.lower() not in skip}
    body = await request.body()
    backend_url = f"{default_base_url()}{backend_path}"
    key = default_api_key()
    if key:
        headers["X-API-Key"] = key
    async with httpx.AsyncClient(timeout=settings.backend_request_timeout) as client:
        r = await client.request(
            method=request.method,
            url=backend_url,
            headers=headers,
            content=body,
        )
    passthrough = {"content-type", "cache-control", "x-request-id"}
    out_headers = {k: v for k, v in r.headers.items() if k.lower() in passthrough}
    return Response(
        content=r.content,
        status_code=r.status_code,
        headers=out_headers,
        media_type=r.headers.get("content-type"),
    )
