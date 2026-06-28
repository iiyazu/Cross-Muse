from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from xmuse_core.chat.memory_sidecar import GroupchatMemorySidecar
from xmuse_core.integrations.memoryos_client import (
    FakeMemoryOSClient,
    MemoryOSContext,
    MemoryOSIngestRequest,
)
from xmuse_core.integrations.memoryos_namespace import conversation_namespace


@pytest.mark.asyncio
async def test_memory_sidecar_probe_reports_available_namespace_client() -> None:
    sidecar = GroupchatMemorySidecar(FakeMemoryOSClient())

    result = await sidecar.probe(conversation_id="conv-1", query="health")

    assert result == {
        "status": "available",
        "authority": "memoryos_sidecar",
        "proof_level": "contract",
        "namespace_uri": "memory://conversation/conv-1",
        "degraded_reason": None,
    }


@pytest.mark.asyncio
async def test_memory_sidecar_probe_reports_degraded_without_blocking() -> None:
    class DegradedClient:
        async def build_context(self, namespace, *, query: str, budget: int = 4096):
            assert namespace == conversation_namespace("conv-1")
            return MemoryOSContext(
                namespace_uri=namespace.uri,
                text="",
                degraded_reason="memoryos_unavailable",
            )

    sidecar = GroupchatMemorySidecar(DegradedClient())

    result = await sidecar.probe(conversation_id="conv-1", query="health")

    assert result["status"] == "degraded"
    assert result["authority"] == "memoryos_sidecar"
    assert result["proof_level"] == "degraded"
    assert result["namespace_uri"] == "memory://conversation/conv-1"
    assert result["degraded_reason"] == "memoryos_unavailable"


@pytest.mark.asyncio
async def test_memory_sidecar_recall_reports_timeout_without_blocking() -> None:
    class SlowClient:
        async def build_context(self, namespace, *, query: str, budget: int = 4096):
            await asyncio.sleep(30)
            raise AssertionError("timeout should cancel slow MemoryOS recall")

    sidecar = GroupchatMemorySidecar(SlowClient(), timeout_s=0.001)
    inbox_item = SimpleNamespace(
        payload={"content": "@architect continue"},
        item_type="mention",
    )

    result = await sidecar.recall_for_turn(
        conversation_id="conv-1",
        actor_id="architect-1",
        inbox_item=inbox_item,
    )

    assert result["status"] == "degraded"
    assert result["authority"] == "memoryos_sidecar"
    assert result["proof_level"] == "degraded"
    assert result["namespace_uri"] == "memory://conversation/conv-1"
    assert result["actor_id"] == "architect-1"
    assert result["query"] == "@architect continue"
    assert result["degraded_reason"] == "memoryos_timeout"
    assert result["source_refs"] == []
    assert "continuity_refs" not in result
    assert result["continuity_attempt_ref"] == (
        "memory://conversation/conv-1/context/memoryos-sidecar-attempt"
    )


@pytest.mark.asyncio
async def test_memory_sidecar_recall_attaches_namespace_continuity_refs() -> None:
    memoryos = FakeMemoryOSClient()
    namespace = conversation_namespace("conv-1")
    await memoryos.ingest(
        MemoryOSIngestRequest(
            namespace=namespace,
            actor_id="god-review",
            content="@architect use prior review: prior review approved the bounded lane.",
            source_refs=["review:verdict-1"],
        )
    )
    sidecar = GroupchatMemorySidecar(memoryos)
    inbox_item = SimpleNamespace(
        payload={"content": "@architect use prior review"},
        item_type="mention",
    )

    result = await sidecar.recall_for_turn(
        conversation_id="conv-1",
        actor_id="architect-1",
        inbox_item=inbox_item,
    )

    assert result["status"] == "attached"
    assert result["source_refs"] == ["review:verdict-1"]
    assert result["continuity_ref"] == (
        "memory://conversation/conv-1/context/memoryos-sidecar"
    )
    assert result["continuity_refs"] == [
        "memory://conversation/conv-1/context/memoryos-sidecar"
    ]
    assert result["continuity_attempt_ref"] == (
        "memory://conversation/conv-1/context/memoryos-sidecar-attempt"
    )
