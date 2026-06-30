from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.protocol import PROTOCOL_VERSION
from xmuse_core.providers.models import ProviderProfileId
from xmuse_core.providers.registry import (
    DEFAULT_CODEX_GOD_MODEL_ID,
    normalize_codex_model_id,
)


@dataclass
class RunnerConfig:
    model: str
    mcp_port: int
    worktree: Path
    role: str
    timeout_s: float


def runtime_truth_metadata() -> dict[str, object]:
    return {
        "runtime_mode": "native_exec_shim",
        "provider_native_long_session": False,
        "spawns_provider_process_per_turn": True,
        "production_peer_happy_path": False,
    }


_ACTIVE_CHILD: subprocess.Popen[str] | None = None
_REVIEW_VERDICT_PREFIX = "XMUSE_REVIEW_VERDICT_JSON:"
_REVIEW_VERDICT_DECISIONS = {"merge", "rework", "terminate"}


def main() -> None:
    _install_signal_handlers()
    config = _parse_args()
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            _emit_error("invalid_json", "stdin line is not valid JSON")
            continue
        if not isinstance(message, dict):
            _emit_error("invalid_message", "stdin message must be a JSON object")
            continue
        if _handle_control_message(message):
            if message.get("type") == "abort":
                break
            continue
        _run_codex_turn(config, message)


def _parse_args() -> RunnerConfig:
    parser = argparse.ArgumentParser(description="xmuse persistent Codex session shim")
    parser.add_argument("--model", default=DEFAULT_CODEX_GOD_MODEL_ID)
    parser.add_argument("--mcp-port", type=int, default=8100)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--timeout-s", type=float, default=900.0)
    args = parser.parse_args()
    profile_id = _profile_id_for_role(args.role)
    return RunnerConfig(
        model=normalize_codex_model_id(
            args.model,
            profile_id=profile_id,
            allow_final_quality=profile_id is ProviderProfileId.FINAL_QUALITY,
        ),
        mcp_port=args.mcp_port,
        worktree=args.worktree,
        role=args.role,
        timeout_s=args.timeout_s,
    )


def _profile_id_for_role(role: str) -> ProviderProfileId:
    normalized = role.strip().lower()
    if normalized == "review":
        return ProviderProfileId.REVIEW
    if normalized == "execute":
        return ProviderProfileId.WORKER
    if normalized in {
        "merge_final_review",
        "merge-final-review",
        "final_quality",
        "final-quality",
    }:
        return ProviderProfileId.FINAL_QUALITY
    return ProviderProfileId.GOD


def _handle_control_message(message: dict[str, Any]) -> bool:
    msg_type = message.get("type")
    if msg_type == "hello":
        _emit(
            {
                "type": "hello_ack",
                "protocol_version": PROTOCOL_VERSION,
                "runtime": "codex",
            }
        )
        return True
    if msg_type == "ping":
        _emit({"type": "pong", "runtime": "codex"})
        return True
    return msg_type == "abort"


def _run_codex_turn(config: RunnerConfig, message: dict[str, Any]) -> None:
    msg_type = str(message.get("type") or "task")
    prompt = str(message.get("prompt") or "")
    context = str(message.get("context") or "")
    request_id = _first_text_value(message.get("request_id"))
    emit_result = _should_emit_turn_result(msg_type)
    full_prompt = _format_turn_prompt(config, msg_type=msg_type, prompt=prompt, context=context)
    execute_metadata = _execute_turn_metadata(message, prompt=prompt, context=context)
    try:
        result = _run_codex_exec(config, full_prompt)
    except subprocess.TimeoutExpired as exc:
        if not emit_result:
            return
        artifacts = {
            "stdout": _bounded(exc.stdout),
            "stderr": _bounded(exc.stderr),
            "message_type": msg_type,
        }
        _attach_request_id(artifacts, request_id)
        _attach_execute_result(
            artifacts,
            msg_type=msg_type,
            execute_metadata=execute_metadata,
            exit_code=1,
            stdout=exc.stdout,
            stderr=exc.stderr,
            timed_out=True,
            transport_error="codex_timeout",
        )
        _emit_error(
            "codex_timeout",
            f"codex exec timed out after {config.timeout_s:g}s",
            artifacts=artifacts,
            request_id=request_id,
        )
        return
    except OSError as exc:
        if not emit_result:
            return
        artifacts = {"message_type": msg_type}
        _attach_request_id(artifacts, request_id)
        _attach_execute_result(
            artifacts,
            msg_type=msg_type,
            execute_metadata=execute_metadata,
            exit_code=1,
            stdout="",
            stderr=str(exc),
            timed_out=False,
            transport_error="codex_spawn_failed",
        )
        _emit_error(
            "codex_spawn_failed",
            str(exc),
            artifacts=artifacts,
            request_id=request_id,
        )
        return

    stdout = result.stdout or ""
    stderr = result.stderr or ""
    artifacts = {
        "stdout": _bounded(stdout),
        "stderr": _bounded(stderr),
        "returncode": result.returncode,
        "message_type": msg_type,
    }
    _attach_request_id(artifacts, request_id)
    _attach_execute_result(
        artifacts,
        msg_type=msg_type,
        execute_metadata=execute_metadata,
        exit_code=result.returncode,
        stdout=stdout,
        stderr=stderr,
        timed_out=False,
    )
    _attach_review_verdict(artifacts, msg_type=msg_type, stdout=stdout)
    if not emit_result:
        return
    if result.returncode == 0:
        payload = {
                "type": "result",
                "status": "success",
                "runtime": "codex",
                "message": _bounded(stdout),
                "artifacts": artifacts,
            }
        if request_id is not None:
            payload["request_id"] = request_id
        _emit(payload)
        return
    _emit_error(
        f"codex_exit_{result.returncode}",
        _bounded(stderr.strip() or stdout.strip() or "codex exec failed"),
        artifacts=artifacts,
        request_id=request_id,
    )


