from __future__ import annotations

import json

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.chat.models import StructuredEscalationTarget
from xmuse_core.chat.peer_proposals import classify_structured_proposal


def test_generic_lane_payload_escalates_to_lane_graph_and_stays_recognizable(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation_id = client.post(
        "/api/chat/conversations",
        json={"title": "Lane Graph Escalation"},
    ).json()["id"]

    create_response = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "summary": "Add worker handoff lanes",
                    "lanes": [
                        {
                            "feature_id": "feature-handoff",
                            "prompt": "Implement worker handoff.",
                            "depends_on": [],
                            "capabilities": ["code"],
                        }
                    ],
                }
            ),
            "references": [],
        },
    )

    assert create_response.status_code == 201
    proposal = create_response.json()
    assert proposal["proposal_type"] == "lane_graph"

    approve_response = client.post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human-1"],
            "approval_mode": "manual",
            "goal_summary": "Ship the lane graph",
        },
    )

    assert approve_response.status_code == 200
    assert approve_response.json()["content"]["type"] == "lane_graph"


def test_feature_plan_payload_escalates_and_cannot_bypass_blueprint_gate(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation_id = client.post(
        "/api/chat/conversations",
        json={"title": "Feature Plan Escalation"},
    ).json()["id"]

    create_response = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "summary": "Feature plan from blueprint",
                    "source_blueprint_ref": "resolution:missing:mission_blueprint",
                    "features": [
                        {
                            "feature_id": "feature-esc",
                            "title": "Escalation feature",
                            "summary": "Keep feature plan behind blueprint.",
                        }
                    ],
                }
            ),
            "references": ["resolution:missing:mission_blueprint"],
        },
    )

    assert create_response.status_code == 400
    assert create_response.json()["detail"]["code"] == "stale_feature_plan_blueprint"


def test_generic_blueprint_payload_escalates_to_mission_blueprint(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation_id = client.post(
        "/api/chat/conversations",
        json={"title": "Blueprint Escalation"},
    ).json()["id"]

    create_response = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "title": "Blueprint the review gate",
                    "body": "Make review trigger happen only after structured escalation.",
                    "acceptance_criteria": ["Review enters only after a reviewable object exists."],
                }
            ),
            "references": [],
        },
    )

    assert create_response.status_code == 201
    proposal = create_response.json()
    assert proposal["proposal_type"] == "mission_blueprint"

    approve_response = client.post(
        f"/api/chat/proposals/{proposal['id']}/approve",
        json={
            "approved_by": ["human-1"],
            "approval_mode": "manual",
            "goal_summary": "Approve blueprint",
        },
    )

    assert approve_response.status_code == 200
    assert approve_response.json()["content"]["type"] == "mission_blueprint"


def test_verdict_payload_classification_is_stable_and_explainable() -> None:
    decision = classify_structured_proposal(
        proposal_type="proposal",
        content=json.dumps({"decision": "approve", "rationale": "Scope is correct."}),
        references=[],
    )

    assert decision.target == StructuredEscalationTarget.VERDICT
    assert decision.normalized_proposal_type == "verdict"
    assert "verdict" in decision.rationale
