from __future__ import annotations

import hashlib
import logging
import os
import time
from typing import Callable

import requests

from app.core.config import settings
from app.services.model_manifest import ModelArtifact, ModelVariant
from app.services import websocket_hub

log = logging.getLogger("mnemos.model_downloader")


class DownloadError(RuntimeError):
    pass


ProgressCb = Callable[[int, int, str, str], None]


def _broadcast_download(done: int, total: int, model: str, *, kind: str = "reindex",
                        artifact: str | None = None) -> None:
    pct = int(100 * done / total) if total > 0 else 0
    payload: dict = {
        "type": f"{kind}.download",
        "model": model,
        "done": done,
        "total": total,
        "pct": pct,
    }
    if artifact is not None:
        payload["artifact"] = artifact
    websocket_hub.publish(payload)


def _hash_file(path: str, expected_sha256: str, *, chunk: int = 1024 * 1024) -> bool:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            buf = f.read(chunk)
            if not buf:
                break
            h.update(buf)
    return h.hexdigest().lower() == expected_sha256.lower()


def download_artifact(art: ModelArtifact, *, model_name: str, kind: str = "reindex",
                     on_progress: ProgressCb | None = None) -> None:
    os.makedirs(os.path.dirname(art.local_path), exist_ok=True)
    tmp_path = art.local_path + ".part"
    have = os.path.getsize(tmp_path) if os.path.isfile(tmp_path) else 0

    if os.path.isfile(art.local_path) and os.path.getsize(art.local_path) == art.size_bytes:
        if _hash_file(art.local_path, art.sha256):
            log.info("artifact already present and verified: %s", art.local_path)
            _broadcast_download(0, 0, model_name, kind=kind)
            if on_progress is not None:
                on_progress(0, 0, model_name)
            return
        log.warning("existing file failed sha256, re-downloading: %s", art.local_path)
        os.remove(art.local_path)

    headers: dict[str, str] = {"User-Agent": "mnemos/1.0"}
    mode = "wb"
    start_from = 0
    if have > 0 and have < art.size_bytes:
        headers["Range"] = f"bytes={have}-"
        mode = "ab"
        start_from = have

    log.info("downloading %s (have=%d, total=%d, resume=%s)", art.url, have, art.size_bytes, start_from > 0)
    try:
        with requests.get(art.url, headers=headers, stream=True, timeout=settings.download_timeout_s) as r:
            if r.status_code == 200 and start_from > 0:
                log.warning("server ignored Range; restarting %s from zero", art.filename)
                start_from = 0
                mode = "wb"
            elif r.status_code == 206:
                pass
            elif r.status_code == 200:
                pass
            else:
                r.raise_for_status()

            if r.status_code == 200 and "Content-Length" in r.headers:
                remote_total = int(r.headers["Content-Length"])
                if remote_total != art.size_bytes:
                    log.warning(
                        "manifest size %d != remote %d for %s; trusting manifest",
                        art.size_bytes,
                        remote_total,
                        art.filename,
                    )

            done = start_from
            last_pct = -1
            last_broadcast = 0.0
            chunk_size = 64 * 1024
            with open(tmp_path, mode) as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    pct = int(100 * done / art.size_bytes) if art.size_bytes > 0 else 0
                    now = time.time()
                    if pct != last_pct or (now - last_broadcast) > 0.25:
                        _broadcast_download(done, art.size_bytes, model_name, kind=kind, artifact=art.filename)
                        if on_progress is not None:
                            on_progress(done, art.size_bytes, model_name, art.filename)
                        last_pct = pct
                        last_broadcast = now

            if done < art.size_bytes:
                raise DownloadError(
                    f"download truncated for {art.filename}: got {done} of {art.size_bytes}"
                )

            if not _hash_file(tmp_path, art.sha256):
                raise DownloadError(f"sha256 mismatch for {art.filename}")

            os.replace(tmp_path, art.local_path)
            _broadcast_download(art.size_bytes, art.size_bytes, model_name, kind=kind, artifact=art.filename)
            if on_progress is not None:
                on_progress(art.size_bytes, art.size_bytes, model_name, art.filename)
            log.info("verified %s (%d bytes)", art.local_path, art.size_bytes)
    except Exception as e:
        log.exception("download failed for %s", art.filename)
        if os.path.isfile(tmp_path) and os.path.getsize(tmp_path) < 1024:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise DownloadError(f"{art.filename}: {e}") from e


def download_variant(variant: ModelVariant, *, kind: str = "reindex",
                     on_progress: ProgressCb | None = None) -> None:
    for art in variant.artifacts:
        download_artifact(art, model_name=variant.name, kind=kind, on_progress=on_progress)


def variant_files_present(variant: ModelVariant) -> bool:
    for art in variant.artifacts:
        if not (os.path.isfile(art.local_path) and os.path.getsize(art.local_path) == art.size_bytes):
            return False
        if not _hash_file(art.local_path, art.sha256):
            return False
    return True


def is_model_ready(name: str) -> bool:
    from app.services.model_manifest import variant_for

    return variant_files_present(variant_for(name))
