#!/usr/bin/env python3
"""Inspect, back up, restore, and compact the local xmuse authority data."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import shutil
import sqlite3
import tempfile
import uuid
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse import workroom
from xmuse.data_backup import (
    DataBackupError,
    manifest_file,
    normalize_artifact_database,
    online_backup,
    verify_manifest_file,
)
from xmuse.data_inspection import (
    DataInspectionError,
    canonical_bytes,
    readonly_connection,
    sha256_bytes,
    sha256_file,
    sqlite_value,
    table_columns,
    table_order_fingerprints,
    unique_keys,
)
from xmuse.data_mutation import (
    DataMutationError,
    operation_directory,
    safe_operation_paths,
    vacuum_into,
)
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.chat.memoryos_supervisor import (
    MemoryOSSupervisorError,
    clear_memoryos_derived_cache,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import (
    COMPAT_CHAT_SCHEMA_ID as CHAT_SCHEMA_ID,
)
from xmuse_core.chat.room_database import (
    COMPAT_CHAT_SCHEMA_VERSION as CHAT_SCHEMA_VERSION,
)
from xmuse_core.chat.room_database import (
    ROOM_REQUIRED_COLUMNS as _CANONICAL_ROOM_REQUIRED_COLUMNS,
)
from xmuse_core.chat.room_database import (
    ROOM_REQUIRED_UNIQUE_KEYS,
    ROOM_SCHEMA_ID,
    ROOM_SCHEMA_VERSION,
)
from xmuse_core.chat.room_execution_profiles import (
    RoomExecutionProfileError,
    execution_gate_plan_from_mapping,
)
from xmuse_core.chat.room_memory_rebuild_store import reset_room_memory_index_conn
from xmuse_core.runtime.paths import default_xmuse_root
from xmuse_core.runtime.processes import discover_xmuse_runtime_processes
from xmuse_core.runtime.root_contract import (
    CHAT_DB_NAME,
    DATA_LOCK_NAME,
    DATA_OPERATION_JOURNAL_NAME,
    GOD_SESSIONS_NAME,
    file_lock,
)

COMMAND_SCHEMA = "xmuse_data_command/v1"
DOCTOR_SCHEMA = "xmuse_data_doctor/v1"
BACKUP_SCHEMA = "xmuse_data_backup/v1"
OPERATION_SCHEMA = "xmuse_data_operation/v1"
CHAT_SCHEMA_CONTRACT = "xmuse.chat_db/v1"
ROOM_SCHEMA_CONTRACT = "xmuse.room_db/v1"
DATA_SCHEMA_VERSION = 1
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_XMUSE_ROOT = default_xmuse_root(REPO_ROOT / "xmuse")

SESSION_NAME = GOD_SESSIONS_NAME
BACKUP_MANIFEST_NAME = "manifest.json"
OPERATION_JOURNAL_NAME = DATA_OPERATION_JOURNAL_NAME

_COMMON_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "conversations": frozenset({"id", "title", "created_at"}),
    "messages": frozenset(
        {
            "id",
            "conversation_id",
            "author",
            "role",
            "content",
            "created_at",
            "envelope_type",
            "envelope_json",
            "mentions_json",
            "reply_to_message_id",
        }
    ),
    "participants": frozenset(
        {
            "participant_id",
            "conversation_id",
            "role",
            "display_name",
            "cli_kind",
            "model",
            "role_template_id",
            "status",
            "last_seen_at",
            "created_at",
        }
    ),
    "proposals": frozenset(
        {
            "id",
            "conversation_id",
            "author",
            "proposal_type",
            "content",
            "references_json",
            "status",
            "created_at",
            "accepted_resolution_id",
        }
    ),
    "chat_request_log": frozenset(
        {
            "id",
            "conversation_id",
            "tool_name",
            "caller_identity",
            "client_request_id",
            "result_json",
            "created_at",
        }
    ),
    "chat_frontend_events": frozenset(
        {
            "event_id",
            "conversation_id",
            "seq",
            "event_type",
            "resource_ref",
            "source_authority",
            "source_ref",
            "payload_json",
            "client_action_id",
            "created_at",
            "projection_only",
            "proof_boundary",
        }
    ),
    "room_activities": frozenset(
        {
            "activity_id",
            "conversation_id",
            "seq",
            "activity_type",
            "actor_kind",
            "actor_identity",
            "actor_participant_id",
            "causation_id",
            "correlation_id",
            "visibility",
            "audience_json",
            "payload_json",
            "materialized_message_id",
            "causal_depth",
            "materialized_proposal_id",
            "delivery_mode",
            "created_at",
        }
    ),
    "room_observations": frozenset(
        {
            "observation_id",
            "conversation_id",
            "activity_id",
            "participant_id",
            "priority",
            "delivery_mode",
            "status",
            "lease_owner",
            "acquired_at",
            "expires_at",
            "lease_token",
            "attempt_count",
            "outcome_type",
            "outcome_payload_json",
            "outcome_actor_identity",
            "outcome_client_request_id",
            "produced_activity_id",
            "produced_message_id",
            "produced_proposal_id",
            "completed_at",
            "created_at",
            "updated_at",
            "control_state",
            "control_seq",
            "manual_retry_budget",
            "current_attempt_id",
        }
    ),
    "room_observation_attempts": frozenset(
        {
            "attempt_id",
            "conversation_id",
            "observation_id",
            "participant_id",
            "attempt_number",
            "effective_attempt_limit",
            "delivery_generation",
            "state",
            "reason_code",
            "lease_owner",
            "lease_token_digest",
            "delivery_task_id",
            "god_session_id",
            "provider_session_id",
            "provider_session_generation",
            "provider_phase",
            "provider_cleanup_reason",
            "provider_phase_updated_at",
            "claimed_at",
            "expires_at",
            "transport_started_at",
            "finished_at",
            "created_at",
            "updated_at",
        }
    ),
    "room_observation_controls": frozenset(
        {
            "control_id",
            "conversation_id",
            "observation_id",
            "participant_id",
            "action",
            "client_action_id",
            "operator_identity",
            "request_fingerprint",
            "expected_state",
            "expected_attempt_count",
            "expected_control_seq",
            "resulting_state",
            "resulting_control_seq",
            "attempt_id",
            "status",
            "reason_code",
            "frontend_event_seq",
            "requested_at",
            "applied_at",
            "updated_at",
        }
    ),
    "room_participant_cursors": frozenset(
        {
            "conversation_id",
            "participant_id",
            "last_acknowledged_seq",
            "last_observation_id",
            "updated_at",
        }
    ),
    "room_attempt_skill_decisions": frozenset(
        {
            "attempt_id",
            "selector_version",
            "participant_role_snapshot",
            "selection_input_sha256",
            "decision",
            "skill_id",
            "skill_version",
            "skill_content_sha256",
            "skill_instructions_sha256",
            "catalog_sha256",
            "selection_reason",
            "matched_terms_json",
            "context_payload_sha256",
            "context_submitted_at",
            "created_at",
            "updated_at",
        }
    ),
}

_COMPAT_ONLY_REQUIRED_COLUMNS: dict[str, frozenset[str]] = {
    "role_templates": frozenset(
        {
            "id",
            "slug",
            "display_name",
            "prompt",
            "cli_kind",
            "default_model",
            "predefined",
            "created_at",
            "updated_at",
        }
    ),
    "schema_migrations": frozenset({"version", "applied_at"}),
}

_ROOM_REQUIRED_COLUMNS = dict(_CANONICAL_ROOM_REQUIRED_COLUMNS)
# Room v1 permits additive runtime migrations without changing the public data
# contract.  A stopped database created by the previous v1 runtime must remain
# inspectable and backupable before the new runtime has had a chance to add
# these internal action-recovery columns.  Runtime initialization still uses
# the canonical set above and therefore adds and validates both columns.
_ROOM_REQUIRED_COLUMNS["room_codex_bridge_actions"] = _ROOM_REQUIRED_COLUMNS[
    "room_codex_bridge_actions"
] - {"execution_stage", "failure_stage"}
_CHAT_REQUIRED_COLUMNS = _COMMON_REQUIRED_COLUMNS | _COMPAT_ONLY_REQUIRED_COLUMNS

_REQUIRED_UNIQUE_KEYS = set(ROOM_REQUIRED_UNIQUE_KEYS)

_JSON_COLUMNS = {
    "messages": ("envelope_json", "mentions_json"),
    "proposals": ("references_json",),
    "chat_request_log": ("result_json",),
    "chat_frontend_events": ("payload_json",),
    "room_activities": ("audience_json", "payload_json"),
    "room_observations": ("outcome_payload_json",),
    "room_attempt_skill_decisions": ("matched_terms_json",),
    "room_execution_candidates": ("allowed_files_json", "files_json"),
    "room_execution_operator_actions": ("result_json",),
    "room_execution_runs": ("changed_files_json", "gate_ids_json"),
    "room_execution_promotion_journal": ("file_entries_json",),
    "room_codex_bridge_actions": ("request_json", "ack_summary_json"),
}


class DataError(RuntimeError):
    """Stable user-facing data lifecycle error."""

    def __init__(self, code: str, message: str, **details: Any) -> None:
        super().__init__(message)
        self.code = code
        self.details = details


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _package_version() -> str:
    try:
        return importlib.metadata.version("xmuse")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0"


def _canonical_bytes(value: Any) -> bytes:
    return canonical_bytes(value)


def _sha256_bytes(value: bytes) -> str:
    return sha256_bytes(value)


def _sha256_file(path: Path) -> str:
    return sha256_file(path)


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


@contextmanager
def _file_lock(path: Path, *, exclusive: bool = True) -> Iterator[None]:
    with file_lock(path, exclusive=exclusive):
        yield


@contextmanager
def _readonly_connection(path: Path) -> Iterator[sqlite3.Connection]:
    try:
        with readonly_connection(path) as connection:
            yield connection
    except DataInspectionError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return table_columns(conn, table)


def _unique_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    return unique_keys(conn, table)


def _schema_contract(conn: sqlite3.Connection) -> dict[str, Any]:
    tables = {
        str(row[0])
        for row in conn.execute(
            "select name from sqlite_schema where type = 'table' and name not like 'sqlite_%'"
        )
    }
    base: dict[str, Any] = {
        "schema_id": None,
        "schema_contract": None,
        "schema_contract_version": None,
        "marker_version": None,
        "marker_versions": {},
        "missing_tables": [],
        "missing_columns": {},
        "missing_unique_keys": [],
    }
    if "chat_schema_meta" not in tables:
        return base | {
            "state": "migration_required" if "conversations" in tables else "unsupported",
            "compatible": False,
        }
    marker_columns = _table_columns(conn, "chat_schema_meta")
    required_marker_columns = {"schema_id", "version", "updated_at"}
    if not required_marker_columns <= marker_columns:
        return base | {
            "state": "unsupported",
            "compatible": False,
            "missing_columns": {
                "chat_schema_meta": sorted(required_marker_columns - marker_columns)
            },
        }
    marker_versions: dict[str, int] = {}
    for schema_id in (ROOM_SCHEMA_ID, CHAT_SCHEMA_ID):
        row = conn.execute(
            "select version from chat_schema_meta where schema_id = ?", (schema_id,)
        ).fetchone()
        if row is None:
            continue
        try:
            marker_versions[schema_id] = int(row[0])
        except (TypeError, ValueError):
            return base | {
                "state": "unsupported",
                "compatible": False,
                "missing_columns": {"chat_schema_meta": ["valid version"]},
            }
    expected_versions = {
        ROOM_SCHEMA_ID: ROOM_SCHEMA_VERSION,
        CHAT_SCHEMA_ID: CHAT_SCHEMA_VERSION,
    }
    incompatible = [
        (schema_id, version)
        for schema_id, version in marker_versions.items()
        if version != expected_versions[schema_id]
    ]
    if incompatible:
        is_future = any(
            version > expected_versions[schema_id] for schema_id, version in incompatible
        )
        return base | {
            "state": "future" if is_future else "migration_required",
            "compatible": False,
            "marker_versions": marker_versions,
        }

    chat_marker = marker_versions.get(CHAT_SCHEMA_ID)
    room_marker = marker_versions.get(ROOM_SCHEMA_ID)
    if chat_marker is not None:
        # A chat-only v1 database is a supported legacy compat artifact. Once a
        # Room marker is also published, the full Room v1 contract must be true.
        required_columns = dict(_CHAT_REQUIRED_COLUMNS)
        if room_marker is not None:
            for table, columns in _ROOM_REQUIRED_COLUMNS.items():
                required_columns[table] = required_columns.get(table, frozenset()) | columns
        schema_id = CHAT_SCHEMA_ID
        schema_contract = CHAT_SCHEMA_CONTRACT
        schema_version = CHAT_SCHEMA_VERSION
        marker_version = chat_marker
    elif room_marker is not None:
        required_columns = _ROOM_REQUIRED_COLUMNS
        schema_id = ROOM_SCHEMA_ID
        schema_contract = ROOM_SCHEMA_CONTRACT
        schema_version = ROOM_SCHEMA_VERSION
        marker_version = room_marker
    else:
        return base | {
            "state": "marker_required",
            "compatible": False,
            "marker_versions": marker_versions,
        }

    missing_tables = sorted(set(required_columns) - tables)
    missing_columns: dict[str, list[str]] = {}
    for table, required in required_columns.items():
        if table in tables and (absent := sorted(required - _table_columns(conn, table))):
            missing_columns[table] = absent
    missing_unique = [
        {"table": table, "columns": list(columns)}
        for table, columns in sorted(_REQUIRED_UNIQUE_KEYS)
        if table in required_columns
        and table in tables
        and columns not in _unique_keys(conn, table)
    ]
    if missing_tables or missing_columns or missing_unique:
        return base | {
            "state": "unsupported",
            "compatible": False,
            "schema_id": schema_id,
            "schema_contract": schema_contract,
            "schema_contract_version": schema_version,
            "marker_version": marker_version,
            "marker_versions": marker_versions,
            "missing_tables": missing_tables,
            "missing_columns": missing_columns,
            "missing_unique_keys": missing_unique,
        }
    return base | {
        "state": "current",
        "compatible": True,
        "schema_id": schema_id,
        "schema_contract": schema_contract,
        "schema_contract_version": schema_version,
        "marker_version": marker_version,
        "marker_versions": marker_versions,
    }


def _integrity_report(conn: sqlite3.Connection) -> dict[str, Any]:
    try:
        integrity_rows = [str(row[0]) for row in conn.execute("pragma integrity_check")]
        foreign_keys = [tuple(row) for row in conn.execute("pragma foreign_key_check")]
    except sqlite3.Error as exc:
        raise DataError("chat_db_corrupt", "SQLite integrity inspection failed") from exc
    return {
        "integrity": "ok" if integrity_rows == ["ok"] else "failed",
        "integrity_messages": integrity_rows if integrity_rows != ["ok"] else [],
        "foreign_key_violation_count": len(foreign_keys),
    }


def _validate_json_columns(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    invalid: list[dict[str, Any]] = []
    for table, columns in _JSON_COLUMNS.items():
        available = _table_columns(conn, table)
        for column in columns:
            if column not in available:
                continue
            row = conn.execute(
                f'select count(*) from "{table}" '
                f'where "{column}" is not null and not json_valid("{column}")'
            ).fetchone()
            count = int(row[0]) if row is not None else 0
            if count:
                invalid.append({"table": table, "column": column, "count": count})
    return invalid


def _sequence_gaps(conn: sqlite3.Connection, table: str) -> list[str]:
    rows = conn.execute(
        f"""select conversation_id from {table}
            group by conversation_id
            having min(seq) <> 1 or count(*) <> max(seq)"""
    ).fetchall()
    return [str(row[0]) for row in rows]


def _batch_authority_invalid_count(conn: sqlite3.Connection) -> int:
    """Validate immutable batch coverage beyond SQLite's row-level foreign keys."""

    invalid = int(
        conn.execute(
            """select count(*) from room_observation_attempts a
               left join room_observation_batches b on b.batch_id = a.batch_id
               where a.batch_id is not null and (
                   b.batch_id is null or a.observation_id <> b.primary_observation_id
               )"""
        ).fetchone()[0]
    )
    batches = conn.execute("select * from room_observation_batches order by batch_id").fetchall()
    for batch in batches:
        members = conn.execute(
            """select m.*, o.conversation_id as observation_conversation_id,
                      o.participant_id as observation_participant_id,
                      o.activity_id as observation_activity_id,
                      a.conversation_id as activity_conversation_id,
                      a.correlation_id as activity_correlation_id,
                      a.seq as authoritative_activity_seq
               from room_observation_batch_members m
               left join room_observations o on o.observation_id = m.observation_id
               left join room_activities a on a.activity_id = m.activity_id
               where m.batch_id = ? order by m.ordinal""",
            (batch["batch_id"],),
        ).fetchall()
        member_facts = [
            {
                "observation_id": str(member["observation_id"]),
                "activity_id": str(member["activity_id"]),
                "activity_seq": int(member["activity_seq"]),
            }
            for member in members
        ]
        expected_digest = _sha256_bytes(
            _canonical_bytes(
                {
                    "conversation_id": str(batch["conversation_id"]),
                    "participant_id": str(batch["participant_id"]),
                    "correlation_id": str(batch["correlation_id"]),
                    "phase": str(batch["phase"]),
                    "cutoff_seq": int(batch["cutoff_seq"]),
                    "members": member_facts,
                }
            )
        )
        valid = (
            bool(members)
            and len(members) == int(batch["member_count"])
            and [int(member["ordinal"]) for member in members] == list(range(len(members)))
            and str(members[0]["observation_id"]) == str(batch["primary_observation_id"])
            and max(int(member["activity_seq"]) for member in members) == int(batch["cutoff_seq"])
            and str(batch["digest"]) == expected_digest
            and all(
                member["observation_conversation_id"] == batch["conversation_id"]
                and member["observation_participant_id"] == batch["participant_id"]
                and member["observation_activity_id"] == member["activity_id"]
                and member["activity_conversation_id"] == batch["conversation_id"]
                and member["activity_correlation_id"] == batch["correlation_id"]
                and member["authoritative_activity_seq"] == member["activity_seq"]
                for member in members
            )
        )
        invalid += int(not valid)
    return invalid


