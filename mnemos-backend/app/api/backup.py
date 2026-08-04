from __future__ import annotations

import logging
import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from app import backup as backup_mod
from app.api.deps import require_full_admin
from app.core.config import settings

log = logging.getLogger("mnemos.backend.api.backup")

router = APIRouter(prefix="/backup", tags=["backup"])


@router.get("", dependencies=[Depends(require_full_admin)])
def list_backups():
    try:
        items = [b.as_dict() for b in backup_mod.list_backups()]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"list failed: {e}")
    return {
        "backups": items,
        "free_bytes": backup_mod.disk_free_bytes(),
        "total_bytes": backup_mod.disk_total_bytes(),
    }


@router.post("", dependencies=[Depends(require_full_admin)], status_code=201)
def create_backup():
    from app.core.version import get_version

    try:
        out = backup_mod.create_backup_tarball(
            backend_db=Path(settings.db_path),
            crops_dir=Path(settings.crops_dir),
            frontend_db=None,
            app_version=get_version(),
        )
    except Exception as e:
        log.exception("backup create failed")
        raise HTTPException(status_code=500, detail=f"create failed: {type(e).__name__}: {e}")
    stat = out.stat()
    return {
        "filename": out.name,
        "size_bytes": stat.st_size,
        "created_at": out.stat().st_mtime,
    }


@router.get("/{filename}/inspect", dependencies=[Depends(require_full_admin)])
def inspect_backup(filename: str):
    try:
        return backup_mod.inspect_backup(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="backup not found")


@router.delete("/{filename}", dependencies=[Depends(require_full_admin)])
def delete_backup(filename: str):
    try:
        backup_mod.delete_backup(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="backup not found")
    return {"deleted": filename}


@router.get("/{filename}/download", dependencies=[Depends(require_full_admin)])
def download_backup(filename: str, request: Request):
    try:
        backup_mod._safe_filename(filename)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    path = backup_mod.backup_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="backup not found")
    size = path.stat().st_size

    def iter_chunks(chunk_size: int = 1024 * 256):
        with path.open("rb") as fh:
            while True:
                chunk = fh.read(chunk_size)
                if not chunk:
                    break
                yield chunk

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "Content-Length": str(size),
        "X-Backup-SHA256": backup_mod._sha256_file(path),
    }
    return StreamingResponse(iter_chunks(), media_type="application/gzip", headers=headers)


@router.post("/restore", dependencies=[Depends(require_full_admin)], status_code=202)
def start_restore(payload: dict):
    filename = payload.get("filename")
    confirm = bool(payload.get("confirm"))
    if not filename or not re.match(r"^[\w.\-]+$", filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    if not confirm:
        raise HTTPException(status_code=400, detail="confirm must be true to restore")
    try:
        job = backup_mod.start_restore_job(
            filename,
            backend_db_dest=Path(settings.db_path),
            crops_dir_dest=Path(settings.crops_dir),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="backup not found")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return job.as_dict()


@router.get("/restore/{job_id}", dependencies=[Depends(require_full_admin)])
def get_restore_status(job_id: str):
    job = backup_mod.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.as_dict()
