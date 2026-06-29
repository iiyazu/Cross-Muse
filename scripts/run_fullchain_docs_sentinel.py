#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore

REPO_ROOT = Path(__file__).resolve().parents[1]
OPENCODE_MODEL = "opencode-go/deepseek-v4-flash"
CODEX_REVIEW_MODEL = "gpt-5.4"
DEFAULT_PEER_CHAT_POST_WRITEBACK_GRACE_S = 8.0
DEFAULT_PEER_CHAT_RESPONSE_WAIT_S = 900.0
SUPPORTED_EXPECTED_STATUSES = frozenset({"awaiting_final_action", "gate_failed"})


def main() -> int:
    args = _parse_args()
    run_root = args.run_root.resolve()
    execution_worktree = args.execution_worktree.resolve()
    run_root.mkdir(parents=True, exist_ok=True)
    execution_worktree.mkdir(parents=True, exist_ok=True)
    artifacts = run_root / "loop_driver_artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    repo_head_sha = _repo_head_sha()

    chat_port = args.chat_port or _free_port()
    mcp_port = args.mcp_port or _free_port()
    feature_id = args.feature_id
    lane_specs = _lane_specs_from_args(args)
    primary_spec = lane_specs[0]
    provider_readiness = _provider_readiness(
        review_provider_policy=args.review_provider,
        ray_god_mcp=args.ray_god_mcp,
    )
    commands = _commands_payload(
        run_root=run_root,
        execution_worktree=execution_worktree,
        chat_port=chat_port,
        mcp_port=mcp_port,
        feature_id=feature_id,
        lane_kind=primary_spec["lane_kind"],
        target_path=primary_spec["target_path"],
        expected_content=primary_spec["expected_content"],
        lane_specs=lane_specs,
        repo_head_sha=repo_head_sha,
        peer_chat_post_writeback_grace_s=args.peer_chat_post_writeback_grace_s,
        peer_chat_response_wait_s=args.peer_chat_response_wait_s,
        peer_god_backend=args.peer_god_backend,
        ray_god_mcp=args.ray_god_mcp,
        review_provider_policy=args.review_provider,
        selected_review_provider=provider_readiness["review_provider_selection"][
            "selected_provider"
        ],
        review_provider_fallback_reason=provider_readiness[
            "review_provider_selection"
        ].get("fallback_reason"),
    )
    _write_json(artifacts / "commands.json", commands)
    _write_json(artifacts / "provider_readiness.json", provider_readiness)
    (run_root / "commands.txt").write_text(
        "\n".join(f"{key}={value}" for key, value in commands.items()) + "\n",
        encoding="utf-8",
    )

    processes: list[subprocess.Popen[bytes]] = []
    try:
        processes.append(
            _start_chat_api(run_root, execution_worktree, chat_port, run_root / "logs")
        )
        processes.append(_start_mcp(run_root, mcp_port, run_root / "logs"))
        _wait_http_ok(f"http://127.0.0.1:{chat_port}/health", timeout_s=30)
        _wait_http_ok(f"http://127.0.0.1:{mcp_port}/health", timeout_s=30)
        processes.append(
            _start_runner(
                run_root=run_root,
                mcp_port=mcp_port,
                chat_port=chat_port,
                logs_dir=run_root / "logs",
                max_hours=args.max_hours,
                peer_chat_response_wait_s=args.peer_chat_response_wait_s,
                peer_chat_post_writeback_grace_s=args.peer_chat_post_writeback_grace_s,
                peer_god_backend=args.peer_god_backend,
                ray_god_mcp=args.ray_god_mcp,
            )
        )

        lane_label = "multilane" if len(lane_specs) > 1 else primary_spec["lane_kind"]
        created = _post_json(
            f"http://127.0.0.1:{chat_port}/api/chat/conversations",
            {
                "title": f"Runtime {lane_label} sentinel {feature_id}",
                "initial_participants": [
                    {
                        "role": "architect",
                        "provider_id": "codex",
                        "profile_id": "god",
                        "cli_kind": "codex",
                        "model": args.architect_model,
                        "display_name": "Architect GOD runtime sentinel",
                    },
                    {
                        "role": "execute",
                        "provider_id": "codex",
                        "profile_id": "worker",
                        "cli_kind": "codex",
                        "model": args.executor_model,
                        "display_name": "Execute GOD runtime sentinel",
                    },
                    _review_participant_spec(provider_readiness),
                ],
            },
        )
        _write_json(artifacts / "conversation_create.json", created)
        conversation_id = str(created["id"])

        demand = _sentinel_demand(
            feature_id=feature_id,
            lane_specs=lane_specs,
            provider_readiness=provider_readiness,
        )
        message = _post_json(
            f"http://127.0.0.1:{chat_port}/api/chat/conversations/{conversation_id}/messages",
            {
                "author": "operator-runtime-driver",
                "role": "human",
                "content": demand,
                "client_request_id": f"{feature_id}-human-demand",
            },
        )
        _write_json(artifacts / "human_message.json", message)

        proposal = _wait_for_open_lane_graph_proposal(
            run_root / "chat.db",
            conversation_id=conversation_id,
            timeout_s=args.proposal_timeout_s,
        )
        _write_json(artifacts / "proposal.json", proposal)
        proposal_review_trigger = _wait_for_proposal_review_trigger_terminal(
            run_root / "chat.db",
            conversation_id=conversation_id,
            proposal_id=str(proposal["id"]),
            timeout_s=args.proposal_review_timeout_s,
        )
        _write_json(
            artifacts / "proposal_review_trigger.json",
            proposal_review_trigger,
        )

        approval = _post_json(
            f"http://127.0.0.1:{chat_port}/api/chat/proposals/{proposal['id']}/approve",
            {
                "approved_by": ["operator-runtime-driver"],
                "approval_mode": "runtime_loop_manual_approval_no_auto_merge",
                "goal_summary": f"Approve runtime sentinel {feature_id}",
            },
        )
        _write_json(artifacts / "approval_response.json", approval)

        lanes = [
            _wait_for_lane(
                run_root / "feature_lanes.json",
                feature_id=spec["feature_id"],
                timeout_s=args.lane_timeout_s,
            )
            for spec in lane_specs
        ]
        snapshot = _build_run_snapshot(
            run_root=run_root,
            conversation_id=conversation_id,
            feature_id=feature_id,
            lane_specs=lane_specs,
            proposal=proposal,
            lanes=lanes,
            provider_readiness=provider_readiness,
        )
        success_checks = _success_checks(snapshot)
        snapshot["success_checks"] = success_checks
        _write_compact_json(artifacts / "success_checks.json", success_checks)
        _write_json(artifacts / "final_snapshot.json", snapshot)
        _write_json(run_root / "driver_output.json", snapshot)
        print(json.dumps(snapshot, indent=2, sort_keys=True))
        return 0 if all(snapshot["success_checks"].values()) else 2
    except Exception as exc:
        failure = {
            "error": type(exc).__name__,
            "message": str(exc),
            "run_root": str(run_root),
            "feature_id": feature_id,
        }
        _write_json(artifacts / "failure.json", failure)
        print(json.dumps(failure, indent=2, sort_keys=True), file=sys.stderr)
        return 1
    finally:
        for process in reversed(processes):
            _terminate_process(process)
        cleanup = {
            "chat_port_listening": _port_listening(chat_port),
            "mcp_port_listening": _port_listening(mcp_port),
        }
        _write_json(artifacts / "cleanup.json", cleanup)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a real xmuse fullchain sentinel."
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execution-worktree", type=Path, required=True)
    parser.add_argument("--feature-id", required=True)
    parser.add_argument(
        "--lane-kind",
        choices=["docs", "code"],
        default="docs",
        help="sentinel lane kind; docs preserves the historical default",
    )
    parser.add_argument(
        "--target-path",
        default=None,
        help=(
            "target path in the isolated execution worktree; optional for "
            "docs mode, required for code mode"
        ),
    )
    parser.add_argument(
        "--expected-content",
        default=None,
        help=(
            "exact expected file content without trailing newline; optional "
            "for docs mode, required for code mode"
        ),
    )
    parser.add_argument(
        "--lane-spec-json",
        default=None,
        help=(
            "optional JSON array of lane specs; each item requires feature_id, "
            "lane_kind, target_path, and expected_content; expected_status "
            "defaults to awaiting_final_action"
        ),
    )
    parser.add_argument(
        "--expected-status",
        choices=sorted(SUPPORTED_EXPECTED_STATUSES),
        default="awaiting_final_action",
        help=(
            "expected terminal lane status for the single-lane CLI; "
            "multi-lane runs use each JSON lane spec's expected_status"
        ),
    )
    parser.add_argument("--chat-port", type=int, default=None)
    parser.add_argument("--mcp-port", type=int, default=None)
    parser.add_argument("--proposal-timeout-s", type=float, default=900.0)
    parser.add_argument("--proposal-review-timeout-s", type=float, default=900.0)
    parser.add_argument("--lane-timeout-s", type=float, default=1200.0)
    parser.add_argument("--max-hours", type=float, default=0.75)
    parser.add_argument("--architect-model", default="gpt-5.4")
    parser.add_argument("--executor-model", default="gpt-5.4-mini")
    parser.add_argument(
        "--peer-chat-response-wait-s",
        type=float,
        default=DEFAULT_PEER_CHAT_RESPONSE_WAIT_S,
        help=(
            "seconds to wait for ordinary peer-chat GOD turns to durably "
            "write back through MCP"
        ),
    )
    parser.add_argument(
        "--peer-chat-post-writeback-grace-s",
        type=float,
        default=DEFAULT_PEER_CHAT_POST_WRITEBACK_GRACE_S,
        help=(
            "seconds to keep a peer-chat turn open after durable MCP writeback "
            "so provider-native result artifacts can be consumed"
        ),
    )
    parser.add_argument(
        "--peer-god-backend",
        choices=["native", "ray", "auto"],
        default="native",
        help=(
            "peer-chat GOD backend for the sentinel; native is a bounded shim, "
            "ray exercises Codex app-server peer sessions"
        ),
    )
    parser.add_argument(
        "--ray-god-mcp",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="enable xmuse MCP tools for Ray/Codex app-server GOD turns",
    )
    parser.add_argument(
        "--review-provider",
        choices=["auto", "opencode", "codex"],
        default="auto",
        help=(
            "review participant runtime for the sentinel; auto prefers OpenCode "
            "when the opencode CLI is available and otherwise records an "
            "opencode_unavailable fallback to Codex"
        ),
    )
    return parser.parse_args()


