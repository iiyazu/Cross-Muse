from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from xmuse_core.agents.codex_app_server_transport import (
    CODEX_ROOM_READ_ONLY_SANDBOX,
    AppServerTurnAccumulator,
    CodexAppServerTransport,
    CodexSandboxProfile,
)


def test_app_server_room_mcp_command_uses_only_room_capability(
    tmp_path: Path,
    monkeypatch,
) -> None:
    ambient_home = tmp_path / "ambient-codex"
    isolated_home = tmp_path / "isolated-codex"
    ambient_home.mkdir()
    (ambient_home / "config.toml").write_text(
        '[mcp_servers.node_repl]\ncommand = "node"\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(ambient_home))
    monkeypatch.setenv("CODEX_INTERNAL_ORIGINATOR_OVERRIDE", "Codex Desktop")
    monkeypatch.setenv("CODEX_PERMISSION_PROFILE", "desktop-inherited")
    monkeypatch.setenv("CODEX_SQLITE_HOME", str(tmp_path / "ambient-sqlite"))
    monkeypatch.setenv("CODEX_THREAD_ID", "ambient-thread")
    monkeypatch.setenv("XMUSE_OPERATOR_TOKEN", "must-not-reach-room-agent")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "must-not-reach-room-agent")
    monkeypatch.setenv("DATABASE_URL", "must-not-reach-room-agent")
    monkeypatch.setenv("GITHUB_TOKEN", "must-not-reach-room-agent")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-room-agent")
    monkeypatch.setenv("XMUSE_WORKROOM_GENERATION", "must-not-reach-room-agent")
    monkeypatch.setenv("XMUSE_MEMORYOS_URL", "http://127.0.0.1:8301")
    monkeypatch.setenv("XMUSE_MEMORYOS_API_KEY", "must-not-reach-room-agent")
    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        mcp_port=8123,
        mcp_path="/mcp/room",
        enable_mcp=True,
        codex_home=isolated_home,
    )

    command = transport._command()

    assert command == [
        "codex",
        "app-server",
        "-c",
        "mcp_servers={}",
        "-c",
        'mcp_servers.xmuse-room.type="streamable_http"',
        "-c",
        'mcp_servers.xmuse-room.url="http://localhost:8123/mcp/room"',
        "-c",
        'mcp_servers.xmuse-room.tools.chat_room_submit_outcome.approval_mode="approve"',
        "-c",
        'shell_environment_policy.inherit="core"',
        "-c",
        "shell_environment_policy.exclude="
        '["ALL_PROXY","CODEX_HOME","HTTPS_PROXY","HTTP_PROXY","NO_PROXY",'
        '"all_proxy","https_proxy","http_proxy","no_proxy"]',
        "--disable",
        "apps",
        "--disable",
        "plugins",
        "--disable",
        "remote_plugin",
        "--disable",
        "plugin_sharing",
        "--disable",
        "browser_use",
        "--disable",
        "browser_use_external",
        "--disable",
        "in_app_browser",
        "--disable",
        "computer_use",
        "--disable",
        "image_generation",
        "--disable",
        "multi_agent",
        "--disable",
        "code_mode_host",
        "--disable",
        "hooks",
        "--disable",
        "skill_mcp_dependency_install",
        "--disable",
        "workspace_dependencies",
        "--listen",
        "stdio://",
    ]
    assert not any("/mcp/chat" in item for item in command)
    assert not any("node_repl" in item for item in command)
    assert not any("default_tools_approval_mode" in item for item in command)
    assert "tool_search" not in command
    assert "tool_suggest" not in command
    assert not any(
        command[index : index + 2] == ["--disable", "goals"] for index in range(len(command) - 1)
    )
    process_environment = transport._process_environment()
    assert process_environment is not None
    assert process_environment["CODEX_HOME"] == str(isolated_home.resolve())
    assert {
        "AWS_SECRET_ACCESS_KEY",
        "DATABASE_URL",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "XMUSE_OPERATOR_TOKEN",
        "XMUSE_WORKROOM_GENERATION",
        "XMUSE_MEMORYOS_URL",
        "XMUSE_MEMORYOS_API_KEY",
    }.isdisjoint(process_environment)
    assert {
        name: value for name, value in process_environment.items() if name.startswith("CODEX_")
    } == {"CODEX_HOME": str(isolated_home.resolve())}


