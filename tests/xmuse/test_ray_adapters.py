from __future__ import annotations

import asyncio
import importlib
import importlib.abc
import importlib.util
import json
import shutil
import sys
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

import pytest
import uvicorn

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime


class _BlockRayImports(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: object = None, target: object = None) -> object:
        del path, target
        if fullname == "ray" or fullname.startswith("ray."):
            raise ModuleNotFoundError("blocked optional ray import")
        return None


def test_ray_is_declared_as_xmuse_optional_dependency() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    dependencies = pyproject["project"]["dependencies"]
    optional = pyproject["project"]["optional-dependencies"]

    assert not any(item.startswith("ray[default]") for item in dependencies)
    assert any(item.startswith("ray[default]") for item in optional["ray"])
    assert any(item.startswith("ray[default]") for item in optional["xmuse"])


def test_native_god_session_layer_import_does_not_require_ray() -> None:
    for module_name in list(sys.modules):
        if module_name == "ray" or module_name.startswith("ray."):
            sys.modules.pop(module_name, None)
    sys.modules.pop("xmuse_core.agents.god_session_layer", None)

    blocker = _BlockRayImports()
    sys.meta_path.insert(0, blocker)
    try:
        module = importlib.import_module("xmuse_core.agents.god_session_layer")
    finally:
        sys.meta_path.remove(blocker)

    assert module.GodSessionLayer.__name__ == "GodSessionLayer"
    assert "ray" not in sys.modules


def test_ray_runtime_backend_import_does_not_require_ray() -> None:
    for module_name in list(sys.modules):
        if module_name == "ray" or module_name.startswith("ray."):
            sys.modules.pop(module_name, None)
    sys.modules.pop("xmuse_core.agents.ray_runtime_backend", None)

    blocker = _BlockRayImports()
    sys.meta_path.insert(0, blocker)
    try:
        module = importlib.import_module("xmuse_core.agents.ray_runtime_backend")
    finally:
        sys.meta_path.remove(blocker)

    assert module.RayRuntimeAdapter.__name__ == "RayRuntimeAdapter"
    assert "ray" not in sys.modules


def test_ray_actor_module_is_import_gated_to_optional_ray_dependency() -> None:
    ray_spec = importlib.util.find_spec("ray")
    actor_spec = importlib.util.find_spec("xmuse_core.agents.ray_god_actor")

    assert actor_spec is not None
    if ray_spec is None:
        return

    module = importlib.import_module("xmuse_core.agents.ray_god_actor")

    assert hasattr(module.RayGodActor, "remote")


@pytest.mark.asyncio
async def test_codex_app_server_exposes_xmuse_mcp_chat_tools(tmp_path: Path) -> None:
    if shutil.which("codex") is None:
        pytest.skip("codex CLI is not installed")

    from xmuse.mcp_server import create_app

    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(tmp_path / "xmuse"),
            host="127.0.0.1",
            port=port,
            log_level="error",
        )
    )
    server_task = asyncio.create_task(server.serve())
    proc: asyncio.subprocess.Process | None = None
    try:
        await _wait_for_http_health(port)
        from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport

        command = CodexAppServerTransport(
            god_id="god-mcp-exposure",
            role="architect",
            display_name="Architect GOD",
            model="gpt-5.5",
            worktree=Path.cwd(),
            mcp_port=port,
            enable_mcp=True,
        )._command()
        proc = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=Path.cwd(),
            limit=1024 * 1024,
        )
        await _app_server_request(
            proc,
            1,
            "initialize",
            {
                "clientInfo": {"name": "xmuse-test", "version": "0"},
                "capabilities": {"experimentalApi": True},
            },
        )
        started = await _app_server_request(
            proc,
            2,
            "thread/start",
            {
                "cwd": str(Path.cwd()),
                "model": None,
                "approvalPolicy": "never",
                "sandbox": "danger-full-access",
                "ephemeral": True,
            },
        )
        thread_id = started["result"]["thread"]["id"]
        status = await _app_server_request(
            proc,
            3,
            "mcpServerStatus/list",
            {"threadId": thread_id, "detail": "toolsAndAuthOnly"},
        )
    finally:
        if proc is not None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except TimeoutError:
                proc.kill()
                await proc.wait()
        server.should_exit = True
        await server_task

    servers = {server["name"]: server for server in status["result"]["data"]}
    xmuse_server = servers["xmuse-platform"]
    assert xmuse_server["serverInfo"]["name"] == "xmuse-mcp"
    assert set(xmuse_server["tools"]) == {
        "chat_create_collaboration_request",
        "chat_emit_proposal",
        "chat_evaluate_dispatch_gate",
        "chat_inspect_conversation",
        "chat_mention",
        "chat_read_inbox",
        "chat_record_collaboration_response",
        "chat_resolve_collaboration_blocker",
        "chat_raise_collaboration_blocker",
        "chat_post_message",
    }
    post_schema = xmuse_server["tools"]["chat_post_message"]["inputSchema"]
    assert "reply_to_inbox_item_id" in post_schema["required"]
    mention_schema = xmuse_server["tools"]["chat_mention"]["inputSchema"]
    assert "target_address" in mention_schema["required"]


