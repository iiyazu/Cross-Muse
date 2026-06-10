from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.protocol_v2 import GodSpeechAct
from xmuse_core.integrations.memoryos_client import FakeMemoryOSClient
from xmuse_core.integrations.memoryos_namespace import task_namespace
from xmuse_core.platform.execution.subagent_runtime import SubagentRuntimeContract
from xmuse_core.self_iteration.runtime_closure import (
    ProofLevel,
    build_self_iteration_closure_artifacts,
    build_self_iteration_lane_dag_request,
    build_self_iteration_replay_fixture,
    derive_frozen_self_iteration_blueprint,
    export_god_deliberation_replay,
    read_github_truth_evidence,
    review_self_iteration_evidence,
    write_self_iteration_memory_evidence,
)
from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    BlueprintLaneDagService,
    LaneDependencyType,
    LaneExecutionStatus,
)
from xmuse_core.structuring.mission_blueprint_v1 import MissionBlueprintStatus

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_replay_fixture_freezes_blueprint_and_blocks_unresolved_objection() -> None:
    replay = build_self_iteration_replay_fixture()
    blueprint = derive_frozen_self_iteration_blueprint(replay)

    assert {message.speech_act for message in replay} >= {
        GodSpeechAct.PROPOSE,
        GodSpeechAct.ASK,
        GodSpeechAct.CHALLENGE,
        GodSpeechAct.OBJECT,
        GodSpeechAct.VOTE,
        GodSpeechAct.DECIDE,
        GodSpeechAct.EVIDENCE,
        GodSpeechAct.HANDOFF,
    }
    assert blueprint.status is MissionBlueprintStatus.FROZEN
    assert blueprint.blueprint_id == "bp-self-iteration-runtime-closure"
    assert "Fake proof is not described as live runtime proof." in blueprint.constraints

    without_resolution = [
        message
        for message in replay
        if message.message_id != "gsa-006-evidence-proof-boundary"
    ]
    with pytest.raises(ValueError, match="unanswered replies|unresolved blockers"):
        derive_frozen_self_iteration_blueprint(without_resolution)


def test_exported_deliberation_replay_keeps_contract_fixture_separate_from_natural_proof() -> None:
    replay = build_self_iteration_replay_fixture()

    exported = export_god_deliberation_replay(
        replay,
        export_id="export-contract-1",
        transcript_source="deterministic-fixture",
        proof_level=ProofLevel.CONTRACT,
        natural_deliberation=False,
    )

    assert exported.proof_level is ProofLevel.CONTRACT
    assert exported.natural_deliberation is False
    assert exported.blueprint.status is MissionBlueprintStatus.FROZEN
    assert GodSpeechAct.CHALLENGE.value in exported.speech_acts
    with pytest.raises(ValueError, match="contract exports must not claim live/real"):
        export_god_deliberation_replay(
            replay,
            export_id="invalid-export",
            transcript_source="deterministic-fixture",
            proof_level=ProofLevel.REAL_PROVIDER,
            natural_deliberation=False,
        )
    with pytest.raises(ValueError, match="natural deliberation evidence requires"):
        export_god_deliberation_replay(
            replay,
            export_id="invalid-natural-export",
            transcript_source="runtime-transcript",
            proof_level=ProofLevel.CONTRACT,
            natural_deliberation=True,
        )


def test_blueprint_builds_authoritative_typed_lanedag_and_dispatch() -> None:
    blueprint = derive_frozen_self_iteration_blueprint(build_self_iteration_replay_fixture())
    request = build_self_iteration_lane_dag_request(blueprint)
    service = BlueprintLaneDagService()
    plan = service.build_plan(request)
    decisions = service.evaluate_dispatch(
        plan,
        lane_statuses={
            "lane-github-truth": LaneExecutionStatus.APPROVED,
            "lane-replay-lanedag": LaneExecutionStatus.APPROVED,
        },
    )

    assert {edge.edge_type for edge in plan.dependency_edges} == {
        LaneDependencyType.HARD_DEP,
        LaneDependencyType.SOFT_DEP,
        LaneDependencyType.REVIEW_DEP,
        LaneDependencyType.ARTIFACT_DEP,
    }
    assert plan.blueprint_ref == "blueprint:bp-self-iteration-runtime-closure:1"
    assert "feature-runtime-evidence" in plan.feature_ids
    assert not any(ref.endswith("feature_lanes.json") for ref in plan.memory_refs)
    assert {decision.lane_id: decision.ready for decision in decisions}[
        "lane-runtime-evidence"
    ] is True


