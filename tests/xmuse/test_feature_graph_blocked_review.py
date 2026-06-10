from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.structuring.feature_graph_blocked_review import (
    build_feature_graph_blocked_review_plan,
)
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphBlockedReviewPlan,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
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


def _blocked_verdict() -> FeatureReviewVerdict:
    merge = _merge_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_blocked_demo",
            "decision": "blocked",
            "summary": "Cannot review without provider CLI resume behavior evidence.",
            "blocked_missing_inputs": ["Codex CLI resume smoke evidence"],
            "blocked_reason": "Need Codex CLI resume smoke evidence.",
            "blocked_owner": "coordinator",
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


def test_blocked_verdict_builds_blocked_review_plan() -> None:
    plan = build_feature_graph_blocked_review_plan(
        evidence_bundle=_bundle(),
        verdict=_blocked_verdict(),
        current_status=_reviewing_status(),
        plan_id="fgblocked:fverdict_blocked_demo:fevb_demo:20260603T021700z",
        created_at="2026-06-03T02:17:00Z",
    )

    assert plan.verdict_id == "fverdict_blocked_demo"
    assert plan.current_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.expected_status is FeatureGraphExecutionStatus.REVIEWING
    assert plan.target_status is FeatureGraphExecutionStatus.BLOCKED
    assert plan.missing_inputs == ["Codex CLI resume smoke evidence"]
    assert plan.blocked_reason == "Need Codex CLI resume smoke evidence."
    assert plan.blocked_owner == "coordinator"
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_blocked_review_plan.v1.json"
    )


def test_blocked_review_plan_fixture_is_stable() -> None:
    plan = FeatureGraphBlockedReviewPlan.model_validate(
        _artifact_payload("feature_graph_blocked_review_plan.v1.json")
    )

    assert plan.plan_id == "fgblocked:fverdict_blocked_demo:fevb_demo:20260603T021700z"
    assert plan.target_status is FeatureGraphExecutionStatus.BLOCKED
    assert plan.missing_inputs == ["Codex CLI resume smoke evidence"]
    assert plan.blocked_owner == "coordinator"
    assert plan.model_dump(mode="json") == _artifact_payload(
        "feature_graph_blocked_review_plan.v1.json"
    )


def test_blocked_verdict_requires_missing_inputs() -> None:
    payload = _blocked_verdict().model_dump(mode="json")

    with pytest.raises(ValueError, match="blocked verdicts require blocked_missing_inputs"):
        FeatureReviewVerdict.model_validate({**payload, "blocked_missing_inputs": []})


def test_blocked_review_builder_rejects_non_blocked_verdict() -> None:
    with pytest.raises(ValueError, match="blocked review plan requires blocked verdict"):
        build_feature_graph_blocked_review_plan(
            evidence_bundle=_bundle(),
            verdict=_merge_verdict(),
            current_status=_reviewing_status(),
            plan_id="fgblocked:fverdict_merge_demo:fevb_demo:20260603T021700z",
            created_at="2026-06-03T02:17:00Z",
        )


def test_blocked_review_builder_requires_reviewing_status() -> None:
    running = _reviewing_status().model_copy(
        update={"status": FeatureGraphExecutionStatus.RUNNING}
    )

    with pytest.raises(ValueError, match="blocked review plan requires reviewing status"):
        build_feature_graph_blocked_review_plan(
            evidence_bundle=_bundle(),
            verdict=_blocked_verdict(),
            current_status=running,
            plan_id="fgblocked:fverdict_blocked_demo:fevb_demo:20260603T021700z",
            created_at="2026-06-03T02:17:00Z",
        )


def test_blocked_review_builder_rejects_mismatched_artifacts() -> None:
    mismatched_bundle = _bundle().model_copy(update={"bundle_id": "other-bundle"})

    with pytest.raises(ValueError, match="verdict evidence_bundle_id must match bundle_id"):
        build_feature_graph_blocked_review_plan(
            evidence_bundle=mismatched_bundle,
            verdict=_blocked_verdict(),
            current_status=_reviewing_status(),
            plan_id="fgblocked:fverdict_blocked_demo:fevb_demo:20260603T021700z",
            created_at="2026-06-03T02:17:00Z",
        )
