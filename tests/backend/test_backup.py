from __future__ import annotations

import sqlite3
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def backend_env_for_backup(backend_imports, tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MNEMOS_BACKUP_DIR", str(backup_dir))
    return tmp_path, backup_dir


@pytest.fixture
def mock_pg(backend_env_for_backup, monkeypatch):
    from app import backup as backup_mod

    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text("-- mock pg\n"))
    monkeypatch.setattr(backup_mod, "_pg_restore", lambda sql: None)


def _make_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (name) VALUES ('hello'), ('world')")
        conn.commit()


def _make_crops(root: Path) -> None:
    (root / "a.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"A" * 200)
    (root / "b.jpg").write_bytes(b"\xff\xd8\xff\xe0" + b"B" * 100)
    (root / "sub").mkdir()
    (root / "sub" / "c.jpg").write_bytes(b"C" * 50)


def test_backup_create_list_inspect_delete(backend_env_for_backup, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    _tmp, bk_dir = backend_env_for_backup
    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    _make_sqlite(backend_db)
    _make_crops(crops_dir)

    monkeypatch.setattr(
        backup_mod, "_pg_dumpall", lambda dest: dest.write_text("-- mock pg\nCREATE TABLE x();\n")
    )

    out_path = bk_dir / "mnemos-backup-20260101-000000.tar.gz"
    result = backup_mod.create_backup_tarball(
        backend_db=backend_db,
        crops_dir=crops_dir,
        frontend_db=None,
        app_version="test-1.0",
        out_path=out_path,
    )
    assert result == out_path
    assert out_path.exists() and out_path.stat().st_size > 0

    items = backup_mod.list_backups()
    assert any(b.filename == out_path.name for b in items)

    info = backup_mod.inspect_backup(out_path.name)
    assert info["filename"] == out_path.name
    assert info["manifest"]["mnemos_backup_version"] == 1
    assert info["manifest"]["app_version"] == "test-1.0"
    assert "backend_db_sha" in info["manifest"]["contents"]

    backup_mod.delete_backup(out_path.name)
    assert not out_path.exists()


def test_backup_create_bundles_crops_tarball(backend_env_for_backup, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    tmp, _bk = backend_env_for_backup
    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    _make_sqlite(backend_db)
    _make_crops(crops_dir)
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))

    out = backup_mod.create_backup_tarball(
        backend_db=backend_db,
        crops_dir=crops_dir,
        frontend_db=None,
        app_version="v",
        out_path=tmp / "backups" / "mnemos-backup-20260102-000000.tar.gz",
    )
    with tarfile.open(out, "r:gz") as tf:
        names = tf.getnames()
    assert "manifest.json" in names
    assert "backend.db" in names
    assert "crops.tar" in names
    assert "pg.sql" in names
    assert "frontend.db" not in names


def test_backup_create_includes_frontend_db_when_provided(backend_env_for_backup, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    tmp, _bk = backend_env_for_backup
    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    fe_db = tmp / "fe.db"
    _make_sqlite(backend_db)
    _make_sqlite(fe_db)
    _make_crops(crops_dir)
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))

    out = backup_mod.create_backup_tarball(
        backend_db=backend_db,
        crops_dir=crops_dir,
        frontend_db=fe_db,
        app_version="v",
        out_path=tmp / "backups" / "mnemos-backup-20260103-000000.tar.gz",
    )
    with tarfile.open(out, "r:gz") as tf:
        names = tf.getnames()
    assert "frontend.db" in names


def test_safe_filename_rejects_path_traversal(backend_imports):
    from app import backup as backup_mod

    with pytest.raises(ValueError):
        backup_mod._safe_filename("../etc/passwd")
    with pytest.raises(ValueError):
        backup_mod._safe_filename("not-a-backup.tar.gz")
    assert (
        backup_mod._safe_filename("mnemos-backup-20260101-000000.tar.gz")
        == "mnemos-backup-20260101-000000.tar.gz"
    )


def test_backup_dir_creates_directory(backend_imports, tmp_path, monkeypatch):
    from app import backup as backup_mod

    monkeypatch.setenv("MNEMOS_BACKUP_DIR", str(tmp_path / "newly-created"))
    d = backup_mod.backup_dir()
    assert d.exists()
    assert d.is_dir()


def test_restore_replaces_backend_db(backend_env_for_backup, mock_pg, monkeypatch, tmp_path):
    from app import backup as backup_mod
    from app.core.config import settings

    tmp, _bk = backend_env_for_backup
    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    _make_sqlite(backend_db)
    _make_crops(crops_dir)
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))

    out = backup_mod.create_backup_tarball(
        backend_db=backend_db,
        crops_dir=crops_dir,
        frontend_db=None,
        app_version="v",
        out_path=tmp / "backups" / "mnemos-backup-20260104-000000.tar.gz",
    )
    backend_db.unlink()
    backup_mod.restore_backup(
        out.name,
        backend_db_dest=backend_db,
        crops_dir_dest=crops_dir,
        progress=lambda m: None,
    )
    assert backend_db.exists()
    with sqlite3.connect(str(backend_db)) as conn:
        rows = conn.execute("SELECT name FROM sample").fetchall()
    assert sorted(r[0] for r in rows) == ["hello", "world"]


