from __future__ import annotations

import asyncio
import json
import shutil
import socket
import statistics
from contextlib import suppress
from pathlib import Path

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from xmuse import platform_runner
from xmuse.chat_api import create_app as create_chat_app
from xmuse.mcp_server import create_app as create_mcp_app
from xmuse_core.agents import codex_persistent
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.ray_session_layer import RayGodSessionLayer
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore


class DummyLauncher:
    supports_persistent_sessions = True

    def __init__(self, model: str) -> None:
        self.model = model

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        return ["codex", role, str(worktree)]

    def persistent_model(self) -> str:
        return self.model


class DummyRayActor:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self._alive = False
        self._shutdown = False
        resumed = kwargs.get("resume_thread_id")
        self._thread_id = resumed if isinstance(resumed, str) and resumed.strip() else None
        if self._thread_id is None:
            self._thread_id = f"thread-{kwargs['god_id']}"

    async def ensure_alive(self):
        self._alive = True
        return None

    async def get_info(self):
        return {
            "alive": self._alive,
            "transport": "codex-app-server",
            "thread_id": self._thread_id,
        }

    async def send_typed(self, *_args, **_kwargs) -> None:
        return None

    async def receive(self):
        return None

    async def shutdown(self):
        self._shutdown = True
        self._alive = False
        return None


class FakeProviderAppServerActor:
    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        self._alive = False
        resumed = kwargs.get("resume_thread_id")
        self._thread_id = resumed if isinstance(resumed, str) and resumed.strip() else None
        if self._thread_id is None:
            self._thread_id = f"provider-thread-{kwargs['god_id']}"
        self.sent: list[dict[str, object]] = []
        self.streaming_deltas: list[str] = []
        self._last_payload: dict[str, object] | None = None

    async def ensure_alive(self):
        self._alive = True
        return None

    async def get_info(self):
        return {
            "alive": self._alive,
            "transport": "codex-app-server",
            "thread_id": self._thread_id,
        }

    async def send_typed(self, msg_type: str, **payload) -> None:
        self.sent.append({"msg_type": msg_type, **payload})
        self._last_payload = payload
        self.streaming_deltas.append("delta:ack")

    async def receive(self):
        assert self._last_payload is not None
        context = json.loads(str(self._last_payload["context"]))
        mcp_url = f"http://127.0.0.1:{self.kwargs['mcp_port']}/mcp"
        async with httpx.AsyncClient(timeout=10.0) as client:
            inbox = await _http_mcp_call(
                client,
                mcp_url,
                "chat_read_inbox",
                {
                    "conversation_id": context["conversation_id"],
                    "participant_id": context["participant_id"],
                    "god_session_id": context["god_session_id"],
                },
            )
            inbox_items = inbox["inbox_items"]
            assert inbox_items
            item = inbox_items[0]
            await _http_mcp_call(
                client,
                mcp_url,
                "chat_post_message",
                {
                    "conversation_id": context["conversation_id"],
                    "participant_id": context["participant_id"],
                    "god_session_id": context["god_session_id"],
                    "client_request_id": f"{item['id']}:fake-provider",
                    "content": f"Architect GOD via {self._thread_id}: received.",
                    "reply_to_inbox_item_id": item["id"],
                },
            )
        return type(
            "Message",
            (),
            {
                "type": "result",
                "status": "success",
                "request_id": self._last_payload.get("request_id"),
                "message": "",
                "artifacts": {"transport": "fake-provider-app-server"},
            },
        )()

    async def shutdown(self):
        self._alive = False
        return None


def _mcp_call(client: TestClient, name: str, arguments: dict[str, object]) -> dict[str, object]:
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


async def _http_mcp_call(
    client: httpx.AsyncClient,
    url: str,
    name: str,
    arguments: dict[str, object],
) -> dict[str, object]:
    response = await client.post(
        url,
        json={
            "jsonrpc": "2.0",
            "id": f"call-{name}",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    response.raise_for_status()
    return response.json()["result"]["structuredContent"]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


async def _serve_app(app, *, port: int) -> tuple[uvicorn.Server, asyncio.Task]:
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    )
    task = asyncio.create_task(server.serve())
    for _ in range(100):
        if server.started:
            return server, task
        await asyncio.sleep(0.05)
    raise AssertionError(f"server did not start on port {port}")


async def _stop_server(server: uvicorn.Server, task: asyncio.Task) -> None:
    server.should_exit = True
    try:
        await asyncio.wait_for(task, timeout=5)
    except (TimeoutError, asyncio.CancelledError):
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _wait_for_reply_count(
    db_path: Path,
    conversation_id: str,
    participant_id: str,
    expected: int,
    *,
    attempts: int = 120,
) -> list:
    for _ in range(attempts):
        replies = [
            message
            for message in ChatStore(db_path).list_messages(conversation_id)
            if message.author == participant_id and message.role == "assistant"
        ]
        if len(replies) >= expected:
            return replies
        await asyncio.sleep(0.1)
    raise AssertionError(f"expected {expected} replies")


async def _wait_for_latency_trace_count(
    db_path: Path,
    conversation_id: str,
    expected: int,
    *,
    attempts: int = 120,
) -> list[dict[str, object]]:
    for _ in range(attempts):
        traces = PeerTurnLatencyTraceStore(db_path).list_recent(conversation_id)
        if len(traces) >= expected:
            return traces
        await asyncio.sleep(0.1)
    raise AssertionError(f"expected {expected} latency traces")


async def _wait_for_read_inbox_count(
    db_path: Path,
    conversation_id: str,
    participant_id: str,
    expected: int,
    *,
    attempts: int = 180,
) -> list:
    for _ in range(attempts):
        items = [
            item
            for item in ChatInboxStore(db_path).list_by_conversation(
                conversation_id,
                include_terminal=True,
            )
            if item.target_participant_id == participant_id and item.status == "read"
        ]
        if len(items) >= expected:
            return items
        await asyncio.sleep(0.1)
    raise AssertionError(f"expected {expected} read inbox items")


async def _wait_for_proposal_count(
    db_path: Path,
    conversation_id: str,
    expected: int,
    *,
    attempts: int = 600,
) -> list:
    for _ in range(attempts):
        proposals = ChatStore(db_path).list_proposals(conversation_id)
        if len(proposals) >= expected:
            return proposals
        await asyncio.sleep(0.1)
    raise AssertionError(f"expected {expected} proposals")


async def _wait_for_review_trigger_count(
    db_path: Path,
    conversation_id: str,
    expected: int,
    *,
    attempts: int = 600,
) -> list:
    for _ in range(attempts):
        items = _review_inbox_items(db_path, conversation_id)
        if len(items) >= expected:
            return items
        await asyncio.sleep(0.1)
    raise AssertionError(f"expected {expected} review trigger inbox items")


async def _wait_for_dispatch_entry_count(
    db_path: Path,
    conversation_id: str,
    expected: int,
    *,
    attempts: int = 120,
) -> list:
    for _ in range(attempts):
        entries = ChatDispatchQueueStore(db_path).list_entries(conversation_id)
        if len(entries) >= expected:
            return entries
        await asyncio.sleep(0.1)
    raise AssertionError(f"expected {expected} dispatch queue entries")


async def _post_architect_turn_and_wait(
    client: httpx.AsyncClient,
    *,
    db_path: Path,
    conversation_id: str,
    architect_id: str,
    turn_index: int,
    content: str,
    attempts: int = 600,
) -> list[dict[str, object]]:
    response = await client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={
            "author": "human-1",
            "role": "human",
            "content": content,
            "client_request_id": f"real-soak-turn-{turn_index}",
        },
    )
    response.raise_for_status()
    await _wait_for_reply_count(
        db_path,
        conversation_id,
        architect_id,
        turn_index,
        attempts=attempts,
    )
    await _wait_for_read_inbox_count(
        db_path,
        conversation_id,
        architect_id,
        turn_index,
        attempts=attempts,
    )
    return await _wait_for_latency_trace_count(
        db_path,
        conversation_id,
        turn_index,
        attempts=attempts,
    )


