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
    note_path = f"docs/xmuse/{feature_id}.md"
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
        note_path=note_path,
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

        created = _post_json(
            f"http://127.0.0.1:{chat_port}/api/chat/conversations",
            {
                "title": f"Runtime docs sentinel {feature_id}",
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
            note_path=note_path,
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
                "goal_summary": f"Approve docs-only runtime sentinel {feature_id}",
            },
        )
        _write_json(artifacts / "approval_response.json", approval)

        lane = _wait_for_lane(
            run_root / "feature_lanes.json",
            feature_id=feature_id,
            timeout_s=args.lane_timeout_s,
        )
        snapshot = _build_snapshot(
            run_root=run_root,
            conversation_id=conversation_id,
            feature_id=feature_id,
            expected_note_path=note_path,
            expected_note_content=_expected_note_content(feature_id),
            proposal=proposal,
            lane=lane,
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
        description="Run a real docs-only xmuse fullchain sentinel."
    )
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--execution-worktree", type=Path, required=True)
    parser.add_argument("--feature-id", required=True)
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


def _commands_payload(
    *,
    run_root: Path,
    execution_worktree: Path,
    chat_port: int,
    mcp_port: int,
    feature_id: str,
    note_path: str,
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
        "note_path": note_path,
        "repo_head_sha": repo_head_sha,
        "expected_note_content": _expected_note_content(feature_id),
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
    note_path: str,
    provider_readiness: dict[str, Any],
) -> str:
    selection = provider_readiness["review_provider_selection"]
    selected_review_provider = str(selection["selected_provider"])
    fallback_reason = selection.get("fallback_reason")
    fallback_clause = (
        "OpenCode was not selected because provider readiness recorded "
        f"`{fallback_reason}`; do not claim OpenCode was verified. "
        if fallback_reason
        else ""
    )
    return (
        "@architect Run a real docs-only xmuse runtime sentinel. "
        "Use the structured collaboration tools before proposing execution: "
        "create a collaboration request to @execute, have execute record an "
        "execute_feasibility_verdict with status executable and at least one "
        "evidence ref, then emit exactly one lane_graph proposal referencing "
        "that collaboration run. The proposal must contain one lane with "
        f"feature_id `{feature_id}`. The lane prompt must instruct the worker "
        f"to create or overwrite `{note_path}` in the isolated execution "
        "worktree with one concise sentence: "
        f"`{_expected_note_content(feature_id)}` "
        "Keep the lane docs-only. Do not include review_runtime; rely on the "
        f"registered {selected_review_provider} review participant. "
        f"{fallback_clause}"
        "Do not edit production code, "
        "tests, PR #43, MemoryOS, TUI, or GitHub-truth code. Do not claim "
        "production readiness, GitHub review truth, live MemoryOS, overnight "
        "readiness, full L8-L10 closure, or full L1-L11 closure."
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
    expected_note_path: str,
    expected_note_content: str,
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
        "classification": "docs_fullchain_sentinel",
        "run_root": str(run_root),
        "conversation_id": conversation_id,
        "feature_id": feature_id,
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
            expected_note_path=expected_note_path,
            expected_note_content=expected_note_content,
        ),
        "final_action_hold": _final_action_hold(run_root, lane),
        "review_task": _review_task(run_root, lane),
        "review_verdict": _review_verdict(run_root, lane),
        "review_peer_participant": _review_peer_participant(participants, lane),
    }


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
    expected_note_path: str,
    expected_note_content: str,
) -> dict[str, Any]:
    worktree = lane.get("worktree") or lane.get("worker_worktree")
    if not isinstance(worktree, str):
        return {
            "exists": False,
            "expected_content": expected_note_content,
            "expected_path": expected_note_path,
            "path": None,
        }
    path = Path(worktree) / expected_note_path
    content = path.read_text(encoding="utf-8") if path.exists() else None
    return {
        "content": content,
        "exists": path.exists(),
        "expected_content": expected_note_content,
        "expected_path": expected_note_path,
        "matches_expected": content == expected_note_content + "\n",
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
    return {
        "single_related_lane_graph_proposal": isinstance(related_proposals, list)
        and len(related_proposals) == 1,
        "approved_proposal_accepted": proposal.get("status") == "accepted"
        and proposal.get("accepted_resolution_id") == lane.get("resolution_id"),
        "lane_awaiting_final_action": lane.get("status") == "awaiting_final_action",
        "gate_passed": lane.get("gate_passed") is True,
        "execution_peer_handoff_not_degraded": lane.get("peer_delivery_mode")
        == "configured_peer"
        and lane.get("peer_result_status") not in {"delivery_failed", "degraded"}
        and lane.get("peer_degraded_reason") is None,
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
        "final_action_hold_pending": isinstance(final_action_hold, dict)
        and final_action_hold.get("status") == "pending",
        "proposal_has_no_review_runtime": snapshot.get("proposal_has_review_runtime")
        is False,
    }


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
