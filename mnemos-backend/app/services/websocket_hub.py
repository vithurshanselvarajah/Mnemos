from __future__ import annotations

import asyncio
import json
import logging
from collections import deque

from fastapi import WebSocket

log = logging.getLogger("mnemos.ws")

_RECENT: deque[dict] = deque(maxlen=64)
_clients: set[WebSocket] = set()
_loop: asyncio.AbstractEventLoop | None = None


def bind_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def publish(event: dict) -> None:
    _RECENT.append(event)
    payload = json.dumps(event, default=str)
    if _loop is None:
        log.warning("publish skipped: no loop bound")
        return
    if not _clients:
        return
    for ws in list(_clients):
        try:
            asyncio.run_coroutine_threadsafe(ws.send_text(payload), _loop)
        except Exception as e:
            log.warning("publish failed: %s", e)
            _clients.discard(ws)


def recent() -> list[dict]:
    return list(_RECENT)


async def register(ws: WebSocket) -> None:
    await ws.accept()
    _clients.add(ws)
    for ev in _RECENT:
        try:
            await ws.send_text(json.dumps(ev, default=str))
        except Exception:
            _clients.discard(ws)
            return


async def unregister(ws: WebSocket) -> None:
    _clients.discard(ws)
