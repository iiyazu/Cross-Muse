from __future__ import annotations

import asyncio
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from xmuse_core.agents.protocol import StdoutMessage

APP_SERVER_STREAM_LIMIT_BYTES = 16 * 1024 * 1024


@dataclass
class AppServerTurnAccumulator:
    request_id: str | None
    clock: Callable[[], float] = time.monotonic
    initial_latency_stages: dict[str, dict[str, float]] | None = None
    turn_id: str | None = None
    _deltas: list[str] = field(default_factory=list)
    _final_text: str | None = None
    _latency_stages: dict[str, dict[str, float]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.initial_latency_stages:
            return
        for name, stage in self.initial_latency_stages.items():
            at = stage.get("at") if isinstance(stage, dict) else None
            if isinstance(name, str) and isinstance(at, (int, float)):
                self._latency_stages[name] = {"at": float(at)}

    def feed(self, message: dict[str, Any]) -> StdoutMessage | None:
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return None
        if method == "mcpServer/startupStatus/updated":
            if _is_xmuse_mcp_ready(params):
                self._record_stage("mcp_tools_ready")
            return None
        if method == "turn/started":
            turn = params.get("turn")
            if isinstance(turn, dict):
                self.turn_id = _clean_text(turn.get("id")) or self.turn_id
            self._record_stage("codex_app_server_turn_start")
            return None
        if method == "error" and self._matches_turn(params):
            return StdoutMessage(
                type="error",
                request_id=self.request_id,
                runtime="codex-app-server",
                code="codex_app_server_error",
                message=_error_notification_message(params),
            )
        if method in {"item/started", "item/completed"} and self._matches_turn(params):
            tool_name = _mcp_tool_name(params)
            if tool_name in {
                "chat_create_collaboration_request",
                "chat_emit_proposal",
                "chat_mention",
                "chat_post_message",
                "chat_record_collaboration_response",
                "chat_read_inbox",
            }:
                self._record_stage("mcp_tool_call_detected")
                if method == "item/started":
                    self._record_stage("mcp_tool_call_started")
                else:
                    self._record_stage("mcp_tool_call_completed")
                self._record_stage(tool_name)
            return None
        if method == "item/agentMessage/delta" and self._matches_turn(params):
            delta_value = params.get("delta")
            if isinstance(delta_value, str) and delta_value:
                self._record_stage("first_stream_delta")
                delta = delta_value
                self._deltas.append(delta)
            return None
        if method == "item/completed" and self._matches_turn(params):
            item = params.get("item")
            if isinstance(item, dict) and item.get("type") == "agentMessage":
                text = _clean_text(item.get("text"))
                if text:
                    self._final_text = text
            return None
        if method == "turn/completed" and self._matches_turn(params):
            turn = params.get("turn")
            if _turn_completed_failed(turn):
                return StdoutMessage(
                    type="error",
                    request_id=self.request_id,
                    runtime="codex-app-server",
                    code="codex_app_server_error",
                    message=_turn_error_message(turn),
                )
            return StdoutMessage(
                type="result",
                request_id=self.request_id,
                runtime="codex-app-server",
                status="success",
                message=self._final_message(),
                artifacts={
                    "stdout": self._final_message(),
                    "transport": "codex-app-server",
                    "latency_stages": self._latency_stages,
                },
            )
        return None

    def _record_stage(self, name: str) -> None:
        if name not in self._latency_stages:
            self._latency_stages[name] = {"at": self.clock()}

    def latency_stages(self) -> dict[str, dict[str, float]]:
        return {name: dict(stage) for name, stage in self._latency_stages.items()}

    def _matches_turn(self, params: dict[str, Any]) -> bool:
        if self.turn_id is None:
            turn = params.get("turn")
            if isinstance(turn, dict):
                self.turn_id = _clean_text(turn.get("id"))
            else:
                self.turn_id = _clean_text(params.get("turnId"))
        if self.turn_id is None:
            return True
        turn_id = _clean_text(params.get("turnId"))
        if turn_id is None:
            turn = params.get("turn")
            if isinstance(turn, dict):
                turn_id = _clean_text(turn.get("id"))
        return turn_id is None or turn_id == self.turn_id

    def _final_message(self) -> str:
        return (self._final_text or "".join(self._deltas)).strip()


class CodexAppServerTransport:
    """Codex app-server JSON-RPC transport for Ray GOD actors."""

    def __init__(
        self,
        *,
        god_id: str,
        role: str,
        display_name: str,
        model: str,
        worktree: Path,
        db_path: Path | None = None,
        mcp_port: int = 8100,
        codex_command: str = "codex",
        reasoning_effort: str = "low",
        enable_mcp: bool = False,
        resume_thread_id: str | None = None,
    ) -> None:
        self._god_id = god_id
        self._role = role
        self._display_name = display_name
        self._model = model
        self._worktree = worktree
        self._db_path = db_path
        self._mcp_port = mcp_port
        self._codex_command = codex_command
        self._reasoning_effort = _normalize_effort(reasoning_effort)
        self._enable_mcp = enable_mcp
        self._process: asyncio.subprocess.Process | None = None
        self._next_request_id = 1
        self._thread_id: str | None = None
        self._resume_thread_id = _clean_text(resume_thread_id)
        self._active_turn_request_id: int | None = None
        self._active_accumulator: AppServerTurnAccumulator | None = None
        self._active_stream_id: str | None = None
        self._active_turn_context: str | None = None
        self._active_request_id: str | None = None

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        self._process = await asyncio.create_subprocess_exec(
            *self._command(),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self._worktree,
            limit=APP_SERVER_STREAM_LIMIT_BYTES,
        )
        await self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "xmuse-ray-god",
                    "version": "0",
                    "title": "xmuse Ray GOD",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        if self._resume_thread_id is not None:
            response = await self._request(
                "thread/resume",
                self._thread_resume_params(self._resume_thread_id),
            )
            thread = response.get("thread") if isinstance(response, dict) else None
            thread_id = _clean_text(thread.get("id")) if isinstance(thread, dict) else None
            self._thread_id = thread_id or self._resume_thread_id
            return
        response = await self._request(
            "thread/start",
            self._thread_start_params(),
        )
        thread = response.get("thread") if isinstance(response, dict) else None
        if not isinstance(thread, dict):
            raise RuntimeError("codex app-server thread/start returned no thread")
        thread_id = _clean_text(thread.get("id"))
        if thread_id is None:
            raise RuntimeError("codex app-server thread/start returned no thread id")
        self._thread_id = thread_id

    async def send_typed(self, msg_type: str, **kwargs: object) -> None:
        await self.start()
        if self._thread_id is None:
            raise RuntimeError("codex app-server thread is not initialized")
        if self._active_accumulator is not None:
            raise RuntimeError("codex app-server transport already has an active turn")
        request_id = _clean_text(kwargs.get("request_id"))
        stream_started_at = self._start_stream_if_possible(
            request_id=request_id,
            context=kwargs.get("context"),
        )
        prompt = _format_turn_prompt(
            role=self._role,
            msg_type=msg_type,
            prompt=_clean_text(kwargs.get("prompt")) or "",
            context=_clean_text(kwargs.get("context")) or "",
        )
        self._active_turn_context = _clean_text(kwargs.get("context")) or ""
        self._active_request_id = request_id
        initial_latency_stages = (
            {"stream_started": {"at": stream_started_at}}
            if stream_started_at is not None
            else None
        )
        self._active_accumulator = AppServerTurnAccumulator(
            request_id=request_id,
            initial_latency_stages=initial_latency_stages,
        )
        self._active_turn_request_id = await self._send_request(
            "turn/start",
            {
                "threadId": self._thread_id,
                "input": [{"type": "text", "text": prompt}],
                "cwd": str(self._worktree),
                "model": self._model or None,
                "approvalPolicy": "never",
                "sandboxPolicy": {"type": "dangerFullAccess"},
                "effort": self._reasoning_effort,
            },
        )

    async def receive(self) -> StdoutMessage | None:
        await self.start()
        if self._active_accumulator is None:
            return None
        while True:
            message = await self._read_message()
            if message is None:
                return None
            if self._is_active_turn_error(message):
                self._finish_stream(status="error")
                self._active_accumulator = None
                return StdoutMessage(
                    type="error",
                    request_id=None,
                    runtime="codex-app-server",
                    code="codex_app_server_error",
                    message=str(message.get("error") or "codex app-server turn failed"),
                )
            self._record_stream_delta(message)
            result = self._active_accumulator.feed(message)
            if result is not None:
                if result.type != "error":
                    self._maybe_record_callback_bridge(result)
                stream_status = "error" if result.type == "error" else "done"
                self._finish_stream(status=stream_status)
                self._active_accumulator = None
                self._active_turn_request_id = None
                self._active_turn_context = None
                self._active_request_id = None
                return result

    def active_latency_stages(self) -> dict[str, dict[str, float]]:
        if self._active_accumulator is None:
            return {}
        return self._active_accumulator.latency_stages()

    async def shutdown(self) -> None:
        if self._process is None or self._process.returncode is not None:
            return
        self._process.terminate()
        try:
            await asyncio.wait_for(self._process.wait(), timeout=5)
        except TimeoutError:
            self._process.kill()
            await self._process.wait()

    def get_info(self) -> dict[str, object]:
        return {
            "alive": self._process is not None and self._process.returncode is None,
            "pid": self._process.pid if self._process else None,
            "transport": "codex-app-server",
            "thread_id": self._thread_id,
            "resume_thread_id": self._resume_thread_id,
        }

    def _start_stream_if_possible(
        self,
        *,
        request_id: str | None,
        context: object,
    ) -> float | None:
        if self._db_path is None:
            return None
        parsed = _parse_context(context)
        conversation_id = _clean_text(parsed.get("conversation_id"))
        if conversation_id is None:
            return None
        inbox_item = parsed.get("inbox_item")
        source_inbox_item_id = None
        if isinstance(inbox_item, dict):
            source_inbox_item_id = _clean_text(inbox_item.get("id"))
        try:
            from xmuse_core.chat.stream_store import ChatStreamStore

            stream = ChatStreamStore(self._db_path).start_or_reset(
                conversation_id=conversation_id,
                author=_clean_text(parsed.get("participant_id")) or self._god_id,
                role="assistant",
                request_id=request_id,
                source_inbox_item_id=source_inbox_item_id,
            )
            self._active_stream_id = stream.id
            return time.monotonic()
        except Exception:
            self._active_stream_id = None
            return None

    def _record_stream_delta(self, message: dict[str, Any]) -> None:
        if self._db_path is None or self._active_stream_id is None:
            return
        if message.get("method") != "item/agentMessage/delta":
            return
        params = message.get("params")
        if not isinstance(params, dict):
            return
        delta = params.get("delta")
        if not isinstance(delta, str) or not delta:
            return
        try:
            from xmuse_core.chat.stream_store import ChatStreamStore

            ChatStreamStore(self._db_path).append_delta(self._active_stream_id, delta)
        except Exception:
            return

    def _finish_stream(self, *, status: str) -> None:
        if self._db_path is None or self._active_stream_id is None:
            return
        try:
            from xmuse_core.chat.stream_store import ChatStreamStore

            ChatStreamStore(self._db_path).finish(
                self._active_stream_id,
                status="error" if status == "error" else "done",
            )
        except Exception:
            return
        finally:
            self._active_stream_id = None

    def _command(self) -> list[str]:
        command = [
            self._codex_command,
            "app-server",
            "--listen",
            "stdio://",
        ]
        if self._enable_mcp:
            command[2:2] = [
                "-c",
                'mcp_servers.xmuse-platform.type="streamable_http"',
                "-c",
                f'mcp_servers.xmuse-platform.url="http://localhost:{self._mcp_port}/mcp/chat"',
            ]
        return command

    def _thread_start_params(self) -> dict[str, Any]:
        return {
            "cwd": str(self._worktree),
            "model": self._model or None,
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
            "ephemeral": False,
            "baseInstructions": self._base_instructions(),
            "developerInstructions": self._developer_instructions(),
        }

    def _thread_resume_params(self, thread_id: str) -> dict[str, Any]:
        return {
            "threadId": thread_id,
            "cwd": str(self._worktree),
            "model": self._model or None,
            "approvalPolicy": "never",
            "sandbox": "danger-full-access",
            "baseInstructions": self._base_instructions(),
            "developerInstructions": self._developer_instructions(),
        }

    def _maybe_record_callback_bridge(self, result: StdoutMessage) -> None:
        if not self._enable_mcp:
            return
        context = self._active_turn_context
        if not context:
            return
        artifacts = result.artifacts if isinstance(result.artifacts, dict) else {}
        latency_stages = artifacts.get("latency_stages")
        if (
            isinstance(latency_stages, dict)
            and "chat_record_collaboration_response" in latency_stages
        ):
            return
        run_id = _collaboration_response_run_id_from_context(context)
        if run_id is None:
            return
        content = _clean_text(result.message)
        if content is None:
            return
        bridge_result = _post_collaboration_response_bridge(
            port=self._mcp_port,
            context=context,
            run_id=run_id,
            content=content,
            request_id=self._active_request_id,
        )
        if not isinstance(result.artifacts, dict):
            result.artifacts = {}
        result.artifacts["codex_callback_bridge"] = bridge_result
        raw_stages = result.artifacts.get("latency_stages")
        stages = dict(raw_stages) if isinstance(raw_stages, dict) else {}
        bridge_at = time.monotonic()
        stages.setdefault("codex_callback_bridge", {"at": bridge_at})
        stages.setdefault("chat_record_collaboration_response", {"at": bridge_at})
        stages.setdefault("chat_post_message", {"at": bridge_at})
        result.artifacts["latency_stages"] = stages

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        request_id = await self._send_request(method, params)
        while True:
            message = await self._read_message()
            if message is None:
                raise RuntimeError(f"codex app-server closed before {method} response")
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"codex app-server {method} failed: {message['error']}")
            return message.get("result")

    async def _send_request(self, method: str, params: dict[str, Any]) -> int:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("codex app-server process is not started")
        request_id = self._next_request_id
        self._next_request_id += 1
        payload = {"id": request_id, "method": method, "params": params}
        self._process.stdin.write((json.dumps(payload, ensure_ascii=False) + "\n").encode())
        await self._process.stdin.drain()
        return request_id

    async def _read_message(self) -> dict[str, Any] | None:
        if self._process is None or self._process.stdout is None:
            return None
        while True:
            line = await self._process.stdout.readline()
            if not line:
                return None
            try:
                message = json.loads(line.decode(errors="replace"))
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict):
                return message

    def _is_active_turn_error(self, message: dict[str, Any]) -> bool:
        return bool(
            self._active_turn_request_id is not None
            and message.get("id") == self._active_turn_request_id
            and "error" in message
        )

    def _base_instructions(self) -> str:
        return (
            f"You are {self._display_name}, a persistent xmuse GOD peer with role "
            f"{self._role}. Keep chat replies concise and useful. When xmuse MCP is "
            "enabled, MCP writeback is the normal peer-chat path; direct final text "
            "is only for degraded no-tool turns. Do not call tools in peer chat turns "
            "unless this transport explicitly enables xmuse MCP."
        )

    def _developer_instructions(self) -> str:
        if self._enable_mcp:
            return (
                "For xmuse peer_chat_nudge turns, use xmuse MCP as the production "
                "writeback path: call chat_post_message directly with "
                "conversation_id, participant_id, god_session_id, and "
                "reply_to_inbox_item_id=xmuse_context.inbox_item.id, using "
                "xmuse_context.inbox_item.payload.content as the request. "
                "If the inbox request explicitly asks for chat_emit_proposal, "
                "call chat_emit_proposal directly instead of chat_post_message; "
                "that tool is the durable writeback for proposal turns. "
                "chat_read_inbox is only for recovery or batch inspection; "
                "do not call it before simple replies. "
                "Natural-language @mentions inside chat_post_message are display-only "
                "and do not enqueue peer work. When you need another GOD to take "
                "over or review, call chat_mention with "
                "reply_to_inbox_item_id=xmuse_context.inbox_item.id, target_address "
                "set to that GOD's exact @role, and content containing the concrete "
                "handoff request; this closes your current inbox item and enqueues "
                "the target GOD in one durable writeback. "
                "When peer discussion produces work that should enter real "
                "execution, use the structured chat tools: create or reference a "
                "collaboration run, have execute record a JSON "
                "execute_feasibility_verdict via chat_record_collaboration_response "
                "using the approval-gate shape "
                '{"type":"execute_feasibility_verdict","status":"executable",'
                '"execution_performed":false,"summary":"<why dispatch is safe>",'
                '"evidence_refs":["<ref>"]}; '
                "looser fields such as verdict=feasible do not satisfy dispatch. "
                "If the current inbox item is a collaboration_request or asks you "
                "to use chat_record_collaboration_response, call that tool; do "
                "not return the JSON as final assistant text or streamed stdout. "
                "If you call chat_create_collaboration_request, do not also call "
                "chat_mention for the same target because the collaboration tool "
                "already creates the target inbox and callback. "
                "then emit a lane_graph proposal with chat_emit_proposal and a "
                "collaboration:<run_id> reference, passing "
                "reply_to_inbox_item_id=xmuse_context.inbox_item.id so the proposal "
                "closes the current inbox item. Human approval remains required before "
                "dispatch. "
                "Only return a direct final assistant message if MCP tools are not "
                "available. If mcp_tools_ready has appeared, MCP tools are available; "
                "do not say you cannot perform durable writeback."
            )
        return (
            "For xmuse peer_chat_nudge turns, answer the user-facing chat request "
            "without unnecessary planning narration. Return the reply as the final "
            "assistant message so xmuse can persist it."
        )


