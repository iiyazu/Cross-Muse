from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.terminal_tui_demo import (
    TERMINAL_TUI_DEMO_EVIDENCE_SOURCE,
    TERMINAL_TUI_DEMO_HARNESS_VERSION,
    is_terminal_tui_launch_command,
    terminal_tui_demo_scripted_inputs,
)
from xmuse_core.platform.dashboard_details import _conversation_runtime_timeline_detail

GATE_NAMES = (
    "fresh_bootstrap",
    "structured_collaboration",
    "review_veto_lifecycle",
    "dispatch_gate_lifecycle",
    "agent_auto_dispatch",
    "real_provider_mcp_writeback",
    "tui_dashboard_read_surface",
    "restart_resume",
    "process_cleanup",
    "official_tui_main_path",
    "terminal_tui_demo",
)


def collect_v14_closure_evidence(
    *,
    xmuse_root: Path | str,
    conversation_id: str,
    provider_session_reused: bool,
    official_tui_main_path: dict[str, Any],
    process_cleanup: dict[str, Any],
) -> dict[str, Any]:
    """Collect V14 closure evidence from official read surfaces.

    External proof inputs such as process cleanup and changed TUI paths are
    supplied by the closure harness. Runtime state itself is read from the same
    chat inspector, bootstrap status, and dashboard timeline surfaces used by
    TUI/dashboard.
    """

    root = Path(xmuse_root)
    clean_conversation_id = str(conversation_id).strip()
    timeline = _conversation_runtime_timeline_detail(
        root,
        clean_conversation_id,
    )
    tui_evidence = _augment_official_tui_main_path_evidence(
        root=root,
        conversation_id=clean_conversation_id,
        supplied=official_tui_main_path,
        timeline=timeline,
    )
    runner_operations = _collect_runner_operations(root)
    return {
        "conversation_id": clean_conversation_id,
        "bootstrap": PeerChatService(root / "chat.db").get_bootstrap_status(
            clean_conversation_id
        ),
        "inspector": build_conversation_inspector_payload(clean_conversation_id, root),
        "runtime_timeline": timeline,
        "runner_operations": runner_operations,
        "provider_session_reused": bool(provider_session_reused),
        "official_tui_main_path": tui_evidence,
        "terminal_tui_demo": _persisted_terminal_tui_demo(root, clean_conversation_id),
        "process_cleanup": process_cleanup,
    }


def _augment_official_tui_main_path_evidence(
    *,
    root: Path,
    conversation_id: str,
    supplied: dict[str, Any],
    timeline: dict[str, Any],
) -> dict[str, Any]:
    evidence = dict(supplied)
    evidence.setdefault("conversation_id", conversation_id)
    if "command_events" not in evidence:
        events = _persisted_tui_command_events(root, conversation_id)
        if events:
            evidence["command_events"] = events
    if "runtime_timeline_event_ids" not in evidence:
        timeline_ids = [
            str(event.get("event_id") or "")
            for event in _dicts(timeline.get("events"))
            if str(event.get("event_id") or "").strip()
        ]
        if timeline_ids:
            evidence["runtime_timeline_event_ids"] = timeline_ids
    return evidence


