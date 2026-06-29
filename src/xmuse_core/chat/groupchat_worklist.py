from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from xmuse_core.chat.models import GroupchatChain, GroupchatWorklistItem

_CHAIN_OPEN_STATUSES = {"open"}
_ITEM_ACTIVE_STATUSES = {"queued", "claimed"}
_ITEM_TERMINAL_STATUSES = {"completed", "blocked", "failed", "canceled"}


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


RouteKind = Literal["mention", "router", "handoff", "review_request"]


class GroupchatWorklistStore:
    def __init__(self, path: Path | str) -> None:
        from xmuse_core.chat.store import ChatStore

        self._path = Path(path)
        ChatStore(self._path)

    def create_chain(
        self,
        *,
        conversation_id: str,
        root_message_id: str,
        policy_id: str = "default-natural-groupchat",
        max_depth: int = 3,
        human_max_targets: int = 2,
        agent_max_targets: int = 1,
        pingpong_warn_after: int = 2,
        pingpong_block_after: int = 4,
    ) -> GroupchatChain:
        now = _utc_now()
        chain_id = _new_id("gchain")
        with self._connect() as conn:
            root = conn.execute(
                "select conversation_id from messages where id = ?",
                (root_message_id,),
            ).fetchone()
            if root is None or root["conversation_id"] != conversation_id:
                raise ValueError("root_message_conversation_mismatch")
            conn.execute(
                """
                insert into groupchat_chains (
                    chain_id, conversation_id, policy_id, root_message_id,
                    last_scanned_message_id, max_depth, human_max_targets,
                    agent_max_targets, pingpong_warn_after, pingpong_block_after,
                    status, status_reason, created_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', null, ?, ?)
                """,
                (
                    chain_id,
                    conversation_id,
                    policy_id,
                    root_message_id,
                    root_message_id,
                    max_depth,
                    human_max_targets,
                    agent_max_targets,
                    pingpong_warn_after,
                    pingpong_block_after,
                    now,
                    now,
                ),
            )
        return self.get_chain(chain_id)

    def get_chain(self, chain_id: str) -> GroupchatChain:
        with self._connect() as conn:
            row = conn.execute(
                "select * from groupchat_chains where chain_id = ?",
                (chain_id,),
            ).fetchone()
        if row is None:
            raise KeyError(chain_id)
        return self._chain_from_row(row)

    def list_chains(self, conversation_id: str) -> list[GroupchatChain]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from groupchat_chains
                where conversation_id = ?
                order by created_at asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._chain_from_row(row) for row in rows]

    def enqueue_route(
        self,
        *,
        chain_id: str,
        source_message_id: str,
        target_participant_id: str,
        route_kind: RouteKind,
        depth: int,
        source_participant_id: str | None = None,
    ) -> GroupchatWorklistItem:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                chain = self._chain_row(conn, chain_id)
                if chain["status"] not in _CHAIN_OPEN_STATUSES:
                    raise ValueError("groupchat_chain_not_open")
                source = conn.execute(
                    "select conversation_id from messages where id = ?",
                    (source_message_id,),
                ).fetchone()
                if source is None or source["conversation_id"] != chain["conversation_id"]:
                    raise ValueError("source_message_conversation_mismatch")

                target = conn.execute(
                    """
                    select participant_id, role
                    from participants
                    where participant_id = ?
                      and conversation_id = ?
                      and status = 'active'
                    """,
                    (target_participant_id, chain["conversation_id"]),
                ).fetchone()
                if target is None:
                    item_id = self._insert_item(
                        conn,
                        now=now,
                        chain=chain,
                        source_message_id=source_message_id,
                        source_participant_id=source_participant_id,
                        target_participant_id=target_participant_id,
                        target_role="unknown",
                        route_kind=route_kind,
                        depth=depth,
                        status="failed",
                        terminal_reason="target_participant_missing",
                    )
                    self._set_chain_status(
                        conn,
                        chain_id=chain_id,
                        status="failed",
                        status_reason="target_participant_missing",
                        now=now,
                    )
                    conn.commit()
                    return self.get_item(item_id)

                dedup_key = self.dedup_key(
                    conversation_id=chain["conversation_id"],
                    chain_id=chain_id,
                    source_message_id=source_message_id,
                    target_participant_id=target_participant_id,
                    route_kind=route_kind,
                )
                duplicate = conn.execute(
                    """
                    select * from groupchat_worklist
                    where chain_id = ?
                      and dedup_key = ?
                      and status in ('queued', 'claimed', 'completed')
                    order by created_at asc
                    limit 1
                    """,
                    (chain_id, dedup_key),
                ).fetchone()
                if duplicate is not None:
                    conn.commit()
                    return self._item_from_row(duplicate)

                if depth >= int(chain["max_depth"]):
                    item_id = self._insert_item(
                        conn,
                        now=now,
                        chain=chain,
                        source_message_id=source_message_id,
                        source_participant_id=source_participant_id,
                        target_participant_id=target_participant_id,
                        target_role=target["role"],
                        route_kind=route_kind,
                        depth=depth,
                        status="blocked",
                        dedup_key=dedup_key,
                        terminal_reason="depth_limit",
                    )
                    self._set_chain_status(
                        conn,
                        chain_id=chain_id,
                        status="blocked",
                        status_reason="depth_limit",
                        now=now,
                    )
                    conn.commit()
                    return self.get_item(item_id)

                item_id = self._insert_item(
                    conn,
                    now=now,
                    chain=chain,
                    source_message_id=source_message_id,
                    source_participant_id=source_participant_id,
                    target_participant_id=target_participant_id,
                    target_role=target["role"],
                    route_kind=route_kind,
                    depth=depth,
                    status="queued",
                    dedup_key=dedup_key,
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_item(item_id)

    def claim_next(
        self,
        *,
        owner: str,
        conversation_id: str | None = None,
        chain_id: str | None = None,
    ) -> GroupchatWorklistItem | None:
        now = _utc_now()
        where = ["w.status = 'queued'", "c.status = 'open'"]
        params: list[str] = []
        if conversation_id is not None:
            where.append("w.conversation_id = ?")
            params.append(conversation_id)
        if chain_id is not None:
            where.append("w.chain_id = ?")
            params.append(chain_id)
        with self._connect() as conn:
            conn.execute("begin immediate")
            row = conn.execute(
                f"""
                select w.*
                from groupchat_worklist w
                join groupchat_chains c on c.chain_id = w.chain_id
                where {" and ".join(where)}
                order by w.created_at asc
                limit 1
                """,
                tuple(params),
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            conn.execute(
                """
                update groupchat_worklist
                set status = 'claimed',
                    claim_owner = ?,
                    claimed_at = ?,
                    updated_at = ?
                where item_id = ? and status = 'queued'
                """,
                (owner, now, now, row["item_id"]),
            )
            conn.commit()
        return self.get_item(row["item_id"])

    def claim_and_link_next(
        self,
        *,
        owner: str,
        conversation_id: str | None = None,
        chain_id: str | None = None,
    ) -> GroupchatWorklistItem | None:
        now = _utc_now()
        where = ["w.status = 'queued'", "c.status = 'open'"]
        params: list[str] = []
        if conversation_id is not None:
            where.append("w.conversation_id = ?")
            params.append(conversation_id)
        if chain_id is not None:
            where.append("w.chain_id = ?")
            params.append(chain_id)
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    f"""
                    select w.*
                    from groupchat_worklist w
                    join groupchat_chains c on c.chain_id = w.chain_id
                    where {" and ".join(where)}
                    order by w.created_at asc
                    limit 1
                    """,
                    tuple(params),
                ).fetchone()
                if row is None:
                    conn.commit()
                    return None
                updated = conn.execute(
                    """
                    update groupchat_worklist
                    set status = 'claimed',
                        claim_owner = ?,
                        claimed_at = ?,
                        updated_at = ?
                    where item_id = ? and status = 'queued'
                    """,
                    (owner, now, now, row["item_id"]),
                ).rowcount
                if updated != 1:
                    raise ValueError("worklist_item_not_queued")
                inbox_item_id = self._insert_linked_inbox_item(conn, item=row, now=now)
                conn.execute(
                    """
                    update groupchat_worklist
                    set inbox_item_id = ?, updated_at = ?
                    where item_id = ? and status = 'claimed'
                    """,
                    (inbox_item_id, now, row["item_id"]),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_item(row["item_id"])

    def link_inbox_item(self, item_id: str, inbox_item_id: str) -> GroupchatWorklistItem:
        now = _utc_now()
        with self._connect() as conn:
            item = self._item_row(conn, item_id)
            inbox = conn.execute(
                "select * from chat_inbox_items where id = ?",
                (inbox_item_id,),
            ).fetchone()
            if inbox is None:
                raise ValueError("inbox_item_missing")
            self._validate_inbox_link(item=item, inbox=inbox)
            existing = conn.execute(
                """
                select item_id from groupchat_worklist
                where inbox_item_id = ? and item_id != ?
                """,
                (inbox_item_id, item_id),
            ).fetchone()
            if existing is not None:
                raise ValueError("inbox_item_already_linked")
            updated = conn.execute(
                """
                update groupchat_worklist
                set inbox_item_id = ?, updated_at = ?
                where item_id = ? and status = 'claimed'
                """,
                (inbox_item_id, now, item_id),
            ).rowcount
            if updated != 1:
                raise ValueError("worklist_item_not_claimed")
        return self.get_item(item_id)

    def complete_item(
        self,
        item_id: str,
        *,
        completed_message_id: str,
    ) -> GroupchatWorklistItem:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                item = self._item_row(conn, item_id)
                message = conn.execute(
                    "select conversation_id from messages where id = ?",
                    (completed_message_id,),
                ).fetchone()
                if message is None:
                    raise ValueError("completed_message_missing")
                if message["conversation_id"] != item["conversation_id"]:
                    raise ValueError("completed_message_conversation_mismatch")
                if item["inbox_item_id"] is None:
                    raise ValueError("worklist_item_missing_inbox_link")
                inbox = conn.execute(
                    "select * from chat_inbox_items where id = ?",
                    (item["inbox_item_id"],),
                ).fetchone()
                if inbox is None:
                    raise ValueError("inbox_item_missing")
                self._validate_inbox_link(item=item, inbox=inbox)
                if (
                    inbox["status"] != "read"
                    or inbox["responded_message_id"] != completed_message_id
                ):
                    raise ValueError("structured_writeback_missing")
                updated = conn.execute(
                    """
                    update groupchat_worklist
                    set status = 'completed',
                        completed_message_id = ?,
                        terminal_reason = null,
                        updated_at = ?
                    where item_id = ? and status = 'claimed'
                    """,
                    (completed_message_id, now, item_id),
                ).rowcount
                if updated != 1:
                    raise ValueError("worklist_item_not_claimed")
                self._complete_chain_if_exhausted(conn, chain_id=item["chain_id"], now=now)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_item(item_id)

    def block_item(self, item_id: str, *, reason: str) -> GroupchatWorklistItem:
        return self._terminal_item(item_id, status="blocked", reason=reason)

    def fail_item(self, item_id: str, *, reason: str) -> GroupchatWorklistItem:
        return self._terminal_item(item_id, status="failed", reason=reason)

    def cancel_item(self, item_id: str, *, reason: str = "canceled") -> GroupchatWorklistItem:
        return self._terminal_item(item_id, status="canceled", reason=reason)

    def get_item(self, item_id: str) -> GroupchatWorklistItem:
        with self._connect() as conn:
            row = conn.execute(
                "select * from groupchat_worklist where item_id = ?",
                (item_id,),
            ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return self._item_from_row(row)

    def list_items(self, chain_id: str) -> list[GroupchatWorklistItem]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select * from groupchat_worklist
                where chain_id = ?
                order by created_at asc
                """,
                (chain_id,),
            ).fetchall()
        return [self._item_from_row(row) for row in rows]

    def dedup_key(
        self,
        *,
        conversation_id: str,
        chain_id: str,
        source_message_id: str,
        target_participant_id: str,
        route_kind: str,
    ) -> str:
        return "|".join(
            (conversation_id, chain_id, source_message_id, target_participant_id, route_kind)
        )

    def _insert_item(
        self,
        conn: sqlite3.Connection,
        *,
        now: str,
        chain: sqlite3.Row,
        source_message_id: str,
        source_participant_id: str | None,
        target_participant_id: str,
        target_role: str,
        route_kind: str,
        depth: int,
        status: str,
        dedup_key: str | None = None,
        terminal_reason: str | None = None,
    ) -> str:
        item_id = _new_id("gwork")
        dedup_key = dedup_key or self.dedup_key(
            conversation_id=chain["conversation_id"],
            chain_id=chain["chain_id"],
            source_message_id=source_message_id,
            target_participant_id=target_participant_id,
            route_kind=route_kind,
        )
        conn.execute(
            """
            insert into groupchat_worklist (
                item_id, conversation_id, chain_id, policy_id, source_message_id,
                source_participant_id, target_participant_id, target_role,
                route_kind, status, depth, dedup_key, inbox_item_id, claim_owner,
                claimed_at, completed_message_id, terminal_reason, created_at,
                updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, null, null, null, ?, ?, ?)
            """,
            (
                item_id,
                chain["conversation_id"],
                chain["chain_id"],
                chain["policy_id"],
                source_message_id,
                source_participant_id,
                target_participant_id,
                target_role,
                route_kind,
                status,
                depth,
                dedup_key,
                terminal_reason,
                now,
                now,
            ),
        )
        return item_id

    def _terminal_item(
        self,
        item_id: str,
        *,
        status: Literal["blocked", "failed", "canceled"],
        reason: str,
    ) -> GroupchatWorklistItem:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                item = self._item_row(conn, item_id)
                updated = conn.execute(
                    """
                    update groupchat_worklist
                    set status = ?, terminal_reason = ?, updated_at = ?
                    where item_id = ? and status in ('queued', 'claimed')
                    """,
                    (status, reason, now, item_id),
                ).rowcount
                if updated != 1:
                    raise ValueError("worklist_item_not_active")
                if status in {"blocked", "failed", "canceled"}:
                    self._set_chain_status(
                        conn,
                        chain_id=item["chain_id"],
                        status=status,
                        status_reason=reason,
                        now=now,
                    )
                    self._cancel_queued_chain_siblings(
                        conn,
                        item=item,
                        reason=f"chain_{status}:{reason}",
                        now=now,
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self.get_item(item_id)

    def _complete_chain_if_exhausted(
        self,
        conn: sqlite3.Connection,
        *,
        chain_id: str,
        now: str,
    ) -> None:
        pending = conn.execute(
            """
            select count(*) as count
            from groupchat_worklist
            where chain_id = ? and status in ('queued', 'claimed')
            """,
            (chain_id,),
        ).fetchone()
        chain = self._chain_row(conn, chain_id)
        if (
            chain["status"] == "open"
            and pending is not None
            and int(pending["count"]) == 0
        ):
            self._set_chain_status(
                conn,
                chain_id=chain_id,
                status="completed",
                status_reason="route_exhausted",
                now=now,
            )

    def _set_chain_status(
        self,
        conn: sqlite3.Connection,
        *,
        chain_id: str,
        status: str,
        status_reason: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            update groupchat_chains
            set status = ?, status_reason = ?, updated_at = ?
            where chain_id = ?
            """,
            (status, status_reason, now, chain_id),
        )

    def _cancel_queued_chain_siblings(
        self,
        conn: sqlite3.Connection,
        *,
        item: sqlite3.Row,
        reason: str,
        now: str,
    ) -> None:
        conn.execute(
            """
            update groupchat_worklist
            set status = 'canceled',
                terminal_reason = ?,
                updated_at = ?
            where chain_id = ?
              and item_id != ?
              and status = 'queued'
            """,
            (reason, now, item["chain_id"], item["item_id"]),
        )

    def _insert_linked_inbox_item(
        self,
        conn: sqlite3.Connection,
        *,
        item: sqlite3.Row,
        now: str,
    ) -> str:
        inbox_item_id = _new_id("inbox")
        payload = {
            "groupchat_chain_id": item["chain_id"],
            "groupchat_worklist_item_id": item["item_id"],
            "route_kind": item["route_kind"],
            "depth": item["depth"],
        }
        conn.execute(
            """
            insert into chat_inbox_items (
                id, conversation_id, target_participant_id, target_role,
                target_address, sender_participant_id, sender_address,
                source_message_id, item_type, payload_json, status,
                created_at, updated_at
            )
            values (?, ?, ?, ?, ?, ?, ?, ?, 'groupchat_route', ?, 'unread', ?, ?)
            """,
            (
                inbox_item_id,
                item["conversation_id"],
                item["target_participant_id"],
                item["target_role"],
                f"@{item['target_role']}",
                item["source_participant_id"],
                (
                    f"@participant:{item['source_participant_id']}"
                    if item["source_participant_id"]
                    else "@groupchat-worklist"
                ),
                item["source_message_id"],
                json.dumps(payload),
                now,
                now,
            ),
        )
        return inbox_item_id

    def _validate_inbox_link(self, *, item: sqlite3.Row, inbox: sqlite3.Row) -> None:
        if (
            inbox["conversation_id"] != item["conversation_id"]
            or inbox["source_message_id"] != item["source_message_id"]
            or inbox["target_participant_id"] != item["target_participant_id"]
            or inbox["target_role"] != item["target_role"]
            or inbox["item_type"] != "groupchat_route"
        ):
            raise ValueError("inbox_item_worklist_mismatch")
        try:
            payload = json.loads(inbox["payload_json"])
        except json.JSONDecodeError as exc:
            raise ValueError("inbox_item_worklist_mismatch") from exc
        if (
            payload.get("groupchat_chain_id") != item["chain_id"]
            or payload.get("groupchat_worklist_item_id") != item["item_id"]
            or payload.get("route_kind") != item["route_kind"]
        ):
            raise ValueError("inbox_item_worklist_mismatch")

    def _chain_row(self, conn: sqlite3.Connection, chain_id: str) -> sqlite3.Row:
        row = conn.execute(
            "select * from groupchat_chains where chain_id = ?",
            (chain_id,),
        ).fetchone()
        if row is None:
            raise KeyError(chain_id)
        return row

    def _item_row(self, conn: sqlite3.Connection, item_id: str) -> sqlite3.Row:
        row = conn.execute(
            "select * from groupchat_worklist where item_id = ?",
            (item_id,),
        ).fetchone()
        if row is None:
            raise KeyError(item_id)
        return row

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _chain_from_row(self, row: sqlite3.Row) -> GroupchatChain:
        return GroupchatChain(**dict(row))

    def _item_from_row(self, row: sqlite3.Row) -> GroupchatWorklistItem:
        return GroupchatWorklistItem(**dict(row))


class GroupchatWorklistScheduler:
    def __init__(
        self,
        *,
        db_path: Path,
        scheduler_id: str,
    ) -> None:
        self._store = GroupchatWorklistStore(db_path)
        self._scheduler_id = scheduler_id

    def claim_and_link_one(
        self,
        *,
        conversation_id: str | None = None,
        chain_id: str | None = None,
    ) -> GroupchatWorklistItem | None:
        return self._store.claim_and_link_next(
            owner=self._scheduler_id,
            conversation_id=conversation_id,
            chain_id=chain_id,
        )

    def complete_from_writeback(
        self,
        item_id: str,
        *,
        completed_message_id: str,
    ) -> GroupchatWorklistItem:
        return self._store.complete_item(
            item_id,
            completed_message_id=completed_message_id,
        )

    def fail_missing_callback(self, item_id: str) -> GroupchatWorklistItem:
        return self._store.fail_item(item_id, reason="callback_missing")
