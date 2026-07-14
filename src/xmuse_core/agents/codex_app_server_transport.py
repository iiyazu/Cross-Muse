from __future__ import annotations

import asyncio
import json
import os
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from xmuse_core.agents.codex_app_server_connection import (
    AppServerConnectionError,
    AppServerEventStream,
    CodexAppServerConnection,
)
from xmuse_core.agents.codex_native_adapter import (
    CodexNativeAdapter,
    NativeInvokeResult,
    NativeModelCatalog,
)
from xmuse_core.agents.protocol import StdoutMessage

APP_SERVER_STREAM_LIMIT_BYTES = 16 * 1024 * 1024
_APP_SERVER_WAIT_HEARTBEAT_INTERVAL_S = 5.0
_ROOM_DISABLED_CODEX_FEATURES = (
    "apps",
    "plugins",
    "remote_plugin",
    "plugin_sharing",
    "browser_use",
    "browser_use_external",
    "in_app_browser",
    "computer_use",
    "image_generation",
    "multi_agent",
    "code_mode_host",
    "hooks",
    "skill_mcp_dependency_install",
    "workspace_dependencies",
)
_ROOM_CODEX_PROCESS_ENV_NAMES = frozenset(
    {
        "ALL_PROXY",
        "CURL_CA_BUNDLE",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "LOGNAME",
        "NODE_EXTRA_CA_CERTS",
        "NO_COLOR",
        "NO_PROXY",
        "PATH",
        "REQUESTS_CA_BUNDLE",
        "SHELL",
        "SSL_CERT_DIR",
        "SSL_CERT_FILE",
        "TEMP",
        "TERM",
        "TMP",
        "TMPDIR",
        "TZ",
        "USER",
        "all_proxy",
        "https_proxy",
        "http_proxy",
        "no_proxy",
    }
)
_ROOM_CODEX_SHELL_ENV_EXCLUDES = (
    "ALL_PROXY",
    "CODEX_HOME",
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "all_proxy",
    "https_proxy",
    "http_proxy",
    "no_proxy",
)


@dataclass(frozen=True, slots=True)
class CodexSandboxProfile:
    """Immutable app-server sandbox parameters supported by Codex 0.144."""

    thread_sandbox: Literal["read-only"]
    turn_policy_type: Literal["readOnly"]
    network_access: bool | None = None

    def __post_init__(self) -> None:
        shape = (
            self.thread_sandbox,
            self.turn_policy_type,
            self.network_access,
        )
        if shape != ("read-only", "readOnly", False):
            raise ValueError("unsupported Codex app-server sandbox profile")

    def turn_sandbox_policy(self) -> dict[str, object]:
        policy: dict[str, object] = {"type": self.turn_policy_type}
        if self.network_access is not None:
            policy["networkAccess"] = self.network_access
        return policy


CODEX_ROOM_READ_ONLY_SANDBOX = CodexSandboxProfile(
    thread_sandbox="read-only",
    turn_policy_type="readOnly",
    network_access=False,
)


