"""SQLite online-backup and artifact verification leaf primitives."""

from __future__ import annotations

import importlib.metadata
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from xmuse.data_authority import (
    database_evidence,
    inspect_database,
    read_sessions,
    validate_session_references,
    validate_sessions,
)
from xmuse.data_contracts import (
    BACKUP_MANIFEST_NAME,
    BACKUP_SCHEMA,
    COMMAND_SCHEMA,
    DATA_SCHEMA_VERSION,
    OPERATION_JOURNAL_NAME,
    SESSION_NAME,
    DataError,
)
from xmuse.data_inspection import DataInspectionError, readonly_connection, sha256_file
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.runtime.root_contract import CHAT_DB_NAME, DATA_LOCK_NAME, file_lock

_T = TypeVar("_T")


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


def backup_data(root: Path, destination: Path) -> dict[str, Any]:
    """Publish one verified online backup without stopping the Workroom."""

    runtime_root = root.expanduser().resolve()
    expanded_destination = destination.expanduser()
    final = expanded_destination.resolve()
    if expanded_destination.is_symlink() or final.exists():
        raise DataError("backup_destination_exists", f"backup destination exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(runtime_root / DATA_LOCK_NAME):
        if (runtime_root / OPERATION_JOURNAL_NAME).exists():
            raise DataError(
                "data_operation_incomplete",
                "recover the interrupted data operation before creating a backup",
            )
        source = runtime_root / CHAT_DB_NAME
        source_inspection = inspect_database(source, require_current=True)
        backup_id = f"backup-{uuid.uuid4().hex}"
        staging = Path(tempfile.mkdtemp(prefix=f".{final.name}.{backup_id}.", dir=final.parent))
        published = False
        try:
            db_started = _utc_now()
            source_mode = _translate_backup_error(
                lambda: online_backup(source, staging / CHAT_DB_NAME)
            )
            db_completed = _utc_now()
            _translate_backup_error(lambda: normalize_artifact_database(staging / CHAT_DB_NAME))
            inspect_database(staging / CHAT_DB_NAME, require_current=True)
            session_payload, session_records, source_sessions_present = read_sessions(runtime_root)
            validate_session_references(staging / CHAT_DB_NAME, session_records)
            _write_json(staging / SESSION_NAME, session_payload)
            manifest = _backup_manifest(
                staging=staging,
                backup_id=backup_id,
                created_at=db_completed,
                capture={
                    "db_started_at": db_started,
                    "db_completed_at": db_completed,
                    "sessions_captured_at": _utc_now(),
                },
                source_mode=str(source_mode),
                source_sessions_present=source_sessions_present,
                session_count=len(session_records),
            )
            _write_json(staging / BACKUP_MANIFEST_NAME, manifest)
            for name in (CHAT_DB_NAME, SESSION_NAME, BACKUP_MANIFEST_NAME):
                _fsync_file(staging / name)
            _fsync_dir(staging)
            os.replace(staging, final)
            _fsync_dir(final.parent)
            published = True
        finally:
            if not published:
                shutil.rmtree(staging, ignore_errors=True)
    return {
        "schema_version": COMMAND_SCHEMA,
        "command": "backup",
        "state": "succeeded",
        "backup": str(final),
        "backup_id": manifest["backup_id"],
        "rooms": len(manifest["rooms"]),
        "source_journal_mode": source_inspection["journal_mode"],
    }


def verify_backup(
    backup: Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], list[GodSessionRecord]]:
    """Verify the complete immutable backup contract and authority evidence."""

    expanded = backup.expanduser()
    # Check the path supplied by the operator before resolve() erases the
    # symlink boundary.  Files inside the directory are checked separately.
    if expanded.is_symlink():
        raise DataError("backup_manifest_invalid", f"backup directory is invalid: {expanded}")
    location = expanded.resolve()
    if not location.is_dir():
        raise DataError("backup_manifest_invalid", f"backup directory is invalid: {location}")
    try:
        entries = {item.name for item in location.iterdir()}
    except OSError as exc:
        raise DataError("backup_manifest_invalid", "backup directory is unreadable") from exc
    expected_entries = {BACKUP_MANIFEST_NAME, CHAT_DB_NAME, SESSION_NAME}
    if entries != expected_entries:
        raise DataError(
            "backup_manifest_invalid",
            "backup directory contains missing or unexpected artifacts",
            entries=sorted(entries),
        )
    manifest = _read_json(location / BACKUP_MANIFEST_NAME, code="backup_manifest_invalid")
    if (
        manifest.get("schema_version") != BACKUP_SCHEMA
        or manifest.get("data_schema_version") != DATA_SCHEMA_VERSION
    ):
        raise DataError("backup_schema_unsupported", "backup schema is not supported")
    if not isinstance(manifest.get("backup_id"), str) or not manifest["backup_id"]:
        raise DataError("backup_manifest_invalid", "backup_id is invalid")
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise DataError("backup_manifest_invalid", "backup files are invalid")
    chat_path = _verified_manifest_file(location, files.get("chat_db"), CHAT_DB_NAME)
    sessions_path = _verified_manifest_file(location, files.get("god_sessions"), SESSION_NAME)
    inspection = inspect_database(chat_path, require_current=True)
    schema = inspection["schema"]
    evidence = database_evidence(chat_path)
    database = manifest.get("database")
    if (
        not isinstance(database, dict)
        or database.get("schema_contract") != schema["schema_contract"]
        or database.get("schema_contract_version") != schema["schema_contract_version"]
        or database.get("schema_fingerprint_sha256") != evidence["schema_fingerprint_sha256"]
        or manifest.get("rooms_sha256") != evidence["rooms_sha256"]
        or manifest.get("rooms") != evidence["rooms"]
        or manifest.get("totals") != evidence["totals"]
    ):
        raise DataError("backup_manifest_invalid", "backup evidence does not match manifest")
    sessions_payload = _read_json(sessions_path, code="session_registry_invalid")
    records = validate_sessions(sessions_payload)
    session_entry = files.get("god_sessions")
    if not isinstance(session_entry, dict) or session_entry.get("session_count") != len(records):
        raise DataError("backup_manifest_invalid", "backup session count does not match")
    validate_session_references(chat_path, records)
    return manifest, chat_path, sessions_payload, records


