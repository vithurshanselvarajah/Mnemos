from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.services import websocket_hub

router = APIRouter()
log = logging.getLogger("mnemos.ws_endpoint")


@router.websocket("/ws/events")
async def events(ws: WebSocket):
    await websocket_hub.register(ws)
    try:
        while True:
            try:
                msg = await ws.receive_text()
                if msg.strip().lower() == "ping":
                    await ws.send_text("pong")
            except WebSocketDisconnect:
                break
    except Exception as e:
        log.debug("ws error: %s", e)
    finally:
        await websocket_hub.unregister(ws)
