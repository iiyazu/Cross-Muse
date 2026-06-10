from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.platform.memory_refs import (
    MemoryCategory,
    MemoryLesson,
    MemoryOSStoreAdapter,
    MemoryRef,
    MemoryScope,
)


class _FakeMemoryOSClient:
    def __init__(self) -> None:
        self.created_titles: list[str] = []
        self.ingested: list[tuple[str, str, str]] = []
        self.context_requests: list[tuple[str, str, int]] = []

    async def create_session(self, title: str) -> str:
        self.created_titles.append(title)
        return f"ses_{len(self.created_titles)}"

    async def ingest(self, session_id: str, role: str, content: str) -> None:
        self.ingested.append((session_id, role, content))

    async def build_context(self, session_id: str, task: str, budget: int = 4096) -> str:
        self.context_requests.append((session_id, task, budget))
        return f"context for {session_id}: {task}"


def test_memory_ref_serialization_distinguishes_scope_taxonomy() -> None:
    ref = MemoryRef(
        scope=MemoryScope.FEATURE,
        category=MemoryCategory.FEATURE_HISTORY,
        session_id="ses_feature_1",
        title="Feature Alpha History",
        conversation_id="conv-1",
        feature_id="feature-alpha",
        primary_evidence_refs=["logs/gates/lane-a/report.json"],
        metadata={"source_lane_id": "lane-a"},
    )

    assert ref.uri == "memoryos://feature/conv-1/feature-alpha/ses_feature_1"
    assert ref.model_dump(mode="json") == {
        "scope": "feature",
        "category": "feature_history",
        "session_id": "ses_feature_1",
        "title": "Feature Alpha History",
        "conversation_id": "conv-1",
        "feature_id": "feature-alpha",
        "participant_id": None,
        "primary_evidence_refs": ["logs/gates/lane-a/report.json"],
        "metadata": {"source_lane_id": "lane-a"},
        "uri": "memoryos://feature/conv-1/feature-alpha/ses_feature_1",
    }


def test_memory_ref_validation_enforces_scope_requirements() -> None:
    with pytest.raises(ValidationError, match="feature memory refs require"):
        MemoryRef(
            scope=MemoryScope.FEATURE,
            category=MemoryCategory.FEATURE_HISTORY,
            session_id="ses_feature_1",
            title="Feature Alpha History",
        )

    with pytest.raises(ValidationError, match="global memory refs cannot include"):
        MemoryRef(
            scope=MemoryScope.GLOBAL,
            category=MemoryCategory.PLATFORM_LESSON,
            session_id="ses_global_1",
            title="Global Platform Lessons",
            conversation_id="conv-1",
        )


@pytest.mark.asyncio
async def test_memoryos_store_adapter_creates_scoped_session_and_ingests_lesson() -> None:
    client = _FakeMemoryOSClient()
    adapter = MemoryOSStoreAdapter(client)

    ref = await adapter.remember(
        MemoryLesson(
            scope=MemoryScope.FEATURE,
            category=MemoryCategory.REVIEW_REWORK_LESSON,
            title="Feature Alpha Review Lessons",
            summary="Retry context must preserve primary evidence refs.",
            conversation_id="conv-1",
            feature_id="feature-alpha",
            source_lane_id="lane-a",
            primary_evidence_refs=[
                "logs/gates/lane-a/report.json",
                "lane.review_summary",
            ],
        )
    )

    assert client.created_titles == ["xmuse-memory:feature:conv-1:feature-alpha"]
    assert ref.model_dump(mode="json") == {
        "scope": "feature",
        "category": "review_rework_lesson",
        "session_id": "ses_1",
        "title": "Feature Alpha Review Lessons",
        "conversation_id": "conv-1",
        "feature_id": "feature-alpha",
        "participant_id": None,
        "primary_evidence_refs": [
            "logs/gates/lane-a/report.json",
            "lane.review_summary",
        ],
        "metadata": {"source_lane_id": "lane-a"},
        "uri": "memoryos://feature/conv-1/feature-alpha/ses_1",
    }
    assert client.ingested == [
        (
            "ses_1",
            "assistant",
            "Feature Alpha Review Lessons\n"
            "Category: review_rework_lesson\n"
            "Summary: Retry context must preserve primary evidence refs.\n"
            "Primary evidence refs:\n"
            "- logs/gates/lane-a/report.json\n"
            "- lane.review_summary",
        )
    ]


@pytest.mark.asyncio
async def test_memoryos_store_adapter_reuses_scope_session_and_builds_context() -> None:
    client = _FakeMemoryOSClient()
    adapter = MemoryOSStoreAdapter(client)

    feature_ref = await adapter.remember(
        MemoryLesson(
            scope=MemoryScope.FEATURE,
            category=MemoryCategory.FEATURE_HISTORY,
            title="Feature Alpha History",
            summary="Review peer routing is active for this feature.",
            conversation_id="conv-1",
            feature_id="feature-alpha",
        )
    )
    reused_ref = await adapter.remember(
        MemoryLesson(
            scope=MemoryScope.FEATURE,
            category=MemoryCategory.FEATURE_HISTORY,
            title="Feature Alpha History",
            summary="Takeover context should cite the same scoped memory session.",
            conversation_id="conv-1",
            feature_id="feature-alpha",
        )
    )
    global_ref = await adapter.remember(
        MemoryLesson(
            scope=MemoryScope.GLOBAL,
            category=MemoryCategory.PLATFORM_LESSON,
            title="Global Platform Lessons",
            summary="Review decisions cannot rely on opaque memory-only evidence.",
        )
    )

    context = await adapter.build_context(
        [feature_ref, reused_ref, global_ref],
        task="prepare peer request",
        budget=600,
    )

    assert feature_ref.session_id == reused_ref.session_id == "ses_1"
    assert global_ref.session_id == "ses_2"
    assert client.created_titles == [
        "xmuse-memory:feature:conv-1:feature-alpha",
        "xmuse-memory:global:platform",
    ]
    assert client.context_requests == [
        ("ses_1", "prepare peer request", 300),
        ("ses_2", "prepare peer request", 300),
    ]
    assert context == (
        "## Feature Alpha History\n\n"
        "context for ses_1: prepare peer request\n\n"
        "## Global Platform Lessons\n\n"
        "context for ses_2: prepare peer request"
    )
