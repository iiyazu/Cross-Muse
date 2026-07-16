"""Read-only schema, authority, and session validation for xmuse data."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

from xmuse.data_contracts import (
    CHAT_SCHEMA_CONTRACT,
    ROOM_SCHEMA_CONTRACT,
    SESSION_NAME,
    DataError,
)
from xmuse.data_inspection import (
    DataInspectionError,
    canonical_bytes,
    readonly_connection,
    sha256_bytes,
    table_columns,
    unique_keys,
)
from xmuse_core.agents.god_session_registry import GodSessionRecord
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
from xmuse_core.runtime.root_contract import file_lock

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


def _canonical_bytes(value: Any) -> bytes:
    return canonical_bytes(value)


def _sha256_bytes(value: bytes) -> str:
    return sha256_bytes(value)


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


def schema_contract(conn: sqlite3.Connection) -> dict[str, Any]:
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


def authority_invariants(conn: sqlite3.Connection) -> dict[str, Any]:
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


def inspect_database(path: Path, *, require_current: bool) -> dict[str, Any]:
    with _readonly_connection(path) as conn:
        integrity = _integrity_report(conn)
        if integrity["integrity"] != "ok" or integrity["foreign_key_violation_count"]:
            raise DataError("chat_db_corrupt", "chat database integrity validation failed")
        contract = schema_contract(conn)
        if require_current and not contract["compatible"]:
            raise DataError(
                "backup_schema_unsupported",
                f"chat schema is not supported: {contract['state']}",
                schema=contract,
            )
        invariants = authority_invariants(conn) if contract["compatible"] else None
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


def database_evidence(path: Path) -> dict[str, Any]:
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


def validate_sessions(payload: dict[str, Any]) -> list[GodSessionRecord]:
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


def read_sessions(
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
    return payload, validate_sessions(payload), True


def validate_session_references(
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


def sanitize_sessions(records: Sequence[GodSessionRecord]) -> dict[str, Any]:
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


__all__ = [
    "authority_invariants",
    "database_evidence",
    "inspect_database",
    "read_sessions",
    "sanitize_sessions",
    "schema_contract",
    "validate_session_references",
    "validate_sessions",
]
