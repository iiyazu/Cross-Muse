from __future__ import annotations

import pytest

from xmuse_core.structuring.blueprint_execution.lane_dag_service import (
    BlueprintFeatureSpec,
    BlueprintLaneDagRequest,
    BlueprintLaneDagService,
    BlueprintLaneSpec,
    LaneDependencyEdge,
    LaneDependencyType,
    LaneExecutionStatus,
    LaneFailureEvidence,
    LaneRecoveryDecisionType,
    LaneRuntimeBudget,
    evaluate_lane_recovery,
)
from xmuse_core.structuring.lane_planner_v2 import LanePlannerV2ValidationError
from xmuse_core.structuring.mission_blueprint_v1 import (
    MissionBlueprintDecisionLogEntry,
    MissionBlueprintStatus,
    MissionBlueprintV1,
)


def test_frozen_blueprint_builds_feature_lane_dag_with_typed_edges() -> None:
    plan = BlueprintLaneDagService().build_plan(
        _request(
            features=[
                _feature("feature-a"),
                _feature("feature-b", depends_on_features=["feature-a"]),
            ],
            lanes=[
                _lane("lane-a", feature_id="feature-a"),
                _lane(
                    "lane-b",
                    feature_id="feature-b",
                    dependency_edges=[
                        LaneDependencyEdge(
                            source_lane_id="lane-a",
                            target_lane_id="lane-b",
                            edge_type=LaneDependencyType.REVIEW_DEP,
                            rationale="lane-b requires lane-a review evidence",
                            source_refs=["review:lane-a"],
                        )
                    ],
                ),
            ],
        )
    )

    lane_b = next(lane for lane in plan.lane_graph.lanes if lane.feature_id == "lane-b")

    assert plan.blueprint_id == "bp-1"
    assert plan.blueprint_ref == "blueprint:bp-1:1"
    assert plan.blueprint_proof_level == "contract_proof"
    assert plan.feature_ids == ["feature-a", "feature-b"]
    assert lane_b.depends_on == ["lane-a"]
    assert {edge.edge_type for edge in plan.dependency_edges} == {
        LaneDependencyType.HARD_DEP,
        LaneDependencyType.REVIEW_DEP,
    }
    assert plan.memory_refs == ["memory://conversation/conv-1/decision/1"]
    assert "message:freeze" in plan.source_refs


def test_lane_dag_plan_preserves_freeze_proof_level() -> None:
    plan = BlueprintLaneDagService().build_plan(
        _request(
            blueprint_proof_level="opt_in_live_proof",
            source_refs=["god-room-event:evt-freeze"],
        )
    )

    assert plan.blueprint_proof_level == "opt_in_live_proof"
    assert "god-room-event:evt-freeze" in plan.source_refs


def test_lane_dag_plan_preserves_runtime_contracts_from_frozen_blueprint() -> None:
    plan = BlueprintLaneDagService().build_plan(
        _request(
            lanes=[
                _lane(
                    "lane-a",
                    owner="god-executor",
                    inputs=["blueprint:bp-1:1#acceptance"],
                    outputs=["artifact://lane-a/runtime-contract.json"],
                    required_checks=["focused-pytest", "ruff"],
                    allowed_files=["src/xmuse_core/structuring/lane_runtime_contracts.py"],
                    rollback_constraints=["preserve graph-set authority"],
                    review_profile="runtime-contract-review",
                    budget=LaneRuntimeBudget(
                        max_attempts=3,
                        max_consecutive_same_failure=2,
                        max_runtime_seconds=1800,
                        retry_backoff_seconds=30,
                        source_refs=["budget:lane-a"],
                    ),
                )
            ]
        )
    )

    contract = plan.lane_contracts[0]

    assert contract.lane_id == "lane-a"
    assert contract.owner == "god-executor"
    assert contract.inputs == ["blueprint:bp-1:1#acceptance"]
    assert contract.outputs == ["artifact://lane-a/runtime-contract.json"]
    assert contract.dependency_refs == []
    assert contract.required_checks == ["focused-pytest", "ruff"]
    assert contract.allowed_files == [
        "src/xmuse_core/structuring/lane_runtime_contracts.py"
    ]
    assert contract.rollback_constraints == ["preserve graph-set authority"]
    assert contract.review_profile == "runtime-contract-review"
    assert contract.memory_refs == ["memory://conversation/conv-1/decision/1"]
    assert contract.budget.max_consecutive_same_failure == 2