def _format_turn_prompt(*, role: str, msg_type: str, prompt: str, context: str) -> str:
    return (
        f"xmuse message type: {msg_type}\n"
        f"role: {role}\n\n"
        f"{prompt.strip()}\n\n"
        "<xmuse_context>\n"
        f"{context.strip()}\n"
        "</xmuse_context>"
    ).strip()


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _error_notification_message(params: dict[str, Any]) -> str:
    error = params.get("error")
    if isinstance(error, dict):
        message = _clean_text(error.get("message"))
        if message is not None:
            return message
    return "codex app-server turn failed"


def _turn_completed_failed(turn: object) -> bool:
    if not isinstance(turn, dict):
        return False
    status = _clean_text(turn.get("status"))
    if status is None:
        return False
    return status.lower() in {"failed", "error", "cancelled", "canceled"}


def _turn_error_message(turn: object) -> str:
    if isinstance(turn, dict):
        error = turn.get("error")
        if isinstance(error, dict):
            message = _clean_text(error.get("message"))
            if message is not None:
                return message
    return "codex app-server turn failed"


def _parse_context(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _collaboration_response_run_id_from_context(context: str) -> str | None:
    parsed = _parse_context(context)
    inbox_item = parsed.get("inbox_item")
    if not isinstance(inbox_item, dict):
        return None
    payload = inbox_item.get("payload")
    if not isinstance(payload, dict):
        return None
    content = _clean_text(payload.get("content"))
    if content is None:
        return None
    if not _asks_for_collaboration_response(content):
        return None
    match = re.search(r"\bcollab_[A-Za-z0-9]+\b", content)
    return match.group(0) if match else None


def _asks_for_collaboration_response(content: str) -> bool:
    normalized = " ".join(content.lower().split())
    if "chat_record_collaboration_response" in normalized:
        return True
    if "collaboration response" in normalized:
        return True
    if "collaboration" in normalized and "record" in normalized and "response" in normalized:
        return True
    compact = "".join(content.split())
    return (
        any(marker in compact for marker in ("协作", "协同"))
        and any(marker in compact for marker in ("响应", "回复", "意见", "审查"))
        and any(marker in compact for marker in ("记录", "提交", "写入", "回填", "回写", "登记"))
    )


def _post_collaboration_response_bridge(
    *,
    port: int,
    context: str,
    run_id: str,
    content: str,
    request_id: str | None,
) -> dict[str, Any]:
    response_payload = _build_collaboration_response_payload(
        context=context,
        run_id=run_id,
        content=_collaboration_response_bridge_content(context=context, content=content),
        request_id=request_id,
    )
    response_result = _call_mcp_chat_tool(port=port, payload=response_payload)
    message_payload = _build_chat_post_message_payload(
        context=context,
        content=content,
        request_id=request_id,
    )
    message_result = _call_mcp_chat_tool(port=port, payload=message_payload)
    return {
        "status": "ok",
        "tools": ["chat_record_collaboration_response", "chat_post_message"],
        "jsonrpc_ids": [response_payload["id"], message_payload["id"]],
        "collaboration_response": _summarize_mcp_result(response_result),
        "chat_message": _summarize_mcp_result(message_result),
    }


def _build_collaboration_response_payload(
    *,
    context: str,
    run_id: str,
    content: str,
    request_id: str | None,
) -> dict[str, Any]:
    parsed, _inbox_item = _parse_peer_chat_context(context)
    client_request_id = (
        f"{request_id}:codex_collaboration_response"
        if request_id
        else f"codex-peer-collaboration-response-{uuid.uuid4().hex}"
    )
    return {
        "jsonrpc": "2.0",
        "id": client_request_id,
        "method": "tools/call",
        "params": {
            "name": "chat_record_collaboration_response",
            "arguments": {
                "conversation_id": _required_context_text(parsed, "conversation_id"),
                "participant_id": _required_context_text(parsed, "participant_id"),
                "god_session_id": _required_context_text(parsed, "god_session_id"),
                "run_id": run_id,
                "content": content,
                "status": "received",
            },
        },
    }


def _build_chat_post_message_payload(
    *,
    context: str,
    content: str,
    request_id: str | None,
) -> dict[str, Any]:
    parsed, inbox_item = _parse_peer_chat_context(context)
    client_request_id = (
        f"{request_id}:codex_callback_message"
        if request_id
        else f"codex-peer-chat-message-{uuid.uuid4().hex}"
    )
    return {
        "jsonrpc": "2.0",
        "id": client_request_id,
        "method": "tools/call",
        "params": {
            "name": "chat_post_message",
            "arguments": {
                "conversation_id": _required_context_text(parsed, "conversation_id"),
                "participant_id": _required_context_text(parsed, "participant_id"),
                "god_session_id": _required_context_text(parsed, "god_session_id"),
                "client_request_id": client_request_id,
                "content": content,
                "reply_to_inbox_item_id": _required_context_text(inbox_item, "id"),
                "envelope": {
                    "type": "message",
                    "schema_version": 1,
                    "writeback_path": "codex_callback_bridge",
                    "callback_action": "chat_record_collaboration_response",
                },
            },
        },
    }


def _parse_peer_chat_context(context: str) -> tuple[dict[str, Any], dict[str, Any]]:
    parsed = _parse_context(context)
    inbox_item = parsed.get("inbox_item")
    if not isinstance(inbox_item, dict):
        raise ValueError("peer chat context missing inbox_item")
    return parsed, inbox_item


def _required_context_text(container: dict[str, Any], key: str) -> str:
    value = _clean_text(container.get(key))
    if value is None:
        raise ValueError(f"peer chat context missing {key}")
    return value


def _call_mcp_chat_tool(*, port: int, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/mcp/chat",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        name = payload["params"]["name"]
        raise RuntimeError(
            f"MCP {name} failed: HTTP {exc.code}: {body}"
        ) from exc
    data = json.loads(response_body) if response_body else {}
    result = data.get("result") if isinstance(data, dict) else None
    if not isinstance(result, dict):
        raise RuntimeError(f"MCP {payload['params']['name']} response missing result")
    _raise_for_mcp_tool_error(result, tool_name=str(payload["params"]["name"]))
    return result


def _collaboration_response_bridge_content(*, context: str, content: str) -> str:
    _parsed, inbox_item = _parse_peer_chat_context(context)
    payload = inbox_item.get("payload")
    request_content = (
        _clean_text(payload.get("content"))
        if isinstance(payload, dict)
        else None
    )
    if request_content is None or "execute_feasibility_verdict" not in request_content:
        return content
    existing_verdict = _valid_execute_feasibility_verdict(content)
    if existing_verdict is not None:
        return existing_verdict
    normalized = " ".join(content.lower().split())
    if _plain_text_blocks_execute_feasibility(normalized):
        return content
    if not _plain_text_allows_execute_feasibility(normalized):
        return content
    verdict = {
        "type": "execute_feasibility_verdict",
        "status": "executable",
        "execution_performed": False,
        "summary": content.strip(),
        "evidence_refs": [_bridge_evidence_ref(inbox_item)],
    }
    return json.dumps(verdict, ensure_ascii=False, separators=(",", ":"))


def _valid_execute_feasibility_verdict(content: str) -> str | None:
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if parsed.get("type") != "execute_feasibility_verdict":
        return None
    if parsed.get("status") != "executable":
        return None
    if parsed.get("execution_performed") is not False:
        return None
    evidence_refs = parsed.get("evidence_refs")
    if not isinstance(evidence_refs, list) or not evidence_refs:
        return None
    if not all(isinstance(ref, str) and ref.strip() for ref in evidence_refs):
        return None
    summary = parsed.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return None
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":"))


