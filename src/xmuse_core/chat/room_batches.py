"""Durable observation batching for one participant and Human correlation.

A batch is immutable delivery scope.  Only its primary observation owns an attempt;
the member observations mirror that attempt's lease/control/outcome facts so existing
read models remain truthful while the provider performs one turn.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from typing import Any

MAX_OBSERVATION_BATCH_MEMBERS = 16
BATCH_SCHEMA_VERSION = "room_observation_batch/v1"


def create_room_batch_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """create table if not exists room_observation_batches (
               batch_id text primary key,
               conversation_id text not null references conversations(id),
               participant_id text not null references participants(participant_id),
               correlation_id text not null,
               phase text not null check (phase in ('root','peer')),
               primary_observation_id text not null unique
                   references room_observations(observation_id),
               cutoff_seq integer not null check (cutoff_seq > 0),
               member_count integer not null check (member_count between 1 and 16),
               digest text not null,
               created_at text not null
           )"""
    )
    conn.execute(
        """create table if not exists room_observation_batch_members (
               batch_id text not null references room_observation_batches(batch_id)
                   on delete cascade,
               observation_id text not null unique references room_observations(observation_id),
               ordinal integer not null check (ordinal >= 0 and ordinal < 16),
               activity_id text not null references room_activities(activity_id),
               activity_seq integer not null check (activity_seq > 0),
               primary key(batch_id, ordinal),
               unique(batch_id, observation_id),
               unique(batch_id, activity_seq)
           )"""
    )
    conn.execute(
        "create index if not exists idx_room_batches_dispatch "
        "on room_observation_batches(conversation_id, participant_id, correlation_id, cutoff_seq)"
    )
    conn.execute(
        "create index if not exists idx_room_batch_members_observation "
        "on room_observation_batch_members(observation_id, batch_id)"
    )
    # Recovery/control code predating batches still updates the primary observation.
    # Keep every member's delivery authority facts identical without duplicating that
    # safety-critical state machine at each call site.
    conn.execute(
        """create trigger if not exists trg_room_batch_primary_mirror
           after update of status, lease_owner, acquired_at, expires_at, lease_token,
                           attempt_count, outcome_type, outcome_payload_json,
                           outcome_actor_identity, outcome_client_request_id,
                           produced_activity_id, produced_message_id,
                           produced_proposal_id, completed_at, updated_at,
                           control_state, control_seq, manual_retry_budget,
                           current_attempt_id
           on room_observations
           when exists (
               select 1 from room_observation_batches b
               where b.primary_observation_id = new.observation_id
           )
           begin
               update room_observations
               set status = new.status,
                   lease_owner = new.lease_owner,
                   acquired_at = new.acquired_at,
                   expires_at = new.expires_at,
                   lease_token = new.lease_token,
                   attempt_count = new.attempt_count,
                   outcome_type = new.outcome_type,
                   outcome_payload_json = new.outcome_payload_json,
                   outcome_actor_identity = new.outcome_actor_identity,
                   outcome_client_request_id = new.outcome_client_request_id,
                   produced_activity_id = null,
                   produced_message_id = null,
                   produced_proposal_id = null,
                   completed_at = new.completed_at,
                   updated_at = new.updated_at,
                   control_state = new.control_state,
                   control_seq = new.control_seq,
                   manual_retry_budget = new.manual_retry_budget,
                   current_attempt_id = new.current_attempt_id
               where observation_id in (
                   select m.observation_id
                   from room_observation_batch_members m
                   join room_observation_batches b on b.batch_id = m.batch_id
                   where b.primary_observation_id = new.observation_id
                     and m.observation_id <> new.observation_id
               );
           end"""
    )


def batch_row_for_observation(conn: sqlite3.Connection, observation_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """select b.* from room_observation_batches b
           join room_observation_batch_members m on m.batch_id = b.batch_id
           where m.observation_id = ?""",
        (observation_id,),
    ).fetchone()


def canonical_observation_id(conn: sqlite3.Connection, observation_id: str) -> str:
    batch = batch_row_for_observation(conn, observation_id)
    return str(batch["primary_observation_id"]) if batch is not None else observation_id


def batch_member_ids(conn: sqlite3.Connection, observation_id: str) -> list[str]:
    batch = batch_row_for_observation(conn, observation_id)
    if batch is None:
        return [observation_id]
    return [
        str(row["observation_id"])
        for row in conn.execute(
            "select observation_id from room_observation_batch_members "
            "where batch_id = ? order by ordinal",
            (batch["batch_id"],),
        )
    ]


def create_observation_batch(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    participant_id: str,
    correlation_id: str,
    phase: str,
    members: list[sqlite3.Row],
    created_at: str,
) -> sqlite3.Row:
    """Persist an immutable batch from rows carrying observation/activity identifiers."""

    if phase not in {"root", "peer"}:
        raise ValueError("room_observation_batch_phase_invalid")
    if not members or len(members) > MAX_OBSERVATION_BATCH_MEMBERS:
        raise ValueError("room_observation_batch_size_invalid")
    existing = batch_row_for_observation(conn, str(members[0]["observation_id"]))
    if existing is not None:
        return existing
    member_facts: list[dict[str, Any]] = [
        {
            "observation_id": str(row["observation_id"]),
            "activity_id": str(row["activity_id"]),
            "activity_seq": int(row["activity_seq"]),
        }
        for row in members
    ]
    cutoff_seq = max(int(item["activity_seq"]) for item in member_facts)
    canonical = {
        "conversation_id": conversation_id,
        "participant_id": participant_id,
        "correlation_id": correlation_id,
        "phase": phase,
        "cutoff_seq": cutoff_seq,
        "members": member_facts,
    }
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    batch_id = f"observation_batch_{uuid.uuid4().hex}"
    primary_id = member_facts[0]["observation_id"]
    conn.execute(
        """insert into room_observation_batches
           (batch_id, conversation_id, participant_id, correlation_id, phase,
            primary_observation_id, cutoff_seq, member_count, digest, created_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            batch_id,
            conversation_id,
            participant_id,
            correlation_id,
            phase,
            primary_id,
            cutoff_seq,
            len(member_facts),
            digest,
            created_at,
        ),
    )
    conn.executemany(
        """insert into room_observation_batch_members
           (batch_id, observation_id, ordinal, activity_id, activity_seq)
           values (?, ?, ?, ?, ?)""",
        [
            (
                batch_id,
                item["observation_id"],
                ordinal,
                item["activity_id"],
                item["activity_seq"],
            )
            for ordinal, item in enumerate(member_facts)
        ],
    )
    row = conn.execute(
        "select * from room_observation_batches where batch_id = ?", (batch_id,)
    ).fetchone()
    assert row is not None
    return row


def batch_identity(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": BATCH_SCHEMA_VERSION,
        "batch_id": str(row["batch_id"]),
        "phase": str(row["phase"]),
        "correlation_id": str(row["correlation_id"]),
        "primary_observation_id": str(row["primary_observation_id"]),
        "cutoff_seq": int(row["cutoff_seq"]),
        "member_count": int(row["member_count"]),
        "digest": str(row["digest"]),
    }
