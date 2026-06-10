from __future__ import annotations

from dataclasses import dataclass

from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_patch_forward_gate import (
    build_feature_graph_patch_forward_merge_guard_decision,
    build_feature_graph_patch_forward_merge_guard_handoff,
    validate_feature_graph_patch_forward_gate_result,
    validate_feature_graph_patch_forward_gate_result_identity,
)
from xmuse_core.structuring.feature_graph_patch_forward_status_application import (
    apply_feature_graph_patch_forward_merge_guard_decision,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardMergeGuardDecision,
    FeatureGraphPatchForwardMergeGuardHandoff,
    FeatureGraphPatchForwardPlan,
)


@dataclass(frozen=True)
class FeatureGraphPatchForwardGateResultOutcome:
    plan: FeatureGraphPatchForwardPlan
    result: FeatureGraphPatchForwardGateResult
    advance_to_merge_guard: bool
    merge_guard_handoff: FeatureGraphPatchForwardMergeGuardHandoff | None = None


@dataclass(frozen=True)
class FeatureGraphPatchForwardMergeGuardDecisionOutcome:
    handoff: FeatureGraphPatchForwardMergeGuardHandoff
    decision: FeatureGraphPatchForwardMergeGuardDecision
    eligible_for_status_transition: bool


@dataclass(frozen=True)
class FeatureGraphPatchForwardStatusTransitionOutcome:
    decision: FeatureGraphPatchForwardMergeGuardDecision
    status: FeatureGraphExecutionStatusRecord


def submit_feature_graph_patch_forward_gate_result(
    *,
    artifact_store: FeatureGraphArtifactStore,
    plan_id: str,
    result: FeatureGraphPatchForwardGateResult,
) -> FeatureGraphPatchForwardGateResultOutcome:
    """Submit coordinator-owned patch-forward gate evidence.

    This helper records reviewer patch-forward gate evidence against the saved
    gate plan. Failed gate results are saved as evidence, but only a passed result
    that satisfies the strict plan limits may advance to the next coordinator gate.
    It does not apply patches or write graph status.
    """

    plan = artifact_store.get_patch_forward_plan(plan_id)
    validated_result = validate_feature_graph_patch_forward_gate_result_identity(
        plan=plan,
        result=result,
    )
    advance_to_merge_guard = False
    if validated_result.passed:
        validated_result = validate_feature_graph_patch_forward_gate_result(
            plan=plan,
            result=validated_result,
        )
        advance_to_merge_guard = True
    saved = artifact_store.save_patch_forward_gate_result(validated_result)
    merge_guard_handoff = None
    if advance_to_merge_guard:
        merge_guard_handoff = artifact_store.save_patch_forward_merge_guard_handoff(
            build_feature_graph_patch_forward_merge_guard_handoff(
                plan=plan,
                result=saved,
                handoff_id=_merge_guard_handoff_id(saved),
                gate_result_ref=_gate_result_ref(saved),
                created_at=saved.created_at,
            )
        )
    return FeatureGraphPatchForwardGateResultOutcome(
        plan=plan,
        result=saved,
        advance_to_merge_guard=advance_to_merge_guard,
        merge_guard_handoff=merge_guard_handoff,
    )


def submit_feature_graph_patch_forward_merge_guard_decision(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore | None,
    handoff_id: str,
    merge_guard_ref: str,
    merge_guard_evidence_refs: list[str],
    passed: bool,
    failure_reasons: list[str] | None,
    checked_at: str,
) -> FeatureGraphPatchForwardMergeGuardDecisionOutcome:
    """Record merge guard output for a patch-forward handoff.

    This is still a coordinator-owned artifact write only. Passing the merge
    guard makes the feature eligible for a later status transition; this helper
    does not perform that transition.
    """

    handoff = artifact_store.get_patch_forward_merge_guard_handoff(handoff_id)
    if passed:
        _require_patch_forward_merge_guard_review_context(
            status_store=status_store,
            handoff=handoff,
        )
    decision = build_feature_graph_patch_forward_merge_guard_decision(
        handoff=handoff,
        decision_id=_merge_guard_decision_id(
            handoff_id=handoff.handoff_id,
            checked_at=checked_at,
        ),
        merge_guard_ref=merge_guard_ref,
        merge_guard_evidence_refs=merge_guard_evidence_refs,
        passed=passed,
        failure_reasons=failure_reasons,
        checked_at=checked_at,
    )
    saved = artifact_store.save_patch_forward_merge_guard_decision(decision)
    return FeatureGraphPatchForwardMergeGuardDecisionOutcome(
        handoff=handoff,
        decision=saved,
        eligible_for_status_transition=saved.passed,
    )


def apply_feature_graph_patch_forward_merge_guard_decision_status(
    *,
    artifact_store: FeatureGraphArtifactStore,
    status_store: FeatureGraphStatusStore,
    decision_id: str,
    updated_at: str,
) -> FeatureGraphPatchForwardStatusTransitionOutcome:
    """Apply a saved patch-forward merge guard decision to graph-native status."""

    decision = artifact_store.get_patch_forward_merge_guard_decision(decision_id)
    status = apply_feature_graph_patch_forward_merge_guard_decision(
        store=status_store,
        decision=decision,
        updated_at=updated_at,
    )
    return FeatureGraphPatchForwardStatusTransitionOutcome(
        decision=decision,
        status=status,
    )


def _require_patch_forward_merge_guard_review_context(
    *,
    status_store: FeatureGraphStatusStore | None,
    handoff: FeatureGraphPatchForwardMergeGuardHandoff,
) -> None:
    if status_store is None:
        raise ValueError("patch-forward merge guard decision requires status store")
    current = status_store.get(
        graph_set_id=handoff.graph_set_id,
        feature_graph_id=handoff.feature_graph_id,
    )
    if current.status is not FeatureGraphExecutionStatus.REVIEWING:
        raise ValueError("patch-forward merge guard decision requires reviewing status")
    identity_pairs = (
        ("graph_set_id", current.graph_set_id, handoff.graph_set_id),
        ("graph_set_version", current.graph_set_version, handoff.graph_set_version),
        ("feature_id", current.feature_id, handoff.feature_id),
        ("feature_graph_id", current.feature_graph_id, handoff.feature_graph_id),
    )
    for field_name, current_value, handoff_value in identity_pairs:
        if current_value != handoff_value:
            raise ValueError(
                f"current status {field_name} must match merge guard handoff"
            )


def _merge_guard_handoff_id(result: FeatureGraphPatchForwardGateResult) -> str:
    return f"fgpfmgh:{result.result_id}"


def _gate_result_ref(result: FeatureGraphPatchForwardGateResult) -> str:
    return f"feature_graph_patch_forward_gate_result:{result.result_id}:v1"


def _merge_guard_decision_id(*, handoff_id: str, checked_at: str) -> str:
    return f"fgpfmgd:{handoff_id}:{_safe_timestamp(checked_at)}"


def _safe_timestamp(value: str) -> str:
    return value.replace("-", "").replace(":", "").replace(".", "").lower()
