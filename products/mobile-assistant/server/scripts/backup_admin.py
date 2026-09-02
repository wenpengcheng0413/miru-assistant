"""Operator CLI for verified Miru backup and staging-only restore."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from miru_server.db.backup import (
    create_verified_backup,
    restore_to_staging,
    verify_backup,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    create = commands.add_parser("create")
    create.add_argument("--database", required=True)
    create.add_argument("--destination", required=True)
    create.add_argument("--attachments")
    create.add_argument("--daily", type=int, default=14)
    create.add_argument("--weekly", type=int, default=8)

    verify = commands.add_parser("verify")
    verify.add_argument("--database", required=True)
    verify.add_argument("--manifest", required=True)
    verify.add_argument("--attachments")

    restore = commands.add_parser("restore")
    restore.add_argument("--database", required=True)
    restore.add_argument("--manifest", required=True)
    restore.add_argument("--staging", required=True)
    restore.add_argument("--attachments")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            result = create_verified_backup(
                args.database,
                args.destination,
                attachment_dir=args.attachments,
                retention_days=args.daily,
                weekly_retention_weeks=args.weekly,
            )
            payload = verify_backup(result.database, result.manifest)
            payload.update({"ok": True, "created": result.created, "weekly": True})
        elif args.command == "verify":
            payload = verify_backup(
                args.database,
                args.manifest,
                attachment_dir=args.attachments,
            )
            payload["ok"] = True
        else:
            payload = restore_to_staging(
                args.database,
                args.manifest,
                args.staging,
                attachment_dir=args.attachments,
            )
            payload["ok"] = True
    except (FileExistsError, FileNotFoundError, RuntimeError, ValueError, OSError):
        print(json.dumps({"ok": False, "error_code": "backup_operation_failed"}), file=sys.stderr)
        return 1
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
