from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

from app import backup as backup_mod
from app.core.config import settings
from app.core.security import rotate_master_key, view_master_key
from app.core.version import get_version
from app.db.session import init_db


def cmd_master_view(_args) -> int:
    print(view_master_key())
    return 0


def cmd_master_rotate(_args) -> int:
    print(rotate_master_key())
    return 0


def cmd_healthz(args) -> int:
    base = args.base or f"http://127.0.0.1:{settings.api_port}"
    url = base.rstrip("/") + "/healthz"
    with urllib.request.urlopen(url, timeout=5) as r:
        body = r.read().decode("utf-8", "replace")
        try:
            print(json.dumps(json.loads(body), indent=2))
        except Exception:
            print(body)
    return 0


def cmd_backup_list(_args) -> int:
    out = [b.as_dict() for b in backup_mod.list_backups()]
    print(json.dumps({"backups": out, "free_bytes": backup_mod.disk_free_bytes(), "total_bytes": backup_mod.disk_total_bytes()}, indent=2))
    return 0


def cmd_backup_create(args) -> int:
    init_db()
    frontend_db = Path(args.frontend_db) if args.frontend_db else None
    out = backup_mod.create_backup_tarball(
        backend_db=Path(settings.db_path),
        crops_dir=Path(settings.crops_dir),
        frontend_db=frontend_db,
        app_version=get_version(),
        out_path=Path(args.out) if args.out else None,
    )
    print(json.dumps({"filename": out.name, "size_bytes": out.stat().st_size}, indent=2))
    return 0


def cmd_backup_inspect(args) -> int:
    info = backup_mod.inspect_backup(args.filename)
    print(json.dumps(info, indent=2))
    return 0


def cmd_backup_delete(args) -> int:
    backup_mod.delete_backup(args.filename)
    print(json.dumps({"deleted": args.filename}))
    return 0


def cmd_backup_restore(args) -> int:
    init_db()
    progress_lines: list[str] = []

    def progress(msg: str) -> None:
        progress_lines.append(msg)
        print(msg, file=sys.stderr)

    try:
        backup_mod.restore_backup(
            args.filename,
            backend_db_dest=Path(settings.db_path),
            crops_dir_dest=Path(settings.crops_dir),
            frontend_db_dest=Path(args.frontend_db) if args.frontend_db else None,
            progress=progress,
        )
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e), "log": progress_lines}, indent=2))
        return 1
    print(json.dumps({"ok": True, "log": progress_lines}, indent=2))
    return 0


def _add_backup_subcommands(p_backup: argparse.ArgumentParser) -> None:
    sub = p_backup.add_subparsers(dest="subcmd", required=True)
    p_list = sub.add_parser("list", help="List existing backups")
    p_list.set_defaults(fn=cmd_backup_list)

    p_create = sub.add_parser("create", help="Create a new backup")
    p_create.add_argument("--out", default=None, help="Override destination path")
    p_create.add_argument("--frontend-db", default=None, help="Optional path to frontend.db to include")
    p_create.set_defaults(fn=cmd_backup_create)

    p_inspect = sub.add_parser("inspect", help="Show manifest + sha256 of a backup")
    p_inspect.add_argument("filename")
    p_inspect.set_defaults(fn=cmd_backup_inspect)

    p_delete = sub.add_parser("delete", help="Delete a backup file")
    p_delete.add_argument("filename")
    p_delete.set_defaults(fn=cmd_backup_delete)

    p_restore = sub.add_parser("restore", help="Restore from a backup (destructive)")
    p_restore.add_argument("filename")
    p_restore.add_argument("--frontend-db", default=None, help="Optional path to frontend.db to restore into")
    p_restore.set_defaults(fn=cmd_backup_restore)


def main(argv: list[str] | None = None) -> int:
    init_db()
    p = argparse.ArgumentParser("mnemos-backend CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_master = sub.add_parser("master-key", help="Master key commands")
    p_master_sub = p_master.add_subparsers(dest="subcmd", required=True)
    p_master_sub.add_parser("view").set_defaults(fn=cmd_master_view)
    p_master_sub.add_parser("rotate").set_defaults(fn=cmd_master_rotate)

    p_h = sub.add_parser("healthz", help="Show the backend's /healthz JSON")
    p_h.add_argument("--base", default=None)
    p_h.set_defaults(fn=cmd_healthz)

    p_backup = sub.add_parser("backup", help="Backup and restore operations")
    _add_backup_subcommands(p_backup)

    args = p.parse_args(argv)
    if args.cmd == "backup":
        return args.fn(args)
    if args.cmd == "master-key":
        return args.fn(args)
    if args.cmd == "healthz":
        return args.fn(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
