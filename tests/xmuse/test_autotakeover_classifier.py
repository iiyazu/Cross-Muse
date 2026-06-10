from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.platform.autotakeover.classifier import (
    classify_takeover_candidate,
    classify_takeover_candidates,
)
from xmuse_core.platform.state_machine import MAX_RETRIES


def test_classify_takeover_candidate_prefers_explicit_current_reason() -> None:
    summary = classify_takeover_candidate(
        {
            "feature_id": "lane-merge",
            "status": "failed",
            "failure_reason": "merge_failed",
        }
    )

    assert summary == {
        "lane_id": "lane-merge",
        "status": "failed",
        "is_takeover_candidate": True,
        "takeover_reason": "merge_failed",
        "legacy_reason_category": None,
        "retry_count": 0,
        "review_retry_count": 0,
        "primary_evidence_refs": ["lane.failure_reason"],
    }


def test_classify_takeover_candidate_maps_legacy_rework_taxonomy() -> None:
    summary = classify_takeover_candidate(
        {
            "feature_id": "lane-rework",
            "status": "reworking",
            "review_fallback_reason": "reproduced_finding",
            "review_summary": "Blocking: retry loop still reproduces the failure.",
            "retry_count": 1,
        }
    )

    assert summary == {
        "lane_id": "lane-rework",
        "status": "reworking",
        "is_takeover_candidate": True,
        "takeover_reason": "rework_failed",
        "legacy_reason_category": "semantic_rework",
        "retry_count": 1,
        "review_retry_count": 0,
        "primary_evidence_refs": [
            "lane.review_fallback_reason",
            "lane.review_summary",
        ],
    }


def test_classify_takeover_candidate_maps_legacy_review_and_merge_taxonomy() -> None:
    review_failed = classify_takeover_candidate(
        {
            "feature_id": "lane-review",
            "status": "gate_failed",
            "failure_reason": "review_infra_unavailable",
            "review_retry_count": 1,
        }
    )
    merge_failed = classify_takeover_candidate(
        {
            "feature_id": "lane-conflict",
            "status": "reworking",
            "merge_failure_reason": "merge_conflict_or_failed",
            "merge_failure_detail": "CONFLICT (content): src/example.py",
            "retry_count": 1,
        }
    )

    assert review_failed == {
        "lane_id": "lane-review",
        "status": "gate_failed",
        "is_takeover_candidate": True,
        "takeover_reason": "review_failed",
        "legacy_reason_category": "review_infra",
        "retry_count": 0,
        "review_retry_count": 1,
        "primary_evidence_refs": ["lane.failure_reason"],
    }
    assert merge_failed == {
        "lane_id": "lane-conflict",
        "status": "reworking",
        "is_takeover_candidate": True,
        "takeover_reason": "merge_failed",
        "legacy_reason_category": "merge_conflict",
        "retry_count": 1,
        "review_retry_count": 0,
        "primary_evidence_refs": [
            "lane.merge_failure_reason",
            "lane.merge_failure_detail",
        ],
    }


def test_classify_takeover_candidate_maps_review_no_verdict_to_review_failed() -> None:
    summary = classify_takeover_candidate(
        {
            "feature_id": "lane-no-verdict",
            "status": "gate_failed",
            "failure_reason": "review_no_verdict",
            "review_retry_count": 1,
        }
    )

    assert summary == {
        "lane_id": "lane-no-verdict",
        "status": "gate_failed",
        "is_takeover_candidate": True,
        "takeover_reason": "review_failed",
        "legacy_reason_category": "review_infra",
        "retry_count": 0,
        "review_retry_count": 1,
        "primary_evidence_refs": ["lane.failure_reason"],
    }