def _plain_text_blocks_execute_feasibility(normalized: str) -> bool:
    return any(
        marker in normalized
        for marker in (
            "not safe",
            "unsafe",
            "not feasible",
            "not executable",
            "blocked",
            "cannot dispatch",
            "should not dispatch",
        )
    )


def _plain_text_allows_execute_feasibility(normalized: str) -> bool:
    return any(
        marker in normalized
        for marker in (
            "safe to dispatch",
            "safe and executable",
            "executable",
            "feasible",
            "dispatch is safe",
        )
    )


def _bridge_evidence_ref(inbox_item: dict[str, Any]) -> str:
    source_message_id = _clean_text(inbox_item.get("source_message_id"))
    if source_message_id is not None:
        return f"msg:{source_message_id}"
    inbox_item_id = _clean_text(inbox_item.get("id"))
    if inbox_item_id is not None:
        return f"inbox:{inbox_item_id}"
    return "codex_callback_bridge:execute_feasibility"


def _raise_for_mcp_tool_error(result: dict[str, Any], *, tool_name: str) -> None:
    if result.get("isError") is True:
        raise RuntimeError(f"MCP {tool_name} returned isError: {result}")
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and isinstance(structured.get("error"), dict):
        error = structured["error"]
        code = error.get("code") or "tool_error"
        message = error.get("message") or code
        raise RuntimeError(f"MCP {tool_name} returned error {code}: {message}")
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return
    first = content[0]
    if not isinstance(first, dict):
        return
    text = first.get("text")
    if not isinstance(text, str):
        return
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return
    if isinstance(parsed, dict) and isinstance(parsed.get("error"), dict):
        error = parsed["error"]
        code = error.get("code") or "tool_error"
        message = error.get("message") or code
        raise RuntimeError(f"MCP {tool_name} returned error {code}: {message}")