def _authority_invariants(conn: sqlite3.Connection) -> dict[str, Any]:
    invalid_json = _validate_json_columns(conn)
    room_gaps = _sequence_gaps(conn, "room_activities")
    event_gaps = _sequence_gaps(conn, "chat_frontend_events")
    tables = {
        str(row[0]) for row in conn.execute("select name from sqlite_schema where type = 'table'")
    }
    has_batches = {
        "room_observation_batches",
        "room_observation_batch_members",
    } <= tables and "batch_id" in _table_columns(conn, "room_observation_attempts")
    if has_batches:
        attempt_mismatches = int(
            conn.execute(
                """select count(*) from room_observations o
                   left join room_observation_attempts a
                     on a.attempt_id = o.current_attempt_id
                   left join room_observation_batch_members bm
                     on bm.observation_id = o.observation_id
                   left join room_observation_batches b on b.batch_id = bm.batch_id
                   where o.current_attempt_id is not null and (
                       a.attempt_id is null
                       or a.conversation_id <> o.conversation_id
                       or a.participant_id <> o.participant_id
                       or not (
                           (bm.batch_id is null
                               and a.observation_id = o.observation_id)
                           or (bm.batch_id is not null
                               and a.batch_id is not null
                               and a.batch_id = bm.batch_id
                               and a.observation_id = b.primary_observation_id)
                       )
                   )"""
            ).fetchone()[0]
        )
        batch_invalid_count = _batch_authority_invalid_count(conn)
    else:
        attempt_mismatches = int(
            conn.execute(
                """select count(*) from room_observations o
                   left join room_observation_attempts a
                     on a.attempt_id = o.current_attempt_id
                   where o.current_attempt_id is not null and (
                       a.attempt_id is null or a.observation_id <> o.observation_id
                       or a.conversation_id <> o.conversation_id
                       or a.participant_id <> o.participant_id)"""
            ).fetchone()[0]
        )
        batch_invalid_count = 0
    control_mismatches = int(
        conn.execute(
            """select count(*) from room_observation_controls c
               left join room_observations o on o.observation_id = c.observation_id
               where o.observation_id is null or o.conversation_id <> c.conversation_id
                   or o.participant_id <> c.participant_id"""
        ).fetchone()[0]
    )
    claimed_without_attempt = int(
        conn.execute(
            """select count(*) from room_observations
               where status = 'claimed' and current_attempt_id is null"""
        ).fetchone()[0]
    )
    active_claim_incomplete = int(
        conn.execute(
            """select count(*) from room_observations
               where status = 'claimed' and control_state = 'active' and (
                   current_attempt_id is null or lease_owner is null
                   or lease_token is null or acquired_at is null or expires_at is null)"""
        ).fetchone()[0]
    )
    has_execution = "room_execution_candidates" in tables
    execution_binding_mismatches = 0
    execution_review_mismatches = 0
    execution_run_mismatches = 0
    execution_gate_plan_mismatches = 0
    if has_execution:
        execution_binding_mismatches = int(
            conn.execute(
                """select count(*) from room_execution_candidates c
                   left join proposals p on p.id = c.proposal_id
                   left join room_activities a on a.activity_id = c.source_activity_id
                   left join room_observations o
                     on o.observation_id = c.source_observation_id
                   left join room_observation_attempts t on t.attempt_id = c.source_attempt_id
                   left join room_observation_batches b on b.batch_id = c.source_batch_id
                   left join participants author on author.participant_id = c.author_participant_id
                   where p.id is null or a.activity_id is null or o.observation_id is null
                      or t.attempt_id is null or b.batch_id is null
                      or author.participant_id is null
                      or p.conversation_id <> c.conversation_id
                      or p.author <> c.author_participant_id
                      or a.conversation_id <> c.conversation_id
                      or a.actor_participant_id <> c.author_participant_id
                      or a.correlation_id <> c.source_correlation_id
                      or t.conversation_id <> c.conversation_id
                      or t.observation_id <> c.source_observation_id
                      or t.batch_id is not c.source_batch_id
                      or o.conversation_id <> c.conversation_id
                      or o.participant_id <> c.author_participant_id
                      or o.current_attempt_id <> c.source_attempt_id
                      or b.conversation_id <> c.conversation_id
                      or b.participant_id <> c.author_participant_id
                      or b.primary_observation_id <> c.source_observation_id
                      or author.conversation_id <> c.conversation_id
                      or a.materialized_proposal_id <> c.proposal_id"""
            ).fetchone()[0]
        )
        execution_review_mismatches = int(
            conn.execute(
                """select count(*) from room_execution_assessments a
                   left join room_execution_candidates c on c.candidate_id = a.candidate_id
                   left join room_execution_candidate_members m
                     on m.candidate_id = a.candidate_id
                    and m.participant_id = a.assessor_participant_id
                   where c.candidate_id is null or m.candidate_id is null
                      or m.full_material_available <> 1
                      or m.review_attempt_id <> a.source_attempt_id
                      or m.review_batch_id <> a.source_batch_id
                      or m.review_activity_id <> a.source_activity_id
                      or m.review_material_digest <> a.review_material_digest
                      or c.candidate_digest <> a.candidate_digest
                      or m.identity_fingerprint <> a.assessor_identity_fingerprint"""
            ).fetchone()[0]
        )
        execution_run_mismatches = int(
            conn.execute(
                """select count(*) from room_execution_runs r
                   left join room_execution_authorizations z
                     on z.authorization_id = r.authorization_id
                   left join room_execution_candidates c on c.candidate_id = r.candidate_id
                   where z.authorization_id is null or c.candidate_id is null
                      or z.candidate_id <> r.candidate_id
                      or z.conversation_id <> r.conversation_id
                      or c.conversation_id <> r.conversation_id
                      or c.state <> 'authorized'
                      or z.candidate_digest <> c.candidate_digest
                      or z.peer_snapshot_digest <> c.peer_snapshot_digest
                      or z.policy_revision <> c.policy_revision_snapshot
                      or z.risk_policy_revision <> c.risk_policy_revision_snapshot"""
            ).fetchone()[0]
        )
        if "room_execution_gate_plan_bindings" in tables:
            execution_gate_plan_mismatches += int(
                conn.execute(
                    """select count(*) from room_execution_runs r
                       left join room_execution_gate_plan_bindings b on b.run_id = r.run_id
                       where r.state not in ('cancelled','succeeded','failed','blocked')
                         and b.run_id is null"""
                ).fetchone()[0]
            )
            bindings = conn.execute(
                """select b.*, r.authorization_id run_authorization_id,
                          r.gate_ids_json run_gate_ids_json,
                          c.allowed_files_json candidate_allowed_files_json
                   from room_execution_gate_plan_bindings b
                   left join room_execution_runs r on r.run_id = b.run_id
                   left join room_execution_candidates c on c.candidate_id = r.candidate_id"""
            ).fetchall()
            for binding in bindings:
                try:
                    mapping = {
                        "schema_version": binding["schema_version"],
                        "profile_id": binding["profile_id"],
                        "revision": int(binding["profile_revision"]),
                        "profile_digest": binding["profile_digest"],
                        "gate_ids": json.loads(binding["gate_ids_json"]),
                        "repository_manifest_digest": binding["repository_manifest_digest"],
                        "toolchain_capability_digest": binding["toolchain_capability_digest"],
                        "gate_plan_digest": binding["gate_plan_digest"],
                    }
                    allowed_files = tuple(json.loads(binding["candidate_allowed_files_json"]))
                    plan = execution_gate_plan_from_mapping(
                        mapping,
                        changed_paths=allowed_files,
                    )
                    valid_binding = binding["run_authorization_id"] == binding[
                        "authorization_id"
                    ] and json.loads(binding["run_gate_ids_json"]) == list(plan.gate_ids)
                except (
                    RoomExecutionProfileError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ):
                    valid_binding = False
                execution_gate_plan_mismatches += int(not valid_binding)
        else:
            execution_gate_plan_mismatches += int(
                conn.execute(
                    """select count(*) from room_execution_runs
                       where state not in ('cancelled','succeeded','failed','blocked')"""
                ).fetchone()[0]
            )
    return {
        "invalid_json": invalid_json,
        "room_sequence_gaps": room_gaps,
        "event_sequence_gaps": event_gaps,
        "attempt_binding_mismatch_count": attempt_mismatches,
        "observation_batch_invalid_count": batch_invalid_count,
        "control_binding_mismatch_count": control_mismatches,
        "claimed_without_attempt_count": claimed_without_attempt,
        "active_claim_incomplete_count": active_claim_incomplete,
        "execution_binding_mismatch_count": execution_binding_mismatches,
        "execution_review_mismatch_count": execution_review_mismatches,
        "execution_run_mismatch_count": execution_run_mismatches,
        "execution_gate_plan_mismatch_count": execution_gate_plan_mismatches,
        "valid": not (
            invalid_json
            or room_gaps
            or event_gaps
            or attempt_mismatches
            or batch_invalid_count
            or control_mismatches
            or claimed_without_attempt
            or active_claim_incomplete
            or execution_binding_mismatches
            or execution_review_mismatches
            or execution_run_mismatches
            or execution_gate_plan_mismatches
        ),
    }