def test_app_server_start_passes_isolated_codex_home_to_subprocess(
    tmp_path: Path,
    monkeypatch,
) -> None:
    isolated_home = tmp_path / "room-codex-home"
    captured: dict[str, object] = {}

    class _Process:
        returncode = None

    async def create_subprocess_exec(*command, **kwargs):
        captured["command"] = command
        captured["kwargs"] = kwargs
        return _Process()

    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        mcp_path="/mcp/room",
        enable_mcp=True,
        codex_home=isolated_home,
    )

    async def request(method: str, _params: dict) -> dict:
        if method == "thread/start":
            return {"thread": {"id": "thread-room"}}
        return {}

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(transport, "_request", request)
    asyncio.run(transport.start())

    kwargs = captured["kwargs"]
    assert isinstance(kwargs, dict)
    environment = kwargs["env"]
    assert isinstance(environment, dict)
    assert environment["CODEX_HOME"] == str(isolated_home.resolve())


async def test_app_server_start_failure_terminates_spawned_process(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Process:
        returncode = None
        terminated = False

        def terminate(self) -> None:
            self.terminated = True
            self.returncode = 0

        async def wait(self) -> int:
            return int(self.returncode or 0)

    process = Process()

    async def create_subprocess_exec(*_command, **_kwargs):
        return process

    async def request(_method: str, _params: dict):
        raise RuntimeError("initialize failed")

    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(transport, "_request", request)

    with pytest.raises(RuntimeError, match="initialize failed"):
        await transport.start()

    assert process.terminated is True


@pytest.mark.parametrize(
    "resume_response",
    [
        {},
        {"thread": {}},
        {"thread": {"id": "thread-other"}},
    ],
)
async def test_app_server_resume_requires_exact_returned_thread_identity(
    tmp_path: Path,
    monkeypatch,
    resume_response: dict[str, object],
) -> None:
    class Process:
        returncode = None

        def terminate(self) -> None:
            self.returncode = 0

        async def wait(self) -> int:
            return int(self.returncode or 0)

    process = Process()

    async def create_subprocess_exec(*_command, **_kwargs):
        return process

    async def request(method: str, _params: dict):
        return resume_response if method == "thread/resume" else {}

    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        resume_thread_id="thread-existing",
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(transport, "_request", request)

    with pytest.raises(RuntimeError, match="thread/resume returned"):
        await transport.start()

    assert process.returncode == 0


async def test_app_server_resume_accepts_exact_returned_thread_identity(
    tmp_path: Path,
    monkeypatch,
) -> None:
    class Process:
        returncode = None
        pid = 5151

    async def create_subprocess_exec(*_command, **_kwargs):
        return Process()

    async def request(method: str, _params: dict):
        if method == "thread/resume":
            return {"thread": {"id": "thread-existing"}}
        return {}

    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        resume_thread_id="thread-existing",
    )
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_subprocess_exec)
    monkeypatch.setattr(transport, "_request", request)

    await transport.start()

    assert transport.get_info()["thread_id"] == "thread-existing"


@pytest.mark.parametrize(
    "mcp_path",
    [
        "",
        "/mcp",
        "/mcp/room/",
        "/mcp/room?tool=chat_post_message",
        "http://example.test/mcp/room",
        "/mcp/room\n-c sandbox=disabled",
        None,
    ],
)
def test_app_server_rejects_non_capability_mcp_paths(
    tmp_path: Path,
    mcp_path: object,
) -> None:
    with pytest.raises(ValueError, match="MCP path must be"):
        CodexAppServerTransport(
            god_id="god",
            role="review",
            display_name="Reviewer",
            model="gpt-5.4",
            worktree=tmp_path,
            mcp_path=mcp_path,  # type: ignore[arg-type]
            enable_mcp=True,
        )


def test_resume_does_not_override_native_model_or_effort(tmp_path: Path) -> None:
    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="bootstrap-only",
        worktree=tmp_path,
        resume_thread_id="thread-existing",
        reasoning_effort="max",
    )

    params = transport._thread_resume_params("thread-existing")
    assert "model" not in params and "effort" not in params


