"""Read-only doctor projection for local xmuse data authority."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Protocol

from xmuse.data_authority import (
    inspect_database,
    read_sessions,
    validate_session_references,
)
from xmuse.data_contracts import DOCTOR_SCHEMA, OPERATION_JOURNAL_NAME, DataError
from xmuse.data_inspection import DataInspectionError, readonly_connection
from xmuse.data_runtime_guard import RuntimeProbe, assert_runtime_stopped, runtime_probe
from xmuse.workroom_contracts import WorkroomError
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.runtime.root_contract import CHAT_DB_NAME


class DatabaseInspector(Protocol):
    def __call__(self, path: Path, *, require_current: bool) -> dict[str, Any]: ...


class SessionReader(Protocol):
    def __call__(
        self, root: Path, *, lock: bool = True
    ) -> tuple[dict[str, Any], list[GodSessionRecord], bool]: ...


SessionReferenceValidator = Callable[[Path, Sequence[GodSessionRecord]], None]


def doctor_data(
    root: Path,
    *,
    database_inspector: DatabaseInspector = inspect_database,
    session_reader: SessionReader = read_sessions,
    session_reference_validator: SessionReferenceValidator = validate_session_references,
    probe: RuntimeProbe = runtime_probe,
) -> tuple[int, dict[str, Any]]:
    """Inspect authority and runtime evidence without creating any root artifact."""

    runtime_root = root.expanduser().resolve()
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: Any) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    journal = runtime_root / OPERATION_JOURNAL_NAME
    add("data_operation", "blocker" if journal.exists() else "ok", str(journal))
    db_path = runtime_root / CHAT_DB_NAME
    try:
        inspection = database_inspector(db_path, require_current=False)
        contract = _mapping(inspection.get("schema"))
        contract_state = contract.get("state")
        schema_status = (
            "ok"
            if contract_state == "current"
            else (
                "warning"
                if contract_state in {"marker_required", "migration_required"}
                else "blocker"
            )
        )
        add("chat_db_integrity", "ok", inspection["integrity"])
        add("chat_schema", schema_status, dict(contract))
        if contract.get("compatible") is True and inspection.get("invariants") is not None:
            add("chat_authority_invariants", "ok", inspection["invariants"])
    except DataError as exc:
        add("chat_db", "blocker", {"code": exc.code, "message": str(exc)})
        inspection = None

    try:
        _payload, records, present = session_reader(runtime_root, lock=False)
        if inspection is not None and _compatible(inspection):
            session_reference_validator(db_path, records)
        add(
            "god_sessions",
            "ok" if present else "warning",
            {"source_present": present, "session_count": len(records)},
        )
    except DataError as exc:
        add("god_sessions", "blocker", {"code": exc.code, "message": str(exc)})

    if inspection is not None and _compatible(inspection):
        try:
            add("runtime_recovery_state", "ok", _runtime_recovery_state(db_path))
        except (DataInspectionError, sqlite3.Error):
            add(
                "runtime_recovery_state",
                "blocker",
                {"code": "chat_db_corrupt", "message": "runtime recovery evidence failed"},
            )
            inspection = None

    try:
        runtime = probe(runtime_root)
        try:
            assert_runtime_stopped(runtime_root, probe=lambda _root: runtime)
        except DataError as exc:
            if exc.code == "workroom_running":
                managed = _mapping(runtime.get("managed"))
                add(
                    "workroom",
                    "warning",
                    {"state": managed.get("state"), "running": True},
                )
            else:
                add(
                    "workroom",
                    "blocker",
                    {"code": exc.code, "message": str(exc)},
                )
        else:
            managed = _mapping(runtime.get("managed"))
            add(
                "workroom",
                "ok",
                {"state": managed.get("state"), "running": False},
            )
    except (OSError, ValueError, WorkroomError):
        add(
            "workroom",
            "blocker",
            {
                "code": "workroom_state_unverifiable",
                "message": "Workroom runtime state cannot be verified",
            },
        )

    blockers = [item for item in checks if item["status"] == "blocker"]
    warnings = [item for item in checks if item["status"] == "warning"]
    projection = {
        "schema_version": DOCTOR_SCHEMA,
        "state": "blocked" if blockers else ("degraded" if warnings else "healthy"),
        "root": str(runtime_root),
        "checks": checks,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
    }
    return (1 if blockers else 0), projection


def _runtime_recovery_state(path: Path) -> dict[str, int]:
    with readonly_connection(path) as conn:
        return {
            "claimed_observation_count": _count(
                conn,
                "select count(*) from room_observations where status = 'claimed'",
            ),
            "pending_control_count": _count(
                conn,
                """select count(*) from room_observations
                   where control_state in ('cancel_requested','cancel_pending')""",
            ),
            "unsafe_provider_cleanup_count": _count(
                conn,
                """select count(*) from room_observations o
                   join room_observation_attempts a on a.attempt_id = o.current_attempt_id
                   where o.status <> 'completed' and a.provider_phase in
                     ('ensure_started','bound','cleanup_pending')""",
            ),
        }


def _count(conn: sqlite3.Connection, statement: str) -> int:
    row = conn.execute(statement).fetchone()
    return int(row[0]) if row is not None else 0


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _compatible(inspection: Mapping[str, Any]) -> bool:
    return _mapping(inspection.get("schema")).get("compatible") is True


__all__ = [
    "DatabaseInspector",
    "SessionReader",
    "SessionReferenceValidator",
    "doctor_data",
]
