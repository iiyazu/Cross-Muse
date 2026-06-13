from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse import chat_api
from xmuse_core.chat import api_models


def test_chat_api_models_module_owns_conversation_request_contract() -> None:
    request = api_models.ConversationCreate(title="  Mission chat  ")

    assert request.title == "Mission chat"


def test_chat_api_models_module_rejects_blank_fork_required_text() -> None:
    with pytest.raises(ValidationError):
        api_models.PeerForkCreate(
            source_peer_id="peer-1",
            role="review",
            prompt_delta="   ",
            inherited_refs=[],
            model_policy={"model_policy_runtime": "codex"},
            fork_reason="split review context",
        )


def test_chat_api_models_reject_unsafe_god_room_artifact_ids() -> None:
    with pytest.raises(ValidationError):
        api_models.GodRoomLaneRecoveryRequest(
            graph_id="../escaped",
            lane_id="lane-runtime-api",
        )
    with pytest.raises(ValidationError):
        api_models.GodRoomLaneDagRequest(
            resolution_id="resolution-1",
            graph_id="graph/escaped",
            features=[
                {
                    "feature_id": "feature-runtime",
                    "title": "Runtime recovery",
                    "goal": "Evaluate recovery from lane runtime budgets.",
                    "acceptance_criteria": ["Recovery artifacts are persisted."],
                    "blueprint_refs": ["blueprint:bp-god-room:1"],
                }
            ],
            lanes=[
                {
                    "lane_id": "lane-runtime-api",
                    "feature_id": "feature-runtime",
                    "title": "Expose lane recovery runtime API",
                    "prompt": "Build the lane recovery runtime action.",
                    "acceptance_criteria": ["Focused tests cover recovery decisions."],
                    "blueprint_refs": ["blueprint:bp-god-room:1"],
                }
            ],
        )


def test_chat_api_preserves_api_model_compat_exports() -> None:
    assert chat_api.ParticipantInit is api_models.ParticipantInit
    assert chat_api.ConversationCreate is api_models.ConversationCreate
    assert chat_api.RoleTemplateCreate is api_models.RoleTemplateCreate
    assert chat_api.RoleTemplateUpdate is api_models.RoleTemplateUpdate
    assert chat_api.MessageCreate is api_models.MessageCreate
    assert chat_api.ProposalCreate is api_models.ProposalCreate
    assert chat_api.ProposalApproval is api_models.ProposalApproval
    assert chat_api.ThreadMessageCreate is api_models.ThreadMessageCreate
    assert chat_api.PeerForkCreate is api_models.PeerForkCreate
    assert chat_api.GodRoomLaneDagRequest is api_models.GodRoomLaneDagRequest
    assert chat_api.GodRoomLaneRecoveryRequest is api_models.GodRoomLaneRecoveryRequest
