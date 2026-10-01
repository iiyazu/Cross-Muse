"""Run broadcast-vs-addressed eval cells against a live loopback Room API.

Usage (server must already be running, e.g. ``xmuse-chat-api`` on the default port)::

    uv run python scripts/eval/run_eval.py \
        --base-url http://127.0.0.1:8201/api/chat \
        --modes broadcast,addressed \
        --roster-template builtin.heterogeneous-duo \
        --tasks all --seed 7 --out eval_out

Endpoints used (verified against the repo sources in July 2026):

- ``POST {base}/conversations`` -> RoomSetupService.create_conversation
  (``xmuse/chat_api_room_setup.py``); body ``{title, client_request_id,
  roster_template_id, collaboration: {mode, lead_role}}``; the response carries
  ``id``, ``participants[]`` and ``setup.collaboration.lead_participant_id``.
- ``POST {base}/threads/{cid}/messages`` (``xmuse/chat_api_room_messages.py``);
  body ``{message, client_request_id}``; the receipt carries ``activity_id`` and
  ``room_activity_seq``.
- ``GET {base}/conversations/{cid}/room-projection?limit=100`` and
  ``?before_room_seq=`` (``xmuse/chat_api_room_projection.py``); the projection
  carries ``active_turn_count``, ``attention_turn_count``, ``turns[]``,
  ``timeline_items[]``, ``participants[].mention_handle`` and ``page`` cursors.
- ``GET {base}/conversations/{cid}/events?after_seq=&limit=``; used only for
  ``latest_seq`` stability.  Room sequence and frontend event sequence are
  different domains (``docs/xmuse/frontend/FRONTEND_API.md``).

Ordering rules from design §3: one seeded task shuffle shared by both modes,
mode order alternates per task block, and the two modes are never run
concurrently (wall time would be distorted by shared compute).
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.eval import metrics, tasks

DEFAULT_BASE_URL = "http://127.0.0.1:8201/api/chat"
TRANSCRIPT_SCHEMA_VERSION = "eval_transcript/v1"
MANIFEST_SCHEMA_VERSION = "eval_run_manifest/v1"
RESULTS_COLUMNS: tuple[str, ...] = (
    "task_id",
    "mode",
    "run",
    "rubric_score",
    "judge_a",
    "judge_b",
    "agree",
    "agent_turns",
    "visible_msgs",
    "echo_msgs",
    "pure_ack_msgs",
    "wall_s",
    "max_causal_depth",
    "handoffs",
    "specialist_ok",
    "tokens_est",
    "notes",
)
MODES = ("broadcast", "addressed")
MAX_TIMELINE_PAGES = 20


class EvalHttpError(RuntimeError):
    """A non-2xx response or transport failure from the Room API."""


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _git_commit() -> dict[str, Any]:
    def run(args: list[str]) -> str:
        completed = subprocess.run(args, capture_output=True, text=True, check=False)
        return completed.stdout.strip()

    try:
        return {
            "commit": run(["git", "rev-parse", "--short", "HEAD"]) or None,
            "dirty": bool(run(["git", "status", "--porcelain"])),
        }
    except OSError:
        return {"commit": None, "dirty": None}


class RoomApiClient:
    """Minimal stdlib JSON client for the loopback Room API."""

    def __init__(self, base_url: str, *, timeout_s: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_s = timeout_s

    def _request(self, method: str, path: str, body: dict[str, Any] | None) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                payload = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise EvalHttpError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise EvalHttpError(f"{method} {path} -> transport error: {exc.reason}") from exc
        try:
            decoded = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise EvalHttpError(f"{method} {path} -> non-JSON response") from exc
        if not isinstance(decoded, dict):
            raise EvalHttpError(f"{method} {path} -> unexpected response shape")
        return decoded

    def create_room(
        self,
        *,
        title: str,
        roster_template_id: str,
        mode: str,
        lead_role: str,
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            "/conversations",
            {
                "title": title,
                "client_request_id": f"eval_room_{uuid.uuid4().hex}",
                "roster_template_id": roster_template_id,
                "collaboration": {"mode": mode, "lead_role": lead_role},
            },
        )

    def post_human_message(
        self, conversation_id: str, *, message: str, client_request_id: str
    ) -> dict[str, Any]:
        return self._request(
            "POST",
            f"/threads/{conversation_id}/messages",
            {"message": message, "client_request_id": client_request_id},
        )

    def room_projection(
        self,
        conversation_id: str,
        *,
        limit: int = 100,
        before_room_seq: int | None = None,
    ) -> dict[str, Any]:
        path = f"/conversations/{conversation_id}/room-projection?limit={limit}"
        if before_room_seq is not None:
            path += f"&before_room_seq={before_room_seq}"
        return self._request("GET", path, None)

    def events_latest_seq(self, conversation_id: str) -> int:
        payload = self._request(
            "GET", f"/conversations/{conversation_id}/events?after_seq=0&limit=1", None
        )
        try:
            return int(payload.get("latest_seq") or 0)
        except (TypeError, ValueError):
            return 0


def resolve_lead_handle(projection: dict[str, Any], lead_participant_id: str | None) -> str:
    """The lead's mention handle (``@role`` or ``@participant:<id>``) from the projection."""
    for participant in projection.get("participants") or []:
        if not isinstance(participant, dict):
            continue
        if lead_participant_id and participant.get("participant_id") == lead_participant_id:
            handle = participant.get("mention_handle")
            if isinstance(handle, str) and handle:
                return handle
    if lead_participant_id:
        return f"@participant:{lead_participant_id}"
    raise EvalHttpError("room projection carries no lead participant")