def _free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _wait_for_http_health(port: int) -> None:
    for _ in range(50):
        try:
            if await asyncio.to_thread(_http_health_status, port) == 200:
                return
        except Exception:
            pass
        await asyncio.sleep(0.1)
    raise RuntimeError("xmuse MCP server did not start")


def _http_health_status(port: int) -> int:
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=0.2) as resp:
        return int(resp.status)


async def _app_server_request(
    proc: asyncio.subprocess.Process,
    request_id: int,
    method: str,
    params: dict[str, object],
) -> dict[str, object]:
    if proc.stdin is None:
        raise RuntimeError("codex app-server stdin is unavailable")
    proc.stdin.write(
        (json.dumps({"id": request_id, "method": method, "params": params}) + "\n").encode()
    )
    await proc.stdin.drain()
    return await _read_app_server_response(proc, request_id)


async def _read_app_server_response(
    proc: asyncio.subprocess.Process,
    request_id: int,
) -> dict[str, object]:
    if proc.stdout is None:
        raise RuntimeError("codex app-server stdout is unavailable")
    while True:
        line = await asyncio.wait_for(proc.stdout.readline(), timeout=15)
        if not line:
            stderr = ""
            if proc.stderr is not None:
                stderr = (await proc.stderr.read()).decode(errors="replace")
            raise RuntimeError(f"codex app-server closed before response: {stderr}")
        try:
            message = json.loads(line.decode())
        except json.JSONDecodeError:
            continue
        if isinstance(message, dict) and message.get("id") == request_id:
            if "error" in message:
                raise RuntimeError(f"codex app-server {request_id} failed: {message['error']}")
            return message


@pytest.mark.asyncio
async def test_ray_god_actor_core_starts_and_stops_child_process(tmp_path: Path) -> None:
    from xmuse_core.agents.ray_god_actor import _RayGodActorCore

    actor = _RayGodActorCore(
        god_id="god-ray-core",
        role="planner",
        display_name="Planner GOD",
        model="gpt-5.5",
        command=[sys.executable, "-c", "import time; time.sleep(60)"],
        db_path=str(tmp_path / "chat.db"),
        worktree=str(tmp_path),
    )

    assert await actor.ensure_alive() is True
    assert actor.get_info()["alive"] is True

    await actor.shutdown()

    assert actor.get_info()["alive"] is False


@pytest.mark.asyncio
async def test_ray_runtime_backend_contract_preserves_durable_refs_not_memory_state() -> None:
    from xmuse_core.agents.ray_runtime_backend import FakeRayRuntimeBackend

    backend = FakeRayRuntimeBackend()
    request: dict[str, Any] = {
        "session_id": "god-session-ray-1",
        "role": "review",
        "conversation_id": "conv-ray-adapter",
        "participant_id": "review-god",
        "event_refs": ["planning_events.sqlite3#pevt-ray-runtime"],
        "artifact_refs": ["feature_plans/conv-ray-adapter/plan.v1.json"],
    }

    result = await backend.shadow_dispatch(request)

    assert result["backend"] == "fake-ray"
    assert result["session_id"] == request["session_id"]
    assert result["event_refs"] == request["event_refs"]
    assert result["artifact_refs"] == request["artifact_refs"]
    assert backend.memory_state == {}


