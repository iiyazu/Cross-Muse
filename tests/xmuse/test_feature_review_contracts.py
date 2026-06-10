from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from xmuse_core.structuring.feature_review_contracts import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardMergeGuardDecision,
    FeatureGraphPatchForwardMergeGuardHandoff,
    FeatureGraphPatchForwardPlan,
    FeatureGraphReviewCoordinatorAction,
    FeatureGraphReviewStatusTransitionPlan,
    FeatureGraphStatusEventRecord,
    FeatureGraphTakeoverDecision,
    FeatureGraphTakeoverFollowupReviewApplicationRecord,
    FeatureGraphTakeoverHandoff,
    FeatureGraphTakeoverOutcome,
    FeatureGraphTakeoverPlan,
    FeatureGraphTakeoverReviewHandoff,
    FeatureGraphWorkerEvidenceSubmissionPlan,
    FeatureReviewDecision,
    FeatureReviewVerdict,
    ProviderSessionBindingDegradationEvidence,
    ProviderSessionBindingRecord,
    ReworkPacket,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def test_feature_evidence_bundle_golden_fixture_is_stable() -> None:
    bundle = FeatureEvidenceBundle.model_validate(
        _artifact_payload("feature_evidence_bundle.v1.json")
    )

    assert bundle.feature_id == "feature-provider-session-binding"
    assert bundle.feature_graph_id == "graph-provider-session-binding"
    assert bundle.provider_session_binding_ref == "provider_session_binding:psb_demo:v1"
    assert bundle.lane_graph_summary.ready_lane_ids == ["binding-schema"]
    assert bundle.verification.commands_run == [
        "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
    ]
    assert bundle.model_dump(mode="json") == _artifact_payload(
        "feature_evidence_bundle.v1.json"
    )


def test_feature_review_verdict_requires_merge_gate_evidence() -> None:
    verdict = FeatureReviewVerdict.model_validate(
        _artifact_payload("feature_review_verdict.v1.json")
    )

    assert verdict.decision is FeatureReviewDecision.MERGE
    assert verdict.acceptance_coverage[0].status == "covered"
    assert verdict.scope_assessment.diff_scope == "feature_matched"
    assert verdict.merge_gate_evidence.merge_guard_ref == "logs/merge_guard/provider-binding.json"

    with pytest.raises(ValidationError, match="merge verdicts require merge_gate_evidence"):
        FeatureReviewVerdict.model_validate(
            {
                **verdict.model_dump(mode="json"),
                "merge_gate_evidence": None,
            }
        )


def test_patch_forward_verdict_requires_strong_low_risk_gate() -> None:
    base = {
        "verdict_id": "fverdict_patch_forward",
        "evidence_bundle_id": "fevb_demo",
        "decision": "patch_forward",
        "summary": "Fix a missing import in an existing worker-touched file.",
        "blocking_findings": [],
        "non_blocking_findings": ["One import is missing."],
        "evidence_refs": ["feature_evidence_bundle:fevb_demo:v1"],
        "acceptance_coverage": [
            {
                "criterion": "Provider binding validates explicit session ids.",
                "status": "covered",
                "evidence_refs": ["logs/gates/provider-binding.json"],
            }
        ],
        "scope_assessment": {
            "diff_scope": "feature_matched",
            "touched_files": ["src/xmuse_core/agents/provider_session_binding.py"],
            "unexpected_files": [],
            "public_contract_changed": False,
            "new_dependency_added": False,
        },
        "required_gates_before_merge": [
            "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
        ],
        "reviewer_session_id": "god-review-demo",
        "patch_forward_gate": {
            "risk": "low",
            "reason_not_rework": "A one-line import fix is cheaper than rehydrating the worker.",
            "allowed_file_refs": ["src/xmuse_core/agents/provider_session_binding.py"],
            "max_files_changed": 1,
            "max_lines_changed": 5,
            "focused_gates_to_rerun": [
                "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
            ],
            "disallow_new_dependencies": True,
            "disallow_public_contract_changes": True,
        },
    }

    verdict = FeatureReviewVerdict.model_validate(base)

    assert verdict.decision is FeatureReviewDecision.PATCH_FORWARD
    assert verdict.patch_forward_gate is not None

    weak_gate = {
        **base,
        "patch_forward_gate": {
            **base["patch_forward_gate"],
            "risk": "medium",
        },
    }
    with pytest.raises(ValidationError, match="patch_forward requires low risk"):
        FeatureReviewVerdict.model_validate(weak_gate)

    missing_gate = {**base, "patch_forward_gate": None}
    with pytest.raises(ValidationError, match="patch_forward requires patch_forward_gate"):
        FeatureReviewVerdict.model_validate(missing_gate)