def _terminal_agent_observations(projection: dict[str, Any], root_activity_id: str | None) -> int:
    total = 0
    for turn in projection.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        if root_activity_id is not None and turn.get("root_activity_id") != root_activity_id:
            continue
        for member in turn.get("participants") or []:
            if not isinstance(member, dict):
                continue
            observation_count = int(member.get("observation_count") or 0)
            unresolved = int(member.get("unresolved_count") or 0)
            total += max(0, observation_count - unresolved)
    return total


@dataclass
class SettleResult:
    projection: dict[str, Any]
    timed_out: bool
    abort_reason: str | None
    polls: int
    events_latest_seq: int
    terminal_turns: int = 0


def settle_cell(
    client: RoomApiClient,
    conversation_id: str,
    *,
    root_activity_id: str | None,
    deadline_s: float,
    max_turns: int,
    poll_interval_s: float,
) -> SettleResult:
    """Poll until the Room is idle and stable, per design §4.

    Settled means ``active_turn_count == 0`` and ``attention_turn_count == 0`` with
    an unchanged frontend ``latest_seq`` for two consecutive polls (the repeat
    covers the 15s lease safety refresh).  Aborts are recorded, never raised.
    """
    started = time.monotonic()
    last_seq = -1
    stable = 0
    polls = 0
    projection: dict[str, Any] = {}
    latest_seq = 0
    while True:
        projection = client.room_projection(conversation_id, limit=100)
        latest_seq = client.events_latest_seq(conversation_id)
        polls += 1
        idle = int(projection.get("active_turn_count") or 0) == 0 and (
            int(projection.get("attention_turn_count") or 0) == 0
        )
        stable = stable + 1 if idle and latest_seq == last_seq else 0
        last_seq = latest_seq
        terminal = _terminal_agent_observations(projection, root_activity_id)
        if idle and stable >= 2:
            return SettleResult(projection, False, None, polls, latest_seq, terminal)
        if terminal >= max_turns:
            return SettleResult(projection, True, "max_turns", polls, latest_seq, terminal)
        if time.monotonic() - started >= deadline_s:
            return SettleResult(projection, True, "deadline", polls, latest_seq, terminal)
        time.sleep(poll_interval_s)


