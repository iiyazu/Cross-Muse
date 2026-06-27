from __future__ import annotations

from xmuse_core.integrations.a2a_sdk_boundary import (
    A2ASDKBoundary,
    a2a_sdk_dependency_status,
    normalize_task_result_payload,
    normalize_task_send_payload,
)


def test_a2a_sdk_dependency_is_importable() -> None:
    status = a2a_sdk_dependency_status()

    assert status["available"] is True
    assert status["import_name"] == "a2a"
    assert isinstance(status["version"], str)
    assert status["version"]
    assert status["models"] == (
        "AgentCard",
        "AgentCapabilities",
        "AgentSkill",
        "Task",
        "Artifact",
    )


def test_a2a_sdk_boundary_names_non_goals() -> None:
    boundary = A2ASDKBoundary()

    assert boundary.protocol == "a2a-sdk"
    assert boundary.authority == "xmuse-chat-db"
    assert boundary.supported_now == (
        "agent_card_model",
        "send_message_request_model",
        "artifact_parts_model",
        "task_result_normalization",
        "jsonrpc_http_boundary",
        "xmuse_authority_normalization",
    )
    assert boundary.deferred == (
        "streaming",
        "push_notifications",
        "direct_review_or_dispatch_authority",
    )


def test_a2a_official_sendmessage_jsonrpc_normalizes_to_task_send() -> None:
    result = normalize_task_send_payload(
        {
            "jsonrpc": "2.0",
            "id": "rpc-send",
            "method": "SendMessage",
            "params": {
                "tenant": "external-a2a",
                "message": {
                    "messageId": "msg-send",
                    "taskId": "task-send",
                    "contextId": "conv-send",
                    "role": "ROLE_USER",
                    "parts": [{"text": "@review inspect official SDK method."}],
                    "metadata": {
                        "sender_agent_id": "external-a2a",
                        "target_address": "@review",
                        "metadata": {"purpose": "official-sdk"},
                    },
                },
            },
        }
    )

    assert result.method == "SendMessage"
    assert result.jsonrpc_id == "rpc-send"
    assert result.task_id == "task-send"
    assert result.context_id == "conv-send"
    assert result.sender_agent_id == "external-a2a"
    assert result.target_address == "@review"
    assert result.content == "@review inspect official SDK method."
    assert result.metadata == {"purpose": "official-sdk"}
    assert result.sdk_request["message"]["task_id"] == "task-send"


def test_a2a_task_result_normalizes_completed_artifacts() -> None:
    result = normalize_task_result_payload(
        {
            "jsonrpc": "2.0",
            "id": "rpc-done",
            "result": {
                "id": "task-done",
                "contextId": "conv-1",
                "status": {"state": "TASK_STATE_COMPLETED"},
                "artifacts": [
                    {
                        "artifactId": "artifact-1",
                        "name": "review-evidence",
                        "description": "A2A result evidence",
                        "parts": [
                            {"text": "review result text"},
                            {"data": {"verdict": "pass"}},
                            {
                                "url": "file:///tmp/evidence.md",
                                "filename": "evidence.md",
                                "mediaType": "text/markdown",
                            },
                        ],
                    }
                ],
                "metadata": {"source": "remote-a2a"},
            },
        }
    )

    assert result.task_id == "task-done"
    assert result.context_id == "conv-1"
    assert result.state == "TASK_STATE_COMPLETED"
    assert result.disposition == "completed"
    assert result.terminal is True
    assert result.content == (
        "review result text\n"
        '{"verdict": "pass"}\n'
        "[a2a-url:file:///tmp/evidence.md]"
    )
    assert result.source_refs == ("a2a_task:task-done", "a2a_context:conv-1")
    assert result.artifacts[0]["parts"][0] == {"text": "review result text", "kind": "text"}
    assert result.artifacts[0]["parts"][1]["kind"] == "data"
    assert result.artifacts[0]["parts"][2]["kind"] == "url"
    assert result.metadata == {"source": "remote-a2a"}
    assert result.jsonrpc_id == "rpc-done"


def test_a2a_task_result_maps_input_required_to_blocked_without_authority_claim() -> None:
    result = normalize_task_result_payload(
        {
            "id": "task-input",
            "contextId": "conv-2",
            "status": {
                "state": "TASK_STATE_INPUT_REQUIRED",
                "message": {
                    "messageId": "msg-input",
                    "contextId": "conv-2",
                    "taskId": "task-input",
                    "role": "ROLE_AGENT",
                    "parts": [{"text": "Need a source ref before review."}],
                },
            },
        }
    )

    assert result.state == "TASK_STATE_INPUT_REQUIRED"
    assert result.disposition == "blocked"
    assert result.terminal is True
    assert result.content == "Need a source ref before review."
    assert result.source_refs == ("a2a_task:task-input", "a2a_context:conv-2")
    assert "review_verdict" not in result.metadata
    assert "dispatch_allowed" not in result.metadata


def test_a2a_task_result_maps_jsonrpc_error_to_failed_diagnostic() -> None:
    result = normalize_task_result_payload(
        {
            "jsonrpc": "2.0",
            "id": "rpc-failed",
            "error": {
                "code": -32000,
                "message": "remote agent unavailable",
                "data": {"retryable": False},
            },
        }
    )

    assert result.task_id == "rpc-failed"
    assert result.state == "TASK_STATE_FAILED"
    assert result.disposition == "failed"
    assert result.terminal is True
    assert result.content == "remote agent unavailable"
    assert result.source_refs == ("a2a_jsonrpc_error:rpc-failed",)
    assert result.metadata["jsonrpc_error"]["code"] == -32000
