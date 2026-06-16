from __future__ import annotations

from xmuse_core.platform.release_readiness import (
    ReleaseGateEvidence,
    ReleaseGateKind,
    evaluate_release_readiness,
)


def test_release_readiness_blocks_configured_live_gate_with_fake_proof() -> None:
    readiness = evaluate_release_readiness(
        [
            ReleaseGateEvidence(
                gate_id="memoryos-live",
                kind=ReleaseGateKind.LIVE_MEMORYOS,
                configured=True,
                required=True,
                status="ok",
                proof_level="fake_runtime_proof",
                owner="operator",
                summary="fake trace converted",
            )
        ]
    )

    assert readiness.decision == "blocked"
    assert readiness.blockers
    assert readiness.blockers[0]["gate_id"] == "memoryos-live"
    assert "requires live_service_proof" in readiness.blockers[0]["reason"]


def test_release_readiness_accepts_internal_review_without_server_enforcement() -> None:
    readiness = evaluate_release_readiness(
        [
            ReleaseGateEvidence(
                gate_id="tests",
                kind=ReleaseGateKind.LOCAL_VALIDATION,
                configured=True,
                required=True,
                status="ok",
                proof_level="contract_proof",
                owner="codex",
                summary="focused tests passed",
            ),
            ReleaseGateEvidence(
                gate_id="internal-review",
                kind=ReleaseGateKind.INTERNAL_REVIEW,
                configured=True,
                required=True,
                status="ok",
                proof_level="internal_review_proof",
                owner="codex-review",
                summary="verified internal review",
            ),
            ReleaseGateEvidence(
                gate_id="github-enforcement",
                kind=ReleaseGateKind.GITHUB_SERVER_TRUTH,
                configured=True,
                required=True,
                status="ok",
                proof_level="server_side_enforcement_proof",
                owner="github",
                summary="branch rules observed",
            ),
            ReleaseGateEvidence(
                gate_id="memoryos-live",
                kind=ReleaseGateKind.LIVE_MEMORYOS,
                configured=True,
                required=True,
                status="ok",
                proof_level="live_service_proof",
                owner="memoryos",
                summary="trace captured",
            ),
            ReleaseGateEvidence(
                gate_id="provider-soak",
                kind=ReleaseGateKind.REAL_PROVIDER,
                configured=True,
                required=True,
                status="ok",
                proof_level="real_provider_proof",
                owner="codex",
                summary="real provider heartbeat captured",
            ),
        ]
    )

    assert readiness.decision == "ready"
    assert readiness.proof_level_summary["internal_review_proof"] == 1
    assert readiness.proof_level_summary["server_side_enforcement_proof"] == 1
    assert readiness.forbidden_claims == []
    assert readiness.forbidden_claim_count == 0
    assert readiness.forbidden_claim_gates == []


def test_release_readiness_reports_forbidden_claims_without_blocking_gate_ready() -> None:
    readiness = evaluate_release_readiness(
        [
            ReleaseGateEvidence(
                gate_id="github-enforcement",
                kind=ReleaseGateKind.GITHUB_SERVER_TRUTH,
                configured=True,
                required=True,
                status="ok",
                proof_level="server_side_enforcement_proof",
                owner="github",
                summary="branch rules observed; merge truth remains absent",
                forbidden_claims=("ready_to_merge", "pr_merged"),
            )
        ]
    )

    assert readiness.decision == "ready"
    assert readiness.blockers == []
    assert readiness.forbidden_claims == ["ready_to_merge", "pr_merged"]
    assert readiness.forbidden_claim_count == 2
    assert readiness.forbidden_claim_gates == [
        {
            "gate_id": "github-enforcement",
            "kind": "github_server_truth",
            "owner": "github",
            "forbidden_claims": ["ready_to_merge", "pr_merged"],
        }
    ]


def test_release_readiness_blocks_internal_review_used_as_github_server_truth() -> None:
    readiness = evaluate_release_readiness(
        [
            ReleaseGateEvidence(
                gate_id="github-enforcement",
                kind=ReleaseGateKind.GITHUB_SERVER_TRUTH,
                configured=True,
                required=True,
                status="ok",
                proof_level="internal_review_proof",
                owner="operator",
                summary="local review exists",
            )
        ]
    )

    assert readiness.decision == "blocked"
    assert readiness.blockers[0]["gate_id"] == "github-enforcement"
    assert "requires server_side_enforcement_proof" in readiness.blockers[0]["reason"]
