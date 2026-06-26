from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.integrations.a2a_bridge import build_participant_agent_card


def test_participant_agent_card_uses_existing_profile_contract(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A card")
    participants = ParticipantStore(db)
    participant = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )

    card = build_participant_agent_card(
        participant,
        base_url="http://testserver/",
        active_participants=participants.list_by_conversation(conversation.id),
        session_binding=None,
    )

    assert card["protocolVersion"] == "1.0"
    assert card["name"] == "Review GOD"
    assert card["url"] == f"http://testserver/a2a/agents/{participant.participant_id}"
    assert card["capabilities"] == {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    }
    metadata = card["metadata"]
    assert metadata["authority"] == "chat.db"
    assert metadata["participant_id"] == participant.participant_id
    assert metadata["conversation_id"] == conversation.id
    assert metadata["role"] == "review"
    assert metadata["mention_handle"] == "@review"
    assert metadata["natural_profile"]["identity_authority_refs"] == [
        f"chat.db:participant:{participant.participant_id}",
        f"chat.db:conversation:{conversation.id}",
    ]


def test_a2a_agent_card_endpoint_is_disabled_by_default(tmp_path: Path) -> None:
    client = TestClient(create_app(base_dir=tmp_path))

    response = client.get("/a2a/agents/missing")

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "a2a_bridge_disabled",
        "message": "A2A bridge is disabled",
    }


def test_a2a_agent_card_endpoint_is_read_only_when_enabled(tmp_path: Path) -> None:
    client = TestClient(create_app(base_dir=tmp_path, a2a_bridge_enabled=True))
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "A2A read-only", "initial_participants": []},
    ).json()
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conversation["id"],
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    session_address, session_inbox_id = build_conversation_session_identity(
        conversation_id=conversation["id"],
        participant_id=participant.participant_id,
    )
    session = GodSessionRegistry(tmp_path / "god_sessions.json").create(
        role=participant.role,
        agent_name=participant.display_name,
        runtime=participant.cli_kind,
        session_address=session_address,
        session_inbox_id=session_inbox_id,
        conversation_id=conversation["id"],
        participant_id=participant.participant_id,
        model=participant.model,
        worktree=str(tmp_path),
    )
    before_messages = ChatStore(tmp_path / "chat.db").list_messages(conversation["id"])
    before_inbox = ChatInboxStore(tmp_path / "chat.db").list_by_conversation(
        conversation["id"],
        include_terminal=True,
    )

    response = client.get(f"/a2a/agents/{participant.participant_id}")

    assert response.status_code == 200
    card = response.json()
    assert card["metadata"]["participant_id"] == participant.participant_id
    assert card["metadata"]["natural_profile"]["provider_session_binding_ref"] == (
        f"god_session:{session.god_session_id}"
    )
    assert ChatStore(tmp_path / "chat.db").list_messages(conversation["id"]) == (
        before_messages
    )
    assert ChatInboxStore(tmp_path / "chat.db").list_by_conversation(
        conversation["id"],
        include_terminal=True,
    ) == before_inbox


def test_a2a_agent_card_endpoint_does_not_add_inbound_task_route(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(base_dir=tmp_path, a2a_bridge_enabled=True))

    response = client.post("/a2a/tasks/send", json={})

    assert response.status_code == 404