def verify_staged_database_copy(path: Path, manifest: Mapping[str, Any]) -> None:
    """Re-prove copied bytes before any restore fencing mutation."""

    files = manifest.get("files")
    entry = files.get("chat_db") if isinstance(files, dict) else None
    if (
        not isinstance(entry, dict)
        or entry.get("size_bytes") != path.stat().st_size
        or entry.get("sha256") != sha256_file(path)
    ):
        raise DataError(
            "backup_checksum_mismatch",
            "staged chat.db no longer matches the verified backup",
        )
    inspect_database(path, require_current=True)
    evidence = database_evidence(path)
    database = manifest.get("database")
    if (
        not isinstance(database, dict)
        or database.get("schema_fingerprint_sha256") != evidence["schema_fingerprint_sha256"]
        or manifest.get("rooms_sha256") != evidence["rooms_sha256"]
        or manifest.get("rooms") != evidence["rooms"]
        or manifest.get("totals") != evidence["totals"]
    ):
        raise DataError(
            "backup_manifest_invalid",
            "staged chat.db evidence no longer matches the verified backup",
        )


def _backup_manifest(
    *,
    staging: Path,
    backup_id: str,
    created_at: str,
    capture: dict[str, str],
    source_mode: str,
    source_sessions_present: bool,
    session_count: int,
) -> dict[str, Any]:
    chat_path = staging / CHAT_DB_NAME
    sessions_path = staging / SESSION_NAME
    inspection = inspect_database(chat_path, require_current=True)
    evidence = database_evidence(chat_path)
    return {
        "schema_version": BACKUP_SCHEMA,
        "data_schema_version": DATA_SCHEMA_VERSION,
        "backup_id": backup_id,
        "created_at": created_at,
        "xmuse_version": _package_version(),
        "files": {
            "chat_db": manifest_file(chat_path),
            "god_sessions": manifest_file(sessions_path)
            | {
                "schema": "xmuse.god_sessions/v1",
                "session_count": session_count,
                "source_present": source_sessions_present,
            },
        },
        "database": {
            "schema_contract": inspection["schema"]["schema_contract"],
            "schema_contract_version": inspection["schema"]["schema_contract_version"],
            "schema_fingerprint_sha256": evidence["schema_fingerprint_sha256"],
            "schema_migrations": inspection["migrations"],
            "sqlite_version": sqlite3.sqlite_version,
            "source_journal_mode": source_mode,
            "artifact_page_size": inspection["page_size"],
            "artifact_page_count": inspection["page_count"],
            "integrity": inspection["integrity"],
        },
        "capture": capture,
        "rooms": evidence["rooms"],
        "rooms_sha256": evidence["rooms_sha256"],
        "totals": evidence["totals"],
        "proof_boundary": (
            "chat.db is the durable authority; god_sessions.json is a separately captured "
            "transport binding snapshot and is fenced on restore; the derived MemoryOS "
            "index is excluded and rebuilt from chat.db"
        ),
    }


def _verified_manifest_file(backup: Path, entry: Any, expected_name: str) -> Path:
    try:
        return verify_manifest_file(backup, entry, expected_name)
    except DataBackupError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _translate_backup_error(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except DataBackupError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _package_version() -> str:
    try:
        return importlib.metadata.version("xmuse")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw_temp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp = Path(raw_temp)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
        _fsync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def _read_json(path: Path, *, code: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataError(code, f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise DataError(code, f"JSON root must be an object: {path}")
    return payload


__all__ = [
    "DataBackupError",
    "backup_data",
    "manifest_file",
    "normalize_artifact_database",
    "online_backup",
    "verify_backup",
    "verify_manifest_file",
    "verify_staged_database_copy",
]
