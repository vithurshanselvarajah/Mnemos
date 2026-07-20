from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.core.config import settings
from app.db.session import init_db

log = logging.getLogger("mnemos.frontend.lifespan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting mnemos-frontend; db=%s", settings.db_path)
    parent = os.path.dirname(settings.db_path) or "."
    os.makedirs(parent, exist_ok=True)
    init_db()
    log.info("frontend SQLite schema ready")
    yield
    log.info("mnemos-frontend shutting down")
