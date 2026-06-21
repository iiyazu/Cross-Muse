from __future__ import annotations

import argparse
import json
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

DEFAULT_GROK_MODEL_ID = "grok-composer-2.5-fast"
MAX_ARTIFACT_TEXT = 12000
MAX_REPLY_TEXT = 8000


@dataclass
class RunnerConfig:
    model: str
    mcp_port: int
    worktree: Path
    role: str
    timeout_s: float
    grok_binary: str
    session_id: str | None = None


@dataclass(frozen=True)
class GrokRunResult:
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
        _run_grok_turn(config, message)


def _parse_args() -> RunnerConfig:
    parser = argparse.ArgumentParser(description="xmuse persistent Grok session shim")
    parser.add_argument("--model", default=DEFAULT_GROK_MODEL_ID)
    parser.add_argument("--mcp-port", type=int, default=8100)
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--timeout-s", type=float, default=900.0)
    parser.add_argument("--grok-binary", default="grok")
    parser.add_argument("--session-id")
    args = parser.parse_args()
    return RunnerConfig(
        model=args.model,
        mcp_port=args.mcp_port,
        worktree=args.worktree,
        role=args.role,
        timeout_s=args.timeout_s,
        grok_binary=args.grok_binary,
        session_id=args.session_id,
    )


def _handle_control_message(message: dict[str, Any]) -> bool:
    msg_type = message.get("type")
    if msg_type == "hello":
        _emit(
            {
                "type": "hello_ack",
                "protocol_version": PROTOCOL_VERSION,
                "runtime": "grok",
            }
        )
        return True
    if msg_type == "ping":
        _emit({"type": "pong", "runtime": "grok"})
        return True
    return msg_type == "abort"


def _run_grok_turn(config: RunnerConfig, message: dict[str, Any]) -> None:
    msg_type = str(message.get("type") or "task")
    prompt = str(message.get("prompt") or "")
    context = str(message.get("context") or "")
    request_id = _first_text_value(message.get("request_id"))
    full_prompt = _format_turn_prompt(config, msg_type=msg_type, prompt=prompt, context=context)

    try:
        previous_session_id = config.session_id
        result = _run_grok(config, full_prompt)
    except subprocess.TimeoutExpired as exc:
        _emit_error(
            "grok_timeout",
            f"grok turn timed out after {config.timeout_s:g}s",
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
            "grok_spawn_failed",
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
        "grok_session_id": result.session_id,
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
            f"grok_exit_{result.returncode}",
            _bounded(result.stderr.strip() or result.reply_text or "grok turn failed"),
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
                "grok_callback_writeback_failed",
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
            "runtime": "grok",
            "message": reply_text,
            "artifacts": artifacts,
            **({"request_id": request_id} if request_id is not None else {}),
        }
    )


def _run_grok(config: RunnerConfig, full_prompt: str) -> GrokRunResult:
    global _ACTIVE_CHILD
    command = _grok_command(config, full_prompt)
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
    reply_text, session_id = _parse_grok_json_output(stdout or "")
    return GrokRunResult(
        returncode=process.returncode or 0,
        stdout=stdout or "",
        stderr=stderr or "",
        reply_text=reply_text,
        session_id=session_id or config.session_id,
    )


def _grok_command(config: RunnerConfig, full_prompt: str) -> list[str]:
    command = [
        config.grok_binary,
        "-m",
        config.model,
        "-p",
        full_prompt,
        "--output-format",
        "json",
        "--max-turns",
        "1",
        "--no-wait-for-background",
        "--disable-web-search",
    ]
    if config.session_id:
        command.extend(["-r", config.session_id])
    command.extend(["-w", str(config.worktree)])
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
        "You are a Grok CLI peer inside xmuse GOD groupchat.",
        f"Role: {config.role}",
        f"Message type: {msg_type}",
        "If this is a peer chat turn, answer the inbox request. xmuse will "
        "write your final text back through its callback bridge; do not treat "
        "stdout as durable chat truth.",
    ]
    if context:
        sections.extend(["## Context", context])
    if prompt:
        sections.extend(["## Request", prompt])
    return "\n\n".join(sections)


def _format_peer_chat_prompt(
    config: RunnerConfig,
    *,
    context: str,
    fallback_prompt: str,
) -> str:
    request = _peer_chat_request_content(context) or fallback_prompt
    roster = _peer_chat_roster_text(context)
    transcript = _peer_chat_transcript_text(context)
    sections = [
        "You are a Grok CLI peer inside xmuse GOD groupchat.",
        f"Role: {config.role}",
        "Message type: peer_chat_nudge",
        "Do not call tools. Return only the concise natural-language reply "
        "that should be written to the current inbox item. xmuse will persist "
        "your reply through its callback bridge.",
    ]
    if roster:
        sections.extend(["## Participants", roster])
    if transcript:
        sections.extend(["## Recent Transcript", transcript])
    if request:
        sections.extend(["## Inbox Request", request])
    return "\n\n".join(sections)


