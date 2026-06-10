from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from xmuse.mcp_server import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatError, PeerChatService
from xmuse_core.chat.store import ChatStore


def _mcp_call(client: TestClient, name: str, arguments: dict):
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return response.json()["result"]["content"][0]["text"]


def _registered_participant(tmp_path):
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Budget")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    session = GodSessionRegistry(tmp_path / "god_sessions.json").create(
        role="architect",
        agent_name="Architect GOD",
        runtime="codex",
        session_address=f"xmuse://{conv.id}/{participant.participant_id}",
        session_inbox_id=f"inbox-{participant.participant_id}",
        conversation_id=conv.id,
        participant_id=participant.participant_id,
    )
    return chat, conv, participant, session


def test_human_message_resets_autonomous_turn_budget(tmp_path):
    chat, conv, _participant, _session = _registered_participant(tmp_path)
    store = ChatStore(tmp_path / "chat.db")
    store.set_turn_budget_remaining(conv.id, 0)

    PeerChatService(tmp_path / "chat.db").post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content="@architect start",
        client_request_id="human-reset",
    )

    assert chat.get_turn_budget_remaining(conv.id) == 8


def test_mcp_god_mentions_decrement_budget_and_stop_at_zero(tmp_path):
    chat, conv, architect, session = _registered_participant(tmp_path)
    review = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    store = ChatStore(tmp_path / "chat.db")
    store.reset_turn_budget(conv.id, amount=2)

    api = TestClient(create_app(tmp_path))
    for request_id in ("god-1", "god-2"):
        payload = _mcp_call(
            api,
            "chat_mention",
            {
                "conversation_id": conv.id,
                "participant_id": architect.participant_id,
                "god_session_id": session.god_session_id,
                "client_request_id": request_id,
                "target_address": "@review",
                "content": "please review",
            },
        )
        assert "turn_budget_exhausted" not in payload

    assert store.get_turn_budget_remaining(conv.id) == 0
    exhausted = _mcp_call(
        api,
        "chat_mention",
        {
            "conversation_id": conv.id,
            "participant_id": architect.participant_id,
            "god_session_id": session.god_session_id,
            "client_request_id": "god-3",
            "target_address": "@review",
            "content": "blocked",
        },
    )

    assert review.participant_id
    assert "turn_budget_exhausted" in exhausted


def test_idempotent_god_mention_retry_does_not_consume_budget_twice(tmp_path):
    _chat, conv, architect, session = _registered_participant(tmp_path)
    ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(tmp_path / "chat.db")
    store = ChatStore(tmp_path / "chat.db")
    store.reset_turn_budget(conv.id, amount=2)

    kwargs = {
        "registry_path": tmp_path / "god_sessions.json",
        "conversation_id": conv.id,
        "participant_id": architect.participant_id,
        "god_session_id": session.god_session_id,
        "client_request_id": "same-god-request",
        "target_address": "@review",
        "content": "please review",
    }
    first = service.mention_from_god(**kwargs)
    second = service.mention_from_god(**kwargs)

    assert second["message"]["id"] == first["message"]["id"]
    assert store.get_turn_budget_remaining(conv.id) == 1


def test_god_mention_retry_replays_after_target_stops(tmp_path):
    _chat, conv, architect, session = _registered_participant(tmp_path)
    participants = ParticipantStore(tmp_path / "chat.db")
    review = participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(tmp_path / "chat.db")
    store = ChatStore(tmp_path / "chat.db")
    store.reset_turn_budget(conv.id, amount=2)

    kwargs = {
        "registry_path": tmp_path / "god_sessions.json",
        "conversation_id": conv.id,
        "participant_id": architect.participant_id,
        "god_session_id": session.god_session_id,
        "client_request_id": "same-after-target-stopped",
        "target_address": "@review",
        "content": "please review",
    }
    first = service.mention_from_god(**kwargs)
    participants.update_status(review.participant_id, "stopped")
    second = service.mention_from_god(**kwargs)

    assert second["message"]["id"] == first["message"]["id"]
    assert store.get_turn_budget_remaining(conv.id) == 1


def test_god_mention_requires_registered_session_for_budget_path(tmp_path):
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Budget")
    architect = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    GodSessionRegistry(tmp_path / "god_sessions.json")
    store = ChatStore(tmp_path / "chat.db")
    store.reset_turn_budget(conv.id, amount=1)

    with pytest.raises(PeerChatError, match="unknown_god_session"):
        PeerChatService(tmp_path / "chat.db").mention_from_god(
            registry_path=tmp_path / "god_sessions.json",
            conversation_id=conv.id,
            participant_id=architect.participant_id,
            god_session_id="unknown-session",
            client_request_id="spoofed",
            target_address="@architect",
            content="spoofed",
        )

    assert store.get_turn_budget_remaining(conv.id) == 1
