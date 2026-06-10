from __future__ import annotations

import httpx
import pytest

from xmuse_core.integrations.memoryos_client import (
    FakeMemoryOSClient,
    MemoryOSIngestRequest,
    RestMemoryOSClient,
)
from xmuse_core.integrations.memoryos_namespace import (
    conversation_namespace,
    deterministic_memory_source_ref,
    participant_namespace,
    repo_namespace,
    shared_namespace,
    workspace_namespace,
)


def test_memoryos_namespace_mapping_uses_memory_uri_contract() -> None:
    assert repo_namespace("iiyazu/Cross-Muse").uri == "memory://global/repo/iiyazu/Cross-Muse"
    assert workspace_namespace("xmuse").uri == "memory://global/workspace/xmuse"
    assert conversation_namespace("conv-1").uri == "memory://conversation/conv-1"
    assert participant_namespace("conv-1", "god-review").uri == (
        "memory://conversation/conv-1/god/god-review"
    )
    assert shared_namespace("iiyazu/Cross-Muse").uri == (
        "memory://global/shared/iiyazu/Cross-Muse"
    )


@pytest.mark.asyncio
async def test_fake_memoryos_client_preserves_namespace_isolation() -> None:
    client = FakeMemoryOSClient()
    private_ns = participant_namespace("conv-1", "god-review")
    shared_ns = shared_namespace("iiyazu/Cross-Muse")

    await client.ingest(
        MemoryOSIngestRequest(
            namespace=private_ns,
            content="Private review memory.",
            source_refs=["review:1"],
        )
    )

    assert await client.search(shared_ns, query="Private") == []
    assert len(await client.search(private_ns, query="Private")) == 1

    await client.ingest(
        MemoryOSIngestRequest(
            namespace=private_ns,
            content="Promoted review memory.",
            source_refs=["review:2"],
            promote_to_shared=True,
            shared_namespace=shared_ns,
        )
    )

    shared_results = await client.search(shared_ns, query="Promoted")
    assert [item.content for item in shared_results] == ["Promoted review memory."]


@pytest.mark.asyncio
async def test_memory_context_includes_source_refs() -> None:
    client = FakeMemoryOSClient()
    namespace = conversation_namespace("conv-1")
    await client.ingest(
        MemoryOSIngestRequest(
            namespace=namespace,
            content="Blueprint froze after review.",
            source_refs=["blueprint:bp-1", "commit:abc123"],
        )
    )

    context = await client.build_context(namespace, query="blueprint", budget=400)

    assert context.degraded_reason is None
    assert context.source_refs == ["blueprint:bp-1", "commit:abc123"]
    assert "Blueprint froze after review." in context.text


def test_commit_aligned_source_ref_is_deterministic() -> None:
    namespace = conversation_namespace("conv-1")

    first = deterministic_memory_source_ref(
        namespace,
        event_kind="blueprint_frozen",
        event_id="bp-1",
        commit_sha="abc123",
    )
    second = deterministic_memory_source_ref(
        namespace,
        event_kind="blueprint_frozen",
        event_id="bp-1",
        commit_sha="abc123",
    )

    assert first == second
    assert first == "memory://conversation/conv-1/commits/abc123/events/blueprint_frozen/bp-1"


@pytest.mark.asyncio
async def test_rest_memoryos_client_degrades_when_service_is_missing() -> None:
    def raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    transport = httpx.MockTransport(raise_connect_error)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = RestMemoryOSClient(base_url="http://memoryos.test", http_client=http_client)
        result = await client.ingest(
            MemoryOSIngestRequest(
                namespace=conversation_namespace("conv-1"),
                content="Local fake flows should continue.",
                source_refs=["message:1"],
            )
        )
        context = await client.build_context(
            conversation_namespace("conv-1"),
            query="continue",
        )

    assert result.ok is False
    assert result.degraded_reason == "memoryos_unavailable"
    assert context.text == ""
    assert context.degraded_reason == "memoryos_unavailable"
