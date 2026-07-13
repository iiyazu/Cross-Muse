"""Pure SQLite schema and additive migrations for Room delivery controls."""

from __future__ import annotations

import sqlite3

from xmuse_core.chat.room_skill_schema import create_room_skill_decision_schema


class RoomControlError(ValueError):
    """Stable failure shared by Room control schema and authority operations."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if cleaned := statement.strip():
            conn.execute(cleaned)


def create_room_restore_fence_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """create table if not exists room_runtime_restore_fences (
               operation_id text primary key,
               result_json text not null,
               applied_at text not null
           )"""
    )


def create_room_control_schema(conn: sqlite3.Connection) -> None:
    """Create the attempt/control schema in the caller transaction."""

    if (
        conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = 'room_observations'"
        ).fetchone()
        is None
    ):
        raise RoomControlError("room_observations_schema_required")
    columns = {row[1] for row in conn.execute("pragma table_info(room_observations)")}
    additions = (
        (
            "control_state",
            "text not null default 'active' check (control_state in "
            "('active','cancel_requested','cancel_pending','cancelled','exhausted'))",
        ),
        ("control_seq", "integer not null default 0 check (control_seq >= 0)"),
        (
            "manual_retry_budget",
            "integer not null default 0 check (manual_retry_budget >= 0)",
        ),
        ("current_attempt_id", "text"),
    )
    for name, definition in additions:
        if name not in columns:
            conn.execute(f"alter table room_observations add column {name} {definition}")
    _execute_schema(
        conn,
        """
        create table if not exists room_observation_attempts (
            attempt_id text primary key,
            batch_id text references room_observation_batches(batch_id),
            conversation_id text not null references conversations(id),
            observation_id text not null references room_observations(observation_id),
            participant_id text not null references participants(participant_id),
            attempt_number integer not null check (attempt_number > 0),
            effective_attempt_limit integer not null check (effective_attempt_limit > 0),
            delivery_generation integer not null check (delivery_generation > 0),
            state text not null check (state in (
                'claimed','delivering','completed','failed','expired',
                'cancel_requested','cancel_pending','cancelled'
            )),
            reason_code text,
            lease_owner text not null,
            lease_token_digest text not null,
            delivery_task_id text,
            god_session_id text,
            provider_session_id text,
            provider_session_generation text,
            provider_phase text not null default 'not_started' check (provider_phase in (
                'not_started','ensure_started','bound','cleanup_pending','cleanup_succeeded'
            )),
            provider_cleanup_reason text,
            provider_phase_updated_at text,
            runner_generation text,
            runner_boot_id text,
            recovery_state text not null default 'none' check (recovery_state in (
                'none','fenced','cleanup_pending','recovered'
            )),
            recovery_reason_code text,
            recovery_started_at text,
            recovery_completed_at text,
            claimed_at text not null,
            expires_at text not null,
            transport_started_at text,
            finished_at text,
            created_at text not null,
            updated_at text not null,
            unique(observation_id, attempt_number),
            unique(observation_id, delivery_generation)
        );

        create index if not exists idx_room_attempts_observation_state
            on room_observation_attempts(observation_id, state, attempt_number);
        create index if not exists idx_room_attempts_delivery_binding
            on room_observation_attempts(delivery_task_id, provider_session_generation);

        create table if not exists room_observation_controls (
            control_id text primary key,
            conversation_id text not null references conversations(id),
            observation_id text not null references room_observations(observation_id),
            participant_id text not null references participants(participant_id),
            action text not null check (action in ('cancel','retry')),
            client_action_id text not null,
            operator_identity text not null,
            request_fingerprint text not null,
            expected_state text not null,
            expected_attempt_count integer not null,
            expected_control_seq integer not null,
            resulting_state text not null,
            resulting_control_seq integer not null,
            attempt_id text references room_observation_attempts(attempt_id),
            status text not null check (status in ('requested','applied','rejected')),
            reason_code text,
            frontend_event_seq integer,
            requested_at text not null,
            applied_at text,
            updated_at text not null,
            unique(observation_id, operator_identity, client_action_id)
        );

        create index if not exists idx_room_controls_reconcile
            on room_observation_controls(action, status, observation_id, requested_at);
        """,
    )
    create_room_restore_fence_schema(conn)
    control_columns = {
        row[1] for row in conn.execute("pragma table_info(room_observation_controls)")
    }
    if "frontend_event_seq" not in control_columns:
        conn.execute("alter table room_observation_controls add column frontend_event_seq integer")
    attempt_columns = {
        row[1] for row in conn.execute("pragma table_info(room_observation_attempts)")
    }
    provider_phase_added = "provider_phase" not in attempt_columns
    if "batch_id" not in attempt_columns:
        conn.execute(
            "alter table room_observation_attempts add column batch_id text "
            "references room_observation_batches(batch_id)"
        )
    if "god_session_id" not in attempt_columns:
        conn.execute("alter table room_observation_attempts add column god_session_id text")
    for name, definition in (
        ("provider_phase", "text not null default 'not_started'"),
        ("provider_cleanup_reason", "text"),
        ("provider_phase_updated_at", "text"),
        ("runner_generation", "text"),
        ("runner_boot_id", "text"),
        (
            "recovery_state",
            "text not null default 'none' check (recovery_state in "
            "('none','fenced','cleanup_pending','recovered'))",
        ),
        ("recovery_reason_code", "text"),
        ("recovery_started_at", "text"),
        ("recovery_completed_at", "text"),
    ):
        if name not in attempt_columns:
            conn.execute(f"alter table room_observation_attempts add column {name} {definition}")
    conn.execute(
        "create index if not exists idx_room_attempts_runner_recovery "
        "on room_observation_attempts(runner_boot_id, recovery_state, observation_id)"
    )
    conn.execute(
        "create index if not exists idx_room_attempts_batch "
        "on room_observation_attempts(batch_id, attempt_number)"
    )
    if provider_phase_added:
        conn.execute(
            """update room_observation_attempts set provider_phase = 'bound',
            provider_phase_updated_at = coalesce(provider_phase_updated_at, updated_at)
            where provider_phase = 'not_started'
              and god_session_id is not null and provider_session_id is not null"""
        )
        conn.execute(
            """update room_observation_attempts set provider_phase = 'ensure_started',
            provider_cleanup_reason = coalesce(
                provider_cleanup_reason, 'migration_delivery_generation_unproven'
            ), provider_phase_updated_at = coalesce(provider_phase_updated_at, updated_at)
            where provider_phase = 'not_started' and state = 'delivering'
              and delivery_task_id is not null and provider_session_generation is not null"""
        )
    create_room_skill_decision_schema(conn)
