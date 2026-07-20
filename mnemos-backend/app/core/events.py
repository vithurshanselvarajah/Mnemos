from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.core.security import ensure_master_key
from app.db.session import init_db

log = logging.getLogger("mnemos.lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting mnemos-backend; db=%s crops=%s", settings.db_path, settings.crops_dir)
    os.makedirs(os.path.dirname(settings.db_path) or ".", exist_ok=True)
    os.makedirs(settings.crops_dir, exist_ok=True)
    init_db()
    ensure_master_key()
    try:
        from app.services import vector_repo

        vector_repo.ensure_schema()
    except Exception as e:
        log.error("could not ensure pgvector schema: %s", e)
    try:
        loop = asyncio.get_running_loop()
        from app.services import websocket_hub

        websocket_hub.bind_loop(loop)
    except RuntimeError as e:
        log.warning("could not bind websocket hub loop: %s", e)
    log.info("master key ready; active model=%s", settings.default_model)
    yield
    log.info("mnemos-backend shutting down")