def _lane_specs_from_args(args: argparse.Namespace) -> list[dict[str, str]]:
    raw_specs = getattr(args, "lane_spec_json", None)
    if raw_specs is None:
        target = _target_spec(
            feature_id=args.feature_id,
            lane_kind=args.lane_kind,
            target_path=args.target_path,
            expected_content=args.expected_content,
        )
        return [
            {
                "feature_id": args.feature_id,
                "lane_kind": args.lane_kind,
                "target_path": target["path"],
                "expected_content": target["expected_content"],
                "expected_status": _expected_status_from_value(
                    getattr(args, "expected_status", "awaiting_final_action"),
                    label=args.feature_id,
                ),
            }
        ]
    try:
        parsed = json.loads(raw_specs)
    except json.JSONDecodeError as exc:
        raise ValueError("--lane-spec-json must be valid JSON") from exc
    if not isinstance(parsed, list) or not parsed:
        raise ValueError("--lane-spec-json must be a non-empty JSON array")
    specs: list[dict[str, str]] = []
    seen_feature_ids: set[str] = set()
    seen_target_paths: set[str] = set()
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"lane spec at index {index} must be an object")
        feature_id = item.get("feature_id")
        lane_kind = item.get("lane_kind")
        if not isinstance(feature_id, str) or not feature_id.strip():
            raise ValueError(f"lane spec at index {index} requires feature_id")
        if not isinstance(lane_kind, str) or not lane_kind.strip():
            raise ValueError(f"lane spec {feature_id} requires lane_kind")
        target = _target_spec(
            feature_id=feature_id,
            lane_kind=lane_kind,
            target_path=item.get("target_path")
            if isinstance(item.get("target_path"), str)
            else None,
            expected_content=item.get("expected_content")
            if isinstance(item.get("expected_content"), str)
            else None,
        )
        if feature_id in seen_feature_ids:
            raise ValueError(f"duplicate lane feature_id: {feature_id}")
        if target["path"] in seen_target_paths:
            raise ValueError(f"duplicate lane target_path: {target['path']}")
        expected_status = _expected_status_from_value(
            item.get("expected_status", "awaiting_final_action"),
            label=feature_id,
        )
        seen_feature_ids.add(feature_id)
        seen_target_paths.add(target["path"])
        specs.append(
            {
                "feature_id": feature_id,
                "lane_kind": lane_kind,
                "target_path": target["path"],
                "expected_content": target["expected_content"],
                "expected_status": expected_status,
            }
        )
    return specs


