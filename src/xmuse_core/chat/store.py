from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.models import (
    ChatMessage,
    Conversation,
    Proposal,
    ProposalStatus,
    ResolutionStatus,
    StructuredResolution,
)
from xmuse_core.chat.participant_store import _PREDEFINED_TEMPLATES
from xmuse_core.chat.participant_store import _new_id as _ps_new_id


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ChatStore:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def create_conversation(self, title: str) -> Conversation:
        conversation = Conversation(
            id=self._new_id("conv"),
            title=title,
            created_at=_utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                "insert into conversations (id, title, created_at) values (?, ?, ?)",
                (conversation.id, conversation.title, conversation.created_at),
            )
        return conversation

    def list_conversations(self) -> list[Conversation]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id, title, created_at
                from conversations
                order by rowid asc
                """
            ).fetchall()
        return [Conversation(**dict(row)) for row in rows]

    def add_message(
        self,
        conversation_id: str,
        author: str,
        role: str,
        content: str,
        *,
        envelope_type: str | None = "message",
        envelope_json: dict | None = None,
        mentions: list[str] | None = None,
        reply_to_message_id: str | None = None,
    ) -> ChatMessage:
        message = ChatMessage(
            id=self._new_id("msg"),
            conversation_id=conversation_id,
            author=author,
            role=role,
            content=content,
            created_at=_utc_now(),
            envelope_type=envelope_type,
            envelope_json=envelope_json or {},
            mentions=mentions or [],
            reply_to_message_id=reply_to_message_id,
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into messages (
                    id, conversation_id, author, role, content, created_at,
                    envelope_type, envelope_json, mentions_json, reply_to_message_id
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    message.id,
                    message.conversation_id,
                    message.author,
                    message.role,
                    message.content,
                    message.created_at,
                    message.envelope_type,
                    json.dumps(message.envelope_json),
                    json.dumps(message.mentions),
                    message.reply_to_message_id,
                ),
            )
        return message

    def list_messages(self, conversation_id: str) -> list[ChatMessage]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                select id, conversation_id, author, role, content, created_at,
                       envelope_type, envelope_json, mentions_json, reply_to_message_id
                from messages
                where conversation_id = ?
                order by rowid asc
                """,
                (conversation_id,),
            ).fetchall()
        return [self._message_from_row(row) for row in rows]

    def create_message_inbox_and_log(
        self,
        *,
        conversation_id: str,
        tool_name: str,
        caller_identity: str,
        client_request_id: str,
        author: str,
        role: str,
        content: str,
        envelope_type: str,
        envelope_json: dict,
        mentions: list[str],
        inbox_items: list[dict],
        reply_to_message_id: str | None = None,
        reply_to_inbox_item_id: str | None = None,
        reply_owner_participant_id: str | None = None,
        turn_budget_action: str = "none",
        turn_budget_reset_amount: int = 8,
    ) -> dict:
        now = _utc_now()
        message = ChatMessage(
            id=self._new_id("msg"),
            conversation_id=conversation_id,
            author=author,
            role=role,
            content=content,
            created_at=now,
            envelope_type=envelope_type,
            envelope_json=envelope_json,
            mentions=mentions,
            reply_to_message_id=reply_to_message_id,
        )
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    """
                    select result_json from chat_request_log
                    where conversation_id = ? and tool_name = ?
                      and caller_identity = ? and client_request_id = ?
                    """,
                    (conversation_id, tool_name, caller_identity, client_request_id),
                ).fetchone()
                if row is not None:
                    conn.commit()
                    return json.loads(row["result_json"])

                if turn_budget_action == "consume":
                    budget = conn.execute(
                        "select remaining from chat_turn_budgets where conversation_id = ?",
                        (conversation_id,),
                    ).fetchone()
                    remaining = int(budget["remaining"]) if budget is not None else 8
                    if remaining <= 0:
                        raise ValueError("turn_budget_exhausted")
                    conn.execute(
                        """
                        insert into chat_turn_budgets (conversation_id, remaining, updated_at)
                        values (?, ?, ?)
                        on conflict(conversation_id) do update set
                            remaining = excluded.remaining,
                            updated_at = excluded.updated_at
                        """,
                        (conversation_id, remaining - 1, now),
                    )
                elif turn_budget_action == "reset":
                    conn.execute(
                        """
                        insert into chat_turn_budgets (conversation_id, remaining, updated_at)
                        values (?, ?, ?)
                        on conflict(conversation_id) do update set
                            remaining = excluded.remaining,
                            updated_at = excluded.updated_at
                        """,
                        (conversation_id, turn_budget_reset_amount, now),
                    )
                elif turn_budget_action != "none":
                    raise ValueError(f"invalid turn_budget_action: {turn_budget_action}")

                conn.execute(
                    """
                    insert into messages (
                        id, conversation_id, author, role, content, created_at,
                        envelope_type, envelope_json, mentions_json, reply_to_message_id
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.id,
                        message.conversation_id,
                        message.author,
                        message.role,
                        message.content,
                        message.created_at,
                        message.envelope_type,
                        json.dumps(message.envelope_json),
                        json.dumps(message.mentions),
                        message.reply_to_message_id,
                    ),
                )

                created_items = []
                for item in inbox_items:
                    item_id = self._new_id("inbox")
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
                            item["target_participant_id"],
                            item.get("target_role"),
                            item["target_address"],
                            item.get("sender_participant_id"),
                            item["sender_address"],
                            message.id,
                            item["item_type"],
                            json.dumps(item["payload"]),
                            now,
                            now,
                        ),
                    )
                    created_items.append(
                        {
                            "id": item_id,
                            "conversation_id": conversation_id,
                            "source_message_id": message.id,
                            "payload": item["payload"],
                            "status": "unread",
                            "claim_owner": None,
                            "claimed_at": None,
                            "claim_expires_at": None,
                            "nudge_count": 0,
                            "last_nudged_at": None,
                            "responded_message_id": None,
                            "failure_reason": None,
                            "created_at": now,
                            "updated_at": now,
                            **item,
                        }
                    )

                if reply_to_inbox_item_id is not None:
                    updated = conn.execute(
                        """
                        update chat_inbox_items
                        set status = 'read', responded_message_id = ?, updated_at = ?
                        where id = ? and conversation_id = ? and target_participant_id = ?
                        """,
                        (
                            message.id,
                            now,
                            reply_to_inbox_item_id,
                            conversation_id,
                            reply_owner_participant_id,
                        ),
                    ).rowcount
                    if updated != 1:
                        raise ValueError("inbox_item_not_owned")

                result = {
                    "message": message.model_dump(mode="json"),
                    "inbox_items": created_items,
                }
                conn.execute(
                    """
                    insert into chat_request_log (
                        id, conversation_id, tool_name, caller_identity,
                        client_request_id, result_json, created_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_id("req"),
                        conversation_id,
                        tool_name,
                        caller_identity,
                        client_request_id,
                        json.dumps(result),
                        _utc_now(),
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return result

    def reset_turn_budget(self, conversation_id: str, *, amount: int = 8) -> None:
        now = _utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                insert into chat_turn_budgets (conversation_id, remaining, updated_at)
                values (?, ?, ?)
                on conflict(conversation_id) do update set
                    remaining = excluded.remaining,
                    updated_at = excluded.updated_at
                """,
                (conversation_id, amount, now),
            )

    def get_turn_budget_remaining(self, conversation_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute(
                "select remaining from chat_turn_budgets where conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return int(row["remaining"]) if row is not None else 8

    def set_turn_budget_remaining(self, conversation_id: str, remaining: int) -> None:
        self.reset_turn_budget(conversation_id, amount=remaining)

    def create_proposal(
        self,
        conversation_id: str,
        author: str,
        proposal_type: str,
        content: str,
        references: list[str],
    ) -> Proposal:
        proposal = Proposal(
            id=self._new_id("prop"),
            conversation_id=conversation_id,
            author=author,
            proposal_type=proposal_type,
            content=content,
            references=references,
            created_at=_utc_now(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                insert into proposals (
                    id,
                    conversation_id,
                    author,
                    proposal_type,
                    content,
                    references_json,
                    status,
                    created_at,
                    accepted_resolution_id
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposal.id,
                    proposal.conversation_id,
                    proposal.author,
                    proposal.proposal_type,
                    proposal.content,
                    json.dumps(proposal.references),
                    proposal.status.value,
                    proposal.created_at,
                    proposal.accepted_resolution_id,
                ),
            )
        return proposal

    def create_proposal_message_and_log(
        self,
        *,
        conversation_id: str,
        tool_name: str,
        caller_identity: str,
        client_request_id: str,
        author: str,
        proposal_type: str,
        content: str,
        references: list[str],
        message_content: str,
        envelope_json: dict[str, Any],
    ) -> dict[str, Any]:
        now = _utc_now()
        proposal = Proposal(
            id=self._new_id("prop"),
            conversation_id=conversation_id,
            author=author,
            proposal_type=proposal_type,
            content=content,
            references=references,
            created_at=now,
        )
        message_envelope = {**envelope_json, "proposal_id": proposal.id}
        message = ChatMessage(
            id=self._new_id("msg"),
            conversation_id=conversation_id,
            author=author,
            role="assistant",
            content=message_content,
            created_at=now,
            envelope_type="proposal",
            envelope_json=message_envelope,
            mentions=[],
        )
        with self._connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    """
                    select result_json from chat_request_log
                    where conversation_id = ? and tool_name = ?
                      and caller_identity = ? and client_request_id = ?
                    """,
                    (conversation_id, tool_name, caller_identity, client_request_id),
                ).fetchone()
                if row is not None:
                    conn.commit()
                    return json.loads(row["result_json"])

                conn.execute(
                    """
                    insert into proposals (
                        id, conversation_id, author, proposal_type, content,
                        references_json, status, created_at, accepted_resolution_id
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        proposal.id,
                        proposal.conversation_id,
                        proposal.author,
                        proposal.proposal_type,
                        proposal.content,
                        json.dumps(proposal.references),
                        proposal.status.value,
                        proposal.created_at,
                        proposal.accepted_resolution_id,
                    ),
                )
                conn.execute(
                    """
                    insert into messages (
                        id, conversation_id, author, role, content, created_at,
                        envelope_type, envelope_json, mentions_json, reply_to_message_id
                    )
                    values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        message.id,
                        message.conversation_id,
                        message.author,
                        message.role,
                        message.content,
                        message.created_at,
                        message.envelope_type,
                        json.dumps(message.envelope_json),
                        "[]",
                        None,
                    ),
                )
                result = {
                    "proposal": proposal.model_dump(mode="json"),
                    "message": message.model_dump(mode="json"),
                }
                conn.execute(
                    """
                    insert into chat_request_log (
                        id, conversation_id, tool_name, caller_identity,
                        client_request_id, result_json, created_at
                    )
                    values (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        self._new_id("req"),
                        conversation_id,
                        tool_name,
                        caller_identity,
                        client_request_id,
                        json.dumps(result),
                        now,
                    ),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return result

    def get_proposal(self, proposal_id: str) -> Proposal:
        with self._connect() as conn:
            row = conn.execute("select * from proposals where id = ?", (proposal_id,)).fetchone()
        if row is None:
            raise KeyError(f"unknown proposal: {proposal_id}")
        return self._proposal_from_row(row)

    def list_proposals(self, conversation_id: str | None = None) -> list[Proposal]:
        query = "select * from proposals"
        params: tuple[str, ...] = ()
        if conversation_id is not None:
            query += " where conversation_id = ?"
            params = (conversation_id,)
        query += " order by rowid asc"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._proposal_from_row(row) for row in rows]

    def approve_proposal(
        self,
        proposal_id: str,
        approved_by: list[str],
        approval_mode: str,
        goal_summary: str,
        content: dict | None = None,
    ) -> StructuredResolution:
        proposal = self.get_proposal(proposal_id)
        with self._connect() as conn:
            version = self._next_resolution_version(conn, proposal.conversation_id)
            resolution_id = self._new_id("res")
            resolution_content = self._content_for_approved_proposal(
                proposal,
                content=content,
                resolution_id=resolution_id,
            )
            resolution = StructuredResolution(
                id=resolution_id,
                conversation_id=proposal.conversation_id,
                version=version,
                status=ResolutionStatus.APPROVED,
                derived_from_proposal_ids=[proposal.id],
                approved_by=approved_by,
                approval_mode=approval_mode,
                goal_summary=goal_summary,
                content=resolution_content,
                created_at=_utc_now(),
            )
            conn.execute(
                """
                insert into resolutions (
                    id,
                    conversation_id,
                    version,
                    status,
                    derived_from_proposal_ids_json,
                    approved_by_json,
                    approval_mode,
                    goal_summary,
                    content_json,
                    created_at,
                    superseded_by_resolution_id
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution.id,
                    resolution.conversation_id,
                    resolution.version,
                    resolution.status.value,
                    json.dumps(resolution.derived_from_proposal_ids),
                    json.dumps(resolution.approved_by),
                    resolution.approval_mode,
                    resolution.goal_summary,
                    json.dumps(resolution_content),
                    resolution.created_at,
                    resolution.superseded_by_resolution_id,
                ),
            )
            conn.execute(
                """
                update proposals
                set status = ?, accepted_resolution_id = ?
                where id = ?
                """,
                (ProposalStatus.ACCEPTED.value, resolution.id, proposal.id),
            )
            self._supersede_revised_blueprint_target(
                conn,
                resolution_content=resolution_content,
                resolution_id=resolution.id,
            )
        return resolution

    def _content_for_approved_proposal(
        self,
        proposal: Proposal,
        *,
        content: dict | None,
        resolution_id: str,
    ) -> dict:
        if proposal.proposal_type == "mission_blueprint":
            content = self._mission_blueprint_resolution_content(proposal)
        else:
            content = content or {}
        return self._content_for_approved_resolution(content, resolution_id=resolution_id)

    def _mission_blueprint_resolution_content(self, proposal: Proposal) -> dict:
        try:
            proposal_payload = json.loads(proposal.content)
        except json.JSONDecodeError:
            proposal_payload = {}
        if isinstance(proposal_payload, dict):
            resolution_content = proposal_payload.get("resolution_content")
            if (
                isinstance(resolution_content, dict)
                and resolution_content.get("type") == "mission_blueprint"
            ):
                return self._mission_blueprint_content_only(resolution_content)
            if proposal_payload.get("type") == "mission_blueprint":
                return self._mission_blueprint_content_only(proposal_payload)
        return {"type": "mission_blueprint", "title": proposal.content, "body": proposal.content}

    def _mission_blueprint_content_only(self, content: dict) -> dict:
        blueprint = {"type": "mission_blueprint"}
        for key in (
            "title",
            "body",
            "acceptance_criteria",
            "proposal_blueprint_ref",
            "revision_of",
            "references",
        ):
            if key in content:
                blueprint[key] = content[key]
        return blueprint

    def _content_for_approved_resolution(
        self,
        content: dict,
        *,
        resolution_id: str,
    ) -> dict:
        if content.get("type") != "mission_blueprint":
            return content
        approved = dict(content)
        approved["blueprint_ref"] = f"resolution:{resolution_id}:mission_blueprint"
        return approved

    def _supersede_revised_blueprint_target(
        self,
        conn: sqlite3.Connection,
        *,
        resolution_content: dict[str, Any],
        resolution_id: str,
    ) -> None:
        if resolution_content.get("type") != "mission_blueprint":
            return
        revision_of = resolution_content.get("revision_of")
        if not isinstance(revision_of, str) or not revision_of.strip():
            return
        prior_resolution_id = self._resolution_id_from_blueprint_ref(revision_of.strip())
        conn.execute(
            """
            update resolutions
            set status = ?, superseded_by_resolution_id = ?
            where id = ?
            """,
            (ResolutionStatus.SUPERSEDED.value, resolution_id, prior_resolution_id),
        )

    def _resolution_id_from_blueprint_ref(self, blueprint_ref: str) -> str:
        prefix = "resolution:"
        suffix = ":mission_blueprint"
        if not blueprint_ref.startswith(prefix) or not blueprint_ref.endswith(suffix):
            raise ValueError(f"invalid mission blueprint ref: {blueprint_ref}")
        resolution_id = blueprint_ref.removeprefix(prefix).removesuffix(suffix)
        if not resolution_id:
            raise ValueError(f"invalid mission blueprint ref: {blueprint_ref}")
        return resolution_id

    def create_resolution_version(
        self,
        prior_resolution_id: str,
        approved_by: list[str],
        approval_mode: str,
        goal_summary: str,
        content: dict | None = None,
    ) -> StructuredResolution:
        prior = self.get_resolution(prior_resolution_id)
        with self._connect() as conn:
            resolution = StructuredResolution(
                id=self._new_id("res"),
                conversation_id=prior.conversation_id,
                version=prior.version + 1,
                status=ResolutionStatus.APPROVED,
                derived_from_proposal_ids=list(prior.derived_from_proposal_ids),
                approved_by=approved_by,
                approval_mode=approval_mode,
                goal_summary=goal_summary,
                content=prior.content if content is None else content,
                created_at=_utc_now(),
            )
            conn.execute(
                """
                insert into resolutions (
                    id,
                    conversation_id,
                    version,
                    status,
                    derived_from_proposal_ids_json,
                    approved_by_json,
                    approval_mode,
                    goal_summary,
                    content_json,
                    created_at,
                    superseded_by_resolution_id
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    resolution.id,
                    resolution.conversation_id,
                    resolution.version,
                    resolution.status.value,
                    json.dumps(resolution.derived_from_proposal_ids),
                    json.dumps(resolution.approved_by),
                    resolution.approval_mode,
                    resolution.goal_summary,
                    json.dumps(resolution.content),
                    resolution.created_at,
                    resolution.superseded_by_resolution_id,
                ),
            )
            conn.execute(
                """
                update resolutions
                set status = ?, superseded_by_resolution_id = ?
                where id = ?
                """,
                (ResolutionStatus.SUPERSEDED.value, resolution.id, prior.id),
            )
        return resolution

    def get_resolution(self, resolution_id: str) -> StructuredResolution:
        with self._connect() as conn:
            row = conn.execute(
                "select * from resolutions where id = ?",
                (resolution_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"unknown resolution: {resolution_id}")
        return self._resolution_from_row(row)

    def list_resolutions(self, conversation_id: str | None = None) -> list[StructuredResolution]:
        query = "select * from resolutions"
        params: tuple[str, ...] = ()
        if conversation_id is not None:
            query += " where conversation_id = ?"
            params = (conversation_id,)
        query += " order by conversation_id asc, version asc"
        with self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
        return [self._resolution_from_row(row) for row in rows]

    def get_logged_request_result(
        self,
        *,
        conversation_id: str,
        tool_name: str,
        caller_identity: str,
        client_request_id: str,
    ) -> dict | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                select result_json from chat_request_log
                where conversation_id = ? and tool_name = ?
                  and caller_identity = ? and client_request_id = ?
                """,
                (conversation_id, tool_name, caller_identity, client_request_id),
            ).fetchone()
        return json.loads(row["result_json"]) if row is not None else None

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        conn.execute("pragma foreign_keys = on")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                create table if not exists conversations (
                    id text primary key,
                    title text not null,
                    created_at text not null
                );

                create table if not exists messages (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    author text not null,
                    role text not null,
                    content text not null,
                    created_at text not null
                );

                create table if not exists proposals (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    author text not null,
                    proposal_type text not null,
                    content text not null,
                    references_json text not null,
                    status text not null,
                    created_at text not null,
                    accepted_resolution_id text
                );

                create table if not exists resolutions (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    version integer not null,
                    status text not null,
                    derived_from_proposal_ids_json text not null,
                    approved_by_json text not null,
                    approval_mode text not null,
                    goal_summary text not null,
                    content_json text not null default '{}',
                    created_at text not null,
                    superseded_by_resolution_id text,
                    unique(conversation_id, version)
                );

                create table if not exists participants (
                    participant_id text primary key,
                    conversation_id text not null references conversations(id),
                    role text not null,
                    display_name text not null,
                    cli_kind text not null,
                    model text not null,
                    role_template_id text,
                    status text not null,
                    last_seen_at text,
                    created_at text not null
                );

                create table if not exists role_templates (
                    id text primary key,
                    slug text not null unique,
                    display_name text not null,
                    prompt text not null,
                    cli_kind text not null,
                    default_model text not null,
                    predefined integer not null default 0,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists peer_forks (
                    fork_id text primary key,
                    conversation_id text not null references conversations(id),
                    source_peer_id text not null references participants(participant_id),
                    new_peer_id text not null unique references participants(participant_id),
                    prompt_delta text not null,
                    inherited_refs_json text not null,
                    model_policy_json text not null,
                    feature_scope_id text,
                    fork_reason text not null,
                    created_at text not null
                );
                """
            )
            self._ensure_column(conn, "resolutions", "content_json", "text not null default '{}'")
            self._ensure_column(conn, "messages", "envelope_type", "text")
            self._ensure_column(conn, "messages", "envelope_json", "text")
            self._ensure_column(conn, "messages", "mentions_json", "text")
            self._ensure_column(conn, "messages", "reply_to_message_id", "text")
            conn.executescript(
                """
                create table if not exists chat_inbox_items (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    target_participant_id text,
                    target_role text,
                    target_address text not null,
                    sender_participant_id text,
                    sender_address text not null,
                    source_message_id text not null references messages(id),
                    item_type text not null,
                    payload_json text not null,
                    status text not null,
                    claim_owner text,
                    claimed_at text,
                    claim_expires_at text,
                    nudge_count integer not null default 0,
                    last_nudged_at text,
                    responded_message_id text,
                    failure_reason text,
                    created_at text not null,
                    updated_at text not null
                );

                create index if not exists idx_chat_inbox_conversation_status_created
                    on chat_inbox_items(conversation_id, status, created_at);
                create index if not exists idx_chat_inbox_target_address_status_created
                    on chat_inbox_items(target_address, status, created_at);
                create index if not exists idx_chat_inbox_target_participant_status_created
                    on chat_inbox_items(target_participant_id, status, created_at);

                create table if not exists chat_request_log (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    tool_name text not null,
                    caller_identity text not null,
                    client_request_id text not null,
                    result_json text not null,
                    created_at text not null,
                    unique(conversation_id, tool_name, caller_identity, client_request_id)
                );

                create table if not exists chat_turn_budgets (
                    conversation_id text primary key references conversations(id),
                    remaining integer not null,
                    updated_at text not null
                );

                create table if not exists chat_streams (
                    id text primary key,
                    conversation_id text not null references conversations(id),
                    author text not null,
                    role text not null,
                    request_id text,
                    source_inbox_item_id text,
                    content text not null default '',
                    status text not null,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists bootstrap_drafts (
                    draft_id text primary key,
                    conversation_id text not null,
                    payload_json text not null,
                    status text not null,
                    created_at text not null,
                    updated_at text not null
                );

                create table if not exists bootstrap_proposals (
                    proposal_id text primary key,
                    draft_id text not null,
                    conversation_id text not null,
                    payload_json text not null,
                    validation_status text not null,
                    created_at text not null
                );

                create table if not exists bootstrap_applications (
                    apply_id text primary key,
                    draft_id text not null,
                    proposal_id text not null,
                    conversation_id text not null,
                    payload_json text not null,
                    status text not null,
                    created_at text not null
                );
                """
            )
        self._seed_role_templates()

    def _seed_role_templates(self) -> None:
        now = _utc_now()
        with self._connect() as conn:
            for tpl in _PREDEFINED_TEMPLATES:
                existing = conn.execute(
                    "select id from role_templates where slug = ?",
                    (tpl["slug"],),
                ).fetchone()
                if existing is not None:
                    continue
                conn.execute(
                    """
                    insert into role_templates (
                        id, slug, display_name, prompt, cli_kind,
                        default_model, predefined, created_at, updated_at
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        _ps_new_id("tmpl"),
                        tpl["slug"],
                        tpl["display_name"],
                        tpl["prompt"],
                        tpl["cli_kind"],
                        tpl["default_model"],
                        1,  # predefined = true
                        now,
                        now,
                    ),
                )

    def _message_from_row(self, row: sqlite3.Row) -> ChatMessage:
        payload = dict(row)
        envelope_json = payload.get("envelope_json")
        mentions_json = payload.get("mentions_json")
        return ChatMessage(
            id=payload["id"],
            conversation_id=payload["conversation_id"],
            author=payload["author"],
            role=payload["role"],
            content=payload["content"],
            created_at=payload["created_at"],
            envelope_type=payload.get("envelope_type"),
            envelope_json=json.loads(envelope_json) if envelope_json else None,
            mentions=json.loads(mentions_json) if mentions_json else [],
            reply_to_message_id=payload.get("reply_to_message_id"),
        )

    def _proposal_from_row(self, row: sqlite3.Row) -> Proposal:
        payload = dict(row)
        return Proposal(
            id=payload["id"],
            conversation_id=payload["conversation_id"],
            author=payload["author"],
            proposal_type=payload["proposal_type"],
            content=payload["content"],
            references=json.loads(payload["references_json"]),
            status=ProposalStatus(payload["status"]),
            created_at=payload["created_at"],
            accepted_resolution_id=payload["accepted_resolution_id"],
        )

    def _resolution_from_row(self, row: sqlite3.Row) -> StructuredResolution:
        payload = dict(row)
        return StructuredResolution(
            id=payload["id"],
            conversation_id=payload["conversation_id"],
            version=payload["version"],
            status=ResolutionStatus(payload["status"]),
            derived_from_proposal_ids=json.loads(payload["derived_from_proposal_ids_json"]),
            approved_by=json.loads(payload["approved_by_json"]),
            approval_mode=payload["approval_mode"],
            goal_summary=payload["goal_summary"],
            content=json.loads(payload.get("content_json") or "{}"),
            created_at=payload["created_at"],
            superseded_by_resolution_id=payload["superseded_by_resolution_id"],
        )

    def _next_resolution_version(self, conn: sqlite3.Connection, conversation_id: str) -> int:
        row = conn.execute(
            """
            select coalesce(max(version), 0) as max_version
            from resolutions
            where conversation_id = ?
            """,
            (conversation_id,),
        ).fetchone()
        return int(row["max_version"]) + 1

    def _new_id(self, prefix: str) -> str:
        return f"{prefix}_{uuid.uuid4().hex}"

    def _ensure_column(
        self, conn: sqlite3.Connection, table_name: str, column_name: str, definition: str
    ) -> None:
        rows = conn.execute(f"pragma table_info({table_name})").fetchall()
        existing = {str(row["name"]) for row in rows}
        if column_name not in existing:
            conn.execute(f"alter table {table_name} add column {column_name} {definition}")
