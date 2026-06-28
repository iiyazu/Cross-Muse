from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "github_server_truth_capture.py"
REQUIRED_CHECKS = [
    "quality-gates",
    "contract-smoke-gates",
    "real-runtime-integration-gate",
    "peer-chat-runtime-gate",
]

module_name = "github_server_truth_capture_test_harness"
loader = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
assert loader is not None and loader.loader is not None
module = importlib.util.module_from_spec(loader)
sys.modules[module_name] = module
loader.loader.exec_module(module)


class _FakeGhApiRunner:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        endpoint = command[2]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(self.responses[endpoint]),
            stderr="",
        )


def _successful_required_check_runs(head_sha: str = "head123") -> list[dict[str, object]]:
    return [
        {
            "id": 111 + index,
            "name": check_name,
            "conclusion": "success",
            "head_sha": head_sha,
            "app": {"slug": "github-actions"},
        }
        for index, check_name in enumerate(REQUIRED_CHECKS)
    ]


def test_github_server_truth_capture_default_required_checks_match_server_gate() -> None:
    assert module.DEFAULT_REQUIRED_CHECKS == REQUIRED_CHECKS


def test_github_server_truth_capture_writes_complete_snapshot_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "github-truth.json"
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
                        {"context": "peer-chat-runtime-gate"},
                    ]
                },
            },
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": _successful_required_check_runs()
            },
        }
    )

    rc = module.capture_github_server_truth(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=REQUIRED_CHECKS,
        output=output,
        base_branch="main",
        runner=runner,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["proof_level"] == "server_side_merge_proof"
    assert payload["can_emit_pr_merged"] is True
    assert payload["head_sha"] == "head123"
    assert payload["check_run_names"] == REQUIRED_CHECKS
    assert payload["check_run_head_shas"] == ["head123"] * len(REQUIRED_CHECKS)
    assert payload["repo"] == "iiyazu/Cross-Muse"
    assert all(command[:2] == ["gh", "api"] for command in runner.commands)


def test_github_server_truth_capture_writes_manual_gap_when_snapshot_missing(
    tmp_path: Path,
) -> None:
    output = tmp_path / "github-truth.json"

    def failing_runner(command: list[str], **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=command,
            returncode=1,
            stdout="",
            stderr="not authenticated",
        )

    rc = module.capture_github_server_truth(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=["quality-gates"],
        output=output,
        base_branch="main",
        runner=failing_runner,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert rc == 2
    assert payload["proof_level"] == "manual_gap"
    assert payload["can_emit_pr_merged"] is False
    assert payload["gap_reason"] == "read-only GitHub server-side truth snapshot unavailable"


def test_github_server_truth_capture_accepts_internal_review_evidence(
    tmp_path: Path,
) -> None:
    output = tmp_path / "github-truth.json"
    artifact = tmp_path / "internal-review.md"
    artifact.write_text("opencode-in review passed", encoding="utf-8")
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/42": {
                "node_id": "PR_node_42",
                "merged": True,
                "merged_at": "2026-06-10T15:00:00Z",
                "merge_commit_sha": "merge123",
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/42/reviews": [],
            "repos/iiyazu/Cross-Muse/branches/main/protection": {
                "required_pull_request_reviews": None,
                "required_status_checks": {
                    "checks": [
                        {"context": "quality-gates"},
                        {"context": "contract-smoke-gates"},
                        {"context": "real-runtime-integration-gate"},
                        {"context": "peer-chat-runtime-gate"},
                    ]
                },
            },
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": _successful_required_check_runs()
            },
        }
    )

    rc = module.capture_github_server_truth(
        repo="iiyazu/Cross-Muse",
        pull_request_number=42,
        required_checks=REQUIRED_CHECKS,
        output=output,
        base_branch="main",
        runner=runner,
        internal_review_artifact=artifact,
        internal_reviewer="opencode-in-review",
        internal_reviewed_head_sha="head123",
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert rc == 0
    assert payload["proof_level"] == "server_side_merge_proof"
    assert payload["can_emit_pr_merged"] is True
    assert payload["head_sha"] == "head123"
    assert payload["check_run_names"] == REQUIRED_CHECKS
    assert payload["check_run_head_shas"] == ["head123"] * len(REQUIRED_CHECKS)
    assert payload["internal_review_artifact"] == str(artifact)
    assert payload["internal_reviewer"] == "opencode-in-review"
    assert payload["internal_review_verified"] is True
