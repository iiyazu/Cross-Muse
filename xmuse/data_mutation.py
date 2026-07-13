"""Crash-safe path validation and SQLite mutation leaf primitives.

This module intentionally does not acquire lifecycle/data locks, discover
processes, assert runtime stoppage, install authority files, or run fencing.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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


def vacuum_into(source: Path, destination: Path) -> None:
    """Build a compact copy; caller must prove stopped runtime and lock order."""

    with sqlite3.connect(source, timeout=30) as conn:
        conn.execute("pragma foreign_keys = on")
        conn.execute("pragma wal_checkpoint(truncate)")
        conn.execute("vacuum into ?", (str(destination),))


__all__ = [
    "DataMutationError",
    "DataOperationPaths",
    "operation_directory",
    "safe_operation_paths",
    "vacuum_into",
]
