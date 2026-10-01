#!/usr/bin/env python3
"""One-shot live smoke of the Claude ACP Room participant path.

This is not part of CI.  It spawns the real ``claude-agent-acp`` bridge against
the operator's existing Claude login and lets one tiny Human turn complete
end-to-end through the durable Room host.  It owns a fresh temporary
``XMUSE_ROOT``, serves the real Room MCP app on an ephemeral loopback port,
prints timed delivery evidence and the projected Room timeline, and always
terminates the agent child process before exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import shlex
import tempfile
import threading
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path

import uvicorn

from xmuse.room_mcp_server import create_app
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_acp_transport import (
    ROOM_ACP_DEFAULT_COMMAND,
    AcpRoomObservationTransport,
    AcpTransportConfig,
)
from xmuse_core.chat.room_agent_stream import RoomAgentStreamCache, RoomAgentStreamProjector
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
CLAUDE_MODEL = "claude-acp-default"
COMMAND_ENV = "XMUSE_CLAUDE_ACP_COMMAND"
DEFAULT_TIMEOUT_S = 180.0
DELIVERY_TIMEOUT_S = 150.0
CLEANUP_GRACE_S = 8.0
LEASE_TTL_S = 240.0

_START = time.monotonic()


def _mark(event: str, **fields: object) -> None:
    elapsed = time.monotonic() - _START
    detail = json.dumps(fields, ensure_ascii=False, sort_keys=True, default=str)
    print(f"[smoke {elapsed:8.2f}s] {event} {detail}", flush=True)


@contextmanager
def _serve_room_mcp(root: Path) -> Iterator[str]:
    server = uvicorn.Server(
        uvicorn.Config(
            create_app(root),
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
    url = f"http://127.0.0.1:{port}/mcp/room"
    _mark("room_mcp_ready", url=url)
    try:
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def _resolve_command(override: str | None, environ: Mapping[str, str]) -> tuple[str, ...]:
    raw = (override or environ.get(COMMAND_ENV) or "").strip()
    if not raw:
        return ROOM_ACP_DEFAULT_COMMAND
    command = tuple(shlex.split(raw))
    if not command:
        raise ValueError("claude acp command override is empty")
    return command


async def _run_smoke(
    *,
    root: Path,
    mcp_url: str,
    command: tuple[str, ...],
    timeout_s: float,
) -> int:
    _mark("root", path=str(root), command=list(command))
    RoomDatabase(root / "chat.db").initialize()

    setup = RoomSetupService(root).create_conversation(
        RoomConversationCreate(
            title="Claude ACP smoke",
            client_request_id=f"claude-acp-smoke-{uuid.uuid4().hex}",
            initial_participants=[
                ParticipantInit(
                    role="review",
                    display_name="Claude Reviewer",
                    cli_kind="claude",
                    model=CLAUDE_MODEL,
                )
            ],
        )
    )
    conversation_id = str(setup["id"])
    participant = next(
        item
        for item in ParticipantStore(root / "chat.db").list_by_conversation(conversation_id)
        if item.cli_kind == "claude"
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
        client_request_id=f"claude-acp-smoke-human-{uuid.uuid4().hex}",
    )
    _mark("human_posted", content=HUMAN_PROMPT)

    controls = RoomObservationControlStore(root / "chat.db")
    decisions = RoomAttemptSkillDecisionStore(root / "chat.db")
    projector = RoomAgentStreamProjector(RoomAgentStreamCache(root))
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    transport = AcpRoomObservationTransport(
        config=AcpTransportConfig(
            workspace=workspace,
            command=command,
            room_mcp_url=mcp_url,
            initialize_timeout_s=90.0,
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
                )
                final = item
            if final is not None:
                break
            _mark("no_work", observations=_observation_states(kernel, conversation_id))
            await asyncio.sleep(0.25)
    finally:
        await transport.aclose()
        await projector.shutdown()

    _print_evidence(root, conversation_id, participant.participant_id)
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


def _print_evidence(root: Path, conversation_id: str, participant_id: str) -> None:
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
        return
    _mark(
        "god_session",
        provider_session_kind=record.provider_session_kind,
        provider_session_id=record.provider_session_id,
        provider_binding_status=record.provider_binding_status,
        provider_binding_failure_reason=record.provider_binding_failure_reason,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=None, help="defaults to a fresh tmp dir")
    parser.add_argument("--command", default=None, help=f"overrides {COMMAND_ENV}")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        command = _resolve_command(args.command, os.environ)
    except ValueError as exc:
        print(f"invalid {COMMAND_ENV}: {exc}", flush=True)
        return 2
    root = args.root or Path(tempfile.mkdtemp(prefix="xmuse-claude-acp-smoke-"))
    root.mkdir(parents=True, exist_ok=True)
    with _serve_room_mcp(root) as mcp_url:
        return asyncio.run(
            _run_smoke(root=root, mcp_url=mcp_url, command=command, timeout_s=args.timeout)
        )


if __name__ == "__main__":
    raise SystemExit(main())
