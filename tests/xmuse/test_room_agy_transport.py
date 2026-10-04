"""End-to-end agy CLI Room transport tests against a scripted CLI.

No real provider and no external network: the CLI is
``tests/xmuse/fixtures/fake_agy.py`` (stdlib only, speaking the
``--input-format stream-json --output-format stream-json`` protocol), and the
Room MCP endpoint is the real ``xmuse.room_mcp_server`` app served by uvicorn
on an ephemeral loopback port.  The scripted CLI commits Room truth only
through ``chat_room_submit_outcome`` over HTTP, exactly like a real CLI agent.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse.room_mcp_server import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_agent_stream import (
    RoomAgentStreamCache,
    RoomAgentStreamProjector,
    build_room_agent_stream_projection,
)
from xmuse_core.chat.room_agy_transport import (
    ROOM_AGY_PROVIDER_SESSION_KIND,
    AgyRoomObservationTransport,
    AgyTransportConfig,
    _pump_agy_stdout,
    agy_turn_error_code,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
    RoomTurnProgress,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_observation_transport_base import tool_call_fingerprint
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore

FAKE_AGY = Path(__file__).resolve().parent / "fixtures" / "fake_agy.py"
INJECTED_SECRETS = (
    "XMUSE_OPERATOR_TOKEN",
    "XMUSE_MEMORYOS_API_KEY",
    "MEMORYOS_API_KEY",
    "ANTHROPIC_API_KEY",
)


@contextlib.contextmanager
def _serve_room_mcp(xmuse_root: Path) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(xmuse_root),
            host="127.0.0.1",
            port=0,
            log_level="warning",
            access_log=False,
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("room mcp server did not start")
        time.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}/mcp/room"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _agent_environment(tmp_path: Path, mode: str, *, mcp_url: str, content: str) -> dict[str, str]:
    return {
        **os.environ,
        # The verification suite runs pytest with PYTHONWARNINGS=error; the CLI
        # subprocess is a separate program and must not inherit that strictness.
        "PYTHONWARNINGS": "default",
        "XMUSE_TEST_AGY_LOG": str(tmp_path / "agy-agent.jsonl"),
        "XMUSE_TEST_AGY_ARGV_LOG": str(tmp_path / "agy-argv.jsonl"),
        "XMUSE_TEST_AGY_MODE": mode,
        "XMUSE_TEST_AGY_MCP_URL": mcp_url,
        "XMUSE_TEST_AGY_CONTENT": content,
        "XMUSE_OPERATOR_TOKEN": "operator-secret",
        "XMUSE_MEMORYOS_API_KEY": "memoryos-secret",
        "MEMORYOS_API_KEY": "memoryos-legacy-secret",
        "ANTHROPIC_API_KEY": "sk-ant-test-secret",
    }


def _command_builder() -> Callable[[str | None], tuple[str, ...]]:
    def _build(resume_conversation_id: str | None) -> tuple[str, ...]:
        argv: list[str] = [
            sys.executable,
            str(FAKE_AGY),
            "--input-format",
            "stream-json",
            "--output-format",
            "stream-json",
            "--model",
            "gemini-3.8-flash-high",
            "--dangerously-skip-permissions",
        ]
        if resume_conversation_id:
            argv.extend(["--conversation", resume_conversation_id])
        argv.append("-p=")
        return tuple(argv)

    return _build


def _agy_transport(
    tmp_path: Path,
    mcp_url: str,
    *,
    mode: str,
    content: str = "agy durable answer",
    controls: RoomObservationControlStore,
    decisions: RoomAttemptSkillDecisionStore,
    projector: RoomAgentStreamProjector | None = None,
    owner: bool = False,
) -> AgyRoomObservationTransport:
    return AgyRoomObservationTransport(
        config=AgyTransportConfig(
            workspace=tmp_path,
            command_builder=_command_builder(),
            default_model="gemini-3.8-flash-high",
            confinement="os_read_only_sandbox",
            owner=owner,
        ),
        registry_path=tmp_path / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
        environ=_agent_environment(tmp_path, mode, mcp_url=mcp_url, content=content),
    )


def _agy_only_room(db: Path) -> tuple[str, Participant, RoomKernelStore]:
    conversation_id = RoomTestStore(db).create_conversation("agy room").id
    antigravity = ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="review",
        display_name="Antigravity Reviewer",
        cli_kind="antigravity",
        model="gemini-3.8-flash-high",
    )
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Answer with one short sentence.",
        client_request_id="human-1",
    )
    return conversation_id, antigravity, kernel


def _host(
    db: Path,
    transport: Any,
    *,
    controls: RoomObservationControlStore,
    decisions: RoomAttemptSkillDecisionStore,
    delivery_timeout_s: float = 60.0,
    cleanup_grace_s: float = 5.0,
) -> RoomParticipantHost:
    return RoomParticipantHost(
        db,
        transport,
        policy=RoomHostPolicy(
            participant_cooldown_s=0,
            delivery_timeout_s=delivery_timeout_s,
            cleanup_grace_s=cleanup_grace_s,
            lease_ttl_s=delivery_timeout_s + cleanup_grace_s + 60.0,
        ),
        control_store=controls,
        skill_decision_store=decisions,
    )


def _read_events(log_path: Path) -> list[dict[str, Any]]:
    if not log_path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            events.append(json.loads(line))
    return events


def _event(events: list[dict[str, Any]], name: str) -> dict[str, Any] | None:
    return next((event for event in events if event.get("event") == name), None)


def _argv_entries(tmp_path: Path) -> list[dict[str, Any]]:
    path = tmp_path / "agy-argv.jsonl"
    if not path.exists():
        return []
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def test_agy_config_rejects_invalid_settings(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="room_agy_command_builder_invalid"):
        AgyTransportConfig(
            workspace=tmp_path,
            command_builder="not-callable",  # type: ignore[arg-type]
            default_model="gemini-3.8-flash-high",
            confinement="os_read_only_sandbox",
        )
    with pytest.raises(ValueError, match="room_agy_default_model_invalid"):
        AgyTransportConfig(
            workspace=tmp_path,
            command_builder=_command_builder(),
            default_model="  ",
            confinement="os_read_only_sandbox",
        )
    with pytest.raises(ValueError, match="room_agy_turn_idle_timeout_s_invalid"):
        AgyTransportConfig(
            workspace=tmp_path,
            command_builder=_command_builder(),
            default_model="gemini-3.8-flash-high",
            confinement="os_read_only_sandbox",
            turn_idle_timeout_s=0,
        )


def test_agy_outcome_lands_durably_with_identity_and_preview(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_durable_scenario(tmp_path, mcp_url))


async def _durable_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, antigravity, _kernel = _agy_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(tmp_path))
    transport = _agy_transport(
        tmp_path,
        mcp_url,
        mode="normal",
        controls=controls,
        decisions=decisions,
        projector=projector,
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
        record = GodSessionRegistry(
            tmp_path / "god_sessions.json"
        ).find_by_conversation_participant(
            conversation_id,
            antigravity.participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
    finally:
        await transport.aclose()
        await projector.shutdown()

    states = {item.participant_id: item for item in result.deliveries}
    assert states[antigravity.participant_id].state == "completed"

    messages = RoomTestStore(db).list_messages(conversation_id)
    agy_messages = [message for message in messages if message.author == antigravity.participant_id]
    assert [message.content for message in agy_messages] == ["agy durable answer"]

    assert record.runtime == "antigravity"
    assert record.provider_session_kind == ROOM_AGY_PROVIDER_SESSION_KIND
    assert record.provider_session_id is not None
    assert record.provider_binding_status == "active"
    closed = GodSessionRegistry(tmp_path / "god_sessions.json").find_by_conversation_participant(
        conversation_id,
        antigravity.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert closed.provider_session_id == record.provider_session_id
    assert closed.provider_binding_status == "closed"
    assert closed.provider_binding_failure_reason == "room_agy_shutdown"

    projection = build_room_agent_stream_projection(tmp_path, conversation_id)
    streams = [
        item
        for item in projection["streams"]
        if item["participant_id"] == antigravity.participant_id
    ]
    assert len(streams) == 1
    assert streams[0]["state"] == "resolved"
    assert "agy draft answer" in streams[0]["content"]

    events = _read_events(tmp_path / "agy-agent.jsonl")
    startup = _event(events, "startup")
    assert startup is not None
    assert startup["conversation_id"] == record.provider_session_id
    assert startup["resumed"] is False
    assert startup["last_arg"] == "-p="
    assert not set(startup["secret_env_names"]) & set(INJECTED_SECRETS)
    assert startup["has_operator_token"] is False
    assert startup["has_memoryos_api_key"] is False
    assert startup["has_anthropic_api_key"] is False
    assert startup["cwd"] == str(tmp_path.resolve())
    prompt = _event(events, "prompt_received")
    assert prompt is not None and prompt["has_context"] is True
    assert prompt["participant_id"] == antigravity.participant_id
    submission = _event(events, "outcome_submission")
    assert submission is not None
    assert "error" not in submission["result"]
    assert submission["result"]["produced_message"]["content"] == "agy durable answer"
    assert _event(events, "result_sent") is not None


def test_second_delivery_reuses_the_same_process_and_conversation(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_reuse_scenario(tmp_path, mcp_url))


async def _reuse_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, antigravity, kernel = _agy_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _agy_transport(
        tmp_path, mcp_url, mode="normal", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        first = await host.pump_once(conversation_id=conversation_id)
        assert first.deliveries[0].state == "completed"
        kernel.post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content="Answer a second question.",
            client_request_id="human-2",
        )
        second = await host.pump_once(conversation_id=conversation_id)
        assert second.deliveries[0].state == "completed"
        record = GodSessionRegistry(
            tmp_path / "god_sessions.json"
        ).find_by_conversation_participant(
            conversation_id,
            antigravity.participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
    finally:
        await transport.aclose()

    events = _read_events(tmp_path / "agy-agent.jsonl")
    assert len([event for event in events if event["event"] == "startup"]) == 1
    assert len([event for event in events if event["event"] == "prompt_received"]) == 2
    assert len([event for event in events if event["event"] == "outcome_submission"]) == 2
    for event in events:
        if event["event"] == "prompt_received":
            assert event["conversation_id"] == record.provider_session_id
    messages = RoomTestStore(db).list_messages(conversation_id)
    contents = [
        message.content for message in messages if message.author == antigravity.participant_id
    ]
    assert contents == ["agy durable answer", "agy follow-up answer"]


def test_forgetful_turn_gets_one_in_lease_reminder(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_forgetful_scenario(tmp_path, mcp_url))


async def _forgetful_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, antigravity, _kernel = _agy_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _agy_transport(
        tmp_path,
        mcp_url,
        mode="forgetful",
        controls=controls,
        decisions=decisions,
        content="verified in a reminder",
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    states = {item.participant_id: item for item in result.deliveries}
    assert states[antigravity.participant_id].state == "completed"
    events = _read_events(tmp_path / "agy-agent.jsonl")
    prompts = [event for event in events if event["event"] == "prompt_received"]
    assert len(prompts) == 2
    assert prompts[0]["has_context"] is True
    # The single in-lease reminder carries no Room context; the stored one is used.
    assert prompts[1]["has_context"] is False
    submission = _event(events, "outcome_submission")
    assert submission is not None and submission["http_status"] == 200
    assert submission["result"]["produced_message"]["content"] == "agy follow-up answer"


def test_silent_turn_sends_one_reminder_then_rotates_and_drops_the_id(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_silent_scenario(tmp_path, mcp_url))


async def _silent_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, antigravity, kernel = _agy_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _agy_transport(
        tmp_path, mcp_url, mode="silent", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(
        item for item in result.deliveries if item.participant_id == antigravity.participant_id
    )
    assert state.state == "incomplete"
    assert state.reason == "durable_outcome_missing"
    assert state.retryable is True

    events = _read_events(tmp_path / "agy-agent.jsonl")
    prompts = [event for event in events if event["event"] == "prompt_received"]
    # Exactly one reminder turn follows the silent observation turn.
    assert len(prompts) == 2
    assert _event(events, "outcome_submission") is None
    assert any(event["event"] in {"agent_exit", "sigterm_received"} for event in events)

    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    record = registry.find_by_conversation_participant(
        conversation_id,
        antigravity.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert record.provider_binding_status == "closed"
    assert record.provider_binding_failure_reason == "room_agy_durable_outcome_missing"
    # The stored conversation id is dropped: the next process starts fresh.
    assert record.provider_session_id is None

    observation = next(
        item
        for item in kernel.list_observations(conversation_id)
        if item["participant_id"] == antigravity.participant_id
    )
    assert observation["status"] == "pending"

    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Try again with a fresh conversation.",
        client_request_id="human-2",
    )
    argv_before = len(_argv_entries(tmp_path))
    transport2 = _agy_transport(
        tmp_path, mcp_url, mode="normal", controls=controls, decisions=decisions
    )
    host2 = _host(db, transport2, controls=controls, decisions=decisions)
    try:
        await host2.pump_once(conversation_id=conversation_id)
    finally:
        await transport2.aclose()
    fresh_spawns = _argv_entries(tmp_path)[argv_before:]
    assert fresh_spawns, "the retried delivery must spawn a new process"
    assert all("--conversation" not in entry["argv"] for entry in fresh_spawns)


@pytest.mark.parametrize(
    "mode,code", [("error", "room_agy_turn_failed"), ("exit", "room_agy_process_exited")]
)
def test_failed_turns_report_stable_codes_with_cleanup_proven(
    tmp_path: Path, mode: str, code: str
) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_failure_scenario(tmp_path, mcp_url, mode, code))


async def _failure_scenario(tmp_path: Path, mcp_url: str, mode: str, code: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, antigravity, kernel = _agy_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _agy_transport(tmp_path, mcp_url, mode=mode, controls=controls, decisions=decisions)
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(
        item for item in result.deliveries if item.participant_id == antigravity.participant_id
    )
    assert state.state == "failed"
    assert state.reason == code
    assert state.retryable is True

    events = _read_events(tmp_path / "agy-agent.jsonl")
    assert _event(events, "outcome_submission") is None
    observation_id = kernel.list_observations(conversation_id)[0]["observation_id"]
    binding = controls.reconcile_state(observation_id).get("reconcile_binding") or {}
    # The dead/failed generation is provably gone, so the host may reopen at once.
    assert binding.get("provider_phase") == "cleanup_succeeded"
    assert binding.get("provider_cleanup_reason") == code


def test_resume_passes_the_stored_conversation_after_a_restart(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_resume_scenario(tmp_path, mcp_url))


async def _resume_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, antigravity, kernel = _agy_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    first = _agy_transport(tmp_path, mcp_url, mode="normal", controls=controls, decisions=decisions)
    host = _host(db, first, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
        assert result.deliveries[0].state == "completed"
    finally:
        await first.aclose()
    stored = (
        GodSessionRegistry(tmp_path / "god_sessions.json")
        .find_by_conversation_participant(
            conversation_id,
            antigravity.participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
        .provider_session_id
    )
    assert stored

    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Continue in the same conversation.",
        client_request_id="human-2",
    )
    argv_before = len(_argv_entries(tmp_path))
    resumed = _agy_transport(
        tmp_path, mcp_url, mode="normal", controls=controls, decisions=decisions
    )
    host2 = _host(db, resumed, controls=controls, decisions=decisions)
    try:
        result2 = await host2.pump_once(conversation_id=conversation_id)
        assert result2.deliveries[0].state == "completed"
    finally:
        await resumed.aclose()

    spawns = _argv_entries(tmp_path)[argv_before:]
    assert len(spawns) == 1
    argv = spawns[0]["argv"]
    assert "--conversation" in argv
    assert argv[argv.index("--conversation") + 1] == stored
    assert argv[-1] == "-p="
    events = _read_events(tmp_path / "agy-agent.jsonl")
    startups = [event for event in events if event["event"] == "startup"]
    assert startups[-1]["resumed"] is True
    assert startups[-1]["conversation_id"] == stored


def _unit_delivery(
    tmp_path: Path, progress: Callable[[RoomTurnProgress], None]
) -> RoomObservationDelivery:
    db = tmp_path / "unit.db"
    conversation_id = RoomTestStore(db).create_conversation("unit").id
    participant = ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="review",
        display_name="Reviewer",
        cli_kind="antigravity",
        model="gemini-3.8-flash-high",
    )
    return RoomObservationDelivery(
        conversation_id=conversation_id,
        participant=participant,
        observation={"observation_id": "obs-1"},
        source_activity={"activity_id": "act-1"},
        recent_activities=(),
        active_participants=(),
        transport_request_id="req-1",
        outcome_client_request_id="out-1",
        progress=progress,
    )


def _unit_transport(tmp_path: Path) -> AgyRoomObservationTransport:
    return AgyRoomObservationTransport(
        config=AgyTransportConfig(
            workspace=tmp_path,
            command_builder=_command_builder(),
            default_model="gemini-3.8-flash-high",
            confinement="os_read_only_sandbox",
        ),
        registry_path=tmp_path / "god_sessions.json",
    )


def test_step_mapping_reports_text_tool_and_other_progress(tmp_path: Path) -> None:
    transport = _unit_transport(tmp_path)
    seen: list[RoomTurnProgress] = []
    delivery = _unit_delivery(tmp_path, seen.append)
    session = SimpleNamespace(preview_listeners=set())

    transport._handle_step_update(
        session,
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": "c",
                "step_index": 1,
                "state": "ACTIVE",
                "step_type": "agent_response",
                "text_delta": "hello",
            },
        },
        turn_id="turn-1",
        delivery=delivery,
    )
    transport._handle_step_update(
        session,
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": "c",
                "step_index": 2,
                "state": "ACTIVE",
                "step_type": "tool",
                "tool_name": "run_command",
                "tool_info": {"name": "run_command", "parameters": {"command": "ls"}},
            },
        },
        turn_id="turn-1",
        delivery=delivery,
    )
    transport._handle_step_update(
        session,
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": "c",
                "step_index": 2,
                "state": "DONE",
                "step_type": "tool",
                "tool_name": "run_command",
                "tool_info": {
                    "name": "run_command",
                    "parameters": {"command": "ls"},
                    "output": "api\n",
                },
            },
        },
        turn_id="turn-1",
        delivery=delivery,
    )
    transport._handle_step_update(
        session,
        {
            "event": "step_update",
            "step_update": {
                "conversation_id": "c",
                "step_index": 3,
                "state": "DONE",
                "step_type": "user_input",
            },
        },
        turn_id="turn-1",
        delivery=delivery,
    )

    assert [item.kind for item in seen] == ["message", "tool_update", "tool_call", "other"]
    assert seen[2].fingerprint == tool_call_fingerprint("run_command", {"command": "ls"})
    assert seen[2].fingerprint == tool_call_fingerprint("run_command", {"command": "ls"})
    assert seen[2].fingerprint != tool_call_fingerprint("run_command", {"command": "pwd"})


def test_outcome_mcp_call_marks_the_preview_committing(tmp_path: Path) -> None:
    transport = _unit_transport(tmp_path)
    delivery = _unit_delivery(tmp_path, lambda progress: None)
    session = SimpleNamespace(preview_listeners=set())
    from xmuse_core.chat.room_agy_transport import _AgyPreviewStream

    listener = _AgyPreviewStream(session)
    session.preview_listeners.add(listener)

    async def _scenario() -> list[dict[str, Any]]:
        params = {"server": "xmuse-room", "tool": "chat_room_submit_outcome"}
        transport._handle_step_update(
            session,
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "c",
                    "step_index": 4,
                    "state": "ACTIVE",
                    "step_type": "tool",
                    "tool_name": "call_mcp_tool",
                    "tool_info": {"name": "call_mcp_tool", "parameters": params},
                },
            },
            turn_id="turn-1",
            delivery=delivery,
        )
        transport._handle_step_update(
            session,
            {
                "event": "step_update",
                "step_update": {
                    "conversation_id": "c",
                    "step_index": 4,
                    "state": "DONE",
                    "step_type": "tool",
                    "tool_name": "call_mcp_tool",
                    "tool_info": {"name": "call_mcp_tool", "parameters": params, "output": "ok"},
                },
            },
            turn_id="turn-1",
            delivery=delivery,
        )
        return [await listener.receive(), await listener.receive()]

    events = asyncio.run(_scenario())
    assert [(event["method"], event["params"]["item"]["name"]) for event in events] == [
        ("item/started", "chat_room_submit_outcome"),
        ("item/completed", "chat_room_submit_outcome"),
    ]


def test_failed_tool_step_counts_as_finished_tool_call(tmp_path: Path) -> None:
    transport = _unit_transport(tmp_path)
    seen: list[RoomTurnProgress] = []
    delivery = _unit_delivery(tmp_path, seen.append)
    session = SimpleNamespace(preview_listeners=set())
    for _ in range(2):
        transport._handle_step_update(
            session,
            {
                "event": "step_update",
                "step_update": {
                    "state": "ERROR",
                    "step_type": "tool",
                    "tool_name": "run_command",
                    "tool_info": {"name": "run_command", "parameters": {"CommandLine": "x"}},
                },
            },
            turn_id="turn-1",
            delivery=delivery,
        )

    # Repeating a failing command must feed the host's loop detector.
    assert [item.kind for item in seen] == ["tool_call", "tool_call"]
    assert seen[0].fingerprint == seen[1].fingerprint


def test_stdout_pump_skips_oversized_line_instead_of_reporting_exit() -> None:
    async def _scenario() -> list[dict[str, Any] | None]:
        stream = asyncio.StreamReader(limit=1024)
        big = {"event": "step_update", "step_update": {"tool_info": {"content": "x" * 4096}}}
        stream.feed_data((json.dumps(big) + "\n").encode())
        stream.feed_data(b'{"event": "result", "result": {"status": "SUCCESS"}}\n')
        stream.feed_eof()
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
        await _pump_agy_stdout(stream, queue)
        return [queue.get_nowait() for _ in range(queue.qsize())]

    events = asyncio.run(_scenario())
    # The oversized step is dropped; the turn's result still arrives and the
    # EOF sentinel comes only at the real end of the stream.
    assert events == [{"event": "result", "result": {"status": "SUCCESS"}}, None]


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (
            "Individual quota reached. Please upgrade your subscription. Resets in 27m19s.",
            "room_agy_quota_exhausted",
        ),
        (
            'API error (attempt 1): request failed: Post "https://x/v1": read: connection reset',
            "room_agy_api_unreachable",
        ),
        ("fake agy turn failed", "room_agy_turn_failed"),
    ],
)
def test_turn_error_classification(error: str, code: str) -> None:
    assert agy_turn_error_code(error) == code