def fetch_all_timeline(
    client: RoomApiClient, conversation_id: str, projection: dict[str, Any]
) -> list[dict[str, Any]]:
    """Merge every visible timeline page (rooms are small; one page usually suffices)."""
    items: list[dict[str, Any]] = [
        dict(item) for item in projection.get("timeline_items") or [] if isinstance(item, dict)
    ]
    seen = {str(item.get("activity_id")) for item in items}
    page = projection.get("page") or {}
    pages = 1
    while isinstance(page, dict) and page.get("has_older") and pages < MAX_TIMELINE_PAGES:
        before = page.get("next_before_room_seq")
        if not isinstance(before, int):
            break
        older = client.room_projection(conversation_id, limit=100, before_room_seq=before)
        for item in older.get("timeline_items") or []:
            if isinstance(item, dict) and str(item.get("activity_id")) not in seen:
                items.append(dict(item))
                seen.add(str(item.get("activity_id")))
        page = older.get("page") or {}
        pages += 1
    items.sort(key=lambda item: int(item.get("room_seq") or 0))
    return items


def _root_correlation(projection: dict[str, Any], root_activity_id: str | None) -> str | None:
    turns = projection.get("turns") or []
    if root_activity_id is not None:
        for turn in turns:
            if isinstance(turn, dict) and turn.get("root_activity_id") == root_activity_id:
                correlation = turn.get("correlation_id")
                return str(correlation) if correlation else None
    if len(turns) == 1 and isinstance(turns[0], dict) and turns[0].get("correlation_id"):
        return str(turns[0]["correlation_id"])
    return None


def run_cell(
    client: RoomApiClient,
    task: tasks.EvalTask,
    mode: str,
    *,
    run: int,
    seed: int,
    roster_template_id: str,
    lead_role: str,
    title_prefix: str,
    deadline_s: float,
    max_turns: int,
    poll_interval_s: float,
) -> dict[str, Any]:
    transcript_id = f"{task.task_id}_{mode}_r{run}"
    room = client.create_room(
        title=f"{title_prefix}-{task.task_id}-{mode}",
        roster_template_id=roster_template_id,
        mode=mode,
        lead_role=lead_role,
    )
    conversation_id = str(room["id"])
    setup_value = room.get("setup")
    setup: dict[str, Any] = setup_value if isinstance(setup_value, dict) else {}
    collaboration_value = setup.get("collaboration")
    collaboration: dict[str, Any] = (
        collaboration_value if isinstance(collaboration_value, dict) else {}
    )
    lead_participant_id = collaboration.get("lead_participant_id")

    try:
        pre_projection = client.room_projection(conversation_id, limit=100)
        mention_prefix: str | None = None
        posted_content = task.prompt
        if mode == "addressed":
            mention_prefix = resolve_lead_handle(
                pre_projection, str(lead_participant_id or "") or None
            )
            posted_content = f"{mention_prefix} {task.prompt}"

        started_at = utc_now()
        receipt = client.post_human_message(
            conversation_id,
            message=posted_content,
            client_request_id=f"eval_msg_{uuid.uuid4().hex}",
        )
        wall_started = time.monotonic()
        settled = settle_cell(
            client,
            conversation_id,
            root_activity_id=str(receipt.get("activity_id") or "") or None,
            deadline_s=deadline_s,
            max_turns=max_turns,
            poll_interval_s=poll_interval_s,
        )
        wall_s = time.monotonic() - wall_started
        root_activity_id = str(receipt.get("activity_id") or "") or None

        projection = dict(settled.projection)
        projection["timeline_items"] = fetch_all_timeline(
            client, conversation_id, settled.projection
        )
        message_value = receipt.get("message")
        message: dict[str, Any] = message_value if isinstance(message_value, dict) else {}
        return {
            "schema_version": TRANSCRIPT_SCHEMA_VERSION,
            "transcript_id": transcript_id,
            "task_id": task.task_id,
            "mode": mode,
            "run": run,
            "seed": seed,
            "roster_template_id": roster_template_id,
            "base_url": client.base_url,
            "conversation_id": conversation_id,
            "room_title": room.get("title"),
            "room_created_at": room.get("created_at"),
            "roster_observed": [
                {
                    key: participant.get(key)
                    for key in ("participant_id", "role", "display_name", "cli_kind", "model")
                }
                for participant in room.get("participants") or []
                if isinstance(participant, dict)
            ],
            "lead_participant_id": lead_participant_id,
            "mention_prefix": mention_prefix,
            "prompt_raw": task.prompt,
            "prompt_posted": posted_content,
            "receipt": {
                "activity_id": receipt.get("activity_id"),
                "room_activity_seq": receipt.get("room_activity_seq"),
                "message_id": message.get("id"),
            },
            "root_correlation_id": _root_correlation(settled.projection, root_activity_id),
            "timing": {
                "started_at": started_at,
                "ended_at": utc_now(),
                "wall_s": round(wall_s, 3),
                "timed_out": settled.timed_out,
                "abort_reason": settled.abort_reason,
                "polls": settled.polls,
                "events_latest_seq": settled.events_latest_seq,
                "terminal_turns_observed": settled.terminal_turns,
            },
            "projection": projection,
        }
    except Exception as exc:  # noqa: BLE001 - one cell failure must not stop the run
        return error_transcript(
            task,
            mode,
            run=run,
            seed=seed,
            message=str(exc),
            conversation_id=conversation_id,
        )