def _persisted_tui_command_events(
    root: Path,
    conversation_id: str,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(
            (root / "tui_command_events.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return []
    raw_events = payload.get("command_events") if isinstance(payload, dict) else None
    if not isinstance(raw_events, list):
        return []
    return [
        event
        for event in raw_events
        if isinstance(event, dict)
        and str(event.get("conversation_id") or "") == conversation_id
    ]


def _persisted_terminal_tui_demo(
    root: Path,
    conversation_id: str,
) -> dict[str, Any]:
    try:
        payload = json.loads(
            (root / "tui_terminal_demo.json").read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    demo = payload.get("terminal_tui_demo")
    if isinstance(demo, dict):
        payload = demo
    if str(payload.get("conversation_id") or "") != conversation_id:
        return {}
    terminal_run_id = str(payload.get("terminal_run_id") or "").strip()
    if terminal_run_id:
        events = [
            event
            for event in _persisted_tui_command_events(root, conversation_id)
            if str(event.get("terminal_run_id") or "") == terminal_run_id
        ]
        payload = {
            **payload,
            "observed_command_event_ids": [
                str(event.get("event_id") or "") for event in events
            ],
            "observed_command_events": events,
        }
    return payload


def _collect_runner_operations(root: Path) -> dict[str, Any]:
    return {"chat_dispatch_bridge": _runner_dispatch_bridge_health(root / "chat.db")}


def _runner_dispatch_bridge_health(chat_db_path: Path) -> dict[str, Any]:
    empty = {
        "status": "no_entries",
        "total": 0,
        "queued": 0,
        "processing": 0,
        "dispatched": 0,
        "failed": 0,
        "latest": None,
    }
    if not chat_db_path.exists():
        return {**empty, "status": "missing_chat_db"}
    try:
        with sqlite3.connect(chat_db_path) as conn:
            conn.row_factory = sqlite3.Row
            table_exists = conn.execute(
                """
                select 1 from sqlite_master
                where type = 'table' and name = 'chat_dispatch_queue'
                """
            ).fetchone()
            if table_exists is None:
                return empty
            rows = conn.execute(
                """
                select status, count(*) as c
                from chat_dispatch_queue
                group by status
                """
            ).fetchall()
            counts = {str(row["status"]): int(row["c"] or 0) for row in rows}
            total = sum(counts.values())
            if total == 0:
                return empty
            latest = conn.execute(
                """
                select
                    entry_id, conversation_id, status, source, target, auto_execute,
                    proposal_id, resolution_id, collaboration_run_id, artifact_ref,
                    dispatch_evidence
                from chat_dispatch_queue
                order by
                    coalesce(completed_at, updated_at, claimed_at, created_at) desc,
                    completed_at is not null desc,
                    rowid desc
                limit 1
                """
            ).fetchone()
            return {
                "status": "observed",
                "total": total,
                "queued": counts.get("queued", 0),
                "processing": counts.get("processing", 0),
                "dispatched": counts.get("dispatched", 0),
                "failed": counts.get("failed", 0),
                "latest": _runner_dispatch_bridge_latest(latest),
            }
    except sqlite3.Error as exc:
        return {**empty, "status": "unreadable", "error": str(exc)}


def _runner_dispatch_bridge_latest(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "entry_id": row["entry_id"],
        "conversation_id": row["conversation_id"],
        "status": row["status"],
        "source": row["source"],
        "target": row["target"],
        "auto_execute": bool(row["auto_execute"]),
        "proposal_id": row["proposal_id"],
        "resolution_id": row["resolution_id"],
        "collaboration_run_id": row["collaboration_run_id"],
        "artifact_ref": row["artifact_ref"],
        "dispatch_evidence": row["dispatch_evidence"],
    }


def validate_v14_closure_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    """Validate that collected runtime evidence is strong enough for V14 closure.

    The validator is intentionally read-only: callers must collect evidence from
    official Chat API, dashboard timeline, latency traces, and cleanup checks.
    This function only rejects weak or contradictory evidence before a handoff
    claims production closure.
    """

    bootstrap = _dict(evidence.get("bootstrap"))
    inspector = _dict(evidence.get("inspector"))
    timeline = _dict(evidence.get("runtime_timeline"))
    runner_operations = _dict(evidence.get("runner_operations"))
    cleanup = _dict(evidence.get("process_cleanup"))

    collaboration = _dict(inspector.get("collaboration"))
    blockers = _dict(inspector.get("blockers"))
    queue = _dict(inspector.get("dispatch_queue"))
    latency = _dict(inspector.get("peer_latency"))
    chain = _closure_chain(
        conversation_id=str(evidence.get("conversation_id") or ""),
        bootstrap=bootstrap,
        inspector=inspector,
        collaboration=collaboration,
        blockers=blockers,
        queue=queue,
        latency=latency,
    )

    gate_checks = {
        "fresh_bootstrap": _has_fresh_bootstrap(bootstrap, inspector),
        "structured_collaboration": chain.get("structured_collaboration") is True,
        "review_veto_lifecycle": chain.get("review_veto_lifecycle") is True,
        "dispatch_gate_lifecycle": chain.get("dispatch_gate_lifecycle") is True,
        "agent_auto_dispatch": (
            chain.get("agent_auto_dispatch") is True
            and _has_runner_dispatch_bridge_evidence(
                runner_operations,
                conversation_id=str(evidence.get("conversation_id") or ""),
                chain=chain,
            )
        ),
        "real_provider_mcp_writeback": (
            chain.get("real_provider_mcp_writeback") is True
        ),
        "tui_dashboard_read_surface": _has_tui_dashboard_read_surface(
            timeline,
            conversation_id=str(evidence.get("conversation_id") or ""),
            chain=chain,
        ),
        "restart_resume": evidence.get("provider_session_reused") is True,
        "process_cleanup": _has_clean_process_cleanup(cleanup),
        "official_tui_main_path": _has_official_tui_main_path_evidence(
            _dict(evidence.get("official_tui_main_path")),
            conversation_id=str(evidence.get("conversation_id") or ""),
            timeline=timeline,
            chain=chain,
        ),
        "terminal_tui_demo": _has_terminal_tui_demo_evidence(
            _dict(evidence.get("terminal_tui_demo")),
            conversation_id=str(evidence.get("conversation_id") or ""),
            timeline=timeline,
            chain=chain,
        ),
    }
    gates = [_gate(name, gate_checks[name]) for name in GATE_NAMES]
    missing = [gate["name"] for gate in gates if not gate["ok"]]
    return {
        "ok": not missing,
        "missing": missing,
        "gates": gates,
    }


def _gate(name: str, ok: bool) -> dict[str, Any]:
    return {"name": name, "ok": bool(ok)}


def _has_fresh_bootstrap(bootstrap: dict[str, Any], inspector: dict[str, Any]) -> bool:
    conversation = _dict(inspector.get("conversation"))
    bootstrap_conversation_id = str(bootstrap.get("conversation_id") or "").strip()
    inspector_conversation_id = str(conversation.get("id") or "").strip()
    if not bootstrap_conversation_id or bootstrap_conversation_id != inspector_conversation_id:
        return False
    if bootstrap.get("status") not in {"bootstrapped", "applied"}:
        return False
    if not str(bootstrap.get("apply_id") or "").strip():
        return False
    plan = set(_strings(bootstrap.get("participant_plan")))
    if not {"architect", "review", "execute"}.issubset(plan):
        return False
    participants = _dict(inspector.get("participants"))
    summary = _dict(participants.get("summary"))
    required_roles = ("init", "architect", "review", "execute")
    return all(int(summary.get(role) or 0) >= 1 for role in required_roles)


def _closure_chain(
    *,
    conversation_id: str,
    bootstrap: dict[str, Any],
    inspector: dict[str, Any],
    collaboration: dict[str, Any],
    blockers: dict[str, Any],
    queue: dict[str, Any],
    latency: dict[str, Any],
) -> dict[str, bool]:
    chain: dict[str, Any] = {
        "structured_collaboration": False,
        "review_veto_lifecycle": False,
        "dispatch_gate_lifecycle": False,
        "agent_auto_dispatch": False,
        "real_provider_mcp_writeback": False,
        "run_id": None,
        "proposal_ref": None,
        "artifact_ref": None,
        "blocker_id": None,
        "dispatch_entry_id": None,
        "dispatch_evidence": None,
        "provider_run_ref": None,
        "inbox_id": None,
        "blocked_gate_id": None,
        "allowed_gate_id": None,
    }
    conversation = _dict(inspector.get("conversation"))
    inspector_conversation_id = str(conversation.get("id") or "").strip()
    bootstrap_conversation_id = str(bootstrap.get("conversation_id") or "").strip()
    if (
        not conversation_id
        or conversation_id != inspector_conversation_id
        or conversation_id != bootstrap_conversation_id
    ):
        return chain

    runs = {
        str(run.get("run_id") or ""): run
        for run in _dicts(collaboration.get("runs"))
        if str(run.get("run_id") or "").strip()
    }
    blocker_rows = _dicts(blockers.get("items"))
    gate_rows = _dicts(collaboration.get("dispatch_gates"))
    turns = _dicts(latency.get("recent_turns"))
    if any(
        turn.get("delivery_mode") == "stdout_fallback"
        or turn.get("degraded_reason") == "stdout_fallback"
        for turn in turns
    ):
        return chain
    turns_by_inbox = {
        str(turn.get("inbox_item_id") or ""): turn
        for turn in turns
        if str(turn.get("inbox_item_id") or "").strip()
    }
    for entry in _dicts(queue.get("entries")):
        if not _is_dispatched_agent_entry(entry):
            continue
        run_id = str(entry.get("collaboration_run_id") or "")
        proposal_ref = f"proposal:{entry.get('proposal_id')}"
        artifact_ref = str(entry.get("artifact_ref") or "")
        run = runs.get(run_id)
        if run is None:
            continue
        execute_response = _valid_structured_run(
            run,
            proposal_ref=proposal_ref,
            artifact_ref=artifact_ref,
        )
        if execute_response is None:
            continue
        chain["structured_collaboration"] = True
        chain["run_id"] = run_id
        chain["proposal_ref"] = proposal_ref
        chain["artifact_ref"] = artifact_ref

        blocker = _matching_resolved_review_veto(blocker_rows, run_id)
        if blocker is None:
            continue
        chain["review_veto_lifecycle"] = True
        chain["blocker_id"] = str(blocker.get("blocker_id") or "")

        gate_pair = _matching_gate_pair(
            gate_rows,
            run_id=run_id,
            proposal_ref=proposal_ref,
            artifact_ref=artifact_ref,
            resolved_at=str(blocker.get("resolved_at") or ""),
            execute_response_created_at=str(execute_response.get("created_at") or ""),
        )
        if gate_pair is None:
            continue
        chain["dispatch_gate_lifecycle"] = True
        chain["agent_auto_dispatch"] = True
        chain["blocked_gate_id"] = str(gate_pair[0].get("event_id") or "")
        chain["allowed_gate_id"] = str(gate_pair[1].get("event_id") or "")
        chain["allowed_gate_created_at"] = str(gate_pair[1].get("created_at") or "")
        chain["dispatch_entry_id"] = str(entry.get("entry_id") or "")
        chain["dispatch_evidence"] = str(entry.get("dispatch_evidence") or "")
        chain["provider_run_ref"] = str(entry.get("provider_run_ref") or "")

        inbox_id = _mcp_writeback_inbox_id(entry)
        if inbox_id is None:
            continue
        turn = turns_by_inbox.get(inbox_id)
        if not turn:
            continue
        if not _valid_mcp_writeback_turn(turn):
            continue
        chain["real_provider_mcp_writeback"] = True
        chain["inbox_id"] = inbox_id
        return chain
    return chain


def _valid_structured_run(
    run: dict[str, Any],
    *,
    proposal_ref: str,
    artifact_ref: str,
) -> dict[str, Any] | None:
    if run.get("orchestration_mode") != "peer_consensus":
        return None
    if str(run.get("status") or "") != "done":
        return None
    targets = set(_strings(run.get("targets")))
    if not {"review", "execute"}.issubset(targets):
        return None
    responses = _dicts(run.get("responses"))
    received_by_target = {
        str(response.get("target") or ""): response
        for response in responses
        if response.get("status") == "received"
        and str(response.get("content") or "").strip()
    }
    if "review" not in received_by_target:
        return None
    execute_response = received_by_target.get("execute")
    if execute_response is None:
        return None
    if not _valid_execute_feasibility_verdict(
        str(execute_response.get("content") or ""),
        proposal_ref=proposal_ref,
        artifact_ref=artifact_ref,
    ):
        return None
    return execute_response


def _valid_execute_feasibility_verdict(
    content: str,
    *,
    proposal_ref: str,
    artifact_ref: str,
) -> bool:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    if payload.get("type") != "execute_feasibility_verdict":
        return False
    if payload.get("status") != "executable":
        return False
    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        return False
    refs = _strings(payload.get("evidence_refs"))
    return bool(refs) and proposal_ref in refs and artifact_ref in refs


def _matching_resolved_review_veto(
    blockers: list[dict[str, Any]],
    run_id: str,
) -> dict[str, Any] | None:
    for blocker in blockers:
        if str(blocker.get("run_id") or "") != run_id:
            continue
        if blocker.get("issuer") != "review":
            continue
        if blocker.get("severity") != "veto":
            continue
        if blocker.get("blocks_dispatch") is not True:
            continue
        if blocker.get("active") is not False:
            continue
        if not str(blocker.get("resolution_evidence") or "").strip():
            continue
        if not str(blocker.get("resolved_at") or "").strip():
            continue
        return blocker
    return None


def _matching_gate_pair(
    gates: list[dict[str, Any]],
    *,
    run_id: str,
    proposal_ref: str,
    artifact_ref: str,
    resolved_at: str,
    execute_response_created_at: str,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    matching = [
        gate
        for gate in gates
        if str(gate.get("run_id") or "") == run_id
        and str(gate.get("proposal_ref") or "") == proposal_ref
        and str(gate.get("artifact_ref") or "") == artifact_ref
    ]
    blocked = [
        gate for gate in matching if gate.get("decision") == "blocked_active_veto"
    ]
    allowed = [
        gate
        for gate in matching
        if gate.get("decision") == "allowed"
        and gate.get("execute_confirmed") is True
        and gate.get("policy_allows_real_provider") is True
    ]
    resolved_time = _parse_timestamp(resolved_at)
    execute_time = _parse_timestamp(execute_response_created_at)
    if resolved_time is None or execute_time is None:
        return None
    for blocked_gate in blocked:
        blocked_time = _parse_timestamp(str(blocked_gate.get("created_at") or ""))
        if blocked_time is None:
            continue
        for allowed_gate in allowed:
            allowed_time = _parse_timestamp(str(allowed_gate.get("created_at") or ""))
            if allowed_time is None:
                continue
            if (
                blocked_time < resolved_time <= allowed_time
                and execute_time <= allowed_time
            ):
                return blocked_gate, allowed_gate
    return None


def _valid_mcp_writeback_turn(turn: dict[str, Any]) -> bool:
    if turn.get("target_role") != "execute":
        return False
    if turn.get("delivery_mode") != "mcp_writeback":
        return False
    if turn.get("degraded_reason") is not None:
        return False
    stages = _dict(turn.get("stage_timings"))
    ordered_stage_names = [
        "ray_actor_delivery_start",
        "codex_app_server_turn_start",
        "chat_post_message",
        "trace_persisted",
    ]
    stage_times: list[float] = []
    for name in ordered_stage_names:
        stage = _dict(stages.get(name))
        at = stage.get("at")
        if isinstance(at, bool) or not isinstance(at, (int, float)):
            return False
        stage_time = float(at)
        if not math.isfinite(stage_time):
            return False
        stage_times.append(stage_time)
    return stage_times == sorted(stage_times)


def _has_tui_dashboard_read_surface(
    timeline: dict[str, Any],
    *,
    conversation_id: str,
    chain: dict[str, Any],
) -> bool:
    if timeline.get("source_authority") != "chat_inspector":
        return False
    if str(timeline.get("conversation_id") or "") != conversation_id:
        return False
    events = _dicts(timeline.get("events"))
    return (
        _has_event(events, event_type="bootstrap", status="bootstrapped")
        and _has_event(
            events,
            event_type="collaboration_run",
            status="done",
            event_id=str(chain.get("run_id") or ""),
            refs={"run_id": chain.get("run_id")},
        )
        and _has_event(
            events,
            event_type="blocker_resolved",
            status="resolved",
            event_id=str(chain.get("blocker_id") or ""),
            refs={"run_id": chain.get("run_id")},
        )
        and _has_event(
            events,
            event_type="dispatch_gate",
            status="blocked_active_veto",
            refs={
                "run_id": chain.get("run_id"),
                "proposal_ref": chain.get("proposal_ref"),
                "artifact_ref": chain.get("artifact_ref"),
            },
        )
        and _has_event(
            events,
            event_type="dispatch_gate",
            status="allowed",
            refs={
                "run_id": chain.get("run_id"),
                "proposal_ref": chain.get("proposal_ref"),
                "artifact_ref": chain.get("artifact_ref"),
            },
        )
        and _has_event(
            events,
            event_type="dispatch_queue",
            status="dispatched",
            event_id=str(chain.get("dispatch_entry_id") or ""),
            refs={
                "entry_id": chain.get("dispatch_entry_id"),
                "dispatch_evidence": chain.get("dispatch_evidence"),
            },
        )
        and _has_event(
            events,
            event_type="provider_writeback",
            status="mcp_writeback",
            event_id=str(chain.get("inbox_id") or ""),
            refs={
                "inbox_item_id": chain.get("inbox_id"),
                "dispatch_queue_entry_id": chain.get("dispatch_entry_id"),
            },
        )
    )


def _has_official_tui_main_path_evidence(
    evidence: dict[str, Any],
    *,
    conversation_id: str,
    timeline: dict[str, Any],
    chain: dict[str, Any],
) -> bool:
    if str(evidence.get("conversation_id") or "") != conversation_id:
        return False
    changed_paths = _strings(evidence.get("changed_paths"))
    if not any(path.startswith("xmuse/tui/") for path in changed_paths):
        return False
    closure_time = _parse_timestamp(str(chain.get("allowed_gate_created_at") or ""))
    if closure_time is None:
        return False
    if not _has_official_tui_code_modification(
        _dicts(evidence.get("code_modifications")),
        changed_paths=set(changed_paths),
        chain=chain,
        closure_time=closure_time,
    ):
        return False
    command_events = _dicts(evidence.get("command_events"))
    linked_ids = set(_strings(evidence.get("runtime_timeline_event_ids")))
    required_chain_ids = {
        str(chain.get("run_id") or ""),
        str(chain.get("blocker_id") or ""),
        str(chain.get("blocked_gate_id") or ""),
        str(chain.get("allowed_gate_id") or ""),
        str(chain.get("dispatch_entry_id") or ""),
        str(chain.get("inbox_id") or ""),
    }
    required_chain_ids.discard("")
    if not required_chain_ids or not required_chain_ids.issubset(linked_ids):
        return False
    timeline_ids = {
        str(event.get("event_id") or "")
        for event in _dicts(timeline.get("events"))
        if str(event.get("event_id") or "").strip()
    }
    if not linked_ids or not linked_ids.issubset(timeline_ids):
        return False
    commands = {
        str(event.get("command") or ""): event
        for event in command_events
        if str(event.get("conversation_id") or "") == conversation_id
        and str(event.get("read_surface_authority") or "")
        in {"chat_inspector", "dashboard_runtime_timeline"}
        and _surface_ref_matches_authority(
            surface_ref=str(event.get("surface_ref") or ""),
            authority=str(event.get("read_surface_authority") or ""),
            conversation_id=conversation_id,
            linked_ids=linked_ids,
        )
    }
    required_commands = {"/new", "/overview", "/discussion", "/blockers"}
    if not required_commands.issubset(commands):
        return False
    for command in required_commands:
        command_time = _parse_timestamp(str(commands[command].get("created_at") or ""))
        if command_time is None or command_time < closure_time:
            return False
    return True


def _has_official_tui_code_modification(
    modifications: list[dict[str, Any]],
    *,
    changed_paths: set[str],
    chain: dict[str, Any],
    closure_time: datetime,
) -> bool:
    for modification in modifications:
        path = str(modification.get("path") or "").strip()
        if path not in changed_paths:
            continue
        if not path.startswith("xmuse/tui/"):
            continue
        if str(modification.get("dispatch_entry_id") or "") != str(
            chain.get("dispatch_entry_id") or ""
        ):
            continue
        if str(modification.get("provider_run_ref") or "") != str(
            chain.get("provider_run_ref") or ""
        ):
            continue
        changed_at = _parse_timestamp(str(modification.get("changed_at") or ""))
        if changed_at is None or changed_at < closure_time:
            continue
        before_sha = str(modification.get("before_sha256") or "").strip()
        after_sha = str(modification.get("after_sha256") or "").strip()
        if not _is_sha256(before_sha) or not _is_sha256(after_sha):
            continue
        if before_sha == after_sha:
            continue
        if not str(modification.get("diff_summary") or "").strip():
            continue
        return True
    return False


def _has_runner_dispatch_bridge_evidence(
    runner_operations: dict[str, Any],
    *,
    conversation_id: str,
    chain: dict[str, Any],
) -> bool:
    bridge = _dict(runner_operations.get("chat_dispatch_bridge"))
    if bridge.get("status") != "observed":
        return False
    dispatched = _safe_int(bridge.get("dispatched"))
    if dispatched is None or dispatched < 1:
        return False
    latest = _dict(bridge.get("latest"))
    return (
        str(latest.get("entry_id") or "") == str(chain.get("dispatch_entry_id") or "")
        and str(latest.get("conversation_id") or "") == conversation_id
        and latest.get("status") == "dispatched"
        and latest.get("source") == "agent"
        and latest.get("target") == "execute"
        and latest.get("auto_execute") is True
        and str(latest.get("proposal_id") or "") == _proposal_id_from_ref(
            str(chain.get("proposal_ref") or "")
        )
        and str(latest.get("collaboration_run_id") or "")
        == str(chain.get("run_id") or "")
        and str(latest.get("artifact_ref") or "") == str(chain.get("artifact_ref") or "")
        and str(latest.get("dispatch_evidence") or "")
        == str(chain.get("dispatch_evidence") or "")
    )


def _proposal_id_from_ref(proposal_ref: str) -> str:
    prefix = "proposal:"
    if not proposal_ref.startswith(prefix):
        return ""
    return proposal_ref.removeprefix(prefix).strip()


def _has_terminal_tui_demo_evidence(
    evidence: dict[str, Any],
    *,
    conversation_id: str,
    timeline: dict[str, Any],
    chain: dict[str, Any],
) -> bool:
    if str(evidence.get("conversation_id") or "") != conversation_id:
        return False
    if str(evidence.get("mode") or "") != "terminal":
        return False
    if str(evidence.get("evidence_source") or "") != TERMINAL_TUI_DEMO_EVIDENCE_SOURCE:
        return False
    if evidence.get("harness_version") != TERMINAL_TUI_DEMO_HARNESS_VERSION:
        return False
    if _exact_string_list(evidence.get("scripted_inputs")) != terminal_tui_demo_scripted_inputs(
        conversation_id
    ):
        return False
    terminal_run_id = str(evidence.get("terminal_run_id") or "").strip()
    if not terminal_run_id:
        return False
    command = str(evidence.get("command") or "")
    if not is_terminal_tui_launch_command(command):
        return False
    exit_code = evidence.get("exit_code")
    if type(exit_code) is not int or exit_code != 0:
        return False
    started_at = _parse_timestamp(str(evidence.get("started_at") or ""))
    completed_at = _parse_timestamp(str(evidence.get("completed_at") or ""))
    closure_time = _parse_timestamp(str(chain.get("allowed_gate_created_at") or ""))
    if started_at is None or completed_at is None or closure_time is None:
        return False
    if not (closure_time <= started_at <= completed_at):
        return False
    if not _has_terminal_run_command_event_evidence(
        evidence,
        conversation_id=conversation_id,
        terminal_run_id=terminal_run_id,
        started_at=started_at,
        completed_at=completed_at,
    ):
        return False
    visible_surfaces = set(_strings(evidence.get("visible_surfaces")))
    required_surfaces = {
        "init",
        "overview",
        "discussion",
        "blockers",
        "dispatch",
        "provider_writeback",
        "resume",
    }
    if not required_surfaces.issubset(visible_surfaces):
        return False
    linked_ids = set(_strings(evidence.get("runtime_timeline_event_ids")))
    required_chain_ids = {
        str(chain.get("run_id") or ""),
        str(chain.get("blocker_id") or ""),
        str(chain.get("blocked_gate_id") or ""),
        str(chain.get("allowed_gate_id") or ""),
        str(chain.get("dispatch_entry_id") or ""),
        str(chain.get("inbox_id") or ""),
    }
    required_chain_ids.discard("")
    if not required_chain_ids or not required_chain_ids.issubset(linked_ids):
        return False
    timeline_ids = {
        str(event.get("event_id") or "")
        for event in _dicts(timeline.get("events"))
        if str(event.get("event_id") or "").strip()
    }
    return bool(linked_ids) and linked_ids.issubset(timeline_ids)


def _has_terminal_run_command_event_evidence(
    evidence: dict[str, Any],
    *,
    conversation_id: str,
    terminal_run_id: str,
    started_at: datetime,
    completed_at: datetime,
) -> bool:
    events = _dicts(evidence.get("observed_command_events"))
    if not events:
        return False
    expected_commands = []
    for scripted_input in terminal_tui_demo_scripted_inputs(conversation_id):
        command, _, _ = scripted_input.partition(" ")
        expected_commands.append(command)
    event_ids = set(_exact_string_list(evidence.get("observed_command_event_ids")))
    if not event_ids:
        return False
    observed_commands: set[str] = set()
    for event in events:
        event_id = str(event.get("event_id") or "").strip()
        if not event_id or event_id not in event_ids:
            return False
        if str(event.get("terminal_run_id") or "") != terminal_run_id:
            return False
        if str(event.get("conversation_id") or "") != conversation_id:
            return False
        if str(event.get("read_surface_authority") or "") != "chat_inspector":
            return False
        if str(event.get("surface_ref") or "") != f"chat_inspector:{conversation_id}":
            return False
        command = str(event.get("command") or "")
        if command not in expected_commands:
            return False
        created_at = _parse_timestamp(str(event.get("created_at") or ""))
        if created_at is None or not (started_at <= created_at <= completed_at):
            return False
        observed_commands.add(command)
    return set(expected_commands).issubset(observed_commands)


def _surface_ref_matches_authority(
    *,
    surface_ref: str,
    authority: str,
    conversation_id: str,
    linked_ids: set[str],
) -> bool:
    if surface_ref in linked_ids:
        return True
    return surface_ref == f"{authority}:{conversation_id}"


def _has_event(
    events: list[dict[str, Any]],
    *,
    event_type: str,
    status: str,
    event_id: str | None = None,
    refs: dict[str, Any] | None = None,
) -> bool:
    for event in events:
        if str(event.get("event_type") or "") != event_type:
            continue
        if str(event.get("status") or "") != status:
            continue
        if event_id is not None and str(event.get("event_id") or "") != event_id:
            continue
        event_refs = _dict(event.get("refs"))
        if refs and any(
            str(event_refs.get(key) or "") != str(value or "")
            for key, value in refs.items()
        ):
            continue
        return True
    return False


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _has_clean_process_cleanup(cleanup: dict[str, Any]) -> bool:
    cleanup = _normalized_process_cleanup(cleanup)
    required = {
        "leftover_codex_app_server",
        "leftover_raylet",
        "leftover_gcs_server",
        "leftover_ray_worker",
    }
    if not required.issubset(cleanup):
        return False
    return not any(
        bool(cleanup.get(name))
        for name in (
            *required,
            "unknown_leftover_process",
            "runner_cleanup_not_clean",
            "contradictory_cleanup_evidence",
            "malformed_cleanup_evidence",
        )
    )


def _normalized_process_cleanup(cleanup: dict[str, Any]) -> dict[str, Any]:
    required = {
        "leftover_codex_app_server",
        "leftover_raylet",
        "leftover_gcs_server",
        "leftover_ray_worker",
    }
    has_runner_cleanup_shape = "status" in cleanup or "leftovers" in cleanup
    if not has_runner_cleanup_shape:
        return cleanup

    status = str(cleanup.get("status") or "").strip()
    leftovers = cleanup.get("leftovers")
    if status not in {"clean", "dirty"} or not isinstance(leftovers, list):
        return {
            **{name: False for name in required},
            "malformed_cleanup_evidence": True,
        }
    if status == "clean" and not leftovers:
        if any(bool(cleanup.get(name)) for name in required if name in cleanup):
            return {
                **{name: False for name in required},
                "contradictory_cleanup_evidence": True,
            }
        return {name: False for name in required}

    codes = set()
    malformed_leftover_rows = False
    for item in leftovers:
        if not isinstance(item, dict):
            malformed_leftover_rows = True
            continue
        codes.add(str(item.get("code") or "").strip())
    normalized = {name: name in codes for name in required}
    if status != "clean":
        normalized["runner_cleanup_not_clean"] = True
    if malformed_leftover_rows or (leftovers and any(code not in required for code in codes)):
        normalized["unknown_leftover_process"] = True
    return normalized


def _is_dispatched_agent_entry(entry: dict[str, Any]) -> bool:
    return (
        entry.get("source") == "agent"
        and entry.get("target") == "execute"
        and entry.get("status") == "dispatched"
        and entry.get("auto_execute") is True
        and entry.get("dispatch_policy") == "real_provider_allowed"
        and bool(str(entry.get("proposal_id") or "").strip())
        and bool(str(entry.get("resolution_id") or "").strip())
        and bool(str(entry.get("collaboration_run_id") or "").strip())
        and bool(str(entry.get("provider_run_ref") or "").strip())
    )


def _mcp_writeback_inbox_id(entry: dict[str, Any]) -> str | None:
    evidence = str(entry.get("dispatch_evidence") or "")
    prefix = "mcp_writeback:"
    if not evidence.startswith(prefix):
        return None
    inbox_id = evidence.removeprefix(prefix).strip()
    return inbox_id or None


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _exact_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    if not all(isinstance(item, str) for item in value):
        return []
    return list(value)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdefABCDEF" for char in value)


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
