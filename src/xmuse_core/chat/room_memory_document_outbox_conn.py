"""Caller-owned SQLite primitives for Room memory document delivery."""

from __future__ import annotations

import sqlite3

from xmuse_core.chat.room_memory_common import RoomMemoryStoreError


def queue_candidate_delivery_conn(
    conn: sqlite3.Connection, *, candidate: sqlite3.Row, stamp: str
) -> None:
    """Queue one approved candidate without committing its caller transaction."""

    if not conn.in_transaction:
        raise RoomMemoryStoreError("room_memory_delivery_transaction_required")
    conn.execute(
        """insert or ignore into room_memory_outbox
           (outbox_id, conversation_id, activity_id, candidate_id, document_id,
            target_scope, state, attempt_count, created_at, updated_at)
           values (?, ?, null, ?, ?, ?, 'pending', 0, ?, ?)""",
        (
            f"memory_outbox_candidate_{candidate['candidate_id']}",
            candidate["conversation_id"],
            candidate["candidate_id"],
            f"xmuse-room-memory-candidate-{candidate['candidate_id']}",
            candidate["target_scope"],
            stamp,
            stamp,
        ),
    )