@pytest.mark.asyncio
async def test_ray_runtime_adapter_can_be_disabled_without_dispatching_backend() -> None:
    from xmuse_core.agents.ray_runtime_backend import FakeRayRuntimeBackend, RayRuntimeAdapter

    backend = FakeRayRuntimeBackend()
    adapter = RayRuntimeAdapter(enabled=False, backend=backend)

    result = await adapter.shadow_dispatch(
        {
            "session_id": "god-session-disabled",
            "event_refs": ["planning_events.sqlite3#pevt-disabled"],
            "artifact_refs": ["feature_plans/conv-disabled/plan.v1.json"],
        }
    )

    assert result == {
        "backend": "ray-disabled",
        "status": "skipped",
        "session_id": "god-session-disabled",
        "event_refs": ["planning_events.sqlite3#pevt-disabled"],
        "artifact_refs": ["feature_plans/conv-disabled/plan.v1.json"],
    }
    assert backend.dispatch_requests == []


class _FakeRayActor:
    def __init__(self) -> None:
        self.info = {"alive": False}
        self.sent: list[tuple[str, dict[str, object]]] = []
        self.received: list[object] = []
        self.shutdown_called = False
        self.ensure_alive_calls = 0

    async def ensure_alive(self) -> bool:
        self.ensure_alive_calls += 1
        self.info["alive"] = True
        return True

    async def get_info(self) -> dict:
        return self.info

    async def send_typed(self, msg_type: str, **payload: object) -> None:
        self.sent.append((msg_type, payload))

    async def receive(self):
        if self.received:
            return self.received.pop(0)
        return None

    async def shutdown(self) -> None:
        self.shutdown_called = True
        self.info["alive"] = False


@pytest.mark.asyncio
async def test_ray_god_session_layer_uses_actor_for_peer_chat(tmp_path: Path) -> None:
    from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

    actors: list[_FakeRayActor] = []

    def actor_factory(**kwargs):
        actor = _FakeRayActor()
        actors.append(actor)
        return actor

    class Launcher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["fake-cli", role, str(worktree)]

        def build_env(self, role: str):
            return None

    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: Launcher()},
        actor_factory=actor_factory,
    )
    agent = AgentDescriptor(
        name="Architect GOD",
        runtime=AgentRuntime.CODEX,
        capabilities=["architect"],
    )

    record = await layer.ensure_conversation_session(
        conversation_id="conv-1",
        participant_id="part-1",
        role="architect",
        agent=agent,
        worktree=tmp_path,
        model="gpt-5.4",
        prompt_fingerprint="sha256:test",
        feature_scope_id=None,
    )
    await layer.send_message(
        record.god_session_id,
        "peer_chat_nudge",
        prompt="Read inbox",
        context="{}",
        request_id="inbox-1",
    )

    assert isinstance(record, GodSessionRecord)
    assert len(actors) == 1
    assert actors[0].info["alive"] is True
    assert actors[0].sent == [
        (
            "peer_chat_nudge",
            {
                "god_session_id": record.god_session_id,
                "prompt": "Read inbox",
                "context": "{}",
                "request_id": "inbox-1",
            },
        )
    ]

    await layer.abort_session(record.god_session_id)

    assert actors[0].shutdown_called is True


@pytest.mark.asyncio
async def test_ray_god_session_layer_uses_process_transport_for_opencode(
    tmp_path: Path,
) -> None:
    from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

    captured: list[dict[str, object]] = []

    def actor_factory(**kwargs):
        captured.append(kwargs)
        return _FakeRayActor()

    class Launcher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["fake-opencode", "run", role, str(worktree)]

        def build_env(self, role: str):
            return None

    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.OPENCODE: Launcher()},
        actor_factory=actor_factory,
        transport_mode="app-server",
    )
    agent = AgentDescriptor(
        name="Review OpenCode",
        runtime=AgentRuntime.OPENCODE,
        capabilities=["review"],
    )

    await layer.ensure_conversation_session(
        conversation_id="conv-1",
        participant_id="part-review",
        role="review",
        agent=agent,
        worktree=tmp_path,
        model="opencode-go/deepseek-v4-flash",
    )

    assert captured[0]["transport_mode"] == "process"
    assert captured[0]["command"] == [
        "fake-opencode",
        "run",
        "review",
        str(tmp_path),
    ]
    assert captured[0]["model"] == "opencode-go/deepseek-v4-flash"


