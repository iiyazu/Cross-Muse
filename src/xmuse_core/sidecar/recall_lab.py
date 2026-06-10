from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from xmuse_core.sidecar.ingest_projection import project_packets
from xmuse_core.sidecar.memoryos_adapter import (
    FakeMemoryOSSidecarAdapter,
    MemoryOSSidecarAdapter,
    SidecarIngestRecord,
    SidecarRecallRequest,
)
from xmuse_core.sidecar.recall_eval import RecallQuery
from xmuse_core.sidecar.replay_packet import ReplayPacket


class RecallLabQueryResult(BaseModel):
    query_id: str
    recall_matched: bool = False
    content_hit: bool = False
    source_evidence_hit: bool = False
    matched_source_ids: list[str] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    matched_participants: list[str] = Field(default_factory=list)
    missing_evidence: bool = False
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.content_hit and self.source_evidence_hit


@dataclass
class RecallLabReport:
    total_items_ingested: int = 0
    total_queries: int = 0
    passed_queries: int = 0
    content_hit_count: int = 0
    source_evidence_hit_count: int = 0
    missing_evidence_count: int = 0
    query_results: list[RecallLabQueryResult] = field(default_factory=list)

    @property
    def content_hit_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.content_hit_count / self.total_queries

    @property
    def source_evidence_hit_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.source_evidence_hit_count / self.total_queries

    @property
    def pass_rate(self) -> float:
        if self.total_queries == 0:
            return 0.0
        return self.passed_queries / self.total_queries


class SourceGroundedRecallLab:
    def __init__(self, adapter: MemoryOSSidecarAdapter | None = None) -> None:
        self._adapter = adapter or FakeMemoryOSSidecarAdapter()

    async def run(
        self,
        packets: list[ReplayPacket],
        queries: list[RecallQuery],
    ) -> RecallLabReport:
        records = project_packets(packets)
        if records:
            await self._adapter.ingest(records)

        conversation_id = ""
        if packets:
            for p in packets:
                if p.items:
                    conversation_id = p.items[0].conversation_id
                    break

        session_id = _session_id(conversation_id)

        report = RecallLabReport(
            total_items_ingested=len(records),
            total_queries=len(queries),
        )

        for q in queries:
            result = await self._evaluate_query(q, session_id, records)
            report.query_results.append(result)
            if result.content_hit:
                report.content_hit_count += 1
            if result.source_evidence_hit:
                report.source_evidence_hit_count += 1
            if result.passed:
                report.passed_queries += 1
            if result.missing_evidence:
                report.missing_evidence_count += 1

        return report

    async def _evaluate_query(
        self,
        query: RecallQuery,
        session_id: str,
        ingested_records: list[SidecarIngestRecord],
    ) -> RecallLabQueryResult:
        recall_request = SidecarRecallRequest(
            session_id=session_id,
            query=query.question,
            expected_keywords=query.expected_keywords,
        )
        recall_result = await self._adapter.recall(recall_request)

        matched_source_ids = [m.source_id for m in recall_result.matches]
        matched_keywords = list(recall_result.matched_keywords)

        content_hit = recall_result.matched
        found_any_keyword = any(
            kw.lower() in " ".join(m.content_snippet.lower() for m in recall_result.matches)
            for kw in query.expected_keywords
        )
        content_hit = content_hit or found_any_keyword

        has_explicit_evidence_spec = (
            bool(query.expected_source_ids) or bool(query.expected_participants)
        )
        expected_source_found = (
            any(sid in matched_source_ids for sid in query.expected_source_ids)
            if query.expected_source_ids
            else False
        )
        expected_participant_found = (
            any(
                pid in [m.metadata.get("participant_id", "") for m in recall_result.matches]
                for pid in query.expected_participants
            )
            if query.expected_participants
            else False
        )

        source_evidence_hit = (
            content_hit
            and has_explicit_evidence_spec
            and (expected_source_found or expected_participant_found)
        )

        return RecallLabQueryResult(
            query_id=query.query_id,
            recall_matched=recall_result.matched,
            content_hit=content_hit,
            source_evidence_hit=source_evidence_hit,
            matched_source_ids=matched_source_ids,
            matched_keywords=matched_keywords,
            matched_participants=list(set(
                m.metadata.get("participant_id", "")
                for m in recall_result.matches
            )),
            missing_evidence=content_hit and not source_evidence_hit,
            error=recall_result.error,
        )


async def run_recall_lab(
    packets: list[ReplayPacket],
    queries: list[RecallQuery],
    *,
    adapter: MemoryOSSidecarAdapter | None = None,
) -> RecallLabReport:
    lab = SourceGroundedRecallLab(adapter=adapter)
    return await lab.run(packets, queries)


def _session_id(conversation_id: str) -> str:
    return f"ses_v6_{conversation_id}" if conversation_id else "ses_v6_default"
