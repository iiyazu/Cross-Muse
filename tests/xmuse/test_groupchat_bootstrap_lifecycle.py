from __future__ import annotations

import json

import pytest

from xmuse_core.chat.bootstrap_store import BootstrapStateStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.peer_types import PeerChatError


def test_create_conversation_proposal_mode_prepares_visible_init_guidance(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")

    payload = service.create_conversation(
        title="Bootstrap UX",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )

    assert payload["bootstrap"]["status"] == "proposal_ready"
    assert payload["bootstrap"]["proposal_id"].startswith("bootstrap-proposal:")
    assert payload["bootstrap"]["init_session"]["role"] == "init"
    assert payload["participants"] == []
    messages = service._chat.list_messages(payload["conversation"]["id"])
    assert len(messages) == 1
    assert messages[0].author == payload["bootstrap"]["init_participant"]["participant_id"]
    assert messages[0].role == "assistant"
    assert messages[0].envelope_type == "bootstrap_guidance"
    assert payload["bootstrap"]["proposal_id"] not in messages[0].content
    assert "/init apply" not in messages[0].content
    assert "选择" in messages[0].content
    assert "architect" in messages[0].content
    assert "review" in messages[0].content
    assert "execute" in messages[0].content
    actions = messages[0].envelope_json["actions"]
    assert [action["id"] for action in actions] == ["apply", "retry", "status"]
    assert actions[0]["command"] == f"/init apply {payload['bootstrap']['proposal_id']}"


def test_deterministic_bootstrap_applies_default_team(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")

    payload = service.create_conversation(
        title="Deterministic Bootstrap",
        preset_id="architect-review-execute",
        init_mode="deterministic",
    )

    assert payload["bootstrap"]["status"] == "bootstrapped"
    assert [participant["role"] for participant in payload["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    assert payload["bootstrap"]["fork_plan"] != []


def test_apply_bootstrap_is_duplicate_safe(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    payload = service.create_conversation(
        title="Apply Once",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )
    conv_id = payload["conversation"]["id"]

    proposal = service.create_bootstrap_proposal(
        conversation_id=conv_id,
        source="deterministic",
    )
    first = service.apply_bootstrap_proposal(
        conversation_id=conv_id,
        proposal_id=proposal["proposal"]["proposal_id"],
    )
    second = service.apply_bootstrap_proposal(
        conversation_id=conv_id,
        proposal_id=proposal["proposal"]["proposal_id"],
    )

    assert first["bootstrap"]["apply_id"] == second["bootstrap"]["apply_id"]
    assert first["bootstrap"]["fork_plan"] == second["bootstrap"]["fork_plan"]
    lineage = service.list_fork_lineage(
        conversation_id=conv_id,
        registry_path=tmp_path / "god_sessions.json",
    )
    assert len(lineage["lineage"]) == 3


def test_bootstrap_durable_status_advances_through_proposal_and_apply(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    payload = service.create_conversation(
        title="Status Lifecycle",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )
    conv_id = payload["conversation"]["id"]

    initial_status = service.get_bootstrap_status(conv_id)
    assert initial_status["status"] == "proposal_ready"
    assert initial_status["proposal_id"].startswith("bootstrap-proposal:")

    proposal = service.create_bootstrap_proposal(
        conversation_id=conv_id,
        source="deterministic",
    )

    proposal_status = service.get_bootstrap_status(conv_id)
    assert proposal_status["status"] == "proposal_ready"
    assert proposal_status["proposal_id"] == proposal["proposal"]["proposal_id"]

    service.apply_bootstrap_proposal(
        conversation_id=conv_id,
        proposal_id=proposal["proposal"]["proposal_id"],
    )

    applied_status = service.get_bootstrap_status(conv_id)
    assert applied_status["status"] == "bootstrapped"
    assert applied_status["proposal_id"] == proposal["proposal"]["proposal_id"]


def test_bootstrap_status_does_not_regress_when_retry_runs_after_apply(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    payload = service.create_conversation(
        title="Retry After Apply",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )
    conv_id = payload["conversation"]["id"]
    proposal = service.create_bootstrap_proposal(
        conversation_id=conv_id,
        source="deterministic",
    )
    service.apply_bootstrap_proposal(
        conversation_id=conv_id,
        proposal_id=proposal["proposal"]["proposal_id"],
    )

    service.create_bootstrap_proposal(conversation_id=conv_id, source="deterministic")

    draft = BootstrapStateStore(tmp_path / "chat.db").get_latest_draft_for_conversation(conv_id)
    assert draft is not None
    assert draft.status == "bootstrapped"
    assert service.get_bootstrap_status(conv_id)["status"] == "bootstrapped"


def test_applied_bootstrap_artifact_embeds_bootstrapped_draft(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    payload = service.create_conversation(
        title="Applied Artifact",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )
    conv_id = payload["conversation"]["id"]
    proposal = service.create_bootstrap_proposal(
        conversation_id=conv_id,
        source="deterministic",
    )

    applied = service.apply_bootstrap_proposal(
        conversation_id=conv_id,
        proposal_id=proposal["proposal"]["proposal_id"],
    )

    artifact_path = tmp_path / applied["bootstrap"]["artifact"]["path"]
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["status"] == "bootstrapped"
    assert artifact["draft"]["status"] == "bootstrapped"


def test_init_god_proposal_source_is_rejected_until_live_path_exists(tmp_path) -> None:
    service = PeerChatService(tmp_path / "chat.db")
    payload = service.create_conversation(
        title="No fake init source",
        preset_id="architect-review-execute",
        init_mode="proposal_then_approve",
    )

    with pytest.raises(PeerChatError, match="bootstrap_init_god_proposal_not_implemented"):
        service.create_bootstrap_proposal(
            conversation_id=payload["conversation"]["id"],
            source="init_god",
        )
