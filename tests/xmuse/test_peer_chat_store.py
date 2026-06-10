import sqlite3
from pathlib import Path

import pytest

from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.store import ChatStore


def test_chat_store_migrates_existing_messages_table(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(
            """
            create table conversations (
                id text primary key,
                title text not null,
                created_at text not null
            );
            create table messages (
                id text primary key,
                conversation_id text not null references conversations(id),
                author text not null,
                role text not null,
                content text not null,
                created_at text not null
            );
            insert into conversations values ('conv_1', 'Legacy', '2026-05-29T00:00:00Z');
            insert into messages values (
                'msg_1', 'conv_1', 'Human', 'human', 'hello @architect', '2026-05-29T00:00:01Z'
            );
            """
        )

    store = ChatStore(db)
    message = store.list_messages("conv_1")[0]

    assert message.envelope_type is None
    assert message.envelope_json is None
    assert message.mentions == []
    assert message.reply_to_message_id is None


def test_inbox_store_creates_claims_and_marks_items(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Peer chat")
    message = chat.add_message(conv.id, "Human", "human", "hello @architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")

    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id="part_architect",
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )
    claimed = inbox.claim_next(owner="scheduler-1", claim_ttl_s=120)
    assert claimed is not None
    assert claimed.id == item.id
    assert claimed.status == "claimed"
    assert claimed.claim_owner == "scheduler-1"

    updated = inbox.mark_read(item.id, responded_message_id="msg_reply")
    assert updated.status == "read"
    assert updated.responded_message_id == "msg_reply"


def test_inbox_store_rejects_cross_conversation_source_message(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    source_conv = chat.create_conversation("Source")
    target_conv = chat.create_conversation("Target")
    message = chat.add_message(source_conv.id, "Human", "human", "hello @architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")

    with pytest.raises(ValueError, match="source_message_conversation_mismatch"):
        inbox.create_item(
            conversation_id=target_conv.id,
            target_participant_id="part_architect",
            target_role="architect",
            target_address="@architect",
            sender_participant_id=None,
            sender_address="@human",
            source_message_id=message.id,
            item_type="mention",
            payload={"content": message.content},
        )


def test_nudge_result_preserves_terminal_read_or_failed_items(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Peer chat")
    message = chat.add_message(conv.id, "Human", "human", "hello @architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id="part_architect",
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )
    inbox.claim_next(owner="scheduler-1")

    read_item = inbox.mark_read(item.id, responded_message_id="msg_reply")
    late_success = inbox.record_nudge_result(item.id, owner="scheduler-1", success=True)

    assert read_item.status == "read"
    assert late_success.status == "read"
    assert late_success.responded_message_id == "msg_reply"

    failed_item = inbox.mark_failed(item.id, reason="manual_failure")
    late_failure = inbox.record_nudge_result(
        item.id,
        owner="scheduler-1",
        success=False,
        max_nudges=99,
    )

    assert failed_item.status == "failed"
    assert late_failure.status == "failed"
    assert late_failure.failure_reason == "manual_failure"
