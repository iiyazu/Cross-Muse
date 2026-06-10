from __future__ import annotations

from xmuse_core.platform.execution.github_ops import (
    CheckStatus,
    FakeGitHubOps,
    FeatureDraftPRRequest,
    ReviewOutcome,
    WorkerOutcome,
    apply_review_outcome,
    apply_worker_outcome,
    evaluate_merge_readiness,
    render_feature_draft_pr_body,
)


def test_feature_draft_pr_body_contains_required_refs_and_evidence() -> None:
    request = _request()

    body = render_feature_draft_pr_body(request)

    assert "Blueprint Refs" in body
    assert "- `blueprint:bp-1`" in body
    assert "- `lane:lane-1`" in body
    assert "- Focused tests pass." in body
    assert "- `tests/xmuse/test_feature.py::test_feature`" in body
    assert "- `memory://conversation/conv-1/context`" in body
    assert "Parent PR: #42" in body


def test_fake_github_ops_creates_and_updates_feature_draft_pr() -> None:
    ops = FakeGitHubOps()
    request = _request()

    created = ops.create_or_update_feature_draft_pr(request)
    updated = ops.create_or_update_feature_draft_pr(
        request.model_copy(update={"title": "Feature 1 updated"})
    )

    assert created.number == updated.number
    assert created.draft is True
    assert updated.title == "Feature 1 updated"
    assert updated.body == render_feature_draft_pr_body(
        request.model_copy(update={"title": "Feature 1 updated"})
    )


def test_required_checks_not_passing_prevent_merge_ready_status() -> None:
    blocked = evaluate_merge_readiness(
        [
            CheckStatus(name="ruff", status="success"),
            CheckStatus(name="pytest", status="failure"),
        ]
    )
    ready = evaluate_merge_readiness(
        [
            CheckStatus(name="ruff", status="success"),
            CheckStatus(name="pytest", status="success"),
        ]
    )

    assert blocked.merge_ready is False
    assert blocked.reason == "required checks not passing: pytest"
    assert ready.merge_ready is True


def test_worker_failure_transitions_lane_to_blocked() -> None:
    lane = {"lane_id": "lane-1", "status": "running"}

    updated = apply_worker_outcome(
        lane,
        WorkerOutcome(status="failed", summary="pytest failed", evidence_refs=["log:pytest"]),
    )

    assert updated["status"] == "blocked"
    assert updated["blocker_reason"] == "worker_failed"
    assert updated["worker_evidence_refs"] == ["log:pytest"]


def test_review_required_fix_transitions_lane_to_patch_forward() -> None:
    lane = {"lane_id": "lane-1", "status": "under_review"}

    updated = apply_review_outcome(
        lane,
        ReviewOutcome(
            verdict="changes_requested",
            summary="Missing edge case.",
            evidence_refs=["review:1"],
        ),
    )

    assert updated["status"] == "patch_forward"
    assert updated["review_required_fix"] == "Missing edge case."
    assert updated["review_evidence_refs"] == ["review:1"]


def _request() -> FeatureDraftPRRequest:
    return FeatureDraftPRRequest(
        feature_id="feature-1",
        title="Feature 1",
        base_branch="main",
        head_branch="feature/feature-1",
        blueprint_refs=["blueprint:bp-1"],
        lane_refs=["lane:lane-1"],
        acceptance_criteria=["Focused tests pass."],
        evidence_bundle_refs=["tests/xmuse/test_feature.py::test_feature"],
        memory_refs=["memory://conversation/conv-1/context"],
        parent_pr=42,
    )