@pytest.mark.asyncio
async def test_ray_god_actor_core_speaks_session_protocol(tmp_path: Path) -> None:
    from xmuse_core.agents.protocol import parse_stdout_line
    from xmuse_core.agents.ray_god_actor import _RayGodActorCore

    script = (
        "import json,sys\n"
        "for line in sys.stdin:\n"
        "    msg=json.loads(line)\n"
        "    print(json.dumps({'type':'result','status':'success',"
        "'request_id':msg.get('request_id'),'message':msg.get('prompt','')}), flush=True)\n"
    )
    actor = _RayGodActorCore(
        god_id="god-ray-core",
        role="architect",
        display_name="Architect GOD",
        model="gpt-5.4",
        command=[sys.executable, "-c", script],
        db_path=str(tmp_path / "chat.db"),
        worktree=str(tmp_path),
    )

    await actor.ensure_alive()
    await actor.send_typed(
        "peer_chat_nudge",
        god_session_id="god-ray-core",
        prompt="hello",
        context="{}",
        request_id="req-1",
    )
    msg = await actor.receive()

    assert msg == parse_stdout_line(
        '{"type":"result","status":"success","request_id":"req-1","message":"hello"}'
    )
    await actor.shutdown()


@pytest.mark.asyncio
async def test_ray_god_actor_core_can_use_injected_transport_without_child_process(
    tmp_path: Path,
) -> None:
    from xmuse_core.agents.protocol import StdoutMessage
    from xmuse_core.agents.ray_god_actor import _RayGodActorCore

    class FakeTransport:
        def __init__(self) -> None:
            self.started = False
            self.sent: list[tuple[str, dict[str, object]]] = []
            self.closed = False

        async def start(self) -> None:
            self.started = True

        async def send_typed(self, msg_type: str, **payload: object) -> None:
            self.sent.append((msg_type, payload))

        async def receive(self):
            return StdoutMessage(
                type="result",
                status="success",
                request_id="req-transport",
                message="transport reply",
            )

        async def shutdown(self) -> None:
            self.closed = True
            self.started = False

        def get_info(self) -> dict[str, object]:
            return {
                "alive": self.started,
                "pid": None,
                "transport": "codex-app-server",
                "thread_id": "thread-real-1",
                "resume_thread_id": None,
            }

    transports: list[FakeTransport] = []

    def transport_factory(**kwargs):
        del kwargs
        transport = FakeTransport()
        transports.append(transport)
        return transport

    actor = _RayGodActorCore(
        god_id="god-ray-core",
        role="architect",
        display_name="Architect GOD",
        model="gpt-5.4",
        command=["should-not-run"],
        db_path=str(tmp_path / "chat.db"),
        worktree=str(tmp_path),
        transport_factory=transport_factory,
    )

    assert await actor.ensure_alive() is True
    await actor.send_typed(
        "peer_chat_nudge",
        god_session_id="god-ray-core",
        prompt="hello",
        context="{}",
        request_id="req-transport",
    )
    msg = await actor.receive()

    info = actor.get_info()
    assert info["transport"] == "codex-app-server"
    assert info["thread_id"] == "thread-real-1"
    assert info["resume_thread_id"] is None
    assert msg.message == "transport reply"
    assert transports[0].sent == [
        (
            "peer_chat_nudge",
            {
                "god_session_id": "god-ray-core",
                "prompt": "hello",
                "context": "{}",
                "request_id": "req-transport",
            },
        )
    ]

    await actor.shutdown()

    assert transports[0].closed is True