def _expected_status_from_value(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"lane spec {label} expected_status must be a non-empty string")
    expected_status = value.strip()
    if expected_status not in SUPPORTED_EXPECTED_STATUSES:
        supported = ", ".join(sorted(SUPPORTED_EXPECTED_STATUSES))
        raise ValueError(
            f"lane spec {label} unsupported expected_status {expected_status!r}; "
            f"supported: {supported}"
        )
    return expected_status


def _target_spec(
    *,
    feature_id: str,
    lane_kind: str,
    target_path: str | None,
    expected_content: str | None,
) -> dict[str, str]:
    if lane_kind == "docs":
        return {
            "path": _clean_target_path(target_path or f"docs/xmuse/{feature_id}.md"),
            "expected_content": expected_content or _expected_note_content(feature_id),
        }
    if lane_kind == "code":
        if not target_path or not target_path.strip():
            raise ValueError("--target-path is required for --lane-kind code")
        if expected_content is None or not expected_content.strip():
            raise ValueError("--expected-content is required for --lane-kind code")
        return {
            "path": _clean_target_path(target_path),
            "expected_content": expected_content,
        }
    raise ValueError(f"unsupported lane kind: {lane_kind}")


def _clean_target_path(path: str) -> str:
    clean = path.strip()
    if not clean:
        raise ValueError("target path must be non-empty")
    target = Path(clean)
    if target.is_absolute() or ".." in target.parts:
        raise ValueError("target path must be relative and stay inside the worktree")
    return clean


def _commands_payload(
    *,
    run_root: Path,
    execution_worktree: Path,
    chat_port: int,
    mcp_port: int,
    feature_id: str,
    lane_kind: str,
    target_path: str,
    expected_content: str,
    lane_specs: list[dict[str, str]],
    repo_head_sha: str,
    peer_chat_response_wait_s: float,
    peer_chat_post_writeback_grace_s: float,
    peer_god_backend: str,
    ray_god_mcp: bool,
    review_provider_policy: str,
    selected_review_provider: str,
    review_provider_fallback_reason: str | None,
) -> dict[str, Any]:
    return {
        "run_root": str(run_root),
        "execution_worktree": str(execution_worktree),
        "chat_port": chat_port,
        "mcp_port": mcp_port,
        "feature_id": feature_id,
        "lane_kind": lane_kind,
        "target_path": target_path,
        "note_path": target_path,
        "lane_specs": lane_specs,
        "lane_count": len(lane_specs),
        "repo_head_sha": repo_head_sha,
        "expected_content": expected_content,
        "expected_note_content": expected_content,
        "peer_chat_response_wait_s": peer_chat_response_wait_s,
        "peer_chat_post_writeback_grace_s": peer_chat_post_writeback_grace_s,
        "peer_god_backend": peer_god_backend,
        "ray_god_mcp": ray_god_mcp,
        "review_provider_policy": review_provider_policy,
        "selected_review_provider": selected_review_provider,
        "review_provider_fallback_reason": review_provider_fallback_reason,
    }


def _repo_head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git rev-parse HEAD failed: {result.stderr.strip() or result.stdout.strip()}"
        )
    head_sha = result.stdout.strip()
    if not head_sha:
        raise RuntimeError("git rev-parse HEAD returned an empty SHA")
    return head_sha


def _start_chat_api(
    run_root: Path,
    execution_worktree: Path,
    port: int,
    logs_dir: Path,
) -> subprocess.Popen[bytes]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["XMUSE_ROOT"] = str(run_root)
    env["XMUSE_CHAT_API_URL"] = f"http://127.0.0.1:{port}"
    env["XMUSE_EXECUTION_WORKTREE"] = str(execution_worktree)
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "import uvicorn\n"
        "from xmuse.chat_api import create_app\n"
        "root = Path(os.environ['XMUSE_ROOT'])\n"
        "worktree = Path(os.environ['XMUSE_EXECUTION_WORKTREE'])\n"
        "uvicorn.run(create_app(root, execution_worktree=worktree), "
        f"host='127.0.0.1', port={port}, log_level='info')\n"
    )
    return _spawn(
        [sys.executable, "-c", code],
        env=env,
        stdout_path=logs_dir / "chat_api.log",
    )


def _start_mcp(run_root: Path, port: int, logs_dir: Path) -> subprocess.Popen[bytes]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["XMUSE_ROOT"] = str(run_root)
    code = (
        "import os\n"
        "from pathlib import Path\n"
        "import uvicorn\n"
        "from xmuse.mcp_server import create_app\n"
        "root = Path(os.environ['XMUSE_ROOT'])\n"
        f"uvicorn.run(create_app(root), host='127.0.0.1', port={port}, log_level='info')\n"
    )
    return _spawn(
        [sys.executable, "-c", code],
        env=env,
        stdout_path=logs_dir / "mcp.log",
    )


def _start_runner(
    *,
    run_root: Path,
    mcp_port: int,
    chat_port: int,
    logs_dir: Path,
    max_hours: float,
    peer_chat_response_wait_s: float,
    peer_chat_post_writeback_grace_s: float,
    peer_god_backend: str,
    ray_god_mcp: bool,
) -> subprocess.Popen[bytes]:
    logs_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["XMUSE_ROOT"] = str(run_root)
    env["XMUSE_CHAT_API_URL"] = f"http://127.0.0.1:{chat_port}"
    env["XMUSE_PEER_GOD_BACKEND"] = peer_god_backend
    env["XMUSE_REVIEW_GOD_BACKEND"] = peer_god_backend
    env["XMUSE_EXECUTE_GOD_BACKEND"] = peer_god_backend
    env["XMUSE_RAY_GOD_MCP"] = "1" if ray_god_mcp else "0"
    return _spawn(
        [
            sys.executable,
            "-m",
            "xmuse.platform_runner",
            "--xmuse-root",
            str(run_root),
            "--mcp-port",
            str(mcp_port),
            "--max-hours",
            str(max_hours),
            "--max-concurrent",
            "4",
            "--peer-chat",
            "--persistent-review-god",
            "--default-review-peer-routing",
            "--no-auto-merge",
            "--require-final-action-approval",
            "--peer-god-backend",
            peer_god_backend,
            "--peer-chat-response-wait-s",
            str(peer_chat_response_wait_s),
            "--peer-chat-post-writeback-grace-s",
            str(peer_chat_post_writeback_grace_s),
        ],
        env=env,
        stdout_path=logs_dir / "platform_runner.log",
    )


