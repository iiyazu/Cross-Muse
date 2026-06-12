from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from xmuse_core.platform.execution.github_ops import (
    GitHubCliServerSideTruthClient,
    ReadOnlyGitHubServerSideTruthCollector,
    can_emit_pr_merged,
)
from xmuse_core.platform.github_truth_release_gate import (
    write_github_server_truth_release_gate,
)

DEFAULT_REQUIRED_CHECKS = [
    "quality-gates",
    "contract-smoke-gates",
    "real-runtime-integration-gate",
]


def capture_github_server_truth(
    *,
    repo: str,
    pull_request_number: int,
    required_checks: list[str],
    output: Path,
    base_branch: str = "main",
    runner: Any | None = None,
    internal_review_artifact: Path | None = None,
    internal_reviewer: str | None = None,
    internal_reviewed_head_sha: str | None = None,
    release_gate_output: Path | None = None,
) -> int:
    client = GitHubCliServerSideTruthClient(
        base_branch=base_branch,
        runner=runner,
        internal_review_artifact=internal_review_artifact,
        internal_reviewer=internal_reviewer,
        internal_reviewed_head_sha=internal_reviewed_head_sha,
    )
    collector = ReadOnlyGitHubServerSideTruthCollector(client=client)
    evidence = collector.collect(
        repo=repo,
        pull_request_number=pull_request_number,
        required_checks=required_checks,
    )
    payload = evidence.model_dump(mode="json")
    payload["schema_version"] = "github_server_side_truth_capture.v1"
    payload["can_emit_pr_merged"] = can_emit_pr_merged(evidence)
    payload["merged"] = payload["can_emit_pr_merged"] is True
    payload["capture_mode"] = "opt_in_read_only_gh_api"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    if release_gate_output is not None:
        write_github_server_truth_release_gate(
            payload,
            artifact_path=output,
            output_path=release_gate_output,
            base_branch=base_branch,
        )
    return 0 if payload["can_emit_pr_merged"] else 2


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Capture opt-in read-only GitHub server-side truth evidence."
    )
    parser.add_argument("--repo", required=True, help="GitHub repository, e.g. owner/name.")
    parser.add_argument("--pull-request", required=True, type=int, help="Pull request number.")
    parser.add_argument("--output", required=True, type=Path, help="Output evidence JSON path.")
    parser.add_argument(
        "--release-gate-output",
        type=Path,
        default=None,
        help="Optional xmuse.production_evidence.v1 GitHub server-truth gate output.",
    )
    parser.add_argument("--base-branch", default="main")
    parser.add_argument(
        "--internal-review-artifact",
        type=Path,
        default=None,
        help="Path to xmuse internal GOD/reviewer evidence for Clowder-style review truth.",
    )
    parser.add_argument(
        "--internal-reviewer",
        default=None,
        help="xmuse internal reviewer identity, e.g. opencode-in-review.",
    )
    parser.add_argument(
        "--internal-reviewed-head-sha",
        default=None,
        help="PR head SHA covered by the internal review artifact.",
    )
    parser.add_argument(
        "--required-check",
        action="append",
        dest="required_checks",
        default=None,
        help="Required check name. May be repeated.",
    )
    args = parser.parse_args(argv)
    return capture_github_server_truth(
        repo=args.repo,
        pull_request_number=args.pull_request,
        required_checks=args.required_checks or list(DEFAULT_REQUIRED_CHECKS),
        output=args.output,
        base_branch=args.base_branch,
        internal_review_artifact=args.internal_review_artifact,
        internal_reviewer=args.internal_reviewer,
        internal_reviewed_head_sha=args.internal_reviewed_head_sha,
        release_gate_output=args.release_gate_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
