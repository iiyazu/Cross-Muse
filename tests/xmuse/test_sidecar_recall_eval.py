from __future__ import annotations

from datetime import UTC, datetime

import pytest

from xmuse_core.sidecar.recall_eval import (
    ChatRecallEvalHarness,
    RecallEvalResult,
    RecallQuery,
    default_accuracy_gate,
    derive_recall_queries_from_packets,
    score_recall_results,
)
from xmuse_core.sidecar.replay_packet import (
    IngestIntent,
    ReplayPacket,
    ReplayPacketItem,
    build_replay_packet,
)


def _make_item(
    source_id: str,
    participant_id: str,
    content: str,
    *,
    source_type: str = "message",
    envelope_type: str | None = None,
) -> ReplayPacketItem:
    return ReplayPacketItem(
        source_type=source_type,
        source_id=source_id,
        conversation_id="conv_eval",
        participant_id=participant_id,
        content=content,
        timestamp=datetime(2026, 6, 4, tzinfo=UTC),
        envelope_type=envelope_type,
    )


@pytest.fixture
def sample_replay_packets() -> list[ReplayPacket]:
    items = [
        _make_item("msg_001", "p_human", "We need to implement user authentication"),
        _make_item("msg_002", "p_arch", "I propose OAuth2 with JWT tokens"),
        _make_item(
            "msg_003",
            "p_arch",
            "The blueprint: auth module, session store, middleware",
            envelope_type="mission_blueprint",
        ),
        _make_item("msg_004", "p_review", "Approved. Let's proceed with implementation"),
        _make_item("msg_005", "p_human", "What about rate limiting?"),
        _make_item(
            "msg_006",
            "p_arch",
            "Rate limiting is out of scope for this iteration",
        ),
    ]
    return [
        build_replay_packet(
            conversation_id="conv_eval",
            items=items,
            ingest_intent=IngestIntent.RAW_MESSAGE,
        ),
        build_replay_packet(
            conversation_id="conv_eval",
            items=[items[2]],
            ingest_intent=IngestIntent.DECISION,
            scope_note="blueprint_decision",
        ),
    ]


class TestRecallQuery:
    def test_query_requires_expected_source_ids(self):
        q = RecallQuery(
            query_id="q_001",
            question="What auth method was proposed?",
            expected_keywords=["OAuth2", "JWT"],
            expected_source_ids=["msg_002"],
            expected_participants=["p_arch"],
            scope="blueprint_decision",
        )
        assert q.query_id == "q_001"
        assert "OAuth2" in q.expected_keywords


class TestRecallEvalResult:
    def test_result_tracks_content_and_evidence(self):
        r = RecallEvalResult(
            query_id="q_001",
            found_content=True,
            found_source_evidence=True,
            matched_source_ids=["msg_002"],
            matched_keywords=["OAuth2"],
            matched_participants=["p_arch"],
        )
        assert r.found_content is True
        assert r.found_source_evidence is True
        assert r.passed is True

    def test_result_fails_when_only_content_found(self):
        r = RecallEvalResult(
            query_id="q_002",
            found_content=True,
            found_source_evidence=False,
            matched_source_ids=[],
            matched_keywords=[],
            matched_participants=[],
        )
        assert r.found_content is True
        assert r.found_source_evidence is False
        assert r.passed is False


