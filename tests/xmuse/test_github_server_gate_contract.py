from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from pydantic import ValidationError

from xmuse_core.platform.execution.github_ops import (
    CheckStatus,
    FakeGitHubServerSideTruthCollector,
    GitHubCliServerSideTruthClient,
    GitHubServerSideTruthEvidence,
    GitHubServerSideTruthSnapshot,
    ReadOnlyGitHubServerSideTruthCollector,
    build_github_server_side_truth_from_snapshot,
    build_github_server_side_truth_gap,
    can_emit_pr_merged,
    evaluate_merge_readiness,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CI_WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "xmuse-ci.yml"
SERVER_GATE_DOC = PROJECT_ROOT / "docs" / "xmuse" / "github-server-side-gate.md"
MERGE_CONTRACT_DOC = PROJECT_ROOT / "docs" / "xmuse" / "github-review-merge-contract.md"
CODEOWNERS = PROJECT_ROOT / "CODEOWNERS"

REQUIRED_SERVER_CHECKS = {
    "quality-gates",
    "contract-smoke-gates",
    "real-runtime-integration-gate",
}


class _FakeReadOnlyGitHubTruthClient:
    def __init__(self, snapshot: GitHubServerSideTruthSnapshot | None) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, int, tuple[str, ...]]] = []
        self.mutation_attempted = False

    def fetch_server_side_truth_snapshot(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthSnapshot | None:
        self.calls.append((repo, pull_request_number, tuple(required_checks)))
        return self.snapshot

    def mutate_branch_protection(self) -> None:
        self.mutation_attempted = True
        raise AssertionError("read-only collector must not mutate GitHub settings")


class _FakeGhApiRunner:
    def __init__(self, responses: dict[str, object], *, fail_on: str | None = None) -> None:
        self.responses = responses
        self.fail_on = fail_on
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        endpoint = command[2]
        if endpoint == self.fail_on:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="not found",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(self.responses[endpoint]),
            stderr="",
        )


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_branch_protection_doc_matches_workflow_job_names_and_ownership() -> None:
    workflow = _read(CI_WORKFLOW)
    server_doc = _read(SERVER_GATE_DOC)
    merge_doc = _read(MERGE_CONTRACT_DOC)
    codeowners = _read(CODEOWNERS)

    for check_name in REQUIRED_SERVER_CHECKS:
        assert f"{check_name}:" in workflow
        assert check_name in server_doc

    for fragment in (
        "Require status checks to pass before merging",
        "Require branches to be up to date before merging",
        "Require review from Code Owners",
        "Require conversation resolution before merging",
        "Do not allow bypassing the above settings",
        "review_evidence_bundle",
        ".github/pull_request_template.md",
        "CODEOWNERS",
    ):
        assert fragment in server_doc

    assert "Branch protection" in merge_doc
    assert ".github/" in codeowners
    assert "src/xmuse_core/integrations/" in codeowners
    assert "docs/xmuse/" in codeowners


def test_merge_readiness_contract_uses_server_side_required_checks() -> None:
    checks = [
        CheckStatus(name="quality-gates", status="success"),
        CheckStatus(name="contract-smoke-gates", status="success"),
        CheckStatus(name="real-runtime-integration-gate", status="success"),
    ]

    ready = evaluate_merge_readiness(
        checks,
        required_check_names=sorted(REQUIRED_SERVER_CHECKS),
        review_evidence_refs=["review:evidence:1"],
    )
    missing = evaluate_merge_readiness(
        checks[:2],
        required_check_names=sorted(REQUIRED_SERVER_CHECKS),
        review_evidence_refs=["review:evidence:1"],
    )
    no_evidence = evaluate_merge_readiness(
        checks,
        required_check_names=sorted(REQUIRED_SERVER_CHECKS),
        review_evidence_refs=[],
    )

    assert ready.merge_ready is True
    assert missing.merge_ready is False
    assert missing.failing_checks == ["real-runtime-integration-gate"]
    assert no_evidence.merge_ready is False
    assert no_evidence.missing_evidence == ["review_evidence_bundle"]