def error_transcript(
    task: tasks.EvalTask,
    mode: str,
    *,
    run: int,
    seed: int,
    message: str,
    conversation_id: str | None = None,
    timing: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": TRANSCRIPT_SCHEMA_VERSION,
        "transcript_id": f"{task.task_id}_{mode}_r{run}",
        "task_id": task.task_id,
        "mode": mode,
        "run": run,
        "seed": seed,
        "conversation_id": conversation_id,
        "error": message,
        "timing": timing or {"wall_s": 0.0, "timed_out": True, "abort_reason": "error"},
        "projection": {"timeline_items": [], "turns": [], "participants": []},
    }


def csv_row(transcript: dict[str, Any], task: tasks.EvalTask) -> dict[str, Any]:
    row: dict[str, Any] = {
        "task_id": transcript["task_id"],
        "mode": transcript["mode"],
        "run": transcript["run"],
        "rubric_score": "",
        "judge_a": "",
        "judge_b": "",
        "agree": "",
    }
    if transcript.get("error"):
        row.update(dict.fromkeys(RESULTS_COLUMNS[7:-1], ""))
        row["notes"] = f"error:{transcript['error']}"[:300]
        return row
    computed = metrics.compute_metrics(transcript, task)
    row["notes"] = computed.pop("notes")
    computed.pop("handoff_targets", None)
    computed.pop("context_only_msgs", None)
    row.update(computed)
    return row


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_results_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(RESULTS_COLUMNS), extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


@dataclass
class RunState:
    rows: list[dict[str, Any]] = field(default_factory=list)
    manifest_cells: list[dict[str, Any]] = field(default_factory=list)


