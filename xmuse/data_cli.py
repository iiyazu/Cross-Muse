#!/usr/bin/env python3
"""Inspect, back up, restore, and compact the local xmuse authority data."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from xmuse import data_compact as _data_compact
from xmuse import data_doctor as _data_doctor
from xmuse import data_restore as _data_restore
from xmuse import data_runtime_guard as _data_runtime_guard
from xmuse.data_backup import backup_data as backup_data
from xmuse.data_backup import verify_backup as verify_backup
from xmuse.data_contracts import (
    BACKUP_MANIFEST_NAME as BACKUP_MANIFEST_NAME,
)
from xmuse.data_contracts import (
    BACKUP_SCHEMA as BACKUP_SCHEMA,
)
from xmuse.data_contracts import (
    CHAT_SCHEMA_CONTRACT as CHAT_SCHEMA_CONTRACT,
)
from xmuse.data_contracts import (
    COMMAND_SCHEMA as COMMAND_SCHEMA,
)
from xmuse.data_contracts import (
    DATA_SCHEMA_VERSION as DATA_SCHEMA_VERSION,
)
from xmuse.data_contracts import (
    DOCTOR_SCHEMA as DOCTOR_SCHEMA,
)
from xmuse.data_contracts import (
    OPERATION_JOURNAL_NAME as OPERATION_JOURNAL_NAME,
)
from xmuse.data_contracts import (
    OPERATION_SCHEMA as OPERATION_SCHEMA,
)
from xmuse.data_contracts import (
    ROOM_SCHEMA_CONTRACT as ROOM_SCHEMA_CONTRACT,
)
from xmuse.data_contracts import (
    SESSION_NAME as SESSION_NAME,
)
from xmuse.data_contracts import (
    DataError as DataError,
)
from xmuse_core.chat.room_database import COMPAT_CHAT_SCHEMA_ID, COMPAT_CHAT_SCHEMA_VERSION
from xmuse_core.chat.room_database import ROOM_SCHEMA_ID as ROOM_SCHEMA_ID
from xmuse_core.chat.room_database import ROOM_SCHEMA_VERSION as ROOM_SCHEMA_VERSION
from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.runtime.root_contract import CHAT_DB_NAME as CHAT_DB_NAME

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XMUSE_ROOT = default_xmuse_root(REPO_ROOT / "xmuse")
CHAT_SCHEMA_ID = COMPAT_CHAT_SCHEMA_ID
CHAT_SCHEMA_VERSION = COMPAT_CHAT_SCHEMA_VERSION


def _runtime_stopped(root: Path) -> None:
    _data_runtime_guard.assert_runtime_stopped(
        root,
        probe=_data_runtime_guard.runtime_probe,
    )


def doctor_data(root: Path) -> tuple[int, dict[str, Any]]:
    """Inspect through the read-only coordinator with the historical signature."""

    return _data_doctor.doctor_data(root)


def restore_data(root: Path, backup: Path, *, replace: bool) -> dict[str, Any]:
    """Restore through the narrow coordinator with a late-bound read guard."""

    return _data_restore.restore_data(
        root,
        backup,
        replace=replace,
        runtime_guard=_runtime_stopped,
    )


def compact_data(root: Path) -> dict[str, Any]:
    """Compact through the narrow coordinator with a late-bound read guard."""

    return _data_compact.compact_data(root, runtime_guard=_runtime_stopped)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="inspect local authority data")
    doctor.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)

    backup = subparsers.add_parser("backup", help="create a verified online backup")
    backup.add_argument("destination", type=Path)
    backup.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)

    restore = subparsers.add_parser("restore", help="restore a verified backup")
    restore.add_argument("backup", type=Path)
    restore.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)
    restore.add_argument("--replace", action="store_true")

    compact = subparsers.add_parser("compact", help="safely compact stopped authority data")
    compact.add_argument("--root", type=Path, default=DEFAULT_XMUSE_ROOT)
    return parser


def _emit(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True), flush=True)


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            exit_code, payload = doctor_data(args.root)
            _emit(payload)
            return exit_code
        if args.command == "backup":
            _emit(backup_data(args.root, args.destination))
            return 0
        if args.command == "restore":
            _emit(restore_data(args.root, args.backup, replace=args.replace))
            return 0
        if args.command == "compact":
            _emit(compact_data(args.root))
            return 0
        raise AssertionError(f"unhandled command: {args.command}")
    except DataError as exc:
        error: dict[str, Any] = {"code": exc.code, "message": str(exc)}
        if exc.details:
            error["details"] = exc.details
        _emit(
            {
                "schema_version": COMMAND_SCHEMA,
                "command": args.command,
                "state": "error",
                "error": error,
            }
        )
        return 1
    except (OSError, sqlite3.Error, ValueError) as exc:
        _emit(
            {
                "schema_version": COMMAND_SCHEMA,
                "command": args.command,
                "state": "error",
                "error": {"code": f"{args.command}_failed", "message": str(exc)},
            }
        )
        return 1


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main())
