"""SQLite online-backup and artifact verification leaf primitives."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from xmuse.data_inspection import DataInspectionError, readonly_connection, sha256_file


class DataBackupError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def normalize_artifact_database(path: Path) -> None:
    """Publish a self-contained SQLite file with no required WAL sidecars."""

    checkpoint = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        checkpoint.execute("pragma wal_checkpoint(truncate)").fetchall()
    finally:
        checkpoint.close()
    switch = sqlite3.connect(path, timeout=30, isolation_level=None)
    try:
        mode = str(switch.execute("pragma journal_mode = delete").fetchone()[0])
    finally:
        switch.close()
    if mode != "delete":
        raise DataBackupError(
            "backup_schema_unsupported",
            f"could not normalize backup journal mode: {mode}",
        )
    for suffix in ("-wal", "-shm"):
        path.with_name(f"{path.name}{suffix}").unlink(missing_ok=True)


def online_backup(source: Path, destination: Path) -> str:
    """Capture a consistent SQLite snapshot; caller owns the data lock."""

    try:
        with readonly_connection(source) as source_conn:
            source_mode = str(source_conn.execute("pragma journal_mode").fetchone()[0])
            destination_conn = sqlite3.connect(destination, timeout=30)
            try:
                source_conn.backup(destination_conn, pages=256, sleep=0.01)
            finally:
                destination_conn.close()
    except DataInspectionError as exc:
        raise DataBackupError(exc.code, str(exc)) from exc
    return source_mode


def manifest_file(path: Path) -> dict[str, Any]:
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verify_manifest_file(backup: Path, entry: Any, expected_name: str) -> Path:
    if not isinstance(entry, dict) or entry.get("name") != expected_name:
        raise DataBackupError(
            "backup_manifest_invalid", f"invalid backup file entry: {expected_name}"
        )
    path = backup / expected_name
    if not path.is_file() or path.is_symlink():
        raise DataBackupError("backup_manifest_invalid", f"backup file is missing: {expected_name}")
    if entry.get("size_bytes") != path.stat().st_size or entry.get("sha256") != sha256_file(path):
        raise DataBackupError(
            "backup_checksum_mismatch", f"backup checksum mismatch: {expected_name}"
        )
    return path


__all__ = [
    "DataBackupError",
    "manifest_file",
    "normalize_artifact_database",
    "online_backup",
    "verify_manifest_file",
]
