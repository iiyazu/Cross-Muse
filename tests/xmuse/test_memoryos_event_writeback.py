from __future__ import annotations

import pytest

from xmuse_core.integrations.memoryos_client import FakeMemoryOSClient
from xmuse_core.integrations.memoryos_events import (
    MemoryOSWritebackEvent,
    build_god_prompt_memory_block,
    write_memory_event,
)
from xmuse_core.integrations.memoryos_namespace import (
    conversation_namespace,
    shared_namespace,
)


@pytest.mark.asyncio
async def test_blueprint_frozen_writeback_uses_commit_aligned_source_ref() -> None:
    client = FakeMemoryOSClient()
    namespace = conversation_namespace("conv-1")

    result = await write_memory_event(
        client,
        MemoryOSWritebackEvent(
            kind="blueprint_frozen",
            namespace=namespace,
            event_id="bp-1",
            summary="Blueprint bp-1 was frozen.",
            source_refs=["message:proposal"],
            commit_sha="abc123",
        ),
    )

    assert result.ok is True
    pages = await client.search(namespace, query="Blueprint")
    assert pages[0].source_refs == [
        "memory://conversation/conv-1/commits/abc123/events/blueprint_frozen/bp-1",
        "message:proposal",
    ]


@pytest.mark.asyncio
async def test_pr_merged_writeback_can_promote_to_shared_memory() -> None:
    client = FakeMemoryOSClient()
    namespace = conversation_namespace("conv-1")
    shared = shared_namespace("iiyazu/Cross-Muse")

    await write_memory_event(
        client,
        MemoryOSWritebackEvent(
            kind="pr_merged",
            namespace=namespace,
            event_id="123",
            summary="PR 123 merged the feature.",
            source_refs=["pr:123"],
            promote_to_shared=True,
            shared_namespace=shared,
        ),
    )

    assert await client.search(namespace, query="merged")
    shared_pages = await client.search(shared, query="merged")
    assert [page.content for page in shared_pages] == [
        "Event: pr_merged\nSummary: PR 123 merged the feature.\nSource refs:\n"
        "- memory://conversation/conv-1/events/pr_merged/123\n"
        "- pr:123"
    ]


@pytest.mark.asyncio
async def test_god_prompt_memory_block_includes_source_refs() -> None:
    client = FakeMemoryOSClient()
    namespace = conversation_namespace("conv-1")
    await write_memory_event(
        client,
        MemoryOSWritebackEvent(
            kind="review_verdict_finalized",
            namespace=namespace,
            event_id="verdict-1",
            summary="Review approved after gate evidence.",
            source_refs=["review:verdict-1", "gate:pytest"],
        ),
    )

    block = await build_god_prompt_memory_block(
        client,
        namespace,
        task="prepare review GOD",
        query="review",
    )

    assert "## MemoryOS Context" in block
    assert "Review approved after gate evidence." in block
    assert "- review:verdict-1" in block
    assert "- gate:pytest" in block
