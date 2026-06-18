from __future__ import annotations

import asyncio
import json
import time
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
                "chat_emit_proposal",
                "chat_mention",
                "chat_post_message",
                "chat_read_inbox",
            }:
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
                stream_status = "error" if result.type == "error" else "done"
                self._finish_stream(status=stream_status)
                self._active_accumulator = None
                self._active_turn_request_id = None
                return result

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
            f"{self._role}. Keep chat replies concise and useful. Prefer direct "
            "natural-language replies for peer chat. Do not call tools in peer chat "
            "turns unless this transport explicitly enables xmuse MCP."
        )

    def _developer_instructions(self) -> str:
        if self._enable_mcp:
            return (
                "For xmuse peer_chat_nudge turns, use xmuse MCP as the production "
                "writeback path: call chat_post_message directly with "
                "conversation_id, participant_id, god_session_id, and "
                "reply_to_inbox_item_id=xmuse_context.inbox_item.id, using "
                "xmuse_context.inbox_item.payload.content as the request. "
                "chat_read_inbox is only for recovery or batch inspection; "
                "do not call it before simple replies. "
                "Natural-language @mentions inside chat_post_message are display-only "
                "and do not enqueue peer work. When you need another GOD to take "
                "over or review, first reply to the current inbox item with "
                "chat_post_message, then call chat_mention with target_address "
                "set to that GOD's exact @role and content containing the concrete "
                "handoff request. "
                "When peer discussion produces work that should enter real "
                "execution, use the structured chat tools: create or reference a "
                "collaboration run, have execute record a JSON "
                "execute_feasibility_verdict via chat_record_collaboration_response "
                "using the approval-gate shape "
                '{"type":"execute_feasibility_verdict","status":"executable",'
                '"summary":"<why dispatch is safe>","evidence_refs":["<ref>"]}; '
                "looser fields such as verdict=feasible do not satisfy dispatch. "
                "then emit a lane_graph proposal with chat_emit_proposal and a "
                "collaboration:<run_id> reference, passing "
                "reply_to_inbox_item_id=xmuse_context.inbox_item.id so the proposal "
                "closes the current inbox item. Human approval remains required before "
                "dispatch. "
                "Only return a direct final assistant message if MCP tools are not "
                "available."
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