def test_restore_replaces_crops(backend_env_for_backup, mock_pg, monkeypatch, tmp_path):
    from app import backup as backup_mod
    from app.core.config import settings

    tmp, _bk = backend_env_for_backup
    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    _make_sqlite(backend_db)
    _make_crops(crops_dir)
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))

    out = backup_mod.create_backup_tarball(
        backend_db=backend_db,
        crops_dir=crops_dir,
        frontend_db=None,
        app_version="v",
        out_path=tmp / "backups" / "mnemos-backup-20260105-000000.tar.gz",
    )
    for f in crops_dir.iterdir():
        if f.is_file():
            f.unlink()
        elif f.is_dir():
            import shutil

            shutil.rmtree(f)
    assert not list(crops_dir.iterdir())

    backup_mod.restore_backup(
        out.name,
        backend_db_dest=backend_db,
        crops_dir_dest=crops_dir,
        progress=lambda m: None,
    )
    assert (crops_dir / "a.jpg").exists()
    assert (crops_dir / "b.jpg").exists()
    assert (crops_dir / "sub" / "c.jpg").exists()


def test_restore_rejects_missing_backup(backend_env_for_backup):
    from app import backup as backup_mod
    from app.core.config import settings

    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    with pytest.raises(FileNotFoundError):
        backup_mod.restore_backup(
            "mnemos-backup-20990101-000000.tar.gz",
            backend_db_dest=backend_db,
            crops_dir_dest=crops_dir,
            progress=lambda m: None,
        )


def test_restore_rejects_invalid_filename(backend_env_for_backup):
    from app import backup as backup_mod
    from app.core.config import settings

    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    with pytest.raises(ValueError):
        backup_mod.restore_backup(
            "../etc/passwd",
            backend_db_dest=backend_db,
            crops_dir_dest=crops_dir,
            progress=lambda m: None,
        )


def test_restore_job_lifecycle(backend_env_for_backup, mock_pg, monkeypatch, tmp_path):
    from app import backup as backup_mod
    from app.core.config import settings

    tmp, _bk = backend_env_for_backup
    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    _make_sqlite(backend_db)
    _make_crops(crops_dir)
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))

    out = backup_mod.create_backup_tarball(
        backend_db=backend_db,
        crops_dir=crops_dir,
        frontend_db=None,
        app_version="v",
        out_path=tmp / "backups" / "mnemos-backup-20260106-000000.tar.gz",
    )
    backend_db.unlink()

    job = backup_mod.start_restore_job(
        out.name,
        backend_db_dest=backend_db,
        crops_dir_dest=crops_dir,
    )
    job._thread.join(timeout=15)
    assert job.status == "done"
    assert backend_db.exists()


def test_restore_job_records_error(backend_env_for_backup, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    job = backup_mod.start_restore_job(
        "mnemos-backup-20990101-000000.tar.gz",
        backend_db_dest=backend_db,
        crops_dir_dest=crops_dir,
    )
    job._thread.join(timeout=5)
    assert job.status == "error"
    assert "FileNotFoundError" in (job.error or "")


def test_restore_job_rejects_concurrent(backend_env_for_backup, mock_pg, monkeypatch, tmp_path):
    from app import backup as backup_mod
    from app.core.config import settings

    tmp, _bk = backend_env_for_backup
    backend_db = Path(settings.db_path)
    crops_dir = Path(settings.crops_dir)
    _make_sqlite(backend_db)
    _make_crops(crops_dir)
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))

    out = backup_mod.create_backup_tarball(
        backend_db=backend_db,
        crops_dir=crops_dir,
        frontend_db=None,
        app_version="v",
        out_path=tmp / "backups" / "mnemos-backup-20260107-000000.tar.gz",
    )

    started = []
    original_restore = backup_mod.restore_backup

    def slow_restore(*args, **kwargs):
        started.append(1)
        import time

        time.sleep(0.5)
        return original_restore(*args, **kwargs)

    monkeypatch.setattr(backup_mod, "restore_backup", slow_restore)
    job = backup_mod.start_restore_job(out.name, backend_db_dest=backend_db, crops_dir_dest=crops_dir)
    try:
        with pytest.raises(RuntimeError):
            backup_mod.start_restore_job(out.name, backend_db_dest=backend_db, crops_dir_dest=crops_dir)
    finally:
        job._thread.join(timeout=10)
