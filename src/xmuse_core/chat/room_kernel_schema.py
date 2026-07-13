"""Pure SQLite schema for Room activities, observations, and cursors."""

from __future__ import annotations

import sqlite3

from xmuse_core.chat.room_batches import create_room_batch_schema
from xmuse_core.chat.room_control_schema import create_room_control_schema


def _execute_schema(conn: sqlite3.Connection, script: str) -> None:
    """Execute DDL without ``executescript`` committing the caller transaction."""

    for statement in script.split(";"):
        if cleaned := statement.strip():
            conn.execute(cleaned)


def create_room_kernel_schema(conn: sqlite3.Connection) -> None:
    """Create the additive Room authority schema in the caller transaction."""

    _execute_schema(
        conn,
        """
        create table if not exists room_activities (
            activity_id text primary key,
            conversation_id text not null references conversations(id),
            seq integer not null,
            activity_type text not null,
            actor_kind text not null,
            actor_identity text not null,
            actor_participant_id text references participants(participant_id),
            causation_id text not null,
            correlation_id text not null,
            visibility text not null,
            audience_json text not null,
            payload_json text not null,
            materialized_message_id text unique references messages(id),
            causal_depth integer not null default 0,
            materialized_proposal_id text references proposals(id),
            delivery_mode text not null check (delivery_mode in ('active', 'shadow')),
            created_at text not null,
            unique(conversation_id, seq)
        );

        create index if not exists idx_room_activities_conversation_seq
            on room_activities(conversation_id, seq);
        create index if not exists idx_room_activities_conversation_correlation
            on room_activities(conversation_id, correlation_id, seq);

        create table if not exists room_observations (
            observation_id text primary key,
            conversation_id text not null references conversations(id),
            activity_id text not null references room_activities(activity_id),
            participant_id text not null references participants(participant_id),
            priority integer not null default 0,
            delivery_mode text not null check (delivery_mode in ('active', 'shadow')),
            status text not null check (status in ('pending', 'shadowed', 'claimed', 'completed')),
            lease_owner text,
            acquired_at text,
            expires_at text,
            lease_token text,
            attempt_count integer not null default 0,
            outcome_type text,
            outcome_payload_json text,
            outcome_actor_identity text,
            outcome_client_request_id text,
            produced_activity_id text references room_activities(activity_id),
            produced_message_id text references messages(id),
            produced_proposal_id text references proposals(id),
            completed_at text,
            created_at text not null,
            updated_at text not null,
            unique(activity_id, participant_id)
        );

        create index if not exists idx_room_observations_activity_created
            on room_observations(conversation_id, activity_id, created_at);
        create index if not exists idx_room_observations_participant_status
            on room_observations(participant_id, status, created_at);
        create index if not exists idx_room_observations_conversation_status
            on room_observations(conversation_id, delivery_mode, status, updated_at);

        create index if not exists idx_room_observations_claim_order
            on room_observations(conversation_id, participant_id, status, activity_id, created_at);

        create table if not exists room_participant_cursors (
            conversation_id text not null references conversations(id),
            participant_id text not null references participants(participant_id),
            last_acknowledged_seq integer not null default 0,
            last_observation_id text references room_observations(observation_id),
            updated_at text not null,
            primary key(conversation_id, participant_id)
        );

        create index if not exists idx_room_participant_cursors_reads
            on room_participant_cursors(conversation_id, participant_id, last_acknowledged_seq);
        """,
    )
    for column, definition in (
        ("causal_depth", "integer not null default 0"),
        ("materialized_proposal_id", "text references proposals(id)"),
    ):
        columns = {row["name"] for row in conn.execute("pragma table_info(room_activities)")}
        if column not in columns:
            conn.execute(f"alter table room_activities add column {column} {definition}")
    conn.execute(
        "create unique index if not exists idx_room_activities_materialized_proposal "
        "on room_activities(materialized_proposal_id) where materialized_proposal_id is not null"
    )
    for column, definition in (
        ("lease_token", "text"),
        ("outcome_actor_identity", "text"),
        ("outcome_client_request_id", "text"),
        ("produced_activity_id", "text references room_activities(activity_id)"),
        ("produced_message_id", "text references messages(id)"),
        ("produced_proposal_id", "text references proposals(id)"),
    ):
        columns = {row["name"] for row in conn.execute("pragma table_info(room_observations)")}
        if column not in columns:
            conn.execute(f"alter table room_observations add column {column} {definition}")
    conn.execute(
        """insert or ignore into room_participant_cursors
        (conversation_id, participant_id, last_acknowledged_seq, updated_at)
        select conversation_id, participant_id, 0, min(created_at)
        from room_observations where delivery_mode = 'active'
        group by conversation_id, participant_id"""
    )
    create_room_batch_schema(conn)
    create_room_control_schema(conn)