def _latency_soak_report(traces: list[dict[str, object]]) -> dict[str, object]:
    chronological = list(reversed(traces))
    totals = [
        int(trace["total_latency_ms"])
        for trace in chronological
        if isinstance(trace.get("total_latency_ms"), int)
    ]
    stage_durations: dict[str, list[int]] = {}
    stage_order = [
        "inbox_claim",
        "ray_actor_delivery_start",
        "stream_started",
        "first_visible",
        "first_stream_delta",
        "codex_app_server_turn_start",
        "mcp_tools_ready",
        "chat_read_inbox",
        "chat_post_message",
        "scheduler_observed_result",
        "trace_persisted",
    ]
    per_turn: list[dict[str, object]] = []
    for index, trace in enumerate(chronological, start=1):
        raw_stages = trace.get("stage_timings")
        stages = raw_stages if isinstance(raw_stages, dict) else {}
        stage_deltas: dict[str, int] = {}
        previous_name: str | None = None
        previous_at: float | None = None
        for name in stage_order:
            raw_stage = stages.get(name)
            if not isinstance(raw_stage, dict):
                continue
            at = raw_stage.get("at")
            if not isinstance(at, (int, float)):
                continue
            if previous_name is not None and previous_at is not None:
                label = f"{previous_name}->{name}"
                duration_ms = max(0, round((float(at) - previous_at) * 1000))
                stage_deltas[label] = duration_ms
                stage_durations.setdefault(label, []).append(duration_ms)
            previous_name = name
            previous_at = float(at)
        slowest_stage = max(stage_deltas.items(), key=lambda item: item[1], default=(None, None))
        per_turn.append(
            {
                "turn": index,
                "inbox_item_id": trace["inbox_item_id"],
                "total_latency_ms": trace["total_latency_ms"],
                "delivery_mode": trace["delivery_mode"],
                "degraded_reason": trace["degraded_reason"],
                "slowest_stage": slowest_stage[0],
                "slowest_stage_ms": slowest_stage[1],
                "observed_stages": sorted(stages),
            }
        )
    slowest_stage_totals = {
        name: max(values)
        for name, values in stage_durations.items()
        if values
    }
    return {
        "turns": len(chronological),
        "total_latency_ms": {
            "median": round(statistics.median(totals)) if totals else None,
            "p95": _p95(totals),
            "max": max(totals) if totals else None,
        },
        "slowest_stage": max(
            slowest_stage_totals.items(),
            key=lambda item: item[1],
            default=(None, None),
        ),
        "per_turn": per_turn,
    }


def _v12_latency_parity_report(
    traces: list[dict[str, object]],
    *,
    provider_session_id: str | None,
    provider_session_reused: bool,
) -> dict[str, object]:
    turns: list[dict[str, object]] = []
    for index, trace in enumerate(reversed(traces), start=1):
        stages = trace.get("stage_timings")
        stage_timings = stages if isinstance(stages, dict) else {}
        inbox_claim_at = _trace_stage_at(stage_timings, "inbox_claim")
        first_visible_at = _trace_stage_at(stage_timings, "first_visible")
        writeback_at = _trace_stage_at(stage_timings, "trace_persisted")
        if not isinstance(writeback_at, float):
            raw_writeback_at = trace.get("writeback_at")
            writeback_at = (
                float(raw_writeback_at)
                if isinstance(raw_writeback_at, (int, float))
                else None
            )
        delivery_mode = str(trace.get("delivery_mode") or "")
        degraded_reason = str(trace.get("degraded_reason") or "")
        turns.append(
            {
                "turn": index,
                "inbox_item_id": trace.get("inbox_item_id"),
                "delivery_mode": delivery_mode,
                "first_visible_ms": _elapsed_ms(inbox_claim_at, first_visible_at),
                "writeback_ms": _elapsed_ms(inbox_claim_at, writeback_at),
                "has_chat_post_message_stage": "chat_post_message" in stage_timings,
                "has_stdout_fallback": (
                    delivery_mode == "stdout_fallback"
                    or degraded_reason == "stdout_fallback"
                ),
                "observed_stages": sorted(stage_timings),
            }
        )
    return {
        "provider_session_id": provider_session_id,
        "provider_session_reused": provider_session_reused,
        "turns": turns,
    }


