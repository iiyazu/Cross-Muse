from __future__ import annotations

import sqlite3

import pytest

from xmuse_core.chat.groupchat_worklist import (
    GroupchatWorklistScheduler,
    GroupchatWorklistStore,
)
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore


def _conversation_with_groupchat_roster(tmp_path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A1 kernel")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    review = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    critic = participants.add(
        conversation_id=conversation.id,
        role="critic",
        display_name="Critic GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    root = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please discuss the next A1 boundary.",
    )
    return db, chat, conversation, root, architect, review, critic


def _writeback_reply(
    chat: ChatStore,
    *,
    conversation_id: str,
    participant_id: str,
    inbox_item_id: str,
    content: str,
    client_request_id: str = "structured-writeback-1",
) -> str:
    result = chat.create_message_inbox_and_log(
        conversation_id=conversation_id,
        tool_name="chat_post_message",
        caller_identity=participant_id,
        client_request_id=client_request_id,
        author=participant_id,
        role="assistant",
        content=content,
        envelope_type="message",
        envelope_json={
            "writeback_path": "groupchat_worklist_test",
            "reply_to_inbox_item_id": inbox_item_id,
        },
        mentions=[],
        inbox_items=[],
        reply_to_inbox_item_id=inbox_item_id,
        reply_owner_participant_id=participant_id,
    )
    return result["message"]["id"]


def test_groupchat_worklist_claims_links_and_completes_from_durable_writeback(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    item = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )

    linked = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).claim_and_link_one(chain_id=chain.chain_id)

    assert linked is not None
    assert linked.item_id == item.item_id
    assert linked.status == "claimed"
    assert linked.claim_owner == "groupchat-a1"
    assert linked.inbox_item_id is not None

    inbox_item = ChatInboxStore(db).get(linked.inbox_item_id)
    assert inbox_item.item_type == "groupchat_route"
    assert inbox_item.target_participant_id == architect.participant_id
    assert inbox_item.payload["groupchat_worklist_item_id"] == item.item_id

    reply_id = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=linked.inbox_item_id,
        content="@critic I propose we inspect the worklist boundary first.",
    )
    completed = store.complete_item(item.item_id, completed_message_id=reply_id)

    assert completed.status == "completed"
    assert completed.completed_message_id == reply_id
    assert store.get_chain(chain.chain_id).status == "completed"
    assert store.get_chain(chain.chain_id).status_reason == "route_exhausted"


def test_groupchat_worklist_schema_records_migration_marker(tmp_path):
    db, _chat, _conversation, _root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )

    with sqlite3.connect(db) as conn:
        versions = {
            row[0]
            for row in conn.execute(
                "select version from schema_migrations",
            ).fetchall()
        }

    assert "groupchat_worklist_a1" in versions


def test_depth_limit_blocks_route_without_schedulable_provider_work(tmp_path):
    db, _chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_depth=1,
    )

    blocked = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="handoff",
        depth=1,
    )

    assert blocked.status == "blocked"
    assert blocked.terminal_reason == "depth_limit"
    assert store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id) is None
    assert store.get_chain(chain.chain_id).status == "blocked"
    assert store.get_chain(chain.chain_id).status_reason == "depth_limit"


def test_duplicate_route_returns_existing_schedulable_item(tmp_path):
    db, _chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    second = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )

    assert second.item_id == first.item_id
    assert len(store.list_items(chain.chain_id)) == 1


def test_link_inbox_item_rejects_wrong_target_payload(tmp_path):
    db, _chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    item = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    claimed = store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id)
    wrong_inbox = ChatInboxStore(db).create_item(
        conversation_id=conversation.id,
        target_participant_id=review.participant_id,
        target_role=review.role,
        target_address="@review",
        sender_participant_id=None,
        sender_address="@groupchat-worklist",
        source_message_id=root.id,
        item_type="groupchat_route",
        payload={
            "groupchat_chain_id": chain.chain_id,
            "groupchat_worklist_item_id": item.item_id,
            "route_kind": "mention",
        },
    )

    assert claimed is not None
    with pytest.raises(ValueError, match="inbox_item_worklist_mismatch"):
        store.link_inbox_item(item.item_id, wrong_inbox.id)


def test_worklist_completion_requires_structured_writeback(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    item = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )
    linked = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).claim_and_link_one(chain_id=chain.chain_id)

    assert linked is not None
    with pytest.raises(ValueError, match="completed_message_missing"):
        store.complete_item(item.item_id, completed_message_id="provider_stdout_only")
    unrelated = chat.add_message(
        conversation_id=conversation.id,
        author="architect",
        role="assistant",
        content="Durable but unrelated message.",
    )
    with pytest.raises(ValueError, match="structured_writeback_missing"):
        store.complete_item(item.item_id, completed_message_id=unrelated.id)

    failed = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).fail_missing_callback(item.item_id)

    assert failed.status == "failed"
    assert failed.terminal_reason == "callback_missing"
    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "callback_missing"


def test_missing_target_is_durable_failed_audit_item_not_schedulable(tmp_path):
    db, _chat, conversation, root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    failed = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id="part_missing",
        route_kind="mention",
        depth=0,
    )

    assert failed.status == "failed"
    assert failed.target_participant_id == "part_missing"
    assert failed.terminal_reason == "target_participant_missing"
    assert store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id) is None
    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "target_participant_missing"


def test_failed_chain_is_not_overwritten_by_later_completion(tmp_path):
    db, chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    second = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=review.participant_id,
        route_kind="review_request",
        depth=0,
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")
    first_linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    second_linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)

    assert first_linked is not None
    assert second_linked is not None
    store.fail_item(second.item_id, reason="callback_missing")
    reply_id = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=first_linked.inbox_item_id,
        content="Durable writeback for the first item.",
        client_request_id="structured-writeback-first",
    )
    store.complete_item(first.item_id, completed_message_id=reply_id)

    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "callback_missing"


def test_terminal_chain_cancels_queued_siblings_and_stops_claiming(tmp_path):
    db, _chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    second = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=review.participant_id,
        route_kind="review_request",
        depth=0,
    )

    store.fail_item(first.item_id, reason="callback_missing")

    assert store.get_item(second.item_id).status == "canceled"
    assert store.get_item(second.item_id).terminal_reason == "chain_failed:callback_missing"
    assert store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id) is None
