from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.agents.protocol import PROTOCOL_VERSION

DEFAULT_OPENCODE_MODEL_REF = "opencode-go/deepseek-v4-flash"
DEFAULT_OPENCODE_VARIANT = "max"
MAX_ARTIFACT_TEXT = 12000
MAX_REPLY_TEXT = 8000


@dataclass
class RunnerConfig:
    model: str
    variant: str
    mcp_port: int
    worktree: Path
    role: str
    timeout_s: float
    opencode_binary: str
    session_id: str | None = None


@dataclass(frozen=True)
class OpenCodeRunResult:
    returncode: int
    stdout: str
    stderr: str
    reply_text: str
    session_id: str | None


_ACTIVE_CHILD: subprocess.Popen[str] | None = None


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
        _run_opencode_turn(config, message)


def _parse_args() -> RunnerConfig:
    parser = argparse.ArgumentParser(description="xmuse persistent OpenCode session shim")
    parser.add_argument("--model", default=DEFAULT_OPENCODE_MODEL_REF)
    parser.add_argument("--variant", default=DEFAULT_OPENCODE_VARIANT)
    parser.add_argument("--mcp-port", type=int, default=8100)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--opencode-binary", default="opencode")
    args = parser.parse_args()
    return RunnerConfig(
        model=args.model,
        variant=args.variant,
        mcp_port=args.mcp_port,
        worktree=args.worktree,
        role=args.role,
        timeout_s=args.timeout_s,
        opencode_binary=args.opencode_binary,
    )


def _handle_control_message(message: dict[str, Any]) -> bool:
    msg_type = message.get("type")
    if msg_type == "hello":
        _emit(
            {
                "type": "hello_ack",
                "protocol_version": PROTOCOL_VERSION,
                "runtime": "opencode",
            }
        )
        return True
    if msg_type == "ping":
        _emit({"type": "pong", "runtime": "opencode"})
        return True
    return msg_type == "abort"


def _run_opencode_turn(config: RunnerConfig, message: dict[str, Any]) -> None:
    msg_type = str(message.get("type") or "task")
    prompt = str(message.get("prompt") or "")
    context = str(message.get("context") or "")
    request_id = _first_text_value(message.get("request_id"))
    full_prompt = _format_turn_prompt(config, msg_type=msg_type, prompt=prompt, context=context)

    try:
        previous_session_id = config.session_id
        result = _run_opencode(config, full_prompt)
    except subprocess.TimeoutExpired as exc:
        _emit_error(
            "opencode_timeout",
            f"opencode run timed out after {config.timeout_s:g}s",
            artifacts={
                "stdout": _bounded(exc.output),
                "stderr": _bounded(exc.stderr),
                "message_type": msg_type,
            },
            request_id=request_id,
        )
        return
    except OSError as exc:
        _emit_error(
            "opencode_spawn_failed",
            str(exc),
            artifacts={"message_type": msg_type},
            request_id=request_id,
        )
        return

    artifacts: dict[str, Any] = {
        "stdout": _bounded(result.stdout),
        "stderr": _bounded(result.stderr),
        "returncode": result.returncode,
        "message_type": msg_type,
        "opencode_session_id": result.session_id,
        "provider_native_session_reused": bool(
            previous_session_id and previous_session_id == result.session_id
        ),
    }
    if result.session_id:
        config.session_id = result.session_id
    if request_id is not None:
        artifacts["request_id"] = request_id

    if result.returncode != 0:
        _emit_error(
            f"opencode_exit_{result.returncode}",
            _bounded(result.stderr.strip() or result.reply_text or "opencode run failed"),
            artifacts=artifacts,
            request_id=request_id,
        )
        return

    reply_text = _reply_text(result)
    if msg_type == "peer_chat_nudge":
        try:
            writeback = _post_peer_chat_writeback(
                config=config,
                context=context,
                content=reply_text,
                request_id=request_id,
            )
        except Exception as exc:
            artifacts["callback_writeback"] = {
                "status": "failed",
                "reason": str(exc),
            }
            _emit_error(
                "opencode_callback_writeback_failed",
                str(exc),
                artifacts=artifacts,
                request_id=request_id,
            )
            return
        artifacts["callback_writeback"] = writeback

    _emit(
        {
            "type": "result",
            "status": "success",
            "runtime": "opencode",
            "message": reply_text,
            "artifacts": artifacts,
            **({"request_id": request_id} if request_id is not None else {}),
        }
    )