def _assert_v12_latency_parity_report(report: dict[str, object]) -> None:
    assert report["provider_session_id"]
    assert report["provider_session_reused"] is True
    turns = report.get("turns")
    assert isinstance(turns, list) and turns
    for turn in turns:
        assert isinstance(turn, dict)
        assert turn["delivery_mode"] == "mcp_writeback"
        assert turn["has_chat_post_message_stage"] is True
        assert turn["has_stdout_fallback"] is False
        first_visible_ms = turn["first_visible_ms"]
        writeback_ms = turn["writeback_ms"]
        assert isinstance(writeback_ms, int)
        if first_visible_ms is not None:
            assert isinstance(first_visible_ms, int)
            assert first_visible_ms < writeback_ms


def _assert_real_provider_mcp_writeback_traces(traces: list[dict[str, object]]) -> None:
    assert {trace["delivery_mode"] for trace in traces} == {"mcp_writeback"}
    allowed_reasons = {None, "peer_writeback_before_provider_result"}
    assert {trace.get("degraded_reason") for trace in traces} <= allowed_reasons
    for trace in traces:
        stages = trace.get("stage_timings")
        assert isinstance(stages, dict)
        assert "chat_post_message" in stages
        assert "chat_post_message_persisted" in stages


def _trace_stage_at(stages: dict[str, object], name: str) -> float | None:
    stage = stages.get(name)
    if not isinstance(stage, dict):
        return None
    at = stage.get("at")
    return float(at) if isinstance(at, (int, float)) else None


def _elapsed_ms(start_at: float | None, end_at: float | None) -> int | None:
    if start_at is None or end_at is None:
        return None
    return max(0, round((end_at - start_at) * 1000))


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * 0.95))
    return ordered[index]


def test_v12_latency_parity_report_records_first_visible_writeback_and_modes() -> None:
    traces = [
        {
            "inbox_item_id": "inbox-1",
            "delivery_mode": "mcp_writeback",
            "degraded_reason": None,
            "writeback_at": 12.0,
            "total_latency_ms": 2000,
            "stage_timings": {
                "inbox_claim": {"at": 10.0},
                "stream_started": {"at": 10.1},
                "first_visible": {"at": 10.1},
                "first_stream_delta": {"at": 10.2},
                "chat_post_message": {"at": 11.7},
                "scheduler_observed_result": {"at": 11.9},
                "trace_persisted": {"at": 12.0},
            },
        }
    ]

    report = _v12_latency_parity_report(
        traces,
        provider_session_id="thread-1",
        provider_session_reused=True,
    )

    assert report == {
        "provider_session_id": "thread-1",
        "provider_session_reused": True,
        "turns": [
            {
                "turn": 1,
                "inbox_item_id": "inbox-1",
                "delivery_mode": "mcp_writeback",
                "first_visible_ms": 100,
                "writeback_ms": 2000,
                "has_chat_post_message_stage": True,
                "has_stdout_fallback": False,
                "observed_stages": [
                    "chat_post_message",
                    "first_stream_delta",
                    "first_visible",
                    "inbox_claim",
                    "scheduler_observed_result",
                    "stream_started",
                    "trace_persisted",
                ],
            }
        ],
    }


def _participant_by_role(db_path: Path, conversation_id: str, role: str) -> Participant:
    store = ParticipantStore(db_path)
    for participant in store.list_by_conversation(conversation_id):
        if participant.role == role:
            return participant
    raise AssertionError(f"missing participant role: {role}")


def _review_inbox_items(db_path: Path, conversation_id: str) -> list:
    return [
        item
        for item in ChatInboxStore(db_path).list_by_conversation(
            conversation_id,
            include_terminal=True,
        )
        if item.target_role == "review" and item.item_type == "review_trigger"
    ]


def _actor_factory(actors: list[DummyRayActor], **kwargs) -> DummyRayActor:
    actor = DummyRayActor(**kwargs)
    actors.append(actor)
    return actor


def test_native_codex_persistent_shim_is_not_production_long_session() -> None:
    metadata = codex_persistent.runtime_truth_metadata()

    assert metadata["runtime_mode"] == "native_exec_shim"
    assert metadata["provider_native_long_session"] is False
    assert metadata["spawns_provider_process_per_turn"] is True
    assert metadata["production_peer_happy_path"] is False


async def _ensure_session(
    layer: RayGodSessionLayer,
    *,
    db_path: Path,
    conversation_id: str,
    role: str,
    worktree: Path,
) -> tuple[Participant, object]:
    participant = _participant_by_role(db_path, conversation_id, role)
    runtime: AgentRuntime | str = (
        AgentRuntime.CODEX if participant.cli_kind == "codex" else participant.cli_kind
    )
    record = await layer.ensure_conversation_session(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        role=participant.role,
        agent=AgentDescriptor(
            name=participant.display_name,
            runtime=runtime,
            capabilities=[participant.role],
        ),
        worktree=worktree,
        model=participant.model,
    )
    return participant, record


