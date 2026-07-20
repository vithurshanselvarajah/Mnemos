from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/partials", tags=["partials"])


@router.get("/ws-target", response_class=JSONResponse)
def ws_target(request: Request) -> JSONResponse:
    scheme = "wss" if request.url.scheme == "https" else "ws"
    host = request.headers.get("host") or request.url.netloc
    return {"ws_url": f"{scheme}://{host}/ws/events"}