def test_rework_packet_targets_same_or_resumable_worker_session() -> None:
    packet = ReworkPacket.model_validate(_artifact_payload("rework_packet.v1.json"))

    assert packet.source_verdict_id == "fverdict_rework_demo"
    assert packet.target_worker_session_id == "god-worker-demo"
    assert packet.gates_to_rerun == [
        "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
    ]

    with pytest.raises(
        ValidationError,
        match=(
            "rework packet requires target_worker_session_id "
            "or target_provider_session_binding_ref"
        ),
    ):
        ReworkPacket.model_validate(
            {
                **packet.model_dump(mode="json"),
                "target_worker_session_id": None,
                "target_provider_session_binding_ref": None,
            }
        )


def test_feature_graph_rework_packet_golden_fixture_is_stable() -> None:
    packet = ReworkPacket.model_validate(
        _artifact_payload("feature_graph_rework_packet.v1.json")
    )

    assert packet.source_verdict_id == "fverdict_rework_demo"
    assert packet.target_worker_session_id == "god-worker-demo"
    assert packet.target_provider_session_binding_ref == "provider_session_binding:psb_demo:v1"
    assert packet.files_or_areas_to_revisit == [
        "src/xmuse_core/agents/provider_session_binding.py",
        "tests/xmuse/test_provider_session_binding.py",
    ]
    assert packet.model_dump(mode="json") == _artifact_payload(
        "feature_graph_rework_packet.v1.json"
    )


def test_provider_session_binding_requires_explicit_provider_session_id() -> None:
    binding = ProviderSessionBindingRecord.model_validate(
        _artifact_payload("provider_session_binding.v1.json")
    )

    assert binding.provider == "codex"
    assert binding.provider_session_id == "codex-session-11111111-2222-3333-4444-555555555555"
    assert binding.session_kind == "exec"
    assert binding.status == "active"

    with pytest.raises(ValidationError, match="provider_session_id must be explicit"):
        ProviderSessionBindingRecord.model_validate(
            {
                **binding.model_dump(mode="json"),
                "provider_session_id": "--last",
            }
        )

    with pytest.raises(ValidationError, match="resume_command_template must not use --last"):
        ProviderSessionBindingRecord.model_validate(
            {
                **binding.model_dump(mode="json"),
                "resume_command_template": "codex exec resume --last {prompt}",
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("created_at", "not-a-timestamp", "created_at must be ISO-8601"),
        ("created_at", "2026-06-03T02:10:00", "created_at must include timezone offset"),
        ("last_used_at", "not-a-timestamp", "last_used_at must be ISO-8601"),
        (
            "last_verified_at",
            "2026-06-03T02:11:30",
            "last_verified_at must include timezone offset",
        ),
    ],
)
def test_provider_session_binding_requires_timestamps_with_timezone(
    field: str,
    value: str,
    message: str,
) -> None:
    binding = ProviderSessionBindingRecord.model_validate(
        _artifact_payload("provider_session_binding.v1.json")
    )

    with pytest.raises(ValidationError, match=message):
        ProviderSessionBindingRecord.model_validate(
            {
                **binding.model_dump(mode="json"),
                field: value,
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        (
            "last_used_at",
            "2026-06-03T02:09:59+08:00",
            "last_used_at must not be earlier than created_at",
        ),
        (
            "last_verified_at",
            "2026-06-03T02:09:59+08:00",
            "last_verified_at must not be earlier than created_at",
        ),
    ],
)
def test_provider_session_binding_timeline_cannot_precede_creation(
    field: str,
    value: str,
    message: str,
) -> None:
    binding = ProviderSessionBindingRecord.model_validate(
        _artifact_payload("provider_session_binding.v1.json")
    )

    with pytest.raises(ValidationError, match=message):
        ProviderSessionBindingRecord.model_validate(
            {
                **binding.model_dump(mode="json"),
                field: value,
            }
        )