async def _run_full_chain(tmp_path: Path, *, restart_midway: bool) -> dict[str, object]:
    db_path = tmp_path / "chat.db"
    chat_client = TestClient(create_chat_app(tmp_path))
    mcp_client = TestClient(create_mcp_app(tmp_path))
    actors: list[DummyRayActor] = []
    launcher = DummyLauncher("gpt-5.5")

    def build_layer() -> RayGodSessionLayer:
        return RayGodSessionLayer(
            registry_path=tmp_path / "god_sessions.json",
            db_path=db_path,
            launchers={AgentRuntime.CODEX: launcher},
            actor_factory=lambda **kwargs: _actor_factory(actors, **kwargs),
        )

    layer = build_layer()

    created = chat_client.post("/api/chat/conversations", json={"title": "Full Chain Real Run"})
    assert created.status_code == 201
    conversation = created.json()
    conversation_id = conversation["id"]
    assert [participant["role"] for participant in conversation["participants"]] == [
        "architect",
        "review",
        "execute",
    ]
    bootstrap_path = tmp_path / conversation["bootstrap"]["artifact"]["path"]
    assert bootstrap_path.exists()

    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    init_sessions = [
        record
        for record in registry.list()
        if record.conversation_id == conversation_id and record.role == "init"
    ]
    assert len(init_sessions) == 1

    human_message = chat_client.post(
        f"/api/chat/conversations/{conversation_id}/messages",
        json={
            "author": "human-1",
            "role": "human",
            "content": "Need a chat-first mission plan with a guarded execution handoff.",
            "client_request_id": "full-chain-human-1",
        },
    )
    assert human_message.status_code == 201
    human_payload = human_message.json()
    assert human_payload["mentions"] == []
    assert len(human_payload["inbox_items"]) == 1
    assert human_payload["inbox_items"][0]["target_role"] == "architect"
    assert human_payload["inbox_items"][0]["item_type"] == "default_intake"

    architect, architect_session = await _ensure_session(
        layer,
        db_path=db_path,
        conversation_id=conversation_id,
        role="architect",
        worktree=tmp_path,
    )
    architect_binding = registry.get(architect_session.god_session_id).provider_session_id
    assert isinstance(architect_binding, str) and architect_binding

    architect_inbox = _mcp_call(
        mcp_client,
        "chat_read_inbox",
        {
            "conversation_id": conversation_id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
        },
    )
    assert [item["id"] for item in architect_inbox["inbox_items"]] == [
        human_payload["inbox_items"][0]["id"]
    ]

    architect_reply = _mcp_call(
        mcp_client,
        "chat_post_message",
        {
            "conversation_id": conversation_id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "architect-reply-1",
            "content": "I will draft the mission blueprint and route review once it is structured.",
            "reply_to_inbox_item_id": human_payload["inbox_items"][0]["id"],
        },
    )

    initial_blueprint = _mcp_call(
        mcp_client,
        "chat_emit_blueprint_proposal",
        {
            "conversation_id": conversation_id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "architect-blueprint-1",
            "title": "Chat-first mission",
            "body": "Route planning through architect first, then hand off only approved work.",
            "acceptance_criteria": [
                "Human unaddressed requests default to architect intake.",
                "Only approved structure can reach execution handoff.",
            ],
            "references": [human_payload["id"], architect_reply["message"]["id"]],
        },
    )
    initial_review_items = _review_inbox_items(db_path, conversation_id)
    assert len(initial_review_items) == 1
    assert initial_review_items[0].payload["reviewable_type"] == "mission_blueprint"

    approve_initial_blueprint = chat_client.post(
        f"/api/chat/proposals/{initial_blueprint['proposal']['id']}/approve",
        json={
            "approved_by": ["human-1"],
            "approval_mode": "manual",
            "goal_summary": "Approve initial mission blueprint",
        },
    )
    assert approve_initial_blueprint.status_code == 200
    approved_initial_blueprint_ref = approve_initial_blueprint.json()["content"]["blueprint_ref"]

    if restart_midway:
        layer = build_layer()
        _, resumed_architect_session = await _ensure_session(
            layer,
            db_path=db_path,
            conversation_id=conversation_id,
            role="architect",
            worktree=tmp_path,
        )
        assert resumed_architect_session.god_session_id == architect_session.god_session_id
        assert actors[-1].kwargs["resume_thread_id"] == architect_binding
        architect_session = resumed_architect_session

    review, review_session = await _ensure_session(
        layer,
        db_path=db_path,
        conversation_id=conversation_id,
        role="review",
        worktree=tmp_path,
    )
    review_inbox = _mcp_call(
        mcp_client,
        "chat_read_inbox",
        {
            "conversation_id": conversation_id,
            "participant_id": review.participant_id,
            "god_session_id": review_session.god_session_id,
        },
    )
    assert [item["id"] for item in review_inbox["inbox_items"]] == [initial_review_items[0].id]

    review_feedback = _mcp_call(
        mcp_client,
        "chat_mention",
        {
            "conversation_id": conversation_id,
            "participant_id": review.participant_id,
            "god_session_id": review_session.god_session_id,
            "client_request_id": "review-mention-1",
            "target_address": "@architect",
            "content": (
                "The mission needs a stricter blueprint: approved scope must block "
                "stale feature plans before execution handoff."
            ),
        },
    )
    assert len(review_feedback["inbox_items"]) == 1
    assert review_feedback["inbox_items"][0]["target_role"] == "architect"

    architect_followup_inbox = _mcp_call(
        mcp_client,
        "chat_read_inbox",
        {
            "conversation_id": conversation_id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
        },
    )
    assert review_feedback["inbox_items"][0]["id"] in {
        item["id"] for item in architect_followup_inbox["inbox_items"]
    }

    revised_blueprint = _mcp_call(
        mcp_client,
        "chat_emit_blueprint_proposal",
        {
            "conversation_id": conversation_id,
            "participant_id": architect.participant_id,
            "god_session_id": architect_session.god_session_id,
            "client_request_id": "architect-blueprint-2",
            "title": "Chat-first mission",
            "body": (
                "Route planning through architect first, require current approved blueprint "
                "before any authoritative feature plan can reach execution handoff."
            ),
            "acceptance_criteria": [
                "Human unaddressed requests default to architect intake.",
                "Stale feature plans are rejected against the latest approved blueprint.",
            ],
            "revises_blueprint_ref": approved_initial_blueprint_ref,
            "references": [review_feedback["message"]["id"]],
        },
    )

    review_items_after_revision = _review_inbox_items(db_path, conversation_id)
    assert len(review_items_after_revision) == 2

    approve_revision = chat_client.post(
        f"/api/chat/proposals/{revised_blueprint['proposal']['id']}/approve",
        json={
            "approved_by": ["human-1"],
            "approval_mode": "manual",
            "goal_summary": "Approve revised mission blueprint",
        },
    )
    assert approve_revision.status_code == 200
    approved_blueprint_ref = approve_revision.json()["content"]["blueprint_ref"]
    assert approve_revision.json()["content"]["revision_of"] == approved_initial_blueprint_ref

    stale_feature_plan = chat_client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "proposal",
            "content": json.dumps(
                {
                    "type": "feature_plan",
                    "source_blueprint_ref": approved_initial_blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-stale",
                            "title": "Stale feature",
                            "goal": "Should be rejected once the blueprint is revised.",
                            "acceptance_criteria": ["Reject stale source blueprint."],
                            "graph_id": "graph-stale",
                            "blueprint_refs": [approved_initial_blueprint_ref],
                        }
                    ],
                }
            ),
            "references": [approved_initial_blueprint_ref],
        },
    )
    assert stale_feature_plan.status_code == 400
    assert stale_feature_plan.json()["detail"]["code"] == "stale_feature_plan_blueprint"

    current_feature_plan = chat_client.post(
        f"/api/chat/conversations/{conversation_id}/proposals",
        json={
            "author": "human-1",
            "proposal_type": "feature_plan",
            "content": json.dumps(
                {
                    "type": "feature_plan",
                    "source_blueprint_ref": approved_blueprint_ref,
                    "features": [
                        {
                            "feature_id": "feature-schema",
                            "title": "Schema",
                            "goal": "Build the authoritative schema handoff.",
                            "acceptance_criteria": ["Schema feature is projected first."],
                            "graph_id": "graph-schema",
                            "blueprint_refs": [approved_blueprint_ref],
                        },
                        {
                            "feature_id": "feature-execution",
                            "title": "Execution",
                            "goal": "Hand the approved feature plan to execution safely.",
                            "acceptance_criteria": ["Execution handoff uses approved blueprint."],
                            "dependencies": ["feature-schema"],
                            "graph_id": "graph-execution",
                            "blueprint_refs": [approved_blueprint_ref],
                        },
                    ],
                }
            ),
            "references": [approved_blueprint_ref],
        },
    )
    assert current_feature_plan.status_code == 201
    feature_plan_payload = current_feature_plan.json()
    assert feature_plan_payload["proposal_type"] == "feature_plan"

    approved_feature_plan = chat_client.post(
        f"/api/chat/proposals/{feature_plan_payload['id']}/approve",
        json={
            "approved_by": ["human-1"],
            "approval_mode": "manual",
            "goal_summary": "Approve current feature plan",
        },
    )
    assert approved_feature_plan.status_code == 200
    assert approved_feature_plan.json()["content"]["source_blueprint_ref"] == approved_blueprint_ref

    lanes_doc = json.loads((tmp_path / "feature_lanes.json").read_text(encoding="utf-8"))
    assert [lane["feature_plan_feature_id"] for lane in lanes_doc["lanes"]] == ["feature-schema"]
    assert lanes_doc["lanes"][0]["feature_plan_id"] == feature_plan_payload["id"]
    assert (tmp_path / "feature_plans").exists()
    assert (tmp_path / "lane_graphs").exists()

    participant_roles = [
        participant.role
        for participant in ParticipantStore(db_path).list_by_conversation(conversation_id)
    ]
    assert sorted(participant_roles) == ["architect", "execute", "init", "review"]
    assert len(
        [
            item
            for item in ChatInboxStore(db_path).list_by_conversation(
                conversation_id,
                include_terminal=True,
            )
            if item.item_type == "default_intake"
        ]
    ) == 1

    return {
        "conversation_id": conversation_id,
        "architect_session_id": architect_session.god_session_id,
        "architect_binding": architect_binding,
        "actors": actors,
    }


