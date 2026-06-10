from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.store import ChatStore
from xmuse_core.sidecar.replay_exporter import ChatReplayExporter, export_all_conversations
from xmuse_core.sidecar.replay_packet import IngestIntent


@pytest.fixture
def chat_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "chat.db"
    store = ChatStore(db_path)
    store.create_conversation("V6 Test Conversation")
    conv_id = store.list_conversations()[0].id

    store.add_message(
        conversation_id=conv_id,
        author="human",
        role="user",
        content="We need to implement feature X",
        envelope_type="message",
    )
    store.add_message(
        conversation_id=conv_id,
        author="architect",
        role="assistant",
        content="Let me analyze the requirements",
        envelope_type="message",
    )
    store.add_message(
        conversation_id=conv_id,
        author="architect",
        role="assistant",
        content="Here is my blueprint",
        envelope_type="message",
        envelope_json={"escalation": "mission_blueprint", "title": "Feature X Blueprint"},
    )

    prop = store.create_proposal(
        conversation_id=conv_id,
        author="architect",
        proposal_type="mission_blueprint",
        content="Mission blueprint for feature X",
        references=["msg_001"],
    )

    store.approve_proposal(
        proposal_id=prop.id,
        approved_by=["human"],
        approval_mode="consensus",
        goal_summary="Approved blueprint for feature X",
    )

    return db_path


class TestChatReplayExporter:
    def test_exporter_creates_replay_packets(self, chat_db: Path):
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        packets = exporter.export_conversation(
            store.list_conversations()[0].id,
        )
        assert len(packets) >= 1
        for p in packets:
            assert p.conversation_id
            assert p.ingest_intent in list(IngestIntent)
            assert len(p.items) >= 1

    def test_exporter_packets_are_deterministic(self, chat_db: Path):
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        conv_id = store.list_conversations()[0].id
        packets1 = exporter.export_conversation(conv_id)
        packets2 = exporter.export_conversation(conv_id)
        for p1, p2 in zip(packets1, packets2, strict=True):
            assert len(p1.items) == len(p2.items)
            for i1, i2 in zip(p1.items, p2.items, strict=True):
                assert i1.source_id == i2.source_id
                assert i1.content == i2.content

    def test_exporter_items_include_all_sources(self, chat_db: Path):
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        conv_id = store.list_conversations()[0].id
        messages = store.list_messages(conv_id)
        proposals = store.list_proposals(conv_id)
        resolutions = store.list_resolutions(conv_id)
        packets = exporter.export_conversation(conv_id)
        exported_ids = {item.source_id for p in packets for item in p.items}
        expected_ids = {m.id for m in messages}
        expected_ids.update(
            p.id for p in proposals if p.conversation_id == conv_id
        )
        expected_ids.update(
            r.id for r in resolutions if r.conversation_id == conv_id
        )
        assert exported_ids == expected_ids

    def test_exporter_includes_resolution_items(self, chat_db: Path):
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        conv_id = store.list_conversations()[0].id
        packets = exporter.export_conversation(conv_id)
        items = [item for p in packets for item in p.items]
        resolution_items = [i for i in items if i.envelope_type == "resolution"]
        assert len(resolution_items) >= 1
        for ri in resolution_items:
            assert ri.source_type == "blueprint"
            assert ri.metadata.get("resolution_status") == "approved"
            assert ri.metadata.get("approved_by") == ["human"]

    def test_exporter_items_include_source_metadata(self, chat_db: Path):
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        conv_id = store.list_conversations()[0].id
        packets = exporter.export_conversation(conv_id)
        items = [item for p in packets for item in p.items]
        for item in items:
            assert item.conversation_id == conv_id
            assert item.participant_id
            assert item.timestamp is not None

    def test_exporter_produces_raw_message_intent(self, chat_db: Path):
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        conv_id = store.list_conversations()[0].id
        packets = exporter.export_conversation(conv_id)
        raw_packets = [p for p in packets if p.ingest_intent == IngestIntent.RAW_MESSAGE]
        assert len(raw_packets) >= 1

    def test_exporter_unknown_conversation_returns_empty(self, chat_db: Path):
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        packets = exporter.export_conversation("nonexistent_conv")
        assert packets == []

    def test_exporter_does_not_write_to_store(self, chat_db: Path):
        original = chat_db.read_bytes()
        store = ChatStore(chat_db)
        exporter = ChatReplayExporter(store)
        conv_id = store.list_conversations()[0].id
        exporter.export_conversation(conv_id)
        assert chat_db.read_bytes() == original


class TestExportAllConversations:
    def test_export_all_conversations(self, chat_db: Path):
        store = ChatStore(chat_db)
        result = export_all_conversations(store)
        assert len(result) >= 1
        all_items = [item for packets in result.values() for p in packets for item in p.items]
        assert len(all_items) >= 4

    def test_export_all_serializes_to_json(self, chat_db: Path):
        store = ChatStore(chat_db)
        result = export_all_conversations(store)
        payload = {}
        for conv_id, packets in result.items():
            payload[conv_id] = [p.model_dump(mode="json") for p in packets]
        serialized = json.dumps(payload)
        restored = json.loads(serialized)
        assert len(restored) >= 1
        for conv_id in restored:
            assert len(restored[conv_id]) >= 1