def _inspect_database(path: Path, *, require_current: bool) -> dict[str, Any]:
    with _readonly_connection(path) as conn:
        integrity = _integrity_report(conn)
        if integrity["integrity"] != "ok" or integrity["foreign_key_violation_count"]:
            raise DataError("chat_db_corrupt", "chat database integrity validation failed")
        contract = _schema_contract(conn)
        if require_current and not contract["compatible"]:
            raise DataError(
                "backup_schema_unsupported",
                f"chat schema is not supported: {contract['state']}",
                schema=contract,
            )
        invariants = _authority_invariants(conn) if contract["compatible"] else None
        if invariants is not None and not invariants["valid"]:
            raise DataError(
                "chat_db_corrupt",
                "chat authority invariants failed",
                invariants=invariants,
            )
        journal_mode = str(conn.execute("pragma journal_mode").fetchone()[0])
        page_size = int(conn.execute("pragma page_size").fetchone()[0])
        page_count = int(conn.execute("pragma page_count").fetchone()[0])
        migrations = (
            sorted(str(row[0]) for row in conn.execute("select version from schema_migrations"))
            if "schema_migrations"
            in {
                str(row[0])
                for row in conn.execute("select name from sqlite_schema where type = 'table'")
            }
            else []
        )
    return {
        "integrity": integrity,
        "schema": contract,
        "invariants": invariants,
        "journal_mode": journal_mode,
        "page_size": page_size,
        "page_count": page_count,
        "migrations": migrations,
    }


