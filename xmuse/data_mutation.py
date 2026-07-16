"""Crash-safe path validation and SQLite mutation leaf primitives.

This module intentionally does not acquire lifecycle/data locks, discover
processes, assert runtime stoppage, install authority files, or run fencing.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse.data_contracts import OPERATION_SCHEMA
from xmuse_core.runtime.root_contract import (
    CHAT_DB_NAME,
    DATA_OPERATION_JOURNAL_NAME,
    GOD_SESSIONS_NAME,
)

_JOURNAL_PHASES = frozenset(
    {
        "prepared",
        "moving_old",
        "old_moved",
        "transport_fenced",
        "installed",
        "committed",
    }
)


class DataMutationError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class DataOperationPaths:
    staging: Path
    rollback: Path


def operation_directory(root: Path, prefix: str, operation_id: str) -> Path:
    return root / f".{prefix}-{operation_id}"


def safe_operation_paths(
    root: Path,
    payload: dict[str, Any],
    *,
    expected_schema: str,
) -> DataOperationPaths:
    """Validate journal-controlled paths without trusting serialized paths."""

    if payload.get("schema_version") != expected_schema:
        raise DataMutationError("data_operation_incomplete", "data operation journal is invalid")
    operation_id = payload.get("operation_id")
    if (
        not isinstance(operation_id, str)
        or re.fullmatch(r"(?:restore|compact)-[0-9a-f]{32}", operation_id) is None
    ):
        raise DataMutationError("data_operation_incomplete", "data operation ID is invalid")
    staging = operation_directory(root, "xmuse-data-stage", operation_id)
    rollback = operation_directory(root, "xmuse-data-rollback", operation_id)
    if payload.get("staging_dir") != staging.name or payload.get("rollback_dir") != rollback.name:
        raise DataMutationError("data_operation_incomplete", "data operation paths are invalid")
    for path in (staging, rollback):
        if path.exists() and (path.is_symlink() or not path.is_dir()):
            raise DataMutationError("data_operation_incomplete", "unsafe data operation directory")
    return DataOperationPaths(staging=staging, rollback=rollback)


def operation_journal(root: Path) -> Path:
    return root / DATA_OPERATION_JOURNAL_NAME


def read_operation(root: Path) -> dict[str, Any]:
    """Read the durable journal snapshot used to decide crash recovery."""

    return _read_json(operation_journal(root))


def new_operation(
    root: Path,
    *,
    kind: str,
    install_names: Sequence[str],
) -> tuple[dict[str, Any], Path, Path]:
    """Create one frozen restore/compact journal and its private directories."""

    if kind not in {"restore", "compact"}:
        raise DataMutationError("data_operation_incomplete", "data operation kind is invalid")
    operation_id = f"{kind}-{uuid.uuid4().hex}"
    staging = operation_directory(root, "xmuse-data-stage", operation_id)
    rollback = operation_directory(root, "xmuse-data-rollback", operation_id)
    staging.mkdir()
    rollback.mkdir()
    target_names = list(
        dict.fromkeys([*install_names, f"{CHAT_DB_NAME}-wal", f"{CHAT_DB_NAME}-shm"])
    )
    allowed_names = {
        CHAT_DB_NAME,
        GOD_SESSIONS_NAME,
        f"{CHAT_DB_NAME}-wal",
        f"{CHAT_DB_NAME}-shm",
    }
    if any(name not in allowed_names for name in target_names):
        raise DataMutationError("data_operation_incomplete", "unsafe data operation target")
    stamp = _utc_now()
    payload: dict[str, Any] = {
        "schema_version": OPERATION_SCHEMA,
        "operation_id": operation_id,
        "kind": kind,
        "phase": "prepared",
        "staging_dir": staging.name,
        "rollback_dir": rollback.name,
        "targets": [
            {"name": name, "had_original": (root / name).exists()} for name in target_names
        ],
        "created_at": stamp,
        "updated_at": stamp,
    }
    _write_json(operation_journal(root), payload)
    return payload, staging, rollback


def update_operation(root: Path, payload: dict[str, Any], phase: str) -> None:
    """Durably advance only within the frozen journal state vocabulary."""

    if phase not in _JOURNAL_PHASES:
        raise DataMutationError(
            "data_operation_incomplete", f"unknown data operation phase: {phase}"
        )
    safe_operation_paths(root, payload, expected_schema=OPERATION_SCHEMA)
    payload["phase"] = phase
    payload["updated_at"] = _utc_now()
    _write_json(operation_journal(root), payload)


def move_old_targets(root: Path, payload: dict[str, Any], rollback: Path) -> None:
    """Move all old authority targets under journal control before installation."""

    paths = safe_operation_paths(root, payload, expected_schema=OPERATION_SCHEMA)
    if paths.rollback != rollback:
        raise DataMutationError("data_operation_incomplete", "data rollback path is invalid")
    update_operation(root, payload, "moving_old")
    targets = _validated_targets(payload)
    for target_record in targets:
        name = str(target_record["name"])
        target = root / name
        if target.exists():
            os.replace(target, rollback / name)
    _fsync_dir(root)
    _fsync_dir(rollback)
    update_operation(root, payload, "old_moved")


def finish_operation(root: Path, payload: dict[str, Any]) -> None:
    paths = safe_operation_paths(root, payload, expected_schema=OPERATION_SCHEMA)
    shutil.rmtree(paths.staging, ignore_errors=True)
    shutil.rmtree(paths.rollback, ignore_errors=True)
    operation_journal(root).unlink(missing_ok=True)
    _fsync_dir(root)


def rollback_operation(root: Path, payload: dict[str, Any]) -> None:
    """Recover all-or-nothing authority bytes from any frozen pre-commit phase."""

    paths = safe_operation_paths(root, payload, expected_schema=OPERATION_SCHEMA)
    phase = str(payload.get("phase") or "")
    if phase == "committed":
        finish_operation(root, payload)
        return
    if phase not in _JOURNAL_PHASES - {"committed"}:
        raise DataMutationError(
            "data_operation_incomplete", f"unknown data operation phase: {phase}"
        )
    if phase != "prepared":
        for target_record in _validated_targets(payload):
            name = str(target_record["name"])
            target = root / name
            prior = paths.rollback / name
            had_original = target_record.get("had_original") is True
            if prior.exists():
                _remove_path(target)
                os.replace(prior, target)
            elif not had_original:
                _remove_path(target)
            elif phase in {"old_moved", "transport_fenced", "installed"}:
                raise DataMutationError(
                    "data_operation_incomplete",
                    f"rollback artifact is missing for {name}",
                )
    finish_operation(root, payload)


def recover_existing_operation(root: Path) -> str | None:
    journal = operation_journal(root)
    if not journal.exists():
        return None
    payload = _read_json(journal)
    operation_id = str(payload.get("operation_id") or "")
    rollback_operation(root, payload)
    return operation_id


def vacuum_into(source: Path, destination: Path) -> None:
    """Build a compact copy; caller must prove stopped runtime and lock order."""

    with sqlite3.connect(source, timeout=30) as conn:
        conn.execute("pragma foreign_keys = on")
        conn.execute("pragma wal_checkpoint(truncate)")
        conn.execute("vacuum into ?", (str(destination),))


def _validated_targets(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    targets = payload.get("targets")
    if not isinstance(targets, list):
        raise DataMutationError("data_operation_incomplete", "data operation targets are invalid")
    allowed_names = {
        CHAT_DB_NAME,
        GOD_SESSIONS_NAME,
        f"{CHAT_DB_NAME}-wal",
        f"{CHAT_DB_NAME}-shm",
    }
    validated: list[dict[str, Any]] = []
    for target_record in targets:
        if not isinstance(target_record, dict):
            raise DataMutationError("data_operation_incomplete", "data operation target is invalid")
        name = target_record.get("name")
        if name not in allowed_names:
            raise DataMutationError("data_operation_incomplete", "unsafe data operation target")
        validated.append(target_record)
    return validated


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DataMutationError("data_operation_incomplete", f"invalid JSON file: {path}") from exc
    if not isinstance(payload, dict):
        raise DataMutationError("data_operation_incomplete", f"JSON root must be an object: {path}")
    return payload


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


__all__ = [
    "DataMutationError",
    "DataOperationPaths",
    "OPERATION_SCHEMA",
    "finish_operation",
    "move_old_targets",
    "new_operation",
    "operation_directory",
    "operation_journal",
    "read_operation",
    "recover_existing_operation",
    "rollback_operation",
    "safe_operation_paths",
    "update_operation",
    "vacuum_into",
]
