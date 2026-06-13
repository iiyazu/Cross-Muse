from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from xmuse_core.platform.release_evidence_candidates import (
    build_release_evidence_candidate_report,
)
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-release-evidence-candidates",
        description="Write a read-only xmuse release evidence candidate report.",
    )
    parser.add_argument("--xmuse-root", type=Path, default=DEFAULT_XMUSE_ROOT)
    parser.add_argument("--conversation-id")
    parser.add_argument("--repo-id")
    parser.add_argument("--workspace-id")
    parser.add_argument("--god-id")
    parser.add_argument("--thread-id")
    parser.add_argument("--blueprint-id")
    parser.add_argument("--feature-id")
    parser.add_argument("--lane-id")
    parser.add_argument("--content")
    parser.add_argument("--query")
    parser.add_argument("--github-repo")
    parser.add_argument("--github-pull-request")
    parser.add_argument("--github-base-branch")
    parser.add_argument("--github-expected-head-sha")
    parser.add_argument("--github-required-check", action="append", default=[])
    parser.add_argument("--trace-limit", type=int, default=20)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "release-evidence-candidates.json",
        help="Path for the xmuse.release_evidence_candidates.v1 report.",
    )
    args = parser.parse_args(argv)
    report = build_release_evidence_candidate_report(
        args.xmuse_root,
        conversation_id=args.conversation_id,
        env=dict(os.environ),
        memoryos_payload=_candidate_payload(args),
        trace_limit=args.trace_limit,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "schema_version": report["schema_version"],
                "output": str(args.output),
                "natural_export_ready": _export_ready(report, "natural_deliberation"),
                "provider_export_ready": _export_ready(
                    report,
                    "real_provider_runtime",
                ),
                "memoryos_export_ready": _export_ready(report, "live_memoryos"),
                "github_export_ready": _export_ready(report, "github_server_truth"),
            },
            sort_keys=True,
        )
    )
    return 0


def _candidate_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    _set_if_present(payload, "repo_id", args.repo_id)
    _set_if_present(payload, "workspace_id", args.workspace_id)
    _set_if_present(payload, "god_id", args.god_id)
    _set_if_present(payload, "thread_id", args.thread_id)
    _set_if_present(payload, "blueprint_id", args.blueprint_id)
    _set_if_present(payload, "feature_id", args.feature_id)
    _set_if_present(payload, "lane_id", args.lane_id)
    _set_if_present(payload, "content", args.content)
    _set_if_present(payload, "query", args.query)
    _set_if_present(payload, "repo", args.github_repo)
    _set_if_present(payload, "pull_request_number", args.github_pull_request)
    _set_if_present(payload, "base_branch", args.github_base_branch)
    _set_if_present(payload, "expected_head_sha", args.github_expected_head_sha)
    if args.github_required_check:
        payload["required_checks"] = [
            check.strip() for check in args.github_required_check if check.strip()
        ]
    return payload


def _set_if_present(payload: dict[str, Any], key: str, value: str | None) -> None:
    if value is not None and value.strip():
        payload[key] = value.strip()


def _export_ready(report: dict[str, Any], key: str) -> bool:
    section = report.get(key)
    return bool(isinstance(section, dict) and section.get("export_ready") is True)


if __name__ == "__main__":
    raise SystemExit(main())