def _schema_fingerprint(conn: sqlite3.Connection) -> str:
    rows = [
        [row[0], row[1], row[2], row[3]]
        for row in conn.execute(
            """select type, name, tbl_name, coalesce(sql, '') from sqlite_schema
               where name not like 'sqlite_%' order by type, name"""
        )
    ]
    return _sha256_bytes(_canonical_bytes(rows))


def _room_high_water(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """select c.id conversation_id,
                  coalesce(a.activity_count, 0) activity_count,
                  coalesce(a.latest_activity_seq, 0) latest_activity_seq,
                  coalesce(e.frontend_event_count, 0) frontend_event_count,
                  coalesce(e.latest_frontend_event_seq, 0) latest_frontend_event_seq
           from conversations c
           left join (
               select conversation_id, count(*) activity_count, max(seq) latest_activity_seq
               from room_activities group by conversation_id
           ) a on a.conversation_id = c.id
           left join (
               select conversation_id, count(*) frontend_event_count,
                      max(seq) latest_frontend_event_seq
               from chat_frontend_events group by conversation_id
           ) e on e.conversation_id = c.id
           order by c.id"""
    ).fetchall()
    return [
        {
            "conversation_id": str(row["conversation_id"]),
            "activity_count": int(row["activity_count"]),
            "latest_activity_seq": int(row["latest_activity_seq"]),
            "frontend_event_count": int(row["frontend_event_count"]),
            "latest_frontend_event_seq": int(row["latest_frontend_event_seq"]),
        }
        for row in rows
    ]


