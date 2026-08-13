from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from sqlalchemy import select

from app.core.middleware import require_admin
from app.core.templates import build_templates, render
from app.db.session import session_scope
from app.models.entities import BackupFile, BackupFileSource, BackupJob, BackupJobStatus, BackupSettings
from app.services import backup_local
from app.services.backend_client import (
    backup_create,
    backup_delete,
    backup_list,
    backup_restore,
    backup_restore_status,
    get_sync,
)

router = APIRouter(prefix="/partials/backup", tags=["backup"])
log = logging.getLogger("mnemos.frontend.partials.backup")

templates = build_templates()


def _refresh_known_files(backend_payload: dict | None) -> None:
    if not isinstance(backend_payload, dict):
        return
    items = backend_payload.get("backups") or []
    seen = set()
    with session_scope() as s:
        for item in items:
            name = item.get("filename")
            if not name:
                continue
            seen.add(name)
            row = s.get(BackupFile, name)
            if row is None:
                s.add(
                    BackupFile(
                        filename=name,
                        size_bytes=int(item.get("size_bytes") or 0),
                        sha256=item.get("sha256") or "",
                        source=BackupFileSource.LOCAL.value,
                    )
                )
            else:
                row.size_bytes = int(item.get("size_bytes") or row.size_bytes)
                row.sha256 = item.get("sha256") or row.sha256
        for row in s.execute(select(BackupFile)).scalars().all():
            if row.filename not in seen and row.source == BackupFileSource.LOCAL.value:
                s.delete(row)


def _local_uploaded_files() -> list[dict]:
    out = []
    for meta in backup_local.list_backups():
        out.append(meta.as_dict())
    return out


def _all_files() -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    backend_error: str | None = None
    try:
        r = backup_list()
        if r.status_code == 200:
            payload = r.json()
            _refresh_known_files(payload)
            for it in payload.get("backups") or []:
                items.append(it)
                seen.add(it["filename"])
        else:
            backend_error = f"backend returned {r.status_code}"
    except Exception:
        log.exception("backup list fetch failed")
        backend_error = "backend unreachable"
    for local in backup_local.list_backups():
        if local.filename in seen:
            continue
        d = local.as_dict()
        d["local_only"] = True
        items.append(d)
    items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return items, backend_error


@router.get("/list", response_class=HTMLResponse)
def partial_backup_list(request: Request):
    require_admin(request)
    items, backend_error = _all_files()
    return render(
        templates,
        request,
        "partials/backup_list.html",
        {
            "files": items,
            "backend_error": backend_error,
        },
    )


@router.post("/create", response_class=HTMLResponse)
async def partial_backup_create(request: Request):
    require_admin(request)
    try:
        r = backup_create()
    except Exception:
        log.exception("backup create failed")
        return HTMLResponse(
            "<div class='error'>Backup create failed. See server logs.</div>",
            status_code=502,
        )
    if r.status_code >= 400:
        return HTMLResponse(
            f"<div class='error'>Create failed ({r.status_code}): {r.text}</div>",
            status_code=r.status_code,
        )
    return partial_backup_list(request)


@router.delete("/{filename}", response_class=HTMLResponse)
def partial_backup_delete(filename: str, request: Request):
    require_admin(request)
    if not backup_local.is_valid_filename(filename):
        return HTMLResponse("<div class='error'>bad filename</div>", status_code=400)
    backend_error: str | None = None
    try:
        r = backup_delete(filename)
        if r.status_code == 404:
            pass
        elif r.status_code >= 400:
            backend_error = f"backend {r.status_code}: {r.text}"
    except Exception:
        log.exception("backup delete request to backend failed for %s", filename)
        backend_error = "backend error"
    local_deleted = False
    try:
        backup_local.delete_backup(filename)
        local_deleted = True
    except FileNotFoundError:
        pass
    except ValueError:
        pass
    items, _ = _all_files()
    return render(
        templates,
        request,
        "partials/backup_list.html",
        {"files": items, "backend_error": backend_error, "deleted": filename, "local_deleted": local_deleted},
    )


