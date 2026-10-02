#!/usr/bin/env python3
"""One-shot live smoke of the heterogeneous Claude + Antigravity Duo Room.

This is not part of CI.  It owns a fresh temporary ``XMUSE_ROOT``, serves the
real Room MCP on 127.0.0.1:8100 (the pinned port Antigravity's global MCP
configuration expects), starts the real Room Runner through the supervisor with
``XMUSE_CLAUDE_ACP=1`` and ``XMUSE_ANTIGRAVITY=1`` forwarded to the runner child
only, creates a ``builtin.heterogeneous-duo`` Room (Claude "Product Lead" +
Antigravity "Researcher", addressed collaboration), posts exactly one Human
message that addresses the lead and requests a handoff to the researcher, then
polls the durable Room projection until the turn settles or the timeout expires.
It prints the projected timeline with per-turn timings and always stops the
managed runtime before exit.
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
import tempfile
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.mentions import MentionResolver, normalize_address
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_api_models import RoomConversationCreate
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_projection import build_room_chat_projection
from xmuse_core.chat.room_runtime_supervisor import (
    RoomRuntimeStartError,
    RoomRuntimeSupervisorConfig,
    ensure_room_runtime,
    stop_room_runtime,
)
from xmuse_core.chat.room_setup import RoomSetupService

REPO_ROOT = Path(__file__).resolve().parents[1]
TEMPLATE_ID = "builtin.heterogeneous-duo"
MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8100
DEFAULT_TIMEOUT_S = 420.0
POLL_INTERVAL_S = 0.4
LOG_TAIL_LINES = 60
HUMAN_PROMPT_SUFFIX = (
    "Plan a 3-step approach to add input validation to a small JSON API. "
    "Hand off to the researcher for a one-paragraph survey of common validation "
    "pitfalls first, then summarize."
)


def _mark(event: str, **fields: Any) -> None:
    print(
        json.dumps({"event": event, **fields}, ensure_ascii=False, separators=(",", ":")),
        flush=True,
    )


def _port_busy(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        try:
            return probe.connect_ex((host, port)) == 0
        except OSError:
            return False


def _tail(path: Path, lines: int) -> list[str]:
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return content.splitlines()[-lines:]


def _item_summary(item: dict[str, Any], *, timing_s: float | None = None) -> dict[str, Any]:
    actor = item.get("actor") or {}
    note = item.get("handoff_note")
    summary: dict[str, Any] = {
        "kind": item.get("kind"),
        "room_seq": item.get("room_seq"),
        "actor": f"{actor.get('display_name')} ({actor.get('kind')}/{actor.get('role')})",
        "addressing": item.get("addressing"),
        "handoff_targets": item.get("handoff_targets") or [],
        "handoff_note_present": bool(isinstance(note, dict) and note),
        "handoff_note_keys": sorted(note) if isinstance(note, dict) else [],
        "causal_depth": item.get("causal_depth"),
        "correlation_id": item.get("correlation_id"),
        "created_at": item.get("created_at"),
        "content_preview": str(item.get("content") or "")[:120],
    }
    if timing_s is not None:
        summary["observed_after_human_s"] = round(timing_s, 2)
    return summary


def _turn_summary(turn: dict[str, Any]) -> dict[str, Any]:
    return {
        "correlation_id": turn.get("correlation_id"),
        "status": turn.get("status"),
        "attempt_count": turn.get("attempt_count"),
        "observation_count": turn.get("observation_count"),
        "root_room_seq": turn.get("root_room_seq"),
        "participants": [
            {
                "name": member.get("display_name"),
                "role": member.get("role"),
                "state": member.get("state"),
                "unresolved_count": member.get("unresolved_count"),
                "response_count": member.get("response_count"),
                "observation_status": (member.get("frontier") or {}).get("status"),
                "control_state": (member.get("frontier") or {}).get("control_state"),
                "recovery_state": (
                    ((member.get("frontier") or {}).get("current_attempt") or {}).get("recovery")
                    or {}
                ).get("state"),
                "recovery_reason": (
                    ((member.get("frontier") or {}).get("current_attempt") or {}).get("recovery")
                    or {}
                ).get("reason_code"),
                "outcome_type": (member.get("latest_outcome") or {}).get("outcome_type"),
                "outcome_completed_at": (member.get("latest_outcome") or {}).get("completed_at"),
            }
            for member in turn.get("participants") or []
        ],
    }


def _parse_stamp(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _created_delta_s(root_stamp: Any, item_stamp: Any) -> float | None:
    root_time = _parse_stamp(root_stamp)
    item_time = _parse_stamp(item_stamp)
    if root_time is None or item_time is None:
        return None
    return (item_time - root_time).total_seconds()


def _pump(
    *,
    root: Path,
    conversation_id: str,
    root_activity_seq: int,
    timeout_s: float,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]], bool, dict[str, Any]]:
    """Poll the durable projection until the Human turn settles or time expires."""

    started = time.monotonic()
    seen: dict[int, dict[str, Any]] = {}
    last_status: str | None = None
    settled = False
    projection: dict[str, Any] = {}
    root_stamp: Any = None
    while True:
        elapsed = time.monotonic() - started
        projection = build_room_chat_projection(conversation_id, root)
        items = projection.get("timeline_items") or []
        for item in items:
            seq = int(item["room_seq"])
            if seq in seen:
                continue
            if seq == root_activity_seq:
                root_stamp = item.get("created_at")
            seen[seq] = item
            _mark(
                "timeline_item",
                timing_s=round(elapsed, 2),
                **_item_summary(item, timing_s=elapsed),
            )
        turns = projection.get("turns") or []
        human_turn = next(
            (turn for turn in turns if int(turn.get("root_room_seq") or -1) == root_activity_seq),
            None,
        )
        if human_turn is not None:
            status = str(human_turn.get("status"))
            if status != last_status:
                _mark("turn_status", **{**_turn_summary(human_turn)})
                last_status = status
            if status == "settled":
                settled = True
                break
            if status == "attention":
                _mark(
                    "turn_attention",
                    note="turn needs operator attention; stop waiting",
                    elapsed_s=round(elapsed, 2),
                )
                break
        if elapsed >= timeout_s:
            _mark("pump_timeout", elapsed_s=round(elapsed, 2))
            break
        time.sleep(POLL_INTERVAL_S)
    for item in seen.values():
        item["_root_created_delta_s"] = _created_delta_s(root_stamp, item.get("created_at"))
    return seen, turns, settled, projection


def _handoff_chain(items: list[dict[str, Any]]) -> tuple[bool, bool, list[str]]:
    handoff_index: int | None = None
    targets: list[str] = []
    for index, item in enumerate(items):
        if (item.get("actor") or {}).get("kind") == "human":
            continue
        item_targets = [str(value) for value in item.get("handoff_targets") or []]
        note = item.get("handoff_note")
        is_handoff = item.get("kind") == "handoff" or bool(item_targets)
        if is_handoff and (item_targets or isinstance(note, dict)):
            handoff_index = index
            targets = item_targets
            break
    if handoff_index is None:
        return False, False, []
    researcher_responded = any(
        (item.get("actor") or {}).get("kind") != "human"
        and (item.get("actor") or {}).get("role") == "research"
        and str(item.get("content") or "").strip()
        for item in items[handoff_index + 1 :]
    )
    return True, researcher_responded, targets


def _print_final_timeline(seen: dict[int, dict[str, Any]]) -> None:
    _mark("final_timeline")
    for seq in sorted(seen):
        item = seen[seq]
        _mark(
            "final_item",
            created_delta_s=(
                round(item["_root_created_delta_s"], 2)
                if item.get("_root_created_delta_s") is not None
                else None
            ),
            **_item_summary(item),
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mcp-port", type=int, default=DEFAULT_MCP_PORT)
    parser.add_argument("--timeout-s", type=float, default=DEFAULT_TIMEOUT_S)
    args = parser.parse_args()

    if _port_busy(MCP_HOST, args.mcp_port):
        _mark(
            "port_busy",
            host=MCP_HOST,
            port=args.mcp_port,
            note="another process already serves the pinned Room MCP port",
        )
        return 2

    root = Path(tempfile.mkdtemp(prefix="xmuse-hetero-smoke-"))
    workspace = root / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    _mark("root", path=str(root))
    RoomDatabase(root / "chat.db").initialize()

    setup = RoomSetupService(root).create_conversation(
        RoomConversationCreate(
            title="Heterogeneous duo smoke",
            client_request_id=f"hetero-smoke-setup-{uuid.uuid4().hex}",
            roster_template_id=TEMPLATE_ID,
        )
    )
    conversation_id = str(setup["id"])
    setup_meta = setup.get("setup")
    collaboration = setup_meta.get("collaboration") if isinstance(setup_meta, dict) else None
    participants = ParticipantStore(root / "chat.db").list_by_conversation(conversation_id)
    lead = next(item for item in participants if item.role == "architect")
    researcher = next(item for item in participants if item.role == "research")
    _mark(
        "room_created",
        conversation_id=conversation_id,
        roster_template_id=TEMPLATE_ID,
        collaboration=collaboration,
        participants=[
            {
                "participant_id": item.participant_id,
                "role": item.role,
                "display_name": item.display_name,
                "cli_kind": item.cli_kind,
                "model": item.model,
            }
            for item in participants
        ],
    )

    content = f"{normalize_address(lead.display_name)} {HUMAN_PROMPT_SUFFIX}"
    resolver = MentionResolver(ParticipantStore(root / "chat.db"))
    mentions = resolver.resolve_content(conversation_id, content, strict=False)
    if not any(item.participant.participant_id == lead.participant_id for item in mentions):
        _mark(
            "mention_unresolved",
            content=content,
            resolved=[item.normalized for item in mentions],
            note="the Human root would not address the lead",
        )
        return 1
    if any(item.participant.participant_id == researcher.participant_id for item in mentions):
        _mark(
            "mention_unexpected",
            content=content,
            resolved=[item.normalized for item in mentions],
            note="the Human root must address only the lead",
        )
        return 1
    kernel = RoomKernelStore(root / "chat.db")
    result = kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="Human operator",
        content=content,
        client_request_id=f"hetero-smoke-human-{uuid.uuid4().hex}",
        mentions=[item.participant.participant_id for item in mentions],
        display_mentions=[item.normalized for item in mentions],
    )
    root_activity_seq = int(result["activity"]["seq"])
    pending = [
        {
            "participant_id": item["participant_id"],
            "status": item["status"],
        }
        for item in kernel.list_observations(conversation_id)
        if item["status"] == "pending"
    ]
    _mark(
        "human_posted",
        content=content,
        root_room_seq=root_activity_seq,
        addressed=[item.normalized for item in mentions],
        pending_observations=pending,
    )

    config = RoomRuntimeSupervisorConfig(
        repo_root=REPO_ROOT,
        xmuse_root=root,
        execution_worktree=workspace,
        generation=f"hetero-smoke-{uuid.uuid4().hex[:12]}",
        mcp_port=args.mcp_port,
        # The pump budget is the real deadline: the 180s default would kill a
        # slow-but-healthy provider turn and restart it from scratch, so two
        # sequential turns could never fit into the bounded scenario window.
        delivery_timeout_s=max(180.0, args.timeout_s - 10.0),
        room_runner_env={"XMUSE_CLAUDE_ACP": "1", "XMUSE_ANTIGRAVITY": "1"},
    )
    try:
        try:
            runtime = ensure_room_runtime(config)
        except RoomRuntimeStartError as exc:
            _mark("runtime_start_failed", code=exc.code, message=str(exc))
            return 1
        _mark(
            "runtime",
            ready=runtime.get("ready"),
            state=runtime.get("state"),
            source=runtime.get("source"),
            boot_id=runtime.get("boot_id"),
            services=runtime.get("services"),
        )
        if not runtime.get("ready"):
            _mark("runtime_not_ready", note="runner composition failed; see log tails")
            return 1
        seen, turns, settled, projection = _pump(
            root=root,
            conversation_id=conversation_id,
            root_activity_seq=root_activity_seq,
            timeout_s=args.timeout_s,
        )
        _print_final_timeline(seen)
        for turn in turns:
            _mark("final_turn", **_turn_summary(turn))
        ordered = [seen[seq] for seq in sorted(seen)]
        handoff, researcher_responded, targets = _handoff_chain(ordered)
        _mark(
            "handoff_chain",
            handoff_observed=handoff,
            handoff_targets=targets,
            researcher_responded=researcher_responded,
        )
        _mark(
            "smoke_result",
            ok=bool(handoff and researcher_responded),
            settled=settled,
            room_status=projection.get("status"),
            timeline_items=len(ordered),
        )
        return 0 if handoff and researcher_responded else 1
    finally:
        stopped = stop_room_runtime(config)
        _mark("runtime_stopped", state=stopped.get("state"))
        for service, path in (
            ("room_runner", root / "logs" / "workroom-room-runner.log"),
            ("room_mcp", root / "logs" / "workroom-room-mcp.log"),
        ):
            lines = _tail(path, LOG_TAIL_LINES)
            if lines:
                _mark("log_tail", service=service, lines=lines)


if __name__ == "__main__":
    sys.exit(main())
