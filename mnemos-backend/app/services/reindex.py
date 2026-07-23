from __future__ import annotations

import logging
import os
import threading
import uuid
from collections import defaultdict
from uuid import UUID

import cv2
import numpy as np
from sqlmodel import select

from app.core.config import settings
from app.db.session import session_scope
from app.models.entities import FaceCrop, FaceCropStatus
from app.services import vector_repo, websocket_hub
from app.services.engine import InsightFaceEngine
from app.services.model_downloader import (
    DownloadError,
    download_variant,
    is_model_ready,
    variant_files_present,
)
from app.services.model_manifest import variant_for

log = logging.getLogger("mnemos.reindex")


class ReindexState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.running: bool = False
        self.model_name: str = ""
        self.total: int = 0
        self.done: int = 0
        self.last_error: str | None = None
        self.download_active: bool = False
        self.download_model: str = ""
        self.download_artifact: str | None = None
        self.download_done: int = 0
        self.download_total: int = 0

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "running": self.running,
                "model": self.model_name,
                "total": self.total,
                "done": self.done,
                "error": self.last_error,
                "download_active": self.download_active,
                "download_model": self.download_model,
                "download_artifact": self.download_artifact,
                "download_done": self.download_done,
                "download_total": self.download_total,
            }

    def start(self, model: str, total: int) -> None:
        with self._lock:
            self.running = True
            self.model_name = model
            self.total = total
            self.done = 0
            self.last_error = None

    def progress(self, done: int) -> None:
        with self._lock:
            self.done = done

    def finish(self, error: str | None = None) -> None:
        with self._lock:
            self.running = False
            if error:
                self.last_error = error

    def download_begin(self, model: str) -> None:
        with self._lock:
            self.download_active = True
            self.download_model = model
            self.download_artifact: str | None = None
            self.download_done = 0
            self.download_total = 0

    def download_update(self, done: int, total: int, artifact: str | None = None) -> None:
        with self._lock:
            self.download_done = done
            self.download_total = total
            if artifact is not None:
                self.download_artifact = artifact

    def download_end(self) -> None:
        with self._lock:
            self.download_active = False
            self.download_artifact = None
            self.download_done = 0
            self.download_total = 0


state = ReindexState()


def _list_crop_ids_with_paths() -> list[tuple[UUID, str]]:
    out: list[tuple[UUID, str]] = []
    with session_scope() as s:
        rows = (
            s.execute(
                select(FaceCrop).where(
                    FaceCrop.status.in_([FaceCropStatus.ASSIGNED.value, FaceCropStatus.UNASSIGNED.value])
                )
            )
            .scalars()
            .all()
        )
        for r in rows:
            out.append((r.id, r.file_path))
    return out


def _gather_by_person() -> dict[UUID, list[UUID]]:
    out: dict[UUID, list[UUID]] = defaultdict(list)
    with session_scope() as s:
        rows = (
            s.execute(select(FaceCrop).where(FaceCrop.status == FaceCropStatus.ASSIGNED.value))
            .scalars()
            .all()
        )
        for r in rows:
            if r.person_id is None:
                continue
            out[r.person_id].append(r.id)
    return out


def _broadcast_progress(done: int, total: int, model: str) -> None:
    websocket_hub.publish({"type": "reindex.progress", "done": done, "total": total, "model": model})


def _broadcast_done(model: str) -> None:
    websocket_hub.publish({"type": "reindex.done", "model": model})


def _broadcast_error(message: str) -> None:
    websocket_hub.publish({"type": "reindex.error", "message": message})


def _broadcast_download(done: int, total: int, model: str, *, kind: str = "reindex") -> None:
    pct = int(100 * done / total) if total > 0 else 0
    websocket_hub.publish(
        {
            "type": f"{kind}.download",
            "model": model,
            "done": done,
            "total": total,
            "pct": pct,
        }
    )
    state.download_update(done, total)


def _link_into_insightface_cache(variant) -> None:
    if settings.provider == "rockchip":
        return
    if variant.kind != "standard":
        return
    target = os.path.join(os.path.expanduser("~/.insightface/models"), variant.name)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.islink(target) or os.path.isdir(target):
        return
    standard_dir = os.path.dirname(variant.artifacts[0].local_path)
    try:
        os.symlink(standard_dir, target)
        log.info("linked %s -> %s", target, standard_dir)
    except OSError as e:
        log.warning("could not symlink %s into insightface cache: %s", target, e)


def ensure_model_ready(name: str, kind: str = "reindex") -> bool:
    try:
        variant = variant_for(name)
    except KeyError as e:
        state.last_error = str(e)
        return False
    if variant_files_present(variant):
        _link_into_insightface_cache(variant)
        _broadcast_download(0, 0, name, kind=kind)
        if kind == "warmup":
            state.download_end()
        return True
    if kind == "warmup":
        state.download_begin(name)

    def _on_progress(done: int, total: int, _model: str, artifact: str | None = None) -> None:
        state.download_update(done, total, artifact)

    try:
        download_variant(variant, kind=kind, on_progress=_on_progress)
    except DownloadError as e:
        log.warning("model %s download failed: %s", name, e)
        state.last_error = f"Model {name} download failed: {e}"
        if kind == "warmup":
            state.download_end()
        return False
    if not variant_files_present(variant):
        if kind == "warmup":
            state.download_end()
        return False
    _link_into_insightface_cache(variant)
    if kind == "warmup":
        state.download_end()
    return True


