from xmuse_core.platform.verdict_adapter import adapt_review_verdict
from xmuse_core.structuring.models import ReviewVerdict


def test_merge_verdict_enters_final_action_hold_when_human_approval_required() -> None:
    verdict = ReviewVerdict(
        id="verdict-1",
        lane_id="lane-1",
        decision="merge",
        status="finalized",
        summary="Core behavior is correct.",
        evidence_refs=["gate://lane-1"],
    )

    result = adapt_review_verdict(
        verdict,
        lane={"feature_id": "lane-1", "prompt": "Implement lane 1"},
        require_final_action_approval=True,
    )

    assert result.transition_status is None
    assert result.final_action is not None
    assert result.final_action.action == "merge"
    assert result.final_action.target_status == "reviewed"


def test_merge_verdict_summary_does_not_claim_merge_truth() -> None:
    verdict = ReviewVerdict(
        id="verdict-merge-boundary",
        lane_id="lane-merge-boundary",
        decision="merge",
        status="finalized",
        summary=(
            "Verdict: merge. Lane reviewed and merged. "
            "ready_to_merge=true; pr_merged=true."
        ),
        evidence_refs=["gate://lane-merge-boundary"],
    )

    result = adapt_review_verdict(
        verdict,
        lane={"feature_id": "lane-merge-boundary", "prompt": "Implement lane"},
        require_final_action_approval=True,
    )

    assert result.final_action is not None
    summary = result.metadata["review_summary"]
    assert result.final_action.summary == summary
    assert "Proof boundary: review acceptance is not merge truth" in summary
    lowered = summary.lower()
    assert "reviewed and merged" not in lowered
    assert "ready_to_merge" not in lowered
    assert "pr_merged" not in lowered
    assert result.metadata["review_history"][-1]["summary"] == summary


def test_rework_verdict_maps_to_rejected_transition() -> None:
    verdict = ReviewVerdict(
        id="verdict-2",
        lane_id="lane-2",
        decision="rework",
        status="finalized",
        summary="Core behavior is incorrect.",
        evidence_refs=["gate://lane-2"],
    )

    result = adapt_review_verdict(
        verdict,
        lane={"feature_id": "lane-2", "prompt": "Implement lane 2"},
        require_final_action_approval=True,
    )

    assert result.transition_status == "rejected"
    assert result.final_action is None
    assert result.metadata["review_decision"] == "rework"
    assert result.metadata["review_summary"] == "Core behavior is incorrect."
    history_entry = result.metadata["review_history"][-1]
    recorded_at = history_entry.pop("recorded_at")
    assert history_entry == {
        "decision": "rework",
        "summary": "Core behavior is incorrect.",
        "fallback": "structured",
        "fallback_reason": "review_verdict",
        "verdict_id": "verdict-2",
    }
    assert isinstance(recorded_at, float)


def test_structured_verdict_appends_existing_review_history() -> None:
    verdict = ReviewVerdict(
        id="verdict-new",
        lane_id="lane-history",
        decision="merge",
        status="finalized",
        summary="Ready now.",
        evidence_refs=["gate://lane-history"],
        created_at="2026-05-30T00:00:00Z",
    )

    result = adapt_review_verdict(
        verdict,
        lane={
            "feature_id": "lane-history",
            "prompt": "Implement lane history",
            "review_history": [
                {
                    "decision": "rework",
                    "summary": "Fix the first issue.",
                    "fallback": "mcp",
                }
            ],
        },
        require_final_action_approval=False,
    )

    assert result.transition_status == "reviewed"
    assert [item["decision"] for item in result.metadata["review_history"]] == [
        "rework",
        "merge",
    ]
    assert result.metadata["review_history"][-1]["recorded_at"] == "2026-05-30T00:00:00Z"


def test_patch_forward_verdict_creates_bounded_followup_lane() -> None:
    verdict = ReviewVerdict(
        id="verdict-3",
        lane_id="lane-3",
        decision="patch-forward",
        status="finalized",
        summary="Core behavior is correct; fix a small dashboard edge case.",
        evidence_refs=["gate://lane-3"],
        patch_instructions="Fix the empty-state rendering bug without broad refactors.",
    )

    result = adapt_review_verdict(
        verdict,
        lane={
            "feature_id": "lane-3",
            "prompt": "Implement lane 3",
            "capabilities": ["code"],
            "conversation_id": "conv-3",
            "resolution_id": "res-3",
            "graph_id": "graph-3",
            "graph_version": 2,
        },
        require_final_action_approval=True,
    )

    assert result.transition_status is None
    assert result.final_action is None
    assert result.patch_lane is not None
    assert result.patch_lane["feature_id"] == "lane-3-patch-forward"
    assert result.patch_lane["source_lane_id"] == "lane-3"
    assert result.patch_lane["conversation_id"] == "conv-3"
    assert result.patch_lane["resolution_id"] == "res-3"
    assert result.patch_lane["graph_id"] == "graph-3"
    assert result.patch_lane["graph_version"] == 2
    assert "Fix the empty-state rendering bug" in result.patch_lane["prompt"]


def test_terminate_verdict_requires_hold_before_failure_transition() -> None:
    verdict = ReviewVerdict(
        id="verdict-4",
        lane_id="lane-4",
        decision="terminate",
        status="finalized",
        summary="Stop this lane.",
        evidence_refs=["gate://lane-4"],
        terminate_reason="Scope is invalid for the current blueprint.",
    )

    result = adapt_review_verdict(
        verdict,
        lane={"feature_id": "lane-4", "prompt": "Implement lane 4"},
        require_final_action_approval=True,
    )

    assert result.transition_status is None
    assert result.final_action is not None
    assert result.final_action.action == "terminate"
    assert result.final_action.target_status == "failed"