@pytest.mark.asyncio
async def test_same_thread_rebind_changes_opaque_session_guard(tmp_path: Path, monkeypatch) -> None:
    class Connection:
        generation = 1

        async def request(self, method: str, _params: dict[str, object]) -> object:
            if method == "thread/read":
                return {"thread": {"status": {"type": "idle"}}}
            assert method == "thread/goal/get"
            return {"goal": None}

    async def no_start() -> None: ...

    guards: list[str] = []
    for _ in range(2):
        transport = CodexAppServerTransport(
            god_id="god",
            role="review",
            display_name="Reviewer",
            model="gpt-5.4",
            worktree=tmp_path,
            resume_thread_id="thread-existing",
        )
        transport._thread_id = "thread-existing"
        transport._connection = Connection()  # type: ignore[assignment]
        monkeypatch.setattr(transport, "start", no_start)
        snapshot = await transport.native_snapshot()
        raw_guards = snapshot["guards"]
        assert isinstance(raw_guards, dict)
        session_guard = raw_guards["session"]
        assert isinstance(session_guard, str)
        guards.append(session_guard)

    assert guards[0] != guards[1]


@pytest.mark.asyncio
async def test_native_snapshot_reproves_active_turn_and_clears_stale_event_state(
    tmp_path: Path, monkeypatch
) -> None:
    class Connection:
        generation = 1
        active = True

        async def request(self, method: str, _params: dict[str, object]) -> object:
            if method == "thread/read":
                return {"thread": {"status": {"type": "active" if self.active else "idle"}}}
            if method == "thread/turns/list":
                return {
                    "data": [
                        {
                            "id": "native-review-turn",
                            "status": "inProgress",
                            "items": [],
                        }
                    ]
                }
            assert method == "thread/goal/get"
            return {"goal": None}

    async def no_start() -> None: ...

    connection = Connection()
    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        resume_thread_id="thread-existing",
    )
    transport._thread_id = "thread-existing"
    transport._connection = connection  # type: ignore[assignment]
    transport._native_active_turn_id = "stale-nested-turn"
    monkeypatch.setattr(transport, "start", no_start)

    active = await transport.native_snapshot()
    assert active["active_turn"] is True
    connection.active = False
    idle = await transport.native_snapshot()
    assert idle["active_turn"] is False
    assert transport._native_active_turn_id is None


@pytest.mark.parametrize("effort", ["unknown", "ultra", "", None])
def test_app_server_rejects_unknown_or_delegating_effort(tmp_path: Path, effort: object) -> None:
    with pytest.raises(ValueError, match="effort"):
        CodexAppServerTransport(
            god_id="god",
            role="review",
            display_name="Reviewer",
            model="gpt-5.4",
            worktree=tmp_path,
            reasoning_effort=effort,  # type: ignore[arg-type]
        )


def test_app_server_accumulator_records_summary_and_plan_latency_stages() -> None:
    now = 10.0

    def clock() -> float:
        return now

    accumulator = AppServerTurnAccumulator(request_id="req-1", clock=clock)

    assert (
        accumulator.feed(
            {
                "method": "turn/started",
                "params": {"turn": {"id": "turn-1"}},
            }
        )
        is None
    )

    now = 11.0
    assert (
        accumulator.feed(
            {
                "method": "item/reasoning/summaryPartAdded",
                "params": {"turnId": "turn-1", "itemId": "reason-1", "summaryIndex": 0},
            }
        )
        is None
    )

    now = 12.0
    assert (
        accumulator.feed(
            {
                "method": "item/reasoning/summaryTextDelta",
                "params": {
                    "turnId": "turn-1",
                    "itemId": "reason-1",
                    "summaryIndex": 0,
                    "delta": "Checking the request.",
                },
            }
        )
        is None
    )

    now = 13.0
    assert (
        accumulator.feed(
            {
                "method": "item/reasoning/textDelta",
                "params": {"turnId": "turn-1", "delta": "raw hidden reasoning"},
            }
        )
        is None
    )

    now = 14.0
    assert (
        accumulator.feed(
            {
                "method": "item/plan/delta",
                "params": {
                    "turnId": "turn-1",
                    "itemId": "plan-1",
                    "delta": "Plan visible progress.",
                },
            }
        )
        is None
    )

    now = 15.0
    assert (
        accumulator.feed(
            {
                "method": "turn/plan/updated",
                "params": {"turnId": "turn-1", "plan": []},
            }
        )
        is None
    )

    now = 16.0
    assert (
        accumulator.feed(
            {
                "method": "item/agentMessage/delta",
                "params": {"turnId": "turn-1", "delta": "Final visible answer."},
            }
        )
        is None
    )

    result = accumulator.feed(
        {
            "method": "turn/completed",
            "params": {"turnId": "turn-1", "turn": {"status": "completed"}},
        }
    )

    assert result is not None
    assert result.message == "Final visible answer."
    assert "raw hidden reasoning" not in result.message
    assert result.artifacts["latency_stages"] == {
        "codex_app_server_turn_start": {"at": 10.0},
        "reasoning_summary_started": {"at": 11.0},
        "first_reasoning_summary_delta": {"at": 12.0},
        "first_plan_delta": {"at": 14.0},
        "turn_plan_updated": {"at": 15.0},
        "first_stream_delta": {"at": 16.0},
    }


