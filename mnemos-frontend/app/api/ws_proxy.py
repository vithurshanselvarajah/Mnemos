from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime

import websockets
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select

from app.core.config import settings
from app.db.session import session_scope
from app.models.entities import Session, User
from app.services.backend_client import default_base_url

log = logging.getLogger("mnemos.frontend.ws_proxy")

router = APIRouter()


def _backend_ws_url() -> str:
    base = default_base_url()
    if base.startswith("https://"):
        ws = "wss://" + base[len("https://") :]
    elif base.startswith("http://"):
        ws = "ws://" + base[len("http://") :]
    else:
        ws = "ws://" + base
    return ws.rstrip("/") + "/ws/events"


def _user_from_cookie(ws: WebSocket) -> User | None:
    token = ws.cookies.get(settings.session_cookie_name) or ""
    if not token:
        return None
    with session_scope() as s:
        row = s.execute(select(Session).where(Session.session_token == token)).scalar_one_or_none()
        if row is None:
            return None
        now = datetime.utcnow()
        if row.expires_at and row.expires_at < now:
            return None
        return s.get(User, row.user_id)


async def _relay(ws_client: WebSocket, ws_backend) -> None:
    try:
        async for msg in ws_backend:
            if isinstance(msg, (bytes, bytearray)):
                await ws_client.send_bytes(bytes(msg))
            else:
                await ws_client.send_text(str(msg))
    except websockets.ConnectionClosed:
        pass
    except Exception as e:
        log.debug("ws backend -> client ended: %s", e)


@router.websocket("/ws/events")
async def ws_events(ws_client: WebSocket) -> None:
    user = _user_from_cookie(ws_client)
    if user is None:
        await ws_client.close(code=4401, reason="auth required")
        return

    await ws_client.accept()
    backend_url = _backend_ws_url()
    back = None
    try:
        back = await websockets.connect(
            backend_url,
            open_timeout=10,
            ping_interval=20,
            ping_timeout=20,
        )
    except Exception as e:
        log.warning("ws proxy: could not connect to backend %s: %s", backend_url, e)
        with suppress(Exception):
            await ws_client.send_text('{"type":"ws.error","message":"backend_unreachable"}')
        await ws_client.close()
        return

    async def client_to_backend() -> None:
        try:
            while True:
                msg = await ws_client.receive_text()
                if msg and msg.strip().lower() == "ping":
                    try:
                        await ws_client.send_text("pong")
                    except Exception:
                        return
        except WebSocketDisconnect:
            return
        except Exception as e:
            log.debug("ws client -> backend ended: %s", e)
            return

    forward_task = asyncio.create_task(_relay(ws_client, back))
    reverse_task = asyncio.create_task(client_to_backend())
    try:
        _, pending = await asyncio.wait(
            {forward_task, reverse_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for t in pending:
            t.cancel()
    finally:
        if back is not None:
            with suppress(Exception):
                await back.close()
        with suppress(Exception):
            await ws_client.close()
