"""Source proof, recall requests, receipts, and context binding for Room memory."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_common import (
    MEMORY_BINDING_SCOPES,
    MEMORY_CANDIDATE_SCOPE_BY_KIND,
    MEMORY_DOCUMENT_PREFIX,
    RoomMemoryStoreError,
    json_dumps,
    json_loads,
    new_id,
    require_text,
    sha256_text,
    timestamp,
)
from xmuse_core.chat.room_memory_contracts import (
    MEMORY_RECEIPT_STATUSES,
    MemoryReceiptItem,
    RoomMemoryContractError,
    normalize_receipt_items,
    require_digest,
    sha256_json,
)


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


def _receipt_view(row: sqlite3.Row) -> dict[str, Any]:
    item_refs = [
        {
            "item_id": item["item_id"],
            "source_activity_ids": item["source_activity_ids"],
            "content_sha256": item["content_sha256"],
        }
        for item in json_loads(row["item_refs_json"], [])
    ]
    return {
        "schema_version": "room_attempt_memory_receipt/v1",
        "receipt_id": row["receipt_id"],
        "conversation_id": row["conversation_id"],
        "participant_id": row["participant_id"],
        "status": row["status"],
        "memory_schema_version": row["schema_version"],
        "latency_ms": int(row["latency_ms"]),
        "item_count": int(row["item_count"]),
        "item_refs": item_refs,
        "source_activity_ids": json_loads(row["source_activity_ids_json"], []),
        "evidence_sha256": row["evidence_sha256"],
        "context_payload_sha256": row["context_payload_sha256"],
        "context_submitted_at": row["context_submitted_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class RoomMemoryRecallStore:
    """Narrow durable store for source proof and attempt recall receipts."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def get_activity_source(self, *, conversation_id: str, activity_id: str) -> dict[str, Any]:
        with self._database.connect(readonly=True) as conn:
            return activity_source_conn(
                conn, conversation_id=conversation_id, activity_id=activity_id
            )

    def resolve_recall_source(
        self,
        *,
        conversation_id: str,
        document_id: str,
        source_activity_ids: Sequence[str],
        content_sha256: str,
        item_text: str,
    ) -> dict[str, Any]:
        with self._database.connect(readonly=True) as conn:
            return resolve_recall_source_conn(
                conn,
                conversation_id=conversation_id,
                document_id=document_id,
                source_activity_ids=source_activity_ids,
                content_sha256=content_sha256,
                item_text=item_text,
            )

    def build_recall_request(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        correlation_id: str,
        causal_activity_ids: Sequence[str],
    ) -> dict[str, Any]:
        causal = tuple(sorted(set(causal_activity_ids)))
        if len(causal) != len(causal_activity_ids) or len(causal) > 64:
            raise RoomMemoryStoreError("room_memory_recall_causal_scope_invalid")
        with self._database.connect(readonly=True) as conn:
            authority = conn.execute(
                """select t.attempt_id, t.conversation_id, t.participant_id,
                          o.activity_id, a.correlation_id
                   from room_observation_attempts t
                   join room_observations o on o.observation_id = t.observation_id
                   join room_activities a on a.activity_id = o.activity_id
                   where t.attempt_id = ?""",
                (attempt_id,),
            ).fetchone()
            if (
                authority is None
                or authority["conversation_id"] != conversation_id
                or authority["correlation_id"] != correlation_id
            ):
                raise RoomMemoryStoreError("room_memory_recall_authority_invalid")
            if causal:
                placeholders = ",".join("?" for _ in causal)
                count = int(
                    conn.execute(
                        f"""select count(*) from room_activities where conversation_id = ?
                            and activity_id in ({placeholders})""",
                        (conversation_id, *causal),
                    ).fetchone()[0]
                )
                if count != len(causal):
                    raise RoomMemoryStoreError("room_memory_recall_causal_scope_invalid")
            bindings = conn.execute(
                """select * from room_memory_bindings where conversation_id = ?
                   order by scope_type""",
                (conversation_id,),
            ).fetchall()
            by_scope = {str(row["scope_type"]): row for row in bindings}
            if set(by_scope) != MEMORY_BINDING_SCOPES or any(
                row["session_state"] != "bound" or row["attachment_state"] != "attached"
                for row in bindings
            ):
                raise RoomMemoryStoreError("room_memory_recall_unavailable")
            session_ids = {str(row["session_id"]) for row in bindings}
            if len(session_ids) != 1:
                raise RoomMemoryStoreError("room_memory_recall_unavailable")
            source = activity_source_conn(
                conn,
                conversation_id=conversation_id,
                activity_id=str(authority["activity_id"]),
            )
            correlated = {
                str(row["activity_id"])
                for row in conn.execute(
                    """select activity_id from room_activities
                       where conversation_id = ? and correlation_id = ?""",
                    (conversation_id, correlation_id),
                )
            }
            excluded = tuple(sorted(correlated | set(causal)))
            query = str(source["content"])
            if len(query.encode("utf-8")) > 4096:
                query = query.encode("utf-8")[:4096].decode("utf-8", errors="ignore")
            build_context_request = {
                "task": ("Recall prior source-backed Room evidence relevant to this observation."),
                "budget": 800,
                "retrieval_query": query,
                "include_global_core": False,
            }
            return {
                "schema_version": "room_memory_recall_request/v1",
                "session_id": next(iter(session_ids)),
                "archive_ids": [str(by_scope[scope]["archive_id"]) for scope in sorted(by_scope)],
                "build_context_request": build_context_request,
                "task": build_context_request["task"],
                "retrieval_query": query,
                "budget": 800,
                "top_k": 8,
                "max_response_bytes": 8192,
                "excluded_activity_ids": list(excluded),
                "excluded_document_ids": [
                    f"{MEMORY_DOCUMENT_PREFIX}{activity_id}" for activity_id in excluded
                ],
            }

    def record_attempt_memory_receipt(
        self,
        *,
        attempt_id: str,
        status: str,
        schema_version: str | None,
        latency_ms: int,
        items: Sequence[Mapping[str, Any]],
        evidence_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if status not in MEMORY_RECEIPT_STATUSES:
            raise RoomMemoryStoreError("room_memory_receipt_status_invalid")
        if (
            isinstance(latency_ms, bool)
            or not isinstance(latency_ms, int)
            or not 0 <= latency_ms <= 60000
        ):
            raise RoomMemoryStoreError("room_memory_receipt_latency_invalid")
        clean_schema = (
            require_text(schema_version, "room_memory_receipt_schema_invalid", maximum=128)
            if schema_version is not None
            else None
        )
        if status in {"ok", "empty"} and clean_schema is None:
            raise RoomMemoryStoreError("room_memory_receipt_schema_invalid")
        evidence_sha256 = require_digest(
            evidence_sha256, "room_memory_receipt_evidence_digest_invalid"
        )
        normalized: tuple[MemoryReceiptItem, ...] = normalize_receipt_items(list(items))
        if (status == "ok") != bool(normalized):
            if status == "ok" or normalized:
                raise RoomMemoryStoreError("room_memory_receipt_items_invalid")
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                authority = conn.execute(
                    """select t.conversation_id, t.participant_id, a.correlation_id
                       from room_observation_attempts t
                       join room_observations o on o.observation_id = t.observation_id
                       join room_activities a on a.activity_id = o.activity_id
                       where t.attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if authority is None:
                    raise RoomMemoryStoreError("room_memory_receipt_attempt_not_found")
                item_refs = [
                    {
                        "item_id": item.item_id,
                        "document_id": item.document_id,
                        "source_activity_ids": list(item.source_activity_ids),
                        "content_sha256": item.content_sha256,
                    }
                    for item in normalized
                ]
                resolved = [
                    resolve_recall_source_conn(
                        conn,
                        conversation_id=str(authority["conversation_id"]),
                        document_id=item.document_id,
                        source_activity_ids=item.source_activity_ids,
                        content_sha256=item.content_sha256,
                        item_text=item.text,
                    )
                    for item in normalized
                ]
                source_ids = sorted(
                    {
                        str(activity["activity_id"])
                        for item in resolved
                        for activity in item["source_activities"]
                    }
                )
                fingerprint = sha256_json(
                    {
                        "attempt_id": attempt_id,
                        "status": status,
                        "schema_version": clean_schema,
                        "latency_ms": latency_ms,
                        "items": item_refs,
                        "evidence_sha256": evidence_sha256,
                    }
                )
                prior = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if prior is not None:
                    if prior["request_fingerprint"] != fingerprint:
                        raise RoomMemoryStoreError("room_memory_receipt_conflict")
                    conn.rollback()
                    return _receipt_view(prior)
                receipt_id = new_id("memory_receipt")
                conn.execute(
                    """insert into room_memory_attempt_receipts
                       (receipt_id, attempt_id, conversation_id, participant_id,
                        correlation_id, status, schema_version, latency_ms, item_count,
                        item_refs_json, source_activity_ids_json, evidence_sha256,
                        request_fingerprint, created_at, updated_at)
                       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        receipt_id,
                        attempt_id,
                        authority["conversation_id"],
                        authority["participant_id"],
                        authority["correlation_id"],
                        status,
                        clean_schema,
                        latency_ms,
                        len(normalized),
                        json_dumps(item_refs),
                        json_dumps(source_ids),
                        evidence_sha256,
                        fingerprint,
                        stamp,
                        stamp,
                    ),
                )
                row = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where receipt_id = ?""",
                    (receipt_id,),
                ).fetchone()
                assert row is not None
                result = _receipt_view(row)
                conn.commit()
                return result
            except (RoomMemoryContractError, RoomMemoryStoreError):
                conn.rollback()
                raise
            except Exception:
                conn.rollback()
                raise

    def bind_attempt_memory_context(
        self,
        *,
        attempt_id: str,
        evidence_sha256: str,
        context_payload_sha256: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        evidence_sha256 = require_digest(
            evidence_sha256, "room_memory_receipt_evidence_digest_invalid"
        )
        context_payload_sha256 = require_digest(
            context_payload_sha256, "room_memory_context_digest_invalid"
        )
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if row is None or row["evidence_sha256"] != evidence_sha256:
                    raise RoomMemoryStoreError("room_memory_receipt_not_found")
                skill = conn.execute(
                    """select context_payload_sha256 from room_attempt_skill_decisions
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                if (
                    skill is not None
                    and skill["context_payload_sha256"] is not None
                    and skill["context_payload_sha256"] != context_payload_sha256
                ):
                    raise RoomMemoryStoreError("room_memory_context_digest_mismatch")
                if row["context_payload_sha256"] is not None:
                    if row["context_payload_sha256"] != context_payload_sha256:
                        raise RoomMemoryStoreError("room_memory_context_receipt_conflict")
                    conn.rollback()
                    return _receipt_view(row)
                conn.execute(
                    """update room_memory_attempt_receipts
                       set context_payload_sha256 = ?, context_submitted_at = ?,
                           updated_at = ? where attempt_id = ?""",
                    (context_payload_sha256, stamp, stamp, attempt_id),
                )
                updated = conn.execute(
                    """select * from room_memory_attempt_receipts
                       where attempt_id = ?""",
                    (attempt_id,),
                ).fetchone()
                assert updated is not None
                result = _receipt_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def list_attempt_receipts(
        self, conversation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from room_memory_attempt_receipts
                   where conversation_id = ?
                   order by created_at desc, receipt_id desc limit ?""",
                (conversation_id, clean_limit),
            ).fetchall()
        return [_receipt_view(row) for row in rows]
