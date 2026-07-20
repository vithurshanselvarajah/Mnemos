from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.db.session import session_scope
from app.models.entities import Session, User

log = logging.getLogger("mnemos.frontend.auth")

EXEMPT_PATHS = (
    "/static/",
    "/healthz",
    "/login",
    "/logout",
    "/onboarding",
    "/partials/onboarding-warmup",
    "/backend/onboarding",
    "/backend/pair",
    "/partials/ws-target",
    "/ws/",
)


def _set_session_cookie(resp, token: str, max_age: int) -> None:
    resp.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=settings.session_cookie_secure,
        path="/",
    )


def _clear_session_cookie(resp) -> None:
    resp.delete_cookie(settings.session_cookie_name, path="/")


def _user_by_session(token: str) -> User | None:
    if not token:
        return None
    with session_scope() as s:
        row = s.execute(select(Session).where(Session.session_token == token)).scalar_one_or_none()
        if row is None:
            return None
        now = datetime.utcnow()
        if row.expires_at and row.expires_at < now:
            return None
        user = s.get(User, row.user_id)
        return user


def issue_session(user_id: uuid.UUID, *, remember: bool) -> tuple[str, int]:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    if remember:
        expires = datetime.utcnow() + timedelta(days=settings.remember_days)
        max_age = settings.remember_days * 24 * 3600
    else:
        expires = datetime.utcnow() + timedelta(hours=settings.session_hours)
        max_age = settings.session_hours * 3600
    with session_scope() as s:
        s.add(Session(user_id=user_id, session_token=token, expires_at=expires))
    return token, max_age


def revoke_session(token: str) -> None:
    if not token:
        return
    with session_scope() as s:
        row = s.execute(select(Session).where(Session.session_token == token)).scalar_one_or_none()
        if row is not None:
            s.delete(row)


def require_admin(request: Request) -> User:
    user = getattr(request.state, "user", None)
    if user is None or user.role != "Admin":
        from fastapi import HTTPException

        raise HTTPException(status_code=403, detail="Admin only")
    return user


class SessionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request.state.user = None
        request.state.session_token = None

        token = request.cookies.get(settings.session_cookie_name)
        if token:
            user = _user_by_session(token)
            if user is not None:
                request.state.user = user
                request.state.session_token = token

        path = request.url.path
        exempt = any(path.startswith(p) for p in EXEMPT_PATHS)
        if not exempt and request.state.user is None:
            accept = request.headers.get("accept", "")
            is_partial = path.startswith(("/partials/", "/_partials/"))
            is_backend_proxy = path.startswith(("/api/", "/backend/")) or is_partial
            wants_html = "text/html" in accept
            if is_backend_proxy:
                return JSONResponse({"detail": "Auth required"}, status_code=401)
            if request.method == "GET" and wants_html:
                return RedirectResponse(f"/login?next={path}", status_code=303)
            if wants_html:
                return RedirectResponse(f"/login?next={path}", status_code=303)
            return JSONResponse({"detail": "Auth required"}, status_code=401)
        return await call_next(request)