def _summarize_mcp_result(result: dict[str, Any]) -> dict[str, Any]:
    content = result.get("content")
    if not isinstance(content, list) or not content:
        return {"content_items": 0}
    first = content[0]
    if not isinstance(first, dict):
        return {"content_items": len(content)}
    text = first.get("text")
    if not isinstance(text, str):
        return {"content_items": len(content)}
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"content_items": len(content), "text": text[:500]}
    if isinstance(parsed, dict):
        return {
            key: parsed[key]
            for key in ("message", "run", "callback")
            if key in parsed
        } or {"content_items": len(content)}
    return {"content_items": len(content)}


def _is_xmuse_mcp_ready(params: dict[str, Any]) -> bool:
    server_name = (
        _clean_text(params.get("serverName"))
        or _clean_text(params.get("server_name"))
        or _clean_text(params.get("name"))
    )
    server = params.get("server")
    if server_name is None and isinstance(server, dict):
        server_name = _clean_text(server.get("name"))
    if server_name is not None and server_name != "xmuse-platform":
        return False
    status = (
        _clean_text(params.get("status"))
        or _clean_text(params.get("startupStatus"))
        or _clean_text(params.get("state"))
    )
    if status is None and isinstance(server, dict):
        status = (
            _clean_text(server.get("status"))
            or _clean_text(server.get("startupStatus"))
            or _clean_text(server.get("state"))
        )
    return status is not None and status.lower() in {"ready", "running", "enabled"}


def _mcp_tool_name(params: dict[str, Any]) -> str | None:
    item = params.get("item")
    if not isinstance(item, dict):
        return None
    direct = (
        _clean_text(item.get("toolName"))
        or _clean_text(item.get("tool_name"))
        or _clean_text(item.get("name"))
    )
    if direct:
        return direct
    tool = item.get("tool")
    if isinstance(tool, str):
        return _clean_text(tool)
    if isinstance(tool, dict):
        return _clean_text(tool.get("name"))
    call = item.get("call")
    if isinstance(call, dict):
        return (
            _clean_text(call.get("toolName"))
            or _clean_text(call.get("tool_name"))
            or _clean_text(call.get("name"))
        )
    return None


def _normalize_effort(value: object) -> str:
    text = _clean_text(value) or "low"
    normalized = text.lower()
    if normalized in {"none", "minimal", "low", "medium", "high", "xhigh"}:
        return normalized
    return "low"


__all__ = ["AppServerTurnAccumulator", "CodexAppServerTransport"]