def test_local_contract_gap_does_not_allow_pr_merged_event() -> None:
    evidence = build_github_server_side_truth_gap(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
        reason="local workflow files are not server-side enforcement evidence",
    )

    assert evidence.proof_level == "manual_gap"
    assert evidence.workflow_run_id is None
    assert evidence.branch_protection_snapshot is None
    assert evidence.merge_commit_sha is None
    assert can_emit_pr_merged(evidence) is False


def test_fake_server_side_truth_collector_never_emits_merge_truth() -> None:
    collector = FakeGitHubServerSideTruthCollector(
        workflow_run_id=123,
        check_suite_id=456,
        check_run_ids=[111, 112, 113],
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
    )

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert evidence.proof_level == "contract_proof"
    assert evidence.workflow_run_id == 123
    assert evidence.has_status_check_truth is True
    assert evidence.has_server_enforcement_truth is True
    assert evidence.has_review_truth is True
    assert evidence.merge_commit_sha is None
    assert evidence.merged_at is None
    assert evidence.merge_event_id is None
    assert evidence.has_merge_truth is False
    assert can_emit_pr_merged(evidence) is False


def test_server_side_merge_proof_requires_real_merge_truth_fields() -> None:
    with pytest.raises(ValidationError, match="merge_commit_sha"):
        GitHubServerSideTruthEvidence(
            repo="iiyazu/Cross-Muse",
            pull_request_number=42,
            required_checks=sorted(REQUIRED_SERVER_CHECKS),
            proof_level="server_side_merge_proof",
            workflow_run_id=123,
            check_suite_id=456,
            expected_source_app="github-actions",
            branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
            review_event_id=789,
            reviewer_login="reviewer",
            code_owner_review_verified=True,
        )


def test_server_side_merge_truth_allows_pr_merged_event() -> None:
    evidence = GitHubServerSideTruthEvidence(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
        proof_level="server_side_merge_proof",
        workflow_run_id=123,
        check_suite_id=456,
        check_run_ids=[111, 112, 113],
        expected_source_app="github-actions",
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
    )

    assert evidence.has_status_check_truth is True
    assert evidence.has_server_enforcement_truth is True
    assert evidence.has_review_truth is True
    assert evidence.has_merge_truth is True
    assert can_emit_pr_merged(evidence) is True


def test_pr_merged_gate_rechecks_all_server_side_truth_dimensions() -> None:
    evidence = GitHubServerSideTruthEvidence.model_construct(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
        proof_level="server_side_merge_proof",
        workflow_run_id=None,
        check_suite_id=None,
        check_run_ids=[],
        expected_source_app=None,
        branch_protection_snapshot=None,
        ruleset_snapshot=None,
        review_event_id=None,
        reviewer_login=None,
        code_owner_review_verified=False,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
        gap_reason=None,
    )

    assert evidence.has_merge_truth is True
    assert can_emit_pr_merged(evidence) is False


def test_pr_merged_gate_requires_all_required_check_runs() -> None:
    evidence = GitHubServerSideTruthEvidence.model_construct(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
        proof_level="server_side_merge_proof",
        workflow_run_id=111,
        check_suite_id=None,
        check_run_ids=[111],
        expected_source_app="github-actions",
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        ruleset_snapshot=None,
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
        gap_reason=None,
    )

    assert evidence.has_merge_truth is True
    assert can_emit_pr_merged(evidence) is False


def test_contract_proof_with_injected_merge_fields_cannot_emit_pr_merged() -> None:
    evidence = GitHubServerSideTruthEvidence.model_construct(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
        proof_level="contract_proof",
        workflow_run_id=123,
        check_suite_id=456,
        check_run_ids=[111, 112, 113],
        expected_source_app="github-actions",
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        ruleset_snapshot=None,
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
        gap_reason=None,
    )

    assert evidence.has_merge_truth is True
    assert can_emit_pr_merged(evidence) is False


