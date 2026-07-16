"""Durable candidate governance for source-backed Room memory.

Memory candidates are created only inside the caller-owned Room outcome
transaction.  Operator resolution uses its own guarded transaction and records
only a safe action receipt; candidate content remains confined to the authority
row and the bounded Room memory projection.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import FRONTEND_EVENT_PROOF_BOUNDARY, RoomDatabase
from xmuse_core.chat.room_memory_common import (
    MEMORY_CANDIDATE_SCOPE_BY_KIND,
    RoomMemoryStoreError,
    json_dumps,
    json_loads,
    new_id,
    require_text,
    sha256_text,
    timestamp,
)
from xmuse_core.chat.room_memory_contracts import (
    MemoryCandidateInput,
    require_digest,
    sha256_json,
)
from xmuse_core.chat.room_memory_delivery_store import queue_candidate_delivery_conn


def _causal_scope_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    batch_activity_ids: set[str],
) -> set[str]:
    if not batch_activity_ids:
        raise RoomMemoryStoreError("room_memory_candidate_sources_invalid")
    allowed: set[str] = set()
    frontier = set(batch_activity_ids)
    for _ in range(32):
        if not frontier or len(allowed) > 128:
            break
        placeholders = ",".join("?" for _ in frontier)
        rows = conn.execute(
            f"""select activity_id, causation_id from room_activities
                where conversation_id = ? and activity_id in ({placeholders})""",
            (conversation_id, *sorted(frontier)),
        ).fetchall()
        found = {str(row["activity_id"]) for row in rows}
        if found != frontier:
            raise RoomMemoryStoreError("room_memory_candidate_sources_invalid")
        allowed.update(found)
        causes = {str(row["causation_id"]) for row in rows}
        if not causes:
            break
        cause_placeholders = ",".join("?" for _ in causes)
        ancestors = {
            str(row["activity_id"])
            for row in conn.execute(
                f"""select activity_id from room_activities
                    where conversation_id = ? and activity_id in ({cause_placeholders})""",
                (conversation_id, *sorted(causes)),
            )
        }
        frontier = ancestors - allowed
    return allowed


def _candidate_safe_reference(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "room_memory_candidate_ref/v1",
        "candidate_id": row["candidate_id"],
        "kind": row["kind"],
        "candidate_digest": row["candidate_digest"],
        "content_sha256": row["content_sha256"],
        "source_activity_ids": json_loads(row["source_activity_ids_json"], []),
        "approval_state": row["approval_state"],
        "publish_state": row["publish_state"],
        "target_scope": row["target_scope"],
        "revision": int(row["revision"]),
    }


def _candidate_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "room_memory_candidate/v1",
        "candidate_id": row["candidate_id"],
        "conversation_id": row["conversation_id"],
        "author_participant_id": row["author_participant_id"],
        "kind": row["kind"],
        "content": row["content"],
        "content_sha256": row["content_sha256"],
        "candidate_digest": row["candidate_digest"],
        "source_activity_ids": json_loads(row["source_activity_ids_json"], []),
        "approval_state": row["approval_state"],
        "approval_mode": row["approval_mode"],
        "publish_state": row["publish_state"],
        "target_scope": row["target_scope"],
        "revision": int(row["revision"]),
        "reason_code": row["reason_code"],
        "created_at": row["created_at"],
        "resolved_at": row["resolved_at"],
        "updated_at": row["updated_at"],
    }


def record_memory_candidates_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    author_participant_id: str,
    source_observation_id: str,
    source_batch_id: str | None,
    source_attempt_id: str,
    batch_activity_ids: set[str],
    candidates: Sequence[MemoryCandidateInput],
    stamp: str,
    allow_external_sources: bool = False,
) -> list[dict[str, Any]]:
    """Persist candidate authority in the caller's Room outcome transaction."""

    if not conn.in_transaction:
        raise RoomMemoryStoreError("room_memory_candidate_transaction_required")
    if not candidates:
        return []
    if source_batch_id is None:
        raise RoomMemoryStoreError("room_memory_candidate_batch_required")
    authority = conn.execute(
        """select o.conversation_id, o.participant_id, o.current_attempt_id,
                  b.primary_observation_id
           from room_observations o
           join room_observation_batches b on b.batch_id = ?
           where o.observation_id = ?""",
        (source_batch_id, source_observation_id),
    ).fetchone()
    if (
        authority is None
        or authority["conversation_id"] != conversation_id
        or authority["participant_id"] != author_participant_id
        or authority["current_attempt_id"] != source_attempt_id
        or authority["primary_observation_id"] != source_observation_id
    ):
        raise RoomMemoryStoreError("room_memory_candidate_authority_invalid")
    allowed_sources = _causal_scope_conn(
        conn,
        conversation_id=conversation_id,
        batch_activity_ids=batch_activity_ids,
    )
    references: list[dict[str, Any]] = []
    for item in candidates:
        sources = tuple(sorted(item.source_activity_ids))
        if allow_external_sources:
            # A MemoryOS advisory may cite an older Room activity recovered by
            # recall.  It is still admitted only after this transaction proves
            # every reference is a visible activity in this same Room; the
            # causal batch rule remains the default for Agent-authored facts.
            placeholders = ",".join("?" for _ in sources)
            visible = {
                str(row["activity_id"])
                for row in conn.execute(
                    f"""select activity_id from room_activities
                        where conversation_id = ? and visibility = 'room'
                          and activity_id in ({placeholders})""",
                    (conversation_id, *sources),
                ).fetchall()
            }
            if visible != set(sources):
                raise RoomMemoryStoreError("room_memory_candidate_source_forbidden")
        elif not set(sources).issubset(allowed_sources):
            raise RoomMemoryStoreError("room_memory_candidate_source_forbidden")
        content_sha256 = sha256_text(item.content)
        candidate_id = new_id("memory_candidate")
        digest = sha256_json(
            {
                "conversation_id": conversation_id,
                "author_participant_id": author_participant_id,
                "kind": item.kind,
                "content": item.content,
                "source_activity_ids": sources,
            }
        )
        automatic = item.kind in {"room_fact", "room_decision"}
        approval_state = "approved" if automatic else "pending"
        publish_state = "queued" if automatic else "not_queued"
        target_scope = MEMORY_CANDIDATE_SCOPE_BY_KIND[item.kind]
        conn.execute(
            """insert into room_memory_candidates
               (candidate_id, conversation_id, author_participant_id,
                source_observation_id, source_batch_id, source_attempt_id, kind,
                content, content_sha256, source_activity_ids_json, candidate_digest,
                approval_state, approval_mode, publish_state, target_scope, revision,
                reason_code, created_at, resolved_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)""",
            (
                candidate_id,
                conversation_id,
                author_participant_id,
                source_observation_id,
                source_batch_id,
                source_attempt_id,
                item.kind,
                item.content,
                content_sha256,
                json_dumps(list(sources)),
                digest,
                approval_state,
                "automatic" if automatic else "operator",
                publish_state,
                target_scope,
                "source_validated_auto_approval" if automatic else "operator_approval_required",
                stamp,
                stamp if automatic else None,
                stamp,
            ),
        )
        row = conn.execute(
            "select * from room_memory_candidates where candidate_id = ?", (candidate_id,)
        ).fetchone()
        assert row is not None
        if automatic:
            queue_candidate_delivery_conn(conn, candidate=row, stamp=stamp)
        references.append(_candidate_safe_reference(row))
    return references