def test_classify_takeover_candidate_infers_retry_exhaustion_and_gate_failure(
    tmp_path: Path,
) -> None:
    gate_report = tmp_path / "logs" / "gates" / "lane-gate" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(
        json.dumps({"passed": False, "blocking_passed": False}),
        encoding="utf-8",
    )

    retry_exhausted = classify_takeover_candidate(
        {
            "feature_id": "lane-retry",
            "status": "exec_failed",
            "failure_reason": "execution_infra_unavailable",
            "retry_count": MAX_RETRIES,
        }
    )
    gate_failed = classify_takeover_candidate(
        {
            "feature_id": "lane-gate",
            "status": "gate_failed",
            "gate_report_ref": "logs/gates/lane-gate/report.json",
        },
        xmuse_root=tmp_path,
    )

    assert retry_exhausted == {
        "lane_id": "lane-retry",
        "status": "exec_failed",
        "is_takeover_candidate": True,
        "takeover_reason": "retry_exhausted",
        "legacy_reason_category": "execution_infra",
        "retry_count": MAX_RETRIES,
        "review_retry_count": 0,
        "primary_evidence_refs": [
            "lane.retry_count",
            "lane.failure_reason",
        ],
    }
    assert gate_failed == {
        "lane_id": "lane-gate",
        "status": "gate_failed",
        "is_takeover_candidate": True,
        "takeover_reason": "gate_failed",
        "legacy_reason_category": "gate_failure",
        "retry_count": 0,
        "review_retry_count": 0,
        "primary_evidence_refs": [
            "lane.gate_report_ref",
            "logs/gates/lane-gate/report.json",
        ],
    }


def test_classify_takeover_candidate_handles_prompt_mismatch_and_non_candidates() -> None:
    prompt_mismatch = classify_takeover_candidate(
        {
            "feature_id": "lane-prompt",
            "status": "reworking",
            "failure_reason": "prompt_mismatch",
            "review_summary": "Findings: approach targets the wrong subsystem",
        }
    )
    pending = classify_takeover_candidate(
        {"feature_id": "lane-pending", "status": "pending"}
    )

    assert prompt_mismatch == {
        "lane_id": "lane-prompt",
        "status": "reworking",
        "is_takeover_candidate": True,
        "takeover_reason": "prompt_subsystem_mismatch",
        "legacy_reason_category": None,
        "retry_count": 0,
        "review_retry_count": 0,
        "primary_evidence_refs": ["lane.failure_reason"],
    }
    assert pending == {
        "lane_id": "lane-pending",
        "status": "pending",
        "is_takeover_candidate": False,
        "takeover_reason": None,
        "legacy_reason_category": None,
        "retry_count": 0,
        "review_retry_count": 0,
        "primary_evidence_refs": [],
    }


@pytest.mark.parametrize(
    ("status", "failure_reason", "takeover_reason", "review_retry_count"),
    [
        ("failed", "review_failed", "review_failed", 0),
        ("gate_failed", "gate_failed", "gate_failed", 1),
    ],
)
def test_classify_takeover_candidate_keeps_explicit_failed_and_gate_failed_reasons(
    status: str,
    failure_reason: str,
    takeover_reason: str,
    review_retry_count: int,
) -> None:
    summary = classify_takeover_candidate(
        {
            "feature_id": f"lane-{status}",
            "status": status,
            "failure_reason": failure_reason,
            "review_retry_count": review_retry_count,
        }
    )

    assert summary == {
        "lane_id": f"lane-{status}",
        "status": status,
        "is_takeover_candidate": True,
        "takeover_reason": takeover_reason,
        "legacy_reason_category": None,
        "retry_count": 0,
        "review_retry_count": review_retry_count,
        "primary_evidence_refs": ["lane.failure_reason"],
    }


def test_classify_takeover_candidates_preserves_input_order() -> None:
    summaries = classify_takeover_candidates(
        [
            {"feature_id": "lane-1", "status": "failed", "failure_reason": "merge_failed"},
            {"feature_id": "lane-2", "status": "pending"},
        ]
    )

    assert [item["lane_id"] for item in summaries] == ["lane-1", "lane-2"]
    assert [item["takeover_reason"] for item in summaries] == [
        "merge_failed",
        None,
    ]
