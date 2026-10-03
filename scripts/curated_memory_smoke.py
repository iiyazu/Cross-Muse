#!/usr/bin/env python3
"""Live end-to-end smoke of the opt-in MemoryOS Curator memory path.

This is not part of CI.  It drives an already running Workroom (started with
``xmuse-workroom launch --memory --memory-profile full-local-curated`` on the
heterogeneous Claude + Antigravity duo) through its loopback Chat API:

1. Room A records a project rule while the Human only asks the Claude lead how
   it would apply the rule; nobody is asked to propose memory.
2. A later delivery makes the Room recall, which pulls the MemoryOS Curator
   advisories and enters Room governance as a ``project_rule`` candidate with
   ``proposer_kind=memoryos_curator``.
3. The operator approves and publishes that candidate.
4. A Human update is recorded and the second curator candidate must supersede
   the published first one.
5. Room B asks the Antigravity researcher a question only the updated rule can
   answer; the durable recall receipt must cite the new curated document and
   never the superseded one.

``chat.db`` is opened read-only for inspection; Human messages go through the
same loopback proxy the browser uses and candidate approval goes through the
same operator governance call the operator endpoint makes.  It prints JSON
events and exits non-zero when any stage fails.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sqlite3
import sys
import time
import urllib.request
import uuid
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

from xmuse_core.chat.mentions import normalize_address
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_memory_governance_store import RoomMemoryGovernanceStore

TEMPLATE_ID = "builtin.heterogeneous-duo"
DEFAULT_API = "http://127.0.0.1:8201"
DEFAULT_FRONTEND = "http://127.0.0.1:3000"
DEFAULT_TURN_TIMEOUT_S = 900.0
DEFAULT_PUBLISH_TIMEOUT_S = 180.0
DEFAULT_CURATOR_WAIT_S = 35.0
POLL_INTERVAL_S = 2.0
CURATOR_PROPOSER_KIND = "memoryos_curator"
PROJECT_RULE_KIND = "project_rule"
CURATOR_DOCUMENT_PREFIX = "xmuse-room-memory-candidate-"
TERMINAL_PUBLISH_STATES = frozenset({"delivered", "failed", "conflict"})


class SmokeFailure(Exception):
    def __init__(self, stage: str, reason: str | None = None) -> None:
        super().__init__(stage)
        self.stage = stage
        self.reason = reason


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
            "client_request_id": f"curated-smoke-{uuid.uuid4().hex}",
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
        {"message": message, "client_request_id": f"curated-smoke-{uuid.uuid4().hex}"},
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


@contextlib.contextmanager
def _stage(name: str, timings: dict[str, float], **fields: Any) -> Iterator[None]:
    started = time.monotonic()
    try:
        yield
    finally:
        timings[name] = round(time.monotonic() - started, 2)
        _mark("stage", name=name, duration_s=timings[name], **fields)


def _connect_readonly(root: Path) -> sqlite3.Connection:
    uri = f"{(root / 'chat.db').resolve().as_uri()}?mode=ro"
    connection = sqlite3.connect(uri, uri=True, timeout=30)
    connection.row_factory = sqlite3.Row
    connection.execute("pragma busy_timeout = 30000")
    connection.execute("pragma query_only = on")
    return connection


def _read_candidates(root: Path, conversation_id: str) -> list[dict[str, Any]]:
    return RoomMemoryGovernanceStore(root / "chat.db").list_candidates(conversation_id, limit=100)


def _read_recall_receipts(root: Path, conversation_id: str) -> list[dict[str, Any]]:
    with contextlib.closing(_connect_readonly(root)) as conn:
        rows = conn.execute(
            """select attempt_id, status, item_count, item_refs_json
               from room_memory_attempt_receipts where conversation_id = ?
               order by created_at desc, receipt_id desc""",
            (conversation_id,),
        ).fetchall()
    return [
        {
            "attempt_id": str(row["attempt_id"]),
            "status": str(row["status"]),
            "item_count": int(row["item_count"]),
            "document_ids": parse_item_document_ids(str(row["item_refs_json"])),
        }
        for row in rows
    ]


def curator_candidates(candidates: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [
        candidate
        for candidate in candidates
        if str(candidate.get("proposer_kind") or "") == CURATOR_PROPOSER_KIND
    ]


def select_curator_candidate(
    candidates: Sequence[Mapping[str, Any]],
    *,
    kind: str,
    supersedes_candidate_id: str | None = None,
) -> Mapping[str, Any] | None:
    for candidate in curator_candidates(candidates):
        if str(candidate.get("kind") or "") != kind:
            continue
        if (
            supersedes_candidate_id is not None
            and candidate.get("supersedes_candidate_id") != supersedes_candidate_id
        ):
            continue
        return candidate
    return None


def candidate_by_id(
    candidates: Sequence[Mapping[str, Any]], candidate_id: str
) -> Mapping[str, Any] | None:
    return next(
        (item for item in candidates if str(item.get("candidate_id") or "") == candidate_id),
        None,
    )


def candidate_document_id(candidate_id: str) -> str:
    return f"{CURATOR_DOCUMENT_PREFIX}{candidate_id}"


def candidate_summary(candidate: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "proposer_kind": str(candidate.get("proposer_kind") or ""),
        "kind": str(candidate.get("kind") or ""),
        "content": str(candidate.get("content") or "")[:600],
        "approval_state": str(candidate.get("approval_state") or ""),
        "publish_state": str(candidate.get("publish_state") or ""),
        "supersedes_candidate_id": candidate.get("supersedes_candidate_id"),
        "superseded_by_candidate_id": candidate.get("superseded_by_candidate_id"),
    }


def parse_item_document_ids(item_refs_json: str) -> list[str]:
    try:
        items = json.loads(item_refs_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(items, list):
        return []
    return sorted(
        {
            str(item["document_id"])
            for item in items
            if isinstance(item, Mapping)
            and isinstance(item.get("document_id"), str)
            and item["document_id"]
        }
    )


def recall_checks(
    receipts: Sequence[Mapping[str, Any]],
    *,
    speech_text: str,
    new_document_id: str,
    old_document_id: str,
) -> dict[str, bool]:
    cited = {
        str(document_id)
        for receipt in receipts
        for document_id in receipt.get("document_ids") or []
    }
    return {
        "answer_mentions_details": "details" in speech_text.lower(),
        "recall_status_ok": any(str(receipt.get("status")) == "ok" for receipt in receipts),
        "new_document_cited": new_document_id in cited,
        "old_document_absent": old_document_id not in cited,
    }


def supersede_checks(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, bool]:
    return {
        "new_supersedes_old": new.get("supersedes_candidate_id") == old.get("candidate_id"),
        "old_superseded_by_new": old.get("superseded_by_candidate_id") == new.get("candidate_id"),
    }


def _wait_curator_candidate(
    args: argparse.Namespace,
    conversation_id: str,
    *,
    supersedes_candidate_id: str | None = None,
) -> Mapping[str, Any] | None:
    started = time.monotonic()
    while True:
        candidate = select_curator_candidate(
            _read_candidates(args.root, conversation_id),
            kind=PROJECT_RULE_KIND,
            supersedes_candidate_id=supersedes_candidate_id,
        )
        if candidate is not None:
            return candidate
        if time.monotonic() - started > args.publish_timeout_s:
            return None
        time.sleep(POLL_INTERVAL_S)


def _approve_and_publish(
    root: Path, conversation_id: str, candidate: Mapping[str, Any], timeout_s: float
) -> Mapping[str, Any] | None:
    store = RoomMemoryGovernanceStore(root / "chat.db")
    candidate_id = str(candidate["candidate_id"])
    store.resolve_candidate(
        candidate_id=candidate_id,
        decision="approve",
        client_action_id=f"curated-smoke-approve-{uuid.uuid4().hex}",
        operator_identity="operator:local",
        expected_candidate_digest=str(candidate["candidate_digest"]),
        expected_revision=int(candidate["revision"]),
    )
    started = time.monotonic()
    while True:
        row = candidate_by_id(_read_candidates(root, conversation_id), candidate_id)
        if row is not None and str(row.get("publish_state")) in TERMINAL_PUBLISH_STATES:
            return row
        if time.monotonic() - started > timeout_s:
            return row
        time.sleep(POLL_INTERVAL_S)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--api", default=DEFAULT_API)
    parser.add_argument("--frontend", default=DEFAULT_FRONTEND)
    parser.add_argument("--turn-timeout-s", type=float, default=DEFAULT_TURN_TIMEOUT_S)
    parser.add_argument("--publish-timeout-s", type=float, default=DEFAULT_PUBLISH_TIMEOUT_S)
    parser.add_argument(
        "--curator-wait-s",
        type=float,
        default=DEFAULT_CURATOR_WAIT_S,
        help="idle wait covering the Curator flush and its polling interval",
    )
    parser.add_argument(
        "--helper-role",
        default="research",
        help="roster role addressed by the trigger, update and Room B recall messages",
    )
    return parser.parse_args()


def _record_rule(args: argparse.Namespace, timings: dict[str, float]) -> tuple[str, Any]:
    with _stage("record_rule", timings):
        room_a = _create_room(args.frontend, "Curated smoke A (record)")
        lead = _participant(args.root, room_a, "architect")
        _mark("room_a", conversation_id=room_a, lead=lead.display_name, cli_kind=lead.cli_kind)
        seq = _post(
            args.frontend,
            room_a,
            "Project rule for this repository: every HTTP error response uses the JSON "
            'envelope {"code", "message", "trace_id"}. '
            f"{normalize_address(lead.display_name)} in two sentences, how would you apply "
            "this in the API layer?",
        )
        settled, items = _wait_turn(args.api, room_a, seq, args.turn_timeout_s)
        _mark("room_a_result", settled=settled, speech=_speech(items))
        if not settled:
            raise SmokeFailure("record_rule", "turn_not_settled")
        return room_a, lead


def _pull_curator_candidate(
    args: argparse.Namespace, room_a: str, timings: dict[str, float]
) -> Mapping[str, Any]:
    with _stage("curator_pull_1", timings, conversation_id=room_a):
        researcher = _participant(args.root, room_a, args.helper_role)
        _mark("curator_wait", conversation_id=room_a, wait_s=args.curator_wait_s)
        time.sleep(args.curator_wait_s)
        seq = _post(
            args.frontend,
            room_a,
            f"{normalize_address(researcher.display_name)} anything to add? One sentence.",
        )
        settled, items = _wait_turn(args.api, room_a, seq, args.turn_timeout_s)
        _mark("room_a_trigger_result", settled=settled, speech=_speech(items))
        if not settled:
            raise SmokeFailure("curator_pull_1", "turn_not_settled")
        candidate = _wait_curator_candidate(args, room_a)
        _mark(
            "curator_candidates",
            conversation_id=room_a,
            items=[
                candidate_summary(item)
                for item in curator_candidates(_read_candidates(args.root, room_a))
            ],
        )
        if candidate is None:
            raise SmokeFailure("curator_candidate_missing", "no curator project_rule candidate")
        _mark("curator_candidate", item=candidate_summary(candidate))
        return candidate


def _approve_1(
    args: argparse.Namespace,
    room_a: str,
    candidate: Mapping[str, Any],
    timings: dict[str, float],
) -> None:
    with _stage("approve_1", timings, candidate_id=str(candidate["candidate_id"])):
        delivered = _approve_and_publish(args.root, room_a, candidate, args.publish_timeout_s)
        if delivered is None or str(delivered.get("publish_state")) != "delivered":
            raise SmokeFailure("approve_1", "candidate_not_delivered")
        _mark("candidate_delivered", **candidate_summary(delivered))


def _record_update(
    args: argparse.Namespace,
    room_a: str,
    lead: Any,
    candidate_1: Mapping[str, Any],
    timings: dict[str, float],
) -> Mapping[str, Any]:
    with _stage("record_update", timings, conversation_id=room_a):
        researcher = _participant(args.root, room_a, args.helper_role)
        seq = _post(
            args.frontend,
            room_a,
            "Update to the project rule: the error envelope now also includes a details "
            'array, so it is {"code", "message", "details", "trace_id"}. '
            f"{normalize_address(researcher.display_name)} acknowledge in one sentence.",
        )
        settled, items = _wait_turn(args.api, room_a, seq, args.turn_timeout_s)
        _mark("room_a_update_result", settled=settled, speech=_speech(items))
        if not settled:
            raise SmokeFailure("record_update", "turn_not_settled")
        _mark("curator_wait", conversation_id=room_a, wait_s=args.curator_wait_s)
        time.sleep(args.curator_wait_s)
        seq = _post(
            args.frontend,
            room_a,
            f"{normalize_address(lead.display_name)} thanks, noted. One sentence.",
        )
        settled, items = _wait_turn(args.api, room_a, seq, args.turn_timeout_s)
        _mark("room_a_thanks_result", settled=settled, speech=_speech(items))
        if not settled:
            raise SmokeFailure("record_update", "turn_not_settled")
        candidate = _wait_curator_candidate(
            args, room_a, supersedes_candidate_id=str(candidate_1["candidate_id"])
        )
        if candidate is None:
            _mark(
                "curator_candidates",
                conversation_id=room_a,
                items=[
                    candidate_summary(item)
                    for item in curator_candidates(_read_candidates(args.root, room_a))
                ],
            )
            raise SmokeFailure(
                "superseding_candidate_missing", "no curator candidate supersedes the first"
            )
        _mark("curator_candidate", item=candidate_summary(candidate))
        delivered = _approve_and_publish(args.root, room_a, candidate, args.publish_timeout_s)
        if delivered is None or str(delivered.get("publish_state")) != "delivered":
            raise SmokeFailure("record_update", "superseding_candidate_not_delivered")
        _mark("candidate_delivered", **candidate_summary(delivered))
        old = candidate_by_id(_read_candidates(args.root, room_a), str(candidate_1["candidate_id"]))
        checks = supersede_checks(old or {}, delivered)
        _mark("supersede_checks", **checks)
        if not all(checks.values()):
            raise SmokeFailure("record_update", "supersede_not_recorded")
        return delivered


def _recall(
    args: argparse.Namespace,
    candidate_1: Mapping[str, Any],
    candidate_2: Mapping[str, Any],
    timings: dict[str, float],
) -> None:
    with _stage("recall", timings):
        room_b = _create_room(args.frontend, "Curated smoke B (recall)")
        researcher = _participant(args.root, room_b, args.helper_role)
        _mark(
            "room_b",
            conversation_id=room_b,
            researcher=researcher.display_name,
            cli_kind=researcher.cli_kind,
        )
        seq = _post(
            args.frontend,
            room_b,
            f"{normalize_address(researcher.display_name)} What JSON envelope must HTTP "
            "error responses use in this repository? Answer only from memory evidence.",
        )
        settled, items = _wait_turn(args.api, room_b, seq, args.turn_timeout_s)
        speech = _speech(items)
        receipts = _read_recall_receipts(args.root, room_b)
        checks = recall_checks(
            receipts,
            speech_text=" ".join(str(item.get("content") or "") for item in speech),
            new_document_id=candidate_document_id(str(candidate_2["candidate_id"])),
            old_document_id=candidate_document_id(str(candidate_1["candidate_id"])),
        )
        _mark(
            "room_b_result",
            settled=settled,
            speech=speech,
            recall_receipts=receipts,
            recall_checks=checks,
            proposer_kinds={
                "first": candidate_1["proposer_kind"],
                "second": candidate_2["proposer_kind"],
            },
        )
        if not settled:
            raise SmokeFailure("recall", "turn_not_settled")
        if not all(checks.values()):
            raise SmokeFailure("recall", "recall_assertion_failed")


def main() -> int:
    args = _parse_args()
    timings: dict[str, float] = {}
    try:
        room_a, lead = _record_rule(args, timings)
        candidate_1 = _pull_curator_candidate(args, room_a, timings)
        _approve_1(args, room_a, candidate_1, timings)
        candidate_2 = _record_update(args, room_a, lead, candidate_1, timings)
        _recall(args, candidate_1, candidate_2, timings)
    except SmokeFailure as failure:
        _mark(
            "smoke_result",
            ok=False,
            stage=failure.stage,
            reason=failure.reason,
            stages=timings,
        )
        return 1
    except Exception as error:
        _mark("smoke_result", ok=False, stage="error", reason=type(error).__name__, stages=timings)
        raise
    _mark("smoke_result", ok=True, stages=timings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
