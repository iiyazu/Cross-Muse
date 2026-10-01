"""End-to-end ACP Room transport tests against a scripted agent.

No real provider and no external network: the "agent" is
``tests/xmuse/fixtures/fake_acp_agent.py`` (the ACP agent-side SDK, stdlib only),
and the Room MCP endpoint is the real ``xmuse.room_mcp_server`` app served by
uvicorn on an ephemeral loopback port.  The scripted agent commits Room truth only
through ``chat_room_submit_outcome`` over HTTP, exactly like a real ACP agent.
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
from types import SimpleNamespace
from typing import Any

import pytest
import uvicorn

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse.room_mcp_server import create_app
from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_acp_transport import (
    ROOM_ACP_BUILTIN_TOOLS,
    ROOM_ACP_PROVIDER_SESSION_KIND,
    AcpRoomObservationTransport,
    AcpTransportConfig,
    _is_room_outcome_tool_identifier,
    _tool_identity_candidates,
)
from xmuse_core.chat.room_agent_stream import (
    RoomAgentStreamCache,
    RoomAgentStreamProjector,
    build_room_agent_stream_projection,
)
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
    RoomTransportResult,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_observation_transport_base import sanitized_agent_environment
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.chat.room_transport_router import RoutingRoomObservationTransport

FAKE_AGENT = Path(__file__).resolve().parent / "fixtures" / "fake_acp_agent.py"
OUTCOME_TOOL_TITLE = "mcp__xmuse-room__chat_room_submit_outcome"
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


class _CodexStubTransport:
    """A trivial provider-neutral peer so the room roster is genuinely mixed."""

    def __init__(self, db: Path, registry_path: Path, record: GodSessionRecord) -> None:
        self._db = db
        self._registry_path = registry_path
        self._record = record
        self.deliveries: list[RoomObservationDelivery] = []

    async def deliver(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> RoomTransportResult:
        self.deliveries.append(delivery)
        RoomApplicationService(self._db, self._registry_path).submit_participant_outcome(
            conversation_id=delivery.conversation_id,
            participant_id=delivery.participant.participant_id,
            god_session_id=self._record.god_session_id,
            observation_id=delivery.observation["observation_id"],
            lease_token=delivery.observation["lease_token"],
            client_request_id=delivery.outcome_client_request_id,
            outcome_type="respond",
            outcome_payload={"content": "codex durable answer"},
        )
        return RoomTransportResult("finished")


def _agent_environment(tmp_path: Path, mode: str, *, content: str) -> dict[str, str]:
    return {
        **os.environ,
        # The verification suite runs pytest with PYTHONWARNINGS=error; the agent
        # subprocess is a separate program and must not inherit that strictness.
        "PYTHONWARNINGS": "default",
        "XMUSE_TEST_ACP_LOG": str(tmp_path / "acp-agent.jsonl"),
        "XMUSE_TEST_ACP_MODE": mode,
        "XMUSE_TEST_ACP_CONTENT": content,
        "XMUSE_OPERATOR_TOKEN": "operator-secret",
        "XMUSE_MEMORYOS_API_KEY": "memoryos-secret",
        "MEMORYOS_API_KEY": "memoryos-legacy-secret",
        "ANTHROPIC_API_KEY": "sk-ant-test-secret",
    }


def _claude_transport(
    tmp_path: Path,
    mcp_url: str,
    *,
    mode: str,
    content: str = "claude durable answer",
    controls: RoomObservationControlStore,
    decisions: RoomAttemptSkillDecisionStore,
    projector: RoomAgentStreamProjector | None = None,
) -> AcpRoomObservationTransport:
    return AcpRoomObservationTransport(
        config=AcpTransportConfig(
            workspace=tmp_path,
            command=(sys.executable, str(FAKE_AGENT)),
            room_mcp_url=mcp_url,
            initialize_timeout_s=30.0,
            shutdown_grace_s=2.0,
        ),
        registry_path=tmp_path / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
        environ=_agent_environment(tmp_path, mode, content=content),
    )


def _claude_only_room(
    db: Path,
) -> tuple[str, Participant, RoomKernelStore]:
    conversation_id = RoomTestStore(db).create_conversation("ACP room").id
    claude = ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="review",
        display_name="Claude Reviewer",
        cli_kind="claude",
        model="claude-acp-default",
    )
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Answer with one short sentence.",
        client_request_id="human-1",
    )
    return conversation_id, claude, kernel


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


@pytest.mark.parametrize(
    ("tool_call", "extra", "allowed"),
    [
        (
            SimpleNamespace(title="mcp__xmuse-room__chat_room_submit_outcome", raw_input={}),
            {},
            True,
        ),
        # A tool name smuggled into model-controlled arguments never authorizes.
        (
            SimpleNamespace(
                title="Bash",
                raw_input="rm -rf ~; echo mcp__xmuse-room__chat_room_submit_outcome",
            ),
            {},
            False,
        ),
        (
            SimpleNamespace(
                title="Bash",
                raw_input={"tool_name": "mcp__xmuse-room__chat_room_submit_outcome"},
                field_meta={"tool": "mcp__xmuse-room__chat_room_submit_outcome"},
            ),
            {"_meta": {"toolName": "mcp__xmuse-room__chat_room_submit_outcome"}},
            False,
        ),
        # Same tool name on another MCP server or a suffix match is not the room tool.
        (SimpleNamespace(title="chat_room_submit_outcome", raw_input={}), {}, False),
        (
            SimpleNamespace(title="mcp__evil__mcp__xmuse-room__chat_room_submit_outcome"),
            {},
            False,
        ),
    ],
)
def test_permission_allows_only_the_exact_room_outcome_tool(
    tool_call: SimpleNamespace, extra: dict[str, Any], allowed: bool
) -> None:
    identifiers = _tool_identity_candidates(tool_call, extra)
    assert any(_is_room_outcome_tool_identifier(item) for item in identifiers) is allowed


def test_sanitized_agent_environment_strips_only_server_secrets() -> None:
    sanitized = sanitized_agent_environment(
        {
            "PATH": "/usr/bin",
            "XMUSE_OPERATOR_TOKEN": "secret",
            "XMUSE_MEMORYOS_API_KEY": "secret",
            "MEMORYOS_API_KEY": "secret",
            "ANTHROPIC_API_KEY": "secret",
            "OPENAI_API_KEY": "kept-for-provider-login",
            "XMUSE_TEST_ACP_LOG": "/tmp/log",
        }
    )
    assert sanitized == {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "kept-for-provider-login",
        "XMUSE_TEST_ACP_LOG": "/tmp/log",
    }


def test_claude_acp_outcome_lands_durably_with_identity_and_preview(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_mixed_roster_scenario(tmp_path, mcp_url))


async def _mixed_roster_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("Mixed ACP room").id
    participants = ParticipantStore(db)
    codex = participants.add(
        conversation_id=conversation_id,
        role="architect",
        display_name="Codex Architect",
        cli_kind="codex",
        model="gpt-5",
    )
    claude = participants.add(
        conversation_id=conversation_id,
        role="review",
        display_name="Claude Reviewer",
        cli_kind="claude",
        model="claude-acp-default",
    )
    registry_path = tmp_path / "god_sessions.json"
    registry = GodSessionRegistry(registry_path)
    codex_record = registry.create(
        codex.role,
        codex.display_name,
        "codex",
        "@architect",
        "inbox-architect",
        conversation_id,
        codex.participant_id,
    )
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Compare two options in one short answer.",
        client_request_id="human-1",
    )

    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(tmp_path))
    claude_transport = _claude_transport(
        tmp_path,
        mcp_url,
        mode="normal",
        controls=controls,
        decisions=decisions,
        projector=projector,
    )
    routing = RoutingRoomObservationTransport(
        {
            "codex": _CodexStubTransport(db, registry_path, codex_record),
            "claude": claude_transport,
        }
    )
    host = _host(db, routing, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
        record = registry.find_by_conversation_participant(
            conversation_id,
            claude.participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
    finally:
        await claude_transport.aclose()
        await projector.shutdown()

    states = {item.participant_id: item for item in result.deliveries}
    assert states[claude.participant_id].state == "completed"
    assert states[codex.participant_id].state == "completed"

    messages = RoomTestStore(db).list_messages(conversation_id)
    claude_messages = [message for message in messages if message.author == claude.participant_id]
    assert [message.content for message in claude_messages] == ["claude durable answer"]
    assert claude_messages[0].role == "assistant"

    assert record.runtime == "claude"
    assert record.provider_session_kind == ROOM_ACP_PROVIDER_SESSION_KIND
    assert record.provider_session_id == "fake-session-1"
    assert record.provider_binding_status == "active"
    closed = registry.find_by_conversation_participant(
        conversation_id,
        claude.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert closed.provider_binding_status == "closed"
    assert closed.provider_binding_failure_reason == "room_acp_shutdown"

    projection = build_room_agent_stream_projection(tmp_path, conversation_id)
    streams = [
        item for item in projection["streams"] if item["participant_id"] == claude.participant_id
    ]
    assert len(streams) == 1
    assert streams[0]["state"] == "resolved"
    assert "claude durable answer" in streams[0]["content"]
    assert streams[0]["resolution"]["outcome_type"] == "respond"

    events = _read_events(tmp_path / "acp-agent.jsonl")
    startup = _event(events, "startup")
    assert startup is not None
    assert not set(startup["secret_env_names"]) & set(INJECTED_SECRETS)
    assert startup["has_operator_token"] is False
    assert startup["has_memoryos_api_key"] is False
    assert startup["has_anthropic_api_key"] is False
    assert startup["cwd"] == str(tmp_path.resolve())
    session_event = _event(events, "new_session")
    assert session_event is not None
    assert session_event["mcp_url"] == mcp_url
    assert session_event["server_name"] == "xmuse-room"
    assert session_event["claude_code"] == {
        "options": {
            "tools": list(ROOM_ACP_BUILTIN_TOOLS),
            "settingSources": ["user"],
        }
    }
    mode_event = _event(events, "set_session_mode")
    assert mode_event == {
        "event": "set_session_mode",
        "session_id": "fake-session-1",
        "mode_id": "default",
    }
    submission = _event(events, "outcome_submission")
    assert submission is not None
    assert "error" not in submission["result"]
    assert submission["result"]["produced_message"]["content"] == "claude durable answer"


def test_forbidden_tool_request_is_rejected_and_outcome_still_lands(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_forbidden_scenario(tmp_path, mcp_url))


async def _forbidden_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, claude, _kernel = _claude_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _claude_transport(
        tmp_path, mcp_url, mode="forbidden", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    states = {item.participant_id: item for item in result.deliveries}
    assert states[claude.participant_id].state == "completed"

    events = _read_events(tmp_path / "acp-agent.jsonl")
    decisions_log = [event for event in events if event["event"] == "permission_decision"]
    assert [(item["tool"], item["allowed"]) for item in decisions_log] == [
        ("Bash", False),
        (OUTCOME_TOOL_TITLE, True),
    ]
    # A denial must be a selected reject option, not ``cancelled`` (which the
    # adapter treats as an abort of the whole turn).
    assert decisions_log[0]["outcome"] == "selected"
    assert decisions_log[0]["chosen_kind"] == "reject_once"
    forbidden = _event(events, "forbidden_tool_decision")
    assert forbidden == {"event": "forbidden_tool_decision", "tool": "Bash", "allowed": False}
    submission = _event(events, "outcome_submission")
    assert submission is not None and "error" not in submission["result"]


def test_silent_turn_without_outcome_rotates_session_and_reopens(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_silent_scenario(tmp_path, mcp_url))


async def _silent_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, claude, kernel = _claude_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _claude_transport(
        tmp_path, mcp_url, mode="silent", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(item for item in result.deliveries if item.participant_id == claude.participant_id)
    assert state.state == "incomplete"
    assert state.reason == "durable_outcome_missing"
    assert state.retryable is True

    observation = next(
        item
        for item in kernel.list_observations(conversation_id)
        if item["participant_id"] == claude.participant_id
    )
    assert observation["status"] == "pending"
    assert observation["lease_token"] is None

    record = GodSessionRegistry(tmp_path / "god_sessions.json").find_by_conversation_participant(
        conversation_id,
        claude.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    assert record.provider_binding_status == "closed"
    assert record.provider_binding_failure_reason == "room_acp_durable_outcome_missing"

    events = _read_events(tmp_path / "acp-agent.jsonl")
    assert _event(events, "prompt_received") is not None
    assert _event(events, "outcome_submission") is None
    assert any(event["event"] in {"agent_exit", "sigterm_received"} for event in events)


def test_slow_turn_times_out_and_cancels_the_provider_turn(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_slow_scenario(tmp_path, mcp_url))


async def _slow_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, claude, _kernel = _claude_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _claude_transport(
        tmp_path, mcp_url, mode="slow", controls=controls, decisions=decisions
    )
    host = _host(
        db,
        transport,
        controls=controls,
        decisions=decisions,
        # The scripted agent needs ~6s to import the ACP SDK before it can
        # receive the turn; the timeout must fire only after the slow turn
        # actually started, or nothing would ever be cancelled.
        delivery_timeout_s=14.0,
        cleanup_grace_s=5.0,
    )
    try:
        result = await host.pump_once(conversation_id=conversation_id)
    finally:
        await transport.aclose()

    state = next(item for item in result.deliveries if item.participant_id == claude.participant_id)
    assert state.state == "failed"
    assert state.reason in {"delivery_timeout", "room_acp_timeout"}
    assert state.retryable is True

    events = _read_events(tmp_path / "acp-agent.jsonl")
    assert _event(events, "prompt_received") is not None
    assert _event(events, "cancel_received") is not None
    assert _event(events, "slow_turn_released") is not None
    assert _event(events, "outcome_submission") is None


def test_reconcile_cancel_settles_only_the_bound_provider_session(tmp_path: Path) -> None:
    with _serve_room_mcp(tmp_path) as mcp_url:
        asyncio.run(_reconcile_scenario(tmp_path, mcp_url))


async def _reconcile_scenario(tmp_path: Path, mcp_url: str) -> None:
    db = tmp_path / "chat.db"
    conversation_id, claude, kernel = _claude_only_room(db)
    controls = RoomObservationControlStore(db)
    decisions = RoomAttemptSkillDecisionStore(db)
    transport = _claude_transport(
        tmp_path, mcp_url, mode="slow", controls=controls, decisions=decisions
    )
    host = _host(db, transport, controls=controls, decisions=decisions)
    pump_task = asyncio.create_task(host.pump_once(conversation_id=conversation_id))
    try:
        observation_id = kernel.list_observations(conversation_id)[0]["observation_id"]
        binding = await _wait_for_bound_attempt(controls, observation_id)
        assert binding["provider_session_id"] == "fake-session-1"
        assert binding["provider_phase"] == "bound"

        settled = await transport.reconcile_cancel(
            conversation_id=conversation_id,
            participant=claude,
            attempt=binding,
            timeout_s=5.0,
        )
        assert settled.status == "settled"
        assert settled.reason == "room_acp_cancel_session_closed"

        again = await transport.reconcile_cancel(
            conversation_id=conversation_id,
            participant=claude,
            attempt=binding,
            timeout_s=5.0,
        )
        assert again.status == "settled"
        assert again.reason == "room_acp_cancel_no_active_session"

        result = await asyncio.wait_for(pump_task, timeout=30.0)
        state = next(
            item for item in result.deliveries if item.participant_id == claude.participant_id
        )
        assert state.state == "failed"
    finally:
        pump_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await pump_task
        await transport.aclose()

    events = _read_events(tmp_path / "acp-agent.jsonl")
    assert _event(events, "cancel_received") is not None
    assert any(event["event"] in {"agent_exit", "sigterm_received"} for event in events)
