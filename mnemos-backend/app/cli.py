from __future__ import annotations

import argparse
import json
import sys
import urllib.request

from app.core.config import settings
from app.core.security import rotate_master_key, view_master_key
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

    args = p.parse_args(argv)
    if args.cmd == "master-key":
        return args.fn(args)
    if args.cmd == "healthz":
        return args.fn(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
