"""Crash-safe restore orchestration for offline xmuse authority data."""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypeVar

from xmuse.data_authority import (
    inspect_database,
    sanitize_sessions,
    validate_session_references,
    validate_sessions,
)
from xmuse.data_backup import verify_backup, verify_staged_database_copy
from xmuse.data_contracts import COMMAND_SCHEMA, SESSION_NAME, DataError
from xmuse.data_mutation import (
    DataMutationError,
    finish_operation,
    move_old_targets,
    new_operation,
    operation_journal,
    recover_existing_operation,
    rollback_operation,
    update_operation,
)
from xmuse.data_runtime_guard import assert_runtime_stopped
from xmuse.workroom_contracts import WorkroomPaths
from xmuse_core.chat.memoryos_supervisor import (
    MemoryOSSupervisorError,
    clear_memoryos_derived_cache,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_memory_rebuild_store import reset_room_memory_index_conn
from xmuse_core.runtime.root_contract import CHAT_DB_NAME, DATA_LOCK_NAME, file_lock

REPO_ROOT = Path(__file__).resolve().parents[1]
RuntimeStopGuard = Callable[[Path], None]
_T = TypeVar("_T")


def fence_restored_execution_runs(path: Path, *, operation_id: str) -> dict[str, int]:
    """Fence process-local Harness work without replaying a restored action."""

    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        tables = {
            str(row[0])
            for row in connection.execute("select name from sqlite_schema where type = 'table'")
        }
        if "room_execution_runs" not in tables:
            return {"blocked": 0, "promotion_unverifiable": 0}
        stamp = _utc_now()
        rows = connection.execute(
            """select r.run_id, r.authorization_id, r.state,
                      coalesce(j.status, '') journal_status
               from room_execution_runs r
               left join room_execution_promotion_journal j on j.run_id = r.run_id
               where r.state not in ('cancelled','succeeded','failed','blocked')"""
        ).fetchall()
        promotion_unverifiable = 0
        connection.execute("begin immediate")
        for row in rows:
            promotion = row["state"] == "promoting" or row["journal_status"] in {
                "applying",
                "applied",
                "ambiguous",
            }
            reason = (
                "room_execution_promotion_unverifiable"
                if promotion
                else "room_execution_restore_reauthorization_required"
            )
            promotion_unverifiable += int(promotion)
            connection.execute(
                """update room_execution_runs
                   set state = 'blocked', revision = revision + 1, reason_code = ?,
                       controller_id = null, controller_generation = null,
                       controller_pid = null, controller_start_identity = null,
                       finished_at = coalesce(finished_at, ?), updated_at = ?
                   where run_id = ?""",
                (reason, stamp, stamp, row["run_id"]),
            )
            connection.execute(
                """update room_execution_authorizations
                   set status = 'invalidated', reason_code = ?, invalidated_at = ?
                   where authorization_id = ?""",
                (reason, stamp, row["authorization_id"]),
            )
        connection.commit()
        return {
            "blocked": len(rows),
            "promotion_unverifiable": promotion_unverifiable,
        }
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise DataError(
            "restore_execution_fence_failed",
            f"could not fence restored execution runs for {operation_id}",
        ) from exc
    finally:
        connection.close()


def fence_restored_memory_index(path: Path, *, operation_id: str) -> dict[str, int]:
    """Reset only derived MemoryOS bindings and reopen rebuildable delivery."""

    connection = sqlite3.connect(path)
    try:
        connection.row_factory = sqlite3.Row
        connection.execute("pragma foreign_keys = on")
        tables = {
            str(row[0])
            for row in connection.execute("select name from sqlite_schema where type = 'table'")
        }
        connection.execute("begin immediate")
        result = reset_room_memory_index_conn(
            connection,
            reason_code="room_memory_restore_rebuild_required",
            stamp=_utc_now(),
        )
        actions_fenced = 0
        if "room_memory_rebuild_actions" in tables:
            stamp = _utc_now()
            actions_fenced = connection.execute(
                """update room_memory_rebuild_actions
                   set status = 'failed', phase = 'complete', revision = revision + 1,
                       after_state = 'stopped',
                       after_code = 'room_memory_restore_action_not_replayed',
                       reason_code = 'room_memory_restore_action_not_replayed',
                       applied_at = ?, updated_at = ?
                   where status = 'requested'""",
                (stamp, stamp),
            ).rowcount
        connection.commit()
        return {**result, "actions_fenced": int(actions_fenced)}
    except sqlite3.Error as exc:
        if connection.in_transaction:
            connection.rollback()
        raise DataError(
            "restore_memory_fence_failed",
            f"could not fence restored MemoryOS state for {operation_id}",
        ) from exc
    finally:
        connection.close()


def clear_derived_memory_cache(root: Path) -> bool:
    """Remove only the fixed rebuildable MemoryOS directory."""

    try:
        return clear_memoryos_derived_cache(root)
    except MemoryOSSupervisorError as exc:
        code = (
            "restore_memory_cache_unsafe"
            if exc.code == "memoryos_derived_cache_unsafe"
            else "restore_memory_cache_clear_failed"
        )
        raise DataError(code, "could not clear the rebuildable MemoryOS cache") from exc


def commit_restore(
    root: Path,
    payload: dict[str, Any],
    staging: Path,
    rollback: Path,
) -> None:
    """Install staged authority with an explicit transport-fenced phase."""

    try:
        _translate_mutation(lambda: move_old_targets(root, payload, rollback))
        empty = staging / ".empty-god-sessions.json"
        _write_json(empty, {"sessions": []})
        os.replace(empty, root / SESSION_NAME)
        _fsync_dir(root)
        _translate_mutation(lambda: update_operation(root, payload, "transport_fenced"))
        os.replace(staging / CHAT_DB_NAME, root / CHAT_DB_NAME)
        os.replace(staging / SESSION_NAME, root / SESSION_NAME)
        _fsync_dir(root)
        _translate_mutation(lambda: update_operation(root, payload, "installed"))
        inspect_database(root / CHAT_DB_NAME, require_current=True)
        installed_sessions = _read_json(
            root / SESSION_NAME,
            code="restore_validation_failed",
        )
        records = validate_sessions(installed_sessions)
        validate_session_references(root / CHAT_DB_NAME, records)
        _translate_mutation(lambda: update_operation(root, payload, "committed"))
        _translate_mutation(lambda: finish_operation(root, payload))
    except Exception as exc:
        try:
            current = _read_json(
                operation_journal(root),
                code="data_operation_incomplete",
            )
            _translate_mutation(lambda: rollback_operation(root, current))
        except Exception as rollback_error:
            if isinstance(exc, DataError):
                exc.add_note(f"restore rollback failed: {rollback_error}")
            raise DataError(
                "data_operation_incomplete",
                "restore failed and automatic rollback was incomplete",
            ) from rollback_error
        if isinstance(exc, DataError):
            raise
        raise DataError("restore_commit_failed", "restore commit failed") from exc


def restore_data(
    root: Path,
    backup: Path,
    *,
    replace: bool,
    runtime_guard: RuntimeStopGuard = assert_runtime_stopped,
) -> dict[str, Any]:
    """Restore verified authority while preserving every offline safety fence."""

    manifest, backup_db, _session_payload, records = verify_backup(backup)
    runtime_root = root.expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    paths = WorkroomPaths.resolve(runtime_root, REPO_ROOT)
    with file_lock(paths.lock):
        with file_lock(runtime_root / DATA_LOCK_NAME):
            runtime_guard(runtime_root)
            recovered_operation = _translate_mutation(
                lambda: recover_existing_operation(runtime_root)
            )
            runtime_guard(runtime_root)
            occupied = any(
                (runtime_root / name).exists()
                for name in (
                    CHAT_DB_NAME,
                    SESSION_NAME,
                    f"{CHAT_DB_NAME}-wal",
                    f"{CHAT_DB_NAME}-shm",
                )
            )
            if occupied and not replace:
                raise DataError(
                    "restore_target_exists",
                    "restore target contains authority data; pass --replace",
                )
            payload, staging, rollback = _translate_mutation(
                lambda: new_operation(
                    runtime_root,
                    kind="restore",
                    install_names=(CHAT_DB_NAME, SESSION_NAME),
                )
            )
            try:
                shutil.copy2(backup_db, staging / CHAT_DB_NAME)
                verify_staged_database_copy(staging / CHAT_DB_NAME, manifest)
                sanitized = sanitize_sessions(records)
                _write_json(staging / SESSION_NAME, sanitized)
                validate_sessions(sanitized)
                validate_session_references(staging / CHAT_DB_NAME, records)
                fence = RoomObservationControlStore(
                    staging / CHAT_DB_NAME,
                    initialize=False,
                ).fence_restored_runtime_generation(
                    operation_id=str(payload["operation_id"]),
                )
                execution_fence = fence_restored_execution_runs(
                    staging / CHAT_DB_NAME,
                    operation_id=str(payload["operation_id"]),
                )
                memory_index_fence = fence_restored_memory_index(
                    staging / CHAT_DB_NAME,
                    operation_id=str(payload["operation_id"]),
                )
                inspect_database(staging / CHAT_DB_NAME, require_current=True)
                _fsync_file(staging / CHAT_DB_NAME)
                _fsync_file(staging / SESSION_NAME)
                _fsync_dir(staging)
                memory_cache_cleared = clear_derived_memory_cache(runtime_root)
                with file_lock(
                    runtime_root / f"{SESSION_NAME}.lock",
                    exclusive=True,
                ):
                    commit_restore(runtime_root, payload, staging, rollback)
            except Exception:
                if operation_journal(runtime_root).exists():
                    current = _read_json(
                        operation_journal(runtime_root),
                        code="data_operation_incomplete",
                    )
                    _translate_mutation(lambda: rollback_operation(runtime_root, current))
                raise
    return {
        "schema_version": COMMAND_SCHEMA,
        "command": "restore",
        "state": "succeeded",
        "root": str(runtime_root),
        "backup_id": manifest["backup_id"],
        "operation_id": payload["operation_id"],
        "recovered_operation_id": recovered_operation,
        "runtime_fence": fence,
        "execution_fence": execution_fence,
        "memory_index_fence": memory_index_fence,
        "memory_cache_cleared": memory_cache_cleared,
        "session_count": len(records),
    }


def _translate_mutation(operation: Callable[[], _T]) -> _T:
    try:
        return operation()
    except DataMutationError as exc:
        raise DataError(exc.code, str(exc)) from exc


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
    "RuntimeStopGuard",
    "clear_derived_memory_cache",
    "commit_restore",
    "fence_restored_execution_runs",
    "fence_restored_memory_index",
    "restore_data",
]
