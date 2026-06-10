from __future__ import annotations

from xmuse_core.structuring.feature_review_contracts import (
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardMergeGuardDecision,
    FeatureGraphPatchForwardMergeGuardHandoff,
    FeatureGraphPatchForwardPlan,
)


def validate_feature_graph_patch_forward_gate_result(
    *,
    plan: FeatureGraphPatchForwardPlan,
    result: FeatureGraphPatchForwardGateResult,
) -> FeatureGraphPatchForwardGateResult:
    """Validate reviewer patch-forward evidence against its coordinator gate plan.

    This pure helper does not apply patches, run gates, or write execution status.
    It only decides whether a recorded patch-forward result satisfies the original
    low-risk gate plan and can be handed to the next coordinator gate.
    """

    result = validate_feature_graph_patch_forward_gate_result_identity(
        plan=plan,
        result=result,
    )
    plan = FeatureGraphPatchForwardPlan.model_validate(plan.model_dump(mode="json"))
    if not result.passed:
        raise ValueError("patch-forward gate result must be passed")
    if not set(result.changed_file_refs).issubset(set(plan.allowed_file_refs)):
        raise ValueError("patch-forward changed files must stay within allowed_file_refs")
    if len(set(result.changed_file_refs)) > plan.max_files_changed:
        raise ValueError("patch-forward changed file count exceeds plan limit")
    if result.lines_changed > plan.max_lines_changed:
        raise ValueError("patch-forward changed line count exceeds plan limit")
    if not set(plan.focused_gates_to_rerun).issubset(set(result.focused_gates_rerun)):
        raise ValueError("patch-forward result must rerun every focused gate in the plan")
    if plan.disallow_new_dependencies and result.introduced_dependency_refs:
        raise ValueError("patch-forward result must not introduce dependencies")
    if plan.disallow_public_contract_changes and result.public_contract_change_refs:
        raise ValueError("patch-forward result must not change public contracts")
    return result


def validate_feature_graph_patch_forward_gate_result_identity(
    *,
    plan: FeatureGraphPatchForwardPlan,
    result: FeatureGraphPatchForwardGateResult,
) -> FeatureGraphPatchForwardGateResult:
    """Validate schema and identity for patch-forward gate evidence.

    This lighter check is used by the coordinator to persist failed gate results
    as evidence. Passing this helper does not mean the result may advance.
    """

    plan = FeatureGraphPatchForwardPlan.model_validate(plan.model_dump(mode="json"))
    result = FeatureGraphPatchForwardGateResult.model_validate(result.model_dump(mode="json"))
    _require_matching_identity(plan, result)
    return result


def build_feature_graph_patch_forward_merge_guard_handoff(
    *,
    plan: FeatureGraphPatchForwardPlan,
    result: FeatureGraphPatchForwardGateResult,
    handoff_id: str,
    gate_result_ref: str,
    created_at: str,
) -> FeatureGraphPatchForwardMergeGuardHandoff:
    """Build the coordinator artifact handed to the next merge-guard step.

    The handoff is only produced from a result that satisfies the strict
    patch-forward gate validator. It does not run merge guard or write status.
    """

    plan = FeatureGraphPatchForwardPlan.model_validate(plan.model_dump(mode="json"))
    result = validate_feature_graph_patch_forward_gate_result(plan=plan, result=result)
    return FeatureGraphPatchForwardMergeGuardHandoff(
        handoff_id=handoff_id,
        plan_id=plan.plan_id,
        gate_result_id=result.result_id,
        verdict_id=result.verdict_id,
        evidence_bundle_id=result.evidence_bundle_id,
        graph_set_id=result.graph_set_id,
        graph_set_version=result.graph_set_version,
        feature_id=result.feature_id,
        feature_graph_id=result.feature_graph_id,
        reviewer_session_id=result.reviewer_session_id,
        patch_diff_ref=result.patch_diff_ref,
        focused_gate_evidence_refs=result.focused_gate_evidence_refs,
        merge_guard_input_refs=[
            gate_result_ref,
            result.patch_diff_ref,
            *result.focused_gate_evidence_refs,
        ],
        required_merge_guard_checks=[
            "verify_patch_forward_gate_result",
            "verify_patch_diff_matches_allowed_scope",
            "run_standard_feature_merge_guard",
        ],
        created_at=created_at,
    )


def build_feature_graph_patch_forward_merge_guard_decision(
    *,
    handoff: FeatureGraphPatchForwardMergeGuardHandoff,
    decision_id: str,
    merge_guard_ref: str,
    merge_guard_evidence_refs: list[str],
    passed: bool,
    failure_reasons: list[str] | None,
    checked_at: str,
) -> FeatureGraphPatchForwardMergeGuardDecision:
    """Build a coordinator-owned decision artifact for merge guard output.

    This records the result of merge guard execution. It does not merge code or
    transition feature graph status.
    """

    handoff = FeatureGraphPatchForwardMergeGuardHandoff.model_validate(
        handoff.model_dump(mode="json")
    )
    return FeatureGraphPatchForwardMergeGuardDecision(
        decision_id=decision_id,
        handoff_id=handoff.handoff_id,
        gate_result_id=handoff.gate_result_id,
        plan_id=handoff.plan_id,
        verdict_id=handoff.verdict_id,
        evidence_bundle_id=handoff.evidence_bundle_id,
        graph_set_id=handoff.graph_set_id,
        graph_set_version=handoff.graph_set_version,
        feature_id=handoff.feature_id,
        feature_graph_id=handoff.feature_graph_id,
        merge_guard_ref=merge_guard_ref,
        merge_guard_evidence_refs=merge_guard_evidence_refs,
        passed=passed,
        failure_reasons=failure_reasons or [],
        checked_at=checked_at,
    )


def _require_matching_identity(
    plan: FeatureGraphPatchForwardPlan,
    result: FeatureGraphPatchForwardGateResult,
) -> None:
    identity_pairs = (
        ("plan_id", result.plan_id, plan.plan_id),
        ("verdict_id", result.verdict_id, plan.verdict_id),
        ("evidence_bundle_id", result.evidence_bundle_id, plan.evidence_bundle_id),
        ("graph_set_id", result.graph_set_id, plan.graph_set_id),
        ("graph_set_version", result.graph_set_version, plan.graph_set_version),
        ("feature_id", result.feature_id, plan.feature_id),
        ("feature_graph_id", result.feature_graph_id, plan.feature_graph_id),
        ("reviewer_session_id", result.reviewer_session_id, plan.reviewer_session_id),
    )
    for field_name, result_value, plan_value in identity_pairs:
        if result_value != plan_value:
            raise ValueError(f"patch-forward result {field_name} must match plan")
