from __future__ import annotations

from pathlib import Path

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
    assert "Feature IDs" in body
    assert "- `feature-1`" in body
    assert "- `feature-shared`" in body
    assert "Lane IDs" in body
    assert "- `lane:lane-1`" in body
    assert "Depends On Lanes" in body
    assert "- `lane:foundation`" in body
    assert "- Focused tests pass." in body
    assert "- `tests/xmuse/test_feature.py::test_feature`" in body
    assert "Review Evidence Bundle" in body
    assert "- `review:evidence:1`" in body
    assert "- `memory://conversation/conv-1/context`" in body
    assert "Memory Impact" in body
    assert "Reads task_state memory only." in body
    assert "New Artifacts" in body
    assert "- `docs/xmuse/mainline-contracts.md`" in body
    assert "Provider Changes" in body
    assert "- No provider changes." in body
    assert "Gate Profile" in body
    assert "contract" in body
    assert "Rollback Plan" in body
    assert "Revert feature branch." in body
    assert "Privacy Impact" in body
    assert "No PII or secret-bearing memory is added." in body
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
        ],
        review_evidence_refs=["review:evidence:1"],
    )
    ready = evaluate_merge_readiness(
        [
            CheckStatus(name="ruff", status="success"),
            CheckStatus(name="pytest", status="success"),
        ],
        review_evidence_refs=["review:evidence:1"],
        required_check_names=["ruff", "pytest"],
    )

    assert blocked.merge_ready is False
    assert blocked.reason == "required checks not passing: pytest"
    assert ready.merge_ready is True
    assert ready.reason == "required checks and review evidence present"


def test_review_evidence_is_required_for_merge_ready_status() -> None:
    decision = evaluate_merge_readiness(
        [
            CheckStatus(name="ruff", status="success"),
            CheckStatus(name="pytest", status="success"),
        ],
        review_evidence_refs=[],
    )

    assert decision.merge_ready is False
    assert decision.reason == "missing review evidence"
    assert decision.missing_evidence == ["review_evidence_bundle"]


def test_missing_required_check_blocks_merge_ready_status() -> None:
    decision = evaluate_merge_readiness(
        [CheckStatus(name="ruff", status="success")],
        review_evidence_refs=["review:evidence:1"],
        required_check_names=["ruff", "pytest"],
    )

    assert decision.merge_ready is False
    assert decision.failing_checks == ["pytest"]


def test_github_review_contract_files_define_required_fields_and_owners() -> None:
    template = Path(".github/pull_request_template.md").read_text(encoding="utf-8")
    owners = Path("CODEOWNERS").read_text(encoding="utf-8")
    policy = Path("docs/xmuse/github-review-merge-contract.md").read_text(encoding="utf-8")

    for field in [
        "blueprint_id",
        "feature_ids",
        "lane_ids",
        "depends_on_lanes",
        "memory_impact",
        "new_artifacts",
        "provider_changes",
        "gate_profile",
        "review_evidence_bundle",
        "rollback_plan",
        "privacy_impact",
    ]:
        assert field in template
        assert field in policy

    for owned_path in [
        "/src/xmuse_core/chat/",
        "/src/xmuse_core/structuring/",
        "/src/xmuse_core/platform/",
        "/src/xmuse_core/integrations/",
        "/src/xmuse_core/providers/",
        "/.github/",
    ]:
        assert owned_path in owners


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
        feature_ids=["feature-1", "feature-shared"],
        title="Feature 1",
        base_branch="main",
        head_branch="feature/feature-1",
        blueprint_refs=["blueprint:bp-1"],
        lane_refs=["lane:lane-1"],
        depends_on_lanes=["lane:foundation"],
        acceptance_criteria=["Focused tests pass."],
        evidence_bundle_refs=["tests/xmuse/test_feature.py::test_feature"],
        review_evidence_bundle=["review:evidence:1"],
        memory_refs=["memory://conversation/conv-1/context"],
        memory_impact="Reads task_state memory only.",
        new_artifacts=["docs/xmuse/mainline-contracts.md"],
        provider_changes=["No provider changes."],
        gate_profile="contract",
        rollback_plan="Revert feature branch.",
        privacy_impact="No PII or secret-bearing memory is added.",
        parent_pr=42,
    )
