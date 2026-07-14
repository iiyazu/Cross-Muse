"""Explicit SQLite boundary for the default Room product.

The default Room runtime owns a deliberately small, versioned schema.  Compatibility
applications may add their historical tables later, but ordinary Room stores never run
schema DDL and read models never open a writable connection.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_codex_schema import create_room_codex_schema
from xmuse_core.chat.room_execution_schema import create_room_execution_schema
from xmuse_core.chat.room_kernel_schema import create_room_kernel_schema
from xmuse_core.chat.room_memory_schema import create_room_memory_schema
from xmuse_core.chat.room_operations_schema import create_room_operations_schema
from xmuse_core.runtime.data_guard import assert_data_operation_complete

ROOM_SCHEMA_ID = "xmuse.room_db"
ROOM_SCHEMA_VERSION = 1
COMPAT_CHAT_SCHEMA_ID = "xmuse.chat_db"
COMPAT_CHAT_SCHEMA_VERSION = 1

FRONTEND_EVENT_PROOF_BOUNDARY = "frontend_event_not_authority"


class RoomDatabaseError(RuntimeError):
    """Stable failure raised by the explicit Room database boundary."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _configure_connection(conn: sqlite3.Connection, *, readonly: bool) -> None:
    conn.row_factory = sqlite3.Row
    conn.execute("pragma busy_timeout = 30000")
    conn.execute("pragma foreign_keys = on")
    if readonly:
        conn.execute("pragma query_only = on")


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    escaped = table.replace('"', '""')
    return {str(row[1]) for row in conn.execute(f'pragma table_info("{escaped}")')}


def _unique_keys(conn: sqlite3.Connection, table: str) -> set[tuple[str, ...]]:
    escaped = table.replace('"', '""')
    result: set[tuple[str, ...]] = set()
    for index in conn.execute(f'pragma index_list("{escaped}")'):
        if not bool(index[2]):
            continue
        name = str(index[1]).replace('"', '""')
        result.add(tuple(str(row[2]) for row in conn.execute(f'pragma index_info("{name}")')))
    primary = sorted(
        (int(row[5]), str(row[1]))
        for row in conn.execute(f'pragma table_info("{escaped}")')
        if int(row[5]) > 0
    )
    if primary:
        result.add(tuple(name for _position, name in primary))
    return result


