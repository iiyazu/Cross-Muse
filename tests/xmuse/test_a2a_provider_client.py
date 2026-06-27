from __future__ import annotations

import json

import httpx
import pytest

from xmuse_core.integrations.a2a_provider_client import (
    A2AProviderClient,
    A2AProviderTaskRequest,
)


@pytest.mark.asyncio
async def test_a2a_provider_client_sends_sdk_request_and_normalizes_task_result() -> None:
    captured: list[dict[str, object]] = []

    def route(request: httpx.Request) -> httpx.Response:
        payload = request.read()
        body = json.loads(payload)
        captured.append(body)
        assert request.headers["Authorization"] == "Bearer secret"
        assert body["jsonrpc"] == "2.0"
        assert body["method"] == "SendMessage"
        assert body["params"]["message"]["task_id"] == "task-remote"
        assert body["params"]["message"]["context_id"] == "conv-remote"
        assert body["params"]["message"]["parts"] == [
            {"text": "@review inspect remote output."},
            {"data": {"evidence": "bounded"}},
            {
                "url": "file:///tmp/evidence.md",
                "metadata": {"file_id": "file:///tmp/evidence.md"},
                "filename": "evidence.md",
                "media_type": "text/markdown",
            },
        ]
        assert body["params"]["message"]["metadata"]["purpose"] == "review_request"
        assert body["params"]["message"]["metadata"]["metadata"] == {
            "purpose": "review_request"
        }
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "task": {
                        "id": "task-remote",
                        "contextId": "conv-remote",
                        "status": {"state": "TASK_STATE_COMPLETED"},
                        "artifacts": [
                            {
                                "artifactId": "artifact-remote",
                                "name": "remote-output",
                                "parts": [{"text": "remote review output"}],
                            }
                        ],
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http_client:
        result = await A2AProviderClient(
            "https://remote.example/a2a",
            api_key="secret",
            http_client=http_client,
        ).invoke_task(
            A2AProviderTaskRequest(
                task_id="task-remote",
                context_id="conv-remote",
                sender_agent_id="xmuse-architect",
                target_address="@review",
                content="@review inspect remote output.",
                metadata={"purpose": "review_request"},
                input_parts=(
                    {"kind": "data", "data": {"evidence": "bounded"}},
                    {
                        "kind": "file",
                        "file_id": "file:///tmp/evidence.md",
                        "filename": "evidence.md",
                        "media_type": "text/markdown",
                    },
                ),
            )
        )

    assert captured
    assert result.task_id == "task-remote"
    assert result.context_id == "conv-remote"
    assert result.disposition == "completed"
    assert result.content == "remote review output"
    assert result.source_refs == ("a2a_task:task-remote", "a2a_context:conv-remote")
    assert "dispatch_allowed" not in result.metadata
    assert "review_verdict" not in result.metadata


@pytest.mark.asyncio
async def test_a2a_provider_client_normalizes_message_result() -> None:
    def route(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "message": {
                        "messageId": "msg-remote",
                        "taskId": "task-message",
                        "contextId": "conv-message",
                        "role": "ROLE_AGENT",
                        "parts": [{"text": "message-only response"}],
                    }
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http_client:
        result = await A2AProviderClient(
            "https://remote.example/a2a",
            http_client=http_client,
        ).invoke_task(
            A2AProviderTaskRequest(
                task_id="task-message",
                context_id="conv-message",
                sender_agent_id="xmuse-architect",
                content="@review inspect remote output.",
            )
        )

    assert result.task_id == "task-message"
    assert result.disposition == "completed"
    assert result.content == "message-only response"


@pytest.mark.asyncio
async def test_a2a_provider_client_maps_jsonrpc_error_to_failed_diagnostic() -> None:
    def route(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.read())
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32000, "message": "remote unavailable"},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(route)) as http_client:
        result = await A2AProviderClient(
            "https://remote.example/a2a",
            http_client=http_client,
        ).invoke_task(
            A2AProviderTaskRequest(
                task_id="task-error",
                context_id="conv-error",
                sender_agent_id="xmuse-architect",
                content="@review inspect remote output.",
            )
        )

    assert result.task_id == "task-error"
    assert result.disposition == "failed"
    assert result.terminal is True
    assert result.content == "remote unavailable"
