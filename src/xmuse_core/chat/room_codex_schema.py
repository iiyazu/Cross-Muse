"""SQLite authority for the narrow Room-to-Codex native bridge."""

from __future__ import annotations

import sqlite3


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if cleaned := statement.strip():
            conn.execute(cleaned)


def create_room_codex_schema(conn: sqlite3.Connection) -> None:
    """Create bridge actions and conservative participant delivery holds."""

    _execute_schema(
        conn,
        """
        create table if not exists room_codex_delivery_holds (
            participant_id text primary key references participants(participant_id),
            conversation_id text not null references conversations(id),
            hold_revision integer not null check (hold_revision >= 0),
            next_control_seq integer not null check (next_control_seq >= 0),
            state text not null check (state in (
                'reconciling','accepting','goal_active','session_conflict','native_unavailable'
            )),
            session_guard text,
            goal_guard text,
            settings_guard text,
            active_turn_guard text,
            reason_code text,
            observed_at text,
            created_at text not null,
            updated_at text not null
        );
        create index if not exists idx_room_codex_delivery_holds_conversation_state
            on room_codex_delivery_holds(conversation_id, state, participant_id);

        create table if not exists room_codex_bridge_actions (
            action_id text primary key,
            conversation_id text not null references conversations(id),
            participant_id text not null references participants(participant_id),
            control_seq integer not null check (control_seq > 0),
            client_action_id text not null,
            operator_identity text not null,
            request_fingerprint text not null,
            capability_id text not null check (capability_id in (
                'goal_set','goal_pause','goal_resume','goal_get','goal_clear',
                'settings_update','models_list','console_turn_start','turn_steer',
                'turn_interrupt','compact_start','review_start'
            )),
            expected_session_guard text not null,
            expected_goal_guard text,
            expected_settings_guard text,
            expected_turn_guard text,
            request_json text not null,
            status text not null check (
                status in ('requested','applying','applied','rejected','failed')
            ),
            reason_code text,
            ack_summary_json text,
            runner_generation text,
            requested_at text not null,
            applying_at text,
            completed_at text,
            updated_at text not null,
            unique(participant_id, control_seq),
            unique(participant_id, operator_identity, client_action_id)
        );
        create index if not exists idx_room_codex_bridge_actions_pending
            on room_codex_bridge_actions(status, participant_id, control_seq);
        """,
    )


__all__ = ["create_room_codex_schema"]