def _run_opencode(config: RunnerConfig, full_prompt: str) -> OpenCodeRunResult:
    global _ACTIVE_CHILD
    command = _opencode_command(config, full_prompt)
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=config.worktree,
        start_new_session=True,
    )
    _ACTIVE_CHILD = process
    try:
        stdout, stderr = process.communicate(timeout=config.timeout_s)
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
    reply_text, session_id = _parse_opencode_json_output(stdout or "")
    return OpenCodeRunResult(
        returncode=process.returncode or 0,
        stdout=stdout or "",
        stderr=stderr or "",
        reply_text=reply_text,
        session_id=session_id or config.session_id,
    )


def _opencode_command(config: RunnerConfig, full_prompt: str) -> list[str]:
    command = [
        config.opencode_binary,
        "run",
        "--model",
        config.model,
        "--variant",
        config.variant,
        "--format",
        "json",
        "--dir",
        str(config.worktree),
    ]
    if config.session_id:
        command.extend(["--session", config.session_id])
    command.append(full_prompt)
    return command


def _format_turn_prompt(
    config: RunnerConfig,
    *,
    msg_type: str,
    prompt: str,
    context: str,
) -> str:
    if msg_type == "peer_chat_nudge":
        return _format_peer_chat_prompt(config, context=context, fallback_prompt=prompt)
    sections = [
        "You are an xmuse OpenCode GOD peer turn worker.",
        f"Role: {config.role}",
        f"Message type: {msg_type}",
    ]
    if context.strip():
        sections.extend(["", "## Context", "", context.strip()])
    if prompt.strip():
        sections.extend(["", "## Task", "", prompt.strip()])
    return "\n".join(sections).strip() + "\n"


def _format_peer_chat_prompt(
    config: RunnerConfig,
    *,
    context: str,
    fallback_prompt: str,
) -> str:
    request_content = _peer_chat_request_content(context) or fallback_prompt.strip()
    roster = _peer_chat_roster(context)
    sections = [
        "You are an xmuse OpenCode GOD peer in a durable groupchat.",
        f"Role: {config.role}",
        "",
        "## Current Request",
        "",
        request_content,
    ]
    if roster:
        sections.extend(["", "## Active Participants", "", roster])
    sections.extend(
        [
            "",
            "## Reply Contract",
            "",
            "Return only the concise natural-language content that should be posted "
            "as your GOD chat reply.",
            "Do not call tools. Do not edit files. Do not run tests. Do not inspect "
            "unrelated repository state.",
            "xmuse will write your reply through a durable callback bridge; stdout "
            "alone is not counted as chat truth.",
            "If another GOD should act next, mention the exact @role and include a "
            "concrete handoff request.",
        ]
    )
    return "\n".join(sections).strip() + "\n"


def _peer_chat_request_content(context: str) -> str:
    try:
        parsed = json.loads(context)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    inbox_item = parsed.get("inbox_item")
    if not isinstance(inbox_item, dict):
        return ""
    payload = inbox_item.get("payload")
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content")
    return content.strip() if isinstance(content, str) else ""


def _peer_chat_roster(context: str) -> str:
    try:
        parsed = json.loads(context)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    group_chat = parsed.get("group_chat")
    if not isinstance(group_chat, dict):
        return ""
    participants = group_chat.get("participants")
    if not isinstance(participants, list):
        return ""
    rows: list[str] = []
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        role = participant.get("role")
        display_name = participant.get("display_name")
        if isinstance(role, str) and role.strip():
            rows.append(
                f"@{role.strip()}"
                + (
                    f"={display_name.strip()}"
                    if isinstance(display_name, str) and display_name.strip()
                    else ""
                )
            )
    return ", ".join(rows)


