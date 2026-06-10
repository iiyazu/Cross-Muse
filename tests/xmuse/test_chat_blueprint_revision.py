from __future__ import annotations

import json

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app


def test_feature_plan_change_of_how_stays_feature_plan_on_current_blueprint(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation_id = _create_conversation(client)
    blueprint_ref = _approve_blueprint(
        client,
        conversation_id=conversation_id,
        title="Current blueprint",
        body="Ship the current blueprint.",
        acceptance_criteria=["Keep the core mission stable."],
    )

    create_response = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "summary": "Refine implementation breakdown",
                    "source_blueprint_ref": blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-current",
                            "title": "Current feature",
                            "goal": "Refine how the work is split.",
                            "acceptance_criteria": ["Break work into stable feature slices."],
                            "graph_id": "graph-current",
                            "blueprint_refs": [blueprint_ref],
                        }
                    ],
                }
            ),
            "references": [blueprint_ref],
        },
    )

    assert create_response.status_code == 201
    proposal = create_response.json()
    assert proposal["proposal_type"] == "feature_plan"


def test_change_of_what_escalates_to_blueprint_revision(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation_id = _create_conversation(client)
    blueprint_ref = _approve_blueprint(
        client,
        conversation_id=conversation_id,
        title="Baseline blueprint",
        body="Ship baseline mission.",
        acceptance_criteria=["Preserve baseline acceptance."],
    )

    create_response = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "source_blueprint_ref": blueprint_ref,
                    "title": "Revised mission",
                    "body": "Change what the system should deliver.",
                    "acceptance_criteria": ["Add a new acceptance boundary."],
                }
            ),
            "references": [blueprint_ref],
        },
    )

    assert create_response.status_code == 201
    proposal = create_response.json()
    payload = json.loads(proposal["content"])

    assert proposal["proposal_type"] == "mission_blueprint"
    assert payload["resolution_content"]["revision_of"] == blueprint_ref


def test_old_feature_plan_proposal_cannot_continue_after_new_blueprint_revision(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation_id = _create_conversation(client)
    original_blueprint_ref = _approve_blueprint(
        client,
        conversation_id=conversation_id,
        title="Original blueprint",
        body="Ship the original scope.",
        acceptance_criteria=["Original scope is stable."],
    )

    stale_feature_plan = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "summary": "Old blueprint plan",
                    "source_blueprint_ref": original_blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-stale",
                            "title": "Stale feature",
                            "goal": "Plan against the original blueprint.",
                            "acceptance_criteria": ["Will become stale after revision."],
                            "graph_id": "graph-stale",
                            "blueprint_refs": [original_blueprint_ref],
                        }
                    ],
                }
            ),
            "references": [original_blueprint_ref],
        },
    )
    assert stale_feature_plan.status_code == 201
    stale_proposal_id = stale_feature_plan.json()["id"]

    revised_blueprint_ref = _approve_blueprint(
        client,
        conversation_id=conversation_id,
        title="Revised blueprint",
        body="Change the mission scope.",
        acceptance_criteria=["The revised mission is now authoritative."],
        revision_of=original_blueprint_ref,
    )
    assert revised_blueprint_ref != original_blueprint_ref

    approve_response = client.post(
        f"/api/chat/proposals/{stale_proposal_id}/approve",
        json={
            "approved_by": ["human-1"],
            "approval_mode": "manual",
            "goal_summary": "Try to approve stale feature plan",
        },
    )

    assert approve_response.status_code == 400
    assert approve_response.json()["detail"]["code"] == "stale_feature_plan_blueprint"


def test_new_feature_plan_must_reference_latest_approved_blueprint_revision(tmp_path) -> None:
    client = TestClient(create_app(tmp_path))
    conversation_id = _create_conversation(client)
    original_blueprint_ref = _approve_blueprint(
        client,
        conversation_id=conversation_id,
        title="Original blueprint",
        body="Ship original mission.",
        acceptance_criteria=["Original mission accepted."],
    )
    revised_blueprint_ref = _approve_blueprint(
        client,
        conversation_id=conversation_id,
        title="Latest blueprint",
        body="Ship revised mission.",
        acceptance_criteria=["Revised mission accepted."],
        revision_of=original_blueprint_ref,
    )

    stale_create = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "summary": "Still using old blueprint",
                    "source_blueprint_ref": original_blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-old-ref",
                            "title": "Old ref feature",
                            "goal": "Should be rejected for stale blueprint ref.",
                            "acceptance_criteria": ["Reject stale source blueprint."],
                            "graph_id": "graph-old-ref",
                            "blueprint_refs": [original_blueprint_ref],
                        }
                    ],
                }
            ),
            "references": [original_blueprint_ref],
        },
    )

    assert stale_create.status_code == 400
    assert stale_create.json()["detail"]["code"] == "stale_feature_plan_blueprint"

    current_create = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "summary": "Using latest blueprint",
                    "source_blueprint_ref": revised_blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-new-ref",
                            "title": "Current ref feature",
                            "goal": "Should be accepted on latest blueprint ref.",
                            "acceptance_criteria": ["Use latest source blueprint."],
                            "graph_id": "graph-new-ref",
                            "blueprint_refs": [revised_blueprint_ref, original_blueprint_ref],
                        }
                    ],
                }
            ),
            "references": [revised_blueprint_ref],
        },
    )

    assert current_create.status_code == 201
    assert current_create.json()["proposal_type"] == "feature_plan"


def _create_conversation(client: TestClient) -> str:
    response = client.post("/api/chat/conversations", json={"title": "Blueprint Revision"})
    assert response.status_code == 201
    return response.json()["id"]


def _approve_blueprint(
    client: TestClient,
    *,
    conversation_id: str,
    title: str,
    body: str,
    acceptance_criteria: list[str],
    revision_of: str | None = None,
) -> str:
    content = {
        "title": title,
        "body": body,
        "acceptance_criteria": acceptance_criteria,
    }
    if revision_of is not None:
        content["revision_of"] = revision_of
        content["source_blueprint_ref"] = revision_of
    create_response = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(content),
            "references": [revision_of] if revision_of is not None else [],
        },
    )
    assert create_response.status_code == 201
    proposal_id = create_response.json()["id"]
    approve_response = client.post(
        f"/api/chat/proposals/{proposal_id}/approve",
        json={
            "approved_by": ["human-1"],
            "approval_mode": "manual",
            "goal_summary": title,
        },
    )
    assert approve_response.status_code == 200
    return approve_response.json()["content"]["blueprint_ref"]
