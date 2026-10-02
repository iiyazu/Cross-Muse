"""Durable per-Room collaboration mode (broadcast default, addressed opt-in)."""

from __future__ import annotations

import sqlite3
from typing import Any

COLLABORATION_MODES = ("broadcast", "addressed")
DEFAULT_COLLABORATION_MODE = "broadcast"
COLLABORATION_SCHEMA_VERSION = "room_collaboration/v1"


def create_room_collaboration_schema(conn: sqlite3.Connection) -> None:
    """Create the additive collaboration policy table in the caller transaction."""

    conn.execute(
        """create table if not exists room_collaboration_policies (
               conversation_id text primary key references conversations(id),
               mode text not null check (mode in ('broadcast', 'addressed')),
               lead_participant_id text references participants(participant_id),
               revision integer not null default 1,
               updated_at text not null
           )"""
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
) -> None:
    """Persist the setup-time policy in the same transaction that creates the Room."""

    if mode not in COLLABORATION_MODES:
        raise ValueError("room_collaboration_mode_invalid")
    conn.execute(
        """insert into room_collaboration_policies
        (conversation_id, mode, lead_participant_id, revision, updated_at)
        values (?, ?, ?, 1, ?)""",
        (conversation_id, mode, lead_participant_id, updated_at),
    )
