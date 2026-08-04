from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import select

from app.core.config import settings
from app.db.session import init_db, session_scope
from app.models.entities import BackupSettings
from app.services.backup_scheduler import _run_scheduler_loop, compute_next_run_at

log = logging.getLogger("mnemos.frontend.lifespan")

_stop_event: asyncio.Event | None = None
_scheduler_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("starting mnemos-frontend; db=%s", settings.db_path)
    parent = os.path.dirname(settings.db_path) or "."
    os.makedirs(parent, exist_ok=True)
    init_db()
    log.info("frontend SQLite schema ready")

    try:
        with session_scope() as s:
            row = s.execute(select(BackupSettings).order_by(BackupSettings.id)).scalars().first()
            if row is not None and row.enabled and row.next_run_at is None:
                from datetime import datetime
                row.next_run_at = compute_next_run_at(row, datetime.utcnow())
    except Exception as e:
        log.warning("could not prime backup schedule: %s", e)

    global _stop_event, _scheduler_task
    _stop_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_run_scheduler_loop(_stop_event), name="mnemos-backup-scheduler")
    log.info("backup scheduler started")

    try:
        yield
    finally:
        if _stop_event is not None:
            _stop_event.set()
        if _scheduler_task is not None:
            try:
                await asyncio.wait_for(_scheduler_task, timeout=5.0)
            except (TimeoutError, asyncio.CancelledError, Exception) as e:
                log.debug("scheduler shutdown: %s", e)
            _scheduler_task = None
        _stop_event = None
        log.info("mnemos-frontend shutting down")