@router.post("/upload", response_class=HTMLResponse)
async def partial_backup_upload(request: Request):
    require_admin(request)
    form = await request.form()
    file = form.get("file")
    if file is None or not hasattr(file, "filename"):
        return HTMLResponse("<div class='error'>file is required</div>", status_code=400)
    filename = (file.filename or "").strip()
    try:
        dest = backup_local.reserve_upload_path(filename)
    except ValueError:
        return HTMLResponse(
            "<div class='error'>filename must match mnemos-backup-YYYYMMDD-HHMMSS.tar.gz</div>",
            status_code=400,
        )
    content = await file.read()
    if not content:
        return HTMLResponse("<div class='error'>empty file</div>", status_code=400)
    dest.write_bytes(content)
    with session_scope() as s:
        existing = s.get(BackupFile, filename)
        if existing is None:
            s.add(
                BackupFile(
                    filename=filename,
                    size_bytes=dest.stat().st_size,
                    sha256="",
                    source=BackupFileSource.UPLOADED.value,
                )
            )
    return partial_backup_list(request)


@router.post("/restore", response_class=HTMLResponse)
async def partial_backup_restore(request: Request):
    require_admin(request)
    form = await request.form()
    filename = (form.get("filename") or "").strip()
    confirm = form.get("confirm") in ("on", "true", "1", "yes")
    if not filename or not backup_local.is_valid_filename(filename):
        return HTMLResponse("<div class='error'>filename is required</div>", status_code=400)
    if not confirm:
        return HTMLResponse(
            "<div class='error'>You must confirm by ticking the checkbox.</div>", status_code=400
        )
    try:
        r = backup_restore(filename)
    except Exception:
        log.exception("backup restore request failed for %s", filename)
        return HTMLResponse(
            "<div class='error'>Backend unreachable. See server logs.</div>",
            status_code=502,
        )
    if r.status_code == 409:
        return HTMLResponse("<div class='error'>A restore is already in progress.</div>", status_code=409)
    if r.status_code >= 400:
        try:
            payload = r.json()
            msg = payload.get("detail") if isinstance(payload, dict) else r.text
        except Exception:
            msg = r.text
        return HTMLResponse(f"<div class='error'>{msg}</div>", status_code=r.status_code)
    job = r.json()
    with session_scope() as s:
        s.add(
            BackupJob(
                id=job["id"],
                kind="restore",
                filename=filename,
                status=job.get("status", BackupJobStatus.RUNNING.value),
            )
        )
    target_id = (form.get("target_id") or "restore-status").strip()
    return render(
        templates,
        request,
        "partials/backup_restore_status.html",
        {"job": job, "filename": filename, "target_id": target_id},
    )


@router.get("/restore-status/{job_id}", response_class=HTMLResponse)
def partial_backup_restore_status(job_id: str, request: Request):
    require_admin(request)
    try:
        r = backup_restore_status(job_id)
    except Exception:
        log.exception("backup restore-status fetch failed for %s", job_id)
        return HTMLResponse(
            "<div class='error'>Could not reach the backend. See server logs.</div>",
            status_code=502,
        )
    if r.status_code == 404:
        try:
            with session_scope() as s:
                row = s.get(BackupJob, job_id)
                if row is not None:
                    s.delete(row)
        except Exception:
            pass
        return HTMLResponse("<div class='status warn'>Restore job no longer available.</div>")
    if r.status_code >= 400:
        return HTMLResponse(f"<div class='error'>{r.text}</div>", status_code=r.status_code)
    job = r.json()
    filename = job.get("filename") or ""
    with session_scope() as s:
        row = s.get(BackupJob, job_id)
        if row is not None:
            row.status = job.get("status", row.status)
            finished = job.get("finished_at")
            if finished is not None and not isinstance(finished, datetime):
                try:
                    row.finished_at = datetime.fromtimestamp(float(finished))
                except (TypeError, ValueError):
                    row.finished_at = None
            else:
                row.finished_at = finished
            row.error = job.get("error")
    target_id = (request.query_params.get("target_id") or "restore-status").strip()
    return render(
        templates,
        request,
        "partials/backup_restore_status.html",
        {"job": job, "filename": filename, "target_id": target_id},
    )


@router.get("/restore-verify/{job_id}", response_class=HTMLResponse)
def partial_backup_restore_verify(job_id: str, request: Request):
    require_admin(request)
    target_id = (request.query_params.get("target_id") or "restore-status").strip()
    try:
        r = backup_list()
    except Exception:
        log.exception("backup restore-verify failed for %s", job_id)
        return _render_repair_required(target_id)
    if r.status_code == 200:
        return _render_restore_ok(target_id)
    if r.status_code in (401, 403):
        return _render_repair_required(target_id)
    log.warning("backup restore-verify unexpected status %s for %s", r.status_code, job_id)
    return _render_repair_required(target_id)


