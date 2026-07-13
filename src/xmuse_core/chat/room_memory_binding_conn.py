"""Caller-owned SQLite primitives for durable Room memory bindings.

This module deliberately has no ``RoomDatabase`` or store dependency.  Schema
backfill, Room creation, and the delivery store can therefore share the exact
binding materialization invariant without creating an import cycle.
"""

from __future__ import annotations

import hashlib
import sqlite3
from typing import Any

from xmuse_core.chat.room_memory_common import (
    MEMORY_BINDING_SCOPES,
    RoomMemoryStoreError,
    require_text,
)


def _scope_archive_id(scope_type: str, scope_key: str) -> str:
    digest = hashlib.sha256(f"{scope_type}:{scope_key}".encode()).hexdigest()[:32]
    return f"xmuse-{scope_type.replace('_', '-')}-{digest}"


def _scope_binding_id(conversation_id: str, scope_type: str) -> str:
    digest = hashlib.sha256(f"{conversation_id}:{scope_type}".encode()).hexdigest()[:32]
    return f"memory_binding_{digest}"


def binding_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "room_memory_binding/v1",
        "binding_id": row["binding_id"],
        "conversation_id": row["conversation_id"],
        "scope_type": row["scope_type"],
        "scope_key": row["scope_key"],
        "archive_id": row["archive_id"],
        "session_state": row["session_state"],
        "session_id": row["session_id"],
        "session_retry_count": int(row["session_retry_count"]),
        "session_retry_not_before": row["session_retry_not_before"],
        "attachment_state": row["attachment_state"],
        "attachment_id": row["attachment_id"],
        "attachment_retry_count": int(row["attachment_retry_count"]),
        "attachment_retry_not_before": row["attachment_retry_not_before"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def binding_safe_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "room_memory_binding/v1",
        "conversation_id": row["conversation_id"],
        "scope_type": row["scope_type"],
        "session_state": row["session_state"],
        "session_retry_count": int(row["session_retry_count"]),
        "session_retry_not_before": row["session_retry_not_before"],
        "attachment_state": row["attachment_state"],
        "attachment_retry_count": int(row["attachment_retry_count"]),
        "attachment_retry_not_before": row["attachment_retry_not_before"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def ensure_binding_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    scope_type: str,
    scope_key: str | None,
    stamp: str,
) -> sqlite3.Row:
    if not conn.in_transaction:
        raise RoomMemoryStoreError("room_memory_binding_transaction_required")
    if scope_type not in MEMORY_BINDING_SCOPES:
        raise RoomMemoryStoreError("room_memory_binding_scope_invalid")
    if (
        conn.execute("select 1 from conversations where id = ?", (conversation_id,)).fetchone()
        is None
    ):
        raise RoomMemoryStoreError("room_memory_conversation_not_found")
    default_shared_key = {"local_user": "local-user", "project": "local-project"}
    key = conversation_id if scope_type == "room" else (scope_key or default_shared_key[scope_type])
    key = require_text(key, "room_memory_binding_scope_key_invalid", maximum=512)
    room = conn.execute(
        """select * from room_memory_bindings
           where conversation_id = ? and scope_type = 'room'""",
        (conversation_id,),
    ).fetchone()
    inherited_session = room["session_id"] if room is not None else None
    inherited_state = "bound" if inherited_session else "unbound"
    conn.execute(
        """insert into room_memory_bindings
           (binding_id, conversation_id, scope_type, scope_key, archive_id,
            session_id, session_state, attachment_state, revision, created_at, updated_at)
           values (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?, ?)
           on conflict(conversation_id, scope_type) do nothing""",
        (
            _scope_binding_id(conversation_id, scope_type),
            conversation_id,
            scope_type,
            key,
            _scope_archive_id(scope_type, key),
            inherited_session if scope_type != "room" else None,
            inherited_state if scope_type != "room" else "unbound",
            stamp,
            stamp,
        ),
    )
    row = conn.execute(
        """select * from room_memory_bindings
           where conversation_id = ? and scope_type = ?""",
        (conversation_id, scope_type),
    ).fetchone()
    if row is None or row["scope_key"] != key:
        raise RoomMemoryStoreError("room_memory_binding_conflict")
    if scope_type == "room":
        for shared_scope, shared_key in (
            ("local_user", "local-user"),
            ("project", "local-project"),
        ):
            ensure_binding_conn(
                conn,
                conversation_id=conversation_id,
                scope_type=shared_scope,
                scope_key=shared_key,
                stamp=stamp,
            )
    return row


def ensure_room_memory_bindings_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    stamp: str,
) -> tuple[dict[str, Any], ...]:
    """Idempotently materialize all archive scopes in a caller-owned transaction."""

    if not conn.in_transaction:
        raise RoomMemoryStoreError("room_memory_binding_transaction_required")
    clean_stamp = require_text(stamp, "room_memory_binding_timestamp_invalid", maximum=64)
    ensure_binding_conn(
        conn,
        conversation_id=conversation_id,
        scope_type="room",
        scope_key=None,
        stamp=clean_stamp,
    )
    rows = conn.execute(
        """select * from room_memory_bindings
           where conversation_id = ? order by scope_type""",
        (conversation_id,),
    ).fetchall()
    if {str(row["scope_type"]) for row in rows} != MEMORY_BINDING_SCOPES:
        raise RoomMemoryStoreError("room_memory_binding_incomplete")
    return tuple(binding_view(row) for row in rows)
