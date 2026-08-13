from __future__ import annotations

import hashlib
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.core.config import settings

log = logging.getLogger("mnemos.frontend.backup")

BACKUP_SUBDIR = "backups"
FILENAME_RE = re.compile(r"^mnemos-backup-(\d{8})-(\d{6})\.tar\.gz$")


@dataclass
class LocalBackupMetadata:
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


def backup_dir() -> Path:
    base = Path(os.environ.get("MNEMOS_FE_BACKUP_DIR", str(Path(settings.db_path).parent / BACKUP_SUBDIR)))
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


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


def snapshot_frontend_db(dest: Path) -> Path:
    src_db = Path(settings.db_path)
    if not src_db.exists():
        raise FileNotFoundError(f"frontend sqlite not found: {src_db}")
    if not _try_sqlite_backup_via_cli(src_db, dest):
        _sqlite_backup_via_api(src_db, dest)
    return dest


def list_backups() -> list[LocalBackupMetadata]:
    base = backup_dir()
    out: list[LocalBackupMetadata] = []
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
            LocalBackupMetadata(filename=entry.name, size_bytes=stat.st_size, created_at=created, sha256=sha)
        )
    out.sort(key=lambda b: b.created_at, reverse=True)
    return out


def is_valid_filename(name: str) -> bool:
    return bool(FILENAME_RE.match(name))


def find_local_backup(name: str) -> Path | None:
    if not is_valid_filename(name):
        return None
    base = backup_dir()
    try:
        for entry in base.iterdir():
            if entry.name == name and entry.is_file():
                return entry
    except FileNotFoundError, OSError:
        return None
    return None


def reserve_upload_path(name: str) -> Path:
    if not is_valid_filename(name):
        raise ValueError(f"invalid backup filename: {name!r}")
    base_real = os.path.realpath(str(backup_dir()))
    candidate_real = os.path.realpath(os.path.join(base_real, name))
    if candidate_real != base_real and not candidate_real.startswith(base_real + os.sep):
        raise ValueError(f"backup path escapes backup dir: {name!r}")
    return Path(candidate_real)


def delete_backup(name: str) -> None:
    if not is_valid_filename(name):
        raise ValueError(f"invalid backup filename: {name!r}")
    path = find_local_backup(name)
    if path is None:
        raise FileNotFoundError(name)
    path.unlink()
    log.info("backup deleted: %s", name)


def reserve_path(name: str) -> Path:
    return reserve_upload_path(name)


def save_uploaded_backup(name: str, source: Path) -> Path:
    dest = reserve_path(name)
    shutil.copy2(source, dest)
    log.info("uploaded backup stored: %s (%d bytes)", dest, dest.stat().st_size)
    return dest


def disk_free_bytes() -> int:
    usage = shutil.disk_usage(str(backup_dir()))
    return usage.free


def disk_total_bytes() -> int:
    usage = shutil.disk_usage(str(backup_dir()))
    return usage.total


def peek_archive(path: Path) -> dict:
    info = {"filename": path.name, "size_bytes": path.stat().st_size, "members": []}
    with tarfile.open(path, "r:gz") as tf:
        for n in tf.getnames():
            try:
                m = tf.getmember(n)
                info["members"].append({"name": n, "size": m.size})
            except KeyError:
                continue
    return info
