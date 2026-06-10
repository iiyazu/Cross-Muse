from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.review_rework import (
    classify_review_rework_lane,
    classify_review_rework_lanes,
)


def test_positive_review_decision_text_classifies_as_approved_review() -> None:
    summary = classify_review_rework_lane(
        {
            "feature_id": "lane-approved",
            "status": "reworking",
            "retry_count": 1,
            "review_retry_count": 2,
            "review_decision": "rework",
            "review_summary": "Review decision: no blocking findings",
            "review_fallback_reason": "unknown_review_text",
        }
    )

    assert summary == {
        "lane_id": "lane-approved",
        "status": "reworking",
        "reason_category": "approved_review",
        "retry_count": 1,
        "review_retry_count": 2,
        "fallback_reason": "unknown_review_text",
        "primary_evidence_refs": ["lane.review_summary"],
    }


def test_positive_fallback_reasons_are_approved_not_semantic_rework() -> None:
    for reason in (
        "verdict_merge",
        "explicit_merge_decision",
        "positive_no_blocking",
        "positive_no_findings",
    ):
        summary = classify_review_rework_lane(
            {
                "feature_id": f"lane-{reason}",
                "status": "reworking",
                "review_decision": "rework",
                "review_fallback_reason": reason,
            }
        )

        assert summary["reason_category"] == "approved_review"
        assert summary["fallback_reason"] == reason
        assert summary["primary_evidence_refs"] == ["lane.review_fallback_reason"]


def test_rework_fallback_reason_classifies_as_semantic_rework() -> None:
    summary = classify_review_rework_lane(
        {
            "feature_id": "lane-real-rework",
            "status": "reworking",
            "retry_count": 2,
            "review_decision": "rework",
            "review_fallback_reason": "reproduced_finding",
            "review_summary": "High: retry loop still reproduces the failure.",
        }
    )

    assert summary["reason_category"] == "semantic_rework"
    assert summary["primary_evidence_refs"] == [
        "lane.review_fallback_reason",
        "lane.review_summary",
    ]


def test_unknown_review_text_without_persisted_fallback_fails_safe_to_rework() -> None:
    summary = classify_review_rework_lane(
        {
            "feature_id": "lane-unknown-review",
            "status": "reworking",
            "review_summary": (
                "I reviewed the lane and have several notes below.\n"
                "The current implementation changes lifecycle behavior."
            ),
        }
    )

    assert summary["reason_category"] == "semantic_rework"
    assert summary["fallback_reason"] == "unknown_review_text"
    assert summary["primary_evidence_refs"] == ["lane.review_summary"]


def test_lane_context_positive_review_text_is_bounded_approved_evidence(
    tmp_path: Path,
) -> None:
    lane = {
        "feature_id": "lane-context-approved",
        "status": "reworking",
        "review_decision": "rework",
        "lane_context_ref": "logs/lane_context/lane-context-approved/latest.json",
    }
    context_path = tmp_path / "logs" / "lane_context" / "lane-context-approved" / "latest.json"
    context_path.parent.mkdir(parents=True)
    context_path.write_text(
        json.dumps(
            {
                "review_summary": "Review decision: no blocking findings",
                "retry_context": "Review decision: no blocking findings",
            }
        ),
        encoding="utf-8",
    )

    summary = classify_review_rework_lane(lane, xmuse_root=tmp_path)

    assert summary["reason_category"] == "approved_review"
    assert summary["fallback_reason"] == "positive_no_blocking"
    assert summary["primary_evidence_refs"] == [
        "lane.lane_context_ref",
        "logs/lane_context/lane-context-approved/latest.json",
    ]


def test_infra_and_gate_failures_classify_from_lane_metadata() -> None:
    review_infra = classify_review_rework_lane(
        {
            "feature_id": "lane-review-infra",
            "status": "gate_failed",
            "failure_reason": "review_infra_unavailable",
            "review_infra_reason": "usage_limit",
        }
    )
    execution_infra = classify_review_rework_lane(
        {
            "feature_id": "lane-exec-infra",
            "status": "exec_failed",
            "failure_reason": "execution_infra_unavailable",
        }
    )
    gate_failure = classify_review_rework_lane(
        {
            "feature_id": "lane-gate",
            "status": "gate_failed",
            "failure_reason": "gate_failed",
        }
    )

    assert review_infra["reason_category"] == "review_infra"
    assert review_infra["primary_evidence_refs"] == [
        "lane.failure_reason",
        "lane.review_infra_reason",
    ]
    assert execution_infra["reason_category"] == "execution_infra"
    assert execution_infra["primary_evidence_refs"] == ["lane.failure_reason"]
    assert gate_failure["reason_category"] == "gate_failure"
    assert gate_failure["primary_evidence_refs"] == ["lane.failure_reason"]


def test_gate_report_ref_is_bounded_read_only_evidence(tmp_path: Path) -> None:
    lane = {
        "feature_id": "lane-with-gate-report",
        "status": "gate_failed",
        "gate_report_ref": "logs/gates/lane-with-gate-report/report.json",
    }
    report_path = tmp_path / "logs" / "gates" / "lane-with-gate-report" / "report.json"
    report_path.parent.mkdir(parents=True)
    report_path.write_text(
        json.dumps({"passed": False, "blocking_passed": False}),
        encoding="utf-8",
    )
    lanes_path = tmp_path / "feature_lanes.json"
    original = {"lanes": [lane]}
    lanes_path.write_text(json.dumps(original), encoding="utf-8")

    summary = classify_review_rework_lane(lane, xmuse_root=tmp_path)

    assert summary["reason_category"] == "gate_failure"
    assert summary["primary_evidence_refs"] == [
        "lane.gate_report_ref",
        "logs/gates/lane-with-gate-report/report.json",
    ]
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original


def test_not_review_related_and_unknown_are_distinct() -> None:
    pending = classify_review_rework_lane(
        {"feature_id": "lane-pending", "status": "pending"}
    )
    historical_failure = classify_review_rework_lane(
        {"feature_id": "lane-historical", "status": "failed", "retry_count": 3}
    )

    assert pending["reason_category"] == "not_review_related"
    assert historical_failure["reason_category"] == "unknown"


def test_classify_review_rework_lanes_returns_compact_summaries() -> None:
    summaries = classify_review_rework_lanes(
        [
            {"feature_id": "lane-1", "status": "reviewed", "review_decision": "merge"},
            {"feature_id": "lane-2", "status": "pending"},
        ]
    )

    assert [item["lane_id"] for item in summaries] == ["lane-1", "lane-2"]
    assert [item["reason_category"] for item in summaries] == [
        "approved_review",
        "not_review_related",
    ]
