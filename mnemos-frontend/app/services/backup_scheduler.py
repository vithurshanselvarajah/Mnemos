from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta

from sqlalchemy import select

from app.db.session import session_scope
from app.models.entities import BackupSettings
from app.services import backup_local
from app.services.backend_client import backup_create, backup_list

log = logging.getLogger("mnemos.frontend.backup.scheduler")


def _next_run(now: datetime, *, cadence: str, hour_utc: int, weekday_utc: int) -> datetime:
    base = now.replace(hour=hour_utc, minute=0, second=0, microsecond=0)
    if cadence == "daily":
        if base <= now:
            base += timedelta(days=1)
        return base
    days_ahead = (weekday_utc - base.weekday()) % 7
    base = base + timedelta(days=days_ahead)
    if base <= now:
        base += timedelta(days=7)
    return base


def compute_next_run_at(settings: BackupSettings, now: datetime | None = None) -> datetime:
    return _next_run(
        now or datetime.utcnow(),
        cadence=settings.cadence,
        hour_utc=settings.hour_utc,
        weekday_utc=settings.weekday_utc,
    )


async def _run_scheduler_loop(stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        try:
            with session_scope() as s:
                row = s.execute(select(BackupSettings).order_by(BackupSettings.id)).scalars().first()
            if row is None or not row.enabled:
                await asyncio.wait_for(stop_event.wait(), timeout=60.0)
                continue
            now = datetime.utcnow()
            if row.next_run_at is None or row.next_run_at <= now:
                try:
                    r = backup_create()
                    if r.status_code >= 400:
                        log.warning("scheduled backup failed: %s %s", r.status_code, r.text)
                    else:
                        try:
                            rj = backup_list()
                            if rj.status_code == 200:
                                items = (rj.json() or {}).get("backups") or []
                                items.sort(key=lambda x: x.get("created_at") or "", reverse=True)
                                for old in items[row.retention_count :]:
                                    name = old.get("filename")
                                    if not name:
                                        continue
                                    try:
                                        from app.services.backend_client import backup_delete

                                        backup_delete(name)
                                    except Exception as e:
                                        log.warning("scheduled delete of %s failed: %s", name, e)
                        except Exception as e:
                            log.warning("retention prune failed: %s", e)
                        try:
                            for meta in backup_local.list_backups()[row.retention_count :]:
                                try:
                                    backup_local.delete_backup(meta.filename)
                                except Exception as e:
                                    log.warning("local retention delete of %s failed: %s", meta.filename, e)
                        except Exception as e:
                            log.warning("local retention listing failed: %s", e)
                except Exception as e:
                    log.warning("scheduled backup request failed: %s", e)
                next_dt = _next_run(
                    datetime.utcnow(), cadence=row.cadence, hour_utc=row.hour_utc, weekday_utc=row.weekday_utc
                )
                with session_scope() as s:
                    cur = s.get(BackupSettings, row.id)
                    if cur is not None:
                        cur.next_run_at = next_dt
                sleep_s = max(0.0, (next_dt - datetime.utcnow()).total_seconds())
            else:
                sleep_s = max(0.0, (row.next_run_at - datetime.utcnow()).total_seconds())
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=min(sleep_s, 300.0))
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.exception("scheduler loop error: %s", e)
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop_event.wait(), timeout=30.0)
