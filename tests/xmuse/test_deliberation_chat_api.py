import json
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.store import ChatStore


def test_append_deliberation_persists_versioned_envelope(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = client.post("/api/chat/conversations", json={"title": "Deliberate"}).json()

    response = client.post(
        f"/api/chat/conversations/{conversation['id']}/deliberations",
        json=_deliberation(
            conversation["id"],
            msg_id="msg-proposal",
            kind="proposal",
            payload={"summary": "Freeze the mission blueprint."},
        ),
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["deliberation"]["version"] == "deliberation_message.v1"
    assert payload["deliberation"]["conversation_id"] == conversation["id"]
    assert payload["idempotency_key"].startswith("deliberation:")

    messages = ChatStore(tmp_path / "chat.db").list_messages(conversation["id"])
    stored = messages[-1]
    assert stored.envelope_type == "deliberation"
    assert stored.envelope_json["message"]["msg_id"] == "msg-proposal"
    assert stored.envelope_json["idempotency_key"] == payload["idempotency_key"]


def test_freeze_blueprint_emits_resolution_card_and_read_evidence(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = client.post("/api/chat/conversations", json={"title": "Freeze"}).json()
    conv_id = conversation["id"]
    target_ref = "blueprint:bp-1:1"

    for event in [
        _deliberation(
            conv_id,
            msg_id="msg-proposal",
            kind="proposal",
            target_ref=target_ref,
            payload={"summary": "Freeze the mission blueprint."},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-objection",
            kind="challenge",
            target_ref=target_ref,
            parent_id="msg-proposal",
            objection_level="non_blocking",
            payload={"question": "Should the API stay REST-first?"},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-commit",
            kind="commit",
            target_ref=target_ref,
            agent_id="god-review",
            payload={"commitment": "ready_to_freeze"},
        ),
    ]:
        response = client.post(f"/api/chat/conversations/{conv_id}/deliberations", json=event)
        assert response.status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/freeze-blueprint",
        json={
            "target_ref": target_ref,
            "blueprint": {
                "blueprint_id": "bp-1",
                "revision": 1,
                "goal": "Ship REST-first deliberation freeze.",
                "scope": ["Append deliberation events", "Freeze a blueprint"],
                "constraints": ["Keep execution centralized"],
                "non_goals": ["No physical distributed transport"],
                "acceptance_contracts": ["Frozen blueprint appears as a durable card"],
                "repo_areas": ["xmuse/chat_api.py", "src/xmuse_core/chat/"],
                "source_refs": ["memory://conversation/conv-1/message/msg-proposal"],
            },
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["decision"]["status"] == "allowed"
    assert payload["blueprint"]["status"] == "frozen"
    assert payload["blueprint"]["approved_by"] == ["god-review"]
    assert payload["blueprint"]["open_questions"] == ["Should the API stay REST-first?"]

    resolution = payload["resolution"]
    stored = ChatStore(tmp_path / "chat.db").get_resolution(resolution["id"])
    assert stored.approval_mode == "deliberation_freeze"
    assert stored.content["blueprint_v1"]["blueprint_id"] == "bp-1"
    assert "## Open Questions" in stored.content["markdown"]

    timeline = client.get(f"/api/chat/conversations/{conv_id}/messages").json()
    card = next(card for card in timeline["cards"] if card["card_type"] == "mission_blueprint")
    assert card["source_id"] == resolution["id"]
    assert card["counts"] == {"acceptance_criteria": 1, "references": 4}

    read_model = json.loads((tmp_path / "read_models" / "resolutions.json").read_text())
    assert read_model["resolutions"][-1]["resolution_id"] == resolution["id"]


def test_freeze_blueprint_conflicts_when_blocking_challenge_is_unresolved(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = client.post("/api/chat/conversations", json={"title": "Blocked"}).json()
    conv_id = conversation["id"]
    target_ref = "blueprint:bp-2:1"

    for event in [
        _deliberation(
            conv_id,
            msg_id="msg-proposal",
            kind="proposal",
            target_ref=target_ref,
            payload={"summary": "Freeze the blocked blueprint."},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-challenge",
            kind="challenge",
            target_ref=target_ref,
            parent_id="msg-proposal",
            objection_level="blocking",
            payload={"question": "Where is the evidence?"},
        ),
        _deliberation(
            conv_id,
            msg_id="msg-commit",
            kind="commit",
            target_ref=target_ref,
            agent_id="god-review",
            payload={"commitment": "ready_to_freeze"},
        ),
    ]:
        response = client.post(f"/api/chat/conversations/{conv_id}/deliberations", json=event)
        assert response.status_code == 201

    response = client.post(
        f"/api/chat/conversations/{conv_id}/freeze-blueprint",
        json={
            "target_ref": target_ref,
            "blueprint": {
                "blueprint_id": "bp-2",
                "revision": 1,
                "goal": "This should stay blocked.",
                "scope": ["Show conflict response"],
                "acceptance_contracts": ["No card is emitted while blocked"],
                "source_refs": ["memory://conversation/conv-1/message/msg-proposal"],
            },
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["decision"]["reason"] == "unresolved blocking challenges"
    timeline = client.get(f"/api/chat/conversations/{conv_id}/messages").json()
    assert not any(card["card_type"] == "mission_blueprint" for card in timeline["cards"])


def _deliberation(
    conversation_id: str,
    *,
    msg_id: str,
    kind: str,
    payload: dict[str, object],
    target_ref: str = "blueprint:bp-1:1",
    parent_id: str | None = None,
    objection_level: str = "none",
    agent_id: str = "god-architect",
) -> dict[str, object]:
    return {
        "msg_id": msg_id,
        "agent_id": agent_id,
        "lamport_ts": int(msg_id.rsplit("-", maxsplit=1)[-1], 36)
        if msg_id.rsplit("-", maxsplit=1)[-1].isalnum()
        else 1,
        "kind": kind,
        "parent_id": parent_id,
        "target_ref": target_ref,
        "mentions": [],
        "payload": payload,
        "source_refs": [f"message:{msg_id}"],
        "objection_level": objection_level,
        "decision_scope": "blueprint.freeze",
    }
