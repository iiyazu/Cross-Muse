"""Source proof, recall requests, receipts, and context binding for Room memory."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

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
    MemoryCandidateInput,
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

    def resolve_recall_message_source(
        self,
        *,
        conversation_id: str,
        session_id: str,
        source_message_ids: Sequence[str],
        content_sha256: str,
        item_text: str,
        derived: bool = False,
    ) -> dict[str, Any]:
        with self._database.connect(readonly=True) as conn:
            return resolve_recall_message_source_conn(
                conn,
                conversation_id=conversation_id,
                session_id=session_id,
                source_message_ids=source_message_ids,
                content_sha256=content_sha256,
                item_text=item_text,
                derived=derived,
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

    def record_external_advisories(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        advisories: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> list[dict[str, Any]]:
        """Re-prove MemoryOS kernel suggestions and enter Room governance.

        MemoryOS is only a proposer.  Source IDs are translated through the
        Room message-delivery ledger or visible activity table.  Historical
        recalled sources are allowed through the explicitly external path;
        ordinary Agent candidates still use the causal batch authority.  Every
        advisory receives a durable accepted/duplicate/rejected receipt.
        """

        if not advisories or len(advisories) > 32:
            return []
        from xmuse_core.chat.room_memory_governance_store import record_memory_candidates_conn

        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                authority = conn.execute(
                    """select t.observation_id, t.batch_id, t.participant_id,
                              b.primary_observation_id
                       from room_observation_attempts t
                       left join room_observation_batches b on b.batch_id = t.batch_id
                       where t.attempt_id = ? and t.conversation_id = ?""",
                    (attempt_id, conversation_id),
                ).fetchone()
                if authority is None or authority["batch_id"] is None:
                    raise RoomMemoryStoreError("room_memory_advisory_authority_invalid")
                batch_id = str(authority["batch_id"])
                primary_observation_id = str(
                    authority["primary_observation_id"] or authority["observation_id"]
                )
                batch_activity_ids = {
                    str(row["activity_id"])
                    for row in conn.execute(
                        """select activity_id from room_observation_batch_members
                           where batch_id = ?""",
                        (batch_id,),
                    ).fetchall()
                }
                if not batch_activity_ids:
                    batch_activity_ids.add(
                        str(
                            conn.execute(
                                "select activity_id from room_observations "
                                "where observation_id = ?",
                                (primary_observation_id,),
                            ).fetchone()[0]
                        )
                    )
                candidates: list[tuple[str, str, MemoryCandidateInput]] = []
                for advisory in advisories:
                    advisory_id = advisory.get("advisory_id")
                    fingerprint = advisory.get("fingerprint")
                    if not isinstance(advisory_id, str) or not advisory_id:
                        continue
                    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
                        fingerprint = sha256_json(
                            {
                                "advisory_id": advisory_id,
                                "proposal_type": advisory.get("proposal_type"),
                                "content": advisory.get("content"),
                                "source_refs": advisory.get("source_refs"),
                            }
                        ).removeprefix("sha256:")
                    prior = conn.execute(
                        """select advisory_fingerprint, status, candidate_digest
                           from room_memory_advisory_receipts
                           where attempt_id = ? and advisory_id = ?""",
                        (attempt_id, advisory_id),
                    ).fetchone()
                    if prior is not None:
                        if prior["advisory_fingerprint"] != fingerprint:
                            self._write_advisory_receipt_conn(
                                conn,
                                conversation_id=conversation_id,
                                attempt_id=attempt_id,
                                advisory_id=advisory_id,
                                fingerprint=fingerprint,
                                status="rejected",
                                reason_code="room_memory_advisory_conflict",
                                source_activity_ids=(),
                                candidate_digest=None,
                                stamp=stamp,
                            )
                        continue
                    proposal_type = advisory.get("proposal_type")
                    kind: Literal["room_fact", "project_rule"] | None
                    if proposal_type == "archive_write":
                        kind = "room_fact"
                    elif proposal_type == "core_promotion_request":
                        kind = "project_rule"
                    else:
                        kind = None
                    content = advisory.get("content")
                    refs = advisory.get("source_refs")
                    if (
                        kind is None
                        or not isinstance(content, str)
                        or not content.strip()
                        or not isinstance(refs, list)
                        or not refs
                        or len(refs) > 8
                    ):
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=advisory_id,
                            fingerprint=fingerprint,
                            status="rejected",
                            reason_code="memoryos_advisory_contract_invalid",
                            source_activity_ids=(),
                            candidate_digest=None,
                            stamp=stamp,
                        )
                        continue
                    source_activity_ids = self._resolve_external_source_ids_conn(
                        conn,
                        conversation_id=conversation_id,
                        source_refs=refs,
                    )
                    if not source_activity_ids:
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=advisory_id,
                            fingerprint=fingerprint,
                            status="rejected",
                            reason_code="room_memory_advisory_source_rejected",
                            source_activity_ids=(),
                            candidate_digest=None,
                            stamp=stamp,
                        )
                        continue
                    candidates.append(
                        (
                            advisory_id,
                            fingerprint,
                            MemoryCandidateInput(
                                kind=kind,
                                content=content.strip(),
                                source_activity_ids=tuple(source_activity_ids),
                            ),
                        )
                    )
                unique: list[MemoryCandidateInput] = []
                candidate_meta: dict[str, tuple[str, str, tuple[str, ...]]] = {}
                seen: set[str] = set()
                for advisory_id, fingerprint, item in candidates:
                    digest = sha256_json(
                        {
                            "conversation_id": conversation_id,
                            "author_participant_id": authority["participant_id"],
                            "kind": item.kind,
                            "content": item.content,
                            "source_activity_ids": tuple(sorted(item.source_activity_ids)),
                        }
                    )
                    if digest in seen:
                        continue
                    seen.add(digest)
                    existing = conn.execute(
                        """select 1 from room_memory_candidates
                           where conversation_id = ? and candidate_digest = ? limit 1""",
                        (conversation_id, digest),
                    ).fetchone()
                    if existing is None:
                        unique.append(item)
                        candidate_meta[digest] = (
                            advisory_id,
                            fingerprint,
                            tuple(sorted(item.source_activity_ids)),
                        )
                    else:
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=advisory_id,
                            fingerprint=fingerprint,
                            status="duplicate",
                            reason_code="room_memory_advisory_duplicate",
                            source_activity_ids=item.source_activity_ids,
                            candidate_digest=digest,
                            stamp=stamp,
                        )
                if not unique:
                    conn.commit()
                    return []
                result = record_memory_candidates_conn(
                    conn,
                    conversation_id=conversation_id,
                    author_participant_id=str(authority["participant_id"]),
                    source_observation_id=primary_observation_id,
                    source_batch_id=batch_id,
                    source_attempt_id=attempt_id,
                    batch_activity_ids=batch_activity_ids,
                    candidates=unique[:3],
                    stamp=stamp,
                    allow_external_sources=True,
                )
                for reference in result:
                    digest = str(reference["candidate_digest"])
                    meta = candidate_meta.get(digest)
                    if meta is not None:
                        self._write_advisory_receipt_conn(
                            conn,
                            conversation_id=conversation_id,
                            attempt_id=attempt_id,
                            advisory_id=meta[0],
                            fingerprint=meta[1],
                            status="accepted",
                            reason_code="room_memory_advisory_accepted",
                            source_activity_ids=meta[2],
                            candidate_digest=digest,
                            stamp=stamp,
                        )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def record_external_advisory_failure(
        self,
        *,
        conversation_id: str,
        attempt_id: str,
        reason_code: str,
        now: datetime | None = None,
    ) -> None:
        """Persist a safe bridge failure without changing recall authority."""

        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                self._write_advisory_receipt_conn(
                    conn,
                    conversation_id=conversation_id,
                    attempt_id=attempt_id,
                    advisory_id="__bridge__",
                    fingerprint=sha256_json({"attempt_id": attempt_id, "reason": reason_code}),
                    status="rejected",
                    reason_code=reason_code[:128],
                    source_activity_ids=(),
                    candidate_digest=None,
                    stamp=stamp,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _write_advisory_receipt_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        attempt_id: str,
        advisory_id: str,
        fingerprint: str,
        status: str,
        reason_code: str,
        source_activity_ids: Sequence[str],
        candidate_digest: str | None,
        stamp: str,
    ) -> None:
        existing = conn.execute(
            """select advisory_fingerprint from room_memory_advisory_receipts
               where attempt_id = ? and advisory_id = ?""",
            (attempt_id, advisory_id),
        ).fetchone()
        if existing is not None:
            return
        conn.execute(
            """insert into room_memory_advisory_receipts
               (receipt_id, conversation_id, attempt_id, advisory_id,
                advisory_fingerprint, status, reason_code, candidate_digest,
                source_activity_ids_json, created_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id("memory_advisory_receipt"),
                conversation_id,
                attempt_id,
                advisory_id[:256],
                fingerprint[:128],
                status,
                reason_code[:128],
                candidate_digest,
                json_dumps(list(source_activity_ids)[:8]),
                stamp,
                stamp,
            ),
        )

    def list_external_advisory_receipts(
        self, conversation_id: str, *, limit: int = 20
    ) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from room_memory_advisory_receipts
                   where conversation_id = ?
                   order by created_at desc, receipt_id desc limit ?""",
                (conversation_id, clean_limit),
            ).fetchall()
        return [
            {
                "schema_version": "room_memory_advisory_receipt/v1",
                "receipt_id": row["receipt_id"],
                "conversation_id": row["conversation_id"],
                "attempt_id": row["attempt_id"],
                "advisory_id": row["advisory_id"],
                "status": row["status"],
                "reason_code": row["reason_code"],
                "candidate_digest": row["candidate_digest"],
                "source_activity_ids": json_loads(row["source_activity_ids_json"], []),
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    @staticmethod
    def _resolve_external_source_ids_conn(
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
