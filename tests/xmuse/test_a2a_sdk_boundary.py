from __future__ import annotations

from xmuse_core.integrations.a2a_sdk_boundary import (
    A2ASDKBoundary,
    a2a_sdk_dependency_status,
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
        "task_send_model",
        "artifact_parts_model",
    )
    assert boundary.deferred == (
        "streaming",
        "push_notifications",
        "direct_review_or_dispatch_authority",
    )