@pytest.mark.asyncio
async def test_full_chain_real_run_fresh(tmp_path: Path) -> None:
    result = await _run_full_chain(tmp_path, restart_midway=False)

    assert result["architect_session_id"]
    assert result["architect_binding"]


@pytest.mark.asyncio
async def test_full_chain_real_run_with_restart_resume(tmp_path: Path) -> None:
    result = await _run_full_chain(tmp_path, restart_midway=True)

    resumed_actors = [
        actor for actor in result["actors"] if "resume_thread_id" in actor.kwargs
    ]
    assert len(resumed_actors) >= 1
    assert resumed_actors[0].kwargs["resume_thread_id"] == result["architect_binding"]


@pytest.mark.asyncio
async def test_real_runtime_restart_resume_smoke_with_fake_app_server(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "chat.db"
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    chat_port = _free_port()
    mcp_port = _free_port()
    actors: list[FakeProviderAppServerActor] = []

    class RuntimeLauncher(DummyLauncher):
        supports_persistent_sessions = True

    def fake_build_default_launchers(*, mcp_port: int):
        launcher = RuntimeLauncher("gpt-5.5")
        launcher.mcp_port = mcp_port
        return {AgentRuntime.CODEX: launcher}

    def fake_build_actor(self, **kwargs):
        del self
        actor = FakeProviderAppServerActor(**kwargs)
        actors.append(actor)
        return actor

    import xmuse_core.agents.launchers as launchers_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        fake_build_default_launchers,
    )
    monkeypatch.setattr(RayGodSessionLayer, "_build_actor", fake_build_actor)
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.delenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", raising=False)

    chat_server, chat_task = await _serve_app(create_chat_app(tmp_path), port=chat_port)
    mcp_server, mcp_task = await _serve_app(create_mcp_app(tmp_path), port=mcp_port)

    async def start_runner() -> asyncio.Task:
        return asyncio.create_task(
            platform_runner.run(
                lanes_path=lanes_path,
                xmuse_root=tmp_path,
                mcp_port=mcp_port,
                max_hours=1,
                max_concurrent=1,
                peer_chat_enabled=True,
            )
        )

    async def stop_runner(task: asyncio.Task) -> None:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=5)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    try:
        runner_task = await start_runner()
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{chat_port}") as client:
            created = await client.post(
                "/api/chat/conversations",
                json={"title": "Real runtime smoke"},
            )
            created.raise_for_status()
            conversation = created.json()
            conversation_id = conversation["id"]
            architect = next(
                participant
                for participant in conversation["participants"]
                if participant["role"] == "architect"
            )
            first = await client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={
                    "author": "human-1",
                    "role": "human",
                    "content": "remember runtime smoke constraint alpha",
                },
            )
            first.raise_for_status()
            await _wait_for_reply_count(
                db_path,
                conversation_id,
                architect["participant_id"],
                1,
            )
            await _wait_for_latency_trace_count(db_path, conversation_id, 1)
            second = await client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={
                    "author": "human-1",
                    "role": "human",
                    "content": "@architect repeat runtime smoke constraint",
                },
            )
            second.raise_for_status()
            await _wait_for_reply_count(
                db_path,
                conversation_id,
                architect["participant_id"],
                2,
            )
            await _wait_for_latency_trace_count(db_path, conversation_id, 2)

            architect_actors = [
                actor for actor in actors if actor.kwargs.get("role") == "architect"
            ]
            assert len(architect_actors) == 1
            first_thread_id = architect_actors[0]._thread_id
            assert len(architect_actors[0].sent) == 2
            assert architect_actors[0].streaming_deltas == ["delta:ack", "delta:ack"]

            await stop_runner(runner_task)
            runner_task = await start_runner()
            third = await client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={
                    "author": "human-1",
                    "role": "human",
                    "content": "@architect after restart, continue",
                },
            )
            third.raise_for_status()
            await _wait_for_reply_count(
                db_path,
                conversation_id,
                architect["participant_id"],
                3,
            )

        architect_actors = [
            actor for actor in actors if actor.kwargs.get("role") == "architect"
        ]
        assert len(architect_actors) == 2
        assert architect_actors[-1].kwargs["resume_thread_id"] == first_thread_id
        assert architect_actors[-1]._thread_id == first_thread_id

        registry = GodSessionRegistry(tmp_path / "god_sessions.json")
        architect_record = registry.find_by_conversation_participant(
            conversation_id,
            architect["participant_id"],
        )
        assert architect_record.provider_session_id == first_thread_id
        traces = await _wait_for_latency_trace_count(db_path, conversation_id, 3)
        assert {trace["delivery_mode"] for trace in traces} == {"mcp_writeback"}
        assert all(trace["degraded_reason"] is None for trace in traces)
        messages = ChatStore(db_path).list_messages(conversation_id)
        assert not any(
            message.envelope_json.get("degraded_reason") == "stdout_fallback"
            for message in messages
        )
    finally:
        if "runner_task" in locals():
            await stop_runner(runner_task)
        await _stop_server(chat_server, chat_task)
        await _stop_server(mcp_server, mcp_task)


