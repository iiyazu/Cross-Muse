"""Durable Room MemoryOS binding, session, and attachment state."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_memory_binding_conn import (
    binding_safe_view as _binding_safe_view,
)
from xmuse_core.chat.room_memory_binding_conn import binding_view as _binding_view
from xmuse_core.chat.room_memory_binding_conn import (
    ensure_binding_conn as _ensure_binding_conn,
)
from xmuse_core.chat.room_memory_common import (
    RoomMemoryStoreError,
    parse_timestamp,
    require_text,
    retry_not_before,
    timestamp,
)


class RoomMemoryBindingStore:
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
