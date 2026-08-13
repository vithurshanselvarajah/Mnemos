from __future__ import annotations

from unittest import mock

import pytest


@pytest.fixture
def fe_setup_backup(frontend_imports, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core import config
    from app.core.config import set_settings
    from app.db.session import init_db, reset_engine
    from app.main import create_app
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
    app = create_app()
    return app, TestClient(app), tmp_path, db_path, backup_dir


@pytest.fixture
def admin_with_backend(fe_setup_backup):
    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import BackendNode, User, UserRole

    app, tc, tmp, db, bk = fe_setup_backup
    with session_scope() as s:
        u = User(username="admin", password_hash=hash_password("password"), role=UserRole.ADMIN.value)
        s.add(u)
        s.add(BackendNode(name="b", base_url="http://b:8000", api_key="k"))
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    return app, tc, tmp, db, bk


@pytest.fixture
def operator_logged_in(fe_setup_backup):
    from app.core.auth import hash_password
    from app.core.middleware import issue_session
    from app.db.session import session_scope
    from app.models.entities import BackendNode, User, UserRole

    app, tc, tmp, db, bk = fe_setup_backup
    with session_scope() as s:
        u = User(username="op", password_hash=hash_password("password"), role=UserRole.OPERATOR.value)
        s.add(u)
        s.add(BackendNode(name="b", base_url="http://b:8000", api_key="k"))
        s.flush()
        uid = u.id
    token, _ = issue_session(uid, remember=True)
    tc.cookies.set("mnemos_sid", token)
    return app, tc, tmp, db, bk


def test_backup_list_requires_auth(fe_setup_backup):
    _app, tc, *_ = fe_setup_backup
    r = tc.get("/partials/backup/list", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code in (303, 401)


def test_backup_list_requires_admin(operator_logged_in):
    _app, tc, *_ = operator_logged_in
    r = tc.get("/partials/backup/list", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 403


def test_backup_list_renders_empty_state(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_list",
        lambda: mock.Mock(status_code=200, json=lambda: {"backups": []}),
    )
    r = tc.get("/partials/backup/list", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "No backups yet" in r.text


def test_backup_list_renders_files(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_list",
        lambda: mock.Mock(
            status_code=200,
            json=lambda: {
                "backups": [
                    {
                        "filename": "mnemos-backup-20260101-000000.tar.gz",
                        "size_bytes": 1024,
                        "created_at": "2026-01-01T00:00:00Z",
                        "sha256": "abcd" * 16,
                    }
                ]
            },
        ),
    )
    r = tc.get("/partials/backup/list", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "mnemos-backup-20260101-000000.tar.gz" in r.text
    assert "abcdabcd" in r.text


def test_backup_create_calls_backend_and_refreshes(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    called = {"count": 0}
    list_calls = {"count": 0}

    def fake_create():
        called["count"] += 1
        return mock.Mock(status_code=201, text="{}", json=lambda: {"filename": "x.tar.gz", "size_bytes": 1})

    def fake_list():
        list_calls["count"] += 1
        return mock.Mock(status_code=200, json=lambda: {"backups": []})

    monkeypatch.setattr("app.api.partials_backup.backup_create", fake_create)
    monkeypatch.setattr("app.api.partials_backup.backup_list", fake_list)
    r = tc.post("/partials/backup/create", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert called["count"] == 1
    assert list_calls["count"] == 1


def test_backup_create_propagates_backend_error(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_create",
        lambda: mock.Mock(status_code=500, text="boom", json=lambda: {"detail": "boom"}),
    )
    r = tc.post("/partials/backup/create", headers={"Accept": "text/html"})
    assert r.status_code == 500
    assert "boom" in r.text


def test_backup_delete_calls_backend_and_cleans_local(admin_with_backend, monkeypatch):
    _app, tc, _tmp, _db, bk = admin_with_backend
    name = "mnemos-backup-20260101-000000.tar.gz"
    (bk / name).write_bytes(b"x")
    monkeypatch.setattr(
        "app.api.partials_backup.backup_delete",
        lambda fn: mock.Mock(status_code=204, text=""),
    )
    r = tc.delete(f"/partials/backup/{name}", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert not (bk / name).exists()
    assert "Deleted" in r.text


def test_backup_delete_rejects_path_traversal(operator_logged_in, monkeypatch):
    _app, tc, *_ = operator_logged_in
    r = tc.delete("/partials/backup/bad_name.tar.gz", headers={"Accept": "text/html"})
    assert r.status_code in (400, 403, 404)


def test_backup_restore_requires_confirm(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    r = tc.post(
        "/partials/backup/restore",
        data={"filename": "mnemos-backup-20260101-000000.tar.gz"},
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 400
    assert "confirm" in r.text.lower()


def test_backup_restore_returns_status_partial(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_restore",
        lambda fn: mock.Mock(
            status_code=202,
            json=lambda: {"id": "abc123", "status": "running", "filename": fn, "log": []},
        ),
    )
    r = tc.post(
        "/partials/backup/restore",
        data={"filename": "mnemos-backup-20260101-000000.tar.gz", "confirm": "on"},
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200
    assert "Restoring" in r.text
    assert "mnemos-backup-20260101-000000.tar.gz" in r.text


def test_backup_restore_handles_409(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_restore",
        lambda fn: mock.Mock(status_code=409, text="busy", json=lambda: {"detail": "busy"}),
    )
    r = tc.post(
        "/partials/backup/restore",
        data={"filename": "mnemos-backup-20260101-000000.tar.gz", "confirm": "on"},
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 409


def test_restore_verify_reports_ok_when_stored_key_still_works(
    admin_with_backend, monkeypatch
):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_list",
        lambda: mock.Mock(status_code=200, json=lambda: {"backups": []}),
    )
    r = tc.get(
        "/partials/backup/restore-verify/abc123?target_id=restore-status-2",
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200
    assert "pairing still valid" in r.text
    assert "Re-pair" not in r.text
    assert "id=\"restore-status-2\"" in r.text or "id='restore-status-2'" in r.text


def test_restore_verify_reports_repair_needed_on_401(
    admin_with_backend, monkeypatch
):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_list",
        lambda: mock.Mock(status_code=401, text="unauth"),
    )
    r = tc.get(
        "/partials/backup/restore-verify/abc123?target_id=restore-status-2",
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200
    assert "no longer works" in r.text
    assert "Re-pair now" in r.text


def test_restore_verify_reports_repair_needed_when_backend_unreachable(
    admin_with_backend, monkeypatch
):
    _app, tc, *_ = admin_with_backend

    def boom():
        raise RuntimeError("connection refused")

    monkeypatch.setattr("app.api.partials_backup.backup_list", boom)
    r = tc.get(
        "/partials/backup/restore-verify/abc123?target_id=restore-status-2",
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200
    assert "no longer works" in r.text


def test_backup_upload_stores_file_and_inserts_row(admin_with_backend):
    _app, tc, _tmp, _db, bk = admin_with_backend
    content = b"fake tarball"
    files = {
        "file": (
            "mnemos-backup-20260101-000000.tar.gz",
            content,
            "application/gzip",
        )
    }
    r = tc.post("/partials/backup/upload", files=files, headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert (bk / "mnemos-backup-20260101-000000.tar.gz").read_bytes() == content

    from app.db.session import session_scope
    from app.models.entities import BackupFile, BackupFileSource

    with session_scope() as s:
        row = s.get(BackupFile, "mnemos-backup-20260101-000000.tar.gz")
    assert row is not None
    assert row.source == BackupFileSource.UPLOADED.value
    assert row.size_bytes == len(content)


def test_backup_upload_rejects_bad_filename(admin_with_backend):
    _app, tc, *_ = admin_with_backend
    files = {"file": ("bad.tar.gz", b"x", "application/gzip")}
    r = tc.post("/partials/backup/upload", files=files, headers={"Accept": "text/html"})
    assert r.status_code == 400


def test_backup_download_serves_local_file(admin_with_backend):
    _app, tc, _tmp, _db, bk = admin_with_backend
    name = "mnemos-backup-20260101-000000.tar.gz"
    payload = b"the actual bytes"
    (bk / name).write_bytes(payload)
    r = tc.get(f"/partials/backup/download/{name}")
    assert r.status_code == 200
    assert r.content == payload
    assert "attachment" in r.headers.get("content-disposition", "")


def test_backup_download_rejects_bad_filename(operator_logged_in, monkeypatch):
    _app, tc, *_ = operator_logged_in
    r = tc.get("/partials/backup/download/bad_name.tar.gz")
    assert r.status_code in (400, 403, 404)


def test_backup_schedule_persists_settings(admin_with_backend):
    _app, tc, *_ = admin_with_backend
    r = tc.post(
        "/partials/backup/schedule",
        data={
            "enabled": "on",
            "cadence": "weekly",
            "hour_utc": "5",
            "weekday_utc": "2",
            "retention_count": "14",
        },
        headers={"Accept": "text/html"},
    )
    assert r.status_code == 200

    from sqlalchemy import select

    from app.db.session import session_scope
    from app.models.entities import BackupSettings

    with session_scope() as s:
        row = s.execute(select(BackupSettings)).scalars().first()
    assert row is not None
    assert row.enabled is True
    assert row.cadence == "weekly"
    assert row.hour_utc == 5
    assert row.weekday_utc == 2
    assert row.retention_count == 14


def test_backup_settings_renders(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    r = tc.get("/partials/backup/settings", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Enable scheduled backups" in r.text


def test_backup_page_requires_admin(operator_logged_in):
    _app, tc, *_ = operator_logged_in
    r = tc.get("/backup", headers={"Accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303
    assert "/dashboard" in r.headers["location"]


def test_backup_page_renders_for_admin(admin_with_backend):
    _app, tc, *_ = admin_with_backend
    r = tc.get("/backup", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "Backup" in r.text
    assert "/partials/backup/list" in r.text
    assert "/partials/backup/upload" in r.text
    assert "/partials/backup/settings" in r.text


def test_backup_list_renders_per_row_restore_form(admin_with_backend, monkeypatch):
    _app, tc, *_ = admin_with_backend
    monkeypatch.setattr(
        "app.api.partials_backup.backup_list",
        lambda: mock.Mock(
            status_code=200,
            json=lambda: {
                "backups": [
                    {
                        "filename": "mnemos-backup-20260101-000000.tar.gz",
                        "size_bytes": 1024,
                        "created_at": "2026-01-01T00:00:00Z",
                        "sha256": "abcd" * 16,
                    }
                ]
            },
        ),
    )
    r = tc.get("/partials/backup/list", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert "/partials/backup/restore" in r.text
    assert 'name="target_id"' in r.text
    assert "Confirm restore" in r.text