def _database_evidence(path: Path) -> dict[str, Any]:
    with _readonly_connection(path) as conn:
        rooms = _room_high_water(conn)
        totals = {
            "conversation_count": int(
                conn.execute("select count(*) from conversations").fetchone()[0]
            ),
            "message_count": int(conn.execute("select count(*) from messages").fetchone()[0]),
            "room_activity_count": int(
                conn.execute("select count(*) from room_activities").fetchone()[0]
            ),
            "observation_count": int(
                conn.execute("select count(*) from room_observations").fetchone()[0]
            ),
            "attempt_count": int(
                conn.execute("select count(*) from room_observation_attempts").fetchone()[0]
            ),
            "control_count": int(
                conn.execute("select count(*) from room_observation_controls").fetchone()[0]
            ),
        }
        return {
            "schema_fingerprint_sha256": _schema_fingerprint(conn),
            "rooms": rooms,
            "rooms_sha256": _sha256_bytes(_canonical_bytes(rooms)),
            "totals": totals,
        }


_SESSION_FIELDS = {field.name for field in fields(GodSessionRecord)}
_SESSION_REQUIRED_TEXT = {
    "god_session_id",
    "role",
    "agent_name",
    "runtime",
    "session_address",
    "session_inbox_id",
}
_SESSION_OPTIONAL_TEXT = (
    _SESSION_FIELDS
    - _SESSION_REQUIRED_TEXT
    - {
        "pid",
        "prompt_layer_order",
        "prompt_layer_hashes",
    }
)


def _validate_sessions(payload: dict[str, Any]) -> list[GodSessionRecord]:
    if set(payload) != {"sessions"} or not isinstance(payload["sessions"], list):
        raise DataError("session_registry_invalid", "session registry must contain only sessions[]")
    records: list[GodSessionRecord] = []
    unique: dict[str, set[str]] = {
        "god_session_id": set(),
        "session_address": set(),
        "session_inbox_id": set(),
        "provider_session_id": set(),
    }
    participant_slots: set[tuple[str, str, str | None]] = set()
    for index, raw in enumerate(payload["sessions"]):
        if not isinstance(raw, dict) or not set(raw) <= _SESSION_FIELDS:
            raise DataError("session_registry_invalid", f"invalid session record at index {index}")
        for name in _SESSION_REQUIRED_TEXT:
            if not isinstance(raw.get(name), str) or not str(raw[name]).strip():
                raise DataError(
                    "session_registry_invalid",
                    f"session field {name} is invalid at index {index}",
                )
        for name in ("conversation_id", "participant_id"):
            if raw.get(name) is not None and not isinstance(raw.get(name), str):
                raise DataError("session_registry_invalid", f"session field {name} is invalid")
        if (raw.get("conversation_id") is None) != (raw.get("participant_id") is None):
            raise DataError(
                "session_registry_invalid",
                "session conversation and participant identity must be paired",
            )
        for name in _SESSION_OPTIONAL_TEXT:
            value = raw.get(name)
            if value is not None and not isinstance(value, str):
                raise DataError("session_registry_invalid", f"session field {name} is invalid")
        pid = raw.get("pid")
        if pid is not None and (not isinstance(pid, int) or isinstance(pid, bool) or pid <= 0):
            raise DataError("session_registry_invalid", "session pid is invalid")
        for name in ("prompt_layer_order",):
            if raw.get(name) is not None and (
                not isinstance(raw.get(name), list)
                or any(not isinstance(item, str) for item in raw[name])
            ):
                raise DataError("session_registry_invalid", f"session field {name} is invalid")
        for name in ("prompt_layer_hashes",):
            if raw.get(name) is not None and (
                not isinstance(raw.get(name), dict)
                or any(
                    not isinstance(key, str) or not isinstance(value, str)
                    for key, value in raw[name].items()
                )
            ):
                raise DataError("session_registry_invalid", f"session field {name} is invalid")
        try:
            record = GodSessionRecord(**raw)
        except (TypeError, ValueError) as exc:
            raise DataError("session_registry_invalid", "session record is invalid") from exc
        for name, values in unique.items():
            raw_value = getattr(record, name)
            if raw_value is None:
                continue
            value = str(raw_value)
            if value in values:
                raise DataError("session_registry_invalid", f"duplicate session {name}: {value}")
            values.add(value)
        if record.conversation_id is not None and record.participant_id is not None:
            slot = (record.conversation_id, record.participant_id, record.feature_scope_id)
            if slot in participant_slots:
                raise DataError("session_registry_invalid", "duplicate participant session slot")
            participant_slots.add(slot)
        records.append(record)
    return records


def _read_sessions(
    root: Path,
    *,
    lock: bool = True,
) -> tuple[dict[str, Any], list[GodSessionRecord], bool]:
    path = root / SESSION_NAME

    @contextmanager
    def read_guard() -> Iterator[None]:
        if lock:
            with _file_lock(path.with_name(f"{path.name}.lock"), exclusive=False):
                yield
        else:
            yield

    with read_guard():
        if not path.exists():
            payload: dict[str, Any] = {"sessions": []}
            return payload, [], False
        if not path.is_file() or path.is_symlink():
            raise DataError("session_registry_invalid", f"invalid session registry: {path}")
        payload = _read_json(path, code="session_registry_invalid")
    return payload, _validate_sessions(payload), True


def _validate_session_references(
    db_path: Path,
    records: Sequence[GodSessionRecord],
) -> None:
    with _readonly_connection(db_path) as conn:
        participants = {
            (str(row["conversation_id"]), str(row["participant_id"])): {
                "role": str(row["role"]),
                "display_name": str(row["display_name"]),
                "cli_kind": str(row["cli_kind"]),
                "model": str(row["model"]),
            }
            for row in conn.execute(
                """select conversation_id, participant_id, role, display_name,
                          cli_kind, model from participants"""
            )
        }
        conversations = {str(row[0]) for row in conn.execute("select id from conversations")}
    for record in records:
        if record.conversation_id is None and record.participant_id is None:
            continue
        if record.conversation_id is None or record.participant_id is None:
            raise DataError(
                "session_registry_invalid",
                f"session identity is incomplete: {record.god_session_id}",
            )
        identity = (record.conversation_id, record.participant_id)
        participant = participants.get(identity)
        if record.conversation_id not in conversations or participant is None:
            raise DataError(
                "session_registry_invalid",
                f"session identity is absent from chat.db: {record.god_session_id}",
            )
        expected = {
            "role": participant["role"],
            "agent_name": participant["display_name"],
            "runtime": participant["cli_kind"],
            "model": participant["model"],
        }
        actual = {
            "role": record.role,
            "agent_name": record.agent_name,
            "runtime": record.runtime,
            "model": record.model,
        }
        if actual != expected:
            raise DataError(
                "session_registry_invalid",
                f"session identity metadata does not match chat.db: {record.god_session_id}",
            )


