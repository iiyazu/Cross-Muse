from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from xmuse_core.chat.models import ChatInboxItem


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(microsecond=0)


def _iso(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


class ChatInboxStore:
    def __init__(self, path: Path | str) -> None:
        from xmuse_core.chat.store import ChatStore

        self._path = Path(path)
        ChatStore(self._path)

    def create_item(
        self,
        *,
        conversation_id: str,
        target_participant_id: str | None,
        target_role: str | None,
        target_address: str,
        sender_participant_id: str | None,
        sender_address: str,
        source_message_id: str,
        item_type: str,
        payload: dict[str, Any],
    ) -> ChatInboxItem:
        now = _iso(_utc_now())
        item_id = f"inbox_{uuid.uuid4().hex}"
        with self._connect() as conn:
            source = conn.execute(
                "select conversation_id from messages where id = ?",
                (source_message_id,),
            ).fetchone()
            if source is None or source["conversation_id"] != conversation_id:
                raise ValueError("source_message_conversation_mismatch")
            conn.execute(
                """
                insert into chat_inbox_items (
                    id, conversation_id, target_participant_id, target_role,
                    target_address, sender_participant_id, sender_address,
                    source_message_id, item_type, payload_json, status,
                    created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'unread', ?, ?)
                """,
                (
                    item_id,
                    conversation_id,
                    target_participant_id,
                    target_role,
                    target_address,
                    sender_participant_id,
                    sender_address,
                    source_message_id,
                    item_type,
                    json.dumps(payload),
                    now,
                    now,
                ),
            )
        return self.get(item_id)

    def get(self, item_id: str) -> ChatInboxItem:
        with self._connect() as conn:
            row = conn.execute(
                "select * from chat_inbox_items where id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return self._from_row(row)

    def list_for_participant(
        self,
        *,
        conversation_id: str,
        participant_id: str,
        include_claimed: bool = True,
        limit: int = 20,
    ) -> list[ChatInboxItem]:
        statuses = ("unread", "claimed") if include_claimed else ("unread",)
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from chat_inbox_items
                where conversation_id = ?
                  and target_participant_id = ?
                  and status in ({placeholders})
                order by created_at asc
                limit ?
                """,
                (conversation_id, participant_id, *statuses, limit),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_by_conversation(
        self,
        conversation_id: str,
        *,
        include_terminal: bool = False,
    ) -> list[ChatInboxItem]:
        statuses = (
            ("unread", "claimed", "read", "failed")
            if include_terminal
            else ("unread", "claimed")
        )
        placeholders = ",".join("?" for _ in statuses)
        with self._connect() as conn:
            rows = conn.execute(
                f"""
                select * from chat_inbox_items
                where conversation_id = ? and status in ({placeholders})
                order by created_at asc
                """,
                (conversation_id, *statuses),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def claim_next(
        self,
        *,
        owner: str,
        claim_ttl_s: int = 120,
        item_id: str | None = None,
    ) -> ChatInboxItem | None:
        now_dt = _utc_now()
        now = _iso(now_dt)
        expires = _iso(now_dt + timedelta(seconds=claim_ttl_s))
        with self._connect() as conn:
            conn.execute("begin immediate")
            if item_id is None:
                row = conn.execute(
                    """
                    select * from chat_inbox_items
                    where status = 'unread'
                       or (
                           status = 'claimed'
                           and claim_expires_at is not null
                           and claim_expires_at <= ?
                       )
                    order by created_at asc
                    limit 1
                    """,
                    (now,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    select * from chat_inbox_items
                    where id = ?
                      and (
                          status = 'unread'
                          or (
                              status = 'claimed'
                              and claim_expires_at is not null
                              and claim_expires_at <= ?
                          )
                      )
                    order by created_at asc
                    limit 1
                    """,
                    (item_id, now),
                ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """
                update chat_inbox_items
                set status = 'claimed',
                    claim_owner = ?,
                    claimed_at = ?,
                    claim_expires_at = ?,
                    updated_at = ?
                where id = ?
                """,
                (owner, now, expires, now, row["id"]),
            )
            conn.commit()
        return self.get(row["id"])

    def mark_read(self, item_id: str, *, responded_message_id: str | None = None) -> ChatInboxItem:
        return self._mark(item_id, status="read", responded_message_id=responded_message_id)

    def mark_failed(self, item_id: str, *, reason: str) -> ChatInboxItem:
        return self._mark(item_id, status="failed", failure_reason=reason)

    def record_nudge_result(
        self,
        item_id: str,
        *,
        owner: str,
        success: bool,
        max_nudges: int = 3,
        reason: str = "",
    ) -> ChatInboxItem:
        now = _iso(_utc_now())
        with self._connect() as conn:
            conn.execute(
                """
                update chat_inbox_items
                set nudge_count = nudge_count + 1,
                    last_nudged_at = ?,
                    status = case
                        when ? then 'claimed'
                        when nudge_count + 1 >= ? then 'failed'
                        else 'unread'
                    end,
                    failure_reason = case
                        when ? then failure_reason
                        when nudge_count + 1 >= ? then ?
                        else failure_reason
                    end,
                    updated_at = ?
                where id = ? and claim_owner = ? and status = 'claimed'
                """,
                (
                    now,
                    1 if success else 0,
                    max_nudges,
                    1 if success else 0,
                    max_nudges,
                    reason or "max_nudges_exceeded",
                    now,
                    item_id,
                    owner,
                ),
            )
        return self.get(item_id)

    def _mark(
        self,
        item_id: str,
        *,
        status: str,
        responded_message_id: str | None = None,
        failure_reason: str | None = None,
    ) -> ChatInboxItem:
        now = _iso(_utc_now())
        with self._connect() as conn:
            conn.execute(
                """
                update chat_inbox_items
                set status = ?, responded_message_id = coalesce(?, responded_message_id),
                    failure_reason = coalesce(?, failure_reason), updated_at = ?
                where id = ?
                """,
                (status, responded_message_id, failure_reason, now, item_id),
            )
        return self.get(item_id)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _from_row(self, row: sqlite3.Row) -> ChatInboxItem:
        payload = dict(row)
        return ChatInboxItem(
            id=payload["id"],
            conversation_id=payload["conversation_id"],
            target_participant_id=payload["target_participant_id"],
            target_role=payload["target_role"],
            target_address=payload["target_address"],
            sender_participant_id=payload["sender_participant_id"],
            sender_address=payload["sender_address"],
            source_message_id=payload["source_message_id"],
            item_type=payload["item_type"],
            payload=json.loads(payload["payload_json"]),
            status=payload["status"],
            claim_owner=payload["claim_owner"],
            claimed_at=payload["claimed_at"],
            claim_expires_at=payload["claim_expires_at"],
            nudge_count=payload["nudge_count"],
            last_nudged_at=payload["last_nudged_at"],
            responded_message_id=payload["responded_message_id"],
            failure_reason=payload["failure_reason"],
            created_at=payload["created_at"],
            updated_at=payload["updated_at"],
        )