@pytest.mark.asyncio
async def test_real_ray_codex_app_server_mcp_writeback_restart_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if shutil.which("codex") is None:
        pytest.skip("codex CLI is not installed")

    db_path = tmp_path / "chat.db"
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    chat_port = _free_port()
    mcp_port = _free_port()

    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.setenv("XMUSE_RAY_GOD_TRANSPORT", "app-server")
    monkeypatch.setenv("XMUSE_RAY_GOD_MCP", "1")
    monkeypatch.setenv("XMUSE_RAY_GOD_EFFORT", "low")
    monkeypatch.delenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", raising=False)

    chat_server, chat_task = await _serve_app(create_chat_app(tmp_path), port=chat_port)
    mcp_server, mcp_task = await _serve_app(create_mcp_app(tmp_path), port=mcp_port)

    async def start_runner() -> asyncio.Task:
        return asyncio.create_task(
            platform_runner.run(
                lanes_path=lanes_path,
                xmuse_root=tmp_path,
                mcp_port=mcp_port,
                max_hours=1,
                max_concurrent=1,
                peer_chat_enabled=True,
            )
        )

    async def stop_runner(task: asyncio.Task) -> None:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    try:
        runner_task = await start_runner()
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{chat_port}",
            timeout=30.0,
        ) as client:
            created = await client.post(
                "/api/chat/conversations",
                json={"title": "Real Codex MCP writeback"},
            )
            created.raise_for_status()
            conversation = created.json()
            conversation_id = conversation["id"]
            architect = next(
                participant
                for participant in conversation["participants"]
                if participant["role"] == "architect"
            )
            architect_id = architect["participant_id"]

            first = await client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={
                    "author": "human-1",
                    "role": "human",
                    "content": (
                        "Use chat_post_message to reply exactly: "
                        "real ray mcp fresh ok"
                    ),
                },
            )
            first.raise_for_status()
            await _wait_for_reply_count(
                db_path,
                conversation_id,
                architect_id,
                1,
                attempts=1800,
            )
            first_inbox_items = await _wait_for_read_inbox_count(
                db_path,
                conversation_id,
                architect_id,
                1,
                attempts=1800,
            )
            first_traces = await _wait_for_latency_trace_count(
                db_path,
                conversation_id,
                1,
                attempts=1800,
            )
            first_registry = GodSessionRegistry(tmp_path / "god_sessions.json")
            first_record = first_registry.find_by_conversation_participant(
                conversation_id,
                architect_id,
            )
            first_provider_session_id = first_record.provider_session_id
            assert first_provider_session_id

            await stop_runner(runner_task)
            runner_task = await start_runner()
            second = await client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={
                    "author": "human-1",
                    "role": "human",
                    "content": (
                        "@architect Use chat_post_message to reply exactly: "
                        "real ray mcp resume ok"
                    ),
                },
            )
            second.raise_for_status()
            await _wait_for_reply_count(
                db_path,
                conversation_id,
                architect_id,
                2,
                attempts=1800,
            )
            inbox_items = await _wait_for_read_inbox_count(
                db_path,
                conversation_id,
                architect_id,
                2,
                attempts=1800,
            )
            traces = await _wait_for_latency_trace_count(
                db_path,
                conversation_id,
                2,
                attempts=1800,
            )

        messages = ChatStore(db_path).list_messages(conversation_id)
        message_ids = {message.id for message in messages}
        assert all(item.responded_message_id in message_ids for item in inbox_items)
        _assert_real_provider_mcp_writeback_traces(traces)
        _assert_real_provider_mcp_writeback_traces(first_traces)
        assert all(item.responded_message_id in message_ids for item in first_inbox_items)
        assert not any(
            message.envelope_json.get("degraded_reason") == "stdout_fallback"
            for message in messages
        )

        registry = GodSessionRegistry(tmp_path / "god_sessions.json")
        architect_record = registry.find_by_conversation_participant(
            conversation_id,
            architect_id,
        )
        assert architect_record.provider_session_id == first_provider_session_id
        assert architect_record.provider_binding_status == "active"
        assert architect_record.provider_session_kind == "codex_app_server_thread"
        v12_report = _v12_latency_parity_report(
            traces,
            provider_session_id=architect_record.provider_session_id,
            provider_session_reused=architect_record.provider_session_id
            == first_provider_session_id,
        )
        _assert_v12_latency_parity_report(v12_report)
        print(
            "XMUSE_REAL_V12_LATENCY_PARITY_REPORT "
            + json.dumps(v12_report, sort_keys=True)
        )
    finally:
        if "runner_task" in locals():
            await stop_runner(runner_task)
        await _stop_server(chat_server, chat_task)
        await _stop_server(mcp_server, mcp_task)