def test_server_side_snapshot_normalizer_promotes_complete_read_only_evidence() -> None:
    snapshot = GitHubServerSideTruthSnapshot(
        workflow_run_id=123,
        check_suite_id=456,
        check_run_ids=[111, 112, 113],
        expected_source_app="github-actions",
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
    )

    evidence = build_github_server_side_truth_from_snapshot(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
        snapshot=snapshot,
    )

    assert evidence.proof_level == "server_side_merge_proof"
    assert evidence.workflow_run_id == 123
    assert evidence.review_event_id == 789
    assert evidence.merge_commit_sha == "abc123"
    assert can_emit_pr_merged(evidence) is True


def test_server_side_snapshot_normalizer_keeps_incomplete_snapshot_as_gap() -> None:
    snapshot = GitHubServerSideTruthSnapshot(
        workflow_run_id=123,
        check_suite_id=456,
        check_run_ids=[111, 112, 113],
        expected_source_app="github-actions",
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        code_owner_review_verified=False,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
    )

    evidence = build_github_server_side_truth_from_snapshot(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
        snapshot=snapshot,
    )

    assert evidence.proof_level == "manual_gap"
    assert evidence.has_merge_truth is True
    assert evidence.has_review_truth is False
    assert evidence.gap_reason is not None
    assert "review" in evidence.gap_reason
    assert can_emit_pr_merged(evidence) is False


def test_read_only_collector_normalizes_client_snapshot_without_mutation() -> None:
    snapshot = GitHubServerSideTruthSnapshot(
        workflow_run_id=123,
        check_suite_id=456,
        check_run_ids=[111, 112, 113],
        expected_source_app="github-actions",
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
    )
    client = _FakeReadOnlyGitHubTruthClient(snapshot)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert client.calls == [
        ("iiyazu/Cross-Muse", 42, tuple(sorted(REQUIRED_SERVER_CHECKS)))
    ]
    assert client.mutation_attempted is False
    assert evidence.proof_level == "server_side_merge_proof"
    assert can_emit_pr_merged(evidence) is True


def test_read_only_collector_records_manual_gap_when_snapshot_unavailable() -> None:
    client = _FakeReadOnlyGitHubTruthClient(snapshot=None)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert client.calls == [
        ("iiyazu/Cross-Muse", 42, tuple(sorted(REQUIRED_SERVER_CHECKS)))
    ]
    assert evidence.proof_level == "manual_gap"
    assert evidence.gap_reason == "read-only GitHub server-side truth snapshot unavailable"
    assert can_emit_pr_merged(evidence) is False


def test_read_only_collector_keeps_partial_client_snapshot_as_gap() -> None:
    snapshot = GitHubServerSideTruthSnapshot(
        workflow_run_id=123,
        check_suite_id=456,
        check_run_ids=[111, 112, 113],
        expected_source_app="github-actions",
        branch_protection_snapshot={"required_status_checks": sorted(REQUIRED_SERVER_CHECKS)},
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="merge-event-1",
    )
    client = _FakeReadOnlyGitHubTruthClient(snapshot)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert evidence.proof_level == "manual_gap"
    assert evidence.has_merge_truth is True
    assert evidence.has_review_truth is False
    assert evidence.gap_reason is not None
    assert "review_truth" in evidence.gap_reason
    assert can_emit_pr_merged(evidence) is False


