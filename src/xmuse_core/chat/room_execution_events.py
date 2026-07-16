"""Transactional frontend invalidation events for the execution ledger."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from xmuse_core.chat.room_database import FRONTEND_EVENT_PROOF_BOUNDARY
from xmuse_core.chat.room_execution_common import json_value, new_id


def record_execution_event_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    event_type: str,
    resource_ref: str,
    source_ref: str,
    payload: Mapping[str, Any],
    client_action_id: str | None,
    stamp: str,
) -> None:
    """Append a projection-only event inside the caller-owned transaction."""

    seq = int(
        conn.execute(
            "select coalesce(max(seq), 0) + 1 from chat_frontend_events where conversation_id = ?",
            (conversation_id,),
        ).fetchone()[0]
    )
    conn.execute(
        """insert into chat_frontend_events
           (event_id, conversation_id, seq, event_type, resource_ref,
            source_authority, source_ref, payload_json, client_action_id, created_at,
            projection_only, proof_boundary)
           values (?, ?, ?, ?, ?, 'chat.db', ?, ?, ?, ?, 1, ?)""",
        (
            new_id("frontend_event"),
            conversation_id,
            seq,
            event_type,
            resource_ref,
            source_ref,
            json_value(dict(payload)),
            client_action_id,
            stamp,
            FRONTEND_EVENT_PROOF_BOUNDARY,
        ),
    )
