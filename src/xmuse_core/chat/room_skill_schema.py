"""Pure SQLite schema for attempt-local Room Skill decisions."""

from __future__ import annotations

import sqlite3


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    for statement in script.split(";"):
        if cleaned := statement.strip():
            conn.execute(cleaned)


def create_room_skill_decision_schema(conn: sqlite3.Connection) -> None:
    """Create the additive decision/receipt ledger in the caller transaction."""

    _execute_schema(
        conn,
        """
        create table if not exists room_attempt_skill_decisions (
            attempt_id text primary key
                references room_observation_attempts(attempt_id),
            selector_version text not null,
            participant_role_snapshot text not null,
            selection_input_sha256 text,
            decision text not null check (decision in ('selected','none')),
            skill_id text,
            skill_version text,
            skill_content_sha256 text,
            skill_instructions_sha256 text,
            catalog_sha256 text not null,
            selection_reason text not null check (
                selection_reason in ('explicit','trigger','no_match','input_too_large')
            ),
            matched_terms_json text not null,
            context_payload_sha256 text,
            context_submitted_at text,
            created_at text not null,
            updated_at text not null,
            check (
              (decision = 'none'
               and selection_reason in ('no_match','input_too_large')
               and skill_id is null
               and skill_version is null
               and skill_content_sha256 is null
               and skill_instructions_sha256 is null
               and matched_terms_json = '[]')
              or
              (decision = 'selected'
               and selection_reason in ('explicit','trigger')
               and skill_id is not null
               and skill_version is not null
               and skill_content_sha256 is not null
               and skill_instructions_sha256 is not null)
            ),
            check (
              (context_payload_sha256 is null and context_submitted_at is null)
              or
              (context_payload_sha256 is not null and context_submitted_at is not null)
            )
        );
        """,
    )
