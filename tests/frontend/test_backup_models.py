from __future__ import annotations

from datetime import datetime, timedelta

import pytest


@pytest.fixture
def fe_db(frontend_imports, tmp_path, monkeypatch):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.models import entities  # noqa: F401

    monkeypatch.setenv("MNEMOS_FE_DB_PATH", str(tmp_path / "fe.db"))
    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    return tmp_path


def test_backup_settings_round_trip(fe_db):

    from app.db.session import session_scope
    from app.models.entities import BackupCadence, BackupSettings

    row = BackupSettings(
        enabled=True,
        cadence=BackupCadence.WEEKLY.value,
        hour_utc=5,
        weekday_utc=3,
        retention_count=10,
        next_run_at=datetime.utcnow() + timedelta(hours=1),
    )
    with session_scope() as s:
        s.add(row)
        s.flush()
        rid = row.id

    with session_scope() as s:
        loaded = s.get(BackupSettings, rid)
    assert loaded is not None
    assert loaded.enabled is True
    assert loaded.cadence == "weekly"
    assert loaded.hour_utc == 5
    assert loaded.weekday_utc == 3
    assert loaded.retention_count == 10
    assert loaded.next_run_at is not None


def test_backup_settings_default_values(fe_db):
    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models.entities import BackupSettings

    with session_scope() as s:
        s.add(BackupSettings())
        s.flush()
        all_rows = s.execute(select(BackupSettings)).scalars().all()
    assert len(all_rows) == 1
    row = all_rows[0]
    assert row.enabled is False
    assert row.cadence == "daily"
    assert row.hour_utc == 3
    assert row.weekday_utc == 0
    assert row.retention_count == 7


def test_backup_job_round_trip(fe_db):

    from app.db.session import session_scope
    from app.models.entities import BackupJob, BackupJobStatus

    job = BackupJob(
        id="deadbeef" * 4,
        kind="restore",
        filename="mnemos-backup-20260101-000000.tar.gz",
        status=BackupJobStatus.RUNNING.value,
    )
    with session_scope() as s:
        s.add(job)

    with session_scope() as s:
        loaded = s.get(BackupJob, "deadbeef" * 4)
    assert loaded is not None
    assert loaded.kind == "restore"
    assert loaded.status == "running"
    assert loaded.filename == "mnemos-backup-20260101-000000.tar.gz"
    assert loaded.error is None
    assert loaded.finished_at is None


def test_backup_file_round_trip(fe_db):
    from app.db.session import session_scope
    from app.models.entities import BackupFile, BackupFileSource

    f = BackupFile(
        filename="mnemos-backup-20260101-000000.tar.gz",
        size_bytes=12345,
        sha256="abc" * 21 + "abcd",
        source=BackupFileSource.UPLOADED.value,
    )
    with session_scope() as s:
        s.add(f)

    with session_scope() as s:
        loaded = s.get(BackupFile, "mnemos-backup-20260101-000000.tar.gz")
    assert loaded is not None
    assert loaded.size_bytes == 12345
    assert loaded.sha256.endswith("abcd")
    assert loaded.source == "uploaded"


def test_backup_file_unique_filename(fe_db):
    import sqlalchemy.exc

    from app.db.session import session_scope
    from app.models.entities import BackupFile

    with session_scope() as s:
        s.add(BackupFile(filename="mnemos-backup-20260101-000000.tar.gz", size_bytes=1))

    raised = False
    try:
        with session_scope() as s:
            s.add(BackupFile(filename="mnemos-backup-20260101-000000.tar.gz", size_bytes=2))
    except sqlalchemy.exc.IntegrityError:
        raised = True
    except Exception as e:
        assert "UNIQUE constraint failed" in str(e) or "IntegrityError" in type(e).__name__, (
            f"unexpected: {e!r}"
        )
        raised = True
    assert raised, "expected duplicate filename to raise an integrity error"
