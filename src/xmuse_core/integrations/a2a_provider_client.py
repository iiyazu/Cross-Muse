from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from xmuse_core.integrations.a2a_sdk_boundary import (
    NormalizedA2ATaskResult,
    normalize_task_result_payload,
    normalize_task_send_payload,
)


@dataclass(frozen=True)
class A2AProviderTaskRequest:
    task_id: str
    context_id: str
    sender_agent_id: str
    content: str
    target_address: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    input_parts: tuple[dict[str, Any], ...] = ()


class A2AProviderClient:
    """Minimal outbound A2A provider boundary.

    The client uses the official a2a-sdk protobuf request/response shape through
    `a2a_sdk_boundary`, but it deliberately returns only a normalized diagnostic
    result. Persisting that result into chat.db/inbox/review/dispatch remains a
    separate xmuse writeback reconciliation step.
    """

    def __init__(
        self,
        endpoint_url: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 120.0,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._endpoint_url = endpoint_url
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._http_client = http_client

    async def invoke_task(self, request: A2AProviderTaskRequest) -> NormalizedA2ATaskResult:
        normalized = normalize_task_send_payload(
            {
                "task_id": request.task_id,
                "context_id": request.context_id,
                "sender_agent_id": request.sender_agent_id,
                "content": request.content,
                "target_address": request.target_address,
                "metadata": request.metadata,
                "input_parts": list(request.input_parts),
            }
        )
        rpc = {
            "jsonrpc": "2.0",
            "id": normalized.task_id,
            "method": "SendMessage",
            "params": normalized.sdk_request,
        }
        try:
            response = await self._post(rpc)
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            return NormalizedA2ATaskResult(
                task_id=normalized.task_id,
                context_id=normalized.context_id,
                state="TASK_STATE_FAILED",
                disposition="failed",
                terminal=True,
                content=str(exc),
                metadata={"transport_error": exc.__class__.__name__},
                source_refs=(f"a2a_task:{normalized.task_id}",),
                jsonrpc_id=normalized.task_id,
            )
        return self._normalize_send_message_response(
            payload,
            task_id=normalized.task_id,
            context_id=normalized.context_id,
        )

    async def _post(self, rpc: dict[str, Any]) -> httpx.Response:
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else None
        if self._http_client is not None:
            response = await self._http_client.post(
                self._endpoint_url,
                json=rpc,
                headers=headers,
            )
            response.raise_for_status()
            return response
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(self._endpoint_url, json=rpc, headers=headers)
            response.raise_for_status()
            return response

    def _normalize_send_message_response(
        self,
        payload: dict[str, Any],
        *,
        task_id: str,
        context_id: str,
    ) -> NormalizedA2ATaskResult:
        if payload.get("jsonrpc") == "2.0" and "error" in payload:
            return normalize_task_result_payload(payload)
        result = payload.get("result")
        if not isinstance(result, dict):
            return normalize_task_result_payload(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id", task_id),
                    "error": {
                        "code": -32603,
                        "message": "A2A SendMessage response missing result object",
                    },
                }
            )
        if isinstance(result.get("task"), dict):
            return normalize_task_result_payload(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id", task_id),
                    "result": result["task"],
                }
            )
        if isinstance(result.get("message"), dict):
            message = result["message"]
            return normalize_task_result_payload(
                {
                    "jsonrpc": "2.0",
                    "id": payload.get("id", task_id),
                    "result": {
                        "id": message.get("taskId") or message.get("task_id") or task_id,
                        "contextId": message.get("contextId")
                        or message.get("context_id")
                        or context_id,
                        "status": {"state": "TASK_STATE_COMPLETED"},
                        "history": [message],
                    },
                }
            )
        return normalize_task_result_payload(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id", task_id),
                "error": {
                    "code": -32603,
                    "message": "A2A SendMessage response missing task or message payload",
                },
            }
        )
