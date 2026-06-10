from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.chat.store import ChatStore
from xmuse_core.sidecar.recall_eval import (
    ChatRecallEvalHarness,
    RecallQuery,
    default_accuracy_gate,
    score_recall_results,
)
from xmuse_core.sidecar.recall_lab import SourceGroundedRecallLab
from xmuse_core.sidecar.replay_exporter import ChatReplayExporter, export_all_conversations
from xmuse_core.sidecar.replay_packet import IngestIntent


@pytest.fixture
def smoke_chat_db(tmp_path: Path) -> Path:
    """Build a realistic multi-turn group chat conversation."""
    db_path = tmp_path / "smoke_chat.db"
    store = ChatStore(db_path)
    store.create_conversation("V6 Smoke Test — Feature Y")

    conv_id = store.list_conversations()[0].id

    store.add_message(
        conversation_id=conv_id,
        author="human",
        role="user",
        content="We need to add rate limiting to the API gateway",
        envelope_type="message",
    )
    store.add_message(
        conversation_id=conv_id,
        author="architect",
        role="assistant",
        content="I recommend a token bucket algorithm with configurable limits",
        envelope_type="message",
    )
    store.add_message(
        conversation_id=conv_id,
        author="architect",
        role="assistant",
        content="Blueprint: rate_limiter middleware, token bucket store, config API",
        envelope_type="message",
        envelope_json={"escalation": "mission_blueprint", "title": "Rate Limiter Blueprint"},
    )
    store.add_message(
        conversation_id=conv_id,
        author="review",
        role="assistant",
        content="Approved. The plan looks solid for MVP",
        envelope_type="message",
    )
    store.add_message(
        conversation_id=conv_id,
        author="human",
        role="user",
        content="What about distributed rate limiting across instances?",
        envelope_type="message",
    )
    store.add_message(
        conversation_id=conv_id,
        author="architect",
        role="assistant",
        content="We can use Redis as the backing store for cross-instance coordination",
        envelope_type="message",
    )

    store.create_proposal(
        conversation_id=conv_id,
        author="architect",
        proposal_type="mission_blueprint",
        content="Rate limiter middleware with token bucket + Redis backend",
        references=["msg_001", "msg_002"],
    )

    store.create_proposal(
        conversation_id=conv_id,
        author="review",
        proposal_type="verdict",
        content="Approved. MVP scope as defined",
        references=["prop_001"],
    )

    return db_path


