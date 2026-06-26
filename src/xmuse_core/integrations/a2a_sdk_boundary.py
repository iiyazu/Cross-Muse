from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata

from a2a import types as a2a_types


@dataclass(frozen=True)
class A2ASDKBoundary:
    protocol: str = "a2a-sdk"
    authority: str = "xmuse-chat-db"
    supported_now: tuple[str, ...] = (
        "agent_card_model",
        "task_send_model",
        "artifact_parts_model",
    )
    deferred: tuple[str, ...] = (
        "streaming",
        "push_notifications",
        "direct_review_or_dispatch_authority",
    )


def a2a_sdk_dependency_status() -> dict[str, object]:
    return {
        "available": True,
        "import_name": "a2a",
        "version": metadata.version("a2a-sdk"),
        "models": _sdk_model_names(),
    }


def _sdk_model_names() -> tuple[str, ...]:
    return (
        a2a_types.AgentCard.__name__,
        a2a_types.AgentCapabilities.__name__,
        a2a_types.AgentSkill.__name__,
        a2a_types.Task.__name__,
        a2a_types.Artifact.__name__,
    )