def test_lane_dag_rejects_invalid_blueprint_refs_and_missing_acceptance() -> None:
    service = BlueprintLaneDagService()
    invalid_ref_request = _request(
        lanes=[
            _lane(
                "lane-a",
                blueprint_refs=["blueprint:unknown:1"],
            )
        ]
    )
    missing_acceptance_request = _request(
        lanes=[
            _lane(
                "lane-a",
                acceptance_criteria=[],
            )
        ]
    )

    with pytest.raises(LanePlannerV2ValidationError) as invalid_ref_error:
        service.build_plan(invalid_ref_request)
    with pytest.raises(LanePlannerV2ValidationError) as missing_acceptance_error:
        service.build_plan(missing_acceptance_request)

    assert invalid_ref_error.value.report.issues[0].code == "invalid_blueprint_ref"
    assert missing_acceptance_error.value.report.issues[0].code == (
        "missing_acceptance_criteria"
    )


def test_lane_dag_rejects_cycles_deterministically() -> None:
    request = _request(
        features=[_feature("feature-a"), _feature("feature-b")],
        lanes=[
            _lane(
                "lane-a",
                feature_id="feature-a",
                dependency_edges=[
                    LaneDependencyEdge(
                        source_lane_id="lane-b",
                        target_lane_id="lane-a",
                        edge_type=LaneDependencyType.HARD_DEP,
                        rationale="cycle a",
                    )
                ],
            ),
            _lane(
                "lane-b",
                feature_id="feature-b",
                dependency_edges=[
                    LaneDependencyEdge(
                        source_lane_id="lane-a",
                        target_lane_id="lane-b",
                        edge_type=LaneDependencyType.HARD_DEP,
                        rationale="cycle b",
                    )
                ],
            ),
        ],
    )

    with pytest.raises(LanePlannerV2ValidationError) as exc_info:
        BlueprintLaneDagService().build_plan(request)

    assert exc_info.value.report.issues[0].code == "invalid_lane_graph"
    assert "cycle" in exc_info.value.report.issues[0].message.lower()


def test_dispatch_readiness_blocks_dependents_until_dependency_is_approved() -> None:
    service = BlueprintLaneDagService()
    plan = service.build_plan(
        _request(
            features=[
                _feature("feature-a"),
                _feature("feature-b", depends_on_features=["feature-a"]),
            ],
            lanes=[
                _lane("lane-a", feature_id="feature-a"),
                _lane("lane-b", feature_id="feature-b"),
            ],
        )
    )

    failed = service.evaluate_dispatch(
        plan,
        lane_statuses={"lane-a": LaneExecutionStatus.FAILED},
    )
    approved = service.evaluate_dispatch(
        plan,
        lane_statuses={"lane-a": LaneExecutionStatus.APPROVED},
    )

    failed_by_lane = {decision.lane_id: decision for decision in failed}
    approved_by_lane = {decision.lane_id: decision for decision in approved}
    assert failed_by_lane["lane-b"].ready is False
    assert failed_by_lane["lane-b"].blockers == ["lane-a is failed"]
    assert approved_by_lane["lane-b"].ready is True
    assert approved_by_lane["lane-b"].blockers == []


def test_lane_recovery_requires_refactor_after_repeated_same_failure() -> None:
    decision = evaluate_lane_recovery(
        lane_id="lane-a",
        budget=LaneRuntimeBudget(max_attempts=4, max_consecutive_same_failure=2),
        failures=[
            LaneFailureEvidence(
                lane_id="lane-a",
                attempt=1,
                failure_class="contract_boundary_leak",
                reason="TUI wrote lane status directly.",
                source_refs=["pytest:test_tui_contract"],
            ),
            LaneFailureEvidence(
                lane_id="lane-a",
                attempt=2,
                failure_class="contract_boundary_leak",
                reason="Dashboard wrote lane status directly.",
                source_refs=["pytest:test_dashboard_contract"],
            ),
        ],
    )

    assert decision.decision is LaneRecoveryDecisionType.REFACTOR_REQUIRED
    assert decision.retry_allowed is False
    assert decision.refactor_required_reason == (
        "failure_class contract_boundary_leak repeated 2 times"
    )
    assert decision.next_action == (
        "refactor or replace the failing lane boundary before retrying"
    )


def test_lane_recovery_suspends_when_retry_budget_is_exhausted() -> None:
    decision = evaluate_lane_recovery(
        lane_id="lane-a",
        budget=LaneRuntimeBudget(max_attempts=2, max_consecutive_same_failure=2),
        failures=[
            LaneFailureEvidence(
                lane_id="lane-a",
                attempt=1,
                failure_class="provider_unavailable",
                reason="provider unavailable",
                source_refs=["provider:deepseek"],
            ),
            LaneFailureEvidence(
                lane_id="lane-a",
                attempt=2,
                failure_class="ci_timeout",
                reason="CI timed out",
                source_refs=["github:run:1"],
            ),
        ],
    )

    assert decision.decision is LaneRecoveryDecisionType.SUSPENDED
    assert decision.retry_allowed is False
    assert decision.suspend_reason == "retry_budget_exhausted"


