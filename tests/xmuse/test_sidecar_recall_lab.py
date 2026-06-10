from __future__ import annotations

from datetime import UTC, datetime

import pytest

from xmuse_core.sidecar.ingest_projection import project_item, project_packets
from xmuse_core.sidecar.memoryos_adapter import (
    FakeMemoryOSSidecarAdapter,
    LiveMemoryOSSidecarAdapter,
    SidecarIngestRecord,
    SidecarRecallRequest,
)
from xmuse_core.sidecar.recall_eval import RecallQuery
from xmuse_core.sidecar.recall_lab import SourceGroundedRecallLab, run_recall_lab
from xmuse_core.sidecar.replay_packet import (
    IngestIntent,
    ReplayPacket,
    ReplayPacketItem,
    build_replay_packet,
)

_TS = datetime(2026, 6, 4, tzinfo=UTC)


def _item(
    source_id: str,
    content: str,
    *,
    source_type: str = "message",
    participant_id: str = "p_human",
    conversation_id: str = "conv_test",
    envelope_type: str | None = None,
    metadata: dict | None = None,
) -> ReplayPacketItem:
    return ReplayPacketItem(
        source_type=source_type,
        source_id=source_id,
        conversation_id=conversation_id,
        participant_id=participant_id,
        content=content,
        timestamp=_TS,
        envelope_type=envelope_type,
        metadata=metadata or {},
    )


_ARCH = dict(participant_id="p_arch", source_type="blueprint")
_SYS = dict(participant_id="p_system", source_type="card")


@pytest.fixture
def sample_packets() -> list[ReplayPacket]:
    items = [
        _item("msg_001", "We need rate limiting"),
        _item("msg_002", "Token bucket algorithm with Redis", participant_id="p_arch"),
        _item("prop_001", "Rate limiter middleware blueprint",
              **_ARCH, envelope_type="mission_blueprint"),
        _item("res_001", "Approved blueprint for rate limiter",
              **_ARCH, envelope_type="resolution",
              metadata={"resolution_status": "approved"}),
        _item("card_001", "Feature X implementation started",
              **_SYS, envelope_type="run_progress"),
        _item("verdict_001", "Review: approved with minor changes",
              participant_id="p_review", source_type="verdict",
              envelope_type="verdict"),
    ]
    return [build_replay_packet(
        conversation_id="conv_test", items=items,
        ingest_intent=IngestIntent.RAW_MESSAGE,
    )]


# ── Adapter Tests ──

class TestSidecarIngestRecord:
    def test_minimal_record(self):
        now = datetime(2026, 6, 4, tzinfo=UTC)
        r = SidecarIngestRecord(
            session_id="ses_test",
            source_type="message",
            source_id="msg_001",
            conversation_id="conv_1",
            participant_id="p_human",
            content="hello",
            timestamp=now,
        )
        assert r.taxonomy_scope == "conversation_shared"
        assert r.ingest_intent == "raw_message"


