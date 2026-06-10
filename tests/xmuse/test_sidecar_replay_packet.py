from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from xmuse_core.sidecar.replay_packet import (
    IngestIntent,
    ReplayPacket,
    ReplayPacketItem,
    build_message_item,
    build_proposal_item,
    build_replay_packet,
    source_type_for_envelope,
)


class TestIngestIntent:
    def test_intent_enum_has_expected_values(self):
        assert IngestIntent.RAW_MESSAGE.value == "raw_message"
        assert IngestIntent.DECISION.value == "decision"
        assert IngestIntent.SUMMARY_CANDIDATE.value == "summary_candidate"
        assert IngestIntent.UNRESOLVED_THREAD.value == "unresolved_thread"
        assert IngestIntent.BLUEPRINT_VERSION.value == "blueprint_version"
        assert IngestIntent.PARTICIPANT_NOTE.value == "participant_note"


class TestReplayPacketItem:
    def test_minimal_message_item(self):
        item = ReplayPacketItem(
            source_type="message",
            source_id="msg_001",
            conversation_id="conv_1",
            participant_id="p_arch",
            content="Hello, architect!",
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
        )
        assert item.source_type == "message"
        assert item.content == "Hello, architect!"
        assert item.thread_id is None
        assert item.envelope_type is None

    def test_proposal_item_with_optional_fields(self):
        item = ReplayPacketItem(
            source_type="proposal",
            source_id="prop_042",
            conversation_id="conv_1",
            participant_id="p_arch",
            content="Proposal to implement feature X",
            timestamp=datetime(2026, 6, 4, tzinfo=UTC),
            thread_id="thread_789",
            envelope_type="mission_blueprint",
            metadata={"decision": "approved"},
        )
        assert item.thread_id == "thread_789"
        assert item.envelope_type == "mission_blueprint"
        assert item.metadata["decision"] == "approved"

    def test_item_rejects_empty_source_id(self):
        with pytest.raises(ValidationError):
            ReplayPacketItem(
                source_type="message",
                source_id="",
                conversation_id="conv_1",
                participant_id="p_arch",
                content="test",
                timestamp=datetime(2026, 6, 4, tzinfo=UTC),
            )


class TestReplayPacket:
    def test_minimal_packet(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        packet = ReplayPacket(
            conversation_id="conv_1",
            ingest_intent=IngestIntent.RAW_MESSAGE,
            items=[
                ReplayPacketItem(
                    source_type="message",
                    source_id="msg_001",
                    conversation_id="conv_1",
                    participant_id="p_human",
                    content="Let's build feature X",
                    timestamp=now,
                ),
            ],
        )
        assert packet.packet_id.startswith("replay_")
        assert packet.conversation_id == "conv_1"
        assert packet.ingest_intent == IngestIntent.RAW_MESSAGE
        assert len(packet.items) == 1

    def test_packet_requires_at_least_one_item(self):
        with pytest.raises(ValidationError, match="at least 1 item"):
            ReplayPacket(
                conversation_id="conv_1",
                ingest_intent=IngestIntent.RAW_MESSAGE,
                items=[],
            )

    def test_packet_serializes_to_json_roundtrip(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        packet = ReplayPacket(
            conversation_id="conv_1",
            ingest_intent=IngestIntent.DECISION,
            items=[
                ReplayPacketItem(
                    source_type="proposal",
                    source_id="prop_001",
                    conversation_id="conv_1",
                    participant_id="p_arch",
                    content="Approved feature X plan",
                    timestamp=now,
                    envelope_type="feature_plan",
                ),
            ],
        )
        payload = packet.model_dump(mode="json")
        restored = ReplayPacket.model_validate(payload)
        assert restored.packet_id == packet.packet_id
        assert restored.ingest_intent == packet.ingest_intent
        assert restored.items[0].source_id == "prop_001"

    def test_packet_items_chronologically_ordered(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        packet = ReplayPacket(
            conversation_id="conv_1",
            ingest_intent=IngestIntent.RAW_MESSAGE,
            items=[
                ReplayPacketItem(
                    source_type="message",
                    source_id="msg_001",
                    conversation_id="conv_1",
                    participant_id="p_human",
                    content="Message 1",
                    timestamp=now,
                ),
                ReplayPacketItem(
                    source_type="message",
                    source_id="msg_002",
                    conversation_id="conv_1",
                    participant_id="p_arch",
                    content="Message 2",
                    timestamp=datetime(2026, 6, 4, 0, 1, tzinfo=UTC),
                ),
            ],
        )
        assert packet.items[0].source_id == "msg_001"
        assert packet.items[1].source_id == "msg_002"


class TestBuilders:
    def test_build_message_item(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        item = build_message_item(
            source_id="msg_001",
            conversation_id="conv_1",
            participant_id="p_human",
            content="Hello!",
            timestamp=now,
        )
        assert item.source_type == "message"
        assert item.content == "Hello!"

    def test_build_proposal_item(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        item = build_proposal_item(
            source_id="prop_001",
            conversation_id="conv_1",
            participant_id="p_arch",
            content="Blueprint for feature X",
            timestamp=now,
            envelope_type="mission_blueprint",
        )
        assert item.source_type == "blueprint"
        assert item.envelope_type == "mission_blueprint"

    def test_build_replay_packet_groups_by_intent(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        items = [
            build_message_item("msg_1", "conv_1", "p_human", "Hi", now),
            build_message_item("msg_2", "conv_1", "p_arch", "Hello!", now),
        ]
        packet = build_replay_packet(
            conversation_id="conv_1",
            items=items,
            ingest_intent=IngestIntent.RAW_MESSAGE,
        )
        assert len(packet.items) == 2
        assert packet.conversation_id == "conv_1"

    def test_build_replay_packet_with_source_refs(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        items = [
            build_message_item("msg_1", "conv_1", "p_human", "Hi", now),
        ]
        packet = build_replay_packet(
            conversation_id="conv_1",
            items=items,
            ingest_intent=IngestIntent.DECISION,
            scope_note="blueprint_decision",
        )
        assert packet.scope_note == "blueprint_decision"


class TestSourceTypeMapping:
    def test_source_type_for_known_envelopes(self):
        assert source_type_for_envelope("message") == "message"
        assert source_type_for_envelope("mission_blueprint") == "blueprint"
        assert source_type_for_envelope("feature_plan") == "blueprint"
        assert source_type_for_envelope("lane_graph") == "proposal"
        assert source_type_for_envelope("proposal") == "proposal"
        assert source_type_for_envelope("verdict") == "verdict"
        assert source_type_for_envelope("card") == "card"

    def test_source_type_fallback_to_message(self):
        assert source_type_for_envelope("unknown_type") == "message"
