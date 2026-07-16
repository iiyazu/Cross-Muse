"""Crash-safe compact orchestration for stopped xmuse authority data."""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from xmuse.data_authority import database_evidence, inspect_database
from xmuse.data_backup import (
    DataBackupError,
    normalize_artifact_database,
)
from xmuse.data_contracts import COMMAND_SCHEMA, DataError
from xmuse.data_inspection import (
    DataInspectionError,
    table_order_fingerprints,
)
from xmuse.data_mutation import (
    DataMutationError,
    finish_operation,
    move_old_targets,
    new_operation,
    operation_journal,
    read_operation,
    recover_existing_operation,
    rollback_operation,
    update_operation,
    vacuum_into,
)
from xmuse.data_runtime_guard import assert_runtime_stopped
from xmuse_core.runtime.root_contract import CHAT_DB_NAME, RuntimeRootPaths, file_lock


class DatabaseInspector(Protocol):
    def __call__(self, path: Path, *, require_current: bool) -> dict[str, Any]: ...


DatabaseEvidence = Callable[[Path], dict[str, Any]]
TableFingerprints = Callable[[Path], dict[str, str]]
RuntimeStoppedGuard = Callable[[Path], None]


def compact_data(
    root: Path,
    *,
    runtime_guard: RuntimeStoppedGuard = assert_runtime_stopped,
    database_inspector: DatabaseInspector = inspect_database,
    evidence_reader: DatabaseEvidence = database_evidence,
    fingerprint_reader: TableFingerprints = table_order_fingerprints,
) -> dict[str, Any]:
    """Compact one stopped authority database without changing logical facts."""

    runtime_root = root.expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    paths = RuntimeRootPaths.resolve(runtime_root, fallback=runtime_root)
    with file_lock(paths.lifecycle_lock):
        with file_lock(paths.data_lock):
            runtime_guard(runtime_root)
            recovered_operation = _recover_operation(runtime_root)
            runtime_guard(runtime_root)
            source = paths.chat_db
            database_inspector(source, require_current=True)
            before_size = source.stat().st_size
            before_evidence = evidence_reader(source)
            before_order = _fingerprints(source, fingerprint_reader)
            payload, staging, rollback = _new_compact_operation(runtime_root)
            try:
                compacted = staging / CHAT_DB_NAME
                _vacuum(source, compacted)
                _normalize_database(compacted)
                database_inspector(compacted, require_current=True)
                after_evidence = evidence_reader(compacted)
                after_order = _fingerprints(compacted, fingerprint_reader)
                if before_evidence != after_evidence or before_order != after_order:
                    raise DataError(
                        "compact_failed",
                        "compacted database changed authority content or row order",
                    )
                _fsync_file(compacted)
                _fsync_dir(staging)
                after_size = compacted.stat().st_size
                _commit_compact(
                    runtime_root,
                    payload,
                    staging,
                    rollback,
                    database_inspector=database_inspector,
                )
            except Exception:
                if operation_journal(runtime_root).exists():
                    _rollback(runtime_root, _read_durable_operation(runtime_root))
                raise
    return {
        "schema_version": COMMAND_SCHEMA,
        "command": "compact",
        "state": "succeeded",
        "root": str(runtime_root),
        "operation_id": payload["operation_id"],
        "recovered_operation_id": recovered_operation,
        "before_size_bytes": before_size,
        "after_size_bytes": after_size,
        "reclaimed_bytes": max(0, before_size - after_size),
    }


def _commit_compact(
    root: Path,
    payload: dict[str, Any],
    staging: Path,
    rollback: Path,
    *,
    database_inspector: DatabaseInspector,
) -> None:
    try:
        move_old_targets(root, payload, rollback)
        os.replace(staging / CHAT_DB_NAME, root / CHAT_DB_NAME)
        _fsync_dir(root)
        update_operation(root, payload, "installed")
        database_inspector(root / CHAT_DB_NAME, require_current=True)
        update_operation(root, payload, "committed")
        finish_operation(root, payload)
    except Exception as exc:
        try:
            _rollback(root, _read_durable_operation(root))
        except Exception as rollback_error:
            raise DataError(
                "data_operation_incomplete",
                "compact failed and automatic rollback was incomplete",
            ) from rollback_error
        if isinstance(exc, DataError):
            raise
        if isinstance(exc, DataMutationError):
            raise DataError(exc.code, str(exc)) from exc
        raise DataError("compact_failed", "compact commit failed") from exc


def _new_compact_operation(root: Path) -> tuple[dict[str, Any], Path, Path]:
    try:
        return new_operation(root, kind="compact", install_names=(CHAT_DB_NAME,))
    except DataMutationError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _recover_operation(root: Path) -> str | None:
    try:
        return recover_existing_operation(root)
    except DataMutationError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _rollback(root: Path, payload: dict[str, Any]) -> None:
    try:
        rollback_operation(root, payload)
    except DataMutationError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _read_durable_operation(root: Path) -> dict[str, Any]:
    try:
        return read_operation(root)
    except DataMutationError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _vacuum(source: Path, destination: Path) -> None:
    try:
        vacuum_into(source, destination)
    except (DataMutationError, OSError) as exc:
        code = exc.code if isinstance(exc, DataMutationError) else "compact_failed"
        raise DataError(code, str(exc)) from exc


def _normalize_database(path: Path) -> None:
    try:
        normalize_artifact_database(path)
    except DataBackupError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _fingerprints(path: Path, reader: TableFingerprints) -> dict[str, str]:
    try:
        return reader(path)
    except DataInspectionError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _fsync_file(path: Path) -> None:
    with path.open("rb") as handle:
        os.fsync(handle.fileno())


def _fsync_dir(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = [
    "DatabaseEvidence",
    "DatabaseInspector",
    "RuntimeStoppedGuard",
    "TableFingerprints",
    "compact_data",
]