def test_app_server_turn_start_requests_concise_reasoning_summary(tmp_path: Path) -> None:
    transport = CodexAppServerTransport(
        god_id="god-architect",
        role="architect",
        display_name="Architect",
        model="gpt-5.4",
        worktree=tmp_path,
    )
    transport._thread_id = "thread-1"

    params = transport._turn_start_params("hello")

    assert params["threadId"] == "thread-1"
    assert params["summary"] == "concise"
    assert "model" not in params and "effort" not in params
    assert params["input"] == [{"type": "text", "text": "hello"}]
    assert params["approvalPolicy"] == "never"
    assert params["sandboxPolicy"] == {"type": "readOnly", "networkAccess": False}

    start = transport._thread_start_params()
    resume = transport._thread_resume_params("thread-existing")
    assert start["approvalPolicy"] == resume["approvalPolicy"] == "never"
    assert start["sandbox"] == resume["sandbox"] == "read-only"


def test_room_read_only_profile_matches_codex_app_server_schema(tmp_path: Path) -> None:
    transport = CodexAppServerTransport(
        god_id="god-review",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        enable_mcp=True,
        mcp_path="/mcp/room",
        sandbox_profile=CODEX_ROOM_READ_ONLY_SANDBOX,
    )
    transport._thread_id = "thread-room"

    start = transport._thread_start_params()
    resume = transport._thread_resume_params("thread-existing")
    turn = transport._turn_start_params("observe")

    assert start["approvalPolicy"] == resume["approvalPolicy"] == "never"
    assert start["sandbox"] == resume["sandbox"] == "read-only"
    assert turn["approvalPolicy"] == "never"
    assert turn["sandboxPolicy"] == {
        "type": "readOnly",
        "networkAccess": False,
    }


def test_codex_sandbox_profiles_are_immutable_and_closed() -> None:
    with pytest.raises(AttributeError):
        CODEX_ROOM_READ_ONLY_SANDBOX.network_access = True  # type: ignore[misc]
    with pytest.raises(ValueError, match="unsupported Codex"):
        CodexSandboxProfile(
            thread_sandbox="read-only",
            turn_policy_type="readOnly",
            network_access=True,
        )


