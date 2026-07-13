"""Pure SQLite schema for the Room Operations action ledger."""

from __future__ import annotations

import sqlite3


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if cleaned := statement.strip():
            conn.execute(cleaned)


def create_room_operations_schema(conn: sqlite3.Connection) -> None:
    _execute_schema(
        conn,
        """
        create table if not exists room_runtime_operator_actions (
            action_id text primary key,
            client_action_id text not null unique,
            operator_identity text not null,
            request_fingerprint text not null,
            incident_guard text not null,
            status text not null check (status in ('requested','applied','rejected','failed')),
            before_state text not null,
            before_code text not null,
            after_state text,
            after_code text,
            result_json text,
            reason_code text,
            requested_at text not null,
            applied_at text,
            updated_at text not null
        );
        create index if not exists idx_room_runtime_operator_actions_status_requested
            on room_runtime_operator_actions(status, requested_at);
        """,
    )