def test_runtime_contract_serializes_required_self_iteration_fields(tmp_path: Path) -> None:
    artifacts = build_self_iteration_closure_artifacts(
        repo_root=PROJECT_ROOT,
        worktree_path=tmp_path,
    )
    contract = artifacts.runtime_contract
    round_trip = SubagentRuntimeContract.model_validate_json(
        json.dumps(contract.model_dump(mode="json"))
    )

    assert round_trip.blueprint_id == "bp-self-iteration-runtime-closure"
    assert round_trip.feature_id == "feature-runtime-evidence"
    assert round_trip.depends_on == ["lane-replay-lanedag"]
    assert round_trip.allowed_files
    assert round_trip.required_checks == [
        "quality-gates",
        "contract-smoke-gates",
        "real-runtime-integration-gate",
    ]
    assert round_trip.memory_context_ref is not None
    assert round_trip.review_profile == "self-iteration-contract"
    assert artifacts.evidence_bundle.proof_level is ProofLevel.FAKE_RUNTIME
    assert "docs/xmuse/self-iteration-runtime-closure.md" in (
        artifacts.evidence_bundle.changed_files
    )


def test_review_failure_appends_patch_forward_without_overwriting_failed_lane(
    tmp_path: Path,
) -> None:
    artifacts = build_self_iteration_closure_artifacts(
        repo_root=PROJECT_ROOT,
        worktree_path=tmp_path,
    )
    failed_review = review_self_iteration_evidence(
        artifacts.evidence_bundle,
        approve=False,
    )
    patch_link = artifacts.patch_forward_plan.patch_forward_links[0]

    assert artifacts.review_pass.verdict == "approved"
    assert failed_review.verdict == "changes_requested"
    assert patch_link.failed_lane_id == "lane-runtime-evidence"
    assert patch_link.patch_lane_id == "lane-runtime-evidence-patch-1"
    assert any(
        lane.feature_id == "lane-runtime-evidence"
        for lane in artifacts.patch_forward_plan.lane_graph.lanes
    )
    assert any(
        lane.feature_id == "lane-runtime-evidence-patch-1"
        and lane.source_lane_id == "lane-runtime-evidence"
        for lane in artifacts.patch_forward_plan.lane_graph.lanes
    )


def test_github_truth_evidence_and_pr_gate_are_contract_only(tmp_path: Path) -> None:
    artifacts = build_self_iteration_closure_artifacts(
        repo_root=PROJECT_ROOT,
        worktree_path=tmp_path,
    )
    evidence = read_github_truth_evidence(PROJECT_ROOT)

    assert evidence.missing_required_checks == []
    assert evidence.codeowners_covers_mainline is True
    assert evidence.branch_protection_verified is False
    assert evidence.proof_level is ProofLevel.CONTRACT
    assert {"required_checks", "review_evidence_bundle", "rollback_plan"} <= set(
        evidence.pr_template_fields
    )
    assert artifacts.merge_readiness.merge_ready is True
    assert "Blueprint Refs" in artifacts.draft_pr.body
    assert "Provider Changes" in artifacts.draft_pr.body
    assert "none; default proof is fake/local" in artifacts.draft_pr.body


@pytest.mark.asyncio
async def test_memoryos_writeback_preserves_namespace_actor_layer_and_sources(
    tmp_path: Path,
) -> None:
    client = FakeMemoryOSClient()
    artifacts = build_self_iteration_closure_artifacts(
        repo_root=PROJECT_ROOT,
        worktree_path=tmp_path,
    )
    results = await write_self_iteration_memory_evidence(
        client,
        artifacts,
        commit_sha="abc123",
    )
    namespace = task_namespace(
        repo_id="iiyazu/Cross-Muse",
        workspace_id="xmuse",
        god_id="god-execute",
        conversation_id=artifacts.blueprint.conversation_id,
        thread_id="thread-self-iteration-runtime-closure",
        blueprint_id=artifacts.blueprint.blueprint_id,
        feature_id=artifacts.runtime_contract.feature_id,
        lane_id=artifacts.runtime_contract.lane_id,
    )
    pages = await client.search(namespace, query="self-iteration", limit=10)

    assert [result.ok for result in results] == [True, True, True, True]
    assert len(pages) == 4
    assert {page.actor_id for page in pages} == {
        "god-convenor",
        "god-execute",
        "god-review",
        "god-github",
    }
    assert all(page.memory_layer.value == "task_state" for page in pages)
    assert any("commits/abc123/events/blueprint_frozen" in ref for ref in pages[0].source_refs)
    writeback_kinds = {page.metadata["memory_writeback_kind"] for page in pages}
    assert "merge_readiness_evaluated" in writeback_kinds
    assert "pr_merged" not in writeback_kinds
    gate_page = next(
        page
        for page in pages
        if page.metadata["memory_writeback_kind"] == "merge_readiness_evaluated"
    )
    assert gate_page.metadata["real_merge_event"] is False
    envelope = json.loads(artifacts.runtime_contract.stable_json())
    assert envelope["memory_context"]["proof_level"] != ProofLevel.LIVE_RUNTIME
