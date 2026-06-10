from __future__ import annotations

import json
import os

import httpx
import pytest

from xmuse_core.integrations.memoryos_client import (
    MemoryOSIngestRequest,
    MemoryOSMemoryLayer,
)
from xmuse_core.integrations.memoryos_lite_interop import (
    LIVE_MEMORYOS_LITE_ENV,
    MEMORYOS_LITE_BASE_URL_ENV,
    MemoryOSLiteInteropAdapter,
    build_memoryos_lite_build_context_payload,
    build_memoryos_lite_create_session_payload,
    build_memoryos_lite_ingest_payload,
    build_memoryos_lite_interop_plan,
    build_memoryos_lite_search_payload,
    live_memoryos_lite_enabled,
    memoryos_lite_session_title,
)
from xmuse_core.integrations.memoryos_namespace import task_namespace


def _task_namespace():
    return task_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        god_id="god-review",
        conversation_id="conv-1",
        thread_id="thread-1",
        blueprint_id="bp-1",
        feature_id="feature-1",
        lane_id="lane-1",
    )


def test_memoryos_lite_session_plan_maps_task_namespace_to_session_contract() -> None:
    namespace = _task_namespace()

    plan = build_memoryos_lite_interop_plan(namespace)

    assert plan.proof_level == "contract"
    assert plan.namespace_uri == namespace.uri
    assert plan.session_title == memoryos_lite_session_title(namespace)
    assert plan.session_title.startswith("xmuse:task:")
    assert plan.session_metadata["xmuse_namespace_uri"] == namespace.uri
    assert plan.endpoint_plan.create_session == "/sessions"
    assert plan.endpoint_plan.ingest == "/sessions/{session_id}/ingest"
    assert plan.endpoint_plan.build_context == "/sessions/{session_id}/build-context"
    assert plan.endpoint_plan.search == "/memory/search"


def test_memoryos_lite_payload_builders_match_session_centric_api() -> None:
    namespace = _task_namespace()
    ingest_request = MemoryOSIngestRequest(
        namespace=namespace,
        actor_id="god-review",
        content="Review accepted the lane.",
        source_refs=["lane:lane-1", "commit:abc123"],
        memory_layer=MemoryOSMemoryLayer.PINNED_CORE,
        metadata={"review_id": "rv-1"},
    )

    assert build_memoryos_lite_create_session_payload(namespace) == {
        "title": memoryos_lite_session_title(namespace),
    }
    assert build_memoryos_lite_build_context_payload(query="lane", budget=2048) == {
        "task": "lane",
        "budget": 2048,
        "retrieval_query": "lane",
        "include_global_core": False,
    }
    assert build_memoryos_lite_search_payload(
        session_id="ses-1",
        query="lane",
        limit=3,
    ) == {
        "query": "lane",
        "top_k": 3,
        "session_id": "ses-1",
        "limit": 3,
    }

    payload = build_memoryos_lite_ingest_payload(ingest_request)

    assert payload["role"] == "assistant"
    assert payload["content"] == "Review accepted the lane."
    metadata = payload["metadata"]
    assert isinstance(metadata, dict)
    assert metadata["xmuse_namespace_uri"] == namespace.uri
    assert metadata["xmuse_actor_id"] == "god-review"
    assert metadata["xmuse_memory_layer"] == "pinned_core"
    assert metadata["xmuse_source_refs"] == ["lane:lane-1", "commit:abc123"]
    assert metadata["xmuse_request_metadata"] == {"review_id": "rv-1"}


