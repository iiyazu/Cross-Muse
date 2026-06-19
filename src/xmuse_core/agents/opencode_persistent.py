from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import urllib.error
import urllib.request
import uuid
from contextlib import contextmanager
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
    with _temporary_runtime_opencode_config(config) as run_cwd:
        command = _opencode_command(config, full_prompt)
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=run_cwd,
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
        "--pure",
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


@contextmanager
def _temporary_runtime_opencode_config(config: RunnerConfig):
    path = config.worktree / "opencode.json"
    existed = path.exists()
    original = path.read_bytes() if existed else b""
    _write_runtime_opencode_config(config, config_dir=config.worktree)
    try:
        yield config.worktree
    finally:
        if existed:
            path.write_bytes(original)
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def _write_runtime_opencode_config(config: RunnerConfig, *, config_dir: Path) -> Path:
    config_dir.mkdir(parents=True, exist_ok=True)
    runtime_config = _runtime_opencode_config(config)
    (config_dir / "opencode.json").write_text(
        json.dumps(runtime_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return config_dir


def _runtime_opencode_config(config: RunnerConfig) -> dict[str, Any]:
    project_config = _load_project_opencode_config(config.worktree / "opencode.json")
    runtime_config: dict[str, Any] = {}
    for key in ("$schema", "model", "provider"):
        if key in project_config:
            runtime_config[key] = project_config[key]
    runtime_config.setdefault("$schema", "https://opencode.ai/config.json")
    runtime_config["permission"] = "allow"
    configured_mcp = project_config.get("mcp")
    mcp = dict(configured_mcp) if isinstance(configured_mcp, dict) else {}
    mcp["xmuse-platform"] = {
        "type": "remote",
        "url": f"http://127.0.0.1:{config.mcp_port}/sse",
    }
    runtime_config["mcp"] = mcp
    return runtime_config


def _load_project_opencode_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


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
    transcript = _peer_chat_recent_transcript(context)
    collaboration_response_run_id = _peer_chat_collaboration_response_run_id(context)
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
    if transcript:
        sections.extend(["", "## Recent Transcript", "", transcript])
    if collaboration_response_run_id:
        sections.extend(
            [
                "",
                "## Structured Callback",
                "",
                "This request asks you to record a formal collaboration response. "
                "Prefer returning exactly one JSON object and no markdown:",
                (
                    '{"callback_action":"chat_record_collaboration_response",'
                    f'"run_id":"{collaboration_response_run_id}",'
                    '"status":"received","content":"<formal response text>",'
                    '"chat_reply":"<concise groupchat acknowledgement>"}'
                ),
                "If you reply in natural language instead, xmuse will still persist "
                "that reply as the formal collaboration response through the callback "
                "bridge for this run.",
                "Preserve exact commands, lane ids, proof boundaries, and forbidden "
                "claims from the current request and recent transcript. Do not "
                "substitute or invent a different command.",
            ]
        )
    sections.extend(["", "## Reply Contract", ""])
    if collaboration_response_run_id:
        sections.append(
            "Return one bounded collaboration response for the run above; do not "
            "ask another GOD to execute the lane from this peer-chat turn."
        )
    else:
        sections.extend(
            [
                "Return only the concise natural-language content that should be "
                "posted as your GOD chat reply.",
                "If another GOD should act next, mention the exact @role and "
                "include a concrete handoff request.",
            ]
        )
    sections.extend(
        [
            "Do not call tools. Do not edit files. Do not run tests. Do not inspect "
            "unrelated repository state.",
            "xmuse will write your reply through a durable callback bridge; stdout "
            "alone is not counted as chat truth.",
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


def _peer_chat_recent_transcript(context: str, limit: int = 6000) -> str:
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


def _peer_chat_collaboration_response_run_id(context: str) -> str:
    content = _peer_chat_request_content(context)
    if not content:
        return ""
    match = re.search(r"\bcollab_[A-Za-z0-9]+\b", content)
    if not match:
        return ""
    normalized = " ".join(content.lower().split())
    if "chat_record_collaboration_response" in normalized:
        return match.group(0)
    if "collaboration response" in normalized:
        return match.group(0)
    if "collaboration" in normalized and re.search(
        r"\b(respond|response|review)\b",
        normalized,
    ):
        return match.group(0)
    if (
        "collaboration" in normalized
        and "record" in normalized
        and "response" in normalized
        and ("durable" in normalized or "durably" in normalized)
    ):
        return match.group(0)
    if re.search(r"\brecord\b.*\bformal\b.*\bresponse\b", normalized):
        return match.group(0)
    if re.search(r"\bformal\b.*\bresponse\b", normalized) and (
        "collaboration run" in normalized or "collaboration" in normalized
    ):
        return match.group(0)
    if _looks_like_cjk_collaboration_response_request(content):
        return match.group(0)
    return ""


def _looks_like_cjk_collaboration_response_request(content: str) -> bool:
    compact = re.sub(r"\s+", "", content)
    has_collaboration = any(marker in compact for marker in ("协作", "协同"))
    has_response = any(marker in compact for marker in ("响应", "回复", "意见", "审查"))
    has_record = any(
        marker in compact
        for marker in (
            "记录",
            "提交",
            "写入",
            "回填",
            "回写",
            "登记",
        )
    )
    return has_collaboration and has_response and has_record


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
    expected_run_id = _peer_chat_collaboration_response_run_id(context)
    callback_action = (
        _parse_peer_chat_callback_action(
            content,
            expected_run_id=expected_run_id,
        )
        if expected_run_id
        else None
    )
    if expected_run_id and callback_action is None:
        callback_action = {
            "callback_action": "chat_record_collaboration_response",
            "run_id": expected_run_id,
            "status": "received",
            "content": content.strip(),
            "chat_reply": content.strip(),
        }
    if callback_action is not None:
        response_payload = _build_collaboration_response_payload(
            context=context,
            action=callback_action,
            request_id=request_id,
        )
        response_result = _call_mcp_chat_tool(
            port=config.mcp_port,
            payload=response_payload,
        )
        chat_content = callback_action.get("chat_reply") or callback_action["content"]
        message_payload = _build_chat_post_message_payload(
            context=context,
            content=chat_content,
            request_id=request_id,
            callback_action="chat_record_collaboration_response",
        )
        message_result = _call_mcp_chat_tool(
            port=config.mcp_port,
            payload=message_payload,
        )
        return {
            "status": "ok",
            "tools": ["chat_record_collaboration_response", "chat_post_message"],
            "jsonrpc_ids": [response_payload["id"], message_payload["id"]],
            "collaboration_response": _summarize_mcp_result(response_result),
            "chat_message": _summarize_mcp_result(message_result),
        }

    payload = _build_chat_post_message_payload(
        context=context,
        content=content,
        request_id=request_id,
    )
    result = _call_mcp_chat_tool(port=config.mcp_port, payload=payload)
    return {
        "status": "ok",
        "tool": "chat_post_message",
        "jsonrpc_id": payload["id"],
        "chat_message": _summarize_mcp_result(result),
    }


def _call_mcp_chat_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp/chat",
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
        raise RuntimeError(f"MCP {payload['params']['name']} response missing result")
    if result.get("isError") is True:
        raise RuntimeError(f"MCP {payload['params']['name']} returned isError: {result}")
    return result


def _build_chat_post_message_payload(
    *,
    context: str,
    content: str,
    request_id: str | None,
    callback_action: str | None = None,
) -> dict[str, Any]:
    parsed, inbox_item = _parse_peer_chat_context(context)
    conversation_id = _required_context_text(parsed, "conversation_id")
    participant_id = _required_context_text(parsed, "participant_id")
    god_session_id = _required_context_text(parsed, "god_session_id")
    inbox_item_id = _required_context_text(inbox_item, "id")
    client_request_id = request_id or f"opencode-peer-chat-{uuid.uuid4().hex}"
    envelope: dict[str, Any] = {
        "type": "message",
        "schema_version": 1,
        "writeback_path": "opencode_callback_bridge",
    }
    if callback_action is not None:
        envelope["callback_action"] = callback_action
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
                "envelope": envelope,
            },
        },
    }


def _build_collaboration_response_payload(
    *,
    context: str,
    action: dict[str, str],
    request_id: str | None,
) -> dict[str, Any]:
    parsed, _inbox_item = _parse_peer_chat_context(context)
    conversation_id = _required_context_text(parsed, "conversation_id")
    participant_id = _required_context_text(parsed, "participant_id")
    god_session_id = _required_context_text(parsed, "god_session_id")
    client_request_id = (
        f"{request_id}:collaboration_response"
        if request_id
        else f"opencode-peer-collaboration-response-{uuid.uuid4().hex}"
    )
    return {
        "jsonrpc": "2.0",
        "id": client_request_id,
        "method": "tools/call",
        "params": {
            "name": "chat_record_collaboration_response",
            "arguments": {
                "conversation_id": conversation_id,
                "participant_id": participant_id,
                "god_session_id": god_session_id,
                "run_id": action["run_id"],
                "content": action["content"],
                "status": action.get("status") or "received",
            },
        },
    }


def _parse_peer_chat_context(context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = json.loads(context)
    if not isinstance(parsed, dict):
        raise ValueError("peer chat context must be an object")
    inbox_item = parsed.get("inbox_item")
    if not isinstance(inbox_item, dict):
        raise ValueError("peer chat context missing inbox_item")
    return parsed, inbox_item


def _parse_peer_chat_callback_action(
    content: str,
    *,
    expected_run_id: str | None = None,
) -> dict[str, str] | None:
    actions = [
        action
        for parsed in _peer_chat_callback_json_objects(content)
        if (action := _callback_action_from_payload(parsed)) is not None
    ]
    if not actions:
        return None
    if expected_run_id is not None:
        actions = [action for action in actions if action["run_id"] == expected_run_id]
        if not actions:
            return None
    run_ids = {action["run_id"] for action in actions}
    if len(run_ids) != 1:
        return None
    return actions[-1]


def _peer_chat_callback_json_objects(content: str) -> list[dict[str, Any]]:
    stripped = content.strip()
    if not stripped:
        return []
    texts = [stripped]
    fenced = _strip_json_fence(stripped)
    if fenced != stripped:
        texts.append(fenced)
    texts.extend(
        match.group(1).strip()
        for match in re.finditer(
            r"```(?:json)?\s*(.*?)```",
            stripped,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )
    decoder = json.JSONDecoder()
    objects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for text in texts:
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                parsed, _end = decoder.raw_decode(text[index:])
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, dict):
                continue
            key = json.dumps(parsed, sort_keys=True, ensure_ascii=False)
            if key in seen:
                continue
            seen.add(key)
            objects.append(parsed)
    return objects


def _callback_action_from_payload(parsed: dict[str, Any]) -> dict[str, str] | None:
    if parsed.get("callback_action") != "chat_record_collaboration_response":
        return None
    run_id = parsed.get("run_id")
    response_content = parsed.get("content")
    if not isinstance(run_id, str) or not run_id.strip():
        return None
    if not isinstance(response_content, str) or not response_content.strip():
        return None
    status = parsed.get("status", "received")
    if not isinstance(status, str) or status not in {"received", "timeout", "failed"}:
        status = "received"
    chat_reply = parsed.get("chat_reply")
    action = {
        "callback_action": "chat_record_collaboration_response",
        "run_id": run_id.strip(),
        "status": status,
        "content": response_content.strip(),
    }
    if isinstance(chat_reply, str) and chat_reply.strip():
        action["chat_reply"] = chat_reply.strip()
    return action


def _strip_json_fence(content: str) -> str:
    if not content.startswith("```"):
        return content
    lines = content.splitlines()
    if len(lines) >= 3 and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return content


def _summarize_mcp_result(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return {"status": "ok"}
    first = content[0]
    if not isinstance(first, dict):
        return {"status": "ok"}
    text = first.get("text")
    if not isinstance(text, str):
        return {"status": "ok"}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {"status": "ok"}
    if not isinstance(payload, dict):
        return {"status": "ok"}
    summary = {"status": "ok"}
    for key in ("message", "run"):
        value = payload.get(key)
        if isinstance(value, dict):
            identifier = value.get("id") or value.get("run_id")
            if isinstance(identifier, str):
                summary[f"{key}_id"] = identifier
    return summary


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