def _spawn(
    command: list[str],
    *,
    env: dict[str, str],
    stdout_path: Path,
) -> subprocess.Popen[bytes]:
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    stream = stdout_path.open("ab")
    process = subprocess.Popen(
        command,
        cwd=REPO_ROOT,
        env=env,
        stdout=stream,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    pid_path = stdout_path.with_suffix(stdout_path.suffix + ".pid")
    pid_path.write_text(f"{process.pid}\n", encoding="utf-8")
    process._xmuse_log_stream = stream  # type: ignore[attr-defined]
    return process


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=10)
    stream = getattr(process, "_xmuse_log_stream", None)
    if stream is not None:
        with contextlib.suppress(Exception):
            stream.close()


def _sentinel_demand(
    *,
    feature_id: str,
    provider_readiness: dict[str, Any],
    lane_specs: list[dict[str, str]] | None = None,
    lane_kind: str | None = None,
    target_path: str | None = None,
    expected_content: str | None = None,
) -> str:
    if lane_specs is None:
        if lane_kind is None or target_path is None or expected_content is None:
            raise ValueError(
                "single-lane demand requires lane_kind, target_path, and "
                "expected_content"
            )
        lane_specs = [
            {
                "feature_id": feature_id,
                "lane_kind": lane_kind,
                "target_path": target_path,
                "expected_content": expected_content,
            }
        ]
    selection = provider_readiness["review_provider_selection"]
    selected_review_provider = str(selection["selected_provider"])
    fallback_reason = selection.get("fallback_reason")
    fallback_clause = (
        "OpenCode was not selected because provider readiness recorded "
        f"`{fallback_reason}`; do not claim OpenCode was verified. "
        if fallback_reason
        else ""
    )
    proposal_lane_clause = (
        f"The proposal must contain one lane with feature_id `{feature_id}`. "
        if len(lane_specs) == 1
        else (
            "The proposal must contain exactly "
            f"{len(lane_specs)} lanes with the exact feature_ids listed in "
            "<lane_specs>. "
        )
    )
    common = (
        "Use the structured collaboration tools before proposing execution: "
        "create a collaboration request to @execute, have execute record an "
        "execute_feasibility_verdict with status executable and at least one "
        "evidence ref, then emit exactly one lane_graph proposal referencing "
        f"that collaboration run. {proposal_lane_clause}"
    )
    review_clause = (
        "Do not include review_runtime; rely on the "
        f"registered {selected_review_provider} review participant. "
        f"{fallback_clause}"
    )
    forbidden_claims = (
        "Do not claim production readiness, GitHub review truth, live MemoryOS, "
        "overnight readiness, full L8-L10 closure, or full L1-L11 closure."
    )
    if len(lane_specs) > 1:
        spec_text = "\n".join(_lane_spec_demand_block(spec) for spec in lane_specs)
        return (
            "@architect Run a real low-risk xmuse multi-lane runtime sentinel. "
            f"{common}"
            "The lane_graph must contain exactly one lane for each item in "
            "<lane_specs>. Keep all lanes independent with empty depends_on "
            "unless the item explicitly says otherwise. Each lane prompt must "
            "instruct the worker to modify exactly one target file, and that "
            "target file must be the lane item's target_path. The complete file "
            "content after execution must be exactly the text inside that "
            "lane item's <expected_content> block, followed by one trailing "
            "newline. A lane with expected_status=\"gate_failed\" is an "
            "intentional bounded failure-isolation lane: it must still create "
            "the exact artifact, but the gate is expected to fail and must not "
            "fabricate a review verdict or final-action hold for that lane. "
            "Do not combine lane artifacts into one file. "
            "<lane_specs>\n"
            f"{spec_text}\n"
            "</lane_specs>\n"
            "Keep this as a bounded multi-lane sentinel, not a docs-only "
            "single-lane replay. Do not edit unrelated files, PR #43, MemoryOS "
            "authority stores, TUI, or GitHub-truth code. "
            f"{review_clause}"
            f"{forbidden_claims}"
        )
    only_spec = lane_specs[0]
    if only_spec["lane_kind"] == "code":
        return (
            "@architect Run a real low-risk xmuse code-change runtime sentinel. "
            f"{common}"
            "The lane prompt must instruct the worker to modify exactly one "
            f"target file, `{only_spec['target_path']}`, in the isolated execution worktree. "
            "The complete file content after execution must be exactly the text "
            "inside <expected_content> below, followed by one trailing newline. "
            "<expected_content>\n"
            f"{only_spec['expected_content']}\n"
            "</expected_content>\n"
            "Keep the lane as a bounded code-change lane, not a docs-only sentinel. "
            "Do not edit unrelated files, PR #43, MemoryOS authority stores, TUI, "
            "or GitHub-truth code. "
            f"{review_clause}"
            f"{forbidden_claims}"
        )
    return (
        "@architect Run a real docs-only xmuse runtime sentinel. "
        f"{common}"
        "The lane prompt must instruct the worker "
        f"to create or overwrite `{only_spec['target_path']}` in the isolated execution "
        "worktree with one concise sentence: "
        f"`{only_spec['expected_content']}` "
        "Keep the lane docs-only. Do not include review_runtime; rely on the "
        f"registered {selected_review_provider} review participant. "
        f"{fallback_clause}"
        "Do not edit production code, "
        "tests, PR #43, MemoryOS, TUI, or GitHub-truth code. Do not claim "
        "production readiness, GitHub review truth, live MemoryOS, overnight "
        "readiness, full L8-L10 closure, or full L1-L11 closure."
    )


def _lane_spec_demand_block(spec: dict[str, str]) -> str:
    return (
        f"<lane feature_id=\"{spec['feature_id']}\" "
        f"lane_kind=\"{spec['lane_kind']}\" "
        f"target_path=\"{spec['target_path']}\" "
        f"expected_status=\"{spec.get('expected_status', 'awaiting_final_action')}\" "
        "depends_on=\"\">\n"
        "<expected_content>\n"
        f"{spec['expected_content']}\n"
        "</expected_content>\n"
        "</lane>"
    )


