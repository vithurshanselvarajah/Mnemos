from __future__ import annotations

from datetime import datetime, timedelta

import pytest


@pytest.fixture
def fe_settings(frontend_imports, tmp_path, monkeypatch):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.models import entities  # noqa: F401

    db_path = tmp_path / "fe.db"
    monkeypatch.setenv("MNEMOS_FE_DB_PATH", str(db_path))
    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    return tmp_path


def _make_settings(**overrides):
    from app.models.entities import BackupCadence, BackupSettings

    base = {
        "enabled": True,
        "cadence": BackupCadence.DAILY.value,
        "hour_utc": 3,
        "weekday_utc": 0,
        "retention_count": 7,
    }
    base.update(overrides)
    return BackupSettings(**base)


def test_next_run_daily_future(fe_settings):
    from app.services.backup_scheduler import compute_next_run_at

    s = _make_settings(hour_utc=3)
    now = datetime(2026, 8, 4, 1, 0, 0)
    nxt = compute_next_run_at(s, now)
    assert nxt == datetime(2026, 8, 4, 3, 0, 0)


def test_next_run_daily_rolls_over(fe_settings):
    from app.services.backup_scheduler import compute_next_run_at

    s = _make_settings(hour_utc=3)
    now = datetime(2026, 8, 4, 5, 0, 0)
    nxt = compute_next_run_at(s, now)
    assert nxt == datetime(2026, 8, 5, 3, 0, 0)


def test_next_run_weekly_same_day_future(fe_settings):
    from app.services.backup_scheduler import compute_next_run_at

    s = _make_settings(cadence="weekly", hour_utc=3, weekday_utc=0)
    now = datetime(2026, 8, 3, 1, 0, 0)
    nxt = compute_next_run_at(s, now)
    assert nxt == datetime(2026, 8, 3, 3, 0, 0)


def test_next_run_weekly_rolls_over_a_week(fe_settings):
    from app.services.backup_scheduler import compute_next_run_at

    s = _make_settings(cadence="weekly", hour_utc=3, weekday_utc=0)
    now = datetime(2026, 8, 3, 5, 0, 0)
    nxt = compute_next_run_at(s, now)
    assert nxt == datetime(2026, 8, 10, 3, 0, 0)


def test_next_run_weekly_jumps_to_target_weekday(fe_settings):
    from app.services.backup_scheduler import compute_next_run_at

    s = _make_settings(cadence="weekly", hour_utc=3, weekday_utc=2)
    now = datetime(2026, 8, 3, 0, 0, 0)
    nxt = compute_next_run_at(s, now)
    assert nxt == datetime(2026, 8, 5, 3, 0, 0)


@pytest.mark.asyncio
async def test_scheduler_loop_creates_when_due_and_prunes(fe_settings, monkeypatch, tmp_path):

    from app.db.session import session_scope
    from app.models.entities import BackupSettings
    from app.services import backup_scheduler

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MNEMOS_FE_BACKUP_DIR", str(backup_dir))

    for i in range(10):
        name = f"mnemos-backup-2026010{i}-000000.tar.gz"
        (backup_dir / name).write_bytes(b"x")

    with session_scope() as s:
        s.add(
            BackupSettings(
                enabled=True,
                cadence="daily",
                hour_utc=3,
                weekday_utc=0,
                retention_count=3,
                next_run_at=datetime.utcnow() - timedelta(minutes=1),
            )
        )

    create_calls = {"n": 0}
    list_calls = {"n": 0}
    delete_calls = []

    def fake_create():
        create_calls["n"] += 1
        new_name = f"mnemos-backup-20260804-12000{create_calls['n']}.tar.gz"
        (backup_dir / new_name).write_bytes(b"new")
        return _FakeResponse(201, {"filename": new_name, "size_bytes": 3})

    def fake_list():
        list_calls["n"] += 1
        items = []
        for p in sorted(backup_dir.iterdir(), reverse=True):
            items.append(
                {"filename": p.name, "size_bytes": p.stat().st_size, "created_at": "now", "sha256": ""}
            )
        return _FakeResponse(200, {"backups": items})

    def fake_delete(name):
        delete_calls.append(name)
        target = backup_dir / name
        if target.exists():
            target.unlink()
        return _FakeResponse(204, "")

    monkeypatch.setattr(backup_scheduler, "backup_create", fake_create)
    monkeypatch.setattr(backup_scheduler, "backup_list", fake_list)
    from app.services import backend_client

    monkeypatch.setattr(backend_client, "backup_delete", fake_delete)

    import asyncio

    stop = asyncio.Event()
    task = asyncio.create_task(backup_scheduler._run_scheduler_loop(stop))
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            if create_calls["n"] >= 1:
                break
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError, asyncio.CancelledError, Exception:
            pass

    assert create_calls["n"] >= 1
    remaining = sorted(p.name for p in backup_dir.iterdir())
    assert len(remaining) <= 3


@pytest.mark.asyncio
async def test_scheduler_loop_idles_when_disabled(fe_settings, monkeypatch, tmp_path):
    from app.db.session import session_scope
    from app.models.entities import BackupSettings
    from app.services import backup_scheduler

    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MNEMOS_FE_BACKUP_DIR", str(backup_dir))

    with session_scope() as s:
        s.add(BackupSettings(enabled=False, cadence="daily", hour_utc=3, retention_count=7))

    create_calls = {"n": 0}

    def fake_create():
        create_calls["n"] += 1
        return _FakeResponse(201, {})

    monkeypatch.setattr(backup_scheduler, "backup_create", fake_create)

    import asyncio

    stop = asyncio.Event()
    task = asyncio.create_task(backup_scheduler._run_scheduler_loop(stop))
    try:
        await asyncio.sleep(0.2)
    finally:
        stop.set()
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except TimeoutError, asyncio.CancelledError, Exception:
            pass

    assert create_calls["n"] == 0


class _FakeResponse:
    def __init__(self, status_code: int, body) -> None:
        self.status_code = status_code
        self._body = body
        self.text = ""

    def json(self):
        return self._body