@pytest.mark.asyncio
async def test_real_ray_codex_app_server_proposal_review_dispatch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if shutil.which("codex") is None:
        pytest.skip("codex CLI is not installed")

    db_path = tmp_path / "chat.db"
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    chat_port = _free_port()
    mcp_port = _free_port()

    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.setenv("XMUSE_RAY_GOD_TRANSPORT", "app-server")
    monkeypatch.setenv("XMUSE_RAY_GOD_MCP", "1")
    monkeypatch.setenv("XMUSE_RAY_GOD_EFFORT", "low")
    monkeypatch.delenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", raising=False)

    chat_server, chat_task = await _serve_app(create_chat_app(tmp_path), port=chat_port)
    mcp_server, mcp_task = await _serve_app(create_mcp_app(tmp_path), port=mcp_port)

    async def start_runner() -> asyncio.Task:
        return asyncio.create_task(
            platform_runner.run(
                lanes_path=lanes_path,
                xmuse_root=tmp_path,
                mcp_port=mcp_port,
                max_hours=1,
                max_concurrent=1,
                peer_chat_enabled=True,
            )
        )

    async def stop_runner(task: asyncio.Task) -> None:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    try:
        runner_task = await start_runner()
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{chat_port}",
            timeout=30.0,
        ) as client:
            created = await client.post(
                "/api/chat/conversations",
                json={"title": "Real Codex proposal review dispatch"},
            )
            created.raise_for_status()
            conversation = created.json()
            conversation_id = conversation["id"]
            participants = {
                participant["role"]: participant
                for participant in conversation["participants"]
            }
            architect_id = participants["architect"]["participant_id"]
            review_id = participants["review"]["participant_id"]

            collaboration = ChatCollaborationStore(db_path)
            run = collaboration.create_request(
                conversation_id=conversation_id,
                goal="Dispatch a bounded real-provider P2 lane after proposal review.",
                initiator="human",
                targets=["execute"],
                callback_target="architect",
                question="Confirm this one-lane P2 dispatch is executable.",
                context_refs=["test:p2-real-provider-proposal-review-dispatch"],
                idempotency_key="p2-real-provider-proposal-review-dispatch",
                timeout_s=480,
            )
            run = collaboration.record_response(
                run.run_id,
                target="execute",
                content=json.dumps(
                    {
                        "type": "execute_feasibility_verdict",
                        "status": "executable",
                        "summary": "The P2 lane is bounded to proposal review dispatch evidence.",
                        "evidence_refs": [
                            "test:p2-real-provider-proposal-review-dispatch"
                        ],
                    }
                ),
                response_status="received",
            )
            assert run.status.value == "done"

            request = await client.post(
                f"/api/chat/conversations/{conversation_id}/messages",
                json={
                    "author": "human-1",
                    "role": "human",
                    "content": (
                        "@architect Call the MCP tool chat_emit_proposal exactly once now. "
                        "Do not call chat_post_message. Use client_request_id "
                        "`p2-real-provider-proposal`, summary `P2 real provider dispatch "
                        "slice`, lanes exactly [{\"feature_id\":\"p2-real-provider-"
                        "dispatch-slice\",\"prompt\":\"Verify real provider proposal "
                        "review dispatch queue evidence.\",\"depends_on\":[],"
                        "\"capabilities\":[\"code\",\"test\"]}], and references exactly "
                        f"[\"collaboration:{run.run_id}\"]."
                    ),
                    "client_request_id": "p2-real-provider-human",
                },
            )
            request.raise_for_status()
            request_payload = request.json()
            inbox_item_id = request_payload["inbox_items"][0]["id"]

            proposals = await _wait_for_proposal_count(
                db_path,
                conversation_id,
                1,
                attempts=1800,
            )
            proposal = proposals[0]
            assert proposal.proposal_type == "lane_graph"
            assert proposal.references == [f"collaboration:{run.run_id}"]
            proposal_payload = json.loads(proposal.content)
            assert proposal_payload["lanes"][0]["feature_id"] == (
                "p2-real-provider-dispatch-slice"
            )
            await _wait_for_read_inbox_count(
                db_path,
                conversation_id,
                architect_id,
                1,
                attempts=1800,
            )
            traces = await _wait_for_latency_trace_count(
                db_path,
                conversation_id,
                1,
                attempts=1800,
            )
            proposal_trace = next(
                trace
                for trace in traces
                if trace["inbox_item_id"] == inbox_item_id
            )
            assert proposal_trace["delivery_mode"] == "mcp_writeback"
            assert proposal_trace.get("degraded_reason") in {
                None,
                "peer_writeback_before_provider_result",
            }
            stages = proposal_trace.get("stage_timings")
            assert isinstance(stages, dict)
            assert "chat_emit_proposal" in stages

            review_items = await _wait_for_review_trigger_count(
                db_path,
                conversation_id,
                1,
                attempts=1800,
            )
            registry = GodSessionRegistry(tmp_path / "god_sessions.json")
            review_session = registry.find_by_conversation_participant(
                conversation_id=conversation_id,
                participant_id=review_id,
            )
            assert review_session is not None
            async with httpx.AsyncClient(timeout=30.0) as mcp_client:
                review_message = await _http_mcp_call(
                    mcp_client,
                    f"http://127.0.0.1:{mcp_port}/mcp",
                    "chat_post_message",
                    {
                        "conversation_id": conversation_id,
                        "participant_id": review_id,
                        "god_session_id": review_session.god_session_id,
                        "client_request_id": "p2-real-provider-review",
                        "content": (
                            "Review verdict: dispatch allowed. The proposal is backed "
                            "by executable collaboration evidence."
                        ),
                        "reply_to_inbox_item_id": review_items[0].id,
                    },
                )
            review_item = ChatInboxStore(db_path).get(review_items[0].id)
            assert review_item.status == "read"
            assert review_item.responded_message_id == review_message["message"]["id"]

            await stop_runner(runner_task)

            approved = await client.post(
                f"/api/chat/proposals/{proposal.id}/approve",
                json={
                    "approved_by": ["human-1"],
                    "approval_mode": "manual",
                    "goal_summary": "Approve P2 real provider dispatch slice",
                },
            )
            approved.raise_for_status()
            entries = await _wait_for_dispatch_entry_count(
                db_path,
                conversation_id,
                1,
            )
            assert entries[0].status == "queued"
            assert entries[0].proposal_id == proposal.id
            assert entries[0].collaboration_run_id == run.run_id

            report = {
                "conversation_id": conversation_id,
                "proposal_id": proposal.id,
                "resolution_id": approved.json()["id"],
                "dispatch_entry_id": entries[0].entry_id,
                "provider_session_kind": registry.find_by_conversation_participant(
                    conversation_id,
                    architect_id,
                ).provider_session_kind,
                "delivery_mode": proposal_trace["delivery_mode"],
                "observed_stages": sorted(stages),
            }
            print("XMUSE_REAL_P2_PROPOSAL_DISPATCH_REPORT " + json.dumps(report, sort_keys=True))
    finally:
        if "runner_task" in locals() and not runner_task.done():
            await stop_runner(runner_task)
        await _stop_server(chat_server, chat_task)
        await _stop_server(mcp_server, mcp_task)