def test_feature_graph_status_record_uses_graph_native_identity() -> None:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )

    assert status.feature_graph_id == "graph-provider-session-binding"
    assert status.ready_lane_ids == ["binding-schema"]
    assert status.projection_lane_ids == [
        "lane:conv-xmuse-hardening:graph-provider-session-binding:binding-schema"
    ]
    assert status.feature_lanes_projection_ref == "feature_lanes.json#projection_revision=42"
    assert status.provider_session_binding_degradations == []

    with pytest.raises(ValidationError, match="feature graph status must identify graph_set_id"):
        FeatureGraphExecutionStatusRecord.model_validate(
            {
                **status.model_dump(mode="json"),
                "graph_set_id": "",
            }
        )


@pytest.mark.parametrize(
    ("updated_at", "message"),
    [
        ("not-a-timestamp", "updated_at must be ISO-8601"),
        ("2026-06-03T03:00:00", "updated_at must include timezone offset"),
    ],
)
def test_feature_graph_status_record_requires_timestamp_with_timezone(
    updated_at: str,
    message: str,
) -> None:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )

    with pytest.raises(ValidationError, match=message):
        FeatureGraphExecutionStatusRecord.model_validate(
            {
                **status.model_dump(mode="json"),
                "updated_at": updated_at,
            }
        )


def test_feature_graph_status_event_record_golden_fixture_is_stable() -> None:
    event = FeatureGraphStatusEventRecord.model_validate(
        _artifact_payload("feature_graph_status_event.v1.json")
    )

    assert event.event_type == "feature_graph_status.transitioned"
    assert event.graph_set_id == "graph-set-provider-session-binding"
    assert event.feature_graph_id == "graph-provider-session-binding"
    assert event.from_status == "ready"
    assert event.to_status == "running"
    assert event.status_id == "fgs-provider-binding-running"
    assert event.idempotency_key == (
        "feature_graph_status.transitioned:"
        "graph-set-provider-session-binding:graph-provider-session-binding:"
        "fgs-provider-binding-ready:fgs-provider-binding-running"
    )
    assert event.model_dump(mode="json") == _artifact_payload(
        "feature_graph_status_event.v1.json"
    )

    with pytest.raises(ValidationError, match="event_type must be a feature graph status event"):
        FeatureGraphStatusEventRecord.model_validate(
            {
                **event.model_dump(mode="json"),
                "event_type": "lane.updated",
            }
        )


@pytest.mark.parametrize(
    ("updated_at", "message"),
    [
        ("not-a-timestamp", "updated_at must be ISO-8601"),
        ("2026-06-03T03:10:00", "updated_at must include timezone offset"),
    ],
)
def test_feature_graph_status_event_requires_timestamp_with_timezone(
    updated_at: str,
    message: str,
) -> None:
    event = FeatureGraphStatusEventRecord.model_validate(
        _artifact_payload("feature_graph_status_event.v1.json")
    )

    with pytest.raises(ValidationError, match=message):
        FeatureGraphStatusEventRecord.model_validate(
            {
                **event.model_dump(mode="json"),
                "updated_at": updated_at,
            }
        )


def test_feature_graph_status_transition_event_requires_derived_idempotency_key() -> None:
    event = FeatureGraphStatusEventRecord.model_validate(
        _artifact_payload("feature_graph_status_event.v1.json")
    )

    with pytest.raises(
        ValidationError,
        match="transitioned event idempotency_key must match status identity",
    ):
        FeatureGraphStatusEventRecord.model_validate(
            {
                **event.model_dump(mode="json"),
                "idempotency_key": "feature_graph_status.transitioned:wrong",
            }
        )


def test_feature_graph_status_transition_event_requires_derived_event_id() -> None:
    event = FeatureGraphStatusEventRecord.model_validate(
        _artifact_payload("feature_graph_status_event.v1.json")
    )

    with pytest.raises(
        ValidationError,
        match="transitioned event_id must match status identity",
    ):
        FeatureGraphStatusEventRecord.model_validate(
            {
                **event.model_dump(mode="json"),
                "event_id": "fgse:transition:wrong",
            }
        )


def test_feature_graph_status_initialized_event_requires_derived_idempotency_key() -> None:
    payload = {
        "event_id": "fgse:initialized:graph-set-1:graph-feature-a:fgs-ready",
        "event_type": "feature_graph_status.initialized",
        "graph_set_id": "graph-set-1",
        "graph_set_version": 1,
        "feature_graph_id": "graph-feature-a",
        "feature_id": "feature-a",
        "from_status": None,
        "to_status": "ready",
        "from_status_id": None,
        "status_id": "fgs-ready",
        "updated_at": "2026-06-03T03:00:00Z",
        "idempotency_key": (
            "feature_graph_status.initialized:graph-set-1:graph-feature-a:fgs-ready"
        ),
    }

    assert FeatureGraphStatusEventRecord.model_validate(payload).idempotency_key == (
        "feature_graph_status.initialized:graph-set-1:graph-feature-a:fgs-ready"
    )

    with pytest.raises(
        ValidationError,
        match="initialized event idempotency_key must match status identity",
    ):
        FeatureGraphStatusEventRecord.model_validate(
            {
                **payload,
                "idempotency_key": "feature_graph_status.initialized:wrong",
            }
        )


def test_feature_graph_status_initialized_event_requires_derived_event_id() -> None:
    payload = {
        "event_id": "fgse:initialized:graph-set-1:graph-feature-a:fgs-ready",
        "event_type": "feature_graph_status.initialized",
        "graph_set_id": "graph-set-1",
        "graph_set_version": 1,
        "feature_graph_id": "graph-feature-a",
        "feature_id": "feature-a",
        "from_status": None,
        "to_status": "ready",
        "from_status_id": None,
        "status_id": "fgs-ready",
        "updated_at": "2026-06-03T03:00:00Z",
        "idempotency_key": (
            "feature_graph_status.initialized:graph-set-1:graph-feature-a:fgs-ready"
        ),
    }

    with pytest.raises(
        ValidationError,
        match="initialized event_id must match status identity",
    ):
        FeatureGraphStatusEventRecord.model_validate(
            {
                **payload,
                "event_id": "fgse:initialized:wrong",
            }
        )


def test_feature_graph_status_provider_binding_degradation_event_golden_fixture_is_stable() -> None:
    event = FeatureGraphStatusEventRecord.model_validate(
        _artifact_payload("feature_graph_provider_binding_degradation_event.v1.json")
    )

    assert event.event_type == "feature_graph_status.provider_session_binding_degraded"
    assert event.from_status == "running"
    assert event.to_status == "running"
    assert event.idempotency_key == (
        "feature_graph_status.provider_session_binding_degraded:"
        "graph-set-provider-session-binding:graph-provider-session-binding:"
        "provider_session_binding:psb_demo:v1:mark_failed_failed"
    )
    assert event.model_dump(mode="json") == _artifact_payload(
        "feature_graph_provider_binding_degradation_event.v1.json"
    )

    with pytest.raises(
        ValidationError,
        match="provider session binding degraded event_id must match evidence",
    ):
        FeatureGraphStatusEventRecord.model_validate(
            {
                **event.model_dump(mode="json"),
                "event_id": "fgse:provider-session-binding-degraded:wrong",
            }
        )


def test_feature_graph_review_status_transition_plan_golden_fixture_is_stable() -> None:
    plan = FeatureGraphReviewStatusTransitionPlan.model_validate(
        _artifact_payload("feature_graph_review_status_transition_plan.v1.json")
    )

    assert plan.coordinator_action is FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS
    assert plan.decision is FeatureReviewDecision.MERGE
    assert plan.expected_status == "reviewing"
    assert plan.target_status == "merged"
    assert plan.target_status_record is not None
    assert plan.target_status_record.status == "merged"
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_review_status_transition_plan.v1.json"
    )

    with pytest.raises(ValidationError, match="transition plans require target_status_record"):
        FeatureGraphReviewStatusTransitionPlan.model_validate(
            {
                **plan.model_dump(mode="json"),
                "target_status_record": None,
            }
        )


def test_feature_graph_status_records_provider_binding_degradation_evidence() -> None:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        {
            **_artifact_payload("feature_graph_status.v1.json"),
            "status": "failed",
            "provider_session_binding_degradations": [
                {
                    "binding_id": "psb-codex-demo",
                    "reason": "mark_failed_failed",
                    "evidence_refs": [
                        "feature_lanes.json#lane=lane-a",
                        "provider_session_binding:psb-codex-demo:v1",
                    ],
                    "failure": "provider session binding store unavailable",
                }
            ],
        }
    )

    degradation = status.provider_session_binding_degradations[0]
    assert degradation.binding_id == "psb-codex-demo"
    assert degradation.reason == "mark_failed_failed"
    assert degradation.evidence_refs == [
        "feature_lanes.json#lane=lane-a",
        "provider_session_binding:psb-codex-demo:v1",
    ]

    with pytest.raises(ValidationError, match="evidence_refs must contain at least one item"):
        ProviderSessionBindingDegradationEvidence.model_validate(
            {
                "binding_id": "psb-codex-demo",
                "reason": "mark_failed_failed",
                "evidence_refs": [],
            }
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("graph_set_version", 2, "target_status_record graph_set_version must match plan"),
        ("feature_id", "other-feature", "target_status_record feature_id must match plan"),
        ("updated_at", "2026-06-03T02:15:00Z", "target_status_record updated_at must match plan"),
    ],
)
def test_feature_graph_review_status_transition_plan_rejects_target_identity_mismatch(
    field: str,
    value: int | str,
    message: str,
) -> None:
    payload = _artifact_payload("feature_graph_review_status_transition_plan.v1.json")
    target_status_record = {
        **payload["target_status_record"],
        field: value,
    }

    with pytest.raises(ValidationError, match=message):
        FeatureGraphReviewStatusTransitionPlan.model_validate(
            {
                **payload,
                "target_status_record": target_status_record,
            }
        )


def test_feature_graph_review_status_transition_plan_rejects_transition_for_gate_decision() -> None:
    payload = _artifact_payload("feature_graph_review_status_transition_plan.v1.json")

    with pytest.raises(
        ValidationError,
        match="transition_status action requires merge, rework, or blocked decision",
    ):
        FeatureGraphReviewStatusTransitionPlan.model_validate(
            {
                **payload,
                "decision": "patch_forward",
            }
        )


def test_feature_graph_review_status_transition_plan_rejects_decision_target_mismatch() -> None:
    payload = _artifact_payload("feature_graph_review_status_transition_plan.v1.json")
    target_status_record = {
        **payload["target_status_record"],
        "status": "blocked",
    }

    with pytest.raises(ValidationError, match="target_status must match review decision"):
        FeatureGraphReviewStatusTransitionPlan.model_validate(
            {
                **payload,
                "target_status": "blocked",
                "target_status_record": target_status_record,
            }
        )


def test_feature_graph_review_status_transition_plan_requires_reviewing_source_status() -> None:
    payload = _artifact_payload("feature_graph_review_status_transition_plan.v1.json")

    with pytest.raises(ValidationError, match="review transition plans require reviewing status"):
        FeatureGraphReviewStatusTransitionPlan.model_validate(
            {
                **payload,
                "current_status": "running",
                "expected_status": "running",
            }
        )


def test_feature_graph_blocked_review_plan_requires_missing_inputs() -> None:
    plan = FeatureGraphBlockedReviewPlan.model_validate(
        _artifact_payload("feature_graph_blocked_review_plan.v1.json")
    )

    assert plan.missing_inputs == ["Codex CLI resume smoke evidence"]

    with pytest.raises(ValidationError, match="missing_inputs must contain at least one item"):
        FeatureGraphBlockedReviewPlan.model_validate(
            {
                **plan.model_dump(mode="json"),
                "missing_inputs": [],
            }
        )


def test_feature_graph_patch_forward_gate_result_fixture_is_stable() -> None:
    result = FeatureGraphPatchForwardGateResult.model_validate(
        _artifact_payload("feature_graph_patch_forward_gate_result.v1.json")
    )

    assert result.plan_id == "fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021600z"
    assert result.changed_file_refs == ["src/xmuse_core/agents/provider_session_binding.py"]
    assert result.lines_changed == 3
    assert result.passed is True
    assert result.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_gate_result.v1.json"
    )

    with pytest.raises(
        ValidationError,
        match="failed patch-forward gate results require failure_reasons",
    ):
        FeatureGraphPatchForwardGateResult.model_validate(
            {
                **result.model_dump(mode="json"),
                "passed": False,
                "failure_reasons": [],
            }
        )


def test_feature_graph_patch_forward_merge_guard_handoff_fixture_is_stable() -> None:
    handoff = FeatureGraphPatchForwardMergeGuardHandoff.model_validate(
        _artifact_payload("feature_graph_patch_forward_merge_guard_handoff.v1.json")
    )

    assert handoff.gate_result_id == (
        "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    )
    assert handoff.merge_guard_input_refs == [
        "feature_graph_patch_forward_gate_result:"
        "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z:v1",
        "diffs/patch-forward/provider-session-binding.diff",
        "logs/gates/provider-binding-patch-forward.json",
    ]
    assert "run_standard_feature_merge_guard" in handoff.required_merge_guard_checks
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_merge_guard_handoff.v1.json"
    )

    with pytest.raises(
        ValidationError,
        match="merge_guard_input_refs must contain at least one item",
    ):
        FeatureGraphPatchForwardMergeGuardHandoff.model_validate(
            {
                **handoff.model_dump(mode="json"),
                "merge_guard_input_refs": [],
            }
        )


def test_feature_graph_patch_forward_merge_guard_decision_fixture_is_stable() -> None:
    decision = FeatureGraphPatchForwardMergeGuardDecision.model_validate(
        _artifact_payload("feature_graph_patch_forward_merge_guard_decision.v1.json")
    )

    assert decision.handoff_id == (
        "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z"
    )
    assert decision.merge_guard_ref == "logs/merge_guard/provider-binding-patch-forward.json"
    assert decision.passed is True
    assert decision.model_dump(mode="json") == _artifact_payload(
        "feature_graph_patch_forward_merge_guard_decision.v1.json"
    )

    with pytest.raises(
        ValidationError,
        match="failed patch-forward merge guard decisions require reasons",
    ):
        FeatureGraphPatchForwardMergeGuardDecision.model_validate(
            {
                **decision.model_dump(mode="json"),
                "passed": False,
                "failure_reasons": [],
            }
        )


def test_feature_graph_takeover_plan_requires_triggered_reason() -> None:
    plan = FeatureGraphTakeoverPlan.model_validate(
        _artifact_payload("feature_graph_takeover_plan.v1.json")
    )

    assert plan.takeover_triggers == ["worker_unrecoverable", "context_lost"]
    assert plan.failed_worker_session_id == "god-worker-demo"

    with pytest.raises(ValidationError, match="takeover_triggers must contain at least one item"):
        FeatureGraphTakeoverPlan.model_validate(
            {
                **plan.model_dump(mode="json"),
                "takeover_triggers": [],
            }
        )


def test_feature_graph_takeover_decision_fixture_is_stable() -> None:
    decision = FeatureGraphTakeoverDecision.model_validate(
        _artifact_payload("feature_graph_takeover_decision.v1.json")
    )

    assert decision.approved is True
    assert decision.takeover_worker_session_id == "god-takeover-worker-demo"
    assert decision.gate_refs == [
        (
            "feature_graph_takeover_plan:fgtakeover:fverdict_takeover_demo:"
            "fevb_demo:20260603T022000z:v1"
        ),
        "logs/takeover/provider-binding-takeover-gate.json",
    ]
    assert decision.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_decision.v1.json"
    )

    with pytest.raises(
        ValidationError,
        match="approved takeover decisions require gate_refs",
    ):
        FeatureGraphTakeoverDecision.model_validate(
            {
                **decision.model_dump(mode="json"),
                "gate_refs": [],
            }
        )


def test_feature_graph_takeover_handoff_fixture_is_stable() -> None:
    handoff = FeatureGraphTakeoverHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_handoff.v1.json")
    )

    assert handoff.decision_id == (
        "fgtd:fgtakeover:fverdict_takeover_demo:fevb_demo:"
        "20260603T022000z:20260603T022300z"
    )
    assert handoff.required_takeover_checks == [
        "verify_takeover_decision_approved",
        "verify_takeover_worker_session_binding",
        "verify_takeover_worktree_lease",
        "verify_failed_worker_is_not_resumed",
    ]
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_handoff.v1.json"
    )

    with pytest.raises(ValidationError, match="takeover_input_refs must contain"):
        FeatureGraphTakeoverHandoff.model_validate(
            {
                **handoff.model_dump(mode="json"),
                "takeover_input_refs": [],
            }
        )


def test_feature_graph_takeover_outcome_fixture_is_stable() -> None:
    outcome = FeatureGraphTakeoverOutcome.model_validate(
        _artifact_payload("feature_graph_takeover_outcome.v1.json")
    )

    assert outcome.completed is True
    assert outcome.evidence_refs == [
        "feature_evidence_bundle:fevb_takeover_provider_binding:v1",
        "diffs/takeover/provider-session-binding.diff",
    ]
    assert outcome.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_outcome.v1.json"
    )

    with pytest.raises(ValidationError, match="failed takeover outcomes require"):
        FeatureGraphTakeoverOutcome.model_validate(
            {
                **outcome.model_dump(mode="json"),
                "completed": False,
                "failure_reasons": [],
            }
        )


def test_feature_graph_takeover_review_handoff_fixture_is_stable() -> None:
    handoff = FeatureGraphTakeoverReviewHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_review_handoff.v1.json")
    )

    assert handoff.outcome_id == (
        "fgto:fgth:fgtd:fgtakeover:fverdict_takeover_demo:fevb_demo:"
        "20260603T022000z:20260603T022300z:20260603T022900z"
    )
    assert handoff.required_review_checks[-1] == (
        "decide_merge_rework_patch_forward_or_blocked"
    )
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_review_handoff.v1.json"
    )

    with pytest.raises(ValidationError, match="reviewer_input_refs must contain"):
        FeatureGraphTakeoverReviewHandoff.model_validate(
            {
                **handoff.model_dump(mode="json"),
                "reviewer_input_refs": [],
            }
        )


def test_feature_graph_takeover_followup_review_application_fixture_is_stable() -> None:
    application = FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
        _artifact_payload("feature_graph_takeover_followup_review_application.v1.json")
    )

    assert application.verdict_id == "fverdict_takeover_followup_merge"
    assert application.review_plan.current_status == "reviewing"
    assert application.applied_status is not None
    assert application.applied_status.status == "merged"
    assert application.output_refs[-1].startswith("feature_graph_status:")
    assert application.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_followup_review_application.v1.json"
    )

    with pytest.raises(ValidationError, match="transition applications require applied_status"):
        FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
            {
                **application.model_dump(mode="json"),
                "applied_status": None,
            }
        )
    with pytest.raises(ValidationError, match="non-rework applications must not carry"):
        FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
            {
                **application.model_dump(mode="json"),
                "rework_id": "rework:unexpected",
            }
        )
    with pytest.raises(ValidationError, match="input_refs must include"):
        FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
            {
                **application.model_dump(mode="json"),
                "input_refs": [
                    ref
                    for ref in application.input_refs
                    if not ref.startswith("feature_review_verdict:")
                ],
            }
        )
    with pytest.raises(ValidationError, match="output_refs must include"):
        FeatureGraphTakeoverFollowupReviewApplicationRecord.model_validate(
            {
                **application.model_dump(mode="json"),
                "output_refs": [
                    ref
                    for ref in application.output_refs
                    if not ref.startswith("feature_graph_status:")
                ],
            }
        )


def test_feature_review_contracts_are_reexported_from_structuring_models() -> None:
    from xmuse_core.structuring import models

    assert models.FeatureEvidenceBundle is FeatureEvidenceBundle
    assert models.FeatureGraphBlockedReviewPlan is FeatureGraphBlockedReviewPlan
    assert models.FeatureGraphPatchForwardGateResult is FeatureGraphPatchForwardGateResult
    assert (
        models.FeatureGraphPatchForwardMergeGuardDecision
        is FeatureGraphPatchForwardMergeGuardDecision
    )
    assert (
        models.FeatureGraphPatchForwardMergeGuardHandoff
        is FeatureGraphPatchForwardMergeGuardHandoff
    )
    assert models.FeatureGraphPatchForwardPlan is FeatureGraphPatchForwardPlan
    assert models.FeatureGraphReviewStatusTransitionPlan is FeatureGraphReviewStatusTransitionPlan
    assert models.FeatureReviewVerdict is FeatureReviewVerdict
    assert models.FeatureGraphTakeoverDecision is FeatureGraphTakeoverDecision
    assert models.FeatureGraphTakeoverHandoff is FeatureGraphTakeoverHandoff
    assert models.FeatureGraphTakeoverOutcome is FeatureGraphTakeoverOutcome
    assert models.FeatureGraphTakeoverPlan is FeatureGraphTakeoverPlan
    assert models.FeatureGraphTakeoverReviewHandoff is FeatureGraphTakeoverReviewHandoff
    assert (
        models.FeatureGraphTakeoverFollowupReviewApplicationRecord
        is FeatureGraphTakeoverFollowupReviewApplicationRecord
    )
    assert (
        models.FeatureGraphWorkerEvidenceSubmissionPlan
        is FeatureGraphWorkerEvidenceSubmissionPlan
    )
    assert models.ReworkPacket is ReworkPacket
    assert models.ProviderSessionBindingRecord is ProviderSessionBindingRecord
    assert (
        models.ProviderSessionBindingDegradationEvidence
        is ProviderSessionBindingDegradationEvidence
    )
    assert models.FeatureGraphExecutionStatusRecord is FeatureGraphExecutionStatusRecord
    assert models.FeatureGraphStatusEventRecord is FeatureGraphStatusEventRecord
