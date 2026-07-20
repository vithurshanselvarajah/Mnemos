from __future__ import annotations

import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import find_api_key_by_raw

log = logging.getLogger("mnemos.auth")

EXCLUDED_PATHS = (
    "/healthz",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/ws/",
)


class _InMemoryRateLimiter:
    def __init__(self, max_per_min: int = 600) -> None:
        self.max_per_min = max_per_min
        self._buckets: dict[str, deque[float]] = defaultdict(deque)
        self._last_prune = time.time()

    def hit(self, key: str) -> bool:
        now = time.time()
        if now - self._last_prune > 60:
            self._last_prune = now
            cutoff = now - 60
            stale: list[str] = []
            for k, bucket in self._buckets.items():
                while bucket and bucket[0] < cutoff:
                    bucket.popleft()
                if not bucket:
                    stale.append(k)
            for k in stale:
                self._buckets.pop(k, None)
        bucket = self._buckets[key]
        cutoff = now - 60
        while bucket and bucket[0] < cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_per_min:
            return False
        bucket.append(now)
        return True


class APIKeyAuthMiddleware(BaseHTTPMiddleware):
    def __init__(self, app) -> None:
        super().__init__(app)
        self._limiter = _InMemoryRateLimiter()

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in EXCLUDED_PATHS):
            return await call_next(request)

        raw_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if raw_key:
            row = find_api_key_by_raw(raw_key)
            if not row or row.revoked_at is not None:
                return JSONResponse({"detail": "Invalid or revoked API key"}, status_code=401)
            request.state.api_key = row
        else:
            if path.startswith(("/api/v1/system/pair", "/api/v1/master")):
                request.state.api_key = None
            else:
                return JSONResponse({"detail": "Missing X-API-Key header"}, status_code=401)

        ident = request.state.api_key.id if getattr(request.state, "api_key", None) else raw_key or "anon"
        if not self._limiter.hit(ident):
            return JSONResponse({"detail": "Rate limit exceeded"}, status_code=429)

        return await call_next(request)
