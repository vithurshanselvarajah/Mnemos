from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
import tempfile
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

log = logging.getLogger("mnemos.backend.backup")

BACKUP_DIRNAME = "backups"
MANIFEST_NAME = "manifest.json"
BACKEND_DB_NAME = "backend.db"
FRONTEND_DB_NAME = "frontend.db"
CROPS_DIR_NAME = "crops"
PG_DUMP_NAME = "pg.sql"

FILENAME_RE = re.compile(r"^mnemos-backup-(\d{8})-(\d{6})\.tar\.gz$")


@dataclass
class BackupMetadata:
    filename: str
    size_bytes: int
    created_at: datetime
    sha256: str

    def as_dict(self) -> dict:
        return {
            "filename": self.filename,
            "size_bytes": self.size_bytes,
            "created_at": self.created_at.isoformat() + "Z",
            "sha256": self.sha256,
        }


@dataclass
class ManifestContents:
    backend_db_sha: str
    crops_sha: str
    pg_sha: str
    frontend_db_sha: str | None

    def as_dict(self) -> dict:
        out = {
            "backend_db_sha": self.backend_db_sha,
            "crops_sha": self.crops_sha,
            "pg_sha": self.pg_sha,
        }
        if self.frontend_db_sha is not None:
            out["frontend_db_sha"] = self.frontend_db_sha
        return out


def backup_dir() -> Path:
    base = Path(os.environ.get("MNEMOS_BACKUP_DIR", "/data/backups"))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _filename_for(now: datetime | None = None) -> str:
    n = now or datetime.utcnow()
    return f"mnemos-backup-{n.strftime('%Y%m%d-%H%M%S')}.tar.gz"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _dir_sha(root: Path) -> str:
    if not root.exists():
        return ""
    h = hashlib.sha256()
    files = sorted(p for p in root.rglob("*") if p.is_file())
    for p in files:
        rel = p.relative_to(root).as_posix().encode("utf-8")
        h.update(rel)
        h.update(b"\x00")
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                h.update(chunk)
        h.update(b"\x00")
    return h.hexdigest()


def _safe_filename(name: str) -> str:
    if not FILENAME_RE.match(name):
        raise ValueError(f"invalid backup filename: {name!r}")
    return name


def _safe_path(filename: str) -> Path:
    name = _safe_filename(filename)
    base = backup_dir().resolve()
    candidate = (base / name).resolve()
    try:
        candidate.relative_to(base)
    except ValueError as e:
        raise ValueError(f"backup path escapes backup dir: {filename!r}") from e
    return candidate


def list_backups() -> list[BackupMetadata]:
    base = backup_dir()
    out: list[BackupMetadata] = []
    for entry in sorted(base.iterdir()):
        if not entry.is_file():
            continue
        m = FILENAME_RE.match(entry.name)
        if not m:
            continue
        try:
            stat = entry.stat()
            sha = _sha256_file(entry)
            created = datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S")
        except Exception as e:
            log.warning("skipping unreadable backup %s: %s", entry.name, e)
            continue
        out.append(
            BackupMetadata(filename=entry.name, size_bytes=stat.st_size, created_at=created, sha256=sha)
        )
    out.sort(key=lambda b: b.created_at, reverse=True)
    return out


def _resolve_path(p: Path | str) -> Path:
    return Path(p)


