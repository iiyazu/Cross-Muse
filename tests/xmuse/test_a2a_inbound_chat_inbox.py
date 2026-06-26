from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.integrations.a2a_bridge import (
    A2ABridgeError,
    A2AInboundBridge,
    A2AInboundTask,
)
from xmuse_core.integrations.a2a_sdk_boundary import A2ASDKBoundary


def test_a2a_inbound_bridge_disabled_does_not_write_chat(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation = ChatStore(db).create_conversation("A2A disabled")

    result = A2AInboundBridge(db).record_task_send(
        A2AInboundTask(
            task_id="task-disabled",
            context_id=conversation.id,
            sender_agent_id="external-agent",
            target_address="@review",
            content="@review inspect this",
        )
    )

    assert result == {
        "status": "disabled",
        "reason": "a2a_bridge_disabled",
        "task_id": "task-disabled",
    }
    assert ChatStore(db).list_messages(conversation.id) == []
    assert ChatInboxStore(db).list_by_conversation(conversation.id) == []


def test_a2a_task_send_enters_chat_inbox_as_durable_route(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A inbound")
    review = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    result = A2AInboundBridge(db, enabled=True).record_task_send(
        A2AInboundTask(
            task_id="task-1",
            context_id=conversation.id,
            sender_agent_id="external-planner",
            target_address="@review",
            content="@review inspect the boundary.",
            metadata={"purpose": "review_request"},
        )
    )

    assert result["status"] == "accepted"
    message = result["message"]
    assert message["author"] == "a2a:external-planner"
    assert message["envelope_type"] == "a2a_task"
    assert message["envelope_json"]["source_refs"] == [
        "a2a_task:task-1",
        f"a2a_context:{conversation.id}",
    ]
    inbox_item = ChatInboxStore(db).list_for_participant(
        conversation_id=conversation.id,
        participant_id=review.participant_id,
    )[0]
    assert inbox_item.item_type == "a2a_task"
    assert inbox_item.target_participant_id == review.participant_id
    assert inbox_item.sender_address == "a2a:external-planner"
    assert inbox_item.payload["source_refs"] == [
        "a2a_task:task-1",
        f"a2a_context:{conversation.id}",
    ]
    assert inbox_item.payload["a2a_metadata"] == {"purpose": "review_request"}


def test_a2a_task_send_is_idempotent_by_task_id(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A idempotent")
    review = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    bridge = A2AInboundBridge(db, enabled=True)
    task = A2AInboundTask(
        task_id="task-idempotent",
        context_id=conversation.id,
        sender_agent_id="external-planner",
        target_address="@review",
        content="@review inspect the boundary.",
    )

    first = bridge.record_task_send(task)
    second = bridge.record_task_send(task)

    assert second == first
    assert len(ChatStore(db).list_messages(conversation.id)) == 1
    assert len(
        ChatInboxStore(db).list_for_participant(
            conversation_id=conversation.id,
            participant_id=review.participant_id,
        )
    ) == 1


def test_a2a_task_send_missing_target_fails_before_write(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation = ChatStore(db).create_conversation("A2A missing target")

    with pytest.raises(A2ABridgeError, match="missing_a2a_target"):
        A2AInboundBridge(db, enabled=True).record_task_send(
            A2AInboundTask(
                task_id="task-missing",
                context_id=conversation.id,
                sender_agent_id="external-planner",
                content="No target here.",
            )
        )

    assert ChatStore(db).list_messages(conversation.id) == []
    assert ChatInboxStore(db).list_by_conversation(conversation.id) == []


def test_a2a_task_send_multiple_targets_fails_before_write(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation = ChatStore(db).create_conversation("A2A multiple target")
    participants = ParticipantStore(db)
    participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    with pytest.raises(A2ABridgeError, match="multiple_a2a_targets"):
        A2AInboundBridge(db, enabled=True).record_task_send(
            A2AInboundTask(
                task_id="task-multiple",
                context_id=conversation.id,
                sender_agent_id="external-planner",
                content="@architect @review split this request.",
            )
        )

    assert ChatStore(db).list_messages(conversation.id) == []
    assert ChatInboxStore(db).list_by_conversation(conversation.id) == []


def test_a2a_task_send_does_not_create_authority_objects(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A authority")
    ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    A2AInboundBridge(db, enabled=True).record_task_send(
        A2AInboundTask(
            task_id="task-authority",
            context_id=conversation.id,
            sender_agent_id="external-planner",
            target_address="@review",
            content="@review inspect this.",
        )
    )

    assert ChatStore(db).list_proposals(conversation.id) == []
    assert AcceptanceSpineStore(db).list_by_conversation(conversation.id) == []
    assert A2ASDKBoundary().authority == "xmuse-chat-db"
    assert not (tmp_path / "feature_lanes.json").exists()
    assert not (tmp_path / "final_actions.json").exists()


def test_a2a_task_send_api_is_opt_in_and_preserves_source_refs(tmp_path: Path) -> None:
    disabled = TestClient(create_app(base_dir=tmp_path))
    disabled_response = disabled.post(
        "/a2a/tasks/send",
        json={
            "task_id": "task-disabled-api",
            "context_id": "conv-missing",
            "sender_agent_id": "external-planner",
            "target_address": "@review",
            "content": "@review inspect this API route.",
        },
    )
    assert disabled_response.status_code == 404
    assert disabled_response.json()["detail"]["code"] == "a2a_bridge_disabled"

    client = TestClient(create_app(base_dir=tmp_path, a2a_bridge_enabled=True))
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "A2A API", "initial_participants": []},
    ).json()
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation["id"],
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    response = client.post(
        "/a2a/tasks/send",
        json={
            "task_id": "task-api",
            "context_id": conversation["id"],
            "sender_agent_id": "external-planner",
            "target_address": "@review",
            "content": "@review inspect this API route.",
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "accepted"
    assert payload["inbox_items"][0]["payload"]["source_refs"] == [
        "a2a_task:task-api",
        f"a2a_context:{conversation['id']}",
    ]
