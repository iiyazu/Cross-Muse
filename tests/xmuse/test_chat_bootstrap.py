from __future__ import annotations

import json

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.agents.god_session_layer import build_conversation_session_identity
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore, RoleTemplateStore
from xmuse_core.chat.peer_service import PeerChatService


def test_create_conversation_bootstraps_init_session_and_artifact(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")

    payload = service.create_conversation(
        title="Bootstrap Demo",
        init_mode="deterministic",
    )

    bootstrap = payload["bootstrap"]
    artifact_path = tmp_path / bootstrap["artifact"]["path"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))

    assert payload["conversation"]["title"] == "Bootstrap Demo"
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert bootstrap["status"] == "bootstrapped"
    assert len(bootstrap["fork_plan"]) == 3
    assert bootstrap["init_session"]["role"] == "init"
    assert artifact["conversation_id"] == payload["conversation"]["id"]
    assert artifact["participant_plan"] == ["architect", "review", "execute"]
    assert len(artifact["fork_plan"]) == 3

    listed = service.list_participants(
        conversation_id=payload["conversation"]["id"],
        registry_path=tmp_path / "god_sessions.json",
    )
    sessions = {
        participant["role"]: participant["session"]
        for participant in listed["participants"]
    }

    assert "init" in sessions
    assert sessions["init"] is not None
    assert sessions["init"]["role"] == "init"


def test_bootstrap_rerun_is_idempotent_after_partial_state(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    conversation = service._chat.create_conversation("Rerun Demo")
    role_templates = RoleTemplateStore(tmp_path / "chat.db")
    participants = ParticipantStore(tmp_path / "chat.db")

    architect = role_templates.get_by_slug("architect")
    assert architect is not None
    participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="architect-god",
        cli_kind=architect.cli_kind,
        model=architect.default_model,
        role_template_id=architect.id,
    )
    init_participant = participants.ensure_init_god(
        conversation_id=conversation.id,
        model=architect.default_model,
    )

    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session_address, session_inbox_id = build_conversation_session_identity(
        conversation_id=conversation.id,
        participant_id=init_participant.participant_id,
    )
    registry.create(
        role="init",
        agent_name=init_participant.display_name,
        runtime="codex",
        session_address=session_address,
        session_inbox_id=session_inbox_id,
        conversation_id=conversation.id,
        participant_id=init_participant.participant_id,
        model=init_participant.model,
    )

    first = service.bootstrap_conversation(
        conversation_id=conversation.id,
        init_mode="deterministic",
    )
    second = service.bootstrap_conversation(
        conversation_id=conversation.id,
        init_mode="deterministic",
    )
    listed = service.list_participants(
        conversation_id=conversation.id,
        registry_path=tmp_path / "god_sessions.json",
    )

    assert first["artifact"]["artifact_id"] == second["artifact"]["artifact_id"]
    assert [participant["role"] for participant in second["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert [participant["role"] for participant in listed["participants"]] == [
        "architect",
        "init",
        "review",
        "execute",
    ]
    assert len(listed["lineage"]) == 3
    assert len(registry.list()) == 4


def test_chat_api_create_conversation_returns_bootstrap_payload(tmp_path) -> None:
    app = create_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/chat/conversations",
        json={"title": "API Bootstrap", "init_mode": "deterministic"},
    )

    assert response.status_code == 201
    payload = response.json()

    assert payload["title"] == "API Bootstrap"
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert payload["bootstrap"]["status"] == "bootstrapped"
    assert payload["bootstrap"]["artifact"]["artifact_id"].startswith("bootstrap:")