ROOM_REQUIRED_COLUMNS: Mapping[str, frozenset[str]] = {
    "chat_schema_meta": frozenset({"schema_id", "version", "updated_at"}),
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
            "persona_snapshot_json",
            "persona_snapshot_sha256",
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
    "room_setup_requests": frozenset(
        {
            "client_request_id",
            "request_fingerprint",
            "conversation_id",
            "result_json",
            "created_at",
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
    "room_participant_cursors": frozenset(
        {
            "conversation_id",
            "participant_id",
            "last_acknowledged_seq",
            "last_observation_id",
            "updated_at",
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
            "runner_generation",
            "runner_boot_id",
            "recovery_state",
            "recovery_reason_code",
            "recovery_started_at",
            "recovery_completed_at",
            "claimed_at",
            "expires_at",
            "transport_started_at",
            "finished_at",
            "created_at",
            "updated_at",
            "batch_id",
        }
    ),
    "room_observation_batches": frozenset(
        {
            "batch_id",
            "conversation_id",
            "participant_id",
            "correlation_id",
            "phase",
            "primary_observation_id",
            "cutoff_seq",
            "member_count",
            "digest",
            "created_at",
        }
    ),
    "room_observation_batch_members": frozenset(
        {"batch_id", "observation_id", "ordinal", "activity_id", "activity_seq"}
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
    "room_execution_policies": frozenset(
        {"conversation_id", "mode", "revision", "risk_policy_revision", "created_at", "updated_at"}
    ),
    "room_execution_candidates": frozenset(
        {
            "candidate_id",
            "proposal_id",
            "conversation_id",
            "author_participant_id",
            "author_identity_fingerprint",
            "source_observation_id",
            "source_batch_id",
            "source_attempt_id",
            "source_activity_id",
            "source_correlation_id",
            "base_head",
            "summary",
            "unified_diff",
            "allowed_files_json",
            "files_json",
            "candidate_digest",
            "patch_sha256",
            "review_material_digest",
            "patch_bytes",
            "file_count",
            "modify_only",
            "context_fit_eligible",
            "direct_human_root",
            "peer_snapshot_digest",
            "policy_mode_snapshot",
            "policy_revision_snapshot",
            "risk_policy_revision_snapshot",
            "state",
            "consensus_state",
            "revision",
            "reason_code",
            "created_at",
            "updated_at",
            "authorized_at",
            "rejected_at",
        }
    ),
    "room_execution_candidate_members": frozenset(
        {
            "candidate_id",
            "participant_id",
            "identity_fingerprint",
            "ordinal",
            "status_snapshot",
            "review_attempt_id",
            "review_batch_id",
            "review_activity_id",
            "review_material_digest",
            "review_context_payload_sha256",
            "full_material_available",
            "review_bound_at",
        }
    ),
    "room_execution_assessments": frozenset(
        {
            "assessment_id",
            "candidate_id",
            "assessor_participant_id",
            "assessor_identity_fingerprint",
            "assessment",
            "rationale",
            "candidate_digest",
            "review_material_digest",
            "source_attempt_id",
            "source_batch_id",
            "source_activity_id",
            "created_at",
        }
    ),
    "room_execution_operator_actions": frozenset(
        {
            "action_id",
            "conversation_id",
            "candidate_id",
            "run_id",
            "action_type",
            "client_action_id",
            "operator_identity",
            "request_fingerprint",
            "expected_candidate_digest",
            "expected_candidate_revision",
            "expected_policy_revision",
            "expected_run_state",
            "expected_run_revision",
            "status",
            "result_json",
            "reason_code",
            "requested_at",
            "applied_at",
            "updated_at",
        }
    ),
    "room_execution_authorizations": frozenset(
        {
            "authorization_id",
            "candidate_id",
            "conversation_id",
            "authorization_mode",
            "candidate_digest",
            "candidate_revision",
            "policy_revision",
            "risk_policy_revision",
            "peer_snapshot_digest",
            "workspace_guard_digest",
            "risk_evidence_digest",
            "status",
            "reason_code",
            "created_at",
            "consumed_at",
            "invalidated_at",
        }
    ),
    "room_execution_runs": frozenset(
        {
            "run_id",
            "authorization_id",
            "candidate_id",
            "conversation_id",
            "state",
            "revision",
            "control_seq",
            "execution_generation",
            "controller_id",
            "controller_generation",
            "controller_pid",
            "controller_start_identity",
            "reason_code",
            "changed_files_json",
            "gate_ids_json",
            "evidence_digest",
            "requested_at",
            "started_at",
            "finished_at",
            "updated_at",
        }
    ),
    "room_execution_gate_plan_bindings": frozenset(
        {
            "binding_id",
            "authorization_id",
            "run_id",
            "schema_version",
            "profile_id",
            "profile_revision",
            "profile_digest",
            "gate_ids_json",
            "repository_manifest_digest",
            "toolchain_capability_digest",
            "gate_plan_digest",
            "created_at",
        }
    ),
    "room_execution_gate_evidence": frozenset(
        {
            "evidence_id",
            "run_id",
            "execution_generation",
            "gate_id",
            "status",
            "evidence_digest",
            "reason_code",
            "started_at",
            "finished_at",
            "created_at",
            "updated_at",
        }
    ),
    "room_execution_promotion_journal": frozenset(
        {
            "journal_id",
            "run_id",
            "execution_generation",
            "target_head",
            "pre_manifest_digest",
            "post_manifest_digest",
            "file_entries_json",
            "status",
            "observed_manifest_digest",
            "prepared_at",
            "applied_at",
            "updated_at",
        }
    ),
    "room_memory_bindings": frozenset(
        {
            "binding_id",
            "conversation_id",
            "scope_type",
            "scope_key",
            "archive_id",
            "session_id",
            "session_state",
            "session_request_id",
            "session_retry_count",
            "session_retry_not_before",
            "attachment_id",
            "attachment_state",
            "attachment_request_id",
            "attachment_retry_count",
            "attachment_retry_not_before",
            "revision",
            "created_at",
            "updated_at",
        }
    ),
    "room_memory_candidates": frozenset(
        {
            "candidate_id",
            "conversation_id",
            "author_participant_id",
            "source_observation_id",
            "source_batch_id",
            "source_attempt_id",
            "kind",
            "content",
            "content_sha256",
            "source_activity_ids_json",
            "candidate_digest",
            "approval_state",
            "approval_mode",
            "publish_state",
            "target_scope",
            "revision",
            "reason_code",
            "resolved_by",
            "resolution_client_action_id",
            "resolution_request_fingerprint",
            "created_at",
            "resolved_at",
            "updated_at",
        }
    ),
    "room_memory_candidate_actions": frozenset(
        {
            "action_id",
            "candidate_id",
            "conversation_id",
            "client_action_id",
            "operator_identity",
            "request_fingerprint",
            "decision",
            "status",
            "reason_code",
            "result_json",
            "created_at",
        }
    ),
    "room_memory_outbox": frozenset(
        {
            "outbox_id",
            "conversation_id",
            "activity_id",
            "candidate_id",
            "document_id",
            "target_scope",
            "state",
            "attempt_count",
            "lease_owner",
            "lease_token",
            "acquired_at",
            "expires_at",
            "current_delivery_id",
            "reason_code",
            "next_attempt_at",
            "created_at",
            "updated_at",
            "delivered_at",
        }
    ),
    "room_memory_deliveries": frozenset(
        {
            "delivery_id",
            "outbox_id",
            "attempt_number",
            "worker_id",
            "lease_token_sha256",
            "state",
            "request_digest",
            "response_digest",
            "reason_code",
            "claimed_at",
            "finished_at",
            "updated_at",
        }
    ),
    "room_memory_attempt_receipts": frozenset(
        {
            "receipt_id",
            "attempt_id",
            "conversation_id",
            "participant_id",
            "correlation_id",
            "status",
            "schema_version",
            "latency_ms",
            "item_count",
            "item_refs_json",
            "source_activity_ids_json",
            "evidence_sha256",
            "context_payload_sha256",
            "context_submitted_at",
            "request_fingerprint",
            "created_at",
            "updated_at",
        }
    ),
    "room_memory_rebuild_actions": frozenset(
        {
            "action_id",
            "client_action_id",
            "operator_identity",
            "request_fingerprint",
            "incident_guard",
            "runtime_generation",
            "status",
            "phase",
            "revision",
            "before_state",
            "before_code",
            "after_state",
            "after_code",
            "reason_code",
            "result_json",
            "requested_at",
            "applied_at",
            "updated_at",
        }
    ),
    "room_runtime_operator_actions": frozenset(
        {
            "action_id",
            "client_action_id",
            "operator_identity",
            "request_fingerprint",
            "incident_guard",
            "status",
            "before_state",
            "before_code",
            "after_state",
            "after_code",
            "result_json",
            "reason_code",
            "requested_at",
            "applied_at",
            "updated_at",
        }
    ),
    "room_runtime_restore_fences": frozenset({"operation_id", "result_json", "applied_at"}),
    "room_codex_delivery_holds": frozenset(
        {
            "participant_id",
            "conversation_id",
            "hold_revision",
            "next_control_seq",
            "state",
            "session_guard",
            "goal_guard",
            "settings_guard",
            "active_turn_guard",
            "reason_code",
            "observed_at",
            "created_at",
            "updated_at",
        }
    ),
    "room_codex_bridge_actions": frozenset(
        {
            "action_id",
            "conversation_id",
            "participant_id",
            "control_seq",
            "client_action_id",
            "operator_identity",
            "request_fingerprint",
            "capability_id",
            "expected_session_guard",
            "expected_goal_guard",
            "expected_settings_guard",
            "expected_turn_guard",
            "request_json",
            "status",
            "execution_stage",
            "failure_stage",
            "reason_code",
            "ack_summary_json",
            "runner_generation",
            "requested_at",
            "applying_at",
            "completed_at",
            "updated_at",
        }
    ),
}

ROOM_REQUIRED_UNIQUE_KEYS = frozenset(
    {
        ("room_activities", ("conversation_id", "seq")),
        ("room_observations", ("activity_id", "participant_id")),
        ("room_observation_attempts", ("observation_id", "attempt_number")),
        ("room_observation_attempts", ("observation_id", "delivery_generation")),
        ("room_observation_batches", ("primary_observation_id",)),
        ("room_observation_batch_members", ("observation_id",)),
        ("room_observation_batch_members", ("batch_id", "ordinal")),
        ("room_execution_candidates", ("proposal_id",)),
        ("room_execution_candidates", ("source_activity_id",)),
        ("room_execution_candidate_members", ("candidate_id", "participant_id")),
        ("room_execution_candidate_members", ("candidate_id", "ordinal")),
        ("room_execution_assessments", ("candidate_id", "assessor_participant_id")),
        ("room_execution_operator_actions", ("operator_identity", "client_action_id")),
        ("room_execution_authorizations", ("candidate_id",)),
        ("room_execution_runs", ("authorization_id",)),
        ("room_execution_runs", ("candidate_id",)),
        ("room_execution_gate_plan_bindings", ("authorization_id",)),
        ("room_execution_gate_plan_bindings", ("run_id",)),
        ("room_execution_gate_evidence", ("run_id", "execution_generation", "gate_id")),
        ("room_execution_promotion_journal", ("run_id",)),
        ("room_memory_bindings", ("conversation_id", "scope_type")),
        ("room_memory_candidates", ("resolution_client_action_id",)),
        ("room_memory_candidate_actions", ("operator_identity", "client_action_id")),
        ("room_memory_outbox", ("activity_id",)),
        ("room_memory_outbox", ("candidate_id",)),
        ("room_memory_outbox", ("document_id",)),
        ("room_memory_deliveries", ("outbox_id", "attempt_number")),
        ("room_memory_attempt_receipts", ("attempt_id",)),
        ("room_memory_rebuild_actions", ("client_action_id",)),
        (
            "room_observation_controls",
            ("observation_id", "operator_identity", "client_action_id"),
        ),
        ("chat_frontend_events", ("conversation_id", "seq")),
        (
            "room_codex_bridge_actions",
            ("participant_id", "operator_identity", "client_action_id"),
        ),
        ("room_codex_bridge_actions", ("participant_id", "control_seq")),
    }
)


def _execute_many(conn: sqlite3.Connection, statements: tuple[str, ...]) -> None:
    for statement in statements:
        conn.execute(statement)


def _create_room_core_schema_conn(conn: sqlite3.Connection) -> None:
    _execute_many(
        conn,
        (
            """create table if not exists chat_schema_meta (
                   schema_id text primary key,
                   version integer not null,
                   updated_at text not null
               )""",
            """create table if not exists conversations (
                   id text primary key,
                   title text not null,
                   created_at text not null
               )""",
            """create table if not exists messages (
                   id text primary key,
                   conversation_id text not null references conversations(id),
                   author text not null,
                   role text not null,
                   content text not null,
                   created_at text not null,
                   envelope_type text,
                   envelope_json text,
                   mentions_json text,
                   reply_to_message_id text
               )""",
            """create table if not exists proposals (
                   id text primary key,
                   conversation_id text not null references conversations(id),
                   author text not null,
                   proposal_type text not null,
                   content text not null,
                   references_json text not null,
                   status text not null,
                   created_at text not null,
                   accepted_resolution_id text
               )""",
            """create table if not exists participants (
                   participant_id text primary key,
                   conversation_id text not null references conversations(id),
                   role text not null,
                   display_name text not null,
                   cli_kind text not null,
                   model text not null,
                   role_template_id text,
                   status text not null,
                   last_seen_at text,
                   persona_snapshot_json text,
                   persona_snapshot_sha256 text,
                   created_at text not null
               )""",
            """create table if not exists chat_request_log (
                   id text primary key,
                   conversation_id text not null references conversations(id),
                   tool_name text not null,
                   caller_identity text not null,
                   client_request_id text not null,
                   result_json text not null,
                   created_at text not null,
                   unique(conversation_id, tool_name, caller_identity, client_request_id)
               )""",
            """create table if not exists chat_frontend_events (
                   event_id text primary key,
                   conversation_id text not null references conversations(id),
                   seq integer not null,
                   event_type text not null,
                   resource_ref text not null,
                   source_authority text not null,
                   source_ref text not null,
                   payload_json text not null,
                   client_action_id text,
                   created_at text not null,
                   projection_only integer not null default 1,
                   proof_boundary text not null,
                   unique(conversation_id, seq)
               )""",
            """create index if not exists idx_chat_frontend_events_conversation_seq
                   on chat_frontend_events(conversation_id, seq)""",
            """create table if not exists room_setup_requests (
                   client_request_id text primary key,
                   request_fingerprint text not null,
                   conversation_id text not null references conversations(id),
                   result_json text not null,
                   created_at text not null
               )""",
        ),
    )
    message_columns = _table_columns(conn, "messages")
    for name, definition in (
        ("envelope_type", "text"),
        ("envelope_json", "text"),
        ("mentions_json", "text"),
        ("reply_to_message_id", "text"),
    ):
        if name not in message_columns:
            conn.execute(f"alter table messages add column {name} {definition}")
    participant_columns = _table_columns(conn, "participants")
    for name in ("persona_snapshot_json", "persona_snapshot_sha256"):
        if name not in participant_columns:
            conn.execute(f"alter table participants add column {name} text")


def _marker_version(conn: sqlite3.Connection, schema_id: str) -> int | None:
    row = conn.execute(
        "select version from chat_schema_meta where schema_id = ?", (schema_id,)
    ).fetchone()
    if row is None:
        return None
    try:
        return int(row[0])
    except (TypeError, ValueError) as exc:
        raise RoomDatabaseError("room_schema_marker_invalid") from exc


def _assert_marker_compatible(
    conn: sqlite3.Connection,
    *,
    schema_id: str,
    supported_version: int,
) -> None:
    version = _marker_version(conn, schema_id)
    if version is None:
        return
    if version > supported_version:
        if schema_id == COMPAT_CHAT_SCHEMA_ID:
            raise RoomDatabaseError(
                f"chat_schema_version_unsupported:{version}>{supported_version}"
            )
        raise RoomDatabaseError("room_schema_version_unsupported")
    if version < supported_version:
        if schema_id == COMPAT_CHAT_SCHEMA_ID:
            raise RoomDatabaseError(
                f"chat_schema_migration_required:{version}->{supported_version}"
            )
        raise RoomDatabaseError("room_schema_migration_required")


def _validate_room_schema(conn: sqlite3.Connection) -> None:
    tables = {
        str(row[0])
        for row in conn.execute(
            "select name from sqlite_schema where type = 'table' and name not like 'sqlite_%'"
        )
    }
    missing_tables = set(ROOM_REQUIRED_COLUMNS) - tables
    if missing_tables:
        raise RoomDatabaseError("room_schema_incomplete")
    for table, required in ROOM_REQUIRED_COLUMNS.items():
        if required - _table_columns(conn, table):
            raise RoomDatabaseError("room_schema_incomplete")
    for table, columns in ROOM_REQUIRED_UNIQUE_KEYS:
        if columns not in _unique_keys(conn, table):
            raise RoomDatabaseError("room_schema_unique_constraint_missing")


def initialize_room_schema_conn(conn: sqlite3.Connection) -> None:
    """Apply the additive Room v1 schema inside the caller-owned transaction."""

    if not conn.in_transaction:
        raise RoomDatabaseError("room_schema_transaction_required")
    conn.execute(
        """create table if not exists chat_schema_meta (
               schema_id text primary key,
               version integer not null,
               updated_at text not null
           )"""
    )
    _assert_marker_compatible(
        conn,
        schema_id=ROOM_SCHEMA_ID,
        supported_version=ROOM_SCHEMA_VERSION,
    )
    _assert_marker_compatible(
        conn,
        schema_id=COMPAT_CHAT_SCHEMA_ID,
        supported_version=COMPAT_CHAT_SCHEMA_VERSION,
    )
    _create_room_core_schema_conn(conn)

    create_room_kernel_schema(conn)
    create_room_execution_schema(conn)
    create_room_memory_schema(conn)
    create_room_operations_schema(conn)
    create_room_codex_schema(conn)
    _validate_room_schema(conn)
    conn.execute(
        """insert into chat_schema_meta(schema_id, version, updated_at)
           values (?, ?, ?)
           on conflict(schema_id) do nothing""",
        (ROOM_SCHEMA_ID, ROOM_SCHEMA_VERSION, _utc_now()),
    )


class RoomDatabase:
    """Explicit initializer and connection factory for one local Room database."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def initialize(self) -> None:
        assert_data_operation_complete(self.path.parent)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.is_symlink():
            raise RoomDatabaseError("room_database_symlink_rejected")
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        _configure_connection(conn, readonly=False)
        try:
            conn.execute("begin immediate")
            initialize_room_schema_conn(conn)
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        finally:
            conn.close()

    def connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        if not self.path.is_file():
            raise RoomDatabaseError("room_database_missing")
        if self.path.is_symlink():
            raise RoomDatabaseError("room_database_symlink_rejected")
        conn: sqlite3.Connection | None = None
        try:
            if readonly:
                conn = sqlite3.connect(
                    f"{self.path.resolve().as_uri()}?mode=ro",
                    uri=True,
                    timeout=30,
                )
            else:
                conn = sqlite3.connect(self.path, timeout=30)
            _configure_connection(conn, readonly=readonly)
            return conn
        except sqlite3.Error as exc:
            if conn is not None:
                conn.close()
            raise RoomDatabaseError("room_database_unavailable") from exc


class RoomEventReadStore:
    """Bounded read-only access to Room projection invalidations."""

    def __init__(self, path: Path | str) -> None:
        self._database = RoomDatabase(path)

    def conversation_exists(self, conversation_id: str) -> bool:
        with self._database.connect(readonly=True) as conn:
            return (
                conn.execute(
                    "select 1 from conversations where id = ? limit 1",
                    (conversation_id,),
                ).fetchone()
                is not None
            )

    def latest_frontend_event_seq(self, conversation_id: str) -> int:
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                "select coalesce(max(seq), 0) latest_seq "
                "from chat_frontend_events where conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row["latest_seq"]) if row is not None else 0

    def list_frontend_events(
        self,
        conversation_id: str,
        *,
        after_seq: int = 0,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 500))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from chat_frontend_events
                   where conversation_id = ? and seq > ?
                   order by seq asc limit ?""",
                (conversation_id, int(after_seq), clean_limit),
            ).fetchall()
        return [self._event_from_row(row) for row in rows]

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(row)
        return {
            "schema_version": "chat_frontend_event/v1",
            "event_id": payload["event_id"],
            "sequence": payload["seq"],
            "conversation_id": payload["conversation_id"],
            "event_type": payload["event_type"],
            "resource_ref": payload["resource_ref"],
            "source_authority": payload["source_authority"],
            "source_ref": payload["source_ref"],
            "payload": json.loads(payload["payload_json"]),
            "client_action_id": payload.get("client_action_id"),
            "created_at": payload["created_at"],
            "projection_only": bool(payload["projection_only"]),
            "proof_boundary": payload["proof_boundary"],
        }


__all__ = [
    "COMPAT_CHAT_SCHEMA_ID",
    "COMPAT_CHAT_SCHEMA_VERSION",
    "FRONTEND_EVENT_PROOF_BOUNDARY",
    "ROOM_REQUIRED_COLUMNS",
    "ROOM_REQUIRED_UNIQUE_KEYS",
    "ROOM_SCHEMA_ID",
    "ROOM_SCHEMA_VERSION",
    "RoomDatabase",
    "RoomDatabaseError",
    "RoomEventReadStore",
    "initialize_room_schema_conn",
]