def _run_codex_exec(
    config: RunnerConfig,
    full_prompt: str,
) -> subprocess.CompletedProcess[str]:
    global _ACTIVE_CHILD
    process = subprocess.Popen(
        _codex_command(config),
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=config.worktree,
        start_new_session=True,
    )
    _ACTIVE_CHILD = process
    try:
        stdout, stderr = process.communicate(input=full_prompt, timeout=config.timeout_s)
    except subprocess.TimeoutExpired as exc:
        _terminate_process_tree(process)
        stdout, stderr = _communicate_after_terminate(process)
        raise subprocess.TimeoutExpired(
            cmd=exc.cmd,
            timeout=exc.timeout,
            output=stdout if stdout is not None else exc.output,
            stderr=stderr if stderr is not None else exc.stderr,
        ) from exc
    finally:
        if _ACTIVE_CHILD is process:
            _ACTIVE_CHILD = None
    return subprocess.CompletedProcess(
        args=process.args,
        returncode=process.returncode or 0,
        stdout=stdout,
        stderr=stderr,
    )


def _install_signal_handlers() -> None:
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, _handle_shutdown_signal)


def _handle_shutdown_signal(signum: int, _frame: Any) -> None:
    if _ACTIVE_CHILD is not None:
        _terminate_process_tree(_ACTIVE_CHILD)
    raise SystemExit(128 + signum)


def _terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            return
        except OSError:
            process.kill()
        process.wait(timeout=5)


def _communicate_after_terminate(
    process: subprocess.Popen[str],
) -> tuple[str | None, str | None]:
    try:
        return process.communicate(timeout=1)
    except subprocess.TimeoutExpired:
        return None, None


def _should_emit_turn_result(msg_type: str) -> bool:
    return True


