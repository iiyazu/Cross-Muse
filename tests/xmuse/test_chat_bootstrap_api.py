from __future__ import annotations

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.store import ChatStore


def test_api_create_conversation_proposal_mode_prepares_user_choice(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "API proposal",
            "preset_id": "architect-review-execute",
            "init_mode": "proposal_then_approve",
        },
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["bootstrap"]["status"] == "proposal_ready"
    assert payload["bootstrap"]["proposal_id"].startswith("bootstrap-proposal:")
    assert payload["participants"] == []


def test_api_proposal_then_apply_materializes_team(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={"title": "API apply", "init_mode": "proposal_then_approve"},
    ).json()
    conv_id = created["id"]

    proposal_response = client.post(
        f"/api/chat/conversations/{conv_id}/bootstrap/proposals",
        json={"source": "deterministic"},
    )
    assert proposal_response.status_code == 201
    proposal = proposal_response.json()["proposal"]

    apply_response = client.post(
        f"/api/chat/conversations/{conv_id}/bootstrap/apply",
        json={"proposal_id": proposal["proposal_id"]},
    )

    assert apply_response.status_code == 200
    payload = apply_response.json()
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert payload["bootstrap"]["fork_plan"] != []


def test_api_bootstrap_status_tracks_draft_proposal_and_apply(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={"title": "API status", "init_mode": "proposal_then_approve"},
    ).json()
    conv_id = created["id"]

    draft_status = client.get(
        f"/api/chat/conversations/{conv_id}/bootstrap/status",
    )

    assert draft_status.status_code == 200
    assert draft_status.json()["status"] == "proposal_ready"
    assert draft_status.json()["conversation_id"] == conv_id
    assert draft_status.json()["proposal_id"].startswith("bootstrap-proposal:")

    proposal_response = client.post(
        f"/api/chat/conversations/{conv_id}/bootstrap/proposals",
        json={"source": "deterministic"},
    )
    proposal = proposal_response.json()["proposal"]
    proposal_status = client.get(
        f"/api/chat/conversations/{conv_id}/bootstrap/status",
    )

    assert proposal_status.status_code == 200
    assert proposal_status.json()["status"] == "proposal_ready"
    assert proposal_status.json()["proposal_id"] == proposal["proposal_id"]

    client.post(
        f"/api/chat/conversations/{conv_id}/bootstrap/apply",
        json={"proposal_id": proposal["proposal_id"]},
    )
    applied_status = client.get(
        f"/api/chat/conversations/{conv_id}/bootstrap/status",
    )

    assert applied_status.status_code == 200
    assert applied_status.json()["status"] == "bootstrapped"
    assert applied_status.json()["proposal_id"] == proposal["proposal_id"]


def test_api_create_without_init_mode_keeps_deterministic_compatibility(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post("/api/chat/conversations", json={"title": "API compat"})

    assert response.status_code == 201
    payload = response.json()
    assert payload["bootstrap"]["status"] == "bootstrapped"
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]


def test_api_opencode_override_requires_explicit_model(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "bad opencode",
            "provider_overrides": {
                "execute": {
                    "provider_id": "opencode",
                    "profile_id": "worker",
                    "cli_kind": "opencode",
                    "model": "",
                }
            },
        },
    )

    assert response.status_code == 422


def test_api_initial_participant_profile_mismatch_returns_role_mapping(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "bad review profile",
            "initial_participants": [
                {
                    "role": "review",
                    "display_name": "Review GOD",
                    "provider_id": "opencode",
                    "profile_id": "default",
                    "cli_kind": "opencode",
                    "model": "deepseek-v4-flash",
                }
            ],
            "init_mode": "proposal_then_approve",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == {
        "code": "participant_profile_role_mismatch",
        "message": "role 'review' must use profile_id 'review', got 'default'",
        "role": "review",
        "expected_profile_id": "review",
        "provided_profile_id": "default",
        "role_profile_map": {"review": "review"},
    }
    assert ChatStore(tmp_path / "chat.db").list_conversations() == []


def test_api_invalid_initial_participants_returns_400_without_residual_conversation(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "bad participants",
            "initial_participants": [{"role": "custom"}],
            "init_mode": "proposal_then_approve",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "role_template_id_required"
    assert ChatStore(tmp_path / "chat.db").list_conversations() == []


def test_api_unknown_bootstrap_preset_returns_400_without_residual_conversation(
    tmp_path,
) -> None:
    client = TestClient(create_app(tmp_path), raise_server_exceptions=False)

    response = client.post(
        "/api/chat/conversations",
        json={
            "title": "bad preset",
            "preset_id": "not-a-preset",
            "init_mode": "proposal_then_approve",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "invalid_bootstrap_preset"
    assert ChatStore(tmp_path / "chat.db").list_conversations() == []


def test_api_rejects_init_god_proposal_source_until_live_path_exists(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    created = client.post(
        "/api/chat/conversations",
        json={"title": "No fake init source", "init_mode": "proposal_then_approve"},
    ).json()

    response = client.post(
        f"/api/chat/conversations/{created['id']}/bootstrap/proposals",
        json={"source": "init_god"},
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "bootstrap_init_god_proposal_not_implemented"