def run_reindex_sync(new_model: str) -> None:
    try:
        state.start(new_model, total=0)
        engine = InsightFaceEngine.current()

        websocket_hub.publish(
            {
                "type": "reindex.preparing",
                "model": new_model,
                "message": "Downloading model weights for " + new_model,
            }
        )
        state.download_begin(new_model)
        if not ensure_model_ready(new_model):
            state.download_end()
            raise RuntimeError(
                "Failed to download model weights and no cached copy is available. "
                "Check the container's network access to insightface.ai."
            )
        state.download_end()

        engine.switch_model(new_model)

        if not engine.warmup():
            last_err = getattr(engine, "last_error", None) or "unknown"
            raise RuntimeError(
                f"Failed to load model {new_model} into memory: {last_err}"
            )

        crops = _list_crop_ids_with_paths()
        state.total = len(crops)
        state.done = 0
        websocket_hub.publish(
            {
                "type": "reindex.start",
                "model": new_model,
                "total": len(crops),
                "phase": "reindexing",
            }
        )

        vector_repo.delete_all()

        by_person: dict[UUID, list[np.ndarray]] = defaultdict(list)
        for idx, (crop_id, rel_path) in enumerate(crops, start=1):
            abs_path = os.path.join(settings.crops_dir, rel_path)
            if not os.path.isfile(abs_path):
                log.warning("crop file missing: %s", abs_path)
                state.progress(idx)
                _broadcast_progress(idx, len(crops), new_model)
                continue
            img = cv2.imread(abs_path, cv2.IMREAD_COLOR)
            if img is None:
                log.warning("failed to read crop: %s", abs_path)
                state.progress(idx)
                _broadcast_progress(idx, len(crops), new_model)
                continue
            dets = engine.detect(img)
            if not dets:
                log.info("no face detected in %s", abs_path)
                state.progress(idx)
                _broadcast_progress(idx, len(crops), new_model)
                continue
            best = max(dets, key=lambda d: (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]))
            with session_scope() as s:
                row = s.get(FaceCrop, crop_id)
                pid = row.person_id if row else None
            if pid is not None:
                by_person[pid].append(best.embedding)
                try:
                    vector_repo.insert_embedding(
                        embed_id=uuid.uuid4(),
                        crop_id=crop_id,
                        person_id=pid,
                        embedding=best.embedding,
                        model_name=new_model,
                        is_averaged=False,
                    )
                except Exception as e:
                    log.warning("per-crop insert failed: %s", e)
            state.progress(idx)
            _broadcast_progress(idx, len(crops), new_model)

        for pid, embs in by_person.items():
            if not embs:
                continue
            avg = np.mean(np.stack(embs, axis=0), axis=0)
            n = float(np.linalg.norm(avg))
            if n > 0:
                avg = avg / n
            vector_repo.upsert_averaged(pid, avg, new_model)

        with session_scope() as s:
            from app.models.entities import SystemSetting

            row = s.get(SystemSetting, "active_model")
            if row is None:
                s.add(SystemSetting(key="active_model", value=new_model))
            else:
                row.value = new_model

        try:
            vector_repo.reindex_hnsw()
        except Exception as e:
            log.warning("HNSW REINDEX failed (index will rebuild lazily): %s", e)

        _broadcast_done(new_model)
        state.finish()
    except Exception as e:
        log.exception("reindex failed: %s", e)
        state.finish(error=str(e))
        _broadcast_error(str(e))
        raise


def start_reindex(new_model: str) -> bool:
    if state.running:
        return False
    t = threading.Thread(target=run_reindex_sync, args=(new_model,), name="mnemos-reindex", daemon=True)
    t.start()
    return True


def _run_warmup_sync(name: str) -> None:
    try:
        engine = InsightFaceEngine.current()
        if engine.model_name != name:
            engine.switch_model(name)
        if engine.is_loaded():
            websocket_hub.publish({"type": "warmup.done", "model": name, "already_loaded": True})
            return
        if not ensure_model_ready(name, kind="warmup"):
            state.last_error = state.last_error or f"Failed to prepare model {name} (download or extract)"
            websocket_hub.publish({"type": "warmup.error", "model": name, "message": state.last_error})
            return
        ok = engine.warmup()
        if not ok:
            last_err = getattr(engine, "last_error", None) or f"Failed to load model {name} into memory"
            state.last_error = last_err
            websocket_hub.publish({"type": "warmup.error", "model": name, "message": last_err})
            return
        websocket_hub.publish({"type": "warmup.done", "model": name, "already_loaded": False})
    except Exception as e:
        log.exception("warmup failed: %s", e)
        state.last_error = str(e)
        websocket_hub.publish({"type": "warmup.error", "model": name, "message": str(e)})


def start_warmup(name: str) -> bool:
    if state.download_active:
        return False
    if InsightFaceEngine.current().is_loaded() and InsightFaceEngine.current().model_name == name:
        return True
    t = threading.Thread(target=_run_warmup_sync, args=(name,), name="mnemos-warmup", daemon=True)
    t.start()
    return True


def active_model() -> str:
    with session_scope() as s:
        from app.models.entities import SystemSetting

        row = s.get(SystemSetting, "active_model")
        if row:
            return row.value
    return settings.default_model