@pytest.mark.asyncio
async def test_ray_god_actor_core_passes_resume_thread_id_to_transport_factory(
    tmp_path: Path,
) -> None:
    from xmuse_core.agents.ray_god_actor import _RayGodActorCore

    captured: dict[str, object] = {}

    class FakeTransport:
        async def start(self) -> None:
            return None

        async def send_typed(self, msg_type: str, **payload: object) -> None:
            del msg_type, payload

        async def receive(self):
            return None

        async def shutdown(self) -> None:
            return None

        def get_info(self) -> dict[str, object]:
            return {
                "alive": True,
                "pid": None,
                "transport": "codex-app-server",
                "thread_id": "thread-existing",
                "resume_thread_id": "thread-existing",
            }

    def transport_factory(**kwargs):
        captured.update(kwargs)
        return FakeTransport()

    actor = _RayGodActorCore(
        god_id="god-ray-core",
        role="architect",
        display_name="Architect GOD",
        model="gpt-5.4",
        command=["should-not-run"],
        db_path=str(tmp_path / "chat.db"),
        worktree=str(tmp_path),
        transport_factory=transport_factory,
        resume_thread_id="thread-existing",
    )

    assert await actor.ensure_alive() is True
    assert captured["resume_thread_id"] == "thread-existing"
    assert actor.get_info()["resume_thread_id"] == "thread-existing"


def test_app_server_turn_accumulator_emits_result_from_agent_message_delta() -> None:
    from xmuse_core.agents.codex_app_server_transport import AppServerTurnAccumulator

    accumulator = AppServerTurnAccumulator(request_id="inbox-1")

    assert accumulator.feed(
        {
            "method": "turn/started",
            "params": {"turn": {"id": "turn-1"}, "threadId": "thread-1"},
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": "你好",
            },
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": "，Architect 在线。",
            },
        }
    ) is None

    result = accumulator.feed(
        {
            "method": "turn/completed",
            "params": {"threadId": "thread-1", "turn": {"id": "turn-1"}},
        }
    )

    assert result is not None
    assert result.type == "result"
    assert result.status == "success"
    assert result.request_id == "inbox-1"
    assert result.message == "你好，Architect 在线。"


def test_app_server_turn_accumulator_emits_latency_stages_from_mcp_events() -> None:
    from xmuse_core.agents.codex_app_server_transport import AppServerTurnAccumulator

    clock_values = iter([200.0, 200.2, 200.5, 201.0, 201.5, 202.0])
    accumulator = AppServerTurnAccumulator(
        request_id="inbox-1",
        clock=lambda: next(clock_values),
    )

    assert accumulator.feed(
        {
            "method": "mcpServer/startupStatus/updated",
            "params": {"serverName": "xmuse-platform", "status": "ready"},
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "turn/started",
            "params": {"turn": {"id": "turn-1"}, "threadId": "thread-1"},
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/started",
            "params": {
                "turnId": "turn-1",
                "item": {"type": "mcpToolCall", "toolName": "chat_read_inbox"},
            },
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/started",
            "params": {
                "turnId": "turn-1",
                "item": {"type": "mcpToolCall", "toolName": "chat_post_message"},
            },
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/started",
            "params": {
                "turnId": "turn-1",
                "item": {"type": "mcpToolCall", "toolName": "chat_mention"},
            },
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/started",
            "params": {
                "turnId": "turn-1",
                "item": {
                    "type": "mcpToolCall",
                    "toolName": "chat_record_collaboration_response",
                },
            },
        }
    ) is None

    result = accumulator.feed(
        {
            "method": "turn/completed",
            "params": {"threadId": "thread-1", "turn": {"id": "turn-1"}},
        }
    )

    assert result is not None
    assert result.artifacts["latency_stages"] == {
        "mcp_tools_ready": {"at": 200.0},
        "codex_app_server_turn_start": {"at": 200.2},
        "chat_read_inbox": {"at": 200.5},
        "chat_post_message": {"at": 201.0},
        "chat_mention": {"at": 201.5},
        "chat_record_collaboration_response": {"at": 202.0},
    }


