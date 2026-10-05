"""Durable per-Room collaboration mode (broadcast default, addressed opt-in)."""

from __future__ import annotations

import sqlite3
from typing import Any

COLLABORATION_MODES = ("broadcast", "addressed")
DEFAULT_COLLABORATION_MODE = "broadcast"
COLLABORATION_SCHEMA_VERSION = "room_collaboration/v1"

REVIEW_POLICIES = ("off", "cross_family")
DEFAULT_REVIEW_POLICY = "off"


def create_room_collaboration_schema(conn: sqlite3.Connection) -> None:
    """Create the additive collaboration policy table in the caller transaction."""

    conn.execute(
        """create table if not exists room_collaboration_policies (
               conversation_id text primary key references conversations(id),
               mode text not null check (mode in ('broadcast', 'addressed')),
               review_policy text not null default 'off' check (
                   review_policy in ('off', 'cross_family')),
               lead_participant_id text references participants(participant_id),
               revision integer not null default 1,
               updated_at text not null
           )"""
    )
    columns = {row[1] for row in conn.execute("pragma table_info(room_collaboration_policies)")}
    if "review_policy" not in columns:
        conn.execute(
            "alter table room_collaboration_policies add column review_policy "
            "text not null default 'off' check (review_policy in ('off', 'cross_family'))"
        )


def has_room_collaboration_table(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "select 1 from sqlite_master where type = 'table' "
            "and name = 'room_collaboration_policies'"
        ).fetchone()
        is not None
    )


def collaboration_policy_row(
    conn: sqlite3.Connection,
    conversation_id: str,
) -> sqlite3.Row | None:
    """Return the stored policy row, or ``None`` for the broadcast default.

    Rooms created before this table existed (or without an explicit policy)
    carry no row and keep exactly the historical broadcast behavior.
    """

    if not has_room_collaboration_table(conn):
        return None
    return conn.execute(
        "select * from room_collaboration_policies where conversation_id = ?",
        (conversation_id,),
    ).fetchone()


def collaboration_view(row: sqlite3.Row | None) -> dict[str, Any]:
    if row is None:
        return {"mode": DEFAULT_COLLABORATION_MODE, "lead_participant_id": None}
    return {
        "mode": str(row["mode"]),
        "lead_participant_id": row["lead_participant_id"],
    }


def is_addressed_mode(conn: sqlite3.Connection, conversation_id: str) -> bool:
    row = collaboration_policy_row(conn, conversation_id)
    return row is not None and str(row["mode"]) == "addressed"


def write_room_collaboration_policy_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    mode: str,
    lead_participant_id: str | None,
    updated_at: str,
    review_policy: str = DEFAULT_REVIEW_POLICY,
) -> None:
    """Persist the setup-time policy in the same transaction that creates the Room."""

    if mode not in COLLABORATION_MODES:
        raise ValueError("room_collaboration_mode_invalid")
    if review_policy not in REVIEW_POLICIES:
        raise ValueError("room_board_review_policy_invalid")
    conn.execute(
        """insert into room_collaboration_policies
        (conversation_id, mode, review_policy, lead_participant_id, revision, updated_at)
        values (?, ?, ?, ?, 1, ?)""",
        (conversation_id, mode, review_policy, lead_participant_id, updated_at),
    )


def review_policy_for_conversation(
    conn: sqlite3.Connection,
    conversation_id: str,
) -> str:
    """Return the room's review policy (``off`` unless setup asked for more).

    Rooms created before this column existed (or without an explicit policy)
    carry no row, or a row without the column, and keep exactly the historical
    behavior: no review is ever opened.
    """

    if not has_room_collaboration_table(conn):
        return DEFAULT_REVIEW_POLICY
    columns = {row[1] for row in conn.execute("pragma table_info(room_collaboration_policies)")}
    if "review_policy" not in columns:
        return DEFAULT_REVIEW_POLICY
    row = conn.execute(
        "select review_policy from room_collaboration_policies where conversation_id = ?",
        (conversation_id,),
    ).fetchone()
    if row is None or row[0] not in REVIEW_POLICIES:
        return DEFAULT_REVIEW_POLICY
    return str(row[0])
