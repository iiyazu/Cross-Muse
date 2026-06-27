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
    assert inbox_item.payload["natural_route"]["route_kind"] == "review_request"
    assert inbox_item.payload["natural_route"]["status"] == "blocked"
    assert inbox_item.payload["blocker_reason"] == "missing_handoff_fields"
    assert inbox_item.payload["blocks_dispatch"] is True
    assert inbox_item.payload["handoff_assessment"]["requires_envelope"] is True
    assert inbox_item.payload["handoff_assessment"]["missing_fields"] == [
        "what",
        "why",
        "tradeoffs",
        "open_questions",
        "next_action",
        "evidence_refs",
    ]
    assert inbox_item.payload["handoff_envelope"]["schema_version"] == (
        "xmuse-natural-handoff-v1"
    )
    assert inbox_item.payload["handoff_envelope"]["target_participant_id"] == (
        review.participant_id
    )


def test_a2a_complete_review_task_records_canonical_handoff_envelope(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A complete handoff")
    review = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    result = A2AInboundBridge(db, enabled=True).record_task_send(
        A2AInboundTask(
            task_id="task-complete-review",
            context_id=conversation.id,
            sender_agent_id="external-planner",
            target_address="@review",
            content=(
                "@review\n"
                "what: inspect the A2A handoff boundary.\n"
                "why: provider tasks need durable xmuse authority.\n"
                "tradeoffs: keep A2A as interop, not authority.\n"
                "open questions: none for this narrow contract.\n"
                "next action: review the inbox payload.\n"
                "evidence refs: a2a_task:task-complete-review"
            ),
            metadata={"feature_scope_id": "feature_scope:a2a-inbound"},
            input_parts=({"kind": "url", "url": "file:///tmp/evidence.md"},),
        )
    )

    assert result["status"] == "accepted"
    inbox_item = ChatInboxStore(db).list_for_participant(
        conversation_id=conversation.id,
        participant_id=review.participant_id,
    )[0]
    assert inbox_item.item_type == "a2a_task"
    assert inbox_item.payload["natural_route"]["route_kind"] == "review_request"
    assert inbox_item.payload["natural_route"]["status"] == "pending"
    assert "blocks_dispatch" not in inbox_item.payload
    assert inbox_item.payload["handoff_assessment"]["is_complete"] is True
    assert inbox_item.payload["handoff_assessment"]["missing_fields"] == []
    assert inbox_item.payload["handoff_envelope"] == {
        "type": "natural_handoff",
        "schema_version": "xmuse-natural-handoff-v1",
        "task_id": "task-complete-review",
        "conversation_id": conversation.id,
        "feature_scope_id": "feature_scope:a2a-inbound",
        "origin_message_id": "task-complete-review",
        "source_message_id": "task-complete-review",
        "source_inbox_item_id": None,
        "source_kind": "a2a_inbound",
        "author_participant_id": "a2a:external-planner",
        "source_participant_id": "a2a:external-planner",
        "target_participant_id": review.participant_id,
        "target_participant_ids": [review.participant_id],
        "target_role": "review",
        "intent": "review_request",
        "route_kind": "review_request",
        "requires_envelope": True,
        "is_complete": True,
        "missing_fields": [],
        "input_parts": [{"kind": "url", "url": "file:///tmp/evidence.md"}],
        "artifact_refs": ["file:///tmp/evidence.md"],
        "what": "inspect the A2A handoff boundary.",
        "why": "provider tasks need durable xmuse authority.",
        "tradeoffs": "keep A2A as interop, not authority.",
        "open_questions": "none for this narrow contract.",
        "next_action": "review the inbox payload.",
        "evidence_refs": [
            "a2a_task:task-complete-review",
            f"a2a_context:{conversation.id}",
        ],
        "fields": {
            "what": "inspect the A2A handoff boundary.",
            "why": "provider tasks need durable xmuse authority.",
            "tradeoffs": "keep A2A as interop, not authority.",
            "open_questions": "none for this narrow contract.",
            "next_action": "review the inbox payload.",
            "evidence_refs": "a2a_task:task-complete-review",
        },
        "source_refs": [
            "a2a_task:task-complete-review",
            f"a2a_context:{conversation.id}",
        ],
    }


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
    assert payload["a2a_sdk"]["protocol"] == "a2a-sdk"
    assert payload["a2a_sdk"]["method"] == "tasks/send"
    assert payload["a2a_sdk"]["authority"] == "xmuse-chat-db"
    assert payload["a2a_sdk"]["input_parts"] == [
        {"text": "@review inspect this API route.", "kind": "text"}
    ]
    assert payload["inbox_items"][0]["payload"]["source_refs"] == [
        "a2a_task:task-api",
        f"a2a_context:{conversation['id']}",
    ]
    assert payload["inbox_items"][0]["payload"]["a2a_sdk_boundary"] == {
        "protocol": "a2a-sdk",
        "authority": "xmuse-chat-db",
    }


def test_a2a_task_send_write_token_rejects_missing_and_accepts_valid_token(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            base_dir=tmp_path,
            a2a_bridge_enabled=True,
            a2a_write_token="a2a-secret",
        )
    )
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "A2A token gate", "initial_participants": []},
    ).json()
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation["id"],
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    body = {
        "task_id": "task-token",
        "context_id": conversation["id"],
        "sender_agent_id": "external-planner",
        "target_address": "@architect",
        "content": "@architect inspect this API route.",
    }

    rejected = client.post("/a2a/tasks/send", json=body)
    accepted = client.post(
        "/a2a/tasks/send",
        json=body,
        headers={"X-XMUSE-A2A-Key": "a2a-secret"},
    )

    assert rejected.status_code == 401
    assert rejected.json()["detail"]["code"] == "a2a_write_auth_required"
    assert accepted.status_code == 202
    assert accepted.json()["status"] == "accepted"