def test_app_server_turn_accumulator_records_first_stream_delta_stage() -> None:
    from xmuse_core.agents.codex_app_server_transport import AppServerTurnAccumulator

    clock_values = iter([300.0, 300.2, 999.0])
    accumulator = AppServerTurnAccumulator(
        request_id="inbox-1",
        clock=lambda: next(clock_values),
    )

    assert accumulator.feed(
        {
            "method": "turn/started",
            "params": {"turn": {"id": "turn-1"}, "threadId": "thread-1"},
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": "first",
            },
        }
    ) is None
    assert accumulator.feed(
        {
            "method": "item/agentMessage/delta",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "itemId": "msg-1",
                "delta": " second",
            },
        }
    ) is None

    result = accumulator.feed(
        {
            "method": "turn/completed",
            "params": {"threadId": "thread-1", "turn": {"id": "turn-1"}},
        }
    )

    assert result is not None
    assert result.message == "first second"
    assert result.artifacts["latency_stages"]["first_stream_delta"] == {"at": 300.2}


def test_app_server_turn_accumulator_emits_error_notification() -> None:
    from xmuse_core.agents.codex_app_server_transport import AppServerTurnAccumulator

    accumulator = AppServerTurnAccumulator(request_id="review-1")

    assert accumulator.feed(
        {
            "method": "turn/started",
            "params": {"turn": {"id": "turn-1"}, "threadId": "thread-1"},
        }
    ) is None

    result = accumulator.feed(
        {
            "method": "error",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "error": {
                    "message": "model is not supported for this account",
                },
                "willRetry": False,
            },
        }
    )

    assert result is not None
    assert result.type == "error"
    assert result.request_id == "review-1"
    assert result.runtime == "codex-app-server"
    assert result.code == "codex_app_server_error"
    assert result.message == "model is not supported for this account"


def test_app_server_turn_accumulator_failed_turn_is_not_success_result() -> None:
    from xmuse_core.agents.codex_app_server_transport import AppServerTurnAccumulator

    accumulator = AppServerTurnAccumulator(request_id="review-1")

    assert accumulator.feed(
        {
            "method": "turn/started",
            "params": {"turn": {"id": "turn-1"}, "threadId": "thread-1"},
        }
    ) is None

    result = accumulator.feed(
        {
            "method": "turn/completed",
            "params": {
                "threadId": "thread-1",
                "turn": {
                    "id": "turn-1",
                    "status": "failed",
                    "error": {"message": "provider rejected model"},
                },
            },
        }
    )

    assert result is not None
    assert result.type == "error"
    assert result.request_id == "review-1"
    assert result.code == "codex_app_server_error"
    assert result.message == "provider rejected model"


def test_app_server_transport_omits_xmuse_mcp_by_default(tmp_path: Path) -> None:
    from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport

    transport = CodexAppServerTransport(
        god_id="god-chat",
        role="architect",
        display_name="Architect GOD",
        model="gpt-5.4",
        worktree=tmp_path,
    )

    command = transport._command()

    assert "app-server" in command
    assert not any("xmuse-platform" in item for item in command)