class RoomMemoryGovernanceStore:
    """Candidate query and guarded local-operator command boundary."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def get_candidate(self, candidate_id: str) -> dict[str, Any] | None:
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                "select * from room_memory_candidates where candidate_id = ?", (candidate_id,)
            ).fetchone()
        return _candidate_view(row) if row is not None else None

    def list_candidates(
        self,
        conversation_id: str,
        *,
        approval_state: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        if approval_state is not None and approval_state not in {
            "pending",
            "approved",
            "rejected",
        }:
            raise RoomMemoryStoreError("room_memory_approval_state_invalid")
        clean_limit = max(1, min(int(limit), 100))
        where = "conversation_id = ?"
        params: list[Any] = [conversation_id]
        if approval_state is not None:
            where += " and approval_state = ?"
            params.append(approval_state)
        params.append(clean_limit)
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                f"""select * from room_memory_candidates where {where}
                    order by created_at desc, candidate_id desc limit ?""",
                params,
            ).fetchall()
        return [_candidate_view(row) for row in rows]

    def count_candidates(
        self,
        conversation_id: str,
        *,
        approval_state: str | None = None,
    ) -> int:
        if approval_state is not None and approval_state not in {
            "pending",
            "approved",
            "rejected",
        }:
            raise RoomMemoryStoreError("room_memory_approval_state_invalid")
        sql = "select count(*) from room_memory_candidates where conversation_id = ?"
        params: list[Any] = [conversation_id]
        if approval_state is not None:
            sql += " and approval_state = ?"
            params.append(approval_state)
        with self._database.connect(readonly=True) as conn:
            return int(conn.execute(sql, params).fetchone()[0])

    @staticmethod
    def _record_event_conn(
        conn: sqlite3.Connection,
        *,
        conversation_id: str,
        candidate_id: str,
        change: str,
        client_action_id: str,
        stamp: str,
    ) -> None:
        sequence = int(
            conn.execute(
                "select coalesce(max(seq), 0) + 1 from chat_frontend_events "
                "where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        )
        conn.execute(
            """insert into chat_frontend_events
               (event_id, conversation_id, seq, event_type, resource_ref,
                source_authority, source_ref, payload_json, client_action_id, created_at,
                projection_only, proof_boundary)
               values (?, ?, ?, 'projection.changed', ?, 'chat.db', ?, ?, ?, ?, 1, ?)""",
            (
                new_id("frontend_event"),
                conversation_id,
                sequence,
                f"room:memory-candidate:{candidate_id}",
                f"room:memory-candidate:{candidate_id}",
                json_dumps({"change": change, "candidate_id": candidate_id}),
                client_action_id,
                stamp,
                FRONTEND_EVENT_PROOF_BOUNDARY,
            ),
        )

    def resolve_candidate(
        self,
        *,
        candidate_id: str,
        decision: Literal["approve", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if decision not in {"approve", "reject"}:
            raise RoomMemoryStoreError("room_memory_candidate_decision_invalid")
        action_id = require_text(client_action_id, "room_memory_client_action_id_required")
        operator = require_text(operator_identity, "room_memory_operator_identity_required")
        digest = require_digest(expected_candidate_digest, "room_memory_candidate_digest_invalid")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise RoomMemoryStoreError("room_memory_candidate_revision_invalid")
        fingerprint = sha256_json(
            {
                "candidate_id": candidate_id,
                "decision": decision,
                "expected_candidate_digest": digest,
                "expected_revision": expected_revision,
            }
        )
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                prior = conn.execute(
                    """select * from room_memory_candidate_actions
                       where operator_identity = ? and client_action_id = ?""",
                    (operator, action_id),
                ).fetchone()
                if prior is not None:
                    if prior["request_fingerprint"] != fingerprint:
                        raise RoomMemoryStoreError("room_memory_action_idempotency_conflict")
                    conn.rollback()
                    if prior["status"] != "applied":
                        raise RoomMemoryStoreError(
                            str(prior["reason_code"] or "room_memory_candidate_guard_mismatch")
                        )
                    replay = conn.execute(
                        "select * from room_memory_candidates where candidate_id = ?",
                        (prior["candidate_id"],),
                    ).fetchone()
                    if replay is None:
                        raise RoomMemoryStoreError("room_memory_candidate_not_found")
                    return _candidate_view(replay)
                row = conn.execute(
                    "select * from room_memory_candidates where candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                if row is None:
                    raise RoomMemoryStoreError("room_memory_candidate_not_found")
                if (
                    row["approval_state"] != "pending"
                    or row["candidate_digest"] != digest
                    or int(row["revision"]) != expected_revision
                ):
                    raise RoomMemoryStoreError("room_memory_candidate_guard_mismatch")
                approval = "approved" if decision == "approve" else "rejected"
                publish = "queued" if decision == "approve" else "not_queued"
                reason = "operator_approved" if decision == "approve" else "operator_rejected"
                conn.execute(
                    """update room_memory_candidates set approval_state = ?,
                       publish_state = ?, revision = revision + 1, reason_code = ?,
                       resolved_by = ?, resolution_client_action_id = ?,
                       resolution_request_fingerprint = ?, resolved_at = ?, updated_at = ?
                       where candidate_id = ?""",
                    (
                        approval,
                        publish,
                        reason,
                        operator,
                        action_id,
                        fingerprint,
                        stamp,
                        stamp,
                        candidate_id,
                    ),
                )
                updated = conn.execute(
                    "select * from room_memory_candidates where candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                assert updated is not None
                if decision == "approve":
                    queue_candidate_delivery_conn(conn, candidate=updated, stamp=stamp)
                result = _candidate_view(updated)
                safe_result = _candidate_safe_reference(updated)
                conn.execute(
                    """insert into room_memory_candidate_actions
                       (action_id, candidate_id, conversation_id, client_action_id,
                        operator_identity, request_fingerprint, decision, status,
                        reason_code, result_json, created_at)
                       values (?, ?, ?, ?, ?, ?, ?, 'applied', null, ?, ?)""",
                    (
                        new_id("memory_action"),
                        candidate_id,
                        row["conversation_id"],
                        action_id,
                        operator,
                        fingerprint,
                        decision,
                        json_dumps(safe_result),
                        stamp,
                    ),
                )
                self._record_event_conn(
                    conn,
                    conversation_id=str(row["conversation_id"]),
                    candidate_id=candidate_id,
                    change=f"memory.candidate_{approval}",
                    client_action_id=action_id,
                    stamp=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise
