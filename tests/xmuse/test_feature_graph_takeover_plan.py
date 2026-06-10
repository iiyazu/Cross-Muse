from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_takeover_plan import (
    build_feature_graph_takeover_decision,
    build_feature_graph_takeover_handoff,
    build_feature_graph_takeover_outcome,
    build_feature_graph_takeover_plan,
    build_feature_graph_takeover_review_handoff,
    validate_feature_graph_takeover_followup_verdict,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphTakeoverDecision,
    FeatureGraphTakeoverHandoff,
    FeatureGraphTakeoverOutcome,
    FeatureGraphTakeoverPlan,
    FeatureGraphTakeoverReviewHandoff,
    FeatureReviewVerdict,
)

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def _bundle() -> FeatureEvidenceBundle:
    return FeatureEvidenceBundle.model_validate(
        _artifact_payload("feature_evidence_bundle.v1.json")
    )


def _merge_verdict() -> FeatureReviewVerdict:
    return FeatureReviewVerdict.model_validate(_artifact_payload("feature_review_verdict.v1.json"))


def _takeover_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_takeover_demo",
            "decision": "takeover",
            "summary": "Worker session is not recoverable.",
            "takeover_reason": "Provider session binding is stale and worker context is lost.",
            "takeover_triggers": ["worker_unrecoverable", "context_lost"],
        }
    )


def _reviewing_status() -> FeatureGraphExecutionStatusRecord:
    status = FeatureGraphExecutionStatusRecord.model_validate(
        _artifact_payload("feature_graph_status.v1.json")
    )
    return status.model_copy(
        update={
            "status_id": "fgstatus_reviewing_demo",
            "status": FeatureGraphExecutionStatus.REVIEWING,
            "ready_lane_ids": [],
            "active_lane_ids": [],
            "completed_lane_ids": ["binding-schema"],
            "updated_at": "2026-06-03T02:13:30Z",
        }
    )


def test_takeover_verdict_builds_feature_graph_takeover_plan() -> None:
    plan = build_feature_graph_takeover_plan(
        evidence_bundle=_bundle(),
        verdict=_takeover_verdict(),
        current_status=_reviewing_status(),
        plan_id="fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T022000z",
        created_at="2026-06-03T02:20:00Z",
    )

    assert plan.current_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.expected_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.takeover_triggers == ["worker_unrecoverable", "context_lost"]
    assert plan.failed_worker_session_id == "god-worker-demo"
    assert plan.failed_provider_session_binding_ref == "provider_session_binding:psb_demo:v1"
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_plan.v1.json"
    )


def test_takeover_plan_fixture_is_stable() -> None:
    plan = FeatureGraphTakeoverPlan.model_validate(
        _artifact_payload("feature_graph_takeover_plan.v1.json")
    )

    assert plan.plan_id == "fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T022000z"
    assert plan.takeover_reason == "Provider session binding is stale and worker context is lost."
    assert plan.takeover_triggers == ["worker_unrecoverable", "context_lost"]
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_plan.v1.json"
    )


def test_takeover_plan_builds_approved_takeover_decision() -> None:
    decision = build_feature_graph_takeover_decision(
        plan=FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        ),
        decision_id=(
            "fgtd:fgtakeover:fverdict_takeover_demo:fevb_demo:"
            "20260603T022000z:20260603T022300z"
        ),
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref=(
            "provider_session_binding:psb_takeover_demo:v1"
        ),
        gate_refs=[
            (
                "feature_graph_takeover_plan:fgtakeover:fverdict_takeover_demo:"
                "fevb_demo:20260603T022000z:v1"
            ),
            "logs/takeover/provider-binding-takeover-gate.json",
        ],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )

    assert decision.approved is True
    assert decision.takeover_worker_session_id == "god-takeover-worker-demo"
    assert decision.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_decision.v1.json"
    )


def test_takeover_decision_fixture_is_stable() -> None:
    decision = FeatureGraphTakeoverDecision.model_validate(
        _artifact_payload("feature_graph_takeover_decision.v1.json")
    )

    assert decision.approved is True
    assert decision.plan_id == "fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T022000z"
    assert decision.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_decision.v1.json"
    )


def test_takeover_decision_builds_takeover_handoff() -> None:
    decision = FeatureGraphTakeoverDecision.model_validate(
        _artifact_payload("feature_graph_takeover_decision.v1.json")
    )

    handoff = build_feature_graph_takeover_handoff(
        decision=decision,
        handoff_id=(
            "fgth:fgtd:fgtakeover:fverdict_takeover_demo:fevb_demo:"
            "20260603T022000z:20260603T022300z"
        ),
        decision_ref=(
            "feature_graph_takeover_decision:fgtd:fgtakeover:"
            "fverdict_takeover_demo:fevb_demo:20260603T022000z:"
            "20260603T022300z:v1"
        ),
        created_at="2026-06-03T02:23:00Z",
    )

    assert handoff.takeover_worker_session_id == "god-takeover-worker-demo"
    assert handoff.required_takeover_checks == [
        "verify_takeover_decision_approved",
        "verify_takeover_worker_session_binding",
        "verify_takeover_worktree_lease",
        "verify_failed_worker_is_not_resumed",
    ]
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_handoff.v1.json"
    )


def test_takeover_handoff_fixture_is_stable() -> None:
    handoff = FeatureGraphTakeoverHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_handoff.v1.json")
    )

    assert handoff.decision_id == (
        "fgtd:fgtakeover:fverdict_takeover_demo:fevb_demo:"
        "20260603T022000z:20260603T022300z"
    )
    assert handoff.takeover_input_refs[-1] == "provider_session_binding:psb_takeover_demo:v1"
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_handoff.v1.json"
    )


def test_takeover_handoff_builds_completed_takeover_outcome() -> None:
    handoff = FeatureGraphTakeoverHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_handoff.v1.json")
    )

    outcome = build_feature_graph_takeover_outcome(
        handoff=handoff,
        outcome_id=(
            "fgto:fgth:fgtd:fgtakeover:fverdict_takeover_demo:fevb_demo:"
            "20260603T022000z:20260603T022300z:20260603T022900z"
        ),
        changed_file_refs=[
            "src/xmuse_core/providers/adapters/codex.py",
            "tests/xmuse/test_provider_codex_retrofit.py",
        ],
        evidence_refs=[
            "feature_evidence_bundle:fevb_takeover_provider_binding:v1",
            "diffs/takeover/provider-session-binding.diff",
        ],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary=(
            "Recovered provider session binding command planning and reran focused gates."
        ),
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )

    assert outcome.completed is True
    assert outcome.takeover_worker_session_id == handoff.takeover_worker_session_id
    assert outcome.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_outcome.v1.json"
    )


def test_takeover_outcome_fixture_is_stable() -> None:
    outcome = FeatureGraphTakeoverOutcome.model_validate(
        _artifact_payload("feature_graph_takeover_outcome.v1.json")
    )

    assert outcome.completed is True
    assert outcome.verification_refs == ["logs/takeover/provider-binding-focused-gates.json"]
    assert outcome.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_outcome.v1.json"
    )


def test_takeover_outcome_allows_failed_result_with_reason() -> None:
    handoff = FeatureGraphTakeoverHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_handoff.v1.json")
    )

    outcome = build_feature_graph_takeover_outcome(
        handoff=handoff,
        outcome_id="fgto:failed",
        changed_file_refs=[],
        evidence_refs=[],
        verification_refs=[],
        output_summary="Takeover worker could not acquire a compatible worktree lease.",
        completed=False,
        failure_reasons=["takeover worktree lease unavailable"],
        created_at="2026-06-03T02:30:00Z",
    )

    assert outcome.completed is False
    assert outcome.failure_reasons == ["takeover worktree lease unavailable"]


def test_takeover_outcome_rejects_completed_without_verification() -> None:
    handoff = FeatureGraphTakeoverHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_handoff.v1.json")
    )

    with pytest.raises(ValueError, match="completed takeover outcomes require verification_refs"):
        build_feature_graph_takeover_outcome(
            handoff=handoff,
            outcome_id="fgto:missing-verification",
            changed_file_refs=[],
            evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
            verification_refs=[],
            output_summary="Missing verification should be rejected.",
            completed=True,
            failure_reasons=None,
            created_at="2026-06-03T02:30:00Z",
        )


def test_takeover_outcome_builds_review_handoff() -> None:
    outcome = FeatureGraphTakeoverOutcome.model_validate(
        _artifact_payload("feature_graph_takeover_outcome.v1.json")
    )

    handoff = build_feature_graph_takeover_review_handoff(
        outcome=outcome,
        review_handoff_id=(
            "fgtrh:fgto:fgth:fgtd:fgtakeover:fverdict_takeover_demo:"
            "fevb_demo:20260603T022000z:20260603T022300z:20260603T022900z"
        ),
        outcome_ref=(
            "feature_graph_takeover_outcome:fgto:fgth:fgtd:fgtakeover:"
            "fverdict_takeover_demo:fevb_demo:20260603T022000z:"
            "20260603T022300z:20260603T022900z:v1"
        ),
        created_at="2026-06-03T02:29:00Z",
    )

    assert handoff.outcome_id == outcome.outcome_id
    assert handoff.required_review_checks == [
        "review_takeover_output_against_original_evidence",
        "verify_takeover_changes_match_feature_scope",
        "verify_takeover_focused_gates",
        "decide_merge_rework_patch_forward_or_blocked",
    ]
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_review_handoff.v1.json"
    )


def test_takeover_review_handoff_fixture_is_stable() -> None:
    handoff = FeatureGraphTakeoverReviewHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_review_handoff.v1.json")
    )

    assert handoff.reviewer_input_refs[0].startswith("feature_graph_takeover_outcome:")
    assert handoff.model_dump(mode="json") == _artifact_payload(
        "feature_graph_takeover_review_handoff.v1.json"
    )


def test_takeover_review_handoff_rejects_failed_outcome() -> None:
    handoff = FeatureGraphTakeoverHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_handoff.v1.json")
    )
    failed = build_feature_graph_takeover_outcome(
        handoff=handoff,
        outcome_id="fgto:failed",
        changed_file_refs=[],
        evidence_refs=[],
        verification_refs=[],
        output_summary="Takeover worker could not acquire a compatible lease.",
        completed=False,
        failure_reasons=["takeover worktree lease unavailable"],
        created_at="2026-06-03T02:30:00Z",
    )

    with pytest.raises(ValueError, match="takeover review handoff requires completed outcome"):
        build_feature_graph_takeover_review_handoff(
            outcome=failed,
            review_handoff_id="fgtrh:failed",
            outcome_ref="feature_graph_takeover_outcome:fgto:failed:v1",
            created_at="2026-06-03T02:30:00Z",
        )


def test_takeover_review_handoff_accepts_followup_merge_verdict() -> None:
    handoff = FeatureGraphTakeoverReviewHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_review_handoff.v1.json")
    )
    verdict = _merge_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_merge",
            "evidence_refs": list(handoff.reviewer_input_refs),
        }
    )

    validated = validate_feature_graph_takeover_followup_verdict(
        handoff=handoff,
        evidence_bundle=_bundle(),
        verdict=verdict,
    )

    assert validated.verdict_id == "fverdict_takeover_followup_merge"
    assert validated.evidence_refs == handoff.reviewer_input_refs


def test_takeover_followup_verdict_must_cite_reviewer_inputs() -> None:
    handoff = FeatureGraphTakeoverReviewHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_review_handoff.v1.json")
    )
    verdict = _merge_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_missing_refs",
            "evidence_refs": ["logs/review/missing-takeover-outcome.json"],
        }
    )

    with pytest.raises(ValueError, match="must cite reviewer_input_refs"):
        validate_feature_graph_takeover_followup_verdict(
            handoff=handoff,
            evidence_bundle=_bundle(),
            verdict=verdict,
        )


def test_takeover_followup_verdict_rejects_second_takeover_request() -> None:
    handoff = FeatureGraphTakeoverReviewHandoff.model_validate(
        _artifact_payload("feature_graph_takeover_review_handoff.v1.json")
    )
    verdict = _takeover_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_takeover_again",
            "evidence_refs": list(handoff.reviewer_input_refs),
        }
    )

    with pytest.raises(ValueError, match="must not request another takeover"):
        validate_feature_graph_takeover_followup_verdict(
            handoff=handoff,
            evidence_bundle=_bundle(),
            verdict=verdict,
        )


def test_takeover_decision_allows_rejected_gate_with_reason() -> None:
    decision = build_feature_graph_takeover_decision(
        plan=FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        ),
        decision_id="fgtd:rejected",
        approved=False,
        takeover_worker_session_id=None,
        takeover_provider_session_binding_ref=None,
        gate_refs=["logs/takeover/rejected.json"],
        failure_reasons=["takeover worker lease unavailable"],
        checked_at="2026-06-03T02:23:00Z",
    )

    assert decision.approved is False
    assert decision.failure_reasons == ["takeover worker lease unavailable"]
    assert decision.takeover_worker_session_id is None


def test_takeover_handoff_rejects_rejected_decision() -> None:
    decision = build_feature_graph_takeover_decision(
        plan=FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        ),
        decision_id="fgtd:rejected",
        approved=False,
        takeover_worker_session_id=None,
        takeover_provider_session_binding_ref=None,
        gate_refs=["logs/takeover/rejected.json"],
        failure_reasons=["takeover worker lease unavailable"],
        checked_at="2026-06-03T02:23:00Z",
    )

    with pytest.raises(ValueError, match="takeover handoff requires approved decision"):
        build_feature_graph_takeover_handoff(
            decision=decision,
            handoff_id="fgth:rejected",
            decision_ref="feature_graph_takeover_decision:fgtd:rejected:v1",
            created_at="2026-06-03T02:23:00Z",
        )


def test_takeover_decision_rejects_approved_without_gate_refs() -> None:
    with pytest.raises(ValueError, match="approved takeover decisions require gate_refs"):
        build_feature_graph_takeover_decision(
            plan=FeatureGraphTakeoverPlan.model_validate(
                _artifact_payload("feature_graph_takeover_plan.v1.json")
            ),
            decision_id="fgtd:missing-gates",
            approved=True,
            takeover_worker_session_id="god-takeover-worker-demo",
            takeover_provider_session_binding_ref=(
                "provider_session_binding:psb_takeover_demo:v1"
            ),
            gate_refs=[],
            failure_reasons=None,
            checked_at="2026-06-03T02:23:00Z",
        )


def test_takeover_decision_rejects_failed_without_reason() -> None:
    with pytest.raises(ValueError, match="rejected takeover decisions require failure_reasons"):
        build_feature_graph_takeover_decision(
            plan=FeatureGraphTakeoverPlan.model_validate(
                _artifact_payload("feature_graph_takeover_plan.v1.json")
            ),
            decision_id="fgtd:rejected-no-reason",
            approved=False,
            takeover_worker_session_id=None,
            takeover_provider_session_binding_ref=None,
            gate_refs=["logs/takeover/rejected.json"],
            failure_reasons=[],
            checked_at="2026-06-03T02:23:00Z",
        )


def test_takeover_verdict_requires_takeover_triggers() -> None:
    payload = _takeover_verdict().model_dump(mode="json")

    with pytest.raises(ValueError, match="takeover verdicts require takeover_triggers"):
        FeatureReviewVerdict.model_validate({**payload, "takeover_triggers": []})


def test_takeover_builder_rejects_non_takeover_verdict() -> None:
    with pytest.raises(ValueError, match="takeover plan requires takeover verdict"):
        build_feature_graph_takeover_plan(
            evidence_bundle=_bundle(),
            verdict=_merge_verdict(),
            current_status=_reviewing_status(),
            plan_id="fgtakeover:fverdict_merge_demo:fevb_demo:20260603T022000z",
            created_at="2026-06-03T02:20:00Z",
        )


def test_takeover_builder_requires_reviewing_status() -> None:
    running = _reviewing_status().model_copy(
        update={"status": FeatureGraphExecutionStatus.RUNNING}
    )

    with pytest.raises(ValueError, match="takeover plan requires reviewing status"):
        build_feature_graph_takeover_plan(
            evidence_bundle=_bundle(),
            verdict=_takeover_verdict(),
            current_status=running,
            plan_id="fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T022000z",
            created_at="2026-06-03T02:20:00Z",
        )


def test_takeover_builder_rejects_mismatched_artifacts() -> None:
    mismatched_bundle = _bundle().model_copy(update={"bundle_id": "other-bundle"})

    with pytest.raises(ValueError, match="verdict evidence_bundle_id must match bundle_id"):
        build_feature_graph_takeover_plan(
            evidence_bundle=mismatched_bundle,
            verdict=_takeover_verdict(),
            current_status=_reviewing_status(),
            plan_id="fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T022000z",
            created_at="2026-06-03T02:20:00Z",
        )