@pytest.mark.asyncio
async def test_app_server_transport_uses_large_stream_limit_for_tool_schema_lines(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from xmuse_core.agents.codex_app_server_transport import (
        APP_SERVER_STREAM_LIMIT_BYTES,
        CodexAppServerTransport,
    )

    captured: dict[str, object] = {}

    async def fake_create_subprocess_exec(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return type(
            "Process",
            (),
            {
                "returncode": None,
                "stdin": object(),
                "stdout": object(),
                "stderr": object(),
            },
        )()

    class CaptureTransport(CodexAppServerTransport):
        async def _request(self, method: str, params: dict[str, object]) -> object:
            if method == "thread/start":
                return {"thread": {"id": "thread-1"}}
            return {}

    monkeypatch.setattr(
        "xmuse_core.agents.codex_app_server_transport.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )
    transport = CaptureTransport(
        god_id="god-chat",
        role="execute",
        display_name="Execute GOD",
        model="gpt-5.4",
        worktree=tmp_path,
        enable_mcp=True,
    )

    await transport.start()

    assert captured["kwargs"]["limit"] == APP_SERVER_STREAM_LIMIT_BYTES
    assert APP_SERVER_STREAM_LIMIT_BYTES >= 16 * 1024 * 1024


def test_app_server_mcp_instructions_prefer_direct_post(tmp_path: Path) -> None:
    from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport

    transport = CodexAppServerTransport(
        god_id="god-chat",
        role="architect",
        display_name="Architect GOD",
        model="gpt-5.4",
        worktree=tmp_path,
        enable_mcp=True,
    )

    instructions = transport._developer_instructions()

    assert "call chat_post_message directly" in instructions
    assert "reply_to_inbox_item_id=xmuse_context.inbox_item.id" in instructions
    assert "chat_read_inbox is only for recovery or batch inspection" in instructions
    assert "Natural-language @mentions inside chat_post_message are display-only" in instructions
    assert "call chat_mention with" in instructions
    assert "closes your current inbox item" in instructions
    assert "chat_emit_proposal" in instructions
    assert "collaboration:<run_id>" in instructions
    assert "do not return the JSON as final assistant text or streamed stdout" in (
        instructions
    )
    assert "do not also call chat_mention for the same target" in instructions
    assert "If mcp_tools_ready has appeared, MCP tools are available" in instructions
    assert "do not say you cannot perform durable writeback" in instructions
    assert "Human approval remains required before dispatch" in instructions
    assert "call chat_read_inbox" not in instructions


def test_app_server_transport_starts_non_ephemeral_thread_for_restart_resume(
    tmp_path: Path,
) -> None:
    from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport

    transport = CodexAppServerTransport(
        god_id="god-chat",
        role="architect",
        display_name="Architect GOD",
        model="gpt-5.4",
        worktree=tmp_path,
    )

    params = transport._thread_start_params()

    assert params["ephemeral"] is False


@pytest.mark.asyncio
async def test_app_server_transport_starts_peer_chat_turn_with_low_effort(
    tmp_path: Path,
) -> None:
    from xmuse_core.agents.codex_app_server_transport import CodexAppServerTransport

    class CaptureTransport(CodexAppServerTransport):
        def __init__(self) -> None:
            super().__init__(
                god_id="god-chat",
                role="architect",
                display_name="Architect GOD",
                model="gpt-5.4",
                worktree=tmp_path,
            )
            self._thread_id = "thread-1"
            self.sent: list[tuple[str, dict[str, object]]] = []

        async def start(self) -> None:
            return None

        async def _send_request(self, method: str, params: dict[str, object]) -> int:
            self.sent.append((method, params))
            return 1

    transport = CaptureTransport()

    await transport.send_typed(
        "peer_chat_nudge",
        prompt="Reply only ok.",
        context="{}",
        request_id="inbox-1",
    )

    method, params = transport.sent[0]
    assert method == "turn/start"
    assert params["effort"] == "low"


@pytest.mark.asyncio
async def test_ray_god_session_layer_prewarms_actor_runtime(tmp_path: Path) -> None:
    from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

    actors: list[_FakeRayActor] = []

    def actor_factory(**kwargs):
        actor = _FakeRayActor()
        actors.append(actor)
        return actor

    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={},
        actor_factory=actor_factory,
    )

    await layer.prewarm()

    assert len(actors) == 1
    assert actors[0].ensure_alive_calls == 1
    assert actors[0].shutdown_called is True


@pytest.mark.asyncio
async def test_ray_god_session_layer_shutdown_closes_all_live_actors(tmp_path: Path) -> None:
    from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

    actors: list[_FakeRayActor] = []

    def actor_factory(**kwargs):
        actor = _FakeRayActor()
        actors.append(actor)
        return actor

    class Launcher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["fake-cli", role, str(worktree)]

        def build_env(self, role: str):
            return None

    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: Launcher()},
        actor_factory=actor_factory,
    )
    agent = AgentDescriptor(
        name="Architect GOD",
        runtime=AgentRuntime.CODEX,
        capabilities=["architect"],
    )
    await layer.ensure_conversation_session(
        conversation_id="conv-1",
        participant_id="part-1",
        role="architect",
        agent=agent,
        worktree=tmp_path,
    )
    await layer.ensure_conversation_session(
        conversation_id="conv-1",
        participant_id="part-2",
        role="review",
        agent=agent,
        worktree=tmp_path,
    )

    await layer.shutdown()

    assert [actor.shutdown_called for actor in actors] == [True, True]
