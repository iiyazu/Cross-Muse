"""Fixed filesystem and lock contract for one local xmuse authority root.

This module contains paths and lock acquisition only.  It deliberately owns no
manifest state, child process, timer, or supervisor lifecycle.
"""

from __future__ import annotations

import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from xmuse_core.runtime.paths import resolve_xmuse_root

WORKROOM_MANIFEST_NAME = "workroom-runtime.json"
WORKROOM_LIFECYCLE_LOCK_NAME = ".xmuse-workroom.lifecycle.lock"
DATA_LOCK_NAME = ".xmuse-data.lock"
DATA_OPERATION_JOURNAL_NAME = ".xmuse-data-operation.json"
CHAT_DB_NAME = "chat.db"
GOD_SESSIONS_NAME = "god_sessions.json"


@dataclass(frozen=True)
class RuntimeRootPaths:
    """Canonical paths shared by Workroom and offline data operations."""

    root: Path
    manifest: Path
    lifecycle_lock: Path
    data_lock: Path
    data_operation_journal: Path
    chat_db: Path
    god_sessions: Path
    god_sessions_lock: Path
    room_runner_pid: Path
    room_mcp_pid: Path
    room_runner_status: Path
    memoryos_status: Path
    memoryos_derived: Path

    @classmethod
    def resolve(
        cls,
        value: str | Path | None,
        *,
        fallback: str | Path,
    ) -> RuntimeRootPaths:
        root = resolve_xmuse_root(value, fallback=fallback)
        sessions = root / GOD_SESSIONS_NAME
        return cls(
            root=root,
            manifest=root / WORKROOM_MANIFEST_NAME,
            lifecycle_lock=root / WORKROOM_LIFECYCLE_LOCK_NAME,
            data_lock=root / DATA_LOCK_NAME,
            data_operation_journal=root / DATA_OPERATION_JOURNAL_NAME,
            chat_db=root / CHAT_DB_NAME,
            god_sessions=sessions,
            god_sessions_lock=sessions.with_name(f"{sessions.name}.lock"),
            room_runner_pid=root / "workroom_room_runner.pid.json",
            room_mcp_pid=root / "workroom_room_mcp.pid.json",
            room_runner_status=root / "room-runner-status.json",
            memoryos_status=root / "memoryos-status.json",
            memoryos_derived=root / "runtime" / "memoryos-derived",
        )


@contextmanager
def file_lock(path: Path, *, exclusive: bool = True) -> Iterator[None]:
    """Acquire one fixed advisory file lock without imposing lifecycle policy."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


__all__ = [
    "CHAT_DB_NAME",
    "DATA_LOCK_NAME",
    "DATA_OPERATION_JOURNAL_NAME",
    "GOD_SESSIONS_NAME",
    "RuntimeRootPaths",
    "WORKROOM_LIFECYCLE_LOCK_NAME",
    "WORKROOM_MANIFEST_NAME",
    "file_lock",
]
