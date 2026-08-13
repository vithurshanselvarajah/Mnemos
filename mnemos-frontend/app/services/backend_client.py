from __future__ import annotations

import logging

import httpx2 as httpx
from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models.entities import BackendNode

log = logging.getLogger("mnemos.frontend.client")


def _default_node() -> BackendNode | None:
    with session_scope() as s:
        row = s.execute(select(BackendNode).order_by(BackendNode.created_at.asc())).scalars().first()
        return row


def default_base_url() -> str:
    row = _default_node()
    if row is None:
        return settings.default_backend_url
    return row.base_url.rstrip("/")


def default_api_key() -> str | None:
    row = _default_node()
    return row.api_key if row else None


async def _request(method: str, path: str, **kwargs) -> httpx.Response:
    base = default_base_url()
    key = default_api_key()
    headers = kwargs.pop("headers", {}) or {}
    if key:
        headers["X-API-Key"] = key
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    timeout = kwargs.pop("timeout", settings.backend_request_timeout)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, url, headers=headers, **kwargs)


def request(method: str, path: str, **kwargs) -> httpx.Response:
    base = default_base_url()
    key = default_api_key()
    headers = kwargs.pop("headers", {}) or {}
    if key:
        headers["X-API-Key"] = key
    url = f"{base}{path if path.startswith('/') else '/' + path}"
    timeout = kwargs.pop("timeout", settings.backend_request_timeout)
    with httpx.Client(timeout=timeout) as client:
        return client.request(method, url, headers=headers, **kwargs)


async def get(path: str, **kwargs) -> httpx.Response:
    return await _request("GET", path, **kwargs)


async def post(path: str, **kwargs) -> httpx.Response:
    return await _request("POST", path, **kwargs)


def get_sync(path: str, **kwargs) -> httpx.Response:
    return request("GET", path, **kwargs)


def post_sync(path: str, **kwargs) -> httpx.Response:
    return request("POST", path, **kwargs)


async def ping() -> tuple[bool, dict]:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{default_base_url()}/healthz")
            r.raise_for_status()
            return True, r.json()
    except Exception as e:
        return False, {"error": str(e)}


def backup_list() -> httpx.Response:
    return get_sync("/api/v1/backup")


def backup_create() -> httpx.Response:
    return post_sync("/api/v1/backup")


def backup_inspect(filename: str) -> httpx.Response:
    return get_sync(f"/api/v1/backup/{filename}/inspect")


def backup_delete(filename: str) -> httpx.Response:
    return request("DELETE", f"/api/v1/backup/{filename}")


def backup_restore(filename: str) -> httpx.Response:
    return post_sync("/api/v1/backup/restore", json={"filename": filename, "confirm": True})


def backup_restore_status(job_id: str) -> httpx.Response:
    return get_sync(f"/api/v1/backup/restore/{job_id}")