def test_gh_cli_truth_client_fetches_read_only_server_snapshot() -> None:
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {
                "node_id": "PR_node_42",
                "merged": True,
                "merged_at": "2026-06-10T15:00:00Z",
                "merge_commit_sha": "abc123",
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/42/reviews": [
                {"id": 789, "user": {"login": "reviewer"}, "state": "APPROVED"}
            ],
            "repos/iiyazu/Cross-Muse/branches/main/protection": {
                "required_pull_request_reviews": {"require_code_owner_reviews": True},
                "required_status_checks": {
                    "checks": [
                        {"context": "quality-gates"},
                        {"context": "contract-smoke-gates"},
                        {"context": "real-runtime-integration-gate"},
                    ]
                },
            },
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": [
                    {
                        "id": 111,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 112,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 113,
                        "name": "real-runtime-integration-gate",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ]
            },
        }
    )
    client = GitHubCliServerSideTruthClient(runner=runner)

    snapshot = client.fetch_server_side_truth_snapshot(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert snapshot == GitHubServerSideTruthSnapshot(
        workflow_run_id=111,
        check_run_ids=[111, 112, 113],
        expected_source_app="github-actions",
        branch_protection_snapshot=runner.responses[
            "repos/iiyazu/Cross-Muse/branches/main/protection"
        ],
        review_event_id=789,
        reviewer_login="reviewer",
        code_owner_review_verified=True,
        merge_commit_sha="abc123",
        merged_at="2026-06-10T15:00:00Z",
        merge_event_id="PR_node_42",
    )
    assert all(command[:2] == ["gh", "api"] for command in runner.commands)
    assert not any(
        token in command
        for command in runner.commands
        for token in ("--method", "PATCH", "PUT", "DELETE", "POST")
    )


def test_gh_cli_truth_client_uses_ruleset_snapshot_when_branch_protection_missing() -> None:
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {
                "node_id": "PR_node_42",
                "merged": True,
                "merged_at": "2026-06-10T15:00:00Z",
                "merge_commit_sha": "abc123",
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/42/reviews": [
                {"id": 789, "user": {"login": "reviewer"}, "state": "APPROVED"}
            ],
            "repos/iiyazu/Cross-Muse/rulesets": [
                {
                    "id": 5001,
                    "name": "main enforcement",
                    "target": "branch",
                    "enforcement": "active",
                    "conditions": {
                        "ref_name": {
                            "include": ["refs/heads/main"],
                            "exclude": [],
                        }
                    },
                    "rules": [
                        {
                            "type": "pull_request",
                            "parameters": {"require_code_owner_review": True},
                        }
                    ],
                }
            ],
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": [
                    {
                        "id": 111,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 112,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 113,
                        "name": "real-runtime-integration-gate",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ]
            },
        },
        fail_on="repos/iiyazu/Cross-Muse/branches/main/protection",
    )
    client = GitHubCliServerSideTruthClient(runner=runner)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert evidence.proof_level == "server_side_merge_proof"
    assert evidence.branch_protection_snapshot is None
    assert evidence.ruleset_snapshot == {
        "rulesets": runner.responses["repos/iiyazu/Cross-Muse/rulesets"]
    }
    assert evidence.code_owner_review_verified is True
    assert can_emit_pr_merged(evidence) is True
    assert ["gh", "api", "repos/iiyazu/Cross-Muse/rulesets"] in runner.commands


def test_gh_cli_truth_client_does_not_use_ruleset_for_different_branch() -> None:
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {
                "node_id": "PR_node_42",
                "merged": True,
                "merged_at": "2026-06-10T15:00:00Z",
                "merge_commit_sha": "abc123",
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/42/reviews": [
                {"id": 789, "user": {"login": "reviewer"}, "state": "APPROVED"}
            ],
            "repos/iiyazu/Cross-Muse/rulesets": [
                {
                    "id": 5002,
                    "name": "release enforcement",
                    "target": "branch",
                    "enforcement": "active",
                    "conditions": {
                        "ref_name": {
                            "include": ["refs/heads/release"],
                            "exclude": [],
                        }
                    },
                    "rules": [
                        {
                            "type": "pull_request",
                            "parameters": {"require_code_owner_review": True},
                        }
                    ],
                }
            ],
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": [
                    {
                        "id": 111,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 112,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 113,
                        "name": "real-runtime-integration-gate",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ]
            },
        },
        fail_on="repos/iiyazu/Cross-Muse/branches/main/protection",
    )
    client = GitHubCliServerSideTruthClient(runner=runner)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert evidence.proof_level == "manual_gap"
    assert evidence.ruleset_snapshot == {
        "rulesets": runner.responses["repos/iiyazu/Cross-Muse/rulesets"]
    }
    assert evidence.has_review_truth is False
    assert evidence.gap_reason is not None
    assert "review_truth" in evidence.gap_reason
    assert can_emit_pr_merged(evidence) is False