def _render_restore_ok(target_id: str) -> HTMLResponse:
    return HTMLResponse(
        f"<div id='{target_id}'><div class='alert ok'>"
        "<strong>Restore complete and pairing still valid.</strong> "
        "The model is reloading — give it a few seconds, then refresh the page."
        "<p style='margin-top:.5rem'>"
        "<a class='btn ghost sm' href='/dashboard'>Back to dashboard</a>"
        "</p></div></div>"
    )


def _render_repair_required(target_id: str) -> HTMLResponse:
    return HTMLResponse(
        f"<div id='{target_id}'><div class='alert warn'>"
        "<strong>Restore complete, but the stored API key no longer works.</strong> "
        "The backend's master key was replaced with a different one from the backup. "
        "You'll need to re-pair with the backend before you can do anything else."
        "<p style='margin-top:.5rem'>"
        "<a class='btn primary' href='/onboarding/repair'>Re-pair now</a>"
        "<a class='btn ghost sm' href='/dashboard' style='margin-left:.5rem'>Back to dashboard</a>"
        "</p></div></div>"
    )


@router.get("/download/{filename}")
def partial_backup_download(filename: str, request: Request):
    require_admin(request)
    if not backup_local.is_valid_filename(filename):
        raise HTTPException(status_code=400, detail="bad filename")
    local_path = backup_local.find_local_backup(filename)
    if local_path is not None:
        return FileResponse(
            path=str(local_path),
            media_type="application/gzip",
            filename=local_path.name,
        )
    try:
        r = get_sync(f"/api/v1/backup/{filename}/download", timeout=None)
    except Exception:
        log.exception("backup download proxy failed for %s", filename)
        raise HTTPException(status_code=502, detail="backend unreachable")
    if r.status_code == 404:
        raise HTTPException(status_code=404, detail="backup not found")
    if r.status_code >= 400:
        raise HTTPException(status_code=r.status_code, detail=r.text)
    headers = dict(r.headers)
    filename_header = headers.get("content-disposition", f'attachment; filename="{filename}"')
    return Response(
        content=r.content,
        media_type="application/gzip",
        headers={
            "Content-Disposition": filename_header,
            "X-Backup-SHA256": headers.get("x-backup-sha256", ""),
            "Content-Length": headers.get("content-length", str(len(r.content))),
        },
    )


@router.post("/schedule", response_class=HTMLResponse)
async def partial_backup_schedule(request: Request):
    require_admin(request)
    form = await request.form()
    enabled = form.get("enabled") in ("on", "true", "1", "yes")
    cadence = (form.get("cadence") or "daily").strip()
    hour_utc = int(form.get("hour_utc") or 3)
    weekday_utc = int(form.get("weekday_utc") or 0)
    retention_count = int(form.get("retention_count") or 7)
    if cadence not in ("daily", "weekly"):
        return HTMLResponse("<div class='error'>cadence must be daily or weekly</div>", status_code=400)
    if not 0 <= hour_utc <= 23 or not 0 <= weekday_utc <= 6 or not 1 <= retention_count <= 365:
        return HTMLResponse("<div class='error'>invalid schedule values</div>", status_code=400)
    with session_scope() as s:
        row = s.execute(select(BackupSettings).order_by(BackupSettings.id)).scalars().first()
        if row is None:
            s.add(
                BackupSettings(
                    enabled=enabled,
                    cadence=cadence,
                    hour_utc=hour_utc,
                    weekday_utc=weekday_utc,
                    retention_count=retention_count,
                )
            )
        else:
            row.enabled = enabled
            row.cadence = cadence
            row.hour_utc = hour_utc
            row.weekday_utc = weekday_utc
            row.retention_count = retention_count
    return partial_backup_settings(request)


@router.get("/settings", response_class=HTMLResponse)
def partial_backup_settings(request: Request):
    require_admin(request)
    with session_scope() as s:
        row = s.execute(select(BackupSettings).order_by(BackupSettings.id)).scalars().first()
    return render(
        templates,
        request,
        "partials/backup_settings.html",
        {"settings": row},
    )