def planned_cells(
    selected: list[tasks.EvalTask], modes: list[str], seed: int
) -> list[tuple[str, str]]:
    """Seeded task shuffle; per-task block with alternated mode order (design §3)."""
    order = list(selected)
    random.Random(seed).shuffle(order)
    plan: list[tuple[str, str]] = []
    for index, task in enumerate(order):
        mode_order = modes if index % 2 == 0 else list(reversed(modes))
        for mode in mode_order:
            plan.append((task.task_id, mode))
    return plan


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--modes", default="broadcast,addressed")
    parser.add_argument("--roster-template", default="builtin.heterogeneous-duo")
    parser.add_argument("--tasks", default="all")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, required=True, help="output directory")
    parser.add_argument("--run", type=int, default=1, help="repetition index for this cell set")
    parser.add_argument("--lead-role", default="architect")
    parser.add_argument("--title-prefix", default="eval")
    parser.add_argument("--deadline-s", type=float, default=480.0)
    parser.add_argument("--max-turns", type=int, default=10)
    parser.add_argument("--poll-interval-s", type=float, default=5.0)
    parser.add_argument("--http-timeout-s", type=float, default=30.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    modes = [mode.strip() for mode in args.modes.split(",") if mode.strip()]
    invalid = [mode for mode in modes if mode not in MODES]
    if invalid:
        raise SystemExit(f"invalid --modes values: {invalid}; expected any of {MODES}")
    selected = tasks.select_tasks(args.tasks)
    selected_by_id = {task.task_id: task for task in selected}
    plan = planned_cells(selected, modes, args.seed)

    args.out.mkdir(parents=True, exist_ok=True)
    transcripts_dir = args.out / "transcripts"
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    client = RoomApiClient(args.base_url, timeout_s=args.http_timeout_s)
    state = RunState()

    manifest: dict[str, Any] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "created_at": utc_now(),
        "base_url": args.base_url,
        "seed": args.seed,
        "roster_template_id": args.roster_template,
        "lead_role": args.lead_role,
        "modes": modes,
        "run": args.run,
        "deadline_s": args.deadline_s,
        "max_turns": args.max_turns,
        "ordering": (
            "seeded task shuffle; mode order alternates per task block; modes never concurrent"
        ),
        "plan": [{"task_id": task_id, "mode": mode} for task_id, mode in plan],
        "environment": {
            "python": sys.version.split()[0],
            "git": _git_commit(),
        },
        "cells": state.manifest_cells,
    }
    _write_json(args.out / "run_manifest.json", manifest)

    errors = 0
    try:
        for index, (task_id, mode) in enumerate(plan, start=1):
            task = selected_by_id[task_id]
            print(f"[{index}/{len(plan)}] {task_id} {mode} ...", flush=True)
            try:
                transcript = run_cell(
                    client,
                    task,
                    mode,
                    run=args.run,
                    seed=args.seed,
                    roster_template_id=args.roster_template,
                    lead_role=args.lead_role,
                    title_prefix=args.title_prefix,
                    deadline_s=args.deadline_s,
                    max_turns=args.max_turns,
                    poll_interval_s=args.poll_interval_s,
                )
            except Exception as exc:  # noqa: BLE001 - stray harness failure, keep the run going
                errors += 1
                transcript = error_transcript(
                    task, mode, run=args.run, seed=args.seed, message=str(exc)
                )
                print(f"    error: {exc}", flush=True)
            _write_json(transcripts_dir / f"{transcript['transcript_id']}.json", transcript)
            row = csv_row(transcript, task)
            state.rows.append(row)
            state.manifest_cells.append(
                {
                    "transcript_id": transcript["transcript_id"],
                    "task_id": task_id,
                    "mode": mode,
                    "conversation_id": transcript.get("conversation_id"),
                    "room_title": transcript.get("room_title"),
                    "roster_observed": transcript.get("roster_observed"),
                    "wall_s": (transcript.get("timing") or {}).get("wall_s"),
                    "timed_out": (transcript.get("timing") or {}).get("timed_out"),
                    "abort_reason": (transcript.get("timing") or {}).get("abort_reason"),
                    "error": transcript.get("error"),
                }
            )
            _write_results_csv(args.out / "results.csv", state.rows)
            _write_json(args.out / "run_manifest.json", manifest)
            timing = transcript.get("timing") or {}
            status = timing.get("abort_reason") or "settled"
            print(
                f"    {status} in {timing.get('wall_s')}s, "
                f"turns={row.get('agent_turns')} visible={row.get('visible_msgs')}",
                flush=True,
            )
    finally:
        _write_results_csv(args.out / "results.csv", state.rows)
        _write_json(args.out / "run_manifest.json", manifest)

    print(f"\nWrote {len(state.rows)} cells to {args.out} (errors: {errors})")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