class TestFakeMemoryOSSidecarAdapter:
    @pytest.mark.asyncio
    async def test_ingest_and_recall_roundtrip(self):
        adapter = FakeMemoryOSSidecarAdapter()
        now = datetime(2026, 6, 4, tzinfo=UTC)
        records = [
            SidecarIngestRecord(
                session_id="ses_test",
                source_type="message",
                source_id="msg_001",
                conversation_id="conv_1",
                participant_id="p_human",
                content="We need rate limiting with token bucket",
                timestamp=now,
            ),
        ]
        result = await adapter.ingest(records)
        assert result.ok is True
        assert result.record_count == 1

        recall = await adapter.recall(SidecarRecallRequest(
            session_id="ses_test",
            query="rate limiting",
            expected_keywords=["token bucket"],
        ))
        assert recall.matched is True
        assert "token bucket" in recall.matched_keywords

    @pytest.mark.asyncio
    async def test_recall_no_records(self):
        adapter = FakeMemoryOSSidecarAdapter()
        recall = await adapter.recall(SidecarRecallRequest(
            session_id="ses_empty",
            query="anything",
        ))
        assert recall.matched is False
        assert recall.error == "no_records_for_session"

    @pytest.mark.asyncio
    async def test_recall_matches_content_and_tracks_source(self):
        adapter = FakeMemoryOSSidecarAdapter()
        now = datetime(2026, 6, 4, tzinfo=UTC)
        records = [
            SidecarIngestRecord(
                session_id="ses_test",
                source_type="blueprint",
                source_id="res_001",
                conversation_id="conv_1",
                participant_id="p_arch",
                content="Approved blueprint for rate limiter",
                timestamp=now,
            ),
        ]
        await adapter.ingest(records)
        recall = await adapter.recall(SidecarRecallRequest(
            session_id="ses_test",
            query="blueprint",
            expected_keywords=["blueprint", "rate limiter"],
        ))
        assert recall.matched is True
        assert recall.matches[0].source_id == "res_001"
        assert recall.matches[0].source_type == "blueprint"

    @pytest.mark.asyncio
    async def test_clear_removes_data(self):
        adapter = FakeMemoryOSSidecarAdapter()
        now = datetime(2026, 6, 4, tzinfo=UTC)
        await adapter.ingest([SidecarIngestRecord(
            session_id="ses_test", source_type="message", source_id="m1",
            conversation_id="c1", participant_id="p1", content="test", timestamp=now,
        )])
        await adapter.clear()
        recall = await adapter.recall(SidecarRecallRequest(session_id="ses_test", query="test"))
        assert recall.matched is False


class TestLiveMemoryOSSidecarAdapter:
    @pytest.mark.asyncio
    async def test_no_live_memoryos_by_default(self):
        adapter = LiveMemoryOSSidecarAdapter()
        now = datetime(2026, 6, 4, tzinfo=UTC)
        result = await adapter.ingest([SidecarIngestRecord(
            session_id="ses_test", source_type="message", source_id="m1",
            conversation_id="c1", participant_id="p1", content="test", timestamp=now,
        )])
        assert result.ok is False
        assert result.error is not None


# ── Ingest Projection Tests ──

class TestProjectItem:
    def test_message_item_projection(self):
        item = _item("msg_001", "We need rate limiting")
        record = project_item(item)
        assert record is not None
        assert record.source_type == "message"
        assert record.source_id == "msg_001"
        assert record.taxonomy_scope == "conversation_shared"
        assert record.ingest_intent == "raw_message"

    def test_blueprint_item_projection(self):
        item = _item("prop_001", "Rate limiter blueprint",
                     source_type="blueprint", envelope_type="mission_blueprint",
                     participant_id="p_arch")
        record = project_item(item)
        assert record is not None
        assert record.taxonomy_scope == "blueprint_decision"
        assert record.ingest_intent == "blueprint_version"

    def test_resolution_item_projection(self):
        record = project_item(_item("res_001", "Approved",
                             source_type="blueprint",
                             envelope_type="resolution",
                             participant_id="p_system",
                             metadata={"resolution_status": "approved"}))
        assert record is not None
        assert record.taxonomy_scope == "blueprint_decision"

    def test_card_item_projection(self):
        record = project_item(_item("card_001", "Implementation started",
                             source_type="card", envelope_type="run_progress",
                             participant_id="p_system"))
        assert record is not None
        assert record.source_type == "card"

    def test_verdict_item_projection(self):
        record = project_item(_item("verdict_001", "Approved with changes",
                             source_type="verdict", envelope_type="verdict",
                             participant_id="p_review"))
        assert record is not None
        assert record.taxonomy_scope == "blueprint_decision"
        assert record.ingest_intent == "decision"

    def test_projection_preserves_source_evidence(self):
        item = _item("msg_001", "Rate limiting with token bucket",
                     source_type="message", participant_id="p_arch",
                     envelope_type="message", metadata={"extra": "info"})
        record = project_item(item)
        assert record is not None
        assert record.source_id == "msg_001"
        assert record.participant_id == "p_arch"
        assert record.envelope_type == "message"
        assert record.metadata.get("extra") == "info"