def _format_turn_prompt(
    config: RunnerConfig,
    *,
    msg_type: str,
    prompt: str,
    context: str,
) -> str:
    if msg_type == "peer_chat_nudge":
        layered_prompt = _xmuse_layered_prompt(context)
        if layered_prompt:
            return _with_xmuse_context(layered_prompt, context)
    sections = [
        "You are an xmuse persistent GOD session turn worker.",
        f"Role: {config.role}",
        f"Message type: {msg_type}",
    ]
    if context.strip():
        sections.extend(["", "## Context", "", context.strip()])
    if prompt.strip():
        sections.extend(["", "## Task", "", prompt.strip()])
    if msg_type == "review":
        sections.extend(
            [
                "",
                "Return a clear review with a Findings section and a Verdict line.",
                "Use exactly one of: Verdict: merge, Verdict: rework, Verdict: terminate.",
                "",
                "## Review expected result contract",
                "",
                "End stdout with exactly one machine-readable verdict line:",
                "XMUSE_REVIEW_VERDICT_JSON: "
                '{"decision":"merge|rework|terminate",'
                '"summary":"<one concise sentence>"}',
                "The shim converts only that validated line into "
                "`artifacts.review_verdict`; ordinary prose and `Verdict:` text "
                "remain diagnostic and are not review authority artifacts.",
                "The JSON summary must summarize authority refs and the review "
                "decision only; do not mention MCP/tool availability or fallback "
                "transport there.",
            ]
        )
    if msg_type == "peer_chat_nudge":
        sections.extend(
            [
                "",
                "## Peer chat expected result contract",
                "",
                "Keep this turn short. This is an interactive chat reply, not a code task.",
                "Use MCP tool `chat_read_inbox` with the provided conversation_id, "
                "participant_id, and god_session_id.",
                "Then respond with `chat_post_message` and mark the inbox item read "
                "through the MCP chat tools.",
                "If the inbox request explicitly asks for `chat_emit_proposal`, call "
                "`chat_emit_proposal` directly instead of `chat_post_message`; that "
                "tool is the durable writeback for proposal turns.",
                "Natural-language @mentions inside `chat_post_message` are display-only "
                "and do not enqueue peer work. When another GOD must take over or "
                "review, call `chat_mention` with "
                "`reply_to_inbox_item_id=xmuse_context.inbox_item.id`, the target "
                "GOD's exact @role, and a concrete handoff request; this closes "
                "your current inbox item and enqueues the target GOD in one durable "
                "writeback.",
                "For work that should enter real execution, use structured chat "
                "tools rather than plain text: create or reference a collaboration "
                "run, have execute record a JSON execute_feasibility_verdict with "
                "`chat_record_collaboration_response` using the approval-gate shape "
                "`{\"type\":\"execute_feasibility_verdict\",\"status\":\"executable\","
                "\"execution_performed\":false,\"summary\":\"<why dispatch is safe>\","
                "\"evidence_refs\":[\"<ref>\"]}`; "
                "looser fields such as `verdict=feasible` do not satisfy dispatch. "
                "Then emit a lane_graph "
                "proposal with `chat_emit_proposal` and a `collaboration:<run_id>` "
                "reference, passing "
                "`reply_to_inbox_item_id=xmuse_context.inbox_item.id` so the proposal "
                "closes the current inbox item. Human approval remains required before "
                "dispatch. Every dispatchable lane_graph lane must include explicit "
                "`gate_profiles`, for example `[\"xmuse-core\"]` for xmuse core code "
                "paths; if you cannot choose a gate profile, write a blocker or open "
                "question instead of proposing dispatchable work.",
                "If MCP tools are unavailable, return one concise natural-language "
                "assistant reply on stdout. The scheduler will publish that stdout as "
                "the GOD reply.",
                "Do not edit files, run tests, inspect unrelated repository state, or "
                "start long-running work for this chat nudge.",
            ]
        )
    if msg_type == "execute":
        sections.extend(
            [
                "",
                "## Execute expected result contract",
                "",
                "You are a temporary child worker delegated by the persistent Execute GOD.",
                "Preserve the lane request id, lane id, and feature context in your evidence.",
                "This shim emits structured `artifacts.execute_result` with "
                "`lane_request_id`, `execute_request_id`, `lane_id`, `exit_code`, "
                "`stdout`, `stderr`, and `timed_out`; do not rely on the runner "
                "parsing free-form status text.",
                "",
                "If MCP tools are not exposed, use the stdout fallback: state that MCP "
                "is unavailable, include the lane id, tests run, changed files, and "
                "the status you would have sent through `update_lane_status`.",
                "The runner does not parse execution stdout status. If your fallback "
                "status is `executed`, exit with status 0; if it is `exec_failed`, "
                "exit non-zero.",
            ]
        )
    return "\n".join(sections).strip() + "\n"


def _xmuse_layered_prompt(context: str) -> str:
    try:
        parsed = json.loads(context)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    prompt_artifact = parsed.get("xmuse_prompt")
    if not isinstance(prompt_artifact, dict):
        return ""
    text = prompt_artifact.get("text")
    return text.strip() + "\n" if isinstance(text, str) and text.strip() else ""


def _with_xmuse_context(prompt: str, context: str) -> str:
    if not context.strip():
        return prompt.strip() + "\n"
    return (
        prompt.strip()
        + "\n\n<xmuse_context>\n"
        + context.strip()
        + "\n</xmuse_context>\n"
    )


