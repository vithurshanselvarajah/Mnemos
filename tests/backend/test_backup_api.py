from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest


@pytest.fixture
def backup_api_env(backend_imports, tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MNEMOS_BACKUP_DIR", str(backup_dir))
    return tmp_path, backup_dir


@pytest.fixture
def full_admin(backup_api_env):
    from fastapi.testclient import TestClient

    import app.models.entities
    from app.core import config
    from app.core.security import create_api_key
    from app.db.session import init_db, reset_engine
    from app.main import create_app
    from app.models.entities import PermissionLevel

    config.set_settings(None)
    reset_engine()
    init_db()
    _row, raw = create_api_key("admin-test", PermissionLevel.FULL_ADMIN.value)
    app = create_app()
    return app, TestClient(app), raw


def test_list_backups_requires_auth(backup_api_env):
    from fastapi.testclient import TestClient

    import app.models.entities
    from app.core import config
    from app.db.session import init_db, reset_engine
    from app.main import create_app

    config.set_settings(None)
    reset_engine()
    init_db()
    app = create_app()
    tc = TestClient(app)
    r = tc.get("/api/v1/backup")
    assert r.status_code in (401, 403)


def test_list_backups_returns_empty(full_admin):
    _app, tc, key = full_admin
    r = tc.get("/api/v1/backup", headers={"X-API-Key": key})
    assert r.status_code == 200
    data = r.json()
    assert "backups" in data
    assert "free_bytes" in data
    assert data["backups"] == []


def test_create_backup_returns_filename(full_admin, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    _app, tc, key = full_admin
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))
    _make_sqlite(Path(settings.db_path))
    r = tc.post("/api/v1/backup", headers={"X-API-Key": key})
    assert r.status_code == 201
    data = r.json()
    assert data["filename"].startswith("mnemos-backup-")
    assert data["size_bytes"] > 0


def test_inspect_requires_valid_filename(full_admin, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    _app, tc, key = full_admin
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))
    _make_sqlite(Path(settings.db_path))
    tc.post("/api/v1/backup", headers={"X-API-Key": key})
    r = tc.get("/api/v1/backup/../etc/passwd/inspect", headers={"X-API-Key": key})
    assert r.status_code in (400, 404)


def test_inspect_returns_404_for_missing(full_admin):
    _app, tc, key = full_admin
    r = tc.get("/api/v1/backup/mnemos-backup-20990101-000000.tar.gz/inspect", headers={"X-API-Key": key})
    assert r.status_code == 404


def test_delete_requires_valid_filename(full_admin):
    _app, tc, key = full_admin
    r = tc.delete("/api/v1/backup/bad_name.tar.gz", headers={"X-API-Key": key})
    assert r.status_code in (400, 404)


def test_restore_requires_confirm(full_admin, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    _app, tc, key = full_admin
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))
    _make_sqlite(Path(settings.db_path))
    cr = tc.post("/api/v1/backup", headers={"X-API-Key": key})
    name = cr.json()["filename"]
    r = tc.post(
        "/api/v1/backup/restore",
        json={"filename": name, "confirm": False},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_restore_returns_job_id(full_admin, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    _app, tc, key = full_admin
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))
    monkeypatch.setattr(backup_mod, "_pg_restore", lambda sql: None)
    _make_sqlite(Path(settings.db_path))
    cr = tc.post("/api/v1/backup", headers={"X-API-Key": key})
    name = cr.json()["filename"]
    r = tc.post(
        "/api/v1/backup/restore",
        json={"filename": name, "confirm": True},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 202
    data = r.json()
    assert "id" in data
    assert data["status"] in ("pending", "running", "done")
    assert data["filename"] == name

    jr = tc.get(f"/api/v1/backup/restore/{data['id']}", headers={"X-API-Key": key})
    assert jr.status_code == 200
    jd = jr.json()
    assert jd["id"] == data["id"]
    assert jd["status"] in ("running", "done", "error")


def test_restore_rejects_invalid_filename(full_admin):
    _app, tc, key = full_admin
    r = tc.post(
        "/api/v1/backup/restore",
        json={"filename": "../etc/passwd", "confirm": True},
        headers={"X-API-Key": key},
    )
    assert r.status_code == 400


def test_restore_status_404_for_unknown_job(full_admin):
    _app, tc, key = full_admin
    r = tc.get("/api/v1/backup/restore/deadbeef", headers={"X-API-Key": key})
    assert r.status_code == 404


def test_download_rejects_invalid_filename(full_admin):
    _app, tc, key = full_admin
    r = tc.get("/api/v1/backup/bad_name.tar.gz/download", headers={"X-API-Key": key})
    assert r.status_code in (400, 404)


def test_download_returns_404_for_missing(full_admin):
    _app, tc, key = full_admin
    r = tc.get(
        "/api/v1/backup/mnemos-backup-20990101-000000.tar.gz/download",
        headers={"X-API-Key": key},
    )
    assert r.status_code == 404


def test_download_serves_file(full_admin, monkeypatch):
    from app import backup as backup_mod
    from app.core.config import settings

    _app, tc, key = full_admin
    monkeypatch.setattr(backup_mod, "_pg_dumpall", lambda dest: dest.write_text(""))
    _make_sqlite(Path(settings.db_path))
    cr = tc.post("/api/v1/backup", headers={"X-API-Key": key})
    name = cr.json()["filename"]
    r = tc.get(f"/api/v1/backup/{name}/download", headers={"X-API-Key": key})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/gzip"
    assert "attachment" in r.headers.get("content-disposition", "")
    assert r.content[:2] == b"\x1f\x8b"


def _make_sqlite(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(str(path)) as conn:
        conn.execute("CREATE TABLE x (id INTEGER PRIMARY KEY)")
        conn.commit()
