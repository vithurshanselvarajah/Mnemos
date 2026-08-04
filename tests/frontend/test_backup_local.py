from __future__ import annotations

import sqlite3
import tarfile

import pytest


@pytest.fixture
def fe_with_db(frontend_imports, tmp_path, monkeypatch):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.models import entities  # noqa: F401

    db_path = tmp_path / "frontend.db"
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MNEMOS_FE_DB_PATH", str(db_path))
    monkeypatch.setenv("MNEMOS_FE_BACKUP_DIR", str(backup_dir))
    config.set_settings(config.Settings())
    set_settings(config.Settings())
    reset_engine()
    init_db()
    with sqlite3.connect(str(db_path)) as conn:
        conn.execute("CREATE TABLE sample (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
        conn.execute("INSERT INTO sample (name) VALUES ('alpha'), ('beta')")
        conn.commit()
    return tmp_path, db_path, backup_dir


def test_snapshot_frontend_db_creates_copy(fe_with_db):
    from app.services import backup_local

    _tmp, _db_path, _bk = fe_with_db
    dest = _tmp / "snap.db"
    backup_local.snapshot_frontend_db(dest)
    assert dest.exists()
    assert dest.stat().st_size > 0
    with sqlite3.connect(str(dest)) as conn:
        rows = conn.execute("SELECT name FROM sample ORDER BY name").fetchall()
    assert rows == [("alpha",), ("beta",)]


def test_snapshot_frontend_db_missing_raises(frontend_imports, tmp_path, monkeypatch):
    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.services import backup_local

    monkeypatch.setenv("MNEMOS_FE_DB_PATH", str(tmp_path / "missing.db"))
    monkeypatch.setenv("MNEMOS_FE_BACKUP_DIR", str(tmp_path / "backups"))
    config.set_settings(None)
    set_settings(None)
    reset_engine()
    init_db()
    (tmp_path / "missing.db").unlink()
    with pytest.raises(FileNotFoundError):
        backup_local.snapshot_frontend_db(tmp_path / "dest.db")


def test_save_uploaded_backup_creates_file(fe_with_db):
    from app.services import backup_local

    _tmp, _db, _bk = fe_with_db
    src = _tmp / "src.tar.gz"
    src.write_bytes(b"hello backup content")
    name = "mnemos-backup-20260101-000000.tar.gz"
    dest = backup_local.save_uploaded_backup(name, src)
    assert dest.exists()
    assert dest.read_bytes() == b"hello backup content"


def test_save_uploaded_backup_rejects_bad_filename(fe_with_db):
    from app.services import backup_local

    _tmp, _db, _bk = fe_with_db
    src = _tmp / "src.tar.gz"
    src.write_bytes(b"x")
    with pytest.raises(ValueError):
        backup_local.save_uploaded_backup("not-a-valid-name.tar.gz", src)


def test_list_backups_returns_sorted(fe_with_db):
    from app.services import backup_local

    _tmp, _db, backup_dir = fe_with_db
    files = [
        "mnemos-backup-20260101-120000.tar.gz",
        "mnemos-backup-20260102-120000.tar.gz",
        "mnemos-backup-20260103-120000.tar.gz",
    ]
    for n in files:
        (backup_dir / n).write_bytes(b"x")
    items = backup_local.list_backups()
    assert [i.filename for i in items] == list(reversed(files))
    assert all(i.size_bytes == 1 for i in items)
    assert all(len(i.sha256) == 64 for i in items)


def test_delete_backup_removes_file(fe_with_db):
    from app.services import backup_local

    _tmp, _db, backup_dir = fe_with_db
    name = "mnemos-backup-20260101-000000.tar.gz"
    (backup_dir / name).write_bytes(b"x")
    backup_local.delete_backup(name)
    assert not (backup_dir / name).exists()


def test_delete_backup_rejects_bad_filename(fe_with_db):
    from app.services import backup_local

    _tmp, _db, _bk = fe_with_db
    with pytest.raises(ValueError):
        backup_local.delete_backup("../etc/passwd")


def test_is_valid_filename(fe_with_db):
    from app.services import backup_local

    _tmp, _db, _bk = fe_with_db
    assert backup_local.is_valid_filename("mnemos-backup-20260804-123045.tar.gz")
    assert not backup_local.is_valid_filename("foo.tar.gz")
    assert not backup_local.is_valid_filename("mnemos-backup-20260804.tar.gz")
    assert not backup_local.is_valid_filename("")


def test_peek_archive_returns_members(fe_with_db):

    from app.services import backup_local

    _tmp, _db, backup_dir = fe_with_db
    archive_path = backup_dir / "mnemos-backup-20260101-000000.tar.gz"
    with tarfile.open(archive_path, "w:gz") as tf:
        tf.add(__file__, arcname="hello.txt")
    info = backup_local.peek_archive(archive_path)
    assert info["filename"] == archive_path.name
    assert any(m["name"] == "hello.txt" for m in info["members"])
