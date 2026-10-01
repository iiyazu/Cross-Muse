#!/usr/bin/env python3
"""Live cross-Room MemoryOS recall smoke for the heterogeneous Claude + Antigravity Duo.

This is not part of CI.  It drives an already running Workroom (started with
``xmuse-workroom launch --memory --claude --antigravity``) through its loopback Chat
API:

1. Room A addresses the Claude lead with a project rule and asks it to propose the
   rule as a ``project_rule`` memory candidate.
2. Pending candidates are approved through the governance store (the same call the
   operator endpoint makes) and the script waits until the candidate is published to
   MemoryOS.
3. Room B addresses the Antigravity researcher with a question only the recalled rule
   can answer, and the script checks the answer plus the durable recall receipts.

It prints JSON events and exits non-zero when any stage fails.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from xmuse_core.chat.mentions import normalize_address
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_memory_governance_store import RoomMemoryGovernanceStore

TEMPLATE_ID = "builtin.heterogeneous-duo"
DEFAULT_API = "http://127.0.0.1:8201"
DEFAULT_FRONTEND = "http://127.0.0.1:3000"
POLL_INTERVAL_S = 2.0
PUBLISHED_STATES = frozenset({"delivered", "not_applicable"})
CODENAME = "Halcyon-7"
RULE = (
    "every HTTP error response must use the JSON envelope "
    '{"code", "message", "trace_id"} and the release codename is ' + CODENAME
)


def _mark(event: str, **fields: Any) -> None:
    print(json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


def _http(api: str, method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if body is not None:
        # Writes go through the browser Workroom's loopback proxy, which owns the
        # server-only operator token and requires a same-origin request.
        headers["Origin"] = api
    request = urllib.request.Request(f"{api}{path}", data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode())


def _create_room(api: str, title: str) -> str:
    created = _http(
        api,
        "POST",
        "/api/rooms",
        {
            "title": title,
            "client_request_id": f"memory-smoke-{uuid.uuid4().hex}",
            "roster_template_id": TEMPLATE_ID,
        },
    )
    return str(created["id"])


def _participant(root: Path, conversation_id: str, role: str) -> Any:
    participants = ParticipantStore(root / "chat.db").list_by_conversation(conversation_id)
    return next(item for item in participants if item.role == role)


def _post(api: str, conversation_id: str, message: str) -> int:
    receipt = _http(
        api,
        "POST",
        f"/api/rooms/{conversation_id}/messages",
        {"message": message, "client_request_id": f"memory-smoke-{uuid.uuid4().hex}"},
    )
    return int(receipt["room_activity_seq"])


def _wait_turn(
    api: str, conversation_id: str, root_seq: int, timeout_s: float
) -> tuple[bool, list[dict[str, Any]]]:
    started = time.monotonic()
    last_status = None
    while True:
        projection = _http(api, "GET", f"/api/chat/conversations/{conversation_id}/room-projection")
        turn = next(
            (
                item
                for item in projection.get("turns") or []
                if int(item.get("root_room_seq") or -1) == root_seq
            ),
            None,
        )
        status = None if turn is None else turn.get("status")
        if status != last_status:
            _mark("turn_status", conversation_id=conversation_id, status=status)
            last_status = status
        items = [
            item
            for item in projection.get("timeline_items") or []
            if int(item["room_seq"]) > root_seq
        ]
        if status in {"settled", "attention"}:
            return status == "settled", items
        if time.monotonic() - started > timeout_s:
            _mark("turn_timeout", conversation_id=conversation_id)
            return False, items
        time.sleep(POLL_INTERVAL_S)


def _speech(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "actor": (item.get("actor") or {}).get("display_name"),
            "kind": item.get("kind"),
            "content": str(item.get("content") or "")[:600],
        }
        for item in items
        if (item.get("actor") or {}).get("kind") != "human"
    ]


def _approve_and_publish(
    root: Path, conversation_id: str, timeout_s: float
) -> list[dict[str, Any]]:
    store = RoomMemoryGovernanceStore(root / "chat.db")
    for candidate in store.list_candidates(conversation_id, approval_state="pending"):
        store.resolve_candidate(
            candidate_id=candidate["candidate_id"],
            decision="approve",
            client_action_id=f"memory-smoke-approve-{uuid.uuid4().hex}",
            operator_identity="operator:local",
            expected_candidate_digest=candidate["candidate_digest"],
            expected_revision=candidate["revision"],
        )
    started = time.monotonic()
    while True:
        candidates = store.list_candidates(conversation_id)
        if candidates and all(item["publish_state"] in PUBLISHED_STATES for item in candidates):
            return candidates
        if time.monotonic() - started > timeout_s:
            return candidates
        time.sleep(POLL_INTERVAL_S)


def _recall_receipts(root: Path, conversation_id: str) -> list[dict[str, Any]]:
    with sqlite3.connect(root / "chat.db") as conn:
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "select * from room_memory_attempt_receipts where conversation_id = ?",
                (conversation_id,),
            ).fetchall()
        except sqlite3.OperationalError:
            return []
    return [{key: str(row[key])[:240] for key in row.keys()} for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND)
    parser.add_argument("--turn-timeout-s", type=float, default=900.0)
    parser.add_argument("--publish-timeout-s", type=float, default=180.0)
    parser.add_argument(
        "--recall-only",
        action="store_true",
        help="skip Room A when an approved project rule was already delivered",
    )
    args = parser.parse_args()

    if not args.recall_only and not _record(args):
        _mark("smoke_result", ok=False, stage="publish")
        return 1
    return _recall(args)


def _record(args: argparse.Namespace) -> bool:
    room_a = _create_room(args.frontend, "Memory smoke A (record)")
    lead = _participant(args.root, room_a, "architect")
    _mark("room_a", conversation_id=room_a, lead=lead.display_name, cli_kind=lead.cli_kind)
    seq_a = _post(
        args.frontend,
        room_a,
        f"{normalize_address(lead.display_name)} Project rule for this repository: {RULE}. "
        "Acknowledge in one sentence and propose exactly this rule as a project_rule "
        "memory candidate sourced from this message. Do not hand off.",
    )
    settled_a, items_a = _wait_turn(args.api, room_a, seq_a, args.turn_timeout_s)
    _mark("room_a_result", settled=settled_a, speech=_speech(items_a))

    candidates = _approve_and_publish(args.root, room_a, args.publish_timeout_s)
    _mark(
        "candidates",
        items=[
            {
                key: item[key]
                for key in ("kind", "content", "approval_state", "publish_state", "target_scope")
            }
            for item in candidates
        ],
    )
    return any(
        item["kind"] == "project_rule" and item["publish_state"] == "delivered"
        for item in candidates
    )


def _recall(args: argparse.Namespace) -> int:
    room_b = _create_room(args.frontend, "Memory smoke B (recall)")
    researcher = _participant(args.root, room_b, "research")
    _mark(
        "room_b",
        conversation_id=room_b,
        researcher=researcher.display_name,
        cli_kind=researcher.cli_kind,
    )
    seq_b = _post(
        args.frontend,
        room_b,
        f"{normalize_address(researcher.display_name)} Using only project memory evidence, "
        "what JSON envelope must HTTP error responses use in this repository, and what is "
        "the release codename? Answer in one or two sentences; say you do not know if the "
        "evidence is absent. Do not hand off.",
    )
    settled_b, items_b = _wait_turn(args.api, room_b, seq_b, args.turn_timeout_s)
    speech_b = _speech(items_b)
    receipts = _recall_receipts(args.root, room_b)
    _mark("room_b_result", settled=settled_b, speech=speech_b, recall_receipts=receipts)
    answer = " ".join(item["content"] for item in speech_b)
    ok = CODENAME in answer and "trace_id" in answer
    _mark("smoke_result", ok=ok, stage="recall")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