def _peer_chat_request_content(context: str) -> str:
    try:
        parsed, inbox_item = _parse_peer_chat_context(context)
    except ValueError:
        return ""
    payload = inbox_item.get("payload")
    if not isinstance(payload, dict):
        return ""
    content = payload.get("content")
    return content.strip() if isinstance(content, str) else ""


def _peer_chat_roster_text(context: str) -> str:
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
        if isinstance(role, str) and role.strip() and isinstance(display_name, str):
            rows.append(f"@{role.strip()}={display_name.strip()}")
    return "\n".join(rows)


def _peer_chat_transcript_text(context: str, *, limit: int = 3000) -> str:
    try:
        parsed = json.loads(context)
    except json.JSONDecodeError:
        return ""
    if not isinstance(parsed, dict):
        return ""
    group_chat = parsed.get("group_chat")
    if not isinstance(group_chat, dict):
        return ""
    messages = group_chat.get("recent_messages")
    if not isinstance(messages, list):
        return ""
    rows: list[str] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            continue
        role = message.get("role")
        author = message.get("author")
        label = (
            role.strip()
            if isinstance(role, str) and role.strip()
            else author.strip()
            if isinstance(author, str) and author.strip()
            else "message"
        )
        rows.append(f"{label}: {content.strip()}")
    transcript = "\n".join(rows).strip()
    if len(transcript) > limit:
        return transcript[-limit:]
    return transcript


def _parse_grok_json_output(stdout: str) -> tuple[str, str | None]:
    text_parts: list[str] = []
    session_id: str | None = None
    for event in _iter_json_objects(stdout):
        raw_session_id = event.get("sessionId") or event.get("sessionID") or event.get("session_id")
        if isinstance(raw_session_id, str) and raw_session_id.strip():
            session_id = raw_session_id.strip()
        for key in ("text", "message", "response", "content"):
            value = event.get(key)
            if isinstance(value, str) and value:
                text_parts.append(value)
                break
    return "\n".join(part.strip() for part in text_parts if part.strip()).strip(), session_id


def _iter_json_objects(stdout: str) -> list[dict[str, Any]]:
    stripped = stdout.strip()
    if not stripped:
        return []
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]

    events: list[dict[str, Any]] = []
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def _reply_text(result: GrokRunResult) -> str:
    text = result.reply_text.strip()
    if not text:
        text = "Grok GOD completed the turn without visible text."
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
    _call_mcp_platform_tool(port=config.mcp_port, payload=payload)
    return {
        "status": "posted",
        "tool": "chat_post_message",
        "reply_to_inbox_item_id": payload["params"]["arguments"]["reply_to_inbox_item_id"],
    }


def _call_mcp_platform_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
    return _call_mcp_tool(port=port, path="/mcp/chat", payload=payload)


def _call_mcp_tool(*, port: int, path: str, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(
            f"MCP {payload['params']['name']} failed: HTTP {exc.code}: {body}"
        ) from exc
    data = json.loads(response_body) if response_body else {}
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError(f"MCP {payload['params']['name']} response missing result")
    if result.get("isError") is True:
        raise RuntimeError(f"MCP {payload['params']['name']} returned isError: {result}")
    return result


def _build_chat_post_message_payload(
    *,
    context: str,
    content: str,
    request_id: str | None,
) -> dict[str, Any]:
    parsed, inbox_item = _parse_peer_chat_context(context)
    conversation_id = _required_context_text(parsed, "conversation_id")
    participant_id = _required_context_text(parsed, "participant_id")
    god_session_id = _required_context_text(parsed, "god_session_id")
    inbox_item_id = _required_context_text(inbox_item, "id")
    client_request_id = request_id or f"grok-peer-chat-{uuid.uuid4().hex}"
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
                    "writeback_path": "grok_callback_bridge",
                    "request_id": client_request_id,
                },
            },
        },
    }


def _parse_peer_chat_context(context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    try:
        parsed = json.loads(context)
    except json.JSONDecodeError as exc:
        raise ValueError("peer chat context must be JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("peer chat context must be a JSON object")
    inbox_item = parsed.get("inbox_item")
    if not isinstance(inbox_item, dict):
        raise ValueError("peer chat context missing inbox_item")
    return parsed, inbox_item


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
        "runtime": "grok",
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
        process.terminate()
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()


def _communicate_after_terminate(process: subprocess.Popen[str]) -> tuple[str, str]:
    try:
        stdout, stderr = process.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        stdout, stderr = process.communicate()
    return stdout or "", stderr or ""


if __name__ == "__main__":
    main()
