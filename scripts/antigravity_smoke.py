#!/usr/bin/env python3
"""One-shot live smoke of the Antigravity agentapi Room participant path.

This is not part of CI.  It spawns the operator's real ``agentapi`` CLI against
the running Antigravity language server and lets one tiny Human turn complete
end-to-end through the durable Room host.  The Room MCP app must listen on
``127.0.0.1:8100`` because the global Antigravity MCP configuration mounts
``xmuse-room`` through a stdio wrapper pointing at exactly that URL; the script
fails fast when the port is owned by someone else.

It owns a fresh temporary ``XMUSE_ROOT`` and brain-independent state, prints
timed delivery evidence, the projected Room timeline, and a transcript excerpt
of the provider conversation, and always terminates the agentapi children
before exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import socket
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from xmuse.room_mcp_server import create_app
from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_agent_stream import RoomAgentStreamCache, RoomAgentStreamProjector
from xmuse_core.chat.room_antigravity_transport import (
    ROOM_ANTIGRAVITY_DEFAULT_MODEL,
    AntigravityRoomObservationTransport,
    AntigravityTransportConfig,
    RoomAntigravityTransportError,
    discover_antigravity_language_server_env,
    read_antigravity_transcript_steps,
    resolve_antigravity_agentapi_path,
    resolve_antigravity_brain_dir,
)
from xmuse_core.chat.room_api_models import ParticipantInit, RoomConversationCreate
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_host import (
    RoomHostDeliveryOutcome,
    RoomHostPolicy,
    RoomParticipantHost,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_projection import build_room_chat_projection
from xmuse_core.chat.room_setup import RoomSetupService
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

HUMAN_PROMPT = "Reply with one short sentence: what is 2+2?"
ANTIGRAVITY_MODEL = ROOM_ANTIGRAVITY_DEFAULT_MODEL
ROOM_MCP_PORT_ENV = "XMUSE_ANTIGRAVITY_SMOKE_PORT"
DEFAULT_ROOM_MCP_PORT = 8100
DEFAULT_TIMEOUT_S = 240.0
DELIVERY_TIMEOUT_S = 180.0
CLEANUP_GRACE_S = 8.0
LEASE_TTL_S = 300.0

_START = time.monotonic()


def _mark(event: str, **fields: object) -> None:
    elapsed = time.monotonic() - _START
    detail = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    print(f"[smoke {elapsed:8.2f}s] {event} {detail}", flush=True)


class _RoomMcpPortBusyError(RuntimeError):
    pass


@contextmanager
def _serve_room_mcp(root: Path, port: int) -> Iterator[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", port))
    except OSError as exc:
        sock.close()
        raise _RoomMcpPortBusyError(
            f"127.0.0.1:{port} is already owned by another process; the Antigravity "
            f"global MCP config expects the xmuse-room HTTP endpoint exactly there. "
            f"Stop the current owner and retry (bind error: {exc})"
        ) from exc
    sock.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(root),
            host="127.0.0.1",
            port=port,
            log_level="warning",
            access_log=False,
            ws="none",
        )
    )
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline or not thread.is_alive():
            raise RuntimeError("room mcp server did not start")
        time.sleep(0.01)
    url = f"http://127.0.0.1:{port}/mcp/room"
    _mark("room_mcp_ready", url=url)
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


async def _run_smoke(
    *,
    root: Path,
    mcp_url: str,
    agentapi: Path,
    brain_dir: Path,
    timeout_s: float,
) -> int:
    _mark(
        "root",
        path=str(root),
        agentapi=str(agentapi),
        brain_dir=str(brain_dir),
    )
    RoomDatabase(root / "chat.db").initialize()

    setup = RoomSetupService(root).create_conversation(
        RoomConversationCreate(
            title="Antigravity smoke",
            client_request_id=f"antigravity-smoke-{uuid.uuid4().hex}",
            initial_participants=[
                ParticipantInit(
                    role="review",
                    display_name="Antigravity Reviewer",
                    cli_kind="antigravity",
                    model=ANTIGRAVITY_MODEL,
                )
            ],
        )
    )
    conversation_id = str(setup["id"])
    participant = next(
        item
        for item in ParticipantStore(root / "chat.db").list_by_conversation(conversation_id)
        if item.cli_kind == "antigravity"
    )
    _mark(
        "room_created",
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        cli_kind=participant.cli_kind,
        model=participant.model,
    )

    kernel = RoomKernelStore(root / "chat.db")
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content=HUMAN_PROMPT,
        client_request_id=f"antigravity-smoke-human-{uuid.uuid4().hex}",
    )
    _mark("human_posted", content=HUMAN_PROMPT)

    controls = RoomObservationControlStore(root / "chat.db")
    decisions = RoomAttemptSkillDecisionStore(root / "chat.db")
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(root))
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    transport = AntigravityRoomObservationTransport(
        config=AntigravityTransportConfig(
            workspace=workspace,
            agentapi_command=(str(agentapi),),
            brain_dir=brain_dir,
            shutdown_grace_s=CLEANUP_GRACE_S,
        ),
        registry_path=root / "god_sessions.json",
        control_store=controls,
        skill_decision_store=decisions,
        stream_projector=projector,
    )
    host = RoomParticipantHost(
        root / "chat.db",
        transport,
        policy=RoomHostPolicy(
            delivery_timeout_s=DELIVERY_TIMEOUT_S,
            cleanup_grace_s=CLEANUP_GRACE_S,
            lease_ttl_s=LEASE_TTL_S,
            participant_cooldown_s=0.0,
        ),
        control_store=controls,
        skill_catalog=SkillCatalog.load_bundled(),
        skill_decision_store=decisions,
    )

    final: RoomHostDeliveryOutcome | None = None
    try:
        await projector.start()
        _mark("pump_start", timeout_s=timeout_s)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            result = await host.pump_once(conversation_id=conversation_id)
            for item in result.deliveries:
                _mark(
                    "delivery",
                    participant_id=item.participant_id,
                    state=item.state,
                    reason=item.reason,
                    attempt_count=item.attempt_count,
                    transport_status=item.transport_status,
                    outcome_type=item.outcome_type,
                    diagnostic_text=getattr(item, "diagnostic_text", None),
                )
                final = item
            if final is not None:
                break
            _mark("no_work", observations=_observation_states(kernel, conversation_id))
            await asyncio.sleep(0.25)
    finally:
        await transport.aclose()
        await projector.shutdown()

    record = _print_evidence(root, conversation_id, participant.participant_id)
    _print_transcript_evidence(brain_dir, record)
    if final is not None and final.state == "completed":
        items = [
            item
            for item in build_room_chat_projection(conversation_id, root)["timeline_items"]
            if item["actor"]["kind"] != "human"
        ]
        ok = bool(items) and bool(str(items[-1]["content"]).strip())
        _mark("smoke_result", ok=ok)
        return 0 if ok else 1
    _mark("smoke_result", ok=False, state=(final.state if final else "no_delivery"))
    return 1


def _observation_states(kernel: RoomKernelStore, conversation_id: str) -> list[dict[str, object]]:
    return [
        {
            "participant_id": item["participant_id"],
            "status": item["status"],
            "attempt_count": item["attempt_count"],
        }
        for item in kernel.list_observations(conversation_id)
    ]


def _print_evidence(
    root: Path, conversation_id: str, participant_id: str
) -> GodSessionRecord | None:
    projection = build_room_chat_projection(conversation_id, root)
    for item in projection["timeline_items"]:
        actor = item["actor"]
        _mark(
            "timeline_item",
            kind=item["kind"],
            room_seq=item["room_seq"],
            actor_kind=actor["kind"],
            actor_name=actor["display_name"],
            role=actor["role"],
            content=item["content"],
        )
    for item in projection["participants"]:
        outcome = item.get("last_completed_outcome") or {}
        _mark(
            "participant_state",
            display_name=item["display_name"],
            role=item["role"],
            state=item["state"],
            last_outcome_type=outcome.get("outcome_type"),
        )
    try:
        record = GodSessionRegistry(root / "god_sessions.json").find_by_conversation_participant(
            conversation_id,
            participant_id,
            feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        )
    except Exception as exc:  # evidence only; absence is reported, not raised
        _mark("god_session_unavailable", error=f"{type(exc).__name__}: {exc}")
        return None
    _mark(
        "god_session",
        provider_session_kind=record.provider_session_kind,
        provider_session_id=record.provider_session_id,
        provider_binding_status=record.provider_binding_status,
        provider_binding_failure_reason=record.provider_binding_failure_reason,
    )
    return record


def _print_transcript_evidence(brain_dir: Path, record: object) -> None:
    conversation_id = getattr(record, "provider_session_id", None)
    if not conversation_id:
        _mark("transcript_evidence_unavailable", reason="no provider session id recorded")
        return
    steps = read_antigravity_transcript_steps(brain_dir, conversation_id)
    if steps is None:
        _mark(
            "transcript_evidence_unavailable",
            conversation_id=conversation_id,
            reason="no transcript file under the brain dir",
        )
        return
    _mark("transcript_evidence", conversation_id=conversation_id, step_count=len(steps))
    for step in steps[-6:]:
        tool_calls = step.get("tool_calls")
        tool_names = (
            [str(call.get("name")) for call in tool_calls if isinstance(call, dict)]
            if isinstance(tool_calls, list)
            else []
        )
        content = step.get("content")
        _mark(
            "transcript_step",
            step_index=step.get("step_index"),
            type=step.get("type"),
            status=step.get("status"),
            tool_names=tool_names,
            content=(str(content)[:240] if content else None),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="defaults to a fresh tmp dir")
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get(ROOM_MCP_PORT_ENV, DEFAULT_ROOM_MCP_PORT)),
        help=(
            "Room MCP port; it must match the global Antigravity MCP config "
            f"(default {DEFAULT_ROOM_MCP_PORT})"
        ),
    )
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    agentapi = resolve_antigravity_agentapi_path()
    if not agentapi.expanduser().exists():
        print(f"agentapi not found at {agentapi}; set XMUSE_ANTIGRAVITY_AGENTAPI", flush=True)
        return 2
    brain_dir = resolve_antigravity_brain_dir()
    try:
        ls_env = discover_antigravity_language_server_env(os.environ)
    except RoomAntigravityTransportError as exc:
        print(f"Antigravity language server unavailable: {exc}", flush=True)
        return 2
    _mark(
        "language_server",
        address=ls_env["ANTIGRAVITY_LS_ADDRESS"],
        has_csrf_token=bool(ls_env.get("ANTIGRAVITY_CSRF_TOKEN")),
    )

    root = args.root or Path(tempfile.mkdtemp(prefix="xmuse-antigravity-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    try:
        with _serve_room_mcp(root, args.port) as mcp_url:
            return asyncio.run(
                _run_smoke(
                    root=root,
                    mcp_url=mcp_url,
                    agentapi=agentapi,
                    brain_dir=brain_dir,
                    timeout_s=args.timeout,
                )
            )
    except _RoomMcpPortBusyError as exc:
        print(str(exc), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