class TestV6IndependentSidecarSmoke:
    """Full V6 chain: exporter → replay packets → recall eval → boundary gate."""

    def test_end_to_end_chain(self, smoke_chat_db: Path):
        store = ChatStore(smoke_chat_db)
        conv_id = store.list_conversations()[0].id

        # Step 1: Export replay packets from chat store
        exporter = ChatReplayExporter(store)
        packets = exporter.export_conversation(conv_id)
        assert len(packets) >= 1
        assert packets[0].conversation_id == conv_id
        assert packets[0].ingest_intent == IngestIntent.RAW_MESSAGE

        # Step 2: Verify packet structure
        items = [item for p in packets for item in p.items]
        assert len(items) >= 6  # 6 messages + 2 proposals
        for item in items:
            assert item.source_id
            assert item.participant_id
            assert item.conversation_id == conv_id

        # Step 3: Run recall eval against exported data
        harness = ChatRecallEvalHarness(packets)
        queries = [
            RecallQuery(
                query_id="smoke_q1",
                question="What rate limiting algorithm was proposed?",
                expected_keywords=["token bucket"],
                expected_source_ids=[items[1].source_id],
                expected_participants=["participant_architect"],
                scope="conversation_shared",
            ),
            RecallQuery(
                query_id="smoke_q2",
                question="What was the blueprint about?",
                expected_keywords=["rate_limiter", "Redis"],
                expected_source_ids=[items[2].source_id],
                expected_participants=["participant_architect"],
                scope="blueprint_decision",
            ),
            RecallQuery(
                query_id="smoke_q3",
                question="Who approved the plan?",
                expected_keywords=["Approved"],
                expected_source_ids=[items[3].source_id],
                expected_participants=["participant_review"],
                scope="conversation_shared",
            ),
            RecallQuery(
                query_id="smoke_q4",
                question="Distributed rate limiting question",
                expected_keywords=["Redis"],
                expected_source_ids=[items[5].source_id],
                expected_participants=["participant_architect"],
                scope="conversation_shared",
            ),
        ]
        results = harness.evaluate(queries)
        assert len(results) == 4

        # Step 4: Verify recall quality — all queries should pass
        for r in results:
            assert r.found_content, f"Query {r.query_id} should find content"
            assert r.found_source_evidence, f"Query {r.query_id} should find source evidence"

        # Step 5: Score and gate
        score = score_recall_results(results)
        assert score.total_queries == 4
        assert score.passed_queries == 4
        assert score.content_recall_rate == 1.0
        assert score.source_evidence_rate == 1.0

        # Step 6: Default accuracy gate should pass
        assert default_accuracy_gate(results, min_pass_rate=0.8) is True

    def test_chain_handles_missing_content(self, smoke_chat_db: Path):
        store = ChatStore(smoke_chat_db)
        conv_id = store.list_conversations()[0].id
        exporter = ChatReplayExporter(store)
        packets = exporter.export_conversation(conv_id)
        harness = ChatRecallEvalHarness(packets)

        queries = [
            RecallQuery(
                query_id="smoke_missing",
                question="What about database migration?",
                expected_keywords=["migration"],
                expected_source_ids=["nonexistent"],
                expected_participants=["participant_unknown"],
                scope="conversation_shared",
            ),
        ]
        results = harness.evaluate(queries)
        assert results[0].found_content is False
        assert results[0].found_source_evidence is False

    def test_chain_export_all_conversations(self, smoke_chat_db: Path):
        store = ChatStore(smoke_chat_db)
        result = export_all_conversations(store)
        assert len(result) >= 1
        for conv_id, packets in result.items():
            assert len(packets) >= 1
            harness = ChatRecallEvalHarness(packets)
            queries = [
                RecallQuery(
                    query_id=f"smoke_all_{conv_id}",
                    question="Rate limiting?",
                    expected_keywords=["token bucket"],
                    expected_source_ids=[],
                    expected_participants=[],
                    scope="conversation_shared",
                ),
            ]
            results = harness.evaluate(queries)
            assert len(results) == 1

    def test_chain_memory_scope_coverage(self, smoke_chat_db: Path):
        """Verify derived queries cover items across scopes."""
        from xmuse_core.sidecar.recall_eval import derive_recall_queries_from_packets

        store = ChatStore(smoke_chat_db)
        conv_id = store.list_conversations()[0].id
        exporter = ChatReplayExporter(store)
        packets = exporter.export_conversation(conv_id)
        queries = derive_recall_queries_from_packets(packets)
        assert len(queries) >= 1

    def test_chain_does_not_mutate_chat_store(self, smoke_chat_db: Path):
        original = smoke_chat_db.read_bytes()
        store = ChatStore(smoke_chat_db)
        conv_id = store.list_conversations()[0].id
        exporter = ChatReplayExporter(store)
        packets = exporter.export_conversation(conv_id)
        harness = ChatRecallEvalHarness(packets)
        queries = [
            RecallQuery(
                query_id="no_mutate",
                question="Rate limiting?",
                expected_keywords=["token bucket"],
                expected_source_ids=[],
                expected_participants=[],
                scope="conversation_shared",
            ),
        ]
        harness.evaluate(queries)
        assert smoke_chat_db.read_bytes() == original

    @pytest.mark.asyncio
    async def test_chain_recall_lab_no_live_memoryos(self, smoke_chat_db: Path):
        """Full recall lab chain: exporter → projection → fake adapter → report."""
        store = ChatStore(smoke_chat_db)
        conv_id = store.list_conversations()[0].id
        exporter = ChatReplayExporter(store)
        packets = exporter.export_conversation(conv_id)
        assert len(packets) >= 1

        queries = [
            RecallQuery(
                query_id="smoke_lab_q1",
                question="Rate limiting token bucket algorithm",
                expected_keywords=["token bucket"],
                expected_source_ids=[
                    p.source_id for pkt in packets
                    for p in pkt.items if "token" in p.content
                ][:1],
                expected_participants=["participant_architect"],
                scope="conversation_shared",
            ),
        ]
        lab = SourceGroundedRecallLab()
        report = await lab.run(packets, queries)
        assert report.total_queries == 1
        assert report.content_hit_rate >= 0