def _attach_execute_result(
    artifacts: dict[str, Any],
    *,
    msg_type: str,
    execute_metadata: dict[str, str],
    exit_code: int,
    stdout: Any,
    stderr: Any,
    timed_out: bool,
    transport_error: str | None = None,
) -> None:
    if msg_type != "execute":
        return
    artifacts["returncode"] = exit_code
    execute_result: dict[str, Any] = {
        "exit_code": exit_code,
        "stdout": _bounded(stdout),
        "stderr": _bounded(stderr),
        "timed_out": timed_out,
    }
    lane_request_id = execute_metadata.get("lane_request_id")
    if lane_request_id:
        execute_result["lane_request_id"] = lane_request_id
        execute_result["execute_request_id"] = lane_request_id
    lane_id = execute_metadata.get("lane_id")
    if lane_id:
        execute_result["lane_id"] = lane_id
    if transport_error:
        execute_result["transport_error"] = transport_error
    artifacts["execute_result"] = execute_result


def _attach_review_verdict(
    artifacts: dict[str, Any],
    *,
    msg_type: str,
    stdout: Any,
) -> None:
    if msg_type != "review":
        return
    verdict = _review_verdict_from_stdout(stdout)
    if verdict is not None:
        artifacts["review_verdict"] = verdict


def _review_verdict_from_stdout(stdout: Any) -> dict[str, str] | None:
    stripped_lines = [line.strip() for line in str(stdout or "").splitlines() if line.strip()]
    if not stripped_lines:
        return None
    final_line = stripped_lines[-1]
    if not final_line.startswith(_REVIEW_VERDICT_PREFIX):
        return None
    lines = [
        line.strip()
        for line in stripped_lines
        if line.strip().startswith(_REVIEW_VERDICT_PREFIX)
    ]
    if len(lines) != 1 or lines[0] != final_line:
        return None
    raw = lines[0][len(_REVIEW_VERDICT_PREFIX) :].strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    raw_decision = payload.get("decision")
    if not isinstance(raw_decision, str):
        return None
    decision = raw_decision.strip().lower()
    if decision not in _REVIEW_VERDICT_DECISIONS:
        return None
    raw_summary = payload.get("summary")
    if not isinstance(raw_summary, str):
        return None
    summary = raw_summary.strip()
    if not summary:
        return None
    return {"decision": decision, "summary": _bounded(summary, max_chars=2000)}


def _attach_request_id(artifacts: dict[str, Any], request_id: str | None) -> None:
    if request_id is not None:
        artifacts["request_id"] = request_id


def _execute_turn_metadata(
    message: dict[str, Any],
    *,
    prompt: str,
    context: str,
) -> dict[str, str]:
    lane_request_id = _first_text_value(
        message.get("lane_request_id"),
        message.get("execute_request_id"),
        _extract_labeled_value(prompt, "lane_request_id"),
        _extract_labeled_value(prompt, "execute_request_id"),
        _extract_labeled_value(context, "lane_request_id"),
        _extract_labeled_value(context, "execute_request_id"),
    )
    lane_id = _first_text_value(
        message.get("lane_id"),
        _extract_labeled_value(context, "Lane ID"),
        _extract_labeled_value(prompt, "Lane ID"),
        _extract_labeled_value(context, "lane_id"),
        _extract_labeled_value(prompt, "lane_id"),
    )
    metadata: dict[str, str] = {}
    if lane_request_id:
        metadata["lane_request_id"] = lane_request_id
    if lane_id:
        metadata["lane_id"] = lane_id
    return metadata


def _first_text_value(*values: Any) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _extract_labeled_value(text: str, label: str) -> str | None:
    pattern = re.compile(rf"^\s*-?\s*{re.escape(label)}\s*:\s*(?P<value>\S.*)$", re.MULTILINE)
    match = pattern.search(text)
    if match is None:
        return None
    return match.group("value").strip()


def _codex_command(config: RunnerConfig) -> list[str]:
    return [
        "codex",
        "exec",
        "--ignore-user-config",
        "-m",
        config.model,
        "--dangerously-bypass-approvals-and-sandbox",
        "-c",
        'mcp_servers.xmuse-platform.type="sse"',
        "-c",
        f'mcp_servers.xmuse-platform.url="http://localhost:{config.mcp_port}/sse"',
        "-C",
        str(config.worktree),
    ]


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _emit_error(
    code: str,
    message: str,
    *,
    artifacts: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    payload = {
        "type": "error",
        "runtime": "codex",
        "code": code,
        "message": message,
        "artifacts": artifacts or {},
    }
    if request_id is not None:
        payload["request_id"] = request_id
    _emit(payload)


def _bounded(value: Any, *, max_chars: int = 12000) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


if __name__ == "__main__":
    main()