def test_a2a_jsonrpc_task_send_auth_failure_preserves_rpc_envelope(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            base_dir=tmp_path,
            a2a_bridge_enabled=True,
            a2a_write_token="a2a-secret",
        )
    )

    response = client.post(
        "/a2a/tasks/send",
        json={
            "jsonrpc": "2.0",
            "id": "rpc-auth-required",
            "method": "SendMessage",
            "params": {
                "tenant": "external-a2a",
                "message": {
                    "messageId": "msg-auth-required",
                    "taskId": "task-auth-required",
                    "contextId": "conv-auth-required",
                    "role": "ROLE_USER",
                    "parts": [{"text": "@review inspect auth boundary."}],
                    "metadata": {
                        "sender_agent_id": "external-a2a",
                        "target_address": "@review",
                    },
                },
            },
        },
    )

    assert response.status_code == 401
    assert response.json() == {
        "jsonrpc": "2.0",
        "id": "rpc-auth-required",
        "error": {
            "code": -32001,
            "message": "a2a_write_auth_required",
            "data": {
                "detail": "A2A task/send requires a valid write token",
            },
        },
    }
    assert ChatStore(tmp_path / "chat.db").list_conversations() == []


def test_a2a_jsonrpc_send_message_request_enters_chat_inbox(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            base_dir=tmp_path,
            a2a_bridge_enabled=True,
            a2a_write_token="a2a-secret",
        )
    )
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "A2A SDK JSON-RPC", "initial_participants": []},
    ).json()
    architect = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation["id"],
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    response = client.post(
        "/a2a/tasks/send",
        headers={"Authorization": "Bearer a2a-secret"},
        json={
            "jsonrpc": "2.0",
            "id": "rpc-1",
            "method": "message/send",
            "params": {
                "tenant": "external-planner",
                "message": {
                    "messageId": "msg-sdk",
                    "taskId": "task-sdk",
                    "contextId": conversation["id"],
                    "role": "ROLE_USER",
                    "parts": [{"text": "@architect inspect the SDK boundary."}],
                    "metadata": {
                        "sender_agent_id": "external-planner",
                        "target_address": "@architect",
                        "metadata": {"purpose": "sdk-boundary"},
                    },
                },
            },
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "rpc-1"
    result = payload["result"]
    assert result["status"] == "accepted"
    assert result["a2a_sdk"]["method"] == "message/send"
    assert result["a2a_sdk"]["sdk_request"]["message"]["task_id"] == "task-sdk"
    inbox_item = ChatInboxStore(tmp_path / "chat.db").list_for_participant(
        conversation_id=conversation["id"],
        participant_id=architect.participant_id,
    )[0]
    assert inbox_item.payload["a2a_input_parts"] == [
        {"text": "@architect inspect the SDK boundary.", "kind": "text"}
    ]
    assert inbox_item.payload["a2a_metadata"] == {"purpose": "sdk-boundary"}
    assert inbox_item.payload["source_refs"] == [
        "a2a_task:task-sdk",
        f"a2a_context:{conversation['id']}",
    ]


def test_a2a_official_sendmessage_request_enters_chat_inbox(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_app(
            base_dir=tmp_path,
            a2a_bridge_enabled=True,
            a2a_write_token="a2a-secret",
        )
    )
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "A2A official SendMessage", "initial_participants": []},
    ).json()
    review = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation["id"],
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    response = client.post(
        "/a2a/tasks/send",
        headers={"Authorization": "Bearer a2a-secret"},
        json={
            "jsonrpc": "2.0",
            "id": "rpc-official",
            "method": "SendMessage",
            "params": {
                "tenant": "external-a2a",
                "message": {
                    "messageId": "msg-official",
                    "taskId": "task-official",
                    "contextId": conversation["id"],
                    "role": "ROLE_USER",
                    "parts": [{"text": "@review inspect official SDK method."}],
                    "metadata": {
                        "sender_agent_id": "external-a2a",
                        "target_address": "@review",
                        "metadata": {"purpose": "official-sdk"},
                    },
                },
            },
        },
    )

    assert response.status_code == 202
    payload = response.json()
    assert payload["jsonrpc"] == "2.0"
    assert payload["id"] == "rpc-official"
    result = payload["result"]
    assert result["status"] == "accepted"
    assert result["a2a_sdk"]["method"] == "SendMessage"
    assert result["a2a_sdk"]["sdk_request"]["message"]["task_id"] == "task-official"
    inbox_item = ChatInboxStore(tmp_path / "chat.db").list_for_participant(
        conversation_id=conversation["id"],
        participant_id=review.participant_id,
    )[0]
    assert inbox_item.item_type == "a2a_task"
    assert inbox_item.payload["a2a_input_parts"] == [
        {"text": "@review inspect official SDK method.", "kind": "text"}
    ]
    assert inbox_item.payload["a2a_metadata"] == {"purpose": "official-sdk"}
    assert inbox_item.payload["source_refs"] == [
        "a2a_task:task-official",
        f"a2a_context:{conversation['id']}",
    ]