def _sanitize_sessions(records: Sequence[GodSessionRecord]) -> dict[str, Any]:
    sessions: list[dict[str, Any]] = []
    for record in records:
        payload = asdict(record)
        payload.update(
            {
                "status": "starting",
                "pid": None,
                "provider_session_id": None,
                "provider_session_kind": None,
                "provider_binding_status": None,
                "provider_binding_failure_reason": None,
            }
        )
        sessions.append(payload)
    return {"sessions": sessions}


def _normalize_artifact_database(path: Path) -> None:
    try:
        normalize_artifact_database(path)
    except DataBackupError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _online_backup(source: Path, destination: Path) -> str:
    try:
        return online_backup(source, destination)
    except DataBackupError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _manifest_file(path: Path) -> dict[str, Any]:
    return manifest_file(path)


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
    inspection = _inspect_database(chat_path, require_current=True)
    evidence = _database_evidence(chat_path)
    return {
        "schema_version": BACKUP_SCHEMA,
        "data_schema_version": DATA_SCHEMA_VERSION,
        "backup_id": backup_id,
        "created_at": created_at,
        "xmuse_version": _package_version(),
        "files": {
            "chat_db": _manifest_file(chat_path),
            "god_sessions": _manifest_file(sessions_path)
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


def backup_data(root: Path, destination: Path) -> dict[str, Any]:
    runtime_root = root.expanduser().resolve()
    final = destination.expanduser().resolve()
    if final.exists() or final.is_symlink():
        raise DataError("backup_destination_exists", f"backup destination exists: {final}")
    final.parent.mkdir(parents=True, exist_ok=True)
    with _file_lock(runtime_root / DATA_LOCK_NAME):
        if _operation_journal(runtime_root).exists():
            raise DataError(
                "data_operation_incomplete",
                "recover the interrupted data operation before creating a backup",
            )
        source = runtime_root / CHAT_DB_NAME
        source_inspection = _inspect_database(source, require_current=True)
        backup_id = f"backup-{uuid.uuid4().hex}"
        staging = Path(tempfile.mkdtemp(prefix=f".{final.name}.{backup_id}.", dir=final.parent))
        published = False
        try:
            db_started = _utc_now()
            source_mode = _online_backup(source, staging / CHAT_DB_NAME)
            db_completed = _utc_now()
            _normalize_artifact_database(staging / CHAT_DB_NAME)
            _inspect_database(staging / CHAT_DB_NAME, require_current=True)
            session_payload, session_records, source_sessions_present = _read_sessions(runtime_root)
            _validate_session_references(staging / CHAT_DB_NAME, session_records)
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
                source_mode=source_mode,
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


def _verify_manifest_file(backup: Path, entry: Any, expected_name: str) -> Path:
    try:
        return verify_manifest_file(backup, entry, expected_name)
    except DataBackupError as exc:
        raise DataError(exc.code, str(exc)) from exc


def verify_backup(
    backup: Path,
) -> tuple[dict[str, Any], Path, dict[str, Any], list[GodSessionRecord]]:
    location = backup.expanduser().resolve()
    if not location.is_dir() or location.is_symlink():
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
    chat_path = _verify_manifest_file(location, files.get("chat_db"), CHAT_DB_NAME)
    sessions_path = _verify_manifest_file(location, files.get("god_sessions"), SESSION_NAME)
    inspection = _inspect_database(chat_path, require_current=True)
    schema = inspection["schema"]
    evidence = _database_evidence(chat_path)
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
    records = _validate_sessions(sessions_payload)
    session_entry = files.get("god_sessions")
    if not isinstance(session_entry, dict) or session_entry.get("session_count") != len(records):
        raise DataError("backup_manifest_invalid", "backup session count does not match")
    _validate_session_references(chat_path, records)
    return manifest, chat_path, sessions_payload, records


def _verify_staged_database_copy(path: Path, manifest: Mapping[str, Any]) -> None:
    """Revalidate the bytes actually copied for restore before any fencing write."""

    files = manifest.get("files")
    entry = files.get("chat_db") if isinstance(files, dict) else None
    if (
        not isinstance(entry, dict)
        or entry.get("size_bytes") != path.stat().st_size
        or entry.get("sha256") != _sha256_file(path)
    ):
        raise DataError(
            "backup_checksum_mismatch",
            "staged chat.db no longer matches the verified backup",
        )
    _inspect_database(path, require_current=True)
    evidence = _database_evidence(path)
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


def _fence_restored_execution_runs(path: Path, *, operation_id: str) -> dict[str, int]:
    """Fence process-local Harness work without replaying a restored process action."""

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


def _fence_restored_memory_index(path: Path, *, operation_id: str) -> dict[str, int]:
    """Forget process-local MemoryOS bindings and reopen rebuildable deliveries.

    ``chat.db`` remains the source of activities, approvals, and audit receipts. A
    restored MemoryOS database is deliberately not part of the backup, so session and
    attachment identifiers plus completion against that old index cannot stay current.
    """

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


def _clear_memoryos_derived_cache(root: Path) -> bool:
    """Remove only the fixed rebuildable MemoryOS directory without following links."""

    try:
        return clear_memoryos_derived_cache(root)
    except MemoryOSSupervisorError as exc:
        code = (
            "restore_memory_cache_unsafe"
            if exc.code == "memoryos_derived_cache_unsafe"
            else "restore_memory_cache_clear_failed"
        )
        raise DataError(
            code,
            "could not clear the rebuildable MemoryOS cache",
        ) from exc


def doctor_data(root: Path) -> tuple[int, dict[str, Any]]:
    runtime_root = root.expanduser().resolve()
    checks: list[dict[str, Any]] = []

    def add(name: str, status: str, detail: Any) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    journal = runtime_root / OPERATION_JOURNAL_NAME
    add("data_operation", "blocker" if journal.exists() else "ok", str(journal))
    db_path = runtime_root / CHAT_DB_NAME
    try:
        inspection = _inspect_database(db_path, require_current=False)
        contract = inspection["schema"]
        schema_status = (
            "ok"
            if contract["state"] == "current"
            else (
                "warning"
                if contract["state"] in {"marker_required", "migration_required"}
                else "blocker"
            )
        )
        add("chat_db_integrity", "ok", inspection["integrity"])
        add("chat_schema", schema_status, contract)
        if contract["compatible"] and inspection["invariants"] is not None:
            add("chat_authority_invariants", "ok", inspection["invariants"])
    except DataError as exc:
        add("chat_db", "blocker", {"code": exc.code, "message": str(exc)})
        inspection = None
    try:
        _payload, records, present = _read_sessions(runtime_root, lock=False)
        if inspection is not None and inspection["schema"]["compatible"]:
            _validate_session_references(db_path, records)
        add(
            "god_sessions",
            "ok" if present else "warning",
            {"source_present": present, "session_count": len(records)},
        )
    except DataError as exc:
        add("god_sessions", "blocker", {"code": exc.code, "message": str(exc)})
    if inspection is not None and inspection["schema"]["compatible"]:
        with _readonly_connection(db_path) as conn:
            recovery_state = {
                "claimed_observation_count": int(
                    conn.execute(
                        "select count(*) from room_observations where status = 'claimed'"
                    ).fetchone()[0]
                ),
                "pending_control_count": int(
                    conn.execute(
                        """select count(*) from room_observations
                           where control_state in ('cancel_requested','cancel_pending')"""
                    ).fetchone()[0]
                ),
                "unsafe_provider_cleanup_count": int(
                    conn.execute(
                        """select count(*) from room_observations o
                           join room_observation_attempts a
                             on a.attempt_id = o.current_attempt_id
                           where o.status <> 'completed' and a.provider_phase in
                             ('ensure_started','bound','cleanup_pending')"""
                    ).fetchone()[0]
                ),
            }
        add("runtime_recovery_state", "ok", recovery_state)
    try:
        runtime = _runtime_probe(runtime_root)
        managed = runtime["managed"]
        inventory = runtime["inventory"]
        if managed.get("state") == "error":
            add("workroom", "blocker", "Workroom state is unverifiable")
        else:
            running = bool(
                managed.get("manager_live")
                or inventory.get("services", [])
                or any(
                    isinstance(item, dict)
                    and item.get("service")
                    in {"runner", "mcp", "chat_api", "dashboard_api", "memoryos"}
                    for item in runtime.get("global_inventory", {}).get("services", [])
                )
                or any(
                    isinstance(item, dict) and item.get("live")
                    for item in managed.get("services", [])
                )
            )
            add(
                "workroom",
                "warning" if running else "ok",
                {"state": managed.get("state"), "running": running},
            )
    except (OSError, ValueError) as exc:
        add("workroom", "blocker", str(exc))
    blockers = [item for item in checks if item["status"] == "blocker"]
    warnings = [item for item in checks if item["status"] == "warning"]
    payload = {
        "schema_version": DOCTOR_SCHEMA,
        "state": "blocked" if blockers else ("degraded" if warnings else "healthy"),
        "root": str(runtime_root),
        "checks": checks,
        "blocker_count": len(blockers),
        "warning_count": len(warnings),
    }
    return (1 if blockers else 0), payload


def _runtime_probe(root: Path) -> dict[str, Any]:
    paths = workroom.WorkroomPaths.resolve(root, REPO_ROOT)
    _exit_code, managed = workroom.workroom_status(
        paths,
        workroom.WorkroomDependencies(repo_root=REPO_ROOT),
        emit=False,
    )
    inventory = discover_xmuse_runtime_processes(xmuse_root=root)
    # Direct default entrypoints can omit XMUSE_ROOT, so cwd-only scoping may
    # not attribute them to the repository's default authority directory.  A
    # destructive operation must fail closed for globally visible processes
    # that can open chat.db.  Standalone Codex transports are excluded because
    # they cannot write Room authority without MCP/Runner.
    global_inventory = discover_xmuse_runtime_processes()
    return {
        "managed": managed,
        "inventory": inventory,
        "global_inventory": global_inventory,
    }


def _assert_runtime_stopped(root: Path) -> None:
    probe = _runtime_probe(root)
    managed = probe["managed"]
    inventory = probe["inventory"]
    global_inventory = probe.get("global_inventory", {})
    if managed.get("state") == "error":
        raise DataError(
            "workroom_state_unverifiable",
            "Workroom manifest is invalid; runtime state cannot be verified",
        )
    live_services = [
        service
        for service in managed.get("services", [])
        if isinstance(service, dict) and service.get("live")
    ]
    discovered = inventory.get("services", []) if isinstance(inventory, dict) else []
    authority_services = {
        "execution_controller",
        "room_runner",
        "room_mcp",
        "runner",
        "mcp",
        "chat_api",
        "dashboard_api",
        "memoryos",
    }
    unscoped_authority = [
        service
        for service in (
            global_inventory.get("services", []) if isinstance(global_inventory, dict) else []
        )
        if isinstance(service, dict) and service.get("service") in authority_services
    ]
    if managed.get("manager_live") or live_services or discovered or unscoped_authority:
        pids = sorted(
            {
                int(pid)
                for service in [*live_services, *discovered, *unscoped_authority]
                if isinstance(service, dict)
                for pid in service.get("pids", [service.get("pid")])
                if isinstance(pid, int)
            }
        )
        raise DataError(
            "workroom_running",
            "restore and compact require a fully stopped Workroom",
            pids=pids,
        )


def _operation_journal(root: Path) -> Path:
    return root / OPERATION_JOURNAL_NAME


def _operation_directory(root: Path, prefix: str, operation_id: str) -> Path:
    return operation_directory(root, prefix, operation_id)


def _safe_operation_payload(root: Path, payload: dict[str, Any]) -> tuple[Path, Path]:
    try:
        paths = safe_operation_paths(
            root,
            payload,
            expected_schema=OPERATION_SCHEMA,
        )
    except DataMutationError as exc:
        raise DataError(exc.code, str(exc)) from exc
    return paths.staging, paths.rollback


def _remove_path(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)


def _finish_operation(root: Path, payload: dict[str, Any]) -> None:
    staging, rollback = _safe_operation_payload(root, payload)
    shutil.rmtree(staging, ignore_errors=True)
    shutil.rmtree(rollback, ignore_errors=True)
    _operation_journal(root).unlink(missing_ok=True)
    _fsync_dir(root)


def _rollback_operation(root: Path, payload: dict[str, Any]) -> None:
    staging, rollback = _safe_operation_payload(root, payload)
    phase = str(payload.get("phase") or "")
    if phase == "committed":
        _finish_operation(root, payload)
        return
    if phase not in {
        "prepared",
        "moving_old",
        "old_moved",
        "transport_fenced",
        "installed",
    }:
        raise DataError("data_operation_incomplete", f"unknown data operation phase: {phase}")
    if phase != "prepared":
        targets = payload.get("targets")
        if not isinstance(targets, list):
            raise DataError("data_operation_incomplete", "data operation targets are invalid")
        for target_record in targets:
            if not isinstance(target_record, dict):
                raise DataError("data_operation_incomplete", "data operation target is invalid")
            name = target_record.get("name")
            allowed_names = {
                CHAT_DB_NAME,
                SESSION_NAME,
                f"{CHAT_DB_NAME}-wal",
                f"{CHAT_DB_NAME}-shm",
            }
            if name not in allowed_names:
                raise DataError("data_operation_incomplete", "unsafe data operation target")
            target = root / name
            prior = rollback / name
            had_original = target_record.get("had_original") is True
            if prior.exists():
                _remove_path(target)
                os.replace(prior, target)
            elif not had_original:
                _remove_path(target)
            elif phase in {"old_moved", "transport_fenced", "installed"}:
                raise DataError(
                    "data_operation_incomplete",
                    f"rollback artifact is missing for {name}",
                )
    _finish_operation(root, payload)


def _recover_existing_operation(root: Path) -> str | None:
    journal = _operation_journal(root)
    if not journal.exists():
        return None
    payload = _read_json(journal, code="data_operation_incomplete")
    operation_id = str(payload.get("operation_id") or "")
    _rollback_operation(root, payload)
    return operation_id


def _new_operation(
    root: Path,
    *,
    kind: str,
    install_names: Sequence[str],
) -> tuple[dict[str, Any], Path, Path]:
    operation_id = f"{kind}-{uuid.uuid4().hex}"
    staging = _operation_directory(root, "xmuse-data-stage", operation_id)
    rollback = _operation_directory(root, "xmuse-data-rollback", operation_id)
    staging.mkdir()
    rollback.mkdir()
    target_names = list(
        dict.fromkeys([*install_names, f"{CHAT_DB_NAME}-wal", f"{CHAT_DB_NAME}-shm"])
    )
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
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    _write_json(_operation_journal(root), payload)
    return payload, staging, rollback


def _update_operation(root: Path, payload: dict[str, Any], phase: str) -> None:
    payload["phase"] = phase
    payload["updated_at"] = _utc_now()
    _write_json(_operation_journal(root), payload)


def _move_old_targets(root: Path, payload: dict[str, Any], rollback: Path) -> None:
    _update_operation(root, payload, "moving_old")
    for target_record in payload["targets"]:
        name = str(target_record["name"])
        target = root / name
        if target.exists():
            os.replace(target, rollback / name)
    _fsync_dir(root)
    _fsync_dir(rollback)
    _update_operation(root, payload, "old_moved")


def _commit_restore(
    root: Path,
    payload: dict[str, Any],
    staging: Path,
    rollback: Path,
) -> None:
    try:
        _move_old_targets(root, payload, rollback)
        empty = staging / ".empty-god-sessions.json"
        _write_json(empty, {"sessions": []})
        os.replace(empty, root / SESSION_NAME)
        _fsync_dir(root)
        _update_operation(root, payload, "transport_fenced")
        os.replace(staging / CHAT_DB_NAME, root / CHAT_DB_NAME)
        os.replace(staging / SESSION_NAME, root / SESSION_NAME)
        _fsync_dir(root)
        _update_operation(root, payload, "installed")
        _inspect_database(root / CHAT_DB_NAME, require_current=True)
        installed_sessions = _read_json(
            root / SESSION_NAME,
            code="restore_validation_failed",
        )
        records = _validate_sessions(installed_sessions)
        _validate_session_references(root / CHAT_DB_NAME, records)
        _update_operation(root, payload, "committed")
        _finish_operation(root, payload)
    except Exception as exc:
        try:
            current = _read_json(
                _operation_journal(root),
                code="data_operation_incomplete",
            )
            _rollback_operation(root, current)
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


def restore_data(root: Path, backup: Path, *, replace: bool) -> dict[str, Any]:
    manifest, backup_db, _session_payload, records = verify_backup(backup)
    runtime_root = root.expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    paths = workroom.WorkroomPaths.resolve(runtime_root, REPO_ROOT)
    with _file_lock(paths.lock):
        with _file_lock(runtime_root / DATA_LOCK_NAME):
            _assert_runtime_stopped(runtime_root)
            recovered_operation = _recover_existing_operation(runtime_root)
            _assert_runtime_stopped(runtime_root)
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
            payload, staging, rollback = _new_operation(
                runtime_root,
                kind="restore",
                install_names=(CHAT_DB_NAME, SESSION_NAME),
            )
            try:
                shutil.copy2(backup_db, staging / CHAT_DB_NAME)
                _verify_staged_database_copy(staging / CHAT_DB_NAME, manifest)
                sanitized = _sanitize_sessions(records)
                _write_json(staging / SESSION_NAME, sanitized)
                _validate_sessions(sanitized)
                _validate_session_references(staging / CHAT_DB_NAME, records)
                fence = RoomObservationControlStore(
                    staging / CHAT_DB_NAME,
                    initialize=False,
                ).fence_restored_runtime_generation(
                    operation_id=str(payload["operation_id"]),
                )
                execution_fence = _fence_restored_execution_runs(
                    staging / CHAT_DB_NAME,
                    operation_id=str(payload["operation_id"]),
                )
                memory_index_fence = _fence_restored_memory_index(
                    staging / CHAT_DB_NAME,
                    operation_id=str(payload["operation_id"]),
                )
                _inspect_database(staging / CHAT_DB_NAME, require_current=True)
                _fsync_file(staging / CHAT_DB_NAME)
                _fsync_file(staging / SESSION_NAME)
                _fsync_dir(staging)
                memory_cache_cleared = _clear_memoryos_derived_cache(runtime_root)
                with _file_lock(
                    runtime_root / f"{SESSION_NAME}.lock",
                    exclusive=True,
                ):
                    _commit_restore(runtime_root, payload, staging, rollback)
            except Exception:
                if _operation_journal(runtime_root).exists():
                    current = _read_json(
                        _operation_journal(runtime_root),
                        code="data_operation_incomplete",
                    )
                    _rollback_operation(runtime_root, current)
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


def _sqlite_value(value: Any) -> Any:
    return sqlite_value(value)


def _table_order_fingerprints(path: Path) -> dict[str, str]:
    try:
        return table_order_fingerprints(path)
    except DataInspectionError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _vacuum_into(source: Path, destination: Path) -> None:
    try:
        vacuum_into(source, destination)
    except DataMutationError as exc:
        raise DataError(exc.code, str(exc)) from exc


def _commit_compact(
    root: Path,
    payload: dict[str, Any],
    staging: Path,
    rollback: Path,
) -> None:
    try:
        _move_old_targets(root, payload, rollback)
        os.replace(staging / CHAT_DB_NAME, root / CHAT_DB_NAME)
        _fsync_dir(root)
        _update_operation(root, payload, "installed")
        _inspect_database(root / CHAT_DB_NAME, require_current=True)
        _update_operation(root, payload, "committed")
        _finish_operation(root, payload)
    except Exception as exc:
        try:
            current = _read_json(
                _operation_journal(root),
                code="data_operation_incomplete",
            )
            _rollback_operation(root, current)
        except Exception as rollback_error:
            raise DataError(
                "data_operation_incomplete",
                "compact failed and automatic rollback was incomplete",
            ) from rollback_error
        if isinstance(exc, DataError):
            raise
        raise DataError("compact_failed", "compact commit failed") from exc


def compact_data(root: Path) -> dict[str, Any]:
    runtime_root = root.expanduser().resolve()
    runtime_root.mkdir(parents=True, exist_ok=True)
    paths = workroom.WorkroomPaths.resolve(runtime_root, REPO_ROOT)
    with _file_lock(paths.lock):
        with _file_lock(runtime_root / DATA_LOCK_NAME):
            _assert_runtime_stopped(runtime_root)
            recovered_operation = _recover_existing_operation(runtime_root)
            _assert_runtime_stopped(runtime_root)
            source = runtime_root / CHAT_DB_NAME
            _inspect_database(source, require_current=True)
            before_size = source.stat().st_size
            before_evidence = _database_evidence(source)
            before_order = _table_order_fingerprints(source)
            payload, staging, rollback = _new_operation(
                runtime_root,
                kind="compact",
                install_names=(CHAT_DB_NAME,),
            )
            try:
                compacted = staging / CHAT_DB_NAME
                _vacuum_into(source, compacted)
                _normalize_artifact_database(compacted)
                _inspect_database(compacted, require_current=True)
                after_evidence = _database_evidence(compacted)
                after_order = _table_order_fingerprints(compacted)
                if before_evidence != after_evidence or before_order != after_order:
                    raise DataError(
                        "compact_failed",
                        "compacted database changed authority content or row order",
                    )
                _fsync_file(compacted)
                _fsync_dir(staging)
                after_size = compacted.stat().st_size
                _commit_compact(runtime_root, payload, staging, rollback)
            except Exception:
                if _operation_journal(runtime_root).exists():
                    current = _read_json(
                        _operation_journal(runtime_root),
                        code="data_operation_incomplete",
                    )
                    _rollback_operation(runtime_root, current)
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