def test_gh_cli_truth_client_does_not_use_ruleset_excluding_base_branch() -> None:
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {
                "node_id": "PR_node_42",
                "merged": True,
                "merged_at": "2026-06-10T15:00:00Z",
                "merge_commit_sha": "abc123",
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/42/reviews": [
                {"id": 789, "user": {"login": "reviewer"}, "state": "APPROVED"}
            ],
            "repos/iiyazu/Cross-Muse/rulesets": [
                {
                    "id": 5003,
                    "name": "all except main",
                    "target": "branch",
                    "enforcement": "active",
                    "conditions": {
                        "ref_name": {
                            "include": ["refs/heads/*"],
                            "exclude": ["refs/heads/main"],
                        }
                    },
                    "rules": [
                        {
                            "type": "pull_request",
                            "parameters": {"require_code_owner_review": True},
                        }
                    ],
                }
            ],
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": [
                    {
                        "id": 111,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 112,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 113,
                        "name": "real-runtime-integration-gate",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ]
            },
        },
        fail_on="repos/iiyazu/Cross-Muse/branches/main/protection",
    )
    client = GitHubCliServerSideTruthClient(runner=runner)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert evidence.proof_level == "manual_gap"
    assert evidence.has_review_truth is False
    assert evidence.gap_reason is not None
    assert "review_truth" in evidence.gap_reason
    assert can_emit_pr_merged(evidence) is False


def test_gh_cli_truth_client_accepts_ruleset_branch_pattern_for_base_branch() -> None:
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {
                "node_id": "PR_node_42",
                "merged": True,
                "merged_at": "2026-06-10T15:00:00Z",
                "merge_commit_sha": "abc123",
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/42/reviews": [
                {"id": 789, "user": {"login": "reviewer"}, "state": "APPROVED"}
            ],
            "repos/iiyazu/Cross-Muse/rulesets": [
                {
                    "id": 5004,
                    "name": "main family",
                    "target": "branch",
                    "enforcement": "active",
                    "conditions": {
                        "ref_name": {
                            "include": ["refs/heads/mai*"],
                            "exclude": ["refs/heads/release"],
                        }
                    },
                    "rules": [
                        {
                            "type": "pull_request",
                            "parameters": {"require_code_owner_review": True},
                        }
                    ],
                }
            ],
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": [
                    {
                        "id": 111,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 112,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 113,
                        "name": "real-runtime-integration-gate",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ]
            },
        },
        fail_on="repos/iiyazu/Cross-Muse/branches/main/protection",
    )
    client = GitHubCliServerSideTruthClient(runner=runner)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert evidence.proof_level == "server_side_merge_proof"
    assert evidence.has_review_truth is True
    assert can_emit_pr_merged(evidence) is True


def test_gh_cli_truth_client_returns_none_when_read_fails() -> None:
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {},
        },
        fail_on="repos/iiyazu/Cross-Muse/pulls/42",
    )
    client = GitHubCliServerSideTruthClient(runner=runner)

    snapshot = client.fetch_server_side_truth_snapshot(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert snapshot is None


def test_gh_cli_truth_client_partial_required_checks_remain_manual_gap() -> None:
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {
                "node_id": "PR_node_42",
                "merged": True,
                "merged_at": "2026-06-10T15:00:00Z",
                "merge_commit_sha": "abc123",
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/42/reviews": [
                {"id": 789, "user": {"login": "reviewer"}, "state": "APPROVED"}
            ],
            "repos/iiyazu/Cross-Muse/branches/main/protection": {
                "required_pull_request_reviews": {"require_code_owner_reviews": True},
                "required_status_checks": {
                    "checks": [
                        {"context": "quality-gates"},
                        {"context": "contract-smoke-gates"},
                        {"context": "real-runtime-integration-gate"},
                    ]
                },
            },
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": [
                    {
                        "id": 111,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    }
                ]
            },
        }
    )
    client = GitHubCliServerSideTruthClient(runner=runner)
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)

    evidence = collector.collect(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=sorted(REQUIRED_SERVER_CHECKS),
    )

    assert evidence.proof_level == "manual_gap"
    assert evidence.has_status_check_truth is False
    assert evidence.gap_reason is not None
    assert "status_check_truth" in evidence.gap_reason
    assert can_emit_pr_merged(evidence) is False
