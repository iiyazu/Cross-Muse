import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
from xmuse_core.namespaces import build_conversation_graph_set_id
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_plan_store import FeatureGraphSetStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureReviewVerdict,
)


def test_self_development_demo_contract_flow_reaches_feature_graph_merge(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path))
    conversation = _create_conversation(client)
    blueprint_ref = _create_approved_blueprint(client, conversation["id"])
    feature_plan_resolution = _create_approved_feature_plan(
        client,
        conversation_id=conversation["id"],
        blueprint_ref=blueprint_ref,
    )

    graph_set_id = _graph_set_id_from_resolution(feature_plan_resolution)
    graph_set = FeatureGraphSetStore(tmp_path / "lane_graphs").load(graph_set_id)
    feature = graph_set.feature_plan.features[0]
    graph = graph_set.graphs[0]
    lanes = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))[
        "lanes"
    ]
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    orch = PlatformOrchestrator(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    initialized = status_store.get(
        graph_set_id=graph_set_id,
        feature_graph_id=feature.graph_id,
    )
    assert initialized.status is FeatureGraphExecutionStatus.READY
    assert initialized.projection_lane_ids == [lanes[0]["feature_id"]]
    claim_updated_at = _plus_minutes(initialized.updated_at, 1)
    evidence_updated_at = _plus_minutes(initialized.updated_at, 2)
    review_updated_at = _plus_minutes(initialized.updated_at, 3)

    claim = orch.claim_next_ready_feature_graph_worker(
        graph_set_id=graph_set_id,
        worker_session_id="god-worker-self-dev-demo",
        provider_session_binding_ref="provider_session_binding:self-dev-demo:v1",
        updated_at=claim_updated_at,
    )

    assert claim is not None
    assert claim.status.status is FeatureGraphExecutionStatus.RUNNING
    assert claim.status.active_lane_ids == initialized.ready_lane_ids

    bundle = _feature_evidence_bundle(
        conversation_id=conversation["id"],
        planning_run_id=claim.status.planning_run_id,
        feature_plan_id=claim.status.feature_plan_id,
        feature_plan_version=claim.status.feature_plan_version,
        graph_set_id=graph_set_id,
        graph_set_version=claim.status.graph_set_version,
        feature_id=feature.feature_id,
        feature_graph_id=feature.graph_id,
        feature_goal=feature.goal,
        acceptance_criteria=feature.acceptance_criteria,
        blueprint_refs=feature.blueprint_refs,
        completed_lane_ids=[lane.feature_id for lane in graph.lanes],
        created_at=evidence_updated_at,
    )
    evidence_outcome = orch.submit_feature_graph_worker_evidence(
        evidence_bundle=bundle,
        evidence_bundle_ref=f"feature_evidence_bundle:{bundle.bundle_id}:v1",
        updated_at=evidence_updated_at,
    )

    assert evidence_outcome.status.status is FeatureGraphExecutionStatus.REVIEWING
    assert evidence_outcome.status.completed_lane_ids == [lane.feature_id for lane in graph.lanes]
    assert artifact_store.get_evidence_bundle(bundle.bundle_id) == bundle

    verdict = _merge_verdict(bundle, created_at=review_updated_at)
    review_outcome = orch.submit_feature_graph_review_verdict(
        evidence_bundle=bundle,
        verdict=verdict,
        updated_at=review_updated_at,
    )

    assert review_outcome.status is not None
    assert review_outcome.status.status is FeatureGraphExecutionStatus.MERGED
    assert artifact_store.get_review_verdict(verdict.verdict_id) == verdict
    assert status_store.get(
        graph_set_id=graph_set_id,
        feature_graph_id=feature.graph_id,
    ).status is FeatureGraphExecutionStatus.MERGED


def _create_conversation(client: TestClient) -> dict[str, object]:
    response = client.post(
        "/api/chat/conversations",
        json={"title": "xmuse self-development demo"},
    )
    assert response.status_code == 201
    return response.json()


def _create_approved_blueprint(client: TestClient, conversation_id: str) -> str:
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "mission_blueprint",
            "content": json.dumps(
                {
                    "type": "mission_blueprint",
                    "title": "Self-development demo",
                    "body": "Use xmuse to improve one xmuse workflow contract.",
                    "acceptance_criteria": [
                        "The approved plan creates graph-native execution status.",
                        "Worker evidence and review verdict are durable artifacts.",
                    ],
                }
            ),
            "references": [],
        },
    )
    assert proposal.status_code == 201
    approval = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve self-development demo blueprint",
        },
    )
    assert approval.status_code == 200
    return approval.json()["content"]["blueprint_ref"]


def _create_approved_feature_plan(
    client: TestClient,
    *,
    conversation_id: str,
    blueprint_ref: str,
) -> dict[str, object]:
    proposal = client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "architect-god",
            "proposal_type": "feature_plan",
            "content": json.dumps(
                {
                    "type": "feature_plan",
                    "source_blueprint_ref": blueprint_ref,
                    "features": [
                        {
                            "feature_id": "self-dev-demo-contract",
                            "title": "Self-development demo contract",
                            "goal": (
                                "Prove the approved plan can enter graph-native "
                                "worker and review coordination."
                            ),
                            "acceptance_criteria": [
                                "A ready graph-native status exists after approval.",
                                "Worker evidence transitions the feature graph to reviewing.",
                                "A merge verdict transitions the feature graph to merged.",
                            ],
                            "graph_id": "graph-self-dev-demo-contract",
                            "blueprint_refs": [blueprint_ref],
                        }
                    ],
                }
            ),
            "references": [blueprint_ref],
        },
    )
    assert proposal.status_code == 201
    approval = client.post(
        f"/api/chat/proposals/{proposal.json()['id']}/approve",
        json={
            "approved_by": ["human"],
            "approval_mode": "manual",
            "goal_summary": "Approve self-development demo feature plan",
        },
    )
    assert approval.status_code == 200
    return approval.json()


