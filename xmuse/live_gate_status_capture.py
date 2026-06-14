from __future__ import annotations

import argparse
import json
import os
from collections.abc import Sequence
from pathlib import Path

from xmuse_core.platform.live_gate_status_capture import capture_live_gate_status
from xmuse_core.runtime.paths import default_xmuse_root

DEFAULT_XMUSE_ROOT = default_xmuse_root(Path(__file__).resolve().parent)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="xmuse-live-gate-status-capture",
        description="CLI for writing configured live-gate status artifacts.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_XMUSE_ROOT
        / "work"
        / "release_readiness"
        / "artifacts"
        / "live_gate_status",
        help="Directory for generated live-gate status JSON artifacts.",
    )
    parser.add_argument(
        "--github-repo",
        default=None,
        help="GitHub repository in owner/name form for server-truth capture.",
    )
    parser.add_argument(
        "--github-pull-request",
        default=None,
        help="Pull request number for server-truth capture.",
    )
    parser.add_argument(
        "--github-base-branch",
        default=None,
        help="Base branch for GitHub branch protection/ruleset truth.",
    )
    parser.add_argument(
        "--github-required-check",
        action="append",
        default=[],
        help="Required GitHub check name. May be repeated.",
    )
    parser.add_argument(
        "--github-expected-head-sha",
        default=None,
        help="Expected current PR head SHA. Mismatches remain manual_gap.",
    )
    args = parser.parse_args(argv)
    summary = capture_live_gate_status(
        output_dir=args.output_dir,
        env=_env_with_cli_overrides(args),
    )
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0


def _env_with_cli_overrides(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    _set_if_present(env, "XMUSE_GITHUB_TRUTH_REPO", args.github_repo)
    _set_if_present(
        env,
        "XMUSE_GITHUB_TRUTH_PULL_REQUEST",
        args.github_pull_request,
    )
    _set_if_present(
        env,
        "XMUSE_GITHUB_TRUTH_BASE_BRANCH",
        args.github_base_branch,
    )
    _set_if_present(
        env,
        "XMUSE_GITHUB_TRUTH_EXPECTED_HEAD_SHA",
        args.github_expected_head_sha,
    )
    if args.github_required_check:
        env["XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS"] = ",".join(
            check.strip() for check in args.github_required_check if check.strip()
        )
    return env


def _set_if_present(env: dict[str, str], key: str, value: str | None) -> None:
    if value is not None and value.strip():
        env[key] = value.strip()


if __name__ == "__main__":
    raise SystemExit(main())
