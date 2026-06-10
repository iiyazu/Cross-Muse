from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SidecarIngestRecord(BaseModel):
    session_id: str = Field(min_length=1)
    source_type: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    participant_id: str = Field(min_length=1)
    content: str
    timestamp: datetime
    taxonomy_scope: str = "conversation_shared"
    ingest_intent: str = "raw_message"
    envelope_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SidecarRecallRequest(BaseModel):
    session_id: str = Field(min_length=1)
    query: str = Field(min_length=1)
    expected_keywords: list[str] = Field(default_factory=list)


class SidecarRecallMatch(BaseModel):
    source_id: str
    source_type: str
    content_snippet: str
    score: float = Field(ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SidecarRecallResult(BaseModel):
    session_id: str
    query: str
    matched: bool = False
    matches: list[SidecarRecallMatch] = Field(default_factory=list)
    matched_keywords: list[str] = Field(default_factory=list)
    error: str | None = None


class SidecarIngestResult(BaseModel):
    session_id: str
    record_count: int = 0
    ok: bool = False
    error: str | None = None


class MemoryOSSidecarAdapter(ABC):
    @abstractmethod
    async def ingest(self, records: list[SidecarIngestRecord]) -> SidecarIngestResult:
        ...

    @abstractmethod
    async def recall(self, request: SidecarRecallRequest) -> SidecarRecallResult:
        ...

    @abstractmethod
    async def clear(self) -> None:
        ...


class FakeMemoryOSSidecarAdapter(MemoryOSSidecarAdapter):
    def __init__(self) -> None:
        self._store: dict[str, list[SidecarIngestRecord]] = {}

    async def ingest(self, records: list[SidecarIngestRecord]) -> SidecarIngestResult:
        if not records:
            return SidecarIngestResult(session_id="", record_count=0, ok=True)
        session_id = records[0].session_id
        for r in records:
            self._store.setdefault(r.session_id, []).append(r)
        return SidecarIngestResult(
            session_id=session_id,
            record_count=len(records),
            ok=True,
        )

    async def recall(self, request: SidecarRecallRequest) -> SidecarRecallResult:
        records = self._store.get(request.session_id, [])
        if not records:
            return SidecarRecallResult(
                session_id=request.session_id,
                query=request.query,
                matched=False,
                error="no_records_for_session",
            )
        query_lower = request.query.lower()
        query_words = set(query_lower.split())
        matches: list[SidecarRecallMatch] = []
        matched_keywords: list[str] = []
        for rec in records:
            content_lower = rec.content.lower()
            keyword_hits = [kw for kw in request.expected_keywords if kw.lower() in content_lower]
            if keyword_hits:
                matched_keywords.extend(kw for kw in keyword_hits if kw not in matched_keywords)
            word_overlap = query_words & set(content_lower.split())
            if not keyword_hits and not word_overlap:
                continue
            score = min(1.0, (len(keyword_hits) * 0.3 + len(word_overlap) * 0.1))
            matches.append(
                SidecarRecallMatch(
                    source_id=rec.source_id,
                    source_type=rec.source_type,
                    content_snippet=rec.content[:200],
                    score=score,
                    metadata={
                        "conversation_id": rec.conversation_id,
                        "participant_id": rec.participant_id,
                        "taxonomy_scope": rec.taxonomy_scope,
                        "ingest_intent": rec.ingest_intent,
                    },
                )
            )
        matches.sort(key=lambda m: m.score, reverse=True)
        return SidecarRecallResult(
            session_id=request.session_id,
            query=request.query,
            matched=len(matches) > 0,
            matches=matches[:10],
            matched_keywords=matched_keywords,
        )

    async def clear(self) -> None:
        self._store.clear()


class LiveMemoryOSSidecarAdapter(MemoryOSSidecarAdapter):
    def __init__(self, *, base_url: str = "http://127.0.0.1:8000") -> None:
        self._base_url = base_url.rstrip("/")

    async def ingest(self, records: list[SidecarIngestRecord]) -> SidecarIngestResult:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                session_ids = set(r.session_id for r in records)
                for sid in session_ids:
                    session_records = [r for r in records if r.session_id == sid]
                    await client.post(
                        f"{self._base_url}/sessions",
                        json={"title": f"v6-sidecar-{sid}"},
                    )
                    for rec in session_records:
                        await client.post(
                            f"{self._base_url}/sessions/{sid}/ingest",
                            json={
                                "role": "assistant",
                                "content": _format_ingest(rec),
                            },
                        )
                return SidecarIngestResult(
                    session_id=next(iter(session_ids)) if session_ids else "",
                    record_count=len(records),
                    ok=True,
                )
        except Exception as e:
            return SidecarIngestResult(
                session_id="",
                record_count=len(records),
                ok=False,
                error=str(e),
            )

    async def recall(self, request: SidecarRecallRequest) -> SidecarRecallResult:
        try:
            import httpx

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{self._base_url}/sessions/{request.session_id}/build-context",
                    json={"task": request.query, "budget": 2048},
                )
                text = resp.json().get("context", "") if resp.is_success else ""
                return SidecarRecallResult(
                    session_id=request.session_id,
                    query=request.query,
                    matched=bool(text),
                    matches=[
                        SidecarRecallMatch(
                            source_id="built_context",
                            source_type="context",
                            content_snippet=text[:500],
                            score=1.0 if text else 0.0,
                        )
                    ],
                )
        except Exception as e:
            return SidecarRecallResult(
                session_id=request.session_id,
                query=request.query,
                matched=False,
                error=str(e),
            )

    async def clear(self) -> None:
        pass


def _format_ingest(record: SidecarIngestRecord) -> str:
    lines = [
        f"[{record.ingest_intent}] {record.content}",
        f"Source: {record.source_type}/{record.source_id}",
        f"Participant: {record.participant_id}",
        f"Scope: {record.taxonomy_scope}",
    ]
    return "\n".join(lines)