def _graph_set_id_from_resolution(resolution: dict[str, object]) -> str:
    return build_conversation_graph_set_id(
        conversation_id=str(resolution["conversation_id"]),
        feature_plan_id=str(resolution["content"]["proposal_id"]),
        version=int(resolution["version"]),
    )


def _plus_minutes(value: str, minutes: int) -> str:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _feature_evidence_bundle(
    *,
    conversation_id: str,
    planning_run_id: str,
    feature_plan_id: str,
    feature_plan_version: int,
    graph_set_id: str,
    graph_set_version: int,
    feature_id: str,
    feature_graph_id: str,
    feature_goal: str,
    acceptance_criteria: list[str],
    blueprint_refs: list[str],
    completed_lane_ids: list[str],
    created_at: str,
) -> FeatureEvidenceBundle:
    return FeatureEvidenceBundle.model_validate(
        {
            "bundle_id": "fevb-self-dev-demo",
            "conversation_id": conversation_id,
            "planning_run_id": planning_run_id,
            "feature_plan_id": feature_plan_id,
            "feature_plan_version": feature_plan_version,
            "graph_set_id": graph_set_id,
            "graph_set_version": graph_set_version,
            "feature_id": feature_id,
            "feature_graph_id": feature_graph_id,
            "worker_session_id": "god-worker-self-dev-demo",
            "provider_session_binding_ref": "provider_session_binding:self-dev-demo:v1",
            "blueprint_refs": blueprint_refs,
            "feature_goal": feature_goal,
            "acceptance_criteria": acceptance_criteria,
            "lane_graph_summary": {
                "feature_graph_id": feature_graph_id,
                "lane_count": len(completed_lane_ids),
                "ready_lane_ids": [],
                "completed_lane_ids": completed_lane_ids,
                "blocked_lane_ids": [],
            },
            "touched_files": ["docs/xmuse/self-development-demo-contract.md"],
            "base_head_sha": "local-contract-demo",
            "branch": "codex/self-development-demo-contract",
            "worktree": "/tmp/xmuse-self-development-demo",
            "diff_ref": "diff://self-development-demo",
            "patch_ref": "patch://self-development-demo",
            "changed_files": ["docs/xmuse/self-development-demo-contract.md"],
            "dependency_changes": [],
            "verification": {
                "commands_run": [
                    "uv run pytest tests/xmuse/test_self_development_demo_flow.py -q"
                ],
                "test_results": [
                    {
                        "command": (
                            "uv run pytest tests/xmuse/"
                            "test_self_development_demo_flow.py -q"
                        ),
                        "status": "passed",
                        "evidence_ref": "logs/self-development-demo-pytest.txt",
                    }
                ],
                "lint_results": [],
                "screenshots_or_logs": ["logs/self-development-demo-pytest.txt"],
                "known_failures": [],
            },
            "worker_notes": {
                "implementation_summary": (
                    "Contract demo evidence for xmuse self-development coordination."
                ),
                "decisions_made": [
                    "Use graph-native status as execution authority.",
                    "Persist worker evidence before review verdict submission.",
                ],
                "risks_or_open_questions": [
                    "This is contract evidence, not live provider proof."
                ],
                "skipped_items_with_reason": [
                    "No real provider invocation in this focused unit test."
                ],
            },
            "created_at": created_at,
        }
    )


def _merge_verdict(
    bundle: FeatureEvidenceBundle,
    *,
    created_at: str,
) -> FeatureReviewVerdict:
    return FeatureReviewVerdict.model_validate(
        {
            "verdict_id": "fverdict-self-dev-demo-merge",
            "evidence_bundle_id": bundle.bundle_id,
            "decision": "merge",
            "summary": "Contract evidence satisfies the self-development demo scope.",
            "blocking_findings": [],
            "non_blocking_findings": [
                "Live provider and GitHub review truth remain out of scope."
            ],
            "evidence_refs": [
                f"feature_evidence_bundle:{bundle.bundle_id}:v1",
                "logs/self-development-demo-pytest.txt",
            ],
            "acceptance_coverage": [
                {
                    "criterion": criterion,
                    "status": "covered",
                    "evidence_refs": [f"feature_evidence_bundle:{bundle.bundle_id}:v1"],
                }
                for criterion in bundle.acceptance_criteria
            ],
            "scope_assessment": {
                "diff_scope": "focused self-development contract demo",
                "touched_files": list(bundle.touched_files),
                "unexpected_files": [],
                "public_contract_changed": False,
                "new_dependency_added": False,
            },
            "required_gates_before_merge": [
                "uv run pytest tests/xmuse/test_self_development_demo_flow.py -q"
            ],
            "merge_gate_evidence": {
                "acceptance_coverage_ref": "artifact://self-dev-demo/acceptance",
                "diff_scope_ref": "artifact://self-dev-demo/scope",
                "verification_ref": "logs/self-development-demo-pytest.txt",
                "merge_guard_ref": "artifact://self-dev-demo/merge-guard",
            },
            "reviewer_session_id": "review-god-self-dev-demo",
            "created_at": created_at,
        }
    )