def test_patch_forward_creates_auditable_patch_lane_link() -> None:
    service = BlueprintLaneDagService()
    plan = service.build_plan(_request(lanes=[_lane("lane-a")]))

    patched = service.append_patch_forward_lane(
        plan,
        failed_lane_id="lane-a",
        patch_lane_id="lane-a-patch-1",
        prompt="Patch lane-a after review found missing evidence.",
        acceptance_criteria=["Review evidence is addressed."],
        verdict_ref="review:verdict:lane-a",
        evidence_refs=["review:evidence:lane-a"],
    )

    patch_lane = next(
        lane for lane in patched.lane_graph.lanes if lane.feature_id == "lane-a-patch-1"
    )

    assert patch_lane.task_type == "patch_forward"
    assert patch_lane.source_lane_id == "lane-a"
    assert patched.patch_forward_links[0].failed_lane_id == "lane-a"
    assert patched.patch_forward_links[0].patch_lane_id == "lane-a-patch-1"
    assert patched.patch_forward_links[0].verdict_ref == "review:verdict:lane-a"
    assert patched.dependency_edges[-1].edge_type is LaneDependencyType.ARTIFACT_DEP
    assert patched.dependency_edges[-1].dispatch_blocking is False


def _request(
    *,
    features: list[BlueprintFeatureSpec] | None = None,
    lanes: list[BlueprintLaneSpec] | None = None,
    blueprint_proof_level: str = "contract_proof",
    source_refs: list[str] | None = None,
) -> BlueprintLaneDagRequest:
    return BlueprintLaneDagRequest(
        graph_id="graph-bp-1",
        resolution_id="resolution-1",
        graph_version=1,
        blueprint=_blueprint(),
        blueprint_proof_level=blueprint_proof_level,
        features=features or [_feature("feature-a")],
        lanes=lanes or [_lane("lane-a")],
        source_refs=source_refs or ["message:freeze"],
    )


def _blueprint(
    *,
    status: MissionBlueprintStatus = MissionBlueprintStatus.FROZEN,
) -> MissionBlueprintV1:
    return MissionBlueprintV1(
        blueprint_id="bp-1",
        conversation_id="conv-1",
        revision=1,
        goal="Make the mainline executable.",
        scope=["Blueprint to laneDAG"],
        acceptance_contracts=["LaneDAG is validated."],
        source_refs=["blueprint:bp-1:1", "message:freeze"],
        status=status,
        decision_log=[
            MissionBlueprintDecisionLogEntry(
                decision="Freeze blueprint for execution.",
                source_refs=["message:freeze"],
            )
        ],
        approved_by=["god-review"],
    )


def _feature(
    feature_id: str,
    *,
    depends_on_features: list[str] | None = None,
) -> BlueprintFeatureSpec:
    return BlueprintFeatureSpec(
        feature_id=feature_id,
        title=f"Feature {feature_id}",
        goal=f"Deliver {feature_id}.",
        acceptance_criteria=[f"{feature_id} acceptance exists."],
        blueprint_refs=["blueprint:bp-1:1"],
        depends_on_features=depends_on_features or [],
        memory_refs=["memory://conversation/conv-1/decision/1"]
        if feature_id == "feature-a"
        else [],
    )


def _lane(
    lane_id: str,
    *,
    feature_id: str = "feature-a",
    acceptance_criteria: list[str] | None = None,
    blueprint_refs: list[str] | None = None,
    dependency_edges: list[LaneDependencyEdge] | None = None,
    owner: str = "codex",
    inputs: list[str] | None = None,
    outputs: list[str] | None = None,
    required_checks: list[str] | None = None,
    allowed_files: list[str] | None = None,
    rollback_constraints: list[str] | None = None,
    review_profile: str = "standard",
    budget: LaneRuntimeBudget | None = None,
) -> BlueprintLaneSpec:
    return BlueprintLaneSpec(
        lane_id=lane_id,
        feature_id=feature_id,
        title=f"Lane {lane_id}",
        prompt=f"Implement {lane_id}.",
        acceptance_criteria=(
            [f"{lane_id} acceptance passes."]
            if acceptance_criteria is None
            else acceptance_criteria
        ),
        blueprint_refs=blueprint_refs or ["blueprint:bp-1:1"],
        dependency_edges=dependency_edges or [],
        expected_touched_areas=["src/xmuse_core/structuring"],
        owner=owner,
        inputs=inputs or ["blueprint:bp-1:1"],
        outputs=outputs or [f"artifact://{lane_id}/evidence.json"],
        required_checks=required_checks or ["focused-pytest"],
        allowed_files=allowed_files or ["src/xmuse_core/structuring"],
        rollback_constraints=rollback_constraints or ["preserve frozen blueprint"],
        review_profile=review_profile,
        budget=budget or LaneRuntimeBudget(),
    )