def _expected_note_content(feature_id: str) -> str:
    return f"Post-main fullchain sentinel {feature_id} reached isolated execution."


def _wait_for_open_lane_graph_proposal(
    db_path: Path,
    *,
    conversation_id: str,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        proposals = ChatStore(db_path).list_proposals(conversation_id)
        for proposal in proposals:
            if proposal.status.value != "open":
                continue
            if proposal.proposal_type != "lane_graph":
                continue
            payload = proposal.model_dump(mode="json")
            parsed = _json_or_none(proposal.content)
            if isinstance(parsed, dict):
                payload["parsed_content"] = parsed
            return payload
        time.sleep(5)
    raise TimeoutError(f"no open lane_graph proposal for {conversation_id}")


def _wait_for_proposal_review_trigger_terminal(
    db_path: Path,
    *,
    conversation_id: str,
    proposal_id: str,
    timeout_s: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        trigger = _proposal_review_trigger(
            db_path,
            conversation_id=conversation_id,
            proposal_id=proposal_id,
        )
        if trigger is not None:
            latest = trigger.model_dump(mode="json")
            if trigger.status == "read":
                return latest
            if trigger.status == "failed":
                raise RuntimeError(
                    f"proposal review trigger failed: {trigger.id}:{trigger.failure_reason}"
                )
        time.sleep(5)
    if latest is not None:
        raise TimeoutError(
            f"proposal review trigger did not finish: {latest['id']}:{latest['status']}"
        )
    raise TimeoutError(f"no proposal review trigger for {proposal_id}")


def _proposal_review_trigger(
    db_path: Path,
    *,
    conversation_id: str,
    proposal_id: str,
):
    proposal_message_id = None
    for message in ChatStore(db_path).list_messages(conversation_id):
        if (
            message.envelope_type == "proposal"
            and message.envelope_json.get("proposal_id") == proposal_id
        ):
            proposal_message_id = message.id
            break
    if proposal_message_id is None:
        return None
    for item in ChatInboxStore(db_path).list_by_conversation(
        conversation_id,
        include_terminal=True,
    ):
        if item.item_type == "review_trigger" and item.source_message_id == proposal_message_id:
            return item
    return None


def _wait_for_lane(lanes_path: Path, *, feature_id: str, timeout_s: float) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    latest: dict[str, Any] | None = None
    while time.monotonic() < deadline:
        if lanes_path.exists():
            try:
                payload = json.loads(lanes_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                payload = {}
            for lane in payload.get("lanes", []):
                if not isinstance(lane, dict):
                    continue
                if lane.get("feature_id") != feature_id:
                    continue
                latest = lane
                if lane.get("status") in {
                    "awaiting_final_action",
                    "merged",
                    "gate_failed",
                    "exec_failed",
                    "rejected",
                    "failed",
                }:
                    return lane
        time.sleep(5)
    if latest is not None:
        return latest
    raise TimeoutError(f"lane not projected for {feature_id}")


def _build_snapshot(
    *,
    run_root: Path,
    conversation_id: str,
    feature_id: str,
    lane_kind: str,
    expected_target_path: str,
    expected_target_content: str,
    proposal: dict[str, Any],
    lane: dict[str, Any],
    provider_readiness: dict[str, Any],
) -> dict[str, Any]:
    participants = [
        participant.model_dump(mode="json")
        for participant in ParticipantStore(run_root / "chat.db").list_by_conversation(
            conversation_id
        )
    ]
    proposals = _conversation_proposals(run_root / "chat.db", conversation_id)
    current_proposal = next(
        (
            candidate
            for candidate in proposals
            if candidate.get("id") == proposal.get("id")
        ),
        proposal,
    )
    related_lane_graph_proposals = [
        candidate
        for candidate in proposals
        if candidate.get("proposal_type") == "lane_graph"
        and feature_id in _proposal_feature_ids(candidate)
    ]
    messages = [
        message.model_dump(mode="json")
        for message in ChatStore(run_root / "chat.db").list_messages(conversation_id)
    ]
    return {
        "classification": f"{lane_kind}_fullchain_sentinel",
        "run_root": str(run_root),
        "conversation_id": conversation_id,
        "feature_id": feature_id,
        "lane_kind": lane_kind,
        "target_path": expected_target_path,
        "provider_readiness": provider_readiness,
        "selected_review_provider": provider_readiness["review_provider_selection"][
            "selected_provider"
        ],
        "review_provider_fallback_reason": provider_readiness[
            "review_provider_selection"
        ].get("fallback_reason"),
        "proposal": current_proposal,
        "proposal_has_review_runtime": _proposal_has_review_runtime(current_proposal),
        "related_lane_graph_proposals": related_lane_graph_proposals,
        "lane": lane,
        "participants": participants,
        "messages": messages,
        "execution_artifact": _execution_artifact(
            lane,
            expected_target_path=expected_target_path,
            expected_target_content=expected_target_content,
        ),
        "final_action_hold": _final_action_hold(run_root, lane),
        "review_task": _review_task(run_root, lane),
        "review_verdict": _review_verdict(run_root, lane),
        "review_peer_participant": _review_peer_participant(participants, lane),
    }


def _build_run_snapshot(
    *,
    run_root: Path,
    conversation_id: str,
    feature_id: str,
    lane_specs: list[dict[str, str]],
    proposal: dict[str, Any],
    lanes: list[dict[str, Any]],
    provider_readiness: dict[str, Any],
) -> dict[str, Any]:
    if len(lane_specs) != len(lanes):
        raise ValueError("lane_specs and lanes must have the same length")
    if len(lane_specs) == 1:
        spec = lane_specs[0]
        snapshot = _build_snapshot(
            run_root=run_root,
            conversation_id=conversation_id,
            feature_id=spec["feature_id"],
            lane_kind=spec["lane_kind"],
            expected_target_path=spec["target_path"],
            expected_target_content=spec["expected_content"],
            proposal=proposal,
            lane=lanes[0],
            provider_readiness=provider_readiness,
        )
        snapshot["expected_status"] = spec.get("expected_status", "awaiting_final_action")
        return snapshot
    lane_snapshots = [
        _snapshot_with_expected_status(
            _build_snapshot(
                run_root=run_root,
                conversation_id=conversation_id,
                feature_id=spec["feature_id"],
                lane_kind=spec["lane_kind"],
                expected_target_path=spec["target_path"],
                expected_target_content=spec["expected_content"],
                proposal=proposal,
                lane=lane,
                provider_readiness=provider_readiness,
            ),
            expected_status=spec.get("expected_status", "awaiting_final_action"),
        )
        for spec, lane in zip(lane_specs, lanes, strict=True)
    ]
    return {
        "classification": "multilane_fullchain_sentinel",
        "run_root": str(run_root),
        "conversation_id": conversation_id,
        "feature_id": feature_id,
        "lane_specs": lane_specs,
        "lane_snapshots": lane_snapshots,
        "proposal": lane_snapshots[0]["proposal"],
        "proposal_has_review_runtime": any(
            item.get("proposal_has_review_runtime") is True
            for item in lane_snapshots
        ),
        "provider_readiness": provider_readiness,
        "selected_review_provider": provider_readiness["review_provider_selection"][
            "selected_provider"
        ],
        "review_provider_fallback_reason": provider_readiness[
            "review_provider_selection"
        ].get("fallback_reason"),
        "target_paths": [spec["target_path"] for spec in lane_specs],
    }


def _snapshot_with_expected_status(
    snapshot: dict[str, Any],
    *,
    expected_status: str,
) -> dict[str, Any]:
    snapshot["expected_status"] = expected_status
    return snapshot


def _conversation_proposals(db_path: Path, conversation_id: str) -> list[dict[str, Any]]:
    proposals: list[dict[str, Any]] = []
    for proposal in ChatStore(db_path).list_proposals(conversation_id):
        payload = proposal.model_dump(mode="json")
        parsed = _json_or_none(proposal.content)
        if isinstance(parsed, dict):
            payload["parsed_content"] = parsed
        proposals.append(payload)
    return proposals


def _proposal_feature_ids(proposal: dict[str, Any]) -> set[str]:
    parsed = proposal.get("parsed_content")
    if not isinstance(parsed, dict):
        return set()
    lanes = parsed.get("lanes")
    if not isinstance(lanes, list):
        return set()
    return {
        str(lane["feature_id"])
        for lane in lanes
        if isinstance(lane, dict) and isinstance(lane.get("feature_id"), str)
    }


def _proposal_has_review_runtime(proposal: dict[str, Any]) -> bool:
    parsed = proposal.get("parsed_content")
    if not isinstance(parsed, dict):
        return False
    lanes = parsed.get("lanes")
    if not isinstance(lanes, list):
        return False
    return any(isinstance(lane, dict) and "review_runtime" in lane for lane in lanes)


def _review_peer_participant(
    participants: list[dict[str, Any]],
    lane: dict[str, Any],
) -> dict[str, Any] | None:
    peer_id = lane.get("review_peer_id")
    if isinstance(peer_id, str):
        for participant in participants:
            if participant.get("participant_id") == peer_id:
                return participant
    audit = lane.get("last_mutation_audit")
    if isinstance(audit, dict):
        actor = audit.get("actor")
        if isinstance(actor, str) and actor.startswith("review-peer-"):
            audit_peer_id = actor.removeprefix("review-peer-")
            for participant in participants:
                if participant.get("participant_id") == audit_peer_id:
                    return participant
    review_cli_kind = lane.get("review_peer_cli_kind")
    review_model = lane.get("review_peer_model")
    for participant in participants:
        if participant.get("role") != "review":
            continue
        if review_cli_kind and participant.get("cli_kind") != review_cli_kind:
            continue
        if review_model and participant.get("model") != review_model:
            continue
        return participant
    return None


def _execution_artifact(
    lane: dict[str, Any],
    *,
    expected_target_path: str,
    expected_target_content: str,
) -> dict[str, Any]:
    worktree = lane.get("worktree") or lane.get("worker_worktree")
    if not isinstance(worktree, str):
        return {
            "exists": False,
            "expected_content": expected_target_content,
            "expected_path": expected_target_path,
            "path": None,
        }
    path = Path(worktree) / expected_target_path
    content = path.read_text(encoding="utf-8") if path.exists() else None
    return {
        "content": content,
        "exists": path.exists(),
        "expected_content": expected_target_content,
        "expected_path": expected_target_path,
        "matches_expected": content == expected_target_content + "\n",
        "path": str(path),
    }


def _final_action_hold(run_root: Path, lane: dict[str, Any]) -> dict[str, Any] | None:
    hold_id = lane.get("final_action_hold_id")
    path = run_root / "final_actions.json"
    if not isinstance(hold_id, str) or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    holds = payload.get("holds")
    if not isinstance(holds, list):
        return None
    for hold in holds:
        if isinstance(hold, dict) and hold.get("id") == hold_id:
            return hold
    return None


def _review_task(run_root: Path, lane: dict[str, Any]) -> dict[str, Any] | None:
    task_id = lane.get("review_task_id")
    path = run_root / "review_plane.json"
    if not isinstance(task_id, str) or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    tasks = payload.get("review_tasks")
    if not isinstance(tasks, list):
        return None
    for task in tasks:
        if isinstance(task, dict) and task.get("task_id") == task_id:
            return task
    return None


def _review_verdict(run_root: Path, lane: dict[str, Any]) -> dict[str, Any] | None:
    verdict_id = lane.get("review_verdict_id")
    path = run_root / "review_plane.json"
    if not isinstance(verdict_id, str) or not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    verdicts = payload.get("review_verdicts")
    if not isinstance(verdicts, list):
        return None
    for verdict in verdicts:
        if isinstance(verdict, dict) and verdict.get("id") == verdict_id:
            return verdict
    return None


def _success_checks(snapshot: dict[str, Any]) -> dict[str, bool]:
    if isinstance(snapshot.get("lane_snapshots"), list):
        return _multi_success_checks(snapshot)
    lane = snapshot["lane"]
    proposal = snapshot["proposal"]
    final_action_hold = snapshot.get("final_action_hold")
    review_task = snapshot.get("review_task")
    review_verdict = snapshot.get("review_verdict")
    artifact = snapshot.get("execution_artifact")
    related_proposals = snapshot.get("related_lane_graph_proposals")
    selected_review_provider = snapshot.get("selected_review_provider")
    review_peer_participant = snapshot.get("review_peer_participant")
    provider_readiness = snapshot.get("provider_readiness")
    review_provider_selection = (
        provider_readiness.get("review_provider_selection", {})
        if isinstance(provider_readiness, dict)
        else {}
    )
    expected_fallback = review_provider_selection.get("fallback_reason")
    expected_status = str(snapshot.get("expected_status") or "awaiting_final_action")
    common_checks = {
        "single_related_lane_graph_proposal": isinstance(related_proposals, list)
        and len(related_proposals) == 1,
        "approved_proposal_accepted": proposal.get("status") == "accepted"
        and proposal.get("accepted_resolution_id") == lane.get("resolution_id"),
        "lane_reached_expected_status": lane.get("status") == expected_status,
        "isolated_artifact_matches": isinstance(artifact, dict)
        and artifact.get("matches_expected") is True,
        "proposal_has_no_review_runtime": snapshot.get("proposal_has_review_runtime")
        is False,
    }
    if expected_status == "gate_failed":
        return common_checks | {
            "expected_gate_failed": lane.get("status") == "gate_failed"
            and lane.get("gate_passed") is False
            and lane.get("failure_reason") == "gate_failed",
            "execution_peer_handoff_not_degraded": _execution_handoff_not_degraded(
                lane,
                expected_status=expected_status,
            ),
            "no_review_or_final_action_for_expected_gate_failure": review_task is None
            and review_verdict is None
            and final_action_hold is None,
        }
    return common_checks | {
        "lane_awaiting_final_action": lane.get("status") == "awaiting_final_action",
        "gate_passed": lane.get("gate_passed") is True,
        "execution_peer_handoff_not_degraded": _execution_handoff_not_degraded(
            lane,
            expected_status=expected_status,
        ),
        "isolated_note_matches": isinstance(artifact, dict)
        and artifact.get("matches_expected") is True,
        "selected_review_peer_recorded": isinstance(selected_review_provider, str)
        and lane.get("review_peer_cli_kind") == selected_review_provider
        and isinstance(review_peer_participant, dict)
        and review_peer_participant.get("cli_kind") == selected_review_provider,
        "review_provider_fallback_recorded": (
            expected_fallback != "opencode_unavailable"
            or (
                selected_review_provider == "codex"
                and snapshot.get("review_provider_fallback_reason")
                == "opencode_unavailable"
            )
        ),
        "review_verdict_finalized": isinstance(review_verdict, dict)
        and review_verdict.get("status") == "finalized",
        "review_task_verdict_emitted": isinstance(review_task, dict)
        and review_task.get("status") == "verdict_emitted",
        "review_authority_not_stdout_fallback": _review_authority_not_stdout_fallback(
            lane=lane,
            review_verdict=review_verdict,
            final_action_hold=final_action_hold,
        ),
        "final_action_hold_pending": isinstance(final_action_hold, dict)
        and final_action_hold.get("status") == "pending",
    }


def _execution_handoff_not_degraded(
    lane: dict[str, Any],
    *,
    expected_status: str,
) -> bool:
    if lane.get("peer_delivery_mode") == "configured_peer":
        return (
            lane.get("peer_result_status") not in {"delivery_failed", "degraded"}
            and lane.get("peer_degraded_reason") is None
        )
    if expected_status != "gate_failed":
        return False
    return (
        lane.get("worker_kind") == "temporary_child_worker"
        and isinstance(lane.get("worker_worktree"), str)
        and bool(str(lane.get("worker_worktree")).strip())
        and lane.get("persistent_execute_degraded") is not True
        and lane.get("provider_session_binding_degraded") is not True
        and lane.get("execute_peer_degraded_reason") is None
        and lane.get("persistent_execute_degraded_reason") is None
    )


def _multi_success_checks(snapshot: dict[str, Any]) -> dict[str, bool]:
    lane_snapshots = snapshot.get("lane_snapshots")
    if not isinstance(lane_snapshots, list) or not lane_snapshots:
        return {"has_lane_snapshots": False}
    per_lane_checks = [
        _success_checks({k: v for k, v in item.items() if k != "success_checks"})
        for item in lane_snapshots
        if isinstance(item, dict)
    ]
    worktrees = [
        item.get("lane", {}).get("worktree") or item.get("lane", {}).get("worker_worktree")
        for item in lane_snapshots
        if isinstance(item, dict)
    ]
    feature_ids = [
        item.get("feature_id") for item in lane_snapshots if isinstance(item, dict)
    ]
    target_paths = [
        item.get("target_path") for item in lane_snapshots if isinstance(item, dict)
    ]
    expected_statuses = [
        item.get("expected_status", "awaiting_final_action")
        for item in lane_snapshots
        if isinstance(item, dict)
    ]
    common_checks = {
        "has_lane_snapshots": len(per_lane_checks) == len(lane_snapshots),
        "all_single_related_lane_graph_proposal": all(
            checks.get("single_related_lane_graph_proposal") is True
            for checks in per_lane_checks
        ),
        "all_approved_proposal_accepted": all(
            checks.get("approved_proposal_accepted") is True
            for checks in per_lane_checks
        ),
        "all_expected_lane_statuses": all(
            checks.get("lane_reached_expected_status") is True
            for checks in per_lane_checks
        ),
        "all_expected_artifacts_match": all(
            checks.get("isolated_artifact_matches") is True
            for checks in per_lane_checks
        ),
        "proposal_has_no_review_runtime": snapshot.get("proposal_has_review_runtime")
        is False,
        "distinct_feature_ids": len(set(feature_ids)) == len(feature_ids),
        "distinct_target_paths": len(set(target_paths)) == len(target_paths),
        "distinct_worktrees": len(set(worktrees)) == len(worktrees),
    }
    if any(status != "awaiting_final_action" for status in expected_statuses):
        return common_checks | {
            "all_success_lanes_completed": all(
                checks.get("lane_awaiting_final_action", True) is True
                and checks.get("gate_passed", True) is True
                and checks.get("review_verdict_finalized", True) is True
                and checks.get("review_task_verdict_emitted", True) is True
                and checks.get("final_action_hold_pending", True) is True
                for checks in per_lane_checks
            ),
            "all_expected_gate_failures_reported": all(
                checks.get("expected_gate_failed", True) is True
                for checks in per_lane_checks
            ),
            "all_expected_gate_failures_skip_review_and_final_action": all(
                checks.get("no_review_or_final_action_for_expected_gate_failure", True)
                is True
                for checks in per_lane_checks
            ),
            "all_execution_peer_handoffs_not_degraded": all(
                checks.get("execution_peer_handoff_not_degraded") is True
                for checks in per_lane_checks
            ),
        }
    return {
        **common_checks,
        "all_lanes_awaiting_final_action": all(
            checks.get("lane_awaiting_final_action") is True
            for checks in per_lane_checks
        ),
        "all_gates_passed": all(
            checks.get("gate_passed") is True for checks in per_lane_checks
        ),
        "all_execution_peer_handoffs_not_degraded": all(
            checks.get("execution_peer_handoff_not_degraded") is True
            for checks in per_lane_checks
        ),
        "all_isolated_artifacts_match": all(
            checks.get("isolated_artifact_matches") is True
            for checks in per_lane_checks
        ),
        "all_review_verdicts_finalized": all(
            checks.get("review_verdict_finalized") is True
            for checks in per_lane_checks
        ),
        "all_review_tasks_verdict_emitted": all(
            checks.get("review_task_verdict_emitted") is True
            for checks in per_lane_checks
        ),
        "all_final_action_holds_pending": all(
            checks.get("final_action_hold_pending") is True
            for checks in per_lane_checks
        ),
        "all_review_authority_not_stdout_fallback": all(
            checks.get("review_authority_not_stdout_fallback") is True
            for checks in per_lane_checks
        ),
    }


def _review_authority_not_stdout_fallback(
    *,
    lane: dict[str, Any],
    review_verdict: dict[str, Any] | None,
    final_action_hold: dict[str, Any] | None,
) -> bool:
    for value in _review_authority_claims(lane, review_verdict, final_action_hold):
        lowered = value.lower()
        if "stdout fallback" in lowered or "provider stdout" in lowered:
            return False
    for key in ("review_fallback", "review_delivery_mode"):
        if lane.get(key) == "stdout":
            return False
    return True


def _review_authority_claims(
    lane: dict[str, Any],
    review_verdict: dict[str, Any] | None,
    final_action_hold: dict[str, Any] | None,
) -> list[str]:
    claims: list[str] = []
    for key in ("review_summary", "review_fallback", "review_fallback_reason"):
        value = lane.get(key)
        if isinstance(value, str):
            claims.append(value)
    history = lane.get("review_history")
    if isinstance(history, list):
        for item in history:
            if not isinstance(item, dict):
                continue
            for key in ("summary", "fallback", "fallback_reason"):
                value = item.get(key)
                if isinstance(value, str):
                    claims.append(value)
    for record in (review_verdict, final_action_hold):
        if not isinstance(record, dict):
            continue
        for key in ("summary", "status", "decision"):
            value = record.get(key)
            if isinstance(value, str):
                claims.append(value)
    return claims


def _provider_readiness(
    *,
    review_provider_policy: str,
    ray_god_mcp: bool,
) -> dict[str, Any]:
    codex = _binary_readiness("codex")
    opencode = _binary_readiness("opencode")
    selection = _select_review_provider(
        policy=review_provider_policy,
        codex_ready=bool(codex["available"]),
        opencode_ready=bool(opencode["available"]),
    )
    return {
        "providers": {
            "codex": codex,
            "opencode": opencode,
        },
        "mcp": {
            "ray_god_mcp_enabled": ray_god_mcp,
        },
        "review_provider_selection": selection,
    }


def _binary_readiness(binary_name: str) -> dict[str, Any]:
    path = shutil.which(binary_name)
    if path is None:
        return {
            "available": False,
            "binary": binary_name,
            "path": None,
            "failure_reason": f"{binary_name}_unavailable",
            "version": None,
        }
    try:
        result = subprocess.run(
            [path, "--version"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        return {
            "available": False,
            "binary": binary_name,
            "path": path,
            "failure_reason": f"{binary_name}_version_failed",
            "version": None,
            "error": str(exc),
        }
    version = (result.stdout or result.stderr).strip()
    return {
        "available": result.returncode == 0,
        "binary": binary_name,
        "path": path,
        "failure_reason": None if result.returncode == 0 else f"{binary_name}_version_failed",
        "version": version or None,
    }


def _select_review_provider(
    *,
    policy: str,
    codex_ready: bool,
    opencode_ready: bool,
) -> dict[str, Any]:
    if policy == "opencode":
        if not opencode_ready:
            raise RuntimeError(
                "requested opencode review provider unavailable: opencode_unavailable"
            )
        return {
            "policy": policy,
            "selected_provider": "opencode",
            "fallback_reason": None,
        }
    if policy == "codex":
        if not codex_ready:
            raise RuntimeError("requested codex review provider unavailable: codex_unavailable")
        return {
            "policy": policy,
            "selected_provider": "codex",
            "fallback_reason": None,
        }
    if policy != "auto":
        raise RuntimeError(f"unknown review provider policy: {policy}")
    if opencode_ready:
        return {
            "policy": policy,
            "selected_provider": "opencode",
            "fallback_reason": None,
        }
    if codex_ready:
        return {
            "policy": policy,
            "selected_provider": "codex",
            "fallback_reason": "opencode_unavailable",
        }
    raise RuntimeError(
        "no review provider available: opencode_unavailable,codex_unavailable"
    )


def _review_participant_spec(provider_readiness: dict[str, Any]) -> dict[str, str]:
    selected = provider_readiness["review_provider_selection"]["selected_provider"]
    if selected == "opencode":
        return {
            "role": "review",
            "provider_id": "opencode",
            "profile_id": "review",
            "cli_kind": "opencode",
            "model": OPENCODE_MODEL,
            "display_name": "OpenCode Review GOD runtime sentinel",
        }
    if selected == "codex":
        return {
            "role": "review",
            "provider_id": "codex",
            "profile_id": "review",
            "cli_kind": "codex",
            "model": CODEX_REVIEW_MODEL,
            "display_name": "Codex Review GOD runtime sentinel",
        }
    raise RuntimeError(f"unsupported review provider: {selected}")


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"POST {url} failed: {exc.code} {body}") from exc


def _wait_http_ok(url: str, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if 200 <= response.status < 300:
                    return
        except Exception:
            time.sleep(0.5)
    raise TimeoutError(f"service did not become healthy: {url}")


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _json_or_none(value: str) -> Any | None:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str) + "\n")


def _write_compact_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        )
        + "\n"
    )


if __name__ == "__main__":
    raise SystemExit(main())