class TestProjectPackets:
    def test_project_all_items(self, sample_packets):
        records = project_packets(sample_packets)
        assert len(records) == 6

    def test_project_source_types_covered(self, sample_packets):
        records = project_packets(sample_packets)
        types = {r.source_type for r in records}
        assert "message" in types
        assert "blueprint" in types
        assert "card" in types
        assert "verdict" in types

    def test_project_empty(self):
        assert project_packets([]) == []


# ── Recall Lab Tests ──

class TestSourceGroundedRecallLab:
    @pytest.mark.asyncio
    async def test_full_pipeline_content_and_evidence(self, sample_packets):
        queries = [
            RecallQuery(
                query_id="q_rate",
                question="What rate limiting algorithm?",
                expected_keywords=["token bucket"],
                expected_source_ids=["msg_002"],
                expected_participants=["p_arch"],
                scope="conversation_shared",
            ),
            RecallQuery(
                query_id="q_blueprint",
                question="What was the blueprint?",
                expected_keywords=["blueprint"],
                expected_source_ids=["prop_001"],
                expected_participants=["p_arch"],
                scope="blueprint_decision",
            ),
        ]
        report = await run_recall_lab(sample_packets, queries)
        assert report.total_queries == 2
        assert report.passed_queries == 2
        assert report.content_hit_rate == 1.0
        assert report.source_evidence_hit_rate == 1.0

    @pytest.mark.asyncio
    async def test_missing_source_evidence_fails(self, sample_packets):
        queries = [
            RecallQuery(
                query_id="q_missing",
                question="What about database sharding?",
                expected_keywords=["sharding"],
                expected_source_ids=["nonexistent"],
                expected_participants=["p_ghost"],
                scope="conversation_shared",
            ),
        ]
        report = await run_recall_lab(sample_packets, queries)
        assert report.total_queries == 1
        assert report.content_hit_count == 0
        assert report.source_evidence_hit_count == 0
        assert report.passed_queries == 0

    @pytest.mark.asyncio
    async def test_content_hit_without_evidence_counted(self, sample_packets):
        queries = [
            RecallQuery(
                query_id="q_content_only",
                question="Rate limiting token bucket",
                expected_keywords=["token bucket", "rate limiting"],
                expected_source_ids=[],
                expected_participants=[],
                scope="conversation_shared",
            ),
        ]
        report = await run_recall_lab(sample_packets, queries)
        assert report.content_hit_count == 1
        assert report.source_evidence_hit_count == 0
        assert report.passed_queries == 0

    @pytest.mark.asyncio
    async def test_does_not_require_live_memoryos(self, sample_packets):
        lab = SourceGroundedRecallLab()
        queries = [
            RecallQuery(query_id="q1", question="rate limiting",
                        expected_keywords=["rate"], scope="conversation_shared"),
        ]
        report = await lab.run(sample_packets, queries)
        assert report.total_queries == 1

    @pytest.mark.asyncio
    async def test_report_is_deterministic(self, sample_packets):
        queries = [
            RecallQuery(query_id="q1", question="rate limiting token bucket",
                        expected_keywords=["token bucket"],
                        expected_source_ids=["msg_002"],
                        expected_participants=["p_arch"],
                        scope="conversation_shared"),
        ]
        r1 = await run_recall_lab(sample_packets, queries)
        r2 = await run_recall_lab(sample_packets, queries)
        assert r1.content_hit_count == r2.content_hit_count
        assert r1.source_evidence_hit_count == r2.source_evidence_hit_count

    @pytest.mark.asyncio
    async def test_empty_packets(self):
        report = await run_recall_lab([], [])
        assert report.total_items_ingested == 0
        assert report.total_queries == 0