class _TransportNativeRpc:
    def __init__(self, transport: CodexAppServerTransport) -> None:
        self._transport = transport

    async def request(self, method: str, params: Mapping[str, object]) -> object:
        return await self._transport._request(method, dict(params))


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
        if method == "item/reasoning/summaryPartAdded" and self._matches_turn(params):
            self._record_stage("reasoning_summary_started")
            return None
        if method == "item/reasoning/summaryTextDelta" and self._matches_turn(params):
            delta = _clean_text(params.get("delta"))
            if delta is not None:
                self._record_stage("first_reasoning_summary_delta")
            return None
        if method == "item/plan/delta" and self._matches_turn(params):
            delta = _clean_text(params.get("delta"))
            if delta is not None:
                self._record_stage("first_plan_delta")
            return None
        if method == "turn/plan/updated" and self._matches_turn(params):
            self._record_stage("turn_plan_updated")
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
            if tool_name == "chat_room_submit_outcome":
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
    """Codex app-server JSON-RPC transport for GOD role sessions."""

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
        enable_mcp: bool = True,
        mcp_path: str = "/mcp/room",
        resume_thread_id: str | None = None,
        sandbox_profile: CodexSandboxProfile = CODEX_ROOM_READ_ONLY_SANDBOX,
        codex_home: Path | None = None,
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
        if enable_mcp is not True:
            raise ValueError("Room Codex transport requires Room MCP")
        self._enable_mcp = True
        self._mcp_path = _normalize_mcp_path(mcp_path)
        if not isinstance(sandbox_profile, CodexSandboxProfile):
            raise TypeError("sandbox_profile must be a CodexSandboxProfile")
        self._sandbox_profile = sandbox_profile
        self._codex_home = (
            codex_home.expanduser().resolve() if isinstance(codex_home, Path) else None
        )
        if codex_home is not None and self._codex_home is None:
            raise TypeError("codex_home must be a Path or None")
        self._process: asyncio.subprocess.Process | None = None
        self._connection: CodexAppServerConnection | None = None
        self._connection_generation = 0
        self._native_incarnation = secrets.token_hex(16)
        self._thread_id: str | None = None
        self._resume_thread_id = _clean_text(resume_thread_id)
        self._active_turn_request_id: int | None = None
        self._active_turn_response: asyncio.Future[object] | None = None
        self._active_event_stream: AppServerEventStream | None = None
        self._active_accumulator: AppServerTurnAccumulator | None = None
        self._active_request_id: str | None = None
        self._active_message_type: str | None = None
        self._native_model = self._model or None
        self._native_effort = self._reasoning_effort
        self._native_active_turn_id: str | None = None
        self._native_idle = asyncio.Event()
        self._native_idle.set()
        self._native_catalog: NativeModelCatalog | None = None
        self._native_state_stream: AppServerEventStream | None = None
        self._native_state_task: asyncio.Task[None] | None = None
        self._native_adapter = CodexNativeAdapter(_TransportNativeRpc(self))

    async def start(self) -> None:
        if self._process is not None and self._process.returncode is None:
            return
        process_kwargs: dict[str, Any] = {
            "stdin": asyncio.subprocess.PIPE,
            "stdout": asyncio.subprocess.PIPE,
            "stderr": asyncio.subprocess.PIPE,
            "cwd": self._worktree,
            "limit": APP_SERVER_STREAM_LIMIT_BYTES,
            "start_new_session": True,
        }
        process_environment = self._process_environment()
        if process_environment is not None:
            process_kwargs["env"] = process_environment
        self._process = await asyncio.create_subprocess_exec(
            *self._command(),
            **process_kwargs,
        )
        try:
            await self._request(
                "initialize",
                {
                    "clientInfo": {
                        "name": "xmuse-god-session",
                        "version": "0",
                        "title": "xmuse GOD session",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            if self._resume_thread_id is None:
                await self._start_thread()
                return
            try:
                response = await self._request(
                    "thread/resume",
                    self._thread_resume_params(self._resume_thread_id),
                )
            except AppServerConnectionError as exc:
                if exc.code != "codex_app_server_thread_not_found":
                    raise
                await self._start_thread()
                return
            thread = response.get("thread") if isinstance(response, dict) else None
            thread_id = _clean_text(thread.get("id")) if isinstance(thread, dict) else None
            if thread_id is None:
                raise RuntimeError("codex app-server thread/resume returned no thread id")
            if thread_id != self._resume_thread_id:
                raise RuntimeError("codex app-server thread/resume returned mismatched thread id")
            self._thread_id = thread_id
            self._record_thread_settings(response)
        except BaseException:
            try:
                await asyncio.shield(self.shutdown())
            except BaseException:
                pass
            raise

    async def _start_thread(self) -> None:
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
        self._record_thread_settings(response)

    async def send_typed(self, msg_type: str, **kwargs: object) -> None:
        await self.start()
        if self._thread_id is None:
            raise RuntimeError("codex app-server thread is not initialized")
        if self._active_accumulator is not None:
            raise RuntimeError("codex app-server transport already has an active turn")
        request_id = _clean_text(kwargs.get("request_id"))
        self._active_message_type = msg_type
        prompt = _format_turn_prompt(
            role=self._role,
            msg_type=msg_type,
            prompt=_clean_text(kwargs.get("prompt")) or "",
            context=_clean_text(kwargs.get("context")) or "",
        )
        if msg_type == "room_observation":
            prompt = f"{prompt}\n\n{self._developer_instructions()}"
        self._active_request_id = request_id
        self._active_accumulator = AppServerTurnAccumulator(
            request_id=request_id,
        )
        self._native_idle.clear()
        self._active_turn_request_id = await self._send_request(
            "turn/start",
            self._turn_start_params(prompt),
        )

    async def receive(self) -> StdoutMessage | None:
        await self.start()
        if self._active_accumulator is None:
            return None
        while True:
            message = await self._read_message_with_idle_heartbeat()
            if message is None:
                return None
            if self._is_active_turn_error(message):
                request_id = self._active_request_id
                self._clear_active_turn()
                return StdoutMessage(
                    type="error",
                    request_id=request_id,
                    runtime="codex-app-server",
                    code="codex_app_server_error",
                    message=str(message.get("error") or "codex app-server turn failed"),
                )
            result = self._active_accumulator.feed(message)
            if result is not None:
                self._clear_active_turn()
                return result

    async def _read_message_with_idle_heartbeat(self) -> dict[str, Any] | None:
        while True:
            try:
                return await asyncio.wait_for(
                    self._read_message(),
                    timeout=_APP_SERVER_WAIT_HEARTBEAT_INTERVAL_S,
                )
            except TimeoutError:
                continue

    def active_latency_stages(self) -> dict[str, dict[str, float]]:
        if self._active_accumulator is None:
            return {}
        return self._active_accumulator.latency_stages()

    async def shutdown(self) -> None:
        if self._connection is not None:
            connection, self._connection = self._connection, None
            self._close_active_event_stream()
            await connection.close()
            if self._native_state_task is not None:
                await asyncio.gather(self._native_state_task, return_exceptions=True)
                self._native_state_task = None
            if self._native_state_stream is not None:
                self._native_state_stream.close()
                self._native_state_stream = None
            return
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

    async def native_snapshot(self) -> dict[str, object]:
        await self.start()
        if self._thread_id is None:
            raise RuntimeError("codex app-server thread is not initialized")
        connection = self._ensure_connection()
        await self._refresh_native_active_turn(connection)
        return await self._native_adapter.snapshot(
            thread_id=self._thread_id,
            session_identity=f"{self._thread_id}\0{self._native_incarnation}",
            connection_generation=connection.generation,
            current_model=self._native_model,
            current_effort=self._native_effort,
            active_turn_id=self._native_active_turn_id,
        )

    async def _refresh_native_active_turn(self, connection: CodexAppServerConnection) -> None:
        """Re-prove the live turn from bounded App Server state.

        Notifications remain the low-latency path, but review and compaction may
        produce nested turn identifiers.  The thread status and a one-page turn
        query prevent an identifier mismatch from holding Room delivery forever.
        """

        assert self._thread_id is not None
        response = await connection.request(
            "thread/read", {"threadId": self._thread_id, "includeTurns": False}
        )
        thread = response.get("thread") if isinstance(response, dict) else None
        status = thread.get("status") if isinstance(thread, dict) else None
        status_type = status.get("type") if isinstance(status, dict) else None
        # App Server keeps a recoverable ``systemError`` marker after a failed
        # turn until the next turn starts.  It is an inactive thread state,
        # not evidence that the participant process or thread binding died.
        # Treating it as unavailable traps Room native reconciliation in a
        # loop that repeatedly reuses the still-live session without ever
        # allowing the next native action to clear the marker.
        if status_type in {"idle", "systemError"}:
            self._native_active_turn_id = None
            self._native_idle.set()
            return
        if status_type != "active":
            raise RuntimeError("codex native thread state unavailable")
        turns_response = await connection.request(
            "thread/turns/list",
            {
                "threadId": self._thread_id,
                "limit": 16,
                "sortDirection": "desc",
                "itemsView": "notLoaded",
            },
        )
        turns = turns_response.get("data") if isinstance(turns_response, dict) else None
        if not isinstance(turns, list):
            raise RuntimeError("codex native turn state unavailable")
        active_ids = [
            turn_id
            for raw in turns
            if isinstance(raw, dict)
            and raw.get("status") == "inProgress"
            and (turn_id := _clean_text(raw.get("id"))) is not None
        ]
        if len(active_ids) != 1:
            raise RuntimeError("codex native active turn unproven")
        self._native_active_turn_id = active_ids[0]
        self._native_idle.clear()

    async def assert_room_delivery_allowed(self) -> None:
        snapshot = await self.native_snapshot()
        goal = snapshot.get("goal")
        if snapshot.get("active_turn") is True or (
            isinstance(goal, dict) and goal.get("status") == "active"
        ):
            raise RuntimeError("codex_native_room_delivery_conflict")

    async def discover_native_capabilities(self) -> dict[str, object]:
        snapshot = await self.native_snapshot()
        if self._thread_id is None:
            raise RuntimeError("codex app-server thread is not initialized")
        guards = snapshot.get("guards")
        session_guard = guards.get("session") if isinstance(guards, dict) else None
        if not isinstance(session_guard, str):
            raise RuntimeError("codex native snapshot returned no session guard")
        descriptor, catalog = await self._native_adapter.discover_capabilities(
            thread_id=self._thread_id,
            session_guard=session_guard,
        )
        self._native_catalog = catalog
        return descriptor | {"models": list(catalog.models)}

    async def invoke_native(
        self,
        capability_id: str,
        safe_request: dict[str, object],
        *,
        resolved_review_target: dict[str, object] | None = None,
    ) -> NativeInvokeResult:
        await self.start()
        if self._thread_id is None:
            raise RuntimeError("codex app-server thread is not initialized")
        if self._native_catalog is None:
            self._native_catalog = await self._native_adapter.list_models()
        result = await self._native_adapter.invoke(
            capability_id,
            safe_request,
            thread_id=self._thread_id,
            active_turn_id=self._native_active_turn_id,
            current_model=self._native_model,
            current_effort=self._native_effort,
            catalog=self._native_catalog,
            resolved_review_target=resolved_review_target,
        )
        if result.private_active_turn_id is not None:
            self._native_active_turn_id = result.private_active_turn_id
            self._native_idle.clear()
        return result

    def subscribe_native_events(self) -> AppServerEventStream:
        return self._ensure_connection().subscribe()

    async def wait_native_idle(self) -> None:
        await self._native_idle.wait()

    def _command(self) -> list[str]:
        command = [
            self._codex_command,
            "app-server",
            "--listen",
            "stdio://",
        ]
        isolated_room = self._mcp_path == "/mcp/room" and self._codex_home is not None
        if isolated_room:
            command[2:2] = [
                "-c",
                'shell_environment_policy.inherit="core"',
                "-c",
                "shell_environment_policy.exclude="
                + json.dumps(_ROOM_CODEX_SHELL_ENV_EXCLUDES, separators=(",", ":")),
            ] + [
                item for feature in _ROOM_DISABLED_CODEX_FEATURES for item in ("--disable", feature)
            ]
        if self._enable_mcp:
            mcp_configuration = [
                "-c",
                'mcp_servers.xmuse-room.type="streamable_http"',
                "-c",
                f'mcp_servers.xmuse-room.url="http://localhost:{self._mcp_port}{self._mcp_path}"',
            ]
            if isolated_room:
                mcp_configuration[0:0] = ["-c", "mcp_servers={}"]
                mcp_configuration.extend(
                    [
                        "-c",
                        "mcp_servers.xmuse-room.tools."
                        'chat_room_submit_outcome.approval_mode="approve"',
                    ]
                )
            command[2:2] = mcp_configuration
        return command

    def _process_environment(self) -> dict[str, str] | None:
        """Return an allowlisted environment for a config-isolated Room Codex home."""

        if self._codex_home is None:
            return None
        environment = {
            name: value
            for name, value in os.environ.items()
            if name in _ROOM_CODEX_PROCESS_ENV_NAMES or name.startswith("LC_")
        }
        environment["CODEX_HOME"] = str(self._codex_home)
        return environment

    def _thread_start_params(self) -> dict[str, Any]:
        return {
            "cwd": str(self._worktree),
            "model": self._model or None,
            "approvalPolicy": "never",
            "sandbox": self._sandbox_profile.thread_sandbox,
            "ephemeral": False,
            "baseInstructions": self._base_instructions(),
            "developerInstructions": self._developer_instructions(),
        }

    def _thread_resume_params(self, thread_id: str) -> dict[str, Any]:
        return {
            "threadId": thread_id,
            "cwd": str(self._worktree),
            "approvalPolicy": "never",
            "sandbox": self._sandbox_profile.thread_sandbox,
            "baseInstructions": self._base_instructions(),
            "developerInstructions": self._developer_instructions(),
        }

    def _turn_start_params(self, prompt: str) -> dict[str, Any]:
        return {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": prompt}],
            "cwd": str(self._worktree),
            "approvalPolicy": "never",
            "sandboxPolicy": self._sandbox_profile.turn_sandbox_policy(),
        }

    async def _request(self, method: str, params: dict[str, Any]) -> Any:
        try:
            return await self._ensure_connection().request(method, params)
        except AppServerConnectionError as exc:
            if exc.code == "codex_app_server_thread_not_found":
                raise
            raise RuntimeError(f"codex app-server {method} failed: {exc.code}") from exc

    async def _send_request(self, method: str, params: dict[str, Any]) -> int:
        connection = self._ensure_connection()
        self._close_active_event_stream()
        self._active_event_stream = connection.subscribe()
        request = await connection.start_request(method, params)
        self._active_turn_response = request.response
        return request.request_id

    async def _read_message(self) -> dict[str, Any] | None:
        if self._active_event_stream is None:
            return None
        while True:
            response = self._active_turn_response
            event_task = asyncio.create_task(self._active_event_stream.receive())
            waiters: set[asyncio.Future[object] | asyncio.Task[dict[str, object]]] = {event_task}
            if response is not None:
                waiters.add(response)
            try:
                done, _pending = await asyncio.wait(waiters, return_when=asyncio.FIRST_COMPLETED)
                if response is not None and response in done:
                    self._active_turn_response = None
                    try:
                        result = response.result()
                    except AppServerConnectionError as exc:
                        event_task.cancel()
                        await asyncio.gather(event_task, return_exceptions=True)
                        return {
                            "id": self._active_turn_request_id,
                            "error": {"code": exc.code},
                        }
                    self._bind_active_turn_from_response(result)
                    if event_task.done():
                        return dict(event_task.result())
                    event_task.cancel()
                    await asyncio.gather(event_task, return_exceptions=True)
                    continue
                return dict(event_task.result())
            except AppServerConnectionError as exc:
                return {
                    "id": self._active_turn_request_id,
                    "error": {"code": exc.code},
                }
            except asyncio.CancelledError:
                event_task.cancel()
                await asyncio.gather(event_task, return_exceptions=True)
                raise

    def _ensure_connection(self) -> CodexAppServerConnection:
        if self._connection is not None:
            return self._connection
        if self._process is None:
            raise RuntimeError("codex app-server process is not started")
        self._connection_generation += 1
        self._connection = CodexAppServerConnection(
            self._process,
            generation=self._connection_generation,
        )
        self._native_state_stream = self._connection.subscribe()
        self._native_state_task = asyncio.create_task(
            self._observe_native_state(self._native_state_stream),
            name="codex-app-server-native-state",
        )
        return self._connection

    def _bind_active_turn_from_response(self, result: object) -> None:
        if self._active_accumulator is None or not isinstance(result, dict):
            return
        turn = result.get("turn")
        if isinstance(turn, dict):
            turn_id = _clean_text(turn.get("id"))
            self._active_accumulator.turn_id = turn_id or self._active_accumulator.turn_id
            self._native_active_turn_id = turn_id or self._native_active_turn_id

    async def _observe_native_state(self, stream: AppServerEventStream) -> None:
        try:
            while True:
                self._apply_native_event(await stream.receive())
        except (AppServerConnectionError, asyncio.CancelledError):
            return

    def _apply_native_event(self, message: dict[str, object]) -> None:
        method = message.get("method")
        params = message.get("params")
        if not isinstance(method, str) or not isinstance(params, dict):
            return
        if method == "thread/settings/updated":
            settings = params.get("threadSettings")
            if isinstance(settings, dict):
                self._native_model = _clean_text(settings.get("model")) or self._native_model
                self._native_effort = _clean_text(settings.get("effort")) or self._native_effort
            return
        if method == "turn/started":
            turn = params.get("turn")
            turn_id = _clean_text(turn.get("id")) if isinstance(turn, dict) else None
            self._native_active_turn_id = turn_id or self._native_active_turn_id
            self._native_idle.clear()
            return
        if method == "turn/completed":
            turn = params.get("turn")
            turn_id = _clean_text(turn.get("id")) if isinstance(turn, dict) else None
            turn_id = turn_id or _clean_text(params.get("turnId"))
            if turn_id is None or turn_id == self._native_active_turn_id:
                self._native_active_turn_id = None
                self._native_idle.set()

    def _record_thread_settings(self, response: object) -> None:
        if not isinstance(response, dict):
            return
        self._native_model = _clean_text(response.get("model")) or self._native_model
        self._native_effort = _clean_text(response.get("reasoningEffort")) or self._native_effort

    def _close_active_event_stream(self) -> None:
        if self._active_event_stream is not None:
            self._active_event_stream.close()
            self._active_event_stream = None
        response, self._active_turn_response = self._active_turn_response, None
        if response is not None:
            if response.done():
                _consume_future_result(response)
            else:
                response.add_done_callback(_consume_future_result)

    def _clear_active_turn(self) -> None:
        self._close_active_event_stream()
        self._active_accumulator = None
        self._active_turn_request_id = None
        self._active_request_id = None
        self._active_message_type = None
        self._native_active_turn_id = None
        self._native_idle.set()

    def _is_active_turn_error(self, message: dict[str, Any]) -> bool:
        return bool(
            self._active_turn_request_id is not None
            and message.get("id") == self._active_turn_request_id
            and "error" in message
        )

    def _base_instructions(self) -> str:
        return (
            f"You are {self._display_name}, a persistent xmuse room participant "
            f"with role {self._role}. Observe shared room events and decide "
            "independently whether and how to act. Infrastructure controls "
            "delivery and identity; never claim another participant's identity. "
            "Only a chat_room_submit_outcome commit is room truth. Final assistant "
            "text is diagnostic only."
        )

    def _developer_instructions(self) -> str:
        return (
            "For room_observation, independently choose exactly one outcome: "
            "respond, handoff, propose, defer, or noop; there is no fixed role "
            "order, role precedence, or waiting for another role. Use only "
            "chat_room_submit_outcome for the durable room outcome. Copy "
            "conversation_id, participant_id, god_session_id, observation_id, "
            "lease_token, and client_request_id from xmuse_context. If a timeout, "
            "disconnect, or unknown completion provides no structured tool result, "
            "replay the exact full arguments with the same client_request_id. If the "
            "tool returns a structured validation error, keep the identity, observation, "
            "lease, batch, selected outcome_type, and client_request_id unchanged, but "
            "correct only the rejected non-authority argument from xmuse_context; never "
            "repeat an argument already proven invalid. For an invalid optional "
            "reply_to_activity_id, use one exact durable_outcome.reply_to_activity_ids "
            "value or omit the field. On lease loss, already completed, actor forbidden, "
            "idempotency conflict, or another immutable-authority error, do not invent "
            "replacement authority data or loop; stop with diagnostic final text. Never "
            "call the outcome tool again after one successful durable commit. Do not call "
            "chat_post_message, chat_mention, chat_emit_proposal, collaboration, "
            "review, critic, or any other retired write. Final assistant text "
            "is diagnostic only and never room truth."
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


def _consume_future_result(future: asyncio.Future[object]) -> None:
    if future.cancelled():
        return
    try:
        future.exception()
    except (asyncio.CancelledError, AppServerConnectionError):
        pass


def _clean_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _normalize_mcp_path(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("codex app-server MCP path must be /mcp/room")
    path = value.strip()
    if path != "/mcp/room":
        raise ValueError("codex app-server MCP path must be /mcp/room")
    return path


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


def _is_xmuse_mcp_ready(params: dict[str, Any]) -> bool:
    server_name = (
        _clean_text(params.get("serverName"))
        or _clean_text(params.get("server_name"))
        or _clean_text(params.get("name"))
    )
    server = params.get("server")
    if server_name is None and isinstance(server, dict):
        server_name = _clean_text(server.get("name"))
    if server_name is not None and server_name != "xmuse-room":
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
    text = _clean_text(value)
    if text is None:
        raise ValueError("codex app-server effort is required")
    normalized = text.lower()
    if normalized in {"none", "minimal", "low", "medium", "high", "xhigh", "max"}:
        return normalized
    raise ValueError("codex app-server effort is unsupported")


__all__ = [
    "AppServerTurnAccumulator",
    "CODEX_ROOM_READ_ONLY_SANDBOX",
    "CodexAppServerTransport",
    "CodexSandboxProfile",
]
