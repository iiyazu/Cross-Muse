from __future__ import annotations

from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardMergeGuardDecision,
)


def apply_feature_graph_patch_forward_merge_guard_decision(
    *,
    store: FeatureGraphStatusStore,
    decision: FeatureGraphPatchForwardMergeGuardDecision,
    updated_at: str,
) -> FeatureGraphExecutionStatusRecord:
    """Apply a passed patch-forward merge guard decision to graph-native status.

    This helper only writes the graph-native status transition. It does not run
    merge guard, merge code, or touch the legacy lane projection.
    """

    decision = FeatureGraphPatchForwardMergeGuardDecision.model_validate(
        decision.model_dump(mode="json")
    )
    if not decision.passed:
        raise ValueError("patch-forward merge guard decision must be passed")
    current = store.get(
        graph_set_id=decision.graph_set_id,
        feature_graph_id=decision.feature_graph_id,
    )
    target = _target_status_record(
        current_status=current,
        decision=decision,
        updated_at=updated_at,
    )
    if (
        current.status is FeatureGraphExecutionStatus.MERGED
        and current.status_id == target.status_id
    ):
        return current
    _require_reviewing_identity(current, decision)
    return store.transition(target, expected_status=FeatureGraphExecutionStatus.REVIEWING)


def _target_status_record(
    *,
    current_status: FeatureGraphExecutionStatusRecord,
    decision: FeatureGraphPatchForwardMergeGuardDecision,
    updated_at: str,
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id=_feature_graph_status_id(
            graph_set_id=decision.graph_set_id,
            feature_graph_id=decision.feature_graph_id,
            updated_at=updated_at,
        ),
        conversation_id=current_status.conversation_id,
        planning_run_id=current_status.planning_run_id,
        graph_set_id=decision.graph_set_id,
        graph_set_version=decision.graph_set_version,
        feature_plan_id=current_status.feature_plan_id,
        feature_plan_version=current_status.feature_plan_version,
        feature_id=decision.feature_id,
        feature_graph_id=decision.feature_graph_id,
        status=FeatureGraphExecutionStatus.MERGED,
        ready_lane_ids=[],
        active_lane_ids=[],
        completed_lane_ids=list(current_status.completed_lane_ids),
        blocked_lane_ids=list(current_status.blocked_lane_ids),
        projection_lane_ids=list(current_status.projection_lane_ids),
        feature_lanes_projection_ref=current_status.feature_lanes_projection_ref,
        provider_session_binding_degradations=list(
            current_status.provider_session_binding_degradations
        ),
        updated_at=updated_at,
    )


def _require_reviewing_identity(
    current_status: FeatureGraphExecutionStatusRecord,
    decision: FeatureGraphPatchForwardMergeGuardDecision,
) -> None:
    if current_status.status is not FeatureGraphExecutionStatus.REVIEWING:
        raise ValueError("patch-forward merge guard decision requires reviewing status")
    identity_pairs = (
        ("graph_set_id", current_status.graph_set_id, decision.graph_set_id),
        ("graph_set_version", current_status.graph_set_version, decision.graph_set_version),
        ("feature_id", current_status.feature_id, decision.feature_id),
        ("feature_graph_id", current_status.feature_graph_id, decision.feature_graph_id),
    )
    for field_name, current_value, decision_value in identity_pairs:
        if current_value != decision_value:
            raise ValueError(f"current status {field_name} must match decision")


def _feature_graph_status_id(
    *,
    graph_set_id: str,
    feature_graph_id: str,
    updated_at: str,
) -> str:
    return (
        f"fgs:{graph_set_id}:{feature_graph_id}:patch_forward_merged:"
        f"{_safe_updated_at(updated_at)}"
    )


def _safe_updated_at(updated_at: str) -> str:
    return (
        updated_at.replace(":", "")
        .replace("-", "")
        .replace("+", "")
        .replace("Z", "z")
    )
