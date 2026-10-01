"""End-to-end Antigravity Room transport tests against a scripted agentapi CLI.

No real provider, no Antigravity language server, and no external network: the
"agentapi" is ``tests/xmuse/fixtures/fake_agentapi.py`` (stdlib only), which
materializes its transcript under a temp brain directory and commits Room truth
only through ``chat_room_submit_outcome`` over HTTP to the real
``xmuse.room_mcp_server`` app served by uvicorn on an ephemeral loopback port.
Language-server discovery is exercised with injected proc trees and probes.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from pathlib import Path
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
from xmuse_core.chat.room_antigravity_transport import (
    ROOM_ANTIGRAVITY_PROVIDER_SESSION_KIND,
    AntigravityRoomObservationTransport,
    AntigravityTransportConfig,
    RoomAntigravityTransportError,
    _parse_new_conversation_id,
    _read_agentapi_stdout,
    discover_antigravity_language_server_env,
    read_antigravity_transcript_steps,
)
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomParticipantHost,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.chat.room_transport_router import RoutingRoomObservationTransport

FAKE_AGENTAPI = Path(__file__).resolve().parent / "fixtures" / "fake_agentapi.py"
INJECTED_SECRETS = (
    "XMUSE_OPERATOR_TOKEN",
    "XMUSE_MEMORYOS_API_KEY",
    "MEMORYOS_API_KEY",
    "ANTHROPIC_API_KEY",
)
STATIC_LS_ENV = {
    "ANTIGRAVITY_LS_ADDRESS": "localhost:1",
    "ANTIGRAVITY_CSRF_TOKEN": "fake-ls-token",
    "ANTIGRAVITY_PROJECT_ID": "outside-of-project",
}


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


def _agentapi_environment(
    tmp_path: Path, mode: str, *, mcp_url: str, brain_dir: Path
) -> dict[str, str]:
    return {
        **os.environ,
        # The verification suite runs pytest with PYTHONWARNINGS=error; the agent
        # subprocess is a separate program and must not inherit that strictness.
        "PYTHONWARNINGS": "default",
        "XMUSE_TEST_AGENTAPI_LOG": str(tmp_path / "agentapi.jsonl"),
        "XMUSE_TEST_AGENTAPI_MODE": mode,
        "XMUSE_TEST_AGENTAPI_MCP_URL": mcp_url,
        "XMUSE_TEST_AGENTAPI_BRAIN": str(brain_dir),
        "XMUSE_TEST_AGENTAPI_COUNTER": str(tmp_path / "conversation-counter.txt"),
        "XMUSE_TEST_AGENTAPI_STEP_DELAY_S": "0.2",
        "XMUSE_OPERATOR_TOKEN": "operator-secret",
        "XMUSE_MEMORYOS_API_KEY": "memoryos-secret",
        "MEMORYOS_API_KEY": "memoryos-legacy-secret",
        "ANTHROPIC_API_KEY": "sk-ant-test-secret",
    }


def _antigravity_transport(
    tmp_path: Path,
    mcp_url: str,
    *,
    mode: str,
    controls: RoomObservationControlStore,
    decisions: RoomAttemptSkillDecisionStore,
    projector: RoomAgentStreamProjector | None = None,
    ls_env_provider: Any = None,
    agentapi_call_timeout_s: float = 60.0,
) -> AntigravityRoomObservationTransport:
    brain_dir = tmp_path / "brain"
    return AntigravityRoomObservationTransport(
        config=AntigravityTransportConfig(
            workspace=tmp_path,
            agentapi_command=(sys.executable, str(FAKE_AGENTAPI)),
            brain_dir=brain_dir,
            poll_interval_s=0.05,
            shutdown_grace_s=2.0,
            agentapi_call_timeout_s=agentapi_call_timeout_s,
        ),
        registry_path=tmp_path / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
        environ=_agentapi_environment(tmp_path, mode, mcp_url=mcp_url, brain_dir=brain_dir),
        ls_env_provider=ls_env_provider or (lambda: dict(STATIC_LS_ENV)),
    )


def _antigravity_only_room(
    db: Path, *, model: str = "pro"
) -> tuple[str, Participant, RoomKernelStore]:
    conversation_id = RoomTestStore(db).create_conversation("Antigravity room").id
    participant = ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="review",
        display_name="Antigravity Reviewer",
        cli_kind="antigravity",
        model=model,
    )
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Answer with one short sentence.",
        client_request_id="human-1",
    )
    return conversation_id, participant, kernel


def _host(
    db: Path,
    transport: Any,
    *,
    controls: RoomObservationControlStore,
    decisions: RoomAttemptSkillDecisionStore,
    delivery_timeout_s: float = 30.0,
    cleanup_grace_s: float = 2.0,
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


def _events(events: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    return [event for event in events if event.get("event") == name]


async def _wait_for_bound_attempt(
    controls: RoomObservationControlStore,
    observation_id: str,
    *,
    timeout: float = 30.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    binding: dict[str, Any] = {}
    while time.monotonic() < deadline:
        projection = controls.reconcile_state(observation_id)
        binding = projection.get("reconcile_binding") or {}
        if binding.get("provider_phase") == "bound" and binding.get("provider_session_id"):
            return binding
        await asyncio.sleep(0.02)
    raise AssertionError(f"attempt never reached a bound provider session: {binding!r}")


def test_antigravity_environment_keeps_ls_credentials_and_strips_server_secrets(
    tmp_path: Path,
) -> None:
    transport = AntigravityRoomObservationTransport(
        config=AntigravityTransportConfig(
            workspace=tmp_path,
            agentapi_command=(sys.executable, "-c", "pass"),
            brain_dir=tmp_path / "brain",
        ),
        registry_path=tmp_path / "god_sessions.json",
        environ={
            "PATH": "/usr/bin",
            "XMUSE_OPERATOR_TOKEN": "secret",
            "XMUSE_MEMORYOS_API_KEY": "secret",
            "MEMORYOS_API_KEY": "secret",
            "ANTHROPIC_API_KEY": "secret",
            "OPENAI_API_KEY": "kept-for-provider-login",
        },
        ls_env_provider=lambda: dict(STATIC_LS_ENV),
    )

    env = transport._agentapi_environment()

    assert env["PATH"] == "/usr/bin"
    assert env["OPENAI_API_KEY"] == "kept-for-provider-login"
    assert env["ANTIGRAVITY_CSRF_TOKEN"] == "fake-ls-token"
    assert env["ANTIGRAVITY_LS_ADDRESS"] == "localhost:1"
    assert env["NO_PROXY"] == "localhost,127.0.0.1,::1"
    for secret in INJECTED_SECRETS:
        assert secret not in env


def test_language_server_discovery_prefers_a_live_env_pair(tmp_path: Path) -> None:
    probes: list[int] = []

    def probe(port: int, _timeout_s: float) -> bool:
        probes.append(port)
        return True

    env = discover_antigravity_language_server_env(
        {
            "ANTIGRAVITY_LS_ADDRESS": "localhost:41234",
            "ANTIGRAVITY_CSRF_TOKEN": "env-token",
            "ANTIGRAVITY_PROJECT_ID": "project-7",
        },
        proc_root=tmp_path / "missing-proc",
        probe=probe,
    )

    assert env == {
        "ANTIGRAVITY_LS_ADDRESS": "localhost:41234",
        "ANTIGRAVITY_CSRF_TOKEN": "env-token",
        "ANTIGRAVITY_PROJECT_ID": "project-7",
    }
    assert probes == [41234]


def test_language_server_discovery_falls_back_to_the_proc_tree(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    (proc_root / "net").mkdir(parents=True)
    (proc_root / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st\n"
        "   0: 0100007F:1F90 00000000:0000 0A 00000000:00000000 00:00000000\n"
        "   1: 0100007F:0050 00000000:0000 0A 00000000:00000000 00:00000000\n",
        encoding="utf-8",
    )
    (proc_root / "4242").mkdir()
    (proc_root / "4242" / "cmdline").write_bytes(
        b"/opt/antigravity/language_server\0--csrf_token=proc-token\0--extension_server_port\0"
    )

    env = discover_antigravity_language_server_env(
        {},
        proc_root=proc_root,
        probe=lambda port, _timeout_s: port == 8080,
    )

    assert env["ANTIGRAVITY_LS_ADDRESS"] == "localhost:8080"
    assert env["ANTIGRAVITY_CSRF_TOKEN"] == "proc-token"
    assert env["ANTIGRAVITY_PROJECT_ID"] == "outside-of-project"


def test_language_server_discovery_fails_clearly_without_a_server(tmp_path: Path) -> None:
    with pytest.raises(RoomAntigravityTransportError) as excinfo:
        discover_antigravity_language_server_env(
            {},
            proc_root=tmp_path / "empty-proc",
            probe=lambda _port, _timeout_s: True,
        )
    assert excinfo.value.code == "room_antigravity_language_server_unavailable"

    proc_root = tmp_path / "proc-no-port"
    (proc_root / "net").mkdir(parents=True)
    (proc_root / "net" / "tcp").write_text(
        "  sl  local_address rem_address   st\n", encoding="utf-8"
    )
    (proc_root / "43").mkdir()
    (proc_root / "43" / "cmdline").write_bytes(b"language_server\0--csrf_token=token\0")
    with pytest.raises(RoomAntigravityTransportError) as excinfo:
        discover_antigravity_language_server_env(
            {},
            proc_root=proc_root,
            probe=lambda _port, _timeout_s: False,
        )
    assert excinfo.value.code == "room_antigravity_language_server_unavailable"


def test_transcript_reader_resolves_truncated_fields_from_full_log(tmp_path: Path) -> None:
    logs = tmp_path / "brain" / "conversation-a" / ".system_generated" / "logs"
    logs.mkdir(parents=True)
    compact = [
        {"step_index": 0, "type": "USER_INPUT", "status": "DONE", "content": "hi"},
        {
            "step_index": 1,
            "type": "PLANNER_RESPONSE",
            "status": "DONE",
            "content": "trunc",
            "truncated_fields": ["content"],
        },
    ]
    full = [
        dict(compact[0]),
        {**compact[1], "content": "full content", "truncated_fields": None},
    ]
    (logs / "transcript.jsonl").write_text(
        "".join(json.dumps(step) + "\n" for step in compact), encoding="utf-8"
    )
    (logs / "transcript_full.jsonl").write_text(
        "".join(json.dumps(step) + "\n" for step in full), encoding="utf-8"
    )

    steps = read_antigravity_transcript_steps(tmp_path / "brain", "conversation-a")

    assert steps is not None
    assert [step["step_index"] for step in steps] == [0, 1]
    assert steps[1]["content"] == "full content"
    assert read_antigravity_transcript_steps(tmp_path / "brain", "unknown") is None


def test_agentapi_stdout_parsing_tolerates_pretty_json_and_chunking() -> None:
    noisy = (
        "language server: connected\n"
        + json.dumps({"response": {"newConversation": {"conversationId": "conv-42"}}}, indent=2)
        + "\n"
    )
    assert _parse_new_conversation_id(noisy) == "conv-42"
    with pytest.raises(RoomAntigravityTransportError) as failure:
        _parse_new_conversation_id("no json document here")
    assert failure.value.code == "room_antigravity_conversation_id_missing"

    async def _scenario() -> None:
        document = json.dumps(
            {"response": {"newConversation": {"conversationId": "conv-7"}}}, indent=2
        )
        stream = asyncio.StreamReader()
        reader = asyncio.create_task(_read_agentapi_stdout(stream, expect_conversation_id=True))
        stream.feed_data(document[: len(document) // 2].encode())
        await asyncio.sleep(0)
        assert not reader.done()
        stream.feed_data(document[len(document) // 2 :].encode())
        stream.feed_eof()
        text = await reader
        assert _parse_new_conversation_id(text) == "conv-7"

        ack_stream = asyncio.StreamReader()
        ack_reader = asyncio.create_task(
            _read_agentapi_stdout(ack_stream, expect_conversation_id=False)
        )
        ack_stream.feed_data(b'{\n  "response"')
        assert (await ack_reader).startswith("{")

    asyncio.run(_scenario())


def test_antigravity_outcome_lands_durably_with_identity_and_preview(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_outcome_scenario(tmp_path, mcp_url))


async def _outcome_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, participant, _kernel = _antigravity_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(tmp_path))
    transport = _antigravity_transport(
        tmp_path,
        mcp_url,
        mode="normal",
        controls=controls,
        decisions=decisions,
        projector=projector,
    )
    routing = RoutingRoomObservationTransport({"antigravity": transport})
    host = _host(db, routing, controls=controls, decisions=decisions)
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    try:
        result = await host.pump_once(conversation_id=conversation_id)
        record = registry.find_by_conversation_participant(
            conversation_id,
            participant.participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
    finally:
        await transport.aclose()
        await projector.shutdown()

    state = next(
        item for item in result.deliveries if item.participant_id == participant.participant_id
    )
    assert state.state == "completed"

    messages = RoomTestStore(db).list_messages(conversation_id)
    antigravity_messages = [
        message for message in messages if message.author == participant.participant_id
    ]
    assert [message.content for message in antigravity_messages] == ["antigravity durable answer"]
    assert antigravity_messages[0].role == "assistant"

    assert record.runtime == "antigravity"
    assert record.provider_session_kind == ROOM_ANTIGRAVITY_PROVIDER_SESSION_KIND
    assert record.provider_session_id == "fake-conversation-1"
    assert record.provider_binding_status == "active"
    closed = registry.find_by_conversation_participant(
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert closed.provider_binding_status == "closed"
    assert closed.provider_binding_failure_reason == "room_antigravity_shutdown"

    projection = build_room_agent_stream_projection(tmp_path, conversation_id)
    streams = [
        item
        for item in projection["streams"]
        if item["participant_id"] == participant.participant_id
    ]
    assert len(streams) == 1
    assert streams[0]["state"] == "resolved"
    assert "antigravity draft answer" in streams[0]["content"]
    assert streams[0]["resolution"]["outcome_type"] == "respond"

    events = _read_events(tmp_path / "agentapi.jsonl")
    startup = _events(events, "startup")[0]
    assert not set(startup["secret_env_names"]) & set(INJECTED_SECRETS)
    assert startup["has_operator_token"] is False
    assert startup["has_memoryos_api_key"] is False
    assert startup["has_anthropic_api_key"] is False
    assert startup["has_csrf_token"] is True
    assert startup["has_ls_address"] is True
    assert startup["cwd"] == str(tmp_path.resolve())
    new_conversation = _events(events, "new_conversation")[0]
    assert new_conversation["conversation_id"] == "fake-conversation-1"
    assert new_conversation["model"] == "pro"
    assert new_conversation["prompt_has_context"] is True
    assert new_conversation["prompt_has_readonly_instruction"] is True
    assert new_conversation["prompt_has_call_mcp_tool"] is True
    submission = _events(events, "outcome_submission")[0]
    assert "error" not in submission["result"]
    assert submission["result"]["produced_message"]["content"] == "antigravity durable answer"
    assert _events(events, "send_message") == []


def test_second_delivery_reuses_the_conversation_via_send_message(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_reuse_scenario(tmp_path, mcp_url))


async def _reuse_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, participant, kernel = _antigravity_only_room(db, model="not-a-model")
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _antigravity_transport(
        tmp_path, mcp_url, mode="normal", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        first = await host.pump_once(conversation_id=conversation_id)
        kernel.post_human_activity(
            conversation_id=conversation_id,
            human_id="human",
            content="Follow up briefly.",
            client_request_id="human-2",
        )
        second = await host.pump_once(conversation_id=conversation_id)
        record = GodSessionRegistry(
            tmp_path / "god_sessions.json"
        ).find_by_conversation_participant(
            conversation_id,
            participant.participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
    finally:
        await transport.aclose()

    for result in (first, second):
        state = next(
            item for item in result.deliveries if item.participant_id == participant.participant_id
        )
        assert state.state == "completed"

    messages = RoomTestStore(db).list_messages(conversation_id)
    assert [
        message.content for message in messages if message.author == participant.participant_id
    ] == ["antigravity durable answer", "antigravity follow-up answer"]
    assert record.provider_session_id == "fake-conversation-1"

    events = _read_events(tmp_path / "agentapi.jsonl")
    new_conversations = _events(events, "new_conversation")
    send_messages = _events(events, "send_message")
    assert len(new_conversations) == 1
    assert new_conversations[0]["conversation_id"] == "fake-conversation-1"
    # A participant model outside the admitted set falls back to the default.
    assert new_conversations[0]["model"] == "flash"
    assert len(send_messages) == 1
    assert send_messages[0]["conversation_id"] == "fake-conversation-1"
    assert send_messages[0]["base_step_index"] == 4
    assert send_messages[0]["prompt_has_context"] is True
    outcomes = _events(events, "outcome_submission")
    assert len(outcomes) == 2
    assert outcomes[1]["result"]["produced_message"]["content"] == "antigravity follow-up answer"


def test_silent_turn_without_outcome_rotates_and_reopens(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_silent_scenario(tmp_path, mcp_url))


async def _silent_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, participant, kernel = _antigravity_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _antigravity_transport(
        tmp_path, mcp_url, mode="silent", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(
        item for item in result.deliveries if item.participant_id == participant.participant_id
    )
    assert state.state == "incomplete"
    assert state.reason == "durable_outcome_missing"
    assert state.retryable is True

    observation = next(
        item
        for item in kernel.list_observations(conversation_id)
        if item["participant_id"] == participant.participant_id
    )
    assert observation["status"] == "pending"
    assert observation["lease_token"] is None

    record = GodSessionRegistry(tmp_path / "god_sessions.json").find_by_conversation_participant(
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert record.provider_binding_status == "closed"
    assert record.provider_binding_failure_reason == "room_antigravity_durable_outcome_missing"

    events = _read_events(tmp_path / "agentapi.jsonl")
    assert _events(events, "turn_finished_without_outcome") != []
    assert _events(events, "outcome_submission") == []
    # The rotated conversation is dropped, so the retry must start a new one.
    assert transport._conversations == {}


def test_slow_turn_times_out_and_rotates_the_conversation(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_slow_scenario(tmp_path, mcp_url))


async def _slow_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, participant, _kernel = _antigravity_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _antigravity_transport(
        tmp_path, mcp_url, mode="slow", controls=controls, decisions=decisions
    )
    host = _host(
        db,
        transport,
        controls=controls,
        decisions=decisions,
        delivery_timeout_s=6.0,
        cleanup_grace_s=2.0,
    )
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(
        item for item in result.deliveries if item.participant_id == participant.participant_id
    )
    assert state.state == "failed"
    assert state.reason in {"delivery_timeout", "room_antigravity_timeout"}
    assert state.retryable is True

    events = _read_events(tmp_path / "agentapi.jsonl")
    assert _events(events, "turn_started") != []
    assert _events(events, "outcome_submission") == []
    assert _events(events, "sigterm_received") != []

    record = GodSessionRegistry(tmp_path / "god_sessions.json").find_by_conversation_participant(
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert record.provider_binding_status == "closed"
    assert record.provider_binding_failure_reason in {
        "room_antigravity_timeout",
        "room_antigravity_delivery_cancelled",
    }
    assert transport._conversations == {}


def test_silent_agentapi_call_times_out_and_fails_cleanly(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_agentapi_call_timeout_scenario(tmp_path, mcp_url))


async def _agentapi_call_timeout_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, participant, _kernel = _antigravity_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _antigravity_transport(
        tmp_path,
        mcp_url,
        mode="mute",
        controls=controls,
        decisions=decisions,
        agentapi_call_timeout_s=0.5,
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(
        item for item in result.deliveries if item.participant_id == participant.participant_id
    )
    assert state.state == "failed"
    assert state.reason == "room_antigravity_agentapi_timeout"
    assert state.retryable is True

    record = GodSessionRegistry(tmp_path / "god_sessions.json").find_by_conversation_participant(
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert record.provider_binding_status == "closed"
    assert record.provider_binding_failure_reason == "room_antigravity_agentapi_timeout"

    events = _read_events(tmp_path / "agentapi.jsonl")
    assert _events(events, "muted") != []
    assert _events(events, "new_conversation") == []
    assert _events(events, "sigterm_received") != []
    assert transport._conversations == {}


def test_reconcile_cancel_drops_the_bound_conversation(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_reconcile_scenario(tmp_path, mcp_url))


async def _reconcile_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, participant, kernel = _antigravity_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _antigravity_transport(
        tmp_path, mcp_url, mode="slow", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    pump_task = asyncio.create_task(host.pump_once(conversation_id=conversation_id))
    try:
        observation_id = kernel.list_observations(conversation_id)[0]["observation_id"]
        binding = await _wait_for_bound_attempt(controls, observation_id)
        assert binding["provider_session_id"] == "fake-conversation-1"
        assert binding["provider_phase"] == "bound"

        settled = await transport.reconcile_cancel(
            conversation_id=conversation_id,
            participant=participant,
            attempt=binding,
            timeout_s=5.0,
        )
        assert settled.status == "settled"
        assert settled.reason == "room_antigravity_cancel_abandoned_turn"

        again = await transport.reconcile_cancel(
            conversation_id=conversation_id,
            participant=participant,
            attempt=binding,
            timeout_s=5.0,
        )
        assert again.status == "settled"
        assert again.reason == "room_antigravity_cancel_no_active_conversation"
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        await transport.aclose()

    record = GodSessionRegistry(tmp_path / "god_sessions.json").find_by_conversation_participant(
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert record.provider_binding_status == "closed"
    assert record.provider_binding_failure_reason == "room_antigravity_cancel_reconcile"

    events = _read_events(tmp_path / "agentapi.jsonl")
    assert _events(events, "sigterm_received") != []
    assert _events(events, "outcome_submission") == []


def test_language_server_env_failure_fails_the_delivery_clearly(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_ls_failure_scenario(tmp_path, mcp_url))


def _unavailable_ls_env() -> dict[str, str]:
    raise RoomAntigravityTransportError(
        "room_antigravity_language_server_unavailable",
        "no running Antigravity language_server process was found",
    )


async def _ls_failure_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, participant, _kernel = _antigravity_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _antigravity_transport(
        tmp_path,
        mcp_url,
        mode="normal",
        controls=controls,
        decisions=decisions,
        ls_env_provider=_unavailable_ls_env,
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(
        item for item in result.deliveries if item.participant_id == participant.participant_id
    )
    assert state.state == "failed"
    assert state.reason == "room_antigravity_language_server_unavailable"
    assert state.retryable is True

    record = GodSessionRegistry(tmp_path / "god_sessions.json").find_by_conversation_participant(
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert record.provider_binding_status == "closed"
    assert record.provider_binding_failure_reason == "room_antigravity_language_server_unavailable"
    # Discovery fails before any agentapi process is ever spawned.
    assert not (tmp_path / "agentapi.jsonl").exists()
