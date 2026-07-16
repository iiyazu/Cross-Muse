"""Durable binding, attachment, and archive-delivery state for Room memory."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_binding_conn import (
    binding_safe_view as _binding_safe_view,
)
from xmuse_core.chat.room_memory_binding_conn import (
    binding_view as _binding_view,
)
from xmuse_core.chat.room_memory_binding_conn import (
    ensure_binding_conn as _ensure_binding_conn,
)
from xmuse_core.chat.room_memory_common import (
    RoomMemoryStoreError,
    json_loads,
    new_id,
    parse_timestamp,
    require_text,
    retry_not_before,
    sha256_text,
    timestamp,
)
from xmuse_core.chat.room_memory_contracts import require_digest, sha256_json


def queue_candidate_delivery_conn(
    conn: sqlite3.Connection, *, candidate: sqlite3.Row, stamp: str
) -> None:
    """Queue one approved candidate inside its caller-owned governance transaction."""

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


def _outbox_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "room_memory_outbox_item/v1",
        "outbox_id": row["outbox_id"],
        "conversation_id": row["conversation_id"],
        "activity_id": row["activity_id"],
        "candidate_id": row["candidate_id"],
        "target_scope": row["target_scope"],
        "state": row["state"],
        "attempt_count": int(row["attempt_count"]),
        "reason_code": row["reason_code"],
        "next_attempt_at": row["next_attempt_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "delivered_at": row["delivered_at"],
    }


def _message_outbox_view(row: sqlite3.Row) -> dict[str, Any]:
    """Return a browser-safe message outbox record.

    The lease token and MemoryOS session are intentionally absent.  The adapter
    receives those only from the claim call and never serializes them into a
    projection or a durable result.
    """

    return {
        "schema_version": "room_memory_message_outbox_item/v1",
        "message_outbox_id": row["message_outbox_id"],
        "conversation_id": row["conversation_id"],
        "activity_id": row["activity_id"],
        "external_id": row["external_id"],
        "state": row["state"],
        "attempt_count": int(row["attempt_count"]),
        "reason_code": row["reason_code"],
        "next_attempt_at": row["next_attempt_at"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "delivered_at": row["delivered_at"],
    }


class RoomMemoryDeliveryStore:
    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def ensure_binding(
        self,
        *,
        conversation_id: str,
        scope_type: Literal["room", "local_user", "project"] = "room",
        scope_key: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = _ensure_binding_conn(
                    conn,
                    conversation_id=conversation_id,
                    scope_type=scope_type,
                    scope_key=scope_key,
                    stamp=stamp,
                )
                result = _binding_view(row)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def get_binding(
        self, conversation_id: str, *, scope_type: str = "room"
    ) -> dict[str, Any] | None:
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                """select * from room_memory_bindings
                   where conversation_id = ? and scope_type = ?""",
                (conversation_id, scope_type),
            ).fetchone()
        return _binding_safe_view(row) if row is not None else None

    def get_binding_internal(
        self, conversation_id: str, *, scope_type: str = "room"
    ) -> dict[str, Any] | None:
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                """select * from room_memory_bindings
                   where conversation_id = ? and scope_type = ?""",
                (conversation_id, scope_type),
            ).fetchone()
        return _binding_view(row) if row is not None else None

    def list_pending_bindings(self, *, limit: int = 20) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        stamp = timestamp()
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                conversations = conn.execute(
                    """select distinct conversation_id from room_memory_outbox
                       where state in ('pending','failed') order by conversation_id limit ?""",
                    (clean_limit,),
                ).fetchall()
                for item in conversations:
                    _ensure_binding_conn(
                        conn,
                        conversation_id=str(item["conversation_id"]),
                        scope_type="room",
                        scope_key=None,
                        stamp=stamp,
                    )
                rows = conn.execute(
                    """select * from room_memory_bindings
                       where session_state <> 'bound' or attachment_state <> 'attached'
                       order by created_at, binding_id limit ?""",
                    (clean_limit,),
                ).fetchall()
                result = [_binding_view(row) for row in rows]
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def reserve_session_create(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request_id = require_text(client_request_id, "room_memory_session_request_id_required")
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                if row is None or row["scope_type"] != "room":
                    raise RoomMemoryStoreError("room_memory_binding_not_found")
                if row["session_state"] == "creating" and row["session_request_id"] == request_id:
                    conn.rollback()
                    return _binding_view(row)
                if row["session_state"] != "unbound" or int(row["revision"]) != expected_revision:
                    raise RoomMemoryStoreError("room_memory_session_guard_mismatch")
                conn.execute(
                    """update room_memory_bindings set session_state = 'creating',
                       session_request_id = ?, revision = revision + 1, updated_at = ?
                       where binding_id = ?""",
                    (request_id, stamp, binding_id),
                )
                updated = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                assert updated is not None
                result = _binding_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def complete_session_create(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        session_id: str | None,
        uncertain: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request_id = require_text(client_request_id, "room_memory_session_request_id_required")
        if not isinstance(uncertain, bool) or (session_id is None) == (not uncertain):
            raise RoomMemoryStoreError("room_memory_session_result_invalid")
        clean_session = (
            require_text(session_id, "room_memory_session_id_invalid")
            if session_id is not None
            else None
        )
        current = now or datetime.now(UTC)
        stamp = timestamp(current)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                if (
                    row is None
                    or row["session_state"] != "creating"
                    or row["session_request_id"] != request_id
                    or int(row["revision"]) != expected_revision
                ):
                    raise RoomMemoryStoreError("room_memory_session_guard_mismatch")
                state = "uncertain" if uncertain else "bound"
                retry_count = int(row["session_retry_count"]) + 1 if uncertain else 0
                retry_at = retry_not_before(current, retry_count) if uncertain else None
                conn.execute(
                    """update room_memory_bindings set session_state = ?, session_id = ?,
                       session_retry_count = ?, session_retry_not_before = ?,
                       revision = revision + 1, updated_at = ? where binding_id = ?""",
                    (state, clean_session, retry_count, retry_at, stamp, binding_id),
                )
                if clean_session is not None:
                    conn.execute(
                        """update room_memory_bindings set session_state = 'bound',
                           session_id = ?, session_retry_count = 0,
                           session_retry_not_before = null,
                           revision = revision + 1, updated_at = ?
                           where conversation_id = ? and binding_id <> ?""",
                        (clean_session, stamp, row["conversation_id"], binding_id),
                    )
                updated = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                assert updated is not None
                result = _binding_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def reserve_attachment(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request_id = require_text(client_request_id, "room_memory_attachment_request_id_required")
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                if row is None:
                    raise RoomMemoryStoreError("room_memory_binding_not_found")
                if (
                    row["attachment_state"] == "attaching"
                    and row["attachment_request_id"] == request_id
                ):
                    conn.rollback()
                    return _binding_view(row)
                if (
                    row["session_state"] != "bound"
                    or row["attachment_state"] != "pending"
                    or int(row["revision"]) != expected_revision
                ):
                    raise RoomMemoryStoreError("room_memory_attachment_guard_mismatch")
                conn.execute(
                    """update room_memory_bindings set attachment_state = 'attaching',
                       attachment_request_id = ?, revision = revision + 1, updated_at = ?
                       where binding_id = ?""",
                    (request_id, stamp, binding_id),
                )
                updated = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                assert updated is not None
                result = _binding_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def complete_attachment(
        self,
        *,
        binding_id: str,
        client_request_id: str,
        expected_revision: int,
        attachment_id: str | None,
        uncertain: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        request_id = require_text(client_request_id, "room_memory_attachment_request_id_required")
        if not isinstance(uncertain, bool) or (attachment_id is None) == (not uncertain):
            raise RoomMemoryStoreError("room_memory_attachment_result_invalid")
        clean_attachment = (
            require_text(attachment_id, "room_memory_attachment_id_invalid")
            if attachment_id is not None
            else None
        )
        current = now or datetime.now(UTC)
        stamp = timestamp(current)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                if (
                    row is None
                    or row["attachment_state"] != "attaching"
                    or row["attachment_request_id"] != request_id
                    or int(row["revision"]) != expected_revision
                ):
                    raise RoomMemoryStoreError("room_memory_attachment_guard_mismatch")
                retry_count = int(row["attachment_retry_count"]) + 1 if uncertain else 0
                retry_at = retry_not_before(current, retry_count) if uncertain else None
                conn.execute(
                    """update room_memory_bindings set attachment_state = ?, attachment_id = ?,
                       attachment_retry_count = ?, attachment_retry_not_before = ?,
                       revision = revision + 1, updated_at = ? where binding_id = ?""",
                    (
                        "uncertain" if uncertain else "attached",
                        clean_attachment,
                        retry_count,
                        retry_at,
                        stamp,
                        binding_id,
                    ),
                )
                updated = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                assert updated is not None
                result = _binding_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def reopen_uncertain_binding(
        self,
        *,
        binding_id: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise RoomMemoryStoreError("room_memory_binding_revision_invalid")
        current = now or datetime.now(UTC)
        stamp = timestamp(current)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                if row is None or int(row["revision"]) != expected_revision:
                    raise RoomMemoryStoreError("room_memory_binding_reopen_guard_mismatch")
                if row["session_state"] == "uncertain" and row["scope_type"] == "room":
                    not_before = row["session_retry_not_before"]
                    if not_before is not None and current < parse_timestamp(str(not_before)):
                        raise RoomMemoryStoreError("room_memory_binding_retry_not_ready")
                    conn.execute(
                        """update room_memory_bindings set session_state = 'unbound',
                           session_id = null, session_request_id = null,
                           session_retry_not_before = null,
                           revision = revision + 1, updated_at = ?
                           where binding_id = ?""",
                        (stamp, binding_id),
                    )
                elif row["attachment_state"] == "uncertain":
                    not_before = row["attachment_retry_not_before"]
                    if not_before is not None and current < parse_timestamp(str(not_before)):
                        raise RoomMemoryStoreError("room_memory_binding_retry_not_ready")
                    conn.execute(
                        """update room_memory_bindings set attachment_state = 'pending',
                           attachment_id = null, attachment_request_id = null,
                           attachment_retry_not_before = null,
                           revision = revision + 1, updated_at = ?
                           where binding_id = ?""",
                        (stamp, binding_id),
                    )
                else:
                    raise RoomMemoryStoreError("room_memory_binding_not_uncertain")
                updated = conn.execute(
                    "select * from room_memory_bindings where binding_id = ?", (binding_id,)
                ).fetchone()
                assert updated is not None
                result = _binding_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def list_outbox(self, conversation_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from room_memory_outbox where conversation_id = ?
                   order by created_at desc, outbox_id desc limit ?""",
                (conversation_id, clean_limit),
            ).fetchall()
        return [_outbox_view(row) for row in rows]

    def count_outbox_by_state(self, conversation_id: str) -> dict[str, int]:
        result = {state: 0 for state in ("pending", "claimed", "delivered", "failed", "conflict")}
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select state, count(*) count from room_memory_outbox
                   where conversation_id = ? group by state""",
                (conversation_id,),
            ).fetchall()
        for row in rows:
            result[str(row["state"])] = int(row["count"])
        return result

    def list_pending_message_outbox(self, *, limit: int = 20) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select * from room_memory_message_outbox
                   where state in ('pending','failed')
                     and (next_attempt_at is null or next_attempt_at <= datetime('now'))
                   order by created_at, message_outbox_id limit ?""",
                (clean_limit,),
            ).fetchall()
        return [_message_outbox_view(row) for row in rows]

    def count_message_outbox_by_state(self, conversation_id: str) -> dict[str, int]:
        result = {state: 0 for state in ("pending", "claimed", "delivered", "failed", "conflict")}
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select state, count(*) count from room_memory_message_outbox
                   where conversation_id = ? group by state""",
                (conversation_id,),
            ).fetchall()
        for row in rows:
            result[str(row["state"])] = int(row["count"])
        return result

    @staticmethod
    def _message_request_conn(
        conn: sqlite3.Connection,
        *,
        outbox: sqlite3.Row,
        session_id: str,
    ) -> dict[str, Any]:
        from xmuse_core.chat.room_memory_recall_store import activity_source_conn

        source = activity_source_conn(
            conn,
            conversation_id=str(outbox["conversation_id"]),
            activity_id=str(outbox["activity_id"]),
        )
        actor_kind = str(source["actor_kind"])
        role = "user" if actor_kind == "human" else "assistant"
        metadata: dict[str, Any] = {
            "schema_version": "xmuse_room_memory_message/v1",
            "conversation_id": source["conversation_id"],
            "activity_id": source["activity_id"],
            "room_seq": source["seq"],
            "correlation_id": source["correlation_id"],
            "activity_type": source["activity_type"],
            "speaker_kind": actor_kind,
        }
        if source.get("actor_participant_id") is not None:
            metadata["participant_id"] = source["actor_participant_id"]
        return {
            "external_id": outbox["external_id"],
            "role": role,
            "content": source["content"],
            "metadata": metadata,
            "session_id": session_id,
        }

    def claim_next_message_outbox(
        self,
        *,
        worker_id: str,
        lease_ttl_s: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        worker = require_text(worker_id, "room_memory_worker_id_required")
        if (
            isinstance(lease_ttl_s, bool)
            or not isinstance(lease_ttl_s, int)
            or not 5 <= lease_ttl_s <= 300
        ):
            raise RoomMemoryStoreError("room_memory_lease_ttl_invalid")
        current = now or datetime.now(UTC)
        stamp = timestamp(current)
        expires = timestamp(current + timedelta(seconds=lease_ttl_s))
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                expired = conn.execute(
                    """select * from room_memory_message_outbox
                       where state = 'claimed' and expires_at <= ?""",
                    (stamp,),
                ).fetchall()
                for item in expired:
                    conn.execute(
                        """update room_memory_message_deliveries set state = 'failed',
                           reason_code = 'memory_message_delivery_lease_expired',
                           finished_at = ?, updated_at = ?
                           where delivery_id = ? and state = 'claimed'""",
                        (stamp, stamp, item["current_delivery_id"]),
                    )
                    conn.execute(
                        """update room_memory_message_outbox set state = 'pending',
                           lease_owner = null, lease_token = null, acquired_at = null,
                           expires_at = null, current_delivery_id = null,
                           reason_code = 'memory_message_delivery_lease_expired',
                           next_attempt_at = null, updated_at = ?
                           where message_outbox_id = ?""",
                        (stamp, item["message_outbox_id"]),
                    )
                row = conn.execute(
                    """select o.* from room_memory_message_outbox o
                       join room_memory_bindings b
                         on b.conversation_id = o.conversation_id
                        and b.scope_type = 'room' and b.session_state = 'bound'
                       where o.state = 'pending'
                         and (o.next_attempt_at is null or o.next_attempt_at <= ?)
                       order by o.created_at, o.message_outbox_id limit 1""",
                    (stamp,),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return None
                binding = conn.execute(
                    """select * from room_memory_bindings
                       where conversation_id = ? and scope_type = 'room'""",
                    (row["conversation_id"],),
                ).fetchone()
                if binding is None or binding["session_state"] != "bound":
                    raise RoomMemoryStoreError("room_memory_session_unavailable")
                request = self._message_request_conn(
                    conn, outbox=row, session_id=str(binding["session_id"])
                )
                request_digest = sha256_json(request)
                token = uuid.uuid4().hex
                delivery_id = new_id("memory_message_delivery")
                attempt = int(row["attempt_count"]) + 1
                conn.execute(
                    """insert into room_memory_message_deliveries
                       (delivery_id, message_outbox_id, attempt_number, worker_id,
                        lease_token_sha256, state, request_digest, claimed_at, updated_at)
                       values (?, ?, ?, ?, ?, 'claimed', ?, ?, ?)""",
                    (
                        delivery_id,
                        row["message_outbox_id"],
                        attempt,
                        worker,
                        sha256_text(token),
                        request_digest,
                        stamp,
                        stamp,
                    ),
                )
                conn.execute(
                    """update room_memory_message_outbox set state = 'claimed',
                       attempt_count = ?, lease_owner = ?, lease_token = ?,
                       acquired_at = ?, expires_at = ?, current_delivery_id = ?,
                       reason_code = null, next_attempt_at = null, updated_at = ?
                       where message_outbox_id = ? and state = 'pending'""",
                    (
                        attempt,
                        worker,
                        token,
                        stamp,
                        expires,
                        delivery_id,
                        stamp,
                        row["message_outbox_id"],
                    ),
                )
                claimed = conn.execute(
                    """select * from room_memory_message_outbox
                       where message_outbox_id = ?""",
                    (row["message_outbox_id"],),
                ).fetchone()
                assert claimed is not None
                result = {
                    "schema_version": "room_memory_message_delivery_claim/v1",
                    "outbox": _message_outbox_view(claimed),
                    "delivery": {
                        "delivery_id": delivery_id,
                        "attempt_number": attempt,
                        "lease_token": token,
                        "expires_at": expires,
                        "request_digest": request_digest,
                    },
                    "message_request": request,
                }
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def complete_message_delivery(
        self,
        *,
        message_outbox_id: str,
        delivery_id: str,
        lease_token: str,
        status: Literal["delivered", "conflict", "failed"],
        request_digest: str,
        response_digest: str | None = None,
        memoryos_message_id: str | None = None,
        memoryos_session_id: str | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if status not in {"delivered", "conflict", "failed"}:
            raise RoomMemoryStoreError("room_memory_delivery_status_invalid")
        request_digest = require_digest(
            request_digest, "room_memory_delivery_request_digest_invalid"
        )
        if response_digest is not None:
            response_digest = require_digest(
                response_digest, "room_memory_delivery_response_digest_invalid"
            )
        if status == "delivered" and (
            memoryos_message_id is not None or memoryos_session_id is not None
        ):
            if (
                not isinstance(memoryos_message_id, str)
                or not memoryos_message_id
                or len(memoryos_message_id.encode("utf-8")) > 512
                or not isinstance(memoryos_session_id, str)
                or not memoryos_session_id
                or len(memoryos_session_id.encode("utf-8")) > 512
            ):
                raise RoomMemoryStoreError("room_memory_message_source_invalid")
        elif memoryos_message_id is not None or memoryos_session_id is not None:
            raise RoomMemoryStoreError("room_memory_message_source_invalid")
        if status != "delivered" and not reason_code:
            raise RoomMemoryStoreError("room_memory_delivery_reason_required")
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    """select o.*, d.state delivery_state,
                              d.request_digest authoritative_request_digest,
                              d.response_digest authoritative_response_digest,
                              d.memoryos_message_id authoritative_memoryos_message_id,
                              d.memoryos_session_id authoritative_memoryos_session_id,
                              d.reason_code delivery_reason_code, d.lease_token_sha256
                       from room_memory_message_outbox o
                       join room_memory_message_deliveries d
                         on d.delivery_id = o.current_delivery_id
                       where o.message_outbox_id = ? and d.delivery_id = ?""",
                    (message_outbox_id, delivery_id),
                ).fetchone()
                if (
                    row is not None
                    and row["delivery_state"] == status
                    and row["authoritative_request_digest"] == request_digest
                    and row["authoritative_response_digest"] == response_digest
                    and (
                        memoryos_message_id is None
                        or row["authoritative_memoryos_message_id"] == memoryos_message_id
                    )
                    and (
                        memoryos_session_id is None
                        or row["authoritative_memoryos_session_id"] == memoryos_session_id
                    )
                    and row["delivery_reason_code"] == reason_code
                ):
                    conn.rollback()
                    return _message_outbox_view(row)
                if (
                    row is None
                    or row["state"] != "claimed"
                    or row["delivery_state"] != "claimed"
                    or row["lease_token"] != lease_token
                    or row["lease_token_sha256"] != sha256_text(lease_token)
                    or row["authoritative_request_digest"] != request_digest
                ):
                    raise RoomMemoryStoreError("room_memory_delivery_lease_lost")
                next_attempt_at = (
                    retry_not_before(datetime.now(UTC), int(row["attempt_count"]))
                    if status == "failed"
                    else None
                )
                conn.execute(
                    """update room_memory_message_deliveries set state = ?,
                       response_digest = ?, memoryos_message_id = ?, memoryos_session_id = ?,
                       reason_code = ?, finished_at = ?, updated_at = ?
                       where delivery_id = ?""",
                    (
                        status,
                        response_digest,
                        memoryos_message_id,
                        memoryos_session_id,
                        reason_code,
                        stamp,
                        stamp,
                        delivery_id,
                    ),
                )
                conn.execute(
                    """update room_memory_message_outbox set state = ?, reason_code = ?,
                       lease_owner = null, lease_token = null, acquired_at = null,
                       expires_at = null, delivered_at = ?, next_attempt_at = ?, updated_at = ?
                       where message_outbox_id = ?""",
                    (
                        status,
                        reason_code,
                        stamp if status == "delivered" else None,
                        next_attempt_at,
                        stamp,
                        message_outbox_id,
                    ),
                )
                updated = conn.execute(
                    """select * from room_memory_message_outbox
                       where message_outbox_id = ?""",
                    (message_outbox_id,),
                ).fetchone()
                assert updated is not None
                result = _message_outbox_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def requeue_retryable_failed_message_outbox(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise RoomMemoryStoreError("room_memory_requeue_limit_invalid")
        clean_limit = max(1, min(limit, 100))
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                rows = conn.execute(
                    """select * from room_memory_message_outbox
                       where state = 'failed'
                         and (next_attempt_at is null or next_attempt_at <= ?)
                       order by coalesce(next_attempt_at, updated_at), message_outbox_id
                       limit ?""",
                    (stamp, clean_limit),
                ).fetchall()
                reopened: list[dict[str, Any]] = []
                for row in rows:
                    changed = conn.execute(
                        """update room_memory_message_outbox set state = 'pending',
                           reason_code = null, current_delivery_id = null,
                           next_attempt_at = null, updated_at = ?
                           where message_outbox_id = ? and state = 'failed'
                             and attempt_count = ?""",
                        (stamp, row["message_outbox_id"], row["attempt_count"]),
                    ).rowcount
                    if changed != 1:
                        raise RoomMemoryStoreError("room_memory_requeue_guard_mismatch")
                    updated = conn.execute(
                        """select * from room_memory_message_outbox
                           where message_outbox_id = ?""",
                        (row["message_outbox_id"],),
                    ).fetchone()
                    assert updated is not None
                    reopened.append(_message_outbox_view(updated))
                conn.commit()
                return reopened
            except Exception:
                conn.rollback()
                raise

    @staticmethod
    def _document_request_conn(
        conn: sqlite3.Connection, *, outbox: sqlite3.Row, session_id: str
    ) -> dict[str, Any]:
        # Local import makes the dependency direction explicit without making
        # schema initialization import the recall store eagerly.
        from xmuse_core.chat.room_memory_recall_store import activity_source_conn

        if outbox["activity_id"] is not None:
            source = activity_source_conn(
                conn,
                conversation_id=str(outbox["conversation_id"]),
                activity_id=str(outbox["activity_id"]),
            )
            content = source["content"]
            source_ids = [source["activity_id"]]
            title = f"Room activity {source['seq']}: {source['activity_type']}"
            metadata = {
                "schema_version": "xmuse_room_memory_document/v1",
                "conversation_id": outbox["conversation_id"],
                "activity_id": source["activity_id"],
                "room_seq": source["seq"],
                "correlation_id": source["correlation_id"],
            }
        else:
            candidate = conn.execute(
                "select * from room_memory_candidates where candidate_id = ?",
                (outbox["candidate_id"],),
            ).fetchone()
            if candidate is None or candidate["approval_state"] != "approved":
                raise RoomMemoryStoreError("room_memory_outbox_authority_invalid")
            content = candidate["content"]
            source_ids = json_loads(candidate["source_activity_ids_json"], [])
            title = f"Curated {str(candidate['kind']).replace('_', ' ')}"
            metadata = {
                "schema_version": "xmuse_room_memory_candidate_document/v1",
                "conversation_id": candidate["conversation_id"],
                "candidate_id": candidate["candidate_id"],
                "candidate_digest": candidate["candidate_digest"],
                "content_sha256": candidate["content_sha256"],
                "kind": candidate["kind"],
            }
        binding = conn.execute(
            """select * from room_memory_bindings
               where conversation_id = ? and scope_type = ?""",
            (outbox["conversation_id"], outbox["target_scope"]),
        ).fetchone()
        if binding is None or binding["session_state"] != "bound":
            raise RoomMemoryStoreError("room_memory_session_unavailable")
        refs = [
            {
                "source_type": "document",
                "source_id": activity_id,
                "session_id": session_id,
                "identity_scope": {
                    "session_id": session_id,
                    "archive_id": binding["archive_id"],
                },
                "metadata": {
                    "conversation_id": outbox["conversation_id"],
                    "activity_id": activity_id,
                },
            }
            for activity_id in source_ids
        ]
        return {
            "document_id": outbox["document_id"],
            "title": title,
            "content": content,
            "source_refs": refs,
            "identity": {"kind": "archive", "archive_id": binding["archive_id"]},
            "tags": ["xmuse", "room", str(outbox["target_scope"])],
            "metadata": metadata,
            "producer": "xmuse_room_archive_adapter/v1",
        }

    def claim_next_outbox(
        self,
        *,
        worker_id: str,
        lease_ttl_s: int = 30,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        worker = require_text(worker_id, "room_memory_worker_id_required")
        if (
            isinstance(lease_ttl_s, bool)
            or not isinstance(lease_ttl_s, int)
            or not 5 <= lease_ttl_s <= 300
        ):
            raise RoomMemoryStoreError("room_memory_lease_ttl_invalid")
        current = now or datetime.now(UTC)
        stamp = timestamp(current)
        expires = timestamp(current + timedelta(seconds=lease_ttl_s))
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                expired = conn.execute(
                    """select * from room_memory_outbox where state = 'claimed'
                       and expires_at <= ?""",
                    (stamp,),
                ).fetchall()
                for item in expired:
                    conn.execute(
                        """update room_memory_deliveries set state = 'failed',
                           reason_code = 'memory_delivery_lease_expired', finished_at = ?,
                           updated_at = ? where delivery_id = ? and state = 'claimed'""",
                        (stamp, stamp, item["current_delivery_id"]),
                    )
                    conn.execute(
                        """update room_memory_outbox set state = 'pending', lease_owner = null,
                           lease_token = null, acquired_at = null, expires_at = null,
                           current_delivery_id = null,
                           reason_code = 'memory_delivery_lease_expired',
                           next_attempt_at = null,
                           updated_at = ? where outbox_id = ?""",
                        (stamp, item["outbox_id"]),
                    )
                row = conn.execute(
                    """select o.* from room_memory_outbox o
                       join room_memory_bindings b
                         on b.conversation_id = o.conversation_id
                        and b.scope_type = 'room' and b.session_state = 'bound'
                       where o.state = 'pending'
                         and (o.next_attempt_at is null or o.next_attempt_at <= ?)
                       order by o.created_at, o.outbox_id limit 1""",
                    (stamp,),
                ).fetchone()
                if row is None:
                    conn.rollback()
                    return None
                target = _ensure_binding_conn(
                    conn,
                    conversation_id=str(row["conversation_id"]),
                    scope_type=str(row["target_scope"]),
                    scope_key=None,
                    stamp=stamp,
                )
                room_binding = conn.execute(
                    """select * from room_memory_bindings
                       where conversation_id = ? and scope_type = 'room'""",
                    (row["conversation_id"],),
                ).fetchone()
                if room_binding is None or room_binding["session_id"] is None:
                    raise RoomMemoryStoreError("room_memory_session_unavailable")
                if target["session_state"] != "bound":
                    raise RoomMemoryStoreError("room_memory_session_unavailable")
                request = self._document_request_conn(
                    conn, outbox=row, session_id=str(room_binding["session_id"])
                )
                request_digest = sha256_json(request)
                token = uuid.uuid4().hex
                delivery_id = new_id("memory_delivery")
                attempt = int(row["attempt_count"]) + 1
                conn.execute(
                    """insert into room_memory_deliveries
                       (delivery_id, outbox_id, attempt_number, worker_id,
                        lease_token_sha256, state, request_digest, claimed_at, updated_at)
                       values (?, ?, ?, ?, ?, 'claimed', ?, ?, ?)""",
                    (
                        delivery_id,
                        row["outbox_id"],
                        attempt,
                        worker,
                        sha256_text(token),
                        request_digest,
                        stamp,
                        stamp,
                    ),
                )
                conn.execute(
                    """update room_memory_outbox set state = 'claimed',
                       attempt_count = ?, lease_owner = ?, lease_token = ?, acquired_at = ?,
                       expires_at = ?, current_delivery_id = ?, reason_code = null,
                       next_attempt_at = null,
                       updated_at = ? where outbox_id = ? and state = 'pending'""",
                    (
                        attempt,
                        worker,
                        token,
                        stamp,
                        expires,
                        delivery_id,
                        stamp,
                        row["outbox_id"],
                    ),
                )
                claimed = conn.execute(
                    "select * from room_memory_outbox where outbox_id = ?",
                    (row["outbox_id"],),
                ).fetchone()
                assert claimed is not None
                result = {
                    "schema_version": "room_memory_delivery_claim/v1",
                    "outbox": _outbox_view(claimed),
                    "delivery": {
                        "delivery_id": delivery_id,
                        "attempt_number": attempt,
                        "lease_token": token,
                        "expires_at": expires,
                        "request_digest": request_digest,
                    },
                    "binding": _binding_view(target),
                    "document_request": request,
                }
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def complete_delivery(
        self,
        *,
        outbox_id: str,
        delivery_id: str,
        lease_token: str,
        status: Literal["delivered", "conflict", "failed"],
        request_digest: str,
        response_digest: str | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if status not in {"delivered", "conflict", "failed"}:
            raise RoomMemoryStoreError("room_memory_delivery_status_invalid")
        request_digest = require_digest(
            request_digest, "room_memory_delivery_request_digest_invalid"
        )
        if response_digest is not None:
            response_digest = require_digest(
                response_digest, "room_memory_delivery_response_digest_invalid"
            )
        if status != "delivered" and not reason_code:
            raise RoomMemoryStoreError("room_memory_delivery_reason_required")
        current = now or datetime.now(UTC)
        stamp = timestamp(current)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    """select o.*, d.state delivery_state,
                              d.request_digest authoritative_request_digest,
                              d.response_digest authoritative_response_digest,
                              d.reason_code delivery_reason_code, d.lease_token_sha256
                       from room_memory_outbox o
                       join room_memory_deliveries d on d.delivery_id = o.current_delivery_id
                       where o.outbox_id = ? and d.delivery_id = ?""",
                    (outbox_id, delivery_id),
                ).fetchone()
                if (
                    row is not None
                    and row["delivery_state"] == status
                    and row["authoritative_request_digest"] == request_digest
                    and row["authoritative_response_digest"] == response_digest
                    and row["delivery_reason_code"] == reason_code
                ):
                    conn.rollback()
                    return _outbox_view(row)
                if (
                    row is None
                    or row["state"] != "claimed"
                    or row["delivery_state"] != "claimed"
                    or row["lease_token"] != lease_token
                    or row["lease_token_sha256"] != sha256_text(lease_token)
                    or row["authoritative_request_digest"] != request_digest
                ):
                    raise RoomMemoryStoreError("room_memory_delivery_lease_lost")
                next_attempt_at = (
                    retry_not_before(current, int(row["attempt_count"]))
                    if status == "failed"
                    else None
                )
                conn.execute(
                    """update room_memory_deliveries set state = ?, response_digest = ?,
                       reason_code = ?, finished_at = ?, updated_at = ?
                       where delivery_id = ?""",
                    (status, response_digest, reason_code, stamp, stamp, delivery_id),
                )
                conn.execute(
                    """update room_memory_outbox set state = ?, reason_code = ?,
                       lease_owner = null, lease_token = null, acquired_at = null,
                       expires_at = null, delivered_at = ?, next_attempt_at = ?, updated_at = ?
                       where outbox_id = ?""",
                    (
                        status,
                        reason_code,
                        stamp if status == "delivered" else None,
                        next_attempt_at,
                        stamp,
                        outbox_id,
                    ),
                )
                if row["candidate_id"] is not None:
                    conn.execute(
                        """update room_memory_candidates set publish_state = ?,
                           revision = revision + 1, reason_code = ?, updated_at = ?
                           where candidate_id = ?""",
                        (status, reason_code, stamp, row["candidate_id"]),
                    )
                updated = conn.execute(
                    "select * from room_memory_outbox where outbox_id = ?", (outbox_id,)
                ).fetchone()
                assert updated is not None
                result = _outbox_view(updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def requeue_outbox(
        self,
        *,
        outbox_id: str,
        expected_state: Literal["failed", "conflict"],
        expected_attempt_count: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if expected_state not in {"failed", "conflict"}:
            raise RoomMemoryStoreError("room_memory_requeue_state_invalid")
        if (
            isinstance(expected_attempt_count, bool)
            or not isinstance(expected_attempt_count, int)
            or expected_attempt_count < 1
        ):
            raise RoomMemoryStoreError("room_memory_requeue_attempt_invalid")
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                changed = conn.execute(
                    """update room_memory_outbox set state = 'pending', reason_code = null,
                       current_delivery_id = null, next_attempt_at = null, updated_at = ?
                       where outbox_id = ? and state = ? and attempt_count = ?""",
                    (stamp, outbox_id, expected_state, expected_attempt_count),
                ).rowcount
                if changed != 1:
                    raise RoomMemoryStoreError("room_memory_requeue_guard_mismatch")
                row = conn.execute(
                    "select * from room_memory_outbox where outbox_id = ?", (outbox_id,)
                ).fetchone()
                assert row is not None
                if row["candidate_id"] is not None:
                    conn.execute(
                        """update room_memory_candidates set publish_state = 'queued',
                           revision = revision + 1, reason_code = null, updated_at = ?
                           where candidate_id = ?""",
                        (stamp, row["candidate_id"]),
                    )
                result = _outbox_view(row)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def requeue_retryable_failed_outbox(
        self,
        *,
        now: datetime | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if isinstance(limit, bool) or not isinstance(limit, int):
            raise RoomMemoryStoreError("room_memory_requeue_limit_invalid")
        clean_limit = max(1, min(limit, 100))
        current = now or datetime.now(UTC)
        stamp = timestamp(current)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                rows = conn.execute(
                    """select * from room_memory_outbox
                       where state = 'failed'
                         and (next_attempt_at is null or next_attempt_at <= ?)
                       order by coalesce(next_attempt_at, updated_at), outbox_id
                       limit ?""",
                    (stamp, clean_limit),
                ).fetchall()
                reopened: list[dict[str, Any]] = []
                for row in rows:
                    changed = conn.execute(
                        """update room_memory_outbox set state = 'pending',
                           reason_code = null, current_delivery_id = null,
                           next_attempt_at = null, updated_at = ?
                           where outbox_id = ? and state = 'failed'
                             and attempt_count = ?""",
                        (stamp, row["outbox_id"], row["attempt_count"]),
                    ).rowcount
                    if changed != 1:
                        raise RoomMemoryStoreError("room_memory_requeue_guard_mismatch")
                    if row["candidate_id"] is not None:
                        conn.execute(
                            """update room_memory_candidates set publish_state = 'queued',
                               revision = revision + 1, reason_code = null, updated_at = ?
                               where candidate_id = ? and publish_state = 'failed'""",
                            (stamp, row["candidate_id"]),
                        )
                    updated = conn.execute(
                        "select * from room_memory_outbox where outbox_id = ?",
                        (row["outbox_id"],),
                    ).fetchone()
                    assert updated is not None
                    reopened.append(_outbox_view(updated))
                conn.commit()
                return reopened
            except Exception:
                conn.rollback()
                raise