@pytest.mark.asyncio
async def test_memoryos_lite_adapter_uses_sessions_ingest_and_context_endpoints() -> None:
    namespace = _task_namespace()
    requests: list[tuple[str, dict[str, object]]] = []

    def route(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode() or "{}")
        requests.append((request.url.path, payload))
        if request.url.path == "/sessions":
            assert payload == {"title": memoryos_lite_session_title(namespace)}
            return httpx.Response(200, json={"id": "ses-task-1", "title": payload["title"]})
        if request.url.path == "/sessions/ses-task-1/ingest":
            metadata = payload["metadata"]
            assert metadata["xmuse_namespace_uri"] == namespace.uri
            assert metadata["xmuse_actor_id"] == "god-review"
            return httpx.Response(
                200,
                json={
                    "message": {
                        "id": "msg-1",
                        "session_id": "ses-task-1",
                        "role": payload["role"],
                        "content": payload["content"],
                        "metadata": metadata,
                    },
                    "should_page": False,
                    "session_token_count": 20,
                },
            )
        if request.url.path == "/sessions/ses-task-1/build-context":
            assert payload["task"] == "review"
            return httpx.Response(
                200,
                json={
                    "session_id": "ses-task-1",
                    "task": "review",
                    "pinned_core": ["Pinned architecture rule."],
                    "retrieved_evidence": [
                        {
                            "message_id": "msg-1",
                            "text": "Review accepted the lane.",
                            "role": "assistant",
                            "reason": "query_match",
                            "estimated_tokens": 5,
                            "metadata": {
                                "xmuse_source_refs": ["lane:lane-1"],
                            },
                        }
                    ],
                    "recent_messages": [],
                },
            )
        raise AssertionError(f"unexpected endpoint: {request.url.path}")

    transport = httpx.MockTransport(route)
    async with httpx.AsyncClient(transport=transport) as http_client:
        adapter = MemoryOSLiteInteropAdapter(
            base_url="http://memoryos-lite.test",
            http_client=http_client,
        )
        result = await adapter.ingest(
            MemoryOSIngestRequest(
                namespace=namespace,
                actor_id="god-review",
                content="Review accepted the lane.",
                source_refs=["lane:lane-1"],
            )
        )
        context = await adapter.build_context(namespace, query="review", budget=512)

    assert result.ok is True
    assert result.memory_ref == f"{namespace.uri}/messages/msg-1"
    assert context.namespace_uri == namespace.uri
    assert "Pinned architecture rule." in context.text
    assert "Review accepted the lane." in context.text
    assert context.source_refs == ["lane:lane-1", "memoryos-lite-message:msg-1"]
    assert [path for path, _payload in requests] == [
        "/sessions",
        "/sessions/ses-task-1/ingest",
        "/sessions/ses-task-1/build-context",
    ]


@pytest.mark.asyncio
async def test_memoryos_lite_adapter_maps_search_hits_to_xmuse_pages() -> None:
    namespace = _task_namespace()

    def route(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/sessions":
            return httpx.Response(200, json={"id": "ses-task-1"})
        if request.url.path == "/memory/search":
            payload = json.loads(request.content.decode())
            assert payload == {
                "query": "lane",
                "top_k": 2,
                "session_id": "ses-task-1",
                "limit": 2,
            }
            return httpx.Response(
                200,
                json=[
                    {
                        "page": {
                            "id": "page-1",
                            "session_id": "ses-task-1",
                            "title": "Lane decision",
                            "summary": "The lane is ready.",
                            "facts": ["fact-a"],
                            "decisions": ["decision-a"],
                            "open_questions": ["question-a"],
                            "source_message_ids": ["msg-1"],
                        },
                        "score": 0.9,
                        "reason": "hybrid",
                    }
                ],
            )
        raise AssertionError(f"unexpected endpoint: {request.url.path}")

    transport = httpx.MockTransport(route)
    async with httpx.AsyncClient(transport=transport) as http_client:
        adapter = MemoryOSLiteInteropAdapter(
            base_url="http://memoryos-lite.test",
            http_client=http_client,
        )
        results = await adapter.search(namespace, query="lane", limit=2)

    assert len(results) == 1
    assert results[0].namespace_uri == namespace.uri
    assert "Lane decision" in results[0].content
    assert "The lane is ready." in results[0].content
    assert results[0].source_refs == ["msg-1"]
    assert results[0].metadata["memoryos_lite_page_id"] == "page-1"
    assert results[0].metadata["memoryos_lite_reason"] == "hybrid"


def test_live_memoryos_lite_requires_explicit_opt_in_and_base_url() -> None:
    assert live_memoryos_lite_enabled({}) is False
    assert live_memoryos_lite_enabled({LIVE_MEMORYOS_LITE_ENV: "1"}) is False
    assert (
        live_memoryos_lite_enabled(
            {
                LIVE_MEMORYOS_LITE_ENV: "1",
                MEMORYOS_LITE_BASE_URL_ENV: "http://127.0.0.1:8000",
            }
        )
        is True
    )


@pytest.mark.asyncio
async def test_live_memoryos_lite_service_contract_is_explicit_opt_in() -> None:
    if not live_memoryos_lite_enabled():
        pytest.skip(
            f"set {LIVE_MEMORYOS_LITE_ENV}=1 and {MEMORYOS_LITE_BASE_URL_ENV} "
            "to run the live MemoryOS Lite interop smoke"
        )

    base_url = os.environ[MEMORYOS_LITE_BASE_URL_ENV]
    namespace = _task_namespace()
    async with httpx.AsyncClient(timeout=10) as http_client:
        health = await http_client.get(f"{base_url.rstrip('/')}/health")
        health.raise_for_status()
        adapter = MemoryOSLiteInteropAdapter(
            base_url=base_url,
            http_client=http_client,
        )
        result = await adapter.ingest(
            MemoryOSIngestRequest(
                namespace=namespace,
                actor_id="god-review",
                content="Live MemoryOS Lite opt-in smoke.",
                source_refs=["live:memoryos-lite:smoke"],
            )
        )
        context = await adapter.build_context(namespace, query="smoke", budget=256)

    assert result.ok is True
    assert result.degraded_reason is None
    assert context.degraded_reason is None