class TestChatRecallEvalHarness:
    def test_harness_runs_queries_against_replay_data(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        queries = [
            RecallQuery(
                query_id="q_001",
                question="What auth method was proposed?",
                expected_keywords=["OAuth2", "JWT"],
                expected_source_ids=["msg_002"],
                expected_participants=["p_arch"],
                scope="conversation_shared",
            ),
        ]
        results = harness.evaluate(queries)
        assert len(results) == 1
        assert results[0].query_id == "q_001"

    def test_harness_finds_matching_content(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        queries = [
            RecallQuery(
                query_id="q_auth",
                question="What auth method?",
                expected_keywords=["OAuth2"],
                expected_source_ids=["msg_002"],
                expected_participants=["p_arch"],
                scope="conversation_shared",
            ),
        ]
        results = harness.evaluate(queries)
        assert results[0].found_content is True
        assert results[0].found_source_evidence is True

    def test_harness_reports_missing_content(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        queries = [
            RecallQuery(
                query_id="q_missing",
                question="What about database sharding?",
                expected_keywords=["sharding"],
                expected_source_ids=["msg_999"],
                expected_participants=["p_arch"],
                scope="conversation_shared",
            ),
        ]
        results = harness.evaluate(queries)
        assert results[0].found_content is False
        assert results[0].found_source_evidence is False

    def test_harness_distinguishes_content_from_evidence(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        queries = [
            RecallQuery(
                query_id="q_content_only",
                question="Who approved the plan?",
                expected_keywords=["Approved"],
                expected_source_ids=["msg_004"],
                expected_participants=["p_review"],
                scope="conversation_shared",
            ),
        ]
        results = harness.evaluate(queries)
        assert results[0].found_content is True
        assert results[0].found_source_evidence is True

    def test_harness_handles_blueprint_scope(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        queries = [
            RecallQuery(
                query_id="q_blueprint",
                question="What was the blueprint content?",
                expected_keywords=["blueprint", "auth"],
                expected_source_ids=["msg_003"],
                expected_participants=["p_arch"],
                scope="blueprint_decision",
            ),
        ]
        results = harness.evaluate(queries)
        assert results[0].found_content is True

    def test_harness_results_are_deterministic(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        queries = [
            RecallQuery(
                query_id="q_001",
                question="What auth method?",
                expected_keywords=["OAuth2"],
                expected_source_ids=["msg_002"],
                expected_participants=["p_arch"],
                scope="conversation_shared",
            ),
        ]
        r1 = harness.evaluate(queries)
        r2 = harness.evaluate(queries)
        assert r1[0].model_dump() == r2[0].model_dump()

    def test_harness_empty_queries_returns_empty(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        assert harness.evaluate([]) == []


class TestScoringAndGates:
    def test_score_recall_results(self, sample_replay_packets):
        harness = ChatRecallEvalHarness(sample_replay_packets)
        queries = [
            RecallQuery(
                query_id="q_pass",
                question="Auth method?",
                expected_keywords=["OAuth2"],
                expected_source_ids=["msg_002"],
                expected_participants=["p_arch"],
                scope="conversation_shared",
            ),
            RecallQuery(
                query_id="q_fail",
                question="Missing topic?",
                expected_keywords=["nonexistent"],
                expected_source_ids=["msg_999"],
                expected_participants=["p_ghost"],
                scope="conversation_shared",
            ),
        ]
        results = harness.evaluate(queries)
        score = score_recall_results(results)
        assert score.total_queries == 2
        assert score.passed_queries >= 1
        assert score.passed_queries <= 2

    def test_default_accuracy_gate_requires_source_evidence(self):
        passed_results = [
            RecallEvalResult(
                query_id="q1",
                found_content=True,
                found_source_evidence=True,
                matched_source_ids=["msg_001"],
                matched_keywords=["key"],
                matched_participants=["p_x"],
            ),
        ]
        assert default_accuracy_gate(passed_results) is True

    def test_default_accuracy_gate_fails_without_evidence(self):
        failed_results = [
            RecallEvalResult(
                query_id="q1",
                found_content=True,
                found_source_evidence=False,
                matched_source_ids=[],
                matched_keywords=[],
                matched_participants=[],
            ),
        ]
        assert default_accuracy_gate(failed_results) is False


class TestDeriveQueries:
    def test_derive_queries_from_packets(self, sample_replay_packets):
        queries = derive_recall_queries_from_packets(sample_replay_packets)
        assert len(queries) >= 1

    def test_derived_queries_have_expectations(self, sample_replay_packets):
        queries = derive_recall_queries_from_packets(sample_replay_packets)
        for q in queries:
            assert q.query_id.startswith("derived_")
            assert len(q.expected_source_ids) >= 1
            assert len(q.expected_participants) >= 1

    def test_derived_queries_are_deterministic(self, sample_replay_packets):
        q1 = derive_recall_queries_from_packets(sample_replay_packets)
        q2 = derive_recall_queries_from_packets(sample_replay_packets)
        for qa, qb in zip(q1, q2, strict=True):
            assert qa.model_dump() == qb.model_dump()

    def test_derived_queries_pass_when_evaluated(self, sample_replay_packets):
        queries = derive_recall_queries_from_packets(sample_replay_packets)
        harness = ChatRecallEvalHarness(sample_replay_packets)
        results = harness.evaluate(queries)
        assert len(results) == len(queries)
        passed = [r for r in results if r.passed]
        assert len(passed) >= 1

    def test_derived_queries_empty_for_empty_packets(self):
        queries = derive_recall_queries_from_packets([])
        assert queries == []

    def test_extract_keywords_filters_stop_words(self):
        from xmuse_core.sidecar.recall_eval import _extract_keywords

        result = _extract_keywords("the quick brown fox jumps over the lazy dog")
        assert "quick" in result
        assert "brown" in result
        assert "the" not in result
        assert "over" not in result