def _parse_opencode_json_output(stdout: str) -> tuple[str, str | None]:
    texts: list[str] = []
    session_id: str | None = None
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        raw_session_id = event.get("sessionID")
        if isinstance(raw_session_id, str) and raw_session_id.strip():
            session_id = raw_session_id.strip()
        part = event.get("part")
        if isinstance(part, dict):
            raw_session_id = part.get("sessionID")
            if isinstance(raw_session_id, str) and raw_session_id.strip():
                session_id = raw_session_id.strip()
            if part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text:
                    texts.append(text)
        if event.get("type") == "text":
            text = event.get("text")
            if isinstance(text, str) and text:
                texts.append(text)
    return "".join(texts).strip(), session_id


def _reply_text(result: OpenCodeRunResult) -> str:
    text = result.reply_text.strip()
    if not text:
        text = "OpenCode GOD completed the turn without visible text."
    if len(text) > MAX_REPLY_TEXT:
        return text[: MAX_REPLY_TEXT - 3] + "..."
    return text


def _post_peer_chat_writeback(
    *,
    config: RunnerConfig,
    context: str,
    content: str,
    request_id: str | None,
) -> dict[str, Any]:
    payload = _build_chat_post_message_payload(
        context=context,
        content=content,
        request_id=request_id,
    )
    req = urllib.request.Request(
        f"http://127.0.0.1:{config.mcp_port}/mcp/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"MCP chat_post_message failed: HTTP {exc.code}: {body}") from exc
    data = json.loads(response_body) if response_body else {}
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError("MCP chat_post_message response missing result")
    if result.get("isError") is True:
        raise RuntimeError(f"MCP chat_post_message returned isError: {result}")
    return {
        "status": "ok",
        "tool": "chat_post_message",
        "jsonrpc_id": payload["id"],
    }


def _build_chat_post_message_payload(
    *,
    context: str,
    content: str,
    request_id: str | None,
) -> dict[str, Any]:
    parsed = json.loads(context)
    if not isinstance(parsed, dict):
        raise ValueError("peer chat context must be an object")
    inbox_item = parsed.get("inbox_item")
    if not isinstance(inbox_item, dict):
        raise ValueError("peer chat context missing inbox_item")
    conversation_id = _required_context_text(parsed, "conversation_id")
    participant_id = _required_context_text(parsed, "participant_id")
    god_session_id = _required_context_text(parsed, "god_session_id")
    inbox_item_id = _required_context_text(inbox_item, "id")
    client_request_id = request_id or f"opencode-peer-chat-{uuid.uuid4().hex}"
    return {
        "jsonrpc": "2.0",
        "id": client_request_id,
        "method": "tools/call",
        "params": {
            "name": "chat_post_message",
            "arguments": {
                "conversation_id": conversation_id,
                "participant_id": participant_id,
                "god_session_id": god_session_id,
                "client_request_id": client_request_id,
                "content": content,
                "reply_to_inbox_item_id": inbox_item_id,
                "envelope": {
                    "type": "message",
                    "schema_version": 1,
                    "writeback_path": "opencode_callback_bridge",
                },
            },
        },
    }


def _required_context_text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"peer chat context missing {key}")
    return value.strip()


def _first_text_value(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _bounded(value: object, limit: int = MAX_ARTIFACT_TEXT) -> str:
    if value is None:
        return ""
    text = str(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _emit_error(
    code: str,
    message: str,
    *,
    artifacts: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "error",
        "runtime": "opencode",
        "code": code,
        "message": message,
        "artifacts": artifacts or {},
    }
    if request_id is not None:
        payload["request_id"] = request_id
    _emit(payload)


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


if __name__ == "__main__":
    main()
