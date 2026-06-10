from __future__ import annotations

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.peer_service import PeerChatService


def test_unaddressed_human_message_defaults_to_architect_inbox(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Default Intake Demo")

    result = service.post_human_message(
        conversation_id=created["conversation"]["id"],
        author="human-1",
        content="Need a plan for this feature.",
        client_request_id="req-default-intake",
    )

    assert result.message.role == "human"
    assert result.message.mentions == []
    assert len(result.inbox_items) == 1
    assert result.inbox_items[0].target_role == "architect"
    assert result.inbox_items[0].target_address == "@architect"
    assert result.inbox_items[0].item_type == "default_intake"


def test_explicit_mentions_do_not_also_create_default_architect_intake(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Explicit Mention Demo")

    result = service.post_human_message(
        conversation_id=created["conversation"]["id"],
        author="human-1",
        content="@review please check this and @execute prepare the patch.",
        client_request_id="req-explicit-mentions",
    )

    assert sorted(item.target_role for item in result.inbox_items) == ["execute", "review"]
    assert all(item.item_type == "mention" for item in result.inbox_items)


def test_unaddressed_human_message_replay_is_idempotent(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    created = service.create_conversation(title="Replay Demo")
    conversation_id = created["conversation"]["id"]

    first = service.post_human_message(
        conversation_id=conversation_id,
        author="human-1",
        content="Please take first pass on this request.",
        client_request_id="req-replay-default-intake",
    )
    second = service.post_human_message(
        conversation_id=conversation_id,
        author="human-1",
        content="Please take first pass on this request.",
        client_request_id="req-replay-default-intake",
    )

    inbox = ChatInboxStore(tmp_path / "chat.db").list_by_conversation(conversation_id)

    assert first.message.id == second.message.id
    assert [item.id for item in first.inbox_items] == [item.id for item in second.inbox_items]
    assert len(inbox) == 1
    assert inbox[0].target_role == "architect"


def test_chat_api_returns_default_intake_inbox_item_for_unaddressed_human_message(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = client.post("/api/chat/conversations", json={"title": "API Intake Demo"})
    conversation_id = conversation.json()["id"]

    response = client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={
            "author": "human-1",
            "role": "human",
            "content": "Can someone pick this up?",
            "client_request_id": "req-api-default-intake",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert len(payload["inbox_items"]) == 1
    assert payload["inbox_items"][0]["target_role"] == "architect"
    assert payload["inbox_items"][0]["item_type"] == "default_intake"