def _sqlite_backup_via_api(src_db: Path, dest_db: Path) -> None:
    dest_db.parent.mkdir(parents=True, exist_ok=True)
    if dest_db.exists():
        dest_db.unlink()
    src = sqlite3.connect(str(src_db))
    try:
        dst = sqlite3.connect(str(dest_db))
        try:
            with dst:
                src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def _try_sqlite_backup_via_cli(src_db: Path, dest_db: Path) -> bool:
    if shutil.which("sqlite3") is None:
        return False
    dest_db.parent.mkdir(parents=True, exist_ok=True)
    if dest_db.exists():
        dest_db.unlink()
    r = subprocess.run(
        ["sqlite3", str(src_db), f".backup {dest_db}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        log.warning("sqlite3 CLI backup failed: %s", r.stderr)
        return False
    return dest_db.exists() and dest_db.stat().st_size > 0


def _backup_sqlite(src_db: Path, dest_db: Path) -> None:
    if not src_db.exists():
        raise FileNotFoundError(f"source SQLite not found: {src_db}")
    if not _try_sqlite_backup_via_cli(src_db, dest_db):
        _sqlite_backup_via_api(src_db, dest_db)


def _pg_dumpall(dest_sql: Path) -> None:
    dsn = os.environ.get(
        "MNEMOS_VECTOR_DSN", "postgresql://mnemos:mnemos@mnemos-vector-db:5432/mnemos_vectors"
    )
    dest_sql.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    r = subprocess.run(
        ["pg_dumpall", "-d", dsn, "--no-role-passwords"], capture_output=True, text=True, env=env
    )
    if r.returncode != 0:
        raise RuntimeError(f"pg_dumpall failed: {r.stderr.strip()}")
    dest_sql.write_text(r.stdout, encoding="utf-8")


def _tar_dir(src_dir: Path) -> bytes:
    if not src_dir.exists():
        return b""
    tmp = Path(tempfile.mkstemp(suffix=".tar")[1])
    try:
        with tarfile.open(tmp, "w") as tf:
            tf.add(str(src_dir), arcname=CROPS_DIR_NAME)
        return tmp.read_bytes()
    finally:
        tmp.unlink(missing_ok=True)


def _build_manifest(version: str, contents: ManifestContents) -> dict:
    return {
        "mnemos_backup_version": 1,
        "app_version": version,
        "created_at": datetime.utcnow().isoformat() + "Z",
        "contents": contents.as_dict(),
    }


def create_backup_tarball(
    *,
    backend_db: Path,
    crops_dir: Path,
    frontend_db: Path | None,
    app_version: str,
    out_path: Path | None = None,
) -> Path:
    out = out_path or (backup_dir() / _filename_for())
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="mnemos-bkp-") as tmpd:
        tmp = Path(tmpd)
        workdir = tmp / "work"
        workdir.mkdir()

        backend_copy = workdir / BACKEND_DB_NAME
        _backup_sqlite(backend_db, backend_copy)

        crops_archive = workdir / (CROPS_DIR_NAME + ".tar")
        crops_bytes = _tar_dir(crops_dir)
        if crops_bytes:
            crops_archive.write_bytes(crops_bytes)

        pg_sql = workdir / PG_DUMP_NAME
        _pg_dumpall(pg_sql)

        frontend_copy: Path | None = None
        if frontend_db is not None:
            frontend_copy = workdir / FRONTEND_DB_NAME
            if frontend_db.exists():
                _backup_sqlite(frontend_db, frontend_copy)
            else:
                frontend_copy = None

        contents = ManifestContents(
            backend_db_sha=_sha256_file(backend_copy),
            crops_sha=_dir_sha(crops_dir),
            pg_sha=_sha256_file(pg_sql),
            frontend_db_sha=_sha256_file(frontend_copy) if frontend_copy is not None else None,
        )
        manifest = _build_manifest(app_version, contents)
        manifest_path = workdir / MANIFEST_NAME
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        if out.exists():
            out.unlink()
        with tarfile.open(out, "w:gz") as tf:
            tf.add(str(manifest_path), arcname=MANIFEST_NAME)
            tf.add(str(backend_copy), arcname=BACKEND_DB_NAME)
            if crops_archive.exists() and crops_archive.stat().st_size > 0:
                tf.add(str(crops_archive), arcname=CROPS_DIR_NAME + ".tar")
            tf.add(str(pg_sql), arcname=PG_DUMP_NAME)
            if frontend_copy is not None:
                tf.add(str(frontend_copy), arcname=FRONTEND_DB_NAME)

    log.info("backup created: %s (%d bytes)", out, out.stat().st_size)
    return out


def read_manifest(tarball: Path) -> tuple[dict, dict]:
    with tarfile.open(tarball, "r:gz") as tf:
        names = tf.getnames()
        if MANIFEST_NAME not in names:
            raise ValueError("backup is missing manifest.json")
        with tf.extractfile(MANIFEST_NAME) as f:
            manifest = json.loads(f.read().decode("utf-8"))
        members: dict[str, bytes] = {}
        for n in names:
            if n == MANIFEST_NAME:
                continue
            member = tf.getmember(n)
            if not member.isfile():
                continue
            with tf.extractfile(member) as f:
                members[n] = f.read()
    return manifest, members


def inspect_backup(filename: str) -> dict:
    path = _safe_path(filename)
    name = path.name
    if not path.exists():
        raise FileNotFoundError(name)
    manifest, _members = read_manifest(path)
    stat = path.stat()
    return {
        "filename": name,
        "size_bytes": stat.st_size,
        "sha256": _sha256_file(path),
        "manifest": manifest,
    }


def extract_member(tarball: Path, member_name: str) -> bytes:
    with tarfile.open(tarball, "r:gz") as tf:
        if member_name not in tf.getnames():
            raise KeyError(member_name)
        with tf.extractfile(member_name) as f:
            return f.read()


def delete_backup(filename: str) -> None:
    path = _safe_path(filename)
    if not path.exists():
        raise FileNotFoundError(path.name)
    path.unlink()
    log.info("backup deleted: %s", path.name)


def _pg_restore(pg_sql_text: str) -> None:
    dsn = os.environ.get(
        "MNEMOS_VECTOR_DSN", "postgresql://mnemos:mnemos@mnemos-vector-db:5432/mnemos_vectors"
    )
    env = os.environ.copy()
    env.setdefault("PGCONNECT_TIMEOUT", "10")
    r = subprocess.run(
        ["psql", "-d", dsn, "-v", "ON_ERROR_STOP=1", "-q"],
        input=pg_sql_text,
        capture_output=True,
        text=True,
        env=env,
    )
    if r.returncode != 0:
        raise RuntimeError(f"psql restore failed: {r.stderr.strip()}")


def _atomic_replace(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        dest.unlink()
    os.replace(src, dest)


def _replace_crops_from_tar(crops_tar_bytes: bytes, dest_dir: Path) -> None:
    dest_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mnemos-crops-") as tmpd:
        tmp_tar = Path(tmpd) / "crops.tar"
        tmp_tar.write_bytes(crops_tar_bytes)
        tmp_extract = Path(tmpd) / "extract"
        tmp_extract.mkdir()
        with tarfile.open(tmp_tar, "r") as tf:
            tf.extractall(tmp_extract, filter="data")
        src_dir = tmp_extract / CROPS_DIR_NAME
        if not src_dir.exists():
            candidates = [p for p in tmp_extract.iterdir() if p.is_dir()]
            src_dir = candidates[0] if candidates else tmp_extract
        for p in dest_dir.iterdir():
            if p.is_file() or p.is_symlink():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p)
        for p in src_dir.iterdir():
            target = dest_dir / p.name
            if p.is_dir():
                shutil.copytree(p, target)
            else:
                shutil.copy2(p, target)


def restore_backup(
    filename: str,
    *,
    backend_db_dest: Path,
    crops_dir_dest: Path,
    frontend_db_dest: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> None:
    name = _safe_filename(filename)
    src = backup_dir() / name
    if not src.exists():
        raise FileNotFoundError(name)
    if progress is not None:
        progress(f"reading backup {name}")
    manifest, members = read_manifest(src)
    expected = manifest.get("contents", {})

    if BACKEND_DB_NAME not in members:
        raise ValueError("backup is missing backend.db")
    if PG_DUMP_NAME not in members:
        raise ValueError("backup is missing pg.sql")
    if progress is not None:
        progress("replacing backend.db")
    with tempfile.NamedTemporaryFile(prefix="mnemos-restore-", suffix=".db", delete=False) as tf:
        tmp_db = Path(tf.name)
    try:
        tmp_db.write_bytes(members[BACKEND_DB_NAME])
        _atomic_replace(tmp_db, backend_db_dest)
    finally:
        if tmp_db.exists():
            tmp_db.unlink()
    if expected.get("backend_db_sha") and _sha256_file(backend_db_dest) != expected["backend_db_sha"]:
        raise RuntimeError("backend.db checksum mismatch after restore")

    crops_tar = members.get(CROPS_DIR_NAME + ".tar")
    if crops_tar:
        if progress is not None:
            progress("replacing crops directory")
        _replace_crops_from_tar(crops_tar, crops_dir_dest)
    elif expected.get("crops_sha"):
        raise ValueError("backup manifest references crops but archive has no crops.tar")

    if progress is not None:
        progress("restoring PostgreSQL (pg.sql)")
    _pg_restore(members[PG_DUMP_NAME].decode("utf-8"))
    if progress is not None:
        progress("psql restore complete")

    if frontend_db_dest is not None and FRONTEND_DB_NAME in members:
        if progress is not None:
            progress("replacing frontend.db")
        with tempfile.NamedTemporaryFile(prefix="mnemos-restore-fe-", suffix=".db", delete=False) as tf:
            tmp_fe = Path(tf.name)
        try:
            tmp_fe.write_bytes(members[FRONTEND_DB_NAME])
            _atomic_replace(tmp_fe, frontend_db_dest)
        finally:
            if tmp_fe.exists():
                tmp_fe.unlink()
    if progress is not None:
        progress("restore complete")


class RestoreJob:
    def __init__(self) -> None:
        self.id: str = uuid.uuid4().hex
        self.status: str = "pending"
        self.log: list[str] = []
        self.error: str | None = None
        self.filename: str | None = None
        self.started_at: float = time.time()
        self.finished_at: float | None = None
        self._thread: threading.Thread | None = None

    def _append(self, msg: str) -> None:
        ts = datetime.utcnow().strftime("%H:%M:%S")
        self.log.append(f"[{ts}] {msg}")
        if len(self.log) > 200:
            self.log = self.log[-200:]

    def as_dict(self) -> dict:
        return {
            "id": self.id,
            "status": self.status,
            "filename": self.filename,
            "log": list(self.log),
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

    def start(self, filename: str, **kwargs) -> None:
        self.filename = filename
        self.status = "running"
        self._append(f"restore job started for {filename}")
        self._thread = threading.Thread(
            target=self._run, kwargs=kwargs, daemon=True, name=f"mnemos-restore-{self.id}"
        )
        self._thread.start()

    def _run(self, **kwargs) -> None:
        try:
            restore_backup(self.filename, progress=self._append, **kwargs)
            self.status = "done"
            self._append("done")
        except Exception as e:
            self.status = "error"
            self.error = f"{type(e).__name__}: {e}"
            self._append(f"ERROR: {self.error}")
        finally:
            self.finished_at = time.time()


_JOBS: dict[str, RestoreJob] = {}
_JOBS_LOCK = threading.Lock()


def start_restore_job(filename: str, **kwargs) -> RestoreJob:
    name = _safe_filename(filename)
    with _JOBS_LOCK:
        for existing in _JOBS.values():
            if existing.status == "running":
                raise RuntimeError("a restore is already in progress")
        job = RestoreJob()
        _JOBS[job.id] = job
    job.start(name, **kwargs)
    return job


def get_job(job_id: str) -> RestoreJob | None:
    with _JOBS_LOCK:
        return _JOBS.get(job_id)


def prune_finished_jobs(max_keep: int = 20) -> None:
    with _JOBS_LOCK:
        finished = sorted(
            [j for j in _JOBS.values() if j.status in ("done", "error")],
            key=lambda j: j.finished_at or 0,
        )
        for j in finished[:-max_keep]:
            _JOBS.pop(j.id, None)


def disk_free_bytes(path: Path | None = None) -> int:
    p = path or backup_dir()
    usage = shutil.disk_usage(str(p))
    return usage.free


def disk_total_bytes(path: Path | None = None) -> int:
    p = path or backup_dir()
    usage = shutil.disk_usage(str(p))
    return usage.total


def list_known_filenames() -> list[str]:
    return [b.filename for b in list_backups()]
