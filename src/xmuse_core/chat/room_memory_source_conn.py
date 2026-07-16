"""Caller-owned connection helpers for proving Room memory sources."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from xmuse_core.chat.room_memory_common import (
    MEMORY_CANDIDATE_SCOPE_BY_KIND,
    MEMORY_DOCUMENT_PREFIX,
    RoomMemoryStoreError,
    json_dumps,
    json_loads,
    sha256_text,
)
from xmuse_core.chat.room_memory_contracts import require_digest


def activity_source_conn(
    conn: sqlite3.Connection, *, conversation_id: str, activity_id: str
) -> dict[str, Any]:
    """Resolve one visible Room activity inside an existing connection."""

    row = conn.execute(
        """select a.*, m.content message_content, p.content proposal_content
           from room_activities a
           left join messages m on m.id = a.materialized_message_id
           left join proposals p on p.id = a.materialized_proposal_id
           where a.conversation_id = ? and a.activity_id = ? and a.visibility = 'room'""",
        (conversation_id, activity_id),
    ).fetchone()
    if row is None:
        raise RoomMemoryStoreError("room_memory_source_not_found")
    content = row["message_content"] or row["proposal_content"]
    if content is None:
        content = json_dumps(
            {
                "activity_type": row["activity_type"],
                "actor_kind": row["actor_kind"],
                "payload": json_loads(row["payload_json"], {}),
            }
        )
    text = str(content)
    return {
        "activity_id": row["activity_id"],
        "conversation_id": row["conversation_id"],
        "seq": int(row["seq"]),
        "activity_type": row["activity_type"],
        "actor_kind": row["actor_kind"],
        "actor_identity": row["actor_identity"],
        "actor_participant_id": row["actor_participant_id"],
        "correlation_id": row["correlation_id"],
        "created_at": row["created_at"],
        "content": text,
        "content_sha256": sha256_text(text),
    }


def resolve_recall_source_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    document_id: str,
    source_activity_ids: Sequence[str],
    content_sha256: str,
    item_text: str,
) -> dict[str, Any]:
    """Verify recalled text against chat.db authority on one connection."""

    content_sha256 = require_digest(content_sha256, "room_memory_recall_content_digest_invalid")
    if not isinstance(item_text, str) or not item_text:
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    sources = tuple(sorted(source_activity_ids))
    if document_id.startswith(MEMORY_DOCUMENT_PREFIX):
        activity_id = document_id.removeprefix(MEMORY_DOCUMENT_PREFIX)
        if sources != (activity_id,):
            raise RoomMemoryStoreError("room_memory_recall_source_rejected")
        source = activity_source_conn(
            conn, conversation_id=conversation_id, activity_id=activity_id
        )
        if item_text not in source["content"] or sha256_text(item_text) != content_sha256:
            raise RoomMemoryStoreError("room_memory_recall_source_rejected")
        return {
            "source_type": "room_activity",
            "document_id": document_id,
            "item_content_sha256": content_sha256,
            "authority_content_sha256": source["content_sha256"],
            "authority_content": source["content"],
            "source_activities": [{key: source[key] for key in source if key != "content"}],
        }

    prefix = "xmuse-room-memory-candidate-"
    if not document_id.startswith(prefix):
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    candidate_id = document_id.removeprefix(prefix)
    candidate = conn.execute(
        """select c.*, o.document_id authoritative_document_id, o.state outbox_state
           from room_memory_candidates c
           join room_memory_outbox o on o.candidate_id = c.candidate_id
           where c.candidate_id = ?""",
        (candidate_id,),
    ).fetchone()
    expected_scope = (
        MEMORY_CANDIDATE_SCOPE_BY_KIND.get(str(candidate["kind"]))
        if candidate is not None
        else None
    )
    if (
        candidate is None
        or candidate["authoritative_document_id"] != document_id
        or expected_scope is None
        or candidate["target_scope"] != expected_scope
        or candidate["approval_state"] != "approved"
        or candidate["publish_state"] != "delivered"
        or candidate["outbox_state"] != "delivered"
        or candidate["content_sha256"] != sha256_text(str(candidate["content"]))
        or item_text not in str(candidate["content"])
        or sha256_text(item_text) != content_sha256
        or tuple(sorted(json_loads(candidate["source_activity_ids_json"], []))) != sources
    ):
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    assert expected_scope is not None
    if expected_scope == "room" and candidate["conversation_id"] != conversation_id:
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    binding = conn.execute(
        """select * from room_memory_bindings
           where conversation_id = ? and scope_type = ?""",
        (conversation_id, candidate["target_scope"]),
    ).fetchone()
    if (
        binding is None
        or binding["session_state"] != "bound"
        or binding["attachment_state"] != "attached"
    ):
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    activities = [
        activity_source_conn(
            conn,
            conversation_id=str(candidate["conversation_id"]),
            activity_id=activity_id,
        )
        for activity_id in sources
    ]
    return {
        "source_type": ("room_candidate" if expected_scope == "room" else "shared_candidate"),
        "document_id": document_id,
        "candidate_id": candidate_id,
        "candidate_digest": candidate["candidate_digest"],
        "item_content_sha256": content_sha256,
        "authority_content_sha256": candidate["content_sha256"],
        "authority_content": candidate["content"],
        "target_scope": expected_scope,
        "source_activities": [
            {key: source[key] for key in source if key != "content"} for source in activities
        ],
    }


def resolve_recall_message_source_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    session_id: str,
    source_message_ids: Sequence[str],
    content_sha256: str,
    item_text: str,
    derived: bool = False,
) -> dict[str, Any]:
    """Resolve MemoryOS message refs back to Room activities.

    MemoryOS v2 recall refs identify derived messages by the sidecar's opaque
    message ID.  The delivery ledger is the only durable bridge to Room
    authority; a missing, duplicated, cross-session, or cross-room bridge is a
    proof failure, never a reason to trust the recalled text.
    """

    content_sha256 = require_digest(content_sha256, "room_memory_recall_content_digest_invalid")
    if (
        not isinstance(conversation_id, str)
        or not conversation_id
        or not isinstance(session_id, str)
        or not session_id
        or not isinstance(item_text, str)
        or not item_text
        or not isinstance(derived, bool)
    ):
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    ids = tuple(source_message_ids)
    if not ids or len(ids) > 8 or len(set(ids)) != len(ids):
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    if any(
        not isinstance(value, str) or not value or len(value.encode("utf-8")) > 512 for value in ids
    ):
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    rows: list[sqlite3.Row] = []
    for message_id in ids:
        matches = conn.execute(
            """select d.memoryos_message_id, d.memoryos_session_id,
                      o.conversation_id, o.activity_id
                 from room_memory_message_deliveries d
                 join room_memory_message_outbox o
                   on o.message_outbox_id = d.message_outbox_id
                where d.memoryos_message_id = ?
                  and d.memoryos_session_id = ?
                  and d.state = 'delivered'""",
            (message_id, session_id),
        ).fetchall()
        if len(matches) != 1 or matches[0]["conversation_id"] != conversation_id:
            raise RoomMemoryStoreError("room_memory_recall_source_rejected")
        rows.append(matches[0])
    activities = [
        activity_source_conn(
            conn,
            conversation_id=conversation_id,
            activity_id=str(row["activity_id"]),
        )
        for row in rows
    ]
    # Exact message evidence must remain a byte-provable excerpt. Recall/page
    # evidence is explicitly derived and untrusted: its text cannot be an
    # excerpt by definition, so authority is limited to proving every complete
    # source ref through the Room delivery ledger.
    if not derived and not any(item_text in str(source["content"]) for source in activities):
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    if sha256_text(item_text) != content_sha256:
        raise RoomMemoryStoreError("room_memory_recall_source_rejected")
    source_ids = tuple(str(source["activity_id"]) for source in activities)
    return {
        "source_type": "room_message",
        # Keep the evidence document identity in the Room namespace.  The
        # MemoryOS message/session IDs are intentionally not returned.
        "document_id": f"{MEMORY_DOCUMENT_PREFIX}{source_ids[0]}",
        "item_content_sha256": content_sha256,
        "authority_content_sha256": sha256_text("\n".join(str(s["content"]) for s in activities)),
        "authority_content": "\n".join(str(s["content"]) for s in activities),
        "source_activities": [
            {key: value for key, value in source.items() if key != "content"}
            for source in activities
        ],
    }


def resolve_external_source_activity_ids_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    source_refs: Sequence[Mapping[str, Any]],
) -> list[str]:
    result: list[str] = []
    for ref in source_refs:
        if not isinstance(ref, Mapping):
            return []
        source_type = ref.get("source_type")
        source_id = ref.get("source_id")
        if (
            not isinstance(source_id, str)
            or not source_id
            or source_type
            not in {
                "message",
                "document",
            }
        ):
            return []
        if source_type == "message":
            session_id = ref.get("session_id")
            if not isinstance(session_id, str) or not session_id:
                return []
            rows = conn.execute(
                """select d.memoryos_message_id, o.activity_id, o.conversation_id
                   from room_memory_message_deliveries d
                   join room_memory_message_outbox o
                     on o.message_outbox_id = d.message_outbox_id
                   where d.memoryos_message_id = ? and d.memoryos_session_id = ?
                     and d.state = 'delivered'""",
                (source_id, session_id),
            ).fetchall()
            if len(rows) != 1 or rows[0]["conversation_id"] != conversation_id:
                return []
            activity_id = str(rows[0]["activity_id"])
        else:
            activity_id = source_id.removeprefix("xmuse-room-activity-")
            row = conn.execute(
                """select activity_id from room_activities
                   where conversation_id = ? and activity_id = ? and visibility = 'room'""",
                (conversation_id, activity_id),
            ).fetchone()
            if row is None:
                return []
        if activity_id not in result:
            result.append(activity_id)
    return result


__all__ = [
    "activity_source_conn",
    "resolve_external_source_activity_ids_conn",
    "resolve_recall_message_source_conn",
    "resolve_recall_source_conn",
]