@pytest.mark.asyncio
async def test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if shutil.which("codex") is None:
        pytest.skip("codex CLI is not installed")

    db_path = tmp_path / "chat.db"
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    chat_port = _free_port()
    mcp_port = _free_port()

    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.setenv("XMUSE_RAY_GOD_TRANSPORT", "app-server")
    monkeypatch.setenv("XMUSE_RAY_GOD_MCP", "1")
    monkeypatch.setenv("XMUSE_RAY_GOD_EFFORT", "low")
    monkeypatch.delenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", raising=False)

    chat_server, chat_task = await _serve_app(create_chat_app(tmp_path), port=chat_port)
    mcp_server, mcp_task = await _serve_app(create_mcp_app(tmp_path), port=mcp_port)

    async def start_runner() -> asyncio.Task:
        return asyncio.create_task(
            platform_runner.run(
                lanes_path=lanes_path,
                xmuse_root=tmp_path,
                mcp_port=mcp_port,
                max_hours=1,
                max_concurrent=1,
                peer_chat_enabled=True,
            )
        )

    async def stop_runner(task: asyncio.Task) -> None:
        task.cancel()
        try:
            await asyncio.wait_for(task, timeout=10)
        except (TimeoutError, asyncio.CancelledError):
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    try:
        runner_task = await start_runner()
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{chat_port}",
            timeout=30.0,
        ) as client:
            created = await client.post(
                "/api/chat/conversations",
                json={"title": "Real Codex MCP writeback soak"},
            )
            created.raise_for_status()
            conversation = created.json()
            conversation_id = conversation["id"]
            architect = next(
                participant
                for participant in conversation["participants"]
                if participant["role"] == "architect"
            )
            architect_id = architect["participant_id"]

            traces: list[dict[str, object]] = []
            for turn_index in range(1, 6):
                traces = await _post_architect_turn_and_wait(
                    client,
                    db_path=db_path,
                    conversation_id=conversation_id,
                    architect_id=architect_id,
                    turn_index=turn_index,
                    content=(
                        "@architect Use chat_post_message to reply exactly: "
                        f"real ray mcp soak fresh {turn_index} ok"
                    ),
                )

            registry = GodSessionRegistry(tmp_path / "god_sessions.json")
            first_record = registry.find_by_conversation_participant(
                conversation_id,
                architect_id,
            )
            first_provider_session_id = first_record.provider_session_id
            assert first_provider_session_id

            await stop_runner(runner_task)
            runner_task = await start_runner()

            for turn_index in range(6, 9):
                traces = await _post_architect_turn_and_wait(
                    client,
                    db_path=db_path,
                    conversation_id=conversation_id,
                    architect_id=architect_id,
                    turn_index=turn_index,
                    content=(
                        "@architect Use chat_post_message to reply exactly: "
                        f"real ray mcp soak resume {turn_index - 5} ok"
                    ),
                )

        messages = ChatStore(db_path).list_messages(conversation_id)
        message_ids = {message.id for message in messages}
        inbox_items = await _wait_for_read_inbox_count(
            db_path,
            conversation_id,
            architect_id,
            8,
            attempts=1,
        )
        assert all(item.responded_message_id in message_ids for item in inbox_items)
        assert len(traces) >= 8
        traces = traces[:8]
        _assert_real_provider_mcp_writeback_traces(traces)
        assert not any(
            message.envelope_json.get("degraded_reason") == "stdout_fallback"
            for message in messages
        )
        for trace in traces:
            stages = trace["stage_timings"]
            assert isinstance(stages, dict)
            assert "inbox_claim" in stages
            assert "ray_actor_delivery_start" in stages
            assert "first_visible" in stages
            assert "codex_app_server_turn_start" in stages
            assert "chat_post_message" in stages
            assert "scheduler_observed_result" in stages
            assert "trace_persisted" in stages

        registry = GodSessionRegistry(tmp_path / "god_sessions.json")
        architect_record = registry.find_by_conversation_participant(
            conversation_id,
            architect_id,
        )
        assert architect_record.provider_session_id == first_provider_session_id
        assert architect_record.provider_binding_status == "active"
        assert architect_record.provider_session_kind == "codex_app_server_thread"
        v12_report = _v12_latency_parity_report(
            traces,
            provider_session_id=architect_record.provider_session_id,
            provider_session_reused=architect_record.provider_session_id
            == first_provider_session_id,
        )
        _assert_v12_latency_parity_report(v12_report)

        print(
            "XMUSE_REAL_SOAK_LATENCY_REPORT "
            + json.dumps(_latency_soak_report(traces), sort_keys=True)
        )
    finally:
        if "runner_task" in locals():
            await stop_runner(runner_task)
        await _stop_server(chat_server, chat_task)
        await _stop_server(mcp_server, mcp_task)