async def test_room_observation_turn_is_diagnostic_without_legacy_side_effects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        enable_mcp=True,
    )
    transport._thread_id = "thread-1"
    calls, start_params = [], []
    context = {
        "conversation_id": "conv-1",
        "participant_id": "participant-1",
        "god_session_id": "god-1",
        "inbox_item": {
            "id": "inbox-1",
            "item_type": "review_trigger",
            "source_message_id": "msg-1",
            "payload": {
                "required_tool": "chat_emit_review_trigger_verdict",
                "content": "Use refs proposal:p1.",
            },
        },
    }

    async def started() -> None:
        return None

    async def send_request(method: str, params: dict) -> int:
        calls.append(method)
        start_params.append(params)
        return 7

    messages = iter(
        (
            {
                "method": "item/agentMessage/delta",
                "params": {"delta": "Review trigger verdict: dispatch_allowed."},
            },
            {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
        )
    )

    async def read_message():
        return next(messages, None)

    monkeypatch.setattr(transport, "start", started)
    monkeypatch.setattr(transport, "_send_request", send_request)
    monkeypatch.setattr(transport, "_read_message", read_message)
    await transport.send_typed(
        "room_observation",
        request_id="req-1",
        prompt="Review trigger verdict: dispatch_allowed.",
        context=json.dumps(context),
    )
    result = await transport.receive()
    assert result is not None and result.message == "Review trigger verdict: dispatch_allowed."
    assert calls == ["turn/start"] and transport._active_message_type is None
    prompt = start_params[0]["input"][0]["text"]
    for text in (
        "room_observation",
        "chat_room_submit_outcome",
        "conversation_id, participant_id, god_session_id, observation_id, "
        "lease_token, and client_request_id",
        "no structured tool result",
        "replay the exact full arguments with the same client_request_id",
        "structured validation error",
        "correct only the rejected non-authority argument",
        "never repeat an argument already proven invalid",
        "durable_outcome.reply_to_activity_ids",
        "immutable-authority error",
        "do not invent replacement authority data or loop",
        "Never call the outcome tool again after one successful durable commit",
        "diagnostic only and never room truth",
        "chat_post_message, chat_mention, chat_emit_proposal",
    ):
        assert text in prompt


def test_room_observation_turn_tracks_scoped_outcome_tool_as_diagnostic() -> None:
    accumulator = AppServerTurnAccumulator(request_id="req")
    for method in "item/started", "item/completed":
        assert (
            accumulator.feed(
                {"method": method, "params": {"item": {"name": "chat_room_submit_outcome"}}},
            )
            is None
        )
    assert (
        accumulator.feed(
            {"method": "item/agentMessage/delta", "params": {"delta": "diagnostic"}},
        )
        is None
    )
    result = accumulator.feed(
        {"method": "turn/completed", "params": {"turn": {"status": "completed"}}},
    )
    assert result is not None and result.message == "diagnostic"
    assert result.artifacts["stdout"] == "diagnostic"
    stages = result.artifacts["latency_stages"]
    assert {
        "mcp_tool_call_detected",
        "mcp_tool_call_started",
        "mcp_tool_call_completed",
        "chat_room_submit_outcome",
    } <= set(stages)
    assert "room_outcome" not in result.artifacts


def test_room_observation_instructions_allow_independent_choice_without_role_order(
    tmp_path: Path,
) -> None:
    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        enable_mcp=True,
    )
    transport._active_message_type = "room_observation"
    instructions = transport._developer_instructions()
    for text in (
        "respond, handoff, propose, defer, or noop",
        "independently",
        "no fixed role order",
        "chat_room_submit_outcome",
        "conversation_id, participant_id, god_session_id, observation_id, "
        "lease_token, and client_request_id",
        "no structured tool result",
        "replay the exact full arguments with the same client_request_id",
        "structured validation error",
        "correct only the rejected non-authority argument",
        "never repeat an argument already proven invalid",
        "durable_outcome.reply_to_activity_ids",
        "immutable-authority error",
        "do not invent replacement authority data or loop",
        "Never call the outcome tool again after one successful durable commit",
        "chat_post_message, chat_mention, chat_emit_proposal, collaboration, review, critic",
        "diagnostic only and never room truth",
    ):
        assert text in instructions


def test_room_capability_session_starts_with_room_instructions(tmp_path: Path) -> None:
    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
        enable_mcp=True,
        mcp_path="/mcp/room",
    )

    params = transport._thread_start_params()

    assert "persistent xmuse room participant" in params["baseInstructions"]
    assert "chat_room_submit_outcome commit is room truth" in params["baseInstructions"]
    assert "no fixed role order" in params["developerInstructions"]
    assert "diagnostic only and never room truth" in params["developerInstructions"]


async def test_active_turn_error_preserves_transport_request_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    transport = CodexAppServerTransport(
        god_id="god",
        role="review",
        display_name="Reviewer",
        model="gpt-5.4",
        worktree=tmp_path,
    )
    transport._thread_id, transport._active_request_id = "thread-1", "req-1"
    transport._active_message_type = "room_observation"
    transport._active_accumulator = AppServerTurnAccumulator(request_id="req-1")
    transport._active_turn_request_id = 7

    async def started() -> None:
        return None

    async def read_message():
        return {"id": 7, "error": {"message": "failed"}}

    monkeypatch.setattr(transport, "start", started)
    monkeypatch.setattr(transport, "_read_message", read_message)
    result = await transport.receive()
    assert result is not None and result.request_id == "req-1"
    assert transport._active_message_type is None and transport._active_accumulator is None
