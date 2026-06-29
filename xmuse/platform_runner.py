#!/usr/bin/env python3
"""xmuse Platform Runner — MVP entrypoint."""
from __future__ import annotations

import argparse
import asyncio
import fcntl
import inspect
import json
import logging
import math
import os
import signal
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.memoryos_client import MemoryOSClient
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.driver import ChatDriver
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.integrations.memoryos_client import (
    RestMemoryOSClient as PeerChatMemoryOSClient,
)
from xmuse_core.platform.coordinator_control import CoordinatorControlService
from xmuse_core.platform.execution.github_ops import (
    GitHubCliServerSideTruthClient,
    GitHubMainCiEvidence,
    GitHubServerSideTruthEvidence,
    ReadOnlyGitHubMainCiTruthCollector,
    ReadOnlyGitHubServerSideTruthCollector,
)
from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.platform.github_gate_evidence import (
    GitHubGateEvidenceStore,
    GitHubGateTruthCollector,
    GitHubMainCiTruthCollector,
)
from xmuse_core.platform.model_policy import CodexModelPolicy, resolve_codex_model_policy
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.platform.review_plane import ReviewPlaneController
from xmuse_core.platform.run_health import (
    DEFAULT_STALE_AFTER_S,
    build_run_health_model,
    discover_xmuse_runtime_processes,
    list_live_pids,
    summarize_run_health,
)
from xmuse_core.providers.registry import DEFAULT_CODEX_GOD_MODEL_ID
from xmuse_core.runtime.paths import default_xmuse_root, resolve_xmuse_root
from xmuse_core.self_evolution import SelfEvolutionController
from xmuse_core.self_evolution.watcher import TerminalRunWatcher
from xmuse_core.structuring.blueprint_execution import BlueprintAutomationService
from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict
from xmuse_core.structuring.ready_set import (
    build_graph_ready_set,
    build_ready_set_parity_evidence,
)

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XMUSE_ROOT = default_xmuse_root(ROOT / "xmuse")
DEFAULT_BLUEPRINT = (
    ROOT
    / "docs"
    / "superpowers"
    / "specs"
    / "2026-05-28-xmuse-initial-self-evolution-blueprint.md"
)
logger = logging.getLogger(__name__)
PLANNING_AUTOMATION_WORKER_ID = "platform-runner"
WRITER_LEASE_TTL_S = 60.0
WRITER_LEASE_RENEW_INTERVAL_S = WRITER_LEASE_TTL_S / 3
DEFAULT_PEER_GOD_BACKEND = "native"
REQUIRED_GITHUB_CHECKS = [
    "quality-gates",
    "contract-smoke-gates",
    "real-runtime-integration-gate",
    "peer-chat-runtime-gate",
]


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class _ManualGapGithubGateCollector:
    def __init__(self, *, reason: str, head_sha: str) -> None:
        self._reason = reason
        self._head_sha = head_sha

    def collect(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthEvidence:
        return GitHubServerSideTruthEvidence(
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
            proof_level="manual_gap",
            internal_review_artifact="acceptance_gate_runner",
            internal_reviewer=PLANNING_AUTOMATION_WORKER_ID,
            internal_reviewed_head_sha=self._head_sha,
            internal_review_verified=True,
            gap_reason=self._reason,
        )


class _ExpectedHeadGithubGateCollector:
    def __init__(
        self,
        *,
        collector: GitHubGateTruthCollector,
        expected_head_sha: str,
    ) -> None:
        self._collector = collector
        self._expected_head_sha = expected_head_sha

    def collect(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthEvidence:
        evidence = self._collector.collect(
            repo=repo,
            pull_request_number=pull_request_number,
            required_checks=required_checks,
        )
        if evidence.head_sha == self._expected_head_sha:
            return evidence
        data = evidence.model_dump(mode="json")
        data["proof_level"] = "manual_gap"
        data["gap_reason"] = "github evidence head SHA mismatch"
        return GitHubServerSideTruthEvidence(**data)


def _with_expected_github_head(
    collector: GitHubGateTruthCollector,
    *,
    expected_head_sha: str,
) -> GitHubGateTruthCollector:
    return _ExpectedHeadGithubGateCollector(
        collector=collector,
        expected_head_sha=expected_head_sha,
    )


def _update_acceptance_gate_lane_projection(
    *,
    lanes_path: Path,
    lane_id: str,
    status: str,
    final_action_ref: str,
    acceptance_spine_ref: str,
    dispatch_ref: str,
    review_verdict_ref: str,
    github_gate_evidence_ref: str | None = None,
    github_gate_gap_ref: str | None = None,
    blocked_reason: str | None = None,
    failure_reason: str | None = None,
) -> None:
    payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise RuntimeError("feature_lanes.json missing lanes list")

    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if lane.get("feature_id") != lane_id:
            continue

        lane["status"] = status
        lane["final_action_ref"] = final_action_ref
        lane["acceptance_spine_ref"] = acceptance_spine_ref
        lane["dispatch_ref"] = dispatch_ref
        lane["review_verdict_ref"] = review_verdict_ref
        lane["projection_proof_boundary"] = (
            "feature_lanes_projection_not_acceptance_authority"
        )
        if github_gate_evidence_ref:
            lane["github_gate_evidence_ref"] = github_gate_evidence_ref
            lane.pop("github_gate_gap_ref", None)
        if github_gate_gap_ref:
            lane["github_gate_gap_ref"] = github_gate_gap_ref
            lane.pop("github_gate_evidence_ref", None)
        if blocked_reason:
            lane["blocked_reason"] = blocked_reason
        else:
            lane.pop("blocked_reason", None)
        if failure_reason:
            lane["failure_reason"] = failure_reason
        else:
            lane.pop("failure_reason", None)

        lanes_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    raise RuntimeError(f"acceptance-gated lane projection not found: {lane_id}")


def _update_existing_final_action_lane_projection(
    *,
    lanes_path: Path,
    lane_id: str,
    final_action_ref: str,
    github_gate_evidence_ref: str | None,
    github_gate_gap_ref: str | None,
    github_repo: str,
    github_pull_request: int,
    required_checks: list[str],
    status: str,
    blocked_reason: str | None = None,
) -> None:
    payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise RuntimeError("feature_lanes.json missing lanes list")

    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if lane.get("feature_id") != lane_id:
            continue

        lane["status"] = status
        lane["final_action_ref"] = final_action_ref
        lane["projection_proof_boundary"] = (
            "feature_lanes_projection_not_acceptance_authority"
        )
        lane["github_gate_repo"] = github_repo
        lane["github_gate_pull_request"] = github_pull_request
        lane["github_gate_required_checks"] = list(required_checks)
        if github_gate_evidence_ref:
            lane["github_gate_evidence_ref"] = github_gate_evidence_ref
            lane.pop("github_gate_gap_ref", None)
        if github_gate_gap_ref:
            lane["github_gate_gap_ref"] = github_gate_gap_ref
            lane.pop("github_gate_evidence_ref", None)
        if blocked_reason:
            lane["blocked_reason"] = blocked_reason
        else:
            lane.pop("blocked_reason", None)

        lanes_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    raise RuntimeError(f"final-action lane projection not found: {lane_id}")


def _preflight_existing_final_action_lane_projection(
    *,
    lanes_path: Path,
    lane_id: str,
    final_action_id: str,
) -> None:
    payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise RuntimeError("feature_lanes.json missing lanes list")

    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if lane.get("feature_id") != lane_id:
            continue
        projected_hold_id = lane.get("final_action_hold_id")
        if (
            isinstance(projected_hold_id, str)
            and projected_hold_id.strip()
            and projected_hold_id != final_action_id
        ):
            raise RuntimeError("final-action projection hold mismatch")
        return

    raise RuntimeError(f"final-action lane projection not found: {lane_id}")


def _load_final_action_lane_projection(
    *,
    lanes_path: Path,
    lane_id: str,
    final_action_id: str,
) -> dict[str, Any]:
    payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise RuntimeError("feature_lanes.json missing lanes list")

    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if lane.get("feature_id") != lane_id:
            continue
        projected_hold_id = lane.get("final_action_hold_id")
        if (
            isinstance(projected_hold_id, str)
            and projected_hold_id.strip()
            and projected_hold_id != final_action_id
        ):
            raise RuntimeError("final-action projection hold mismatch")
        return lane

    raise RuntimeError(f"final-action lane projection not found: {lane_id}")


def _update_final_action_pr_lane_projection(
    *,
    lanes_path: Path,
    lane_id: str,
    pr_ref: str,
    pull_request_number: int,
    pull_request_url: str,
    pull_request_head_sha: str,
    head_branch: str,
) -> None:
    payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise RuntimeError("feature_lanes.json missing lanes list")

    for lane in lanes:
        if not isinstance(lane, dict):
            continue
        if lane.get("feature_id") != lane_id:
            continue
        lane["pull_request_ref"] = pr_ref
        lane["pull_request_number"] = pull_request_number
        lane["pull_request_url"] = pull_request_url
        lane["pull_request_head_sha"] = pull_request_head_sha
        lane["pull_request_head_branch"] = head_branch
        lane["pull_request_status"] = "created"
        lane["projection_proof_boundary"] = (
            "feature_lanes_projection_not_pr_ci_or_merge_authority"
        )
        lanes_path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return

    raise RuntimeError(f"final-action lane projection not found: {lane_id}")


def _find_resolvable_final_action_hold(
    *,
    final_action_store: FinalActionGateStore,
    lane_id: str | None,
    final_action_id: str | None,
):
    matches = []
    for action in final_action_store.list_actions():
        if action.status != "pending" and not (
            action.status == "blocked" and action.github_gate_gap_ref
        ):
            continue
        if lane_id is not None and action.lane_id != lane_id:
            continue
        if final_action_id is not None and action.id != final_action_id:
            continue
        matches.append(action)
    if not matches:
        raise ValueError("resolvable final action hold not found")
    if len(matches) > 1:
        raise ValueError("multiple pending final action holds matched")
    return matches[0]


def _find_final_action_hold(
    *,
    final_action_store: FinalActionGateStore,
    lane_id: str | None,
    final_action_id: str | None,
):
    matches = []
    for action in final_action_store.list_actions():
        if lane_id is not None and action.lane_id != lane_id:
            continue
        if final_action_id is not None and action.id != final_action_id:
            continue
        matches.append(action)
    if not matches:
        raise ValueError("final action hold not found")
    if len(matches) > 1:
        raise ValueError("multiple final action holds matched")
    return matches[0]


def _main_ci_status(
    main_ci: GitHubMainCiEvidence | None,
    *,
    merge_commit_sha: str | None,
) -> str:
    if main_ci is None:
        return "missing"
    status = main_ci.conclusion or main_ci.status or "unknown"
    if (
        status == "success"
        and merge_commit_sha is not None
        and main_ci.head_sha is not None
        and main_ci.head_sha != merge_commit_sha
    ):
        return "head_mismatch"
    return status


def _find_pending_merge_final_action_hold(
    *,
    final_action_store: FinalActionGateStore,
    lane_id: str | None,
    final_action_id: str | None,
):
    matches = []
    for action in final_action_store.list_actions():
        if action.status != "pending" or action.action != "merge":
            continue
        if lane_id is not None and action.lane_id != lane_id:
            continue
        if final_action_id is not None and action.id != final_action_id:
            continue
        matches.append(action)
    if not matches:
        raise ValueError("pending merge final action hold not found")
    if len(matches) > 1:
        raise ValueError("multiple pending merge final action holds matched")
    return matches[0]


def _sanitize_branch_component(value: str) -> str:
    cleaned = []
    for char in value.strip():
        if char.isalnum() or char in {"-", "_", "."}:
            cleaned.append(char)
        else:
            cleaned.append("-")
    branch = "".join(cleaned).strip("-._")
    if not branch:
        raise ValueError("branch component is empty")
    return branch


def _command_stdout(
    command_runner,
    command: list[str],
    *,
    cwd: Path,
    timeout: int = 120,
) -> str:
    result = command_runner(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(
            "command failed: " + " ".join(command) + (f": {message}" if message else "")
        )
    return str(result.stdout or "").strip()


def _read_final_action_prs(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": "final_action_prs.v1", "items": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("items"), list):
        raise RuntimeError("final_action_prs.json items must be a list")
    return data


def _write_final_action_prs(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload["schema_version"] = "final_action_prs.v1"
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _render_final_action_pr_body(
    *,
    lane_id: str,
    final_action_id: str,
    final_action_summary: str,
    pr_ref: str,
    source_refs: list[Any],
    base_head_sha: str | None,
) -> str:
    refs = "\n".join(f"- {ref}" for ref in source_refs if isinstance(ref, str))
    if not refs:
        refs = "- (none recorded)"
    return (
        f"## Summary\n{final_action_summary}\n\n"
        "## xmuse Authority\n"
        f"- Lane: `{lane_id}`\n"
        f"- Final action: `final_actions.json#hold={final_action_id}`\n"
        f"- PR record: `{pr_ref}`\n"
        f"- Base head: `{base_head_sha or 'unknown'}`\n\n"
        "## Source Refs\n"
        f"{refs}\n\n"
        "## Proof Boundary\n"
        "This pull request was created from a pending xmuse final-action hold. "
        "It is not CI truth, GitHub review truth, merge truth, or final-action "
        "approval. Exact-head CI and guarded merge must be observed separately.\n"
    )


def create_final_action_pull_request(
    *,
    xmuse_root: Path,
    github_repo: str,
    lane_id: str | None = None,
    final_action_id: str | None = None,
    base_branch: str = "main",
    branch_prefix: str = "codex/",
    draft: bool = False,
    command_runner=None,
) -> dict[str, Any]:
    """Create a GitHub PR from an existing pending merge final-action hold."""

    if lane_id is None and final_action_id is None:
        raise ValueError("lane_id or final_action_id is required")
    clean_lane_id = lane_id.strip() if isinstance(lane_id, str) else None
    clean_final_action_id = (
        final_action_id.strip() if isinstance(final_action_id, str) else None
    )
    if lane_id is not None and not clean_lane_id:
        raise ValueError("lane_id must be non-empty")
    if final_action_id is not None and not clean_final_action_id:
        raise ValueError("final_action_id must be non-empty")
    clean_repo = github_repo.strip() if isinstance(github_repo, str) else ""
    if not clean_repo:
        raise ValueError("github_repo is required")
    clean_base = base_branch.strip()
    if not clean_base:
        raise ValueError("base_branch is required")
    clean_prefix = branch_prefix.strip()
    if not clean_prefix:
        raise ValueError("branch_prefix is required")

    command_runner = command_runner or subprocess.run
    lanes_path = xmuse_root / "feature_lanes.json"
    final_actions_path = xmuse_root / "final_actions.json"
    pr_store_path = xmuse_root / "final_action_prs.json"
    final_action_store = FinalActionGateStore(final_actions_path)
    hold = _find_pending_merge_final_action_hold(
        final_action_store=final_action_store,
        lane_id=clean_lane_id,
        final_action_id=clean_final_action_id,
    )
    lane = _load_final_action_lane_projection(
        lanes_path=lanes_path,
        lane_id=hold.lane_id,
        final_action_id=hold.id,
    )
    if lane.get("status") != "awaiting_final_action":
        raise RuntimeError("final action lane must be awaiting_final_action")
    worktree_value = lane.get("worktree")
    worktree = Path(str(worktree_value)) if worktree_value else None
    if worktree is None:
        raise RuntimeError("final action lane missing worktree")
    if not worktree.is_absolute():
        worktree = (xmuse_root / worktree).resolve()
    if not worktree.exists():
        raise RuntimeError("final action worktree not found")

    _command_stdout(
        command_runner,
        ["git", "rev-parse", "--is-inside-work-tree"],
        cwd=worktree,
    )
    dirty = _command_stdout(
        command_runner,
        ["git", "status", "--porcelain"],
        cwd=worktree,
    )
    if not dirty:
        raise RuntimeError("final action worktree has no changes")

    head_branch = clean_prefix + _sanitize_branch_component(hold.lane_id)
    title = f"xmuse final action: {hold.lane_id}"
    record_id = f"fapr-{uuid.uuid4().hex[:12]}"
    pr_ref = f"final_action_prs.json#pr={record_id}"
    base_head_sha = lane.get("base_head_sha")
    body = _render_final_action_pr_body(
        lane_id=hold.lane_id,
        final_action_id=hold.id,
        final_action_summary=hold.summary,
        pr_ref=pr_ref,
        source_refs=list(lane.get("source_refs") or []),
        base_head_sha=base_head_sha if isinstance(base_head_sha, str) else None,
    )
    _command_stdout(command_runner, ["git", "checkout", "-B", head_branch], cwd=worktree)
    _command_stdout(command_runner, ["git", "add", "--all"], cwd=worktree)
    _command_stdout(command_runner, ["git", "commit", "-m", title], cwd=worktree)
    _command_stdout(
        command_runner,
        ["git", "fetch", "origin", clean_base],
        cwd=worktree,
        timeout=300,
    )
    _command_stdout(
        command_runner,
        ["git", "merge", "--no-edit", f"origin/{clean_base}"],
        cwd=worktree,
        timeout=300,
    )
    commit_sha = _command_stdout(command_runner, ["git", "rev-parse", "HEAD"], cwd=worktree)
    _command_stdout(
        command_runner,
        ["git", "push", "-u", "origin", f"HEAD:refs/heads/{head_branch}"],
        cwd=worktree,
        timeout=300,
    )
    pr_create = [
        "gh",
        "pr",
        "create",
        "--repo",
        clean_repo,
        "--base",
        clean_base,
        "--head",
        head_branch,
        "--title",
        title,
        "--body",
        body,
    ]
    if draft:
        pr_create.append("--draft")
    pr_url = _command_stdout(command_runner, pr_create, cwd=worktree, timeout=300)
    pr_view = _command_stdout(
        command_runner,
        [
            "gh",
            "pr",
            "view",
            pr_url,
            "--repo",
            clean_repo,
            "--json",
            "number,url,headRefOid",
        ],
        cwd=worktree,
        timeout=120,
    )
    pr_payload = json.loads(pr_view)
    pr_number = int(pr_payload["number"])
    pr_url = str(pr_payload["url"])
    pr_head_sha = str(pr_payload["headRefOid"])
    record = {
        "id": record_id,
        "final_action_id": hold.id,
        "lane_id": hold.lane_id,
        "status": "created",
        "repo": clean_repo,
        "base_branch": clean_base,
        "head_branch": head_branch,
        "commit_sha": commit_sha,
        "pull_request_number": pr_number,
        "pull_request_url": pr_url,
        "head_sha": pr_head_sha,
        "draft": draft,
        "worktree": str(worktree),
        "proof_boundary": "pull_request_created_not_merge_truth",
        "created_at": _utc_now(),
    }
    pr_store = _read_final_action_prs(pr_store_path)
    pr_store.setdefault("items", []).append(record)
    _write_final_action_prs(pr_store_path, pr_store)
    pr_ref = f"final_action_prs.json#pr={record['id']}"
    _update_final_action_pr_lane_projection(
        lanes_path=lanes_path,
        lane_id=hold.lane_id,
        pr_ref=pr_ref,
        pull_request_number=pr_number,
        pull_request_url=pr_url,
        pull_request_head_sha=pr_head_sha,
        head_branch=head_branch,
    )
    return {
        "status": "created",
        "lane_id": hold.lane_id,
        "final_action_id": hold.id,
        "pull_request_number": pr_number,
        "pull_request_url": pr_url,
        "pull_request_head_sha": pr_head_sha,
        "durable_refs": {
            "final_action_ref": f"final_actions.json#hold={hold.id}",
            "pull_request_ref": pr_ref,
            "feature_lanes": str(lanes_path),
        },
    }


def resolve_existing_final_action_with_github_gate(
    *,
    xmuse_root: Path,
    github_repo: str,
    github_pull_request: int,
    required_checks: list[str] | None = None,
    head_sha: str | None = None,
    lane_id: str | None = None,
    final_action_id: str | None = None,
    github_gate_collector: GitHubGateTruthCollector | None = None,
    main_ci_collector: GitHubMainCiTruthCollector | None = None,
    resolved_by: str = PLANNING_AUTOMATION_WORKER_ID,
) -> dict[str, Any]:
    """Resolve an existing pending final-action hold with GitHub gate truth."""

    if lane_id is None and final_action_id is None:
        raise ValueError("lane_id or final_action_id is required")
    clean_lane_id = lane_id.strip() if isinstance(lane_id, str) else None
    clean_final_action_id = (
        final_action_id.strip() if isinstance(final_action_id, str) else None
    )
    if lane_id is not None and not clean_lane_id:
        raise ValueError("lane_id must be non-empty")
    if final_action_id is not None and not clean_final_action_id:
        raise ValueError("final_action_id must be non-empty")
    if github_pull_request <= 0:
        raise ValueError("github_pull_request must be positive")
    clean_repo = github_repo.strip() if isinstance(github_repo, str) else ""
    if not clean_repo:
        raise ValueError("github_repo is required")
    clean_checks = list(required_checks or REQUIRED_GITHUB_CHECKS)
    if not clean_checks or any(not check.strip() for check in clean_checks):
        raise ValueError("required_checks must contain non-empty check names")
    clean_head_sha = (head_sha or _current_git_head_sha(ROOT)).strip()
    if not clean_head_sha:
        raise ValueError("head_sha is required")

    xmuse_root.mkdir(parents=True, exist_ok=True)
    lanes_path = xmuse_root / "feature_lanes.json"
    final_actions_path = xmuse_root / "final_actions.json"
    github_gate_evidence_path = xmuse_root / "github_gate_evidence.json"

    final_action_store = FinalActionGateStore(final_actions_path)
    hold = _find_resolvable_final_action_hold(
        final_action_store=final_action_store,
        lane_id=clean_lane_id,
        final_action_id=clean_final_action_id,
    )
    _preflight_existing_final_action_lane_projection(
        lanes_path=lanes_path,
        lane_id=hold.lane_id,
        final_action_id=hold.id,
    )
    collector = _with_expected_github_head(
        github_gate_collector
        or _ManualGapGithubGateCollector(
            reason="server_side_merge_proof unavailable for existing final action",
            head_sha=clean_head_sha,
        ),
        expected_head_sha=clean_head_sha,
    )
    resolved_hold = final_action_store.resolve_with_github_gate_evidence(
        hold.id,
        status="approved",
        resolved_by=resolved_by,
        repo=clean_repo,
        pull_request_number=github_pull_request,
        required_checks=clean_checks,
        collector=collector,
        main_ci_collector=main_ci_collector,
        evidence_store_path=github_gate_evidence_path,
    )

    final_action_ref = f"final_actions.json#hold={hold.id}"
    github_ref = (
        resolved_hold.github_gate_evidence_ref or resolved_hold.github_gate_gap_ref
    )
    if resolved_hold.github_gate_evidence_ref:
        terminal_status = "accepted"
        lane_status = "merged" if hold.action == "merge" else hold.target_status
        blocked_reason = None
    else:
        terminal_status = "blocked"
        lane_status = "blocked_for_input"
        blocked_reason = "github_gate_unverified"

    _update_existing_final_action_lane_projection(
        lanes_path=lanes_path,
        lane_id=hold.lane_id,
        final_action_ref=final_action_ref,
        github_gate_evidence_ref=resolved_hold.github_gate_evidence_ref,
        github_gate_gap_ref=resolved_hold.github_gate_gap_ref,
        github_repo=clean_repo,
        github_pull_request=github_pull_request,
        required_checks=clean_checks,
        status=lane_status,
        blocked_reason=blocked_reason,
    )
    return {
        "status": terminal_status,
        "blocked_reason": blocked_reason,
        "lane_id": hold.lane_id,
        "final_action_id": hold.id,
        "durable_refs": {
            "final_action_ref": final_action_ref,
            "github_gate_evidence_ref": github_ref,
            "feature_lanes": str(lanes_path),
        },
    }


def capture_existing_final_action_main_ci(
    *,
    xmuse_root: Path,
    lane_id: str | None = None,
    final_action_id: str | None = None,
    main_ci_collector: GitHubMainCiTruthCollector,
) -> dict[str, Any]:
    """Capture post-merge main CI truth for an existing accepted GitHub gate ref."""

    if lane_id is None and final_action_id is None:
        raise ValueError("lane_id or final_action_id is required")
    clean_lane_id = lane_id.strip() if isinstance(lane_id, str) else None
    clean_final_action_id = (
        final_action_id.strip() if isinstance(final_action_id, str) else None
    )
    if lane_id is not None and not clean_lane_id:
        raise ValueError("lane_id must be non-empty")
    if final_action_id is not None and not clean_final_action_id:
        raise ValueError("final_action_id must be non-empty")

    final_action_store = FinalActionGateStore(xmuse_root / "final_actions.json")
    hold = _find_final_action_hold(
        final_action_store=final_action_store,
        lane_id=clean_lane_id,
        final_action_id=clean_final_action_id,
    )
    github_gate_ref = hold.github_gate_evidence_ref
    if github_gate_ref is None:
        raise ValueError("final action hold has no accepted github gate evidence ref")
    evidence_store = GitHubGateEvidenceStore(xmuse_root / "github_gate_evidence.json")
    record = evidence_store.capture_main_ci_for_ref(
        github_gate_ref,
        collector=main_ci_collector,
        final_action_id=hold.id,
    )
    main_ci_status = _main_ci_status(
        record.main_ci,
        merge_commit_sha=record.evidence.merge_commit_sha,
    )
    terminal_status = "captured" if main_ci_status == "success" else "blocked"
    blocked_reason = None if terminal_status == "captured" else "main_ci_unverified"
    return {
        "status": terminal_status,
        "blocked_reason": blocked_reason,
        "lane_id": hold.lane_id,
        "final_action_id": hold.id,
        "github_gate_evidence_ref": github_gate_ref,
        "main_ci_status": main_ci_status,
        "durable_refs": {
            "final_action_ref": f"final_actions.json#hold={hold.id}",
            "github_gate_evidence_ref": github_gate_ref,
            "feature_lanes": str(xmuse_root / "feature_lanes.json"),
        },
    }


def run_acceptance_gated_goal(
    *,
    goal: str,
    xmuse_root: Path,
    github_repo: str,
    github_pull_request: int,
    required_checks: list[str] | None = None,
    head_sha: str | None = None,
    github_gate_collector: GitHubGateTruthCollector | None = None,
    main_ci_collector: GitHubMainCiTruthCollector | None = None,
) -> dict[str, Any]:
    """Run the smallest durable acceptance-gated goal path.

    This entrypoint is intentionally short-running. It creates the same durable
    stores used by the chat/control-plane path and resolves the final action
    through the GitHub gate evidence producer. Without a complete server-side
    merge proof, the terminal state remains blocked.
    """

    clean_goal = goal.strip() if isinstance(goal, str) else ""
    if not clean_goal:
        raise ValueError("goal is required")
    if github_pull_request <= 0:
        raise ValueError("github_pull_request must be positive")
    clean_repo = github_repo.strip() if isinstance(github_repo, str) else ""
    if not clean_repo:
        raise ValueError("github_repo is required")
    clean_checks = list(required_checks or REQUIRED_GITHUB_CHECKS)
    if not clean_checks or any(not check.strip() for check in clean_checks):
        raise ValueError("required_checks must contain non-empty check names")
    clean_head_sha = (head_sha or _current_git_head_sha(ROOT)).strip()
    if not clean_head_sha:
        raise ValueError("head_sha is required")

    xmuse_root.mkdir(parents=True, exist_ok=True)
    chat_db_path = xmuse_root / "chat.db"
    lanes_path = xmuse_root / "feature_lanes.json"
    review_plane_path = xmuse_root / "review_plane.json"
    final_actions_path = xmuse_root / "final_actions.json"
    github_gate_evidence_path = xmuse_root / "github_gate_evidence.json"

    peer_service = PeerChatService(chat_db_path)
    conversation = peer_service.create_conversation(
        title="Acceptance-gated platform runner goal"
    )["conversation"]
    conversation_id = str(conversation["id"])
    intake = peer_service.post_human_message(
        conversation_id=conversation_id,
        author="Human operator",
        content=clean_goal,
        client_request_id=f"acceptance-gate-{uuid.uuid4().hex[:12]}",
    )

    chat_store = ChatStore(chat_db_path)
    proposal = chat_store.create_proposal(
        conversation_id=conversation_id,
        author=PLANNING_AUTOMATION_WORKER_ID,
        proposal_type="acceptance_gate_runtime_contract",
        content=json.dumps(
            {
                "summary": clean_goal,
                "runner": "xmuse-platform-runner",
                "acceptance_gate": True,
            },
            ensure_ascii=False,
        ),
        references=[f"intake_message:{intake.message.id}"],
    )
    resolution = chat_store.approve_proposal(
        proposal.id,
        approved_by=[PLANNING_AUTOMATION_WORKER_ID],
        approval_mode="acceptance_gate_runner",
        goal_summary=clean_goal,
        content={
            "type": "acceptance_gate_runtime_contract",
            "goal": clean_goal,
        },
    )

    dispatch_store = ChatDispatchQueueStore(chat_db_path)
    dispatch = dispatch_store.enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id=None,
        artifact_ref=f"chat.db#proposal={proposal.id}",
        target="execute",
        dispatch_policy="acceptance_gate_short_run",
    )
    claimed = dispatch_store.claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by=PLANNING_AUTOMATION_WORKER_ID,
    )
    if claimed is None:
        raise RuntimeError("acceptance-gated dispatch item was not claimable")
    dispatch_store.mark_dispatched(
        dispatch.entry_id,
        provider_run_ref=f"platform_runner.acceptance_gate#head={clean_head_sha}",
        dispatch_evidence=f"chat_dispatch_queue#entry={dispatch.entry_id}",
    )

    lane_id = f"acceptance-gate-{uuid.uuid4().hex[:12]}"
    graph_id = f"acceptance-graph-{uuid.uuid4().hex[:12]}"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": lane_id,
                        "status": "gated",
                        "prompt": clean_goal,
                        "graph_id": graph_id,
                        "resolution_id": resolution.id,
                        "integration_mode": "noop",
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    review_controller = ReviewPlaneController(
        lanes_path=lanes_path,
        store_path=review_plane_path,
        final_actions_path=final_actions_path,
        require_final_action_approval=True,
    )
    task = review_controller.open_review_task(lane_id)
    verdict_id = f"verdict-{uuid.uuid4().hex[:12]}"
    review_controller.ingest_verdict(
        task.task_id,
        ReviewVerdict(
            id=verdict_id,
            lane_id=lane_id,
            decision=ReviewDecision.MERGE,
            summary="Acceptance-gated short run reached final-action review.",
            evidence_refs=[
                f"chat_dispatch_queue#entry={dispatch.entry_id}",
                f"platform_runner.acceptance_gate#head={clean_head_sha}",
            ],
        ),
    )

    final_action_store = FinalActionGateStore(final_actions_path)
    hold = next(
        action
        for action in final_action_store.list_actions()
        if action.lane_id == lane_id and action.verdict_id == verdict_id
    )
    collector = _with_expected_github_head(
        github_gate_collector
        or _ManualGapGithubGateCollector(
            reason="server_side_merge_proof unavailable for acceptance-gated short run",
            head_sha=clean_head_sha,
        ),
        expected_head_sha=clean_head_sha,
    )
    resolved_hold = final_action_store.resolve_with_github_gate_evidence(
        hold.id,
        status="approved",
        resolved_by=PLANNING_AUTOMATION_WORKER_ID,
        repo=clean_repo,
        pull_request_number=github_pull_request,
        required_checks=clean_checks,
        collector=collector,
        main_ci_collector=main_ci_collector,
        evidence_store_path=github_gate_evidence_path,
    )

    from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore

    spine = AcceptanceSpineStore(chat_db_path).list_by_conversation(conversation_id)[0]
    if spine.status is AcceptanceSpineStatus.ACCEPTED:
        terminal_status = "accepted"
        lane_projection_status = "merged"
    elif spine.status is AcceptanceSpineStatus.FAILED:
        terminal_status = "failed"
        lane_projection_status = "failed"
    else:
        terminal_status = "blocked"
        lane_projection_status = "blocked_for_input"
    github_ref = resolved_hold.github_gate_evidence_ref or resolved_hold.github_gate_gap_ref
    final_action_ref = f"final_actions.json#hold={hold.id}"
    spine_ref = f"chat.db#acceptance_spine={spine.spine_id}"
    dispatch_ref = f"chat_dispatch_queue#entry={dispatch.entry_id}"
    review_verdict_ref = f"review_plane.json#verdict={verdict_id}"
    _update_acceptance_gate_lane_projection(
        lanes_path=lanes_path,
        lane_id=lane_id,
        status=lane_projection_status,
        final_action_ref=final_action_ref,
        acceptance_spine_ref=spine_ref,
        dispatch_ref=dispatch_ref,
        review_verdict_ref=review_verdict_ref,
        github_gate_evidence_ref=resolved_hold.github_gate_evidence_ref,
        github_gate_gap_ref=resolved_hold.github_gate_gap_ref,
        blocked_reason=spine.blocked_reason
        if lane_projection_status == "blocked_for_input"
        else None,
        failure_reason=spine.blocked_reason if lane_projection_status == "failed" else None,
    )
    return {
        "status": terminal_status,
        "blocked_reason": spine.blocked_reason,
        "conversation_id": conversation_id,
        "spine_id": spine.spine_id,
        "lane_id": lane_id,
        "final_action_id": hold.id,
        "durable_refs": {
            "chat_db": str(chat_db_path),
            "spine_ref": spine_ref,
            "intake_message_ref": f"chat.db#message={intake.message.id}",
            "proposal_ref": f"chat.db#proposal={proposal.id}",
            "dispatch_ref": dispatch_ref,
            "review_verdict_ref": review_verdict_ref,
            "final_action_ref": final_action_ref,
            "github_gate_evidence_ref": github_ref,
        },
    }


async def run(
    lanes_path: Path,
    xmuse_root: Path,
    mcp_port: int,
    max_hours: float,
    max_concurrent: int,
    graph_id: str | None = None,
    resolution_id: str | None = None,
    require_final_action_approval: bool = False,
    god_runtime: str | None = None,
    auto_evolve: bool = False,
    blueprint_path: Path | None = None,
    decomposer_kind: str = "single",
    chat_driver_enabled: bool = False,
    chat_driver_model: str = DEFAULT_CODEX_GOD_MODEL_ID,
    peer_chat_enabled: bool = False,
    persistent_review_god_enabled: bool = False,
    persistent_review_timeout_s: float | None = None,
    default_review_peer_routing_enabled: bool = False,
    persistent_execute_god_enabled: bool = False,
    peer_chat_scheduler=None,
    peer_god_backend: str | None = None,
    peer_chat_response_wait_s: float = 900.0,
    peer_chat_post_writeback_grace_s: float = 8.0,
    peer_chat_dispatch_response_wait_s: float = 300.0,
    peer_chat_memoryos_url: str | None = None,
    memoryos_url: str | None = None,
    model_policy: CodexModelPolicy | None = None,
    execution_provider_profile_ref: str | None = None,
    review_provider_profile_ref: str | None = None,
) -> None:
    runner_id = _default_runner_id()
    control_service = CoordinatorControlService(
        xmuse_root=xmuse_root,
        runner_id=runner_id,
    )
    writer_lease: dict[str, Any] | None = None
    writer_lease_heartbeat_task: asyncio.Task | None = None
    writer_lease_heartbeat_stop: asyncio.Event | None = None
    writer_lease_lost: asyncio.Event | None = None
    in_flight: set[asyncio.Task] = set()
    in_flight_lane_ids: set[str] = set()
    reconcile_task: asyncio.Task | None = None
    runtime_god_layers: list[Any] = []
    chat_dispatch_bridge = None
    try:
        memoryos_client = (
            MemoryOSClient(base_url=memoryos_url)
            if memoryos_url is not None
            else None
        )
        peer_chat_memoryos_client = (
            PeerChatMemoryOSClient(
                base_url=peer_chat_memoryos_url,
                api_key=os.environ.get("XMUSE_PEER_CHAT_MEMORYOS_API_KEY"),
            )
            if peer_chat_memoryos_url is not None
            else None
        )
        from xmuse_core.agents.god_session_layer import GodSessionLayer
        from xmuse_core.agents.launchers import build_default_launchers

        if model_policy is not None:
            launchers = build_default_launchers(
                mcp_port=mcp_port,
                codex_model=model_policy.review_model,
            )
        else:
            launchers = build_default_launchers(mcp_port=mcp_port)
        if (
            persistent_review_god_enabled or persistent_execute_god_enabled
        ) and not _has_persistent_session_launcher(launchers):
            raise RuntimeError(
                "--persistent-review-god/--persistent-execute-god requires "
                "a launcher that supports xmuse persistent sessions"
            )
        writer_lease = _acquire_writer_lease(lanes_path, runner_id=runner_id)
        control_service.record_lifecycle(
            "writer_lease_acquired",
            details={
                "lanes_path": str(lanes_path),
                "lease_id": str(writer_lease["lease_id"]),
            },
        )
        god_session_layer = GodSessionLayer(
            registry_path=xmuse_root / "god_sessions.json",
            launchers=launchers,
        )
        orchestrator_kwargs: dict[str, Any] = {
            "lanes_path": lanes_path,
            "xmuse_root": xmuse_root,
            "mcp_port": mcp_port,
            "require_final_action_approval": require_final_action_approval,
            "god_runtime": god_runtime,
            "runner_id": runner_id,
            "memoryos_client": memoryos_client,
            "review_god_session_layer": None,
        }
        if persistent_review_god_enabled:
            review_god_layer = _build_review_god_layer(
                backend=os.environ.get("XMUSE_REVIEW_GOD_BACKEND", "ray"),
                native_layer=god_session_layer,
                launchers=launchers,
                xmuse_root=xmuse_root,
            )
            prewarm = getattr(review_god_layer, "prewarm", None)
            if callable(prewarm):
                await prewarm()
            orchestrator_kwargs["review_god_session_layer"] = review_god_layer
            runtime_god_layers.append(review_god_layer)
        if persistent_review_timeout_s is not None:
            orchestrator_kwargs["persistent_review_receive_timeout_s"] = (
                persistent_review_timeout_s
            )
        if model_policy is not None:
            orchestrator_kwargs["model_policy"] = model_policy
        if default_review_peer_routing_enabled:
            orchestrator_kwargs["default_review_peer_routing_enabled"] = True
        if persistent_execute_god_enabled:
            execute_god_layer = _build_execution_god_layer(
                backend=os.environ.get("XMUSE_EXECUTE_GOD_BACKEND", "ray"),
                native_layer=god_session_layer,
                launchers=launchers,
                xmuse_root=xmuse_root,
            )
            prewarm = getattr(execute_god_layer, "prewarm", None)
            if callable(prewarm):
                await prewarm()
            orchestrator_kwargs["persistent_execute_enabled"] = True
            orchestrator_kwargs["persistent_execute_session_layer"] = execute_god_layer
            runtime_god_layers.append(execute_god_layer)
        if execution_provider_profile_ref is not None:
            orchestrator_kwargs["execution_provider_profile_ref"] = (
                execution_provider_profile_ref
            )
        if review_provider_profile_ref is not None:
            orchestrator_kwargs["review_provider_profile_ref"] = review_provider_profile_ref

        watcher: TerminalRunWatcher | None = None
        if auto_evolve:
            decomposer = _build_decomposer(decomposer_kind)
            controller = SelfEvolutionController(
                xmuse_root=xmuse_root,
                blueprint_path=blueprint_path or DEFAULT_BLUEPRINT,
                decomposer=decomposer,
            )
            watcher = TerminalRunWatcher(controller)
            logger.info(
                "Auto-evolve enabled (blueprint=%s, decomposer=%s)",
                controller._blueprint_path,
                decomposer_kind,
            )

        chat_driver: ChatDriver | None = None
        if chat_driver_enabled:
            chat_driver = ChatDriver(
                chat_db_path=xmuse_root / "chat.db",
                model=chat_driver_model,
            )
            logger.info("Chat driver enabled (model=%s)", chat_driver_model)

        if (
            peer_chat_enabled
            and peer_chat_scheduler is None
            and _has_persistent_session_launcher(launchers)
        ):
            from xmuse_core.chat.peer_scheduler import PeerChatScheduler

            peer_god_layer = _build_peer_god_layer(
                backend=peer_god_backend
                or os.environ.get("XMUSE_PEER_GOD_BACKEND", DEFAULT_PEER_GOD_BACKEND),
                native_layer=god_session_layer,
                launchers=launchers,
                xmuse_root=xmuse_root,
            )
            peer_god_layer = await _prewarm_peer_god_layer_or_fallback(
                peer_god_layer,
                native_layer=god_session_layer,
            )
            runtime_god_layers.append(peer_god_layer)
            if orchestrator_kwargs["review_god_session_layer"] is None:
                orchestrator_kwargs["review_god_session_layer"] = peer_god_layer
            peer_chat_worktree = _peer_chat_runtime_worktree(xmuse_root)
            peer_chat_claim_ttl_s = max(
                240,
                int(
                    math.ceil(
                        peer_chat_response_wait_s
                        + peer_chat_post_writeback_grace_s
                        + 30.0
                    )
                ),
            )
            peer_chat_dispatch_claim_ttl_s = max(
                240,
                int(math.ceil(peer_chat_dispatch_response_wait_s + 30.0)),
            )
            peer_chat_scheduler = PeerChatScheduler(
                db_path=xmuse_root / "chat.db",
                god_layer=peer_god_layer,
                worktree=peer_chat_worktree,
                scheduler_id="platform-runner",
                claim_ttl_s=peer_chat_claim_ttl_s,
                response_wait_s=peer_chat_response_wait_s,
                post_writeback_grace_s=peer_chat_post_writeback_grace_s,
                degraded_fallback_enabled=False,
                memoryos_client=peer_chat_memoryos_client,
            )
            logger.info(
                "Peer chat scheduler enabled (god_backend=%s)",
                type(peer_god_layer).__name__,
            )
            from xmuse_core.chat.dispatch_bridge import ChatDispatchBridge

            chat_dispatch_bridge = ChatDispatchBridge(
                db_path=xmuse_root / "chat.db",
                god_layer=peer_god_layer,
                worktree=peer_chat_worktree,
                bridge_id="platform-runner-dispatch",
                claim_ttl_s=peer_chat_dispatch_claim_ttl_s,
                response_wait_s=peer_chat_dispatch_response_wait_s,
                memoryos_client=peer_chat_memoryos_client,
            )
        elif peer_chat_enabled and peer_chat_scheduler is None:
            logger.warning(
                "Peer chat scheduler disabled: no launcher supports xmuse persistent sessions"
            )

        orch = PlatformOrchestrator(**orchestrator_kwargs)

        shutdown = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                loop.add_signal_handler(sig, shutdown.set)
            except NotImplementedError:
                pass
        writer_lease_heartbeat_stop = asyncio.Event()
        writer_lease_lost = asyncio.Event()
        writer_lease_heartbeat_task = asyncio.create_task(
            _writer_lease_heartbeat_loop(
                lanes_path,
                lease_id=writer_lease["lease_id"],
                runner_id=runner_id,
                stop=writer_lease_heartbeat_stop,
                lost=writer_lease_lost,
            )
        )

        deadline = loop.time() + max_hours * 3600
        semaphore = asyncio.Semaphore(max_concurrent)
        blueprint_automation_service: BlueprintAutomationService | None = None
        logger.info("Platform started, max_hours=%.1f, concurrency=%d", max_hours, max_concurrent)
        control_service.record_lifecycle(
            "started",
            details={
                "lanes_path": str(lanes_path),
                "max_hours": max_hours,
                "max_concurrent": max_concurrent,
            },
        )

        while not shutdown.is_set() and loop.time() < deadline:
            if writer_lease_lost.is_set():
                raise RuntimeError(
                    "writer lease lost during heartbeat; refusing to continue dispatch"
                )
            renewed = _renew_writer_lease(
                lanes_path,
                lease_id=writer_lease["lease_id"],
                runner_id=runner_id,
            )
            if renewed is None:
                writer_lease_lost.set()
                raise RuntimeError(
                    "writer lease lost before reconcile; refusing to continue dispatch"
                )
            writer_lease = renewed
            _repair_stale_dispatched_lanes(orch, owned_lane_ids=in_flight_lane_ids)
            if blueprint_automation_service is None:
                blueprint_automation_service = BlueprintAutomationService(base_dir=xmuse_root)
            control_service.drive_blueprint_automation(
                blueprint_automation_service,
                worker_id=PLANNING_AUTOMATION_WORKER_ID,
            )
            if watcher is not None and not in_flight:
                control_service.drive_auto_evolve(watcher)
            if chat_driver is not None:
                control_service.drive_chat(chat_driver)
            if peer_chat_scheduler is not None:
                await control_service.tick_peer_chat_scheduler(
                    peer_chat_scheduler,
                    max_concurrent=max_concurrent,
                )
            if chat_dispatch_bridge is not None:
                await _tick_chat_dispatch_bridge(chat_dispatch_bridge, xmuse_root=xmuse_root)
            pending = _candidate_lanes(
                orch,
                graph_id=graph_id,
                resolution_id=resolution_id,
            )
            if pending:
                pending.sort(key=lambda lane: -lane.get("priority", 0))

                for lane in pending:
                    if writer_lease_lost.is_set():
                        raise RuntimeError(
                            "writer lease lost during heartbeat; refusing to dispatch lane"
                        )
                    if len(in_flight) >= max_concurrent:
                        done, in_flight = await asyncio.wait(
                            in_flight, return_when=asyncio.FIRST_COMPLETED
                        )
                        in_flight = set(in_flight)
                        if writer_lease_lost.is_set():
                            raise RuntimeError(
                                "writer lease lost during heartbeat; refusing to dispatch lane"
                            )
                    lane_id = lane["feature_id"]
                    logger.info(
                        "Dispatching lane: %s (priority=%d)", lane_id, lane.get("priority", 0)
                    )

                    async def _run(lid: str) -> None:
                        async with semaphore:
                            await orch.dispatch_lane(lid)

                    task = asyncio.create_task(_run(lane_id))
                    in_flight.add(task)
                    in_flight_lane_ids.add(lane_id)

                    def _discard_finished_lane_id(
                        _finished: asyncio.Task,
                        *,
                        finished_lane_id: str = lane_id,
                    ) -> None:
                        in_flight_lane_ids.discard(finished_lane_id)

                    task.add_done_callback(in_flight.discard)
                    task.add_done_callback(_discard_finished_lane_id)

            if reconcile_task is None or reconcile_task.done():
                reconcile_task = asyncio.create_task(
                    _reconcile_status_changes(orch, dispatch_reworking=False)
                )
                reconcile_task.add_done_callback(_log_background_task_exception)
            if pending:
                await asyncio.sleep(5.0)
            else:
                try:
                    idle_wait_s = 1.0 if peer_chat_scheduler is not None else 10.0
                    await asyncio.wait_for(shutdown.wait(), timeout=idle_wait_s)
                except TimeoutError:
                    pass

        if in_flight:
            await asyncio.gather(*in_flight, return_exceptions=True)
        logger.info("Platform shutting down")
    finally:
        control_service.record_lifecycle(
            "stopping",
            details={
                "lanes_path": str(lanes_path),
                "in_flight_count": len(in_flight),
            },
        )
        if reconcile_task is not None and not reconcile_task.done():
            reconcile_task.cancel()
            with suppress(asyncio.CancelledError):
                await reconcile_task
        if writer_lease_heartbeat_stop is not None:
            writer_lease_heartbeat_stop.set()
        if writer_lease_heartbeat_task is not None:
            writer_lease_heartbeat_task.cancel()
            with suppress(asyncio.CancelledError):
                await writer_lease_heartbeat_task
        if in_flight:
            for task in list(in_flight):
                if not task.done():
                    task.cancel()
            await asyncio.gather(*list(in_flight), return_exceptions=True)
            in_flight.clear()
            in_flight_lane_ids.clear()
        await _shutdown_runtime_god_layers(runtime_god_layers)
        if writer_lease is not None:
            _release_writer_lease(
                lanes_path,
                lease_id=writer_lease["lease_id"],
                runner_id=runner_id,
            )


def _default_runner_id() -> str:
    return f"runner-{os.getpid()}"


async def _shutdown_runtime_god_layers(layers: list[Any]) -> None:
    seen: set[int] = set()
    for layer in layers:
        layer_id = id(layer)
        if layer_id in seen:
            continue
        seen.add(layer_id)
        shutdown = getattr(layer, "shutdown", None)
        if not callable(shutdown):
            continue
        result = shutdown()
        if inspect.isawaitable(result):
            await result


def _writer_lease_path(lanes_path: Path) -> Path:
    return lanes_path.with_name(f"{lanes_path.name}.writer_lease.json")


@contextmanager
def _locked_writer_lease(lanes_path: Path):
    lease_path = _writer_lease_path(lanes_path)
    lock_path = lease_path.with_name(f"{lease_path.name}.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield lease_path
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)


def _read_writer_lease(lease_path: Path) -> dict[str, Any] | None:
    if not lease_path.exists():
        return None
    return json.loads(lease_path.read_text(encoding="utf-8"))


def _lease_is_active(lease: dict[str, Any] | None, *, now: float) -> bool:
    if not isinstance(lease, dict):
        return False
    expires_at = lease.get("expires_at")
    return (
        isinstance(expires_at, (int, float))
        and not isinstance(expires_at, bool)
        and now < expires_at
    )


def _acquire_writer_lease(
    lanes_path: Path,
    *,
    runner_id: str,
    now: float | None = None,
    ttl_s: float = WRITER_LEASE_TTL_S,
) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    with _locked_writer_lease(lanes_path) as lease_path:
        existing = _read_writer_lease(lease_path)
        if _lease_is_active(existing, now=current_time):
            existing_runner_id = existing.get("runner_id")
            if existing_runner_id != runner_id:
                raise RuntimeError(
                    "active writer lease already held by "
                    f"{existing_runner_id} until {existing.get('expires_at')}"
                )
        reclaimed_from_runner_id = None
        if isinstance(existing, dict) and not _lease_is_active(existing, now=current_time):
            reclaimed_from_runner_id = existing.get("runner_id")
        lease = {
            "runner_id": runner_id,
            "lease_id": f"lease-{uuid.uuid4().hex[:12]}",
            "heartbeat_at": current_time,
            "expires_at": current_time + ttl_s,
        }
        if reclaimed_from_runner_id and reclaimed_from_runner_id != runner_id:
            lease["reclaimed_from_runner_id"] = reclaimed_from_runner_id
        lease_path.write_text(json.dumps(lease, indent=2) + "\n", encoding="utf-8")
        return lease


def _renew_writer_lease(
    lanes_path: Path,
    *,
    lease_id: str,
    runner_id: str,
    now: float | None = None,
    ttl_s: float = WRITER_LEASE_TTL_S,
) -> dict[str, Any] | None:
    current_time = time.time() if now is None else now
    with _locked_writer_lease(lanes_path) as lease_path:
        existing = _read_writer_lease(lease_path)
        if not isinstance(existing, dict):
            return None
        if existing.get("lease_id") != lease_id or existing.get("runner_id") != runner_id:
            return None
        existing["heartbeat_at"] = current_time
        existing["expires_at"] = current_time + ttl_s
        lease_path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")
        return existing


def _release_writer_lease(
    lanes_path: Path,
    *,
    lease_id: str,
    runner_id: str,
) -> None:
    with _locked_writer_lease(lanes_path) as lease_path:
        existing = _read_writer_lease(lease_path)
        if not isinstance(existing, dict):
            return
        if existing.get("lease_id") != lease_id or existing.get("runner_id") != runner_id:
            return
        lease_path.unlink(missing_ok=True)


async def _writer_lease_heartbeat_loop(
    lanes_path: Path,
    *,
    lease_id: str,
    runner_id: str,
    stop: asyncio.Event,
    lost: asyncio.Event,
    interval_s: float = WRITER_LEASE_RENEW_INTERVAL_S,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
            continue
        except TimeoutError:
            pass

        renewed = _renew_writer_lease(
            lanes_path,
            lease_id=lease_id,
            runner_id=runner_id,
        )
        if renewed is None:
            lost.set()
            stop.set()
            log_payload = {
                "runner_id": runner_id,
                "lease_id": lease_id,
                "lanes_path": str(lanes_path),
            }
            logger.error("writer lease heartbeat lost: %s", log_payload)
            return


def _drive_auto_evolve(watcher: TerminalRunWatcher) -> None:
    try:
        outcomes = watcher.tick()
    except Exception:
        logger.exception("auto-evolve tick failed; continuing")
        return
    for outcome in outcomes:
        if outcome.spawned is not None:
            logger.info(
                "auto-evolve: spawned %s from %s",
                outcome.spawned.spawned_graph_id,
                outcome.source_run_id,
            )
        elif outcome.skip_reason:
            logger.debug(
                "auto-evolve: skipped %s (%s)",
                outcome.source_run_id,
                outcome.skip_reason,
            )


def _drive_blueprint_automation(
    service: BlueprintAutomationService,
    *,
    worker_id: str,
) -> None:
    try:
        outcome = service.tick(worker_id=worker_id)
    except Exception:
        logger.exception("blueprint automation tick failed; continuing")
        return
    if outcome is not None:
        logger.info(
            "blueprint automation: started planning_run=%s from event=%s",
            outcome.planning_run_id,
            outcome.claimed_event_id,
        )


def _drive_chat(driver: ChatDriver) -> None:
    try:
        outcomes = driver.tick()
    except Exception:
        logger.exception("chat-driver tick failed; continuing")
        return
    for outcome in outcomes:
        if outcome.reply_message_id:
            logger.info(
                "chat-driver: %s replied in %s (envelope=%s)",
                outcome.god_role,
                outcome.conversation_id,
                outcome.envelope_type,
            )
        elif outcome.skip_reason:
            logger.warning(
                "chat-driver: %s skipped %s (%s)",
                outcome.god_role,
                outcome.source_message_id,
                outcome.skip_reason,
            )


async def _tick_chat_dispatch_bridge(chat_dispatch_bridge, *, xmuse_root: Path) -> None:
    from xmuse_core.chat.store import ChatStore

    try:
        conversations = ChatStore(xmuse_root / "chat.db").list_conversations()
    except Exception:
        logger.exception("chat dispatch bridge could not list conversations")
        return
    for conversation in conversations:
        try:
            await chat_dispatch_bridge.tick_once(conversation_id=conversation.id)
        except Exception:
            logger.exception(
                "chat dispatch bridge tick failed for conversation %s",
                conversation.id,
            )


async def _reconcile_status_changes(
    orch: PlatformOrchestrator,
    *,
    dispatch_reworking: bool,
) -> None:
    signature = inspect.signature(orch.reconcile_status_changes)
    if (
        "dispatch_reworking" in signature.parameters
        or any(
            parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in signature.parameters.values()
        )
    ):
        await orch.reconcile_status_changes(dispatch_reworking=dispatch_reworking)
        return
    await orch.reconcile_status_changes()


def _log_background_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    try:
        task.result()
    except Exception:
        logger.exception("background reconcile task failed")


def _build_decomposer(kind: str):
    """Pick the decomposer backend.

    ``single`` (default) is the backward-compatible one-rich-lane behavior.
    ``deterministic-multi`` produces a 3-lane design/impl/tests chain per
    track. ``peer-chat`` shells out to codex exec once per chain step and
    parses a multi-feature JSON plan; falls back to ``single`` on failure.
    Returning ``None`` lets the controller construct its built-in default.
    """
    if kind == "single":
        return None  # controller wires SingleLaneDecomposer with its own factories
    if kind == "deterministic-multi":
        from xmuse_core.self_evolution.decomposer import DeterministicMultiLaneDecomposer

        return DeterministicMultiLaneDecomposer()
    if kind == "peer-chat":
        from xmuse_core.self_evolution.decomposer import SingleLaneDecomposer
        from xmuse_core.self_evolution.peer_chat_decomposer import PeerChatDecomposer

        # Closures referencing the controller's per-track factories happen
        # *after* controller construction; here we use track-only fallback
        # factories so PeerChatDecomposer can degrade without controller refs.
        fallback = SingleLaneDecomposer(
            lane_id_factory=lambda evidence, track: (
                f"self-evolution-{track}-{evidence.source_run_id}"[:120]
            ),
            prompt_factory=lambda evidence, track: (
                f"Implement the next xmuse self-evolution improvement for "
                f"track {track}. Use evidence bundle {evidence.bundle_id}. "
                f"Preserve chat -> proposal -> approved resolution -> lane "
                f"graph -> execution as the mainline."
            ),
        )
        return PeerChatDecomposer(fallback=fallback)
    raise ValueError(f"unknown decomposer kind: {kind!r}")


def _candidate_lanes(
    orch: PlatformOrchestrator,
    *,
    graph_id: str | None,
    resolution_id: str | None,
) -> list[dict]:
    all_lanes = orch._sm.get_lanes()
    lane_status_by_id = {
        lane.get("feature_id"): lane.get("status")
        for lane in all_lanes
        if isinstance(lane.get("feature_id"), str)
    }
    lanes_by_id: dict[str, dict] = {}
    for status in ("pending", "reworking"):
        for lane in orch._sm.get_lanes(status=status):
            lane_id = lane.get("feature_id")
            if isinstance(lane_id, str):
                lanes_by_id[lane_id] = lane

    lanes = list(lanes_by_id.values())
    if graph_id is not None:
        lanes = [lane for lane in lanes if lane.get("graph_id") == graph_id]
    if resolution_id is not None:
        lanes = [lane for lane in lanes if lane.get("resolution_id") == resolution_id]
    legacy_candidates = [
        lane for lane in lanes
        if _dependencies_satisfied(lane, lane_status_by_id)
    ]
    ready_set_candidates = build_graph_ready_set(
        all_lanes,
        graph_id=graph_id,
        resolution_id=resolution_id,
    )
    parity_evidence = build_ready_set_parity_evidence(
        legacy_candidates=legacy_candidates,
        ready_set_candidates=ready_set_candidates,
        graph_id=graph_id,
        resolution_id=resolution_id,
    )
    return [
        {**lane, "ready_set_parity": dict(parity_evidence)}
        for lane in legacy_candidates
    ]


def _live_pids() -> set[int]:
    return list_live_pids()


def _has_persistent_session_launcher(launchers: dict[Any, object]) -> bool:
    return any(
        getattr(launcher, "supports_persistent_sessions", False) is True
        and callable(getattr(launcher, "build_persistent_command", None))
        for launcher in launchers.values()
    )


def _build_peer_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
):
    return _build_optional_ray_god_layer(
        backend=backend,
        native_layer=native_layer,
        launchers=launchers,
        xmuse_root=xmuse_root,
        purpose="peer",
    )


async def _prewarm_peer_god_layer_or_fallback(peer_god_layer, *, native_layer):
    prewarm = getattr(peer_god_layer, "prewarm", None)
    if not callable(prewarm):
        return peer_god_layer
    try:
        await prewarm()
    except Exception as exc:
        if not _degraded_local_god_mode_enabled():
            raise RuntimeError(
                f"Ray peer GOD backend unavailable and native fallback is disabled: {exc}"
            ) from exc
        logger.warning(
            "Ray peer GOD backend prewarm failed; degraded local mode using native: %s",
            exc,
        )
        return _mark_degraded_native_god_layer(
            native_layer,
            purpose="peer",
            reason="ray_unavailable_degraded_local_mode",
        )
    return peer_god_layer


def _build_review_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
):
    return _build_optional_ray_god_layer(
        backend=backend,
        native_layer=native_layer,
        launchers=launchers,
        xmuse_root=xmuse_root,
        purpose="review",
    )


def _build_execution_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
):
    return _build_optional_ray_god_layer(
        backend=backend,
        native_layer=native_layer,
        launchers=launchers,
        xmuse_root=xmuse_root,
        purpose="execution",
    )


def _build_optional_ray_god_layer(
    *,
    backend: str,
    native_layer,
    launchers: dict[Any, object],
    xmuse_root: Path,
    purpose: str,
):
    normalized = (backend or DEFAULT_PEER_GOD_BACKEND).strip().lower()
    if normalized in {"native", "local"}:
        return native_layer
    if normalized not in {"ray", "auto"}:
        raise RuntimeError(
            f"Unknown {purpose} GOD backend '{backend}'; "
            "native fallback requires explicit backend=native/local"
        )
    try:
        from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

        return RayGodSessionLayer(
            registry_path=xmuse_root / "god_sessions.json",
            db_path=xmuse_root / "chat.db",
            launchers=launchers,
        )
    except Exception as exc:
        if not _degraded_local_god_mode_enabled():
            raise RuntimeError(
                f"Ray {purpose} GOD backend unavailable and native fallback is disabled: {exc}"
            ) from exc
        logger.warning(
            "Ray %s GOD backend unavailable; degraded local mode using native: %s",
            purpose,
            exc,
        )
        return _mark_degraded_native_god_layer(
            native_layer,
            purpose=purpose,
            reason="ray_unavailable_degraded_local_mode",
        )


def _degraded_local_god_mode_enabled() -> bool:
    value = os.environ.get("XMUSE_DEGRADED_LOCAL_GOD_MODE", "")
    normalized = value.strip().lower()
    return normalized in {"1", "true", "yes", "on"}


def _mark_degraded_native_god_layer(native_layer, *, purpose: str, reason: str):
    setattr(native_layer, f"degraded_{purpose}_runtime", "native_exec_shim")
    setattr(native_layer, f"degraded_{purpose}_runtime_reason", reason)
    return native_layer


def health_once(
    lanes_path: Path,
    *,
    xmuse_root: Path | None = None,
    mcp_port: int = 8100,
    chat_api_url: str | None = None,
    check_http: bool = False,
    now: float | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    live_pids: set[int] | None = None,
) -> dict[str, Any]:
    """Return the same operational health summary used by stale repair."""
    process_inventory = discover_xmuse_runtime_processes(
        xmuse_root=xmuse_root or lanes_path.parent,
    )
    live_pid_set = _live_pids() if live_pids is None else live_pids
    summary = build_run_health_model(
        lanes_path,
        now=now,
        stale_after_s=stale_after_s,
        live_pids=live_pid_set,
        runner_pids=process_inventory["runner_pids"],
        mcp_pids=process_inventory["mcp_pids"],
        process_inventory=process_inventory,
    )
    summary["operations"] = _build_runtime_operations_health(
        xmuse_root=xmuse_root or lanes_path.parent,
        mcp_port=mcp_port,
        chat_api_url=chat_api_url,
        check_http=check_http,
        process_inventory=process_inventory,
    )
    return summary


def _build_runtime_operations_health(
    *,
    xmuse_root: Path,
    mcp_port: int,
    chat_api_url: str,
    check_http: bool,
    process_inventory: dict[str, Any],
) -> dict[str, Any]:
    chat_url = _normalize_base_url(chat_api_url)
    mcp_url = f"http://127.0.0.1:{mcp_port}/mcp"
    counts = process_inventory.get("counts_by_service") or {}
    runner_count = _service_count(counts, "runner")
    mcp_count = _service_count(counts, "mcp")
    chat_api_count = _service_count(counts, "chat_api")
    return {
        "ports": {
            "mcp": {"port": mcp_port, "url": mcp_url},
            "mcp_chat": {"port": mcp_port, "url": f"{mcp_url}/chat"},
            "chat_api": {"port": _url_port(chat_url, default=8201), "url": chat_url},
        },
        "readiness": {
            "chat_api": _endpoint_readiness(
                service_count=chat_api_count,
                url=f"{chat_url}/health",
                check_http=check_http,
            ),
            "mcp": _endpoint_readiness(
                service_count=mcp_count,
                url=f"http://127.0.0.1:{mcp_port}/health",
                check_http=check_http,
            ),
            "runner": _process_readiness(runner_count),
            "ray_god_layer": _ray_god_layer_readiness(),
            "codex_app_server": _codex_app_server_readiness(
                counts,
                runner_count=runner_count,
            ),
        },
        "durable_state": _durable_state_health(xmuse_root),
        "scheduler_progress": _scheduler_progress_health(xmuse_root / "chat.db"),
        "chat_dispatch_bridge": _chat_dispatch_bridge_health(xmuse_root / "chat.db"),
        "cleanup": _cleanup_health(counts, runner_count=runner_count),
    }


def _endpoint_readiness(
    *,
    service_count: int,
    url: str,
    check_http: bool,
) -> dict[str, Any]:
    if not check_http:
        return {
            "status": "observed" if service_count else "unchecked",
            "process_count": service_count,
            "check_url": url,
        }
    status_code = _http_status(url)
    return {
        "status": "ready" if status_code == 200 else "unreachable",
        "process_count": service_count,
        "check_url": url,
        "http_status": status_code,
    }


def _process_readiness(service_count: int) -> dict[str, Any]:
    if service_count == 1:
        status = "ready"
    elif service_count > 1:
        status = "duplicate"
    else:
        status = "missing"
    return {"status": status, "process_count": service_count}


def _ray_god_layer_readiness() -> dict[str, Any]:
    backend = (
        os.environ.get("XMUSE_PEER_GOD_BACKEND", DEFAULT_PEER_GOD_BACKEND).strip().lower()
        or DEFAULT_PEER_GOD_BACKEND
    )
    transport = os.environ.get("XMUSE_RAY_GOD_TRANSPORT", "app-server").strip().lower()
    mcp_enabled = os.environ.get("XMUSE_RAY_GOD_MCP", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    status = "native_configured" if backend in {"native", "local"} else "configured"
    return {
        "status": status,
        "backend": backend,
        "transport": "app-server" if transport in {"app-server", "appserver"} else transport,
        "mcp_enabled": mcp_enabled,
    }


def _codex_app_server_readiness(
    counts: dict[str, Any],
    *,
    runner_count: int,
) -> dict[str, Any]:
    count = _service_count(counts, "codex_app_server")
    if count == 0:
        status = "not_observed"
    elif runner_count == 0:
        status = "orphaned"
    else:
        status = "observed"
    return {"status": status, "process_count": count}


def _durable_state_health(xmuse_root: Path) -> dict[str, Any]:
    return {
        "chat_db": _state_file_health(xmuse_root / "chat.db"),
        "god_sessions": _state_file_health(xmuse_root / "god_sessions.json"),
    }


def _state_file_health(path: Path) -> dict[str, Any]:
    return {"path": str(path), "exists": path.exists()}


def _scheduler_progress_health(chat_db_path: Path) -> dict[str, Any]:
    if not chat_db_path.exists():
        return {"status": "missing_chat_db", "trace_count": 0}
    try:
        with sqlite3.connect(chat_db_path) as conn:
            table_exists = conn.execute(
                """
                select 1 from sqlite_master
                where type = 'table' and name = 'peer_turn_latency_traces'
                """
            ).fetchone()
            if table_exists is None:
                return {"status": "no_traces", "trace_count": 0}
            row = conn.execute(
                """
                select count(*) as trace_count, max(writeback_at) as last_writeback_at
                from peer_turn_latency_traces
                """
            ).fetchone()
            trace_count = int(row[0] or 0)
            if trace_count == 0:
                return {"status": "no_traces", "trace_count": 0}
            modes = [
                str(item[0])
                for item in conn.execute(
                    """
                    select distinct delivery_mode from peer_turn_latency_traces
                    order by delivery_mode
                    """
                ).fetchall()
                if item[0]
            ]
            return {
                "status": "observed",
                "trace_count": trace_count,
                "last_writeback_at": row[1],
                "delivery_modes": modes,
            }
    except sqlite3.Error as exc:
        return {
            "status": "unreadable",
            "trace_count": 0,
            "error": str(exc),
        }


def _chat_dispatch_bridge_health(chat_db_path: Path) -> dict[str, Any]:
    empty = {
        "status": "no_entries",
        "total": 0,
        "queued": 0,
        "processing": 0,
        "dispatched": 0,
        "failed": 0,
        "latest": None,
    }
    if not chat_db_path.exists():
        return {**empty, "status": "missing_chat_db"}
    try:
        with sqlite3.connect(chat_db_path) as conn:
            conn.row_factory = sqlite3.Row
            table_exists = conn.execute(
                """
                select 1 from sqlite_master
                where type = 'table' and name = 'chat_dispatch_queue'
                """
            ).fetchone()
            if table_exists is None:
                return empty
            rows = conn.execute(
                """
                select status, count(*) as c
                from chat_dispatch_queue
                group by status
                """
            ).fetchall()
            counts = {str(row["status"]): int(row["c"] or 0) for row in rows}
            total = sum(counts.values())
            if total == 0:
                return empty
            latest = conn.execute(
                """
                select
                    entry_id, conversation_id, status, source, target, auto_execute,
                    proposal_id, resolution_id, collaboration_run_id, artifact_ref,
                    dispatch_evidence
                from chat_dispatch_queue
                order by
                    coalesce(completed_at, updated_at, claimed_at, created_at) desc,
                    completed_at is not null desc,
                    rowid desc
                limit 1
                """
            ).fetchone()
            return {
                "status": "observed",
                "total": total,
                "queued": counts.get("queued", 0),
                "processing": counts.get("processing", 0),
                "dispatched": counts.get("dispatched", 0),
                "failed": counts.get("failed", 0),
                "latest": _chat_dispatch_bridge_latest(latest),
            }
    except sqlite3.Error as exc:
        return {
            **empty,
            "status": "unreadable",
            "error": str(exc),
        }


def _chat_dispatch_bridge_latest(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "entry_id": row["entry_id"],
        "conversation_id": row["conversation_id"],
        "status": row["status"],
        "source": row["source"],
        "target": row["target"],
        "auto_execute": bool(row["auto_execute"]),
        "proposal_id": row["proposal_id"],
        "resolution_id": row["resolution_id"],
        "collaboration_run_id": row["collaboration_run_id"],
        "artifact_ref": row["artifact_ref"],
        "dispatch_evidence": row["dispatch_evidence"],
    }


def _cleanup_health(counts: dict[str, Any], *, runner_count: int) -> dict[str, Any]:
    leftover_services = (
        "codex_app_server",
        "raylet",
        "gcs_server",
        "ray_worker",
    )
    leftovers = []
    if runner_count == 0:
        for service in leftover_services:
            count = _service_count(counts, service)
            if count:
                leftovers.append(
                    {
                        "code": f"leftover_{service}",
                        "service": service,
                        "count": count,
                        "action": "report_only",
                        "automated_cleanup": False,
                        "operator_action": "inspect_and_cleanup_manually",
                    }
                )
    return {
        "status": "dirty" if leftovers else "clean",
        "leftovers": leftovers,
    }


def _service_count(counts: dict[str, Any], service: str) -> int:
    value = counts.get(service, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _normalize_base_url(url: str | None) -> str:
    normalized = (
        url
        or os.environ.get("XMUSE_CHAT_API_URL")
        or "http://127.0.0.1:8201"
    ).strip().rstrip("/")
    return normalized or "http://127.0.0.1:8201"


def _url_port(url: str, *, default: int) -> int:
    parsed = urllib.parse.urlparse(url)
    return parsed.port or default


def _http_status(url: str) -> int | None:
    try:
        with urllib.request.urlopen(url, timeout=0.5) as response:
            return int(response.status)
    except (OSError, urllib.error.URLError):
        return None


def _repair_stale_dispatched_lanes(
    orch: PlatformOrchestrator,
    *,
    now: float | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    owned_lane_ids: set[str] | None = None,
) -> None:
    current_time = time.time() if now is None else now
    lanes = orch._sm.get_lanes(status="dispatched")
    if not lanes:
        return
    live_pids = _live_pids()
    health = summarize_run_health(
        lanes,
        now=current_time,
        stale_after_s=stale_after_s,
        live_pids=live_pids,
    )
    stale_ids = set(health["groups"]["stale"])
    owned = owned_lane_ids or set()
    for lane in lanes:
        lane_id = str(lane.get("feature_id") or "")
        worker_pid = lane.get("worker_pid")
        if (
            lane_id not in stale_ids
            or lane_id in owned
            or not isinstance(worker_pid, int)
            or isinstance(worker_pid, bool)
        ):
            continue
        metadata: dict[str, Any] = {
            "failure_reason": "stale_worker_lost",
            "stale_worker_pid": worker_pid,
            "stale_repaired_at": current_time,
        }
        logger.warning(
            "repairing stale dispatched lane: %s worker_pid=%s",
            lane_id,
            worker_pid,
        )
        orch._sm.transition_if_metadata(
            lane_id,
            "exec_failed",
            expected_metadata={
                "status": "dispatched",
                "worker_pid": worker_pid,
            },
            metadata=metadata,
        )


def _dependencies_satisfied(lane: dict, lane_status_by_id: dict[str, str | None]) -> bool:
    success_statuses = {"done", "merged", "completed"}
    for dependency_id in lane.get("depends_on", []):
        if lane_status_by_id.get(dependency_id) not in success_statuses:
            return False
    return True


def main_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="xmuse Platform Runner (MVP)")
    parser.add_argument(
        "--xmuse-root",
        type=Path,
        default=DEFAULT_XMUSE_ROOT,
        help="xmuse runtime root; defaults to XMUSE_ROOT or ./xmuse",
    )
    parser.add_argument(
        "--lanes",
        type=Path,
        default=None,
        help="lane projection path; defaults to <xmuse-root>/feature_lanes.json",
    )
    parser.add_argument("--mcp-port", type=int, default=8100)
    parser.add_argument("--max-hours", type=float, default=8.0)
    parser.add_argument("--max-concurrent", type=int, default=4)
    parser.add_argument("--graph-id")
    parser.add_argument("--resolution-id")
    parser.add_argument(
        "--require-final-action-approval",
        action="store_true",
        help="hold merge/terminate verdicts for external final-action approval",
    )
    parser.add_argument(
        "--no-auto-merge",
        action="store_true",
        help=(
            "runtime-probe safety mode: hold accepted lanes for final-action "
            "approval instead of auto-merging into the control branch"
        ),
    )
    parser.add_argument(
        "--god-runtime",
        choices=("codex",),
        default=None,
        help="GOD CLI runtime; xmuse is currently codex-only",
    )
    parser.add_argument(
        "--auto-evolve",
        action="store_true",
        help="auto-spawn next self-evolution run when a graph terminalizes",
    )
    parser.add_argument(
        "--blueprint",
        type=Path,
        default=DEFAULT_BLUEPRINT,
        help="path to the active EvolutionBlueprintSet markdown",
    )
    parser.add_argument(
        "--decomposer",
        choices=("single", "deterministic-multi", "peer-chat"),
        default="single",
        help="how to decompose each chain step into lanes",
    )
    parser.add_argument(
        "--chat-driver",
        action="store_true",
        help="enable multi-GOD chat driver (architect/review reply to human messages)",
    )
    parser.add_argument(
        "--chat-driver-model",
        default=DEFAULT_CODEX_GOD_MODEL_ID,
        help="Codex model for chat-driver GOD replies",
    )
    parser.add_argument(
        "--peer-chat",
        action="store_true",
        help="enable MCP peer-chat scheduler for long-lived GOD sessions",
    )
    parser.add_argument(
        "--peer-god-backend",
        choices=("ray", "auto", "native", "local"),
        default=None,
        help=(
            "backend for --peer-chat GOD sessions; native/local uses the "
            "provider-native persistent session layer without Ray"
        ),
    )
    parser.add_argument(
        "--peer-chat-response-wait-s",
        type=float,
        default=900.0,
        help=(
            "seconds to wait for ordinary peer-chat GOD turns to durably "
            "write back through MCP"
        ),
    )
    parser.add_argument(
        "--peer-chat-post-writeback-grace-s",
        type=float,
        default=8.0,
        help=(
            "seconds to keep a peer-chat turn open after a durable MCP writeback "
            "so the same provider turn can finish a short burst of tool calls"
        ),
    )
    parser.add_argument(
        "--peer-chat-dispatch-response-wait-s",
        type=float,
        default=300.0,
        help=("seconds to wait for execute peers to durably acknowledge dispatch-bridge handoffs"),
    )
    parser.add_argument(
        "--peer-chat-memoryos-url",
        default=os.environ.get("XMUSE_PEER_CHAT_MEMORYOS_URL"),
        help=(
            "optional MemoryOS REST base URL for natural peer-chat recall "
            "sidecar; does not create proposal/review/dispatch authority"
        ),
    )
    parser.add_argument(
        "--persistent-review-god",
        action="store_true",
        help=(
            "route review through long-lived GOD sessions; requires a launcher "
            "that speaks the xmuse persistent session protocol"
        ),
    )
    parser.add_argument(
        "--persistent-review-timeout-s",
        type=float,
        default=None,
        help=(
            "seconds to wait for a persistent Review GOD result before one-shot "
            "fallback; defaults to 1800 seconds"
        ),
    )
    parser.add_argument(
        "--default-review-peer-routing",
        action="store_true",
        help=(
            "with --persistent-review-god, create/reuse a default chat review "
            "peer per conversation feature and route review through that peer"
        ),
    )
    parser.add_argument(
        "--persistent-execute-god",
        action="store_true",
        help=(
            "route execution through long-lived Execute GOD sessions; requires a "
            "launcher that speaks the xmuse persistent session protocol"
        ),
    )
    parser.add_argument(
        "--execution-provider-profile-ref",
        default=None,
        help="provider profile ref override for execution transport, e.g. codex.default",
    )
    parser.add_argument(
        "--review-provider-profile-ref",
        default=None,
        help="provider profile ref override for review transport, e.g. codex.review",
    )
    parser.add_argument(
        "--codex-model-policy",
        choices=("tiered",),
        default=None,
        help=(
            "opt into codex-only tiered model policy metadata and model config"
        ),
    )
    parser.add_argument(
        "--review-model",
        default=None,
        help="Codex model for review layer when --codex-model-policy is enabled",
    )
    parser.add_argument(
        "--coordinator-model",
        default=None,
        help="Codex model for one-shot coordinator layer when policy is enabled",
    )
    parser.add_argument(
        "--worker-model",
        default=None,
        help="Codex model target for bounded workers when policy is enabled",
    )
    parser.add_argument(
        "--delegation-mode",
        choices=("legacy_single_agent", "bounded_worker"),
        default=None,
        help="delegation mode recorded when --codex-model-policy is enabled",
    )
    parser.add_argument(
        "--memoryos-url",
        default=None,
        help="optional MemoryOS API base URL for lane context and execution memory",
    )
    parser.add_argument(
        "--goal",
        default=None,
        help="short human demand for one acceptance-gated platform runner closure",
    )
    parser.add_argument(
        "--acceptance-gate",
        action="store_true",
        help=(
            "run one short durable goal through the AcceptanceSpine/final-action/"
            "GitHub gate producer and exit"
        ),
    )
    parser.add_argument(
        "--resolve-final-action",
        action="store_true",
        help=(
            "resolve an existing pending final-action hold through the GitHub "
            "gate producer and exit"
        ),
    )
    parser.add_argument(
        "--capture-final-action-main-ci",
        action="store_true",
        help=(
            "capture post-merge main CI truth for an existing accepted "
            "final-action GitHub gate evidence ref and exit"
        ),
    )
    parser.add_argument(
        "--create-final-action-pr",
        action="store_true",
        help=(
            "create a pull request from an existing pending merge final-action "
            "hold and exit; does not resolve the hold or claim CI/merge truth"
        ),
    )
    parser.add_argument(
        "--final-action-id",
        default=None,
        help="pending final-action hold id used by --resolve-final-action",
    )
    parser.add_argument(
        "--lane-id",
        default=None,
        help="lane id used by --resolve-final-action",
    )
    parser.add_argument(
        "--github-repo",
        default="iiyazu/Cross-Muse",
        help="GitHub owner/repo used by GitHub gate evidence capture",
    )
    parser.add_argument(
        "--pr-base-branch",
        default="main",
        help="base branch used by --create-final-action-pr",
    )
    parser.add_argument(
        "--pr-branch-prefix",
        default="codex/",
        help="remote branch prefix used by --create-final-action-pr",
    )
    parser.add_argument(
        "--pr-draft",
        action="store_true",
        help="create draft pull requests with --create-final-action-pr",
    )
    parser.add_argument(
        "--github-pr",
        type=int,
        default=None,
        help="GitHub pull request number bound to GitHub gate evidence",
    )
    parser.add_argument(
        "--github-head-sha",
        default=None,
        help=(
            "head SHA bound to GitHub gate evidence; defaults to current "
            "repository HEAD"
        ),
    )
    parser.add_argument(
        "--github-required-check",
        action="append",
        default=None,
        help=(
            "required check name for --acceptance-gate evidence; repeat to "
            "override the default xmuse required checks"
        ),
    )
    parser.add_argument(
        "--github-live-capture",
        action="store_true",
        help=(
            "opt into read-only gh api capture for server-side merge proof"
        ),
    )
    parser.add_argument(
        "--internal-review-artifact",
        type=Path,
        default=None,
        help="internal review artifact path bound to live GitHub review truth",
    )
    parser.add_argument(
        "--internal-reviewer",
        default=None,
        help="internal reviewer id bound to live GitHub review truth",
    )
    parser.add_argument(
        "--internal-reviewed-head-sha",
        default=None,
        help="PR head SHA reviewed by the internal review artifact",
    )
    parser.add_argument(
        "--health-once",
        action="store_true",
        help="print a JSON run health summary and exit without starting the runner",
    )
    parser.add_argument(
        "--health-check-http",
        action="store_true",
        help="with --health-once, probe Chat API and MCP /health endpoints",
    )
    parser.add_argument(
        "--stale-after-s",
        type=float,
        default=DEFAULT_STALE_AFTER_S,
        help="worker inactivity threshold used by --health-once",
    )
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.goal and not args.acceptance_gate:
        raise SystemExit("--goal requires --acceptance-gate")
    if args.acceptance_gate and args.resolve_final_action:
        raise SystemExit(
            "--acceptance-gate and --resolve-final-action are mutually exclusive"
        )
    if args.capture_final_action_main_ci and (
        args.acceptance_gate or args.resolve_final_action or args.create_final_action_pr
    ):
        raise SystemExit(
            "--capture-final-action-main-ci is mutually exclusive with "
            "--acceptance-gate, --resolve-final-action, and --create-final-action-pr"
        )
    if args.create_final_action_pr and (args.acceptance_gate or args.resolve_final_action):
        raise SystemExit(
            "--create-final-action-pr is mutually exclusive with --acceptance-gate "
            "and --resolve-final-action"
        )
    if args.acceptance_gate:
        if not args.goal or not args.goal.strip():
            raise SystemExit("--acceptance-gate requires --goal")
        if args.github_pr is None or args.github_pr <= 0:
            raise SystemExit("--acceptance-gate requires a positive --github-pr")
        if args.health_once:
            raise SystemExit("--acceptance-gate and --health-once are mutually exclusive")
    if args.resolve_final_action:
        if args.github_pr is None or args.github_pr <= 0:
            raise SystemExit("--resolve-final-action requires a positive --github-pr")
        if not (args.final_action_id or args.lane_id):
            raise SystemExit(
                "--resolve-final-action requires --final-action-id or --lane-id"
            )
        if args.health_once:
            raise SystemExit(
                "--resolve-final-action and --health-once are mutually exclusive"
            )
    if args.capture_final_action_main_ci:
        if not (args.final_action_id or args.lane_id):
            raise SystemExit(
                "--capture-final-action-main-ci requires --final-action-id or --lane-id"
            )
        if not args.github_live_capture:
            raise SystemExit("--capture-final-action-main-ci requires --github-live-capture")
        if args.health_once:
            raise SystemExit(
                "--capture-final-action-main-ci and --health-once are mutually exclusive"
            )
    if args.create_final_action_pr:
        if not (args.final_action_id or args.lane_id):
            raise SystemExit(
                "--create-final-action-pr requires --final-action-id or --lane-id"
            )
        if args.health_once:
            raise SystemExit(
                "--create-final-action-pr and --health-once are mutually exclusive"
            )
    if args.github_live_capture and (args.acceptance_gate or args.resolve_final_action):
        missing_live_args = [
            name
            for name, value in (
                ("--internal-review-artifact", args.internal_review_artifact),
                ("--internal-reviewer", args.internal_reviewer),
                ("--internal-reviewed-head-sha", args.internal_reviewed_head_sha),
            )
            if value is None or (isinstance(value, str) and not value.strip())
        ]
        if missing_live_args:
            raise SystemExit(
                "--github-live-capture requires "
                + ", ".join(missing_live_args)
            )
        if not Path(args.internal_review_artifact).is_file():
            raise SystemExit("--internal-review-artifact must be an existing file")
    if args.peer_chat and args.chat_driver:
        raise SystemExit("--peer-chat and --chat-driver are mutually exclusive")
    if args.default_review_peer_routing and not args.persistent_review_god:
        raise SystemExit(
            "--default-review-peer-routing requires --persistent-review-god"
        )
    if (
        not math.isfinite(args.peer_chat_response_wait_s)
        or args.peer_chat_response_wait_s <= 0
    ):
        raise SystemExit(
            "--peer-chat-response-wait-s must be a positive finite number"
        )
    if (
        not math.isfinite(args.peer_chat_post_writeback_grace_s)
        or args.peer_chat_post_writeback_grace_s < 0
    ):
        raise SystemExit(
            "--peer-chat-post-writeback-grace-s must be a non-negative finite number"
        )
    if (
        not math.isfinite(args.peer_chat_dispatch_response_wait_s)
        or args.peer_chat_dispatch_response_wait_s <= 0
    ):
        raise SystemExit(
            "--peer-chat-dispatch-response-wait-s must be a positive finite number"
        )
    if args.persistent_review_timeout_s is not None:
        if not args.persistent_review_god:
            raise SystemExit(
                "--persistent-review-timeout-s requires --persistent-review-god"
            )
        if (
            not math.isfinite(args.persistent_review_timeout_s)
            or args.persistent_review_timeout_s <= 0
        ):
            raise SystemExit(
                "--persistent-review-timeout-s must be a positive finite number"
            )
    model_override_args = (
        args.review_model,
        args.coordinator_model,
        args.worker_model,
        args.delegation_mode,
    )
    if any(value is not None for value in model_override_args) and not args.codex_model_policy:
        raise SystemExit(
            "--review-model/--coordinator-model/--worker-model/--delegation-mode "
            "require --codex-model-policy"
        )


def _model_policy_from_args(args: argparse.Namespace) -> CodexModelPolicy | None:
    return resolve_codex_model_policy(
        enabled=args.codex_model_policy == "tiered",
        review_model=args.review_model,
        coordinator_model=args.coordinator_model,
        worker_model=args.worker_model,
        delegation_mode=args.delegation_mode,
    )


def _runtime_paths_from_args(args: argparse.Namespace) -> tuple[Path, Path]:
    xmuse_root = resolve_xmuse_root(args.xmuse_root, fallback=DEFAULT_XMUSE_ROOT)
    lanes_path = args.lanes or (xmuse_root / "feature_lanes.json")
    return xmuse_root, lanes_path


def _peer_chat_runtime_worktree(xmuse_root: Path) -> Path:
    worktree = xmuse_root / "peer_chat_worktree"
    if _is_git_worktree(worktree):
        return worktree
    if worktree.exists():
        try:
            next(worktree.iterdir())
        except StopIteration:
            worktree.rmdir()
        else:
            logger.warning(
                "Peer chat worktree exists but is not a git worktree: %s",
                worktree,
            )
            return worktree
    worktree.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        ["git", "worktree", "add", "--detach", str(worktree), "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode == 0:
        return worktree
    logger.warning(
        "Failed to create git peer chat worktree at %s: %s",
        worktree,
        result.stderr.strip() or result.stdout.strip(),
    )
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree


def _is_git_worktree(path: Path) -> bool:
    if not path.exists():
        return False
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--is-inside-work-tree"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _current_git_head_sha(cwd: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    parser = main_arg_parser()
    args = parser.parse_args()
    validate_args(args)
    model_policy = _model_policy_from_args(args)
    xmuse_root, lanes_path = _runtime_paths_from_args(args)

    if args.acceptance_gate:
        github_gate_collector: GitHubGateTruthCollector | None = None
        main_ci_collector: GitHubMainCiTruthCollector | None = None
        if args.github_live_capture:
            github_client = GitHubCliServerSideTruthClient(
                internal_review_artifact=args.internal_review_artifact,
                internal_reviewer=args.internal_reviewer,
                internal_reviewed_head_sha=args.internal_reviewed_head_sha,
            )
            github_gate_collector = ReadOnlyGitHubServerSideTruthCollector(
                client=github_client
            )
            main_ci_collector = ReadOnlyGitHubMainCiTruthCollector(
                client=github_client
            )
        print(
            json.dumps(
                run_acceptance_gated_goal(
                    goal=args.goal,
                    xmuse_root=xmuse_root,
                    github_repo=args.github_repo,
                    github_pull_request=args.github_pr,
                    required_checks=args.github_required_check
                    or REQUIRED_GITHUB_CHECKS,
                    head_sha=args.github_head_sha
                    or args.internal_reviewed_head_sha,
                    github_gate_collector=github_gate_collector,
                    main_ci_collector=main_ci_collector,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.resolve_final_action:
        github_gate_collector: GitHubGateTruthCollector | None = None
        main_ci_collector: GitHubMainCiTruthCollector | None = None
        if args.github_live_capture:
            github_client = GitHubCliServerSideTruthClient(
                internal_review_artifact=args.internal_review_artifact,
                internal_reviewer=args.internal_reviewer,
                internal_reviewed_head_sha=args.internal_reviewed_head_sha,
            )
            github_gate_collector = ReadOnlyGitHubServerSideTruthCollector(
                client=github_client
            )
            main_ci_collector = ReadOnlyGitHubMainCiTruthCollector(
                client=github_client
            )
        print(
            json.dumps(
                resolve_existing_final_action_with_github_gate(
                    xmuse_root=xmuse_root,
                    lane_id=args.lane_id,
                    final_action_id=args.final_action_id,
                    github_repo=args.github_repo,
                    github_pull_request=args.github_pr,
                    required_checks=args.github_required_check
                    or REQUIRED_GITHUB_CHECKS,
                    head_sha=args.github_head_sha
                    or args.internal_reviewed_head_sha,
                    github_gate_collector=github_gate_collector,
                    main_ci_collector=main_ci_collector,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.capture_final_action_main_ci:
        github_client = GitHubCliServerSideTruthClient()
        print(
            json.dumps(
                capture_existing_final_action_main_ci(
                    xmuse_root=xmuse_root,
                    lane_id=args.lane_id,
                    final_action_id=args.final_action_id,
                    main_ci_collector=ReadOnlyGitHubMainCiTruthCollector(
                        client=github_client
                    ),
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.create_final_action_pr:
        print(
            json.dumps(
                create_final_action_pull_request(
                    xmuse_root=xmuse_root,
                    lane_id=args.lane_id,
                    final_action_id=args.final_action_id,
                    github_repo=args.github_repo,
                    base_branch=args.pr_base_branch,
                    branch_prefix=args.pr_branch_prefix,
                    draft=args.pr_draft,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.health_once:
        print(
            json.dumps(
                health_once(
                    lanes_path,
                    xmuse_root=xmuse_root,
                    mcp_port=args.mcp_port,
                    chat_api_url=os.environ.get("XMUSE_CHAT_API_URL"),
                    check_http=args.health_check_http,
                    stale_after_s=args.stale_after_s,
                ),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return

    asyncio.run(run(
        lanes_path=lanes_path,
        xmuse_root=xmuse_root,
        mcp_port=args.mcp_port,
        max_hours=args.max_hours,
        max_concurrent=args.max_concurrent,
        graph_id=args.graph_id,
        resolution_id=args.resolution_id,
        require_final_action_approval=(
            args.require_final_action_approval or args.no_auto_merge
        ),
        god_runtime=args.god_runtime,
        auto_evolve=args.auto_evolve,
        blueprint_path=args.blueprint,
        decomposer_kind=args.decomposer,
        chat_driver_enabled=args.chat_driver,
        chat_driver_model=args.chat_driver_model,
        peer_chat_enabled=args.peer_chat,
        peer_god_backend=args.peer_god_backend,
        persistent_review_god_enabled=args.persistent_review_god,
        persistent_review_timeout_s=args.persistent_review_timeout_s,
        default_review_peer_routing_enabled=args.default_review_peer_routing,
        persistent_execute_god_enabled=args.persistent_execute_god,
        peer_chat_response_wait_s=args.peer_chat_response_wait_s,
        peer_chat_post_writeback_grace_s=args.peer_chat_post_writeback_grace_s,
        peer_chat_dispatch_response_wait_s=args.peer_chat_dispatch_response_wait_s,
        peer_chat_memoryos_url=args.peer_chat_memoryos_url,
        memoryos_url=args.memoryos_url,
        model_policy=model_policy,
        execution_provider_profile_ref=args.execution_provider_profile_ref,
        review_provider_profile_ref=args.review_provider_profile_ref,
    ))


if __name__ == "__main__":
    main()
