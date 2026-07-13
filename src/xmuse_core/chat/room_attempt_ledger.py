"""Caller-transaction primitives for the Room observation attempt ledger.

The functions in this module neither open nor commit a database connection.  They
persist and query attempt facts only; the Room Kernel/control coordinator remains
responsible for lease fencing, observation state, batch membership, retry policy,
events, and atomic multi-table transitions.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any

ATTEMPT_ACTIVE_STATES = frozenset({"claimed", "delivering", "cancel_requested", "cancel_pending"})

_AUTHORITY_PRIVATE_FIELDS = frozenset(
    {"lease_owner", "lease_token_digest", "runner_generation", "runner_boot_id"}
)
_RECONCILE_BINDING_FIELDS = frozenset(
    {
        "delivery_task_id",
        "god_session_id",
        "provider_session_id",
        "provider_session_generation",
        "provider_phase",
        "provider_cleanup_reason",
        "provider_phase_updated_at",
    }
)
_PUBLIC_ATTEMPT_FIELDS = (
    "attempt_number",
    "effective_attempt_limit",
    "state",
    "reason_code",
    "claimed_at",
    "expires_at",
    "transport_started_at",
    "finished_at",
    "updated_at",
)


@dataclass(frozen=True)
class ClaimAttemptRecord:
    """Already-authorized values for one claimed attempt ledger row."""

    attempt_id: str
    batch_id: str | None
    conversation_id: str
    observation_id: str
    participant_id: str
    attempt_number: int
    effective_attempt_limit: int
    delivery_generation: int
    lease_owner: str
    lease_token_digest: str
    runner_generation: str | None
    runner_boot_id: str | None
    claimed_at: str
    expires_at: str
    created_at: str
    updated_at: str


def attempt_by_id_conn(conn: sqlite3.Connection, attempt_id: str | None) -> sqlite3.Row | None:
    """Return one attempt row without translating absence into policy."""

    if not attempt_id:
        return None
    return conn.execute(
        "select * from room_observation_attempts where attempt_id = ?", (attempt_id,)
    ).fetchone()


def attempt_by_number_conn(
    conn: sqlite3.Connection,
    *,
    observation_id: str,
    attempt_number: int,
) -> sqlite3.Row | None:
    return conn.execute(
        "select * from room_observation_attempts where observation_id = ? and attempt_number = ?",
        (observation_id, attempt_number),
    ).fetchone()


def insert_claim_attempt_conn(conn: sqlite3.Connection, record: ClaimAttemptRecord) -> sqlite3.Row:
    """Insert one coordinator-authorized claim record in the caller transaction."""

    conn.execute(
        """insert into room_observation_attempts
        (attempt_id, batch_id, conversation_id, observation_id, participant_id, attempt_number,
         effective_attempt_limit, delivery_generation, state, reason_code, lease_owner,
         lease_token_digest, runner_generation, runner_boot_id, claimed_at, expires_at,
         created_at, updated_at)
        values (?, ?, ?, ?, ?, ?, ?, ?, 'claimed', null, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            record.attempt_id,
            record.batch_id,
            record.conversation_id,
            record.observation_id,
            record.participant_id,
            record.attempt_number,
            record.effective_attempt_limit,
            record.delivery_generation,
            record.lease_owner,
            record.lease_token_digest,
            record.runner_generation,
            record.runner_boot_id,
            record.claimed_at,
            record.expires_at,
            record.created_at,
            record.updated_at,
        ),
    )
    row = attempt_by_id_conn(conn, record.attempt_id)
    assert row is not None
    return row


def attempt_view(
    row: sqlite3.Row | None, *, include_reconcile_binding: bool = False
) -> dict[str, Any] | None:
    """Return the internal view while always fencing lease and Runner authority."""

    if row is None:
        return None
    hidden = set(_AUTHORITY_PRIVATE_FIELDS)
    if not include_reconcile_binding:
        hidden.update(_RECONCILE_BINDING_FIELDS)
    return {key: row[key] for key in row.keys() if key not in hidden}


def public_attempt_view(row: sqlite3.Row | None) -> dict[str, Any] | None:
    """Return only bounded attempt facts allowed in browser projections."""

    if row is None:
        return None
    result = {key: row[key] for key in _PUBLIC_ATTEMPT_FIELDS}
    result["attempt_number"] = int(result["attempt_number"])
    result["effective_attempt_limit"] = int(result["effective_attempt_limit"])
    return result


def pending_cancel_observation_ids_conn(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        """select distinct coalesce(b.primary_observation_id, o.observation_id)
                                  as observation_id
           from room_observations o
           left join room_observation_batch_members bm
             on bm.observation_id = o.observation_id
           left join room_observation_batches b on b.batch_id = bm.batch_id
           where o.control_state in ('cancel_requested','cancel_pending')
           order by o.updated_at, o.observation_id"""
    ).fetchall()
    return [str(row["observation_id"]) for row in rows]


def pending_provider_cleanup_observation_ids_conn(
    conn: sqlite3.Connection,
) -> list[str]:
    rows = conn.execute(
        """select distinct coalesce(b.primary_observation_id, o.observation_id)
                                  as observation_id
           from room_observations o
           join room_observation_attempts a on a.attempt_id = o.current_attempt_id
           left join room_observation_batch_members bm
             on bm.observation_id = o.observation_id
           left join room_observation_batches b on b.batch_id = bm.batch_id
           where o.status <> 'completed'
             and o.control_state in ('active', 'exhausted')
             and (a.provider_phase in ('ensure_started', 'cleanup_pending')
                  or (a.provider_phase = 'bound'
                      and a.state in ('claimed', 'delivering')))
           order by o.updated_at, o.observation_id"""
    ).fetchall()
    return [str(row["observation_id"]) for row in rows]


def pending_runner_recovery_observation_ids_conn(
    conn: sqlite3.Connection, *, reason_code: str
) -> list[str]:
    rows = conn.execute(
        """select distinct coalesce(b.primary_observation_id, o.observation_id)
                                  as observation_id
           from room_observations o
           join room_observation_attempts a on a.attempt_id = o.current_attempt_id
           left join room_observation_batch_members bm
             on bm.observation_id = o.observation_id
           left join room_observation_batches b on b.batch_id = bm.batch_id
           where o.status <> 'completed'
             and o.control_state in ('active','exhausted')
             and a.recovery_state in ('fenced','cleanup_pending')
             and a.recovery_reason_code = ?
           order by o.updated_at, o.observation_id""",
        (reason_code,),
    ).fetchall()
    return [str(row["observation_id"]) for row in rows]
