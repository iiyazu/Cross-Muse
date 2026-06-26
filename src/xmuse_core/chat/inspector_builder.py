from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.collaboration_store import ChatCollaborationStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _find_conversation_graph_ids(xmuse_root: Path, conversation_id: str) -> set[str]:
    """Return all graph IDs whose lane-graph file belongs to this conversation."""
    graph_ids: set[str] = set()
    lg_dir = xmuse_root / "lane_graphs"
    if not lg_dir.is_dir():
        return graph_ids
    for path in sorted(lg_dir.glob("*.json")):
        data = _read_json(path)
        if not isinstance(data, dict):
            continue
        if data.get("conversation_id") == conversation_id:
            gid = data.get("id") or path.stem
            if isinstance(gid, str) and gid:
                graph_ids.add(gid)
    return graph_ids


def _participant_provider_summary(participant_rows: list[Any]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], int] = {}
    for participant in participant_rows:
        provider_id = str(participant.provider_id)
        cli_kind = str(participant.cli_kind)
        key = (provider_id, cli_kind)
        grouped[key] = grouped.get(key, 0) + 1
    return [
        {"provider_id": provider_id, "cli_kind": cli_kind, "count": count}
        for (provider_id, cli_kind), count in sorted(grouped.items())
    ]


def _closure_evidence_summary(db_path: Path, conversation_id: str) -> dict[str, Any]:
    spines = AcceptanceSpineStore(db_path).list_by_conversation(conversation_id)
    status_summary: dict[str, int] = {}
    proposal_review_refs: list[str] = []
    independent_review_refs: list[str] = []
    dispatch_ack_refs: list[str] = []
    lane_execution_refs: list[str] = []
    items: list[dict[str, Any]] = []

    for spine in spines:
        status_summary[spine.status.value] = status_summary.get(spine.status.value, 0) + 1
        if spine.review_or_execute_verdict_ref:
            proposal_review_refs.append(spine.review_or_execute_verdict_ref)
        if spine.review_verdict_ref:
            independent_review_refs.append(spine.review_verdict_ref)
        ack_refs = _dispatch_ack_refs(spine.execution_evidence_refs)
        lane_refs = _lane_execution_refs(spine.execution_evidence_refs)
        dispatch_ack_refs.extend(ack_refs)
        lane_execution_refs.extend(lane_refs)
        items.append(
            {
                "spine_id": spine.spine_id,
                "status": spine.status.value,
                "intake_message_id": spine.intake_message_id,
                "proposal_id": spine.proposal_id,
                "review_trigger_inbox_id": spine.review_trigger_inbox_id,
                "proposal_review_ref": spine.review_or_execute_verdict_ref,
                "dispatch_item_id": spine.dispatch_item_id,
                "dispatch_ack_refs": ack_refs,
                "lane_execution_refs": lane_refs,
                "independent_review_ref": spine.review_verdict_ref,
                "final_action_ref": spine.final_action_ref,
                "github_gate_evidence_ref": spine.github_gate_evidence_ref,
                "blocked_reason": spine.blocked_reason,
                "manual_gaps": spine.manual_gaps,
                "created_at": spine.created_at,
                "updated_at": spine.updated_at,
            }
        )

    return {
        "source_authority": "chat.db.acceptance_spines",
        "total": len(spines),
        "status_summary": status_summary,
        "proposal_review": {
            "total": len(proposal_review_refs),
            "refs": proposal_review_refs,
        },
        "dispatch_ack": {
            "total": len(dispatch_ack_refs),
            "refs": dispatch_ack_refs,
        },
        "lane_execution": {
            "total": len(lane_execution_refs),
            "refs": lane_execution_refs,
        },
        "independent_review": {
            "total": len(independent_review_refs),
            "refs": independent_review_refs,
        },
        "items": items,
    }


def _dispatch_ack_refs(evidence_refs: list[str]) -> list[str]:
    prefixes = (
        "mcp_writeback:",
        "peer_ack:",
        "chat_dispatch_queue#entry=",
    )
    return [ref for ref in evidence_refs if ref.startswith(prefixes)]


def _lane_execution_refs(evidence_refs: list[str]) -> list[str]:
    prefixes = (
        "feature_lanes.json#lane=",
        "lane_graph:",
        "dispatch_attempt:",
        "provider_session_binding:",
    )
    return [ref for ref in evidence_refs if ref.startswith(prefixes)]


def build_conversation_inspector_payload(
    conversation_id: str,
    xmuse_root: Path,
) -> dict[str, Any]:
    """Single authoritative builder for conversation inspector across all surfaces."""
    db_path = xmuse_root / "chat.db"
    chat = ChatStore(db_path)
    participants = ParticipantStore(db_path)
    inbox = ChatInboxStore(db_path)
    peer = PeerChatService(db_path)

    conversation = next(
        (c for c in chat.list_conversations() if c.id == conversation_id), None
    )
    if conversation is None:
        raise KeyError(f"conversation not found: {conversation_id}")

    # Participants
    participant_rows = participants.list_by_conversation(conversation_id)
    role_counts: dict[str, int] = {}
    for p in participant_rows:
        role_counts[p.role] = role_counts.get(p.role, 0) + 1

    # Inbox per participant
    all_inbox = inbox.list_by_conversation(conversation_id, include_terminal=True)
    inbox_by_pid: dict[str, dict[str, int]] = {}
    for item in all_inbox:
        pid = item.target_participant_id or "__unknown__"
        if pid not in inbox_by_pid:
            inbox_by_pid[pid] = {"unread": 0, "claimed": 0, "read": 0, "failed": 0}
        ist = item.status
        if ist in inbox_by_pid[pid]:
            inbox_by_pid[pid][ist] += 1
    inbox_summary = [
        {"participant_id": pid, **counts} for pid, counts in inbox_by_pid.items()
    ]

    # Timeline
    timeline = peer.list_conversation_timeline(conversation_id)
    messages = timeline.get("messages", [])
    cards = timeline.get("cards", [])

    # Blueprint, feature plan, graph set from cards
    bp: dict[str, Any] | None = None
    fp: dict[str, Any] | None = None
    gs: dict[str, Any] | None = None
    for card in cards:
        ct = card.get("card_type")
        if ct == "mission_blueprint" and bp is None:
            bp = {
                "id": card.get("source_id"), "title": card.get("title"),
                "summary": card.get("summary"), "status": card.get("status"),
            }
        elif ct == "feature_plan" and fp is None:
            fp = {
                "id": card.get("source_id"), "title": card.get("title"),
                "status": card.get("status"),
                "feature_count": card.get("counts", {}).get("features", 0),
            }
        elif ct == "feature_graph_set" and gs is None:
            gs = {
                "id": card.get("source_id"), "title": card.get("title"),
                "status": card.get("status"),
                "lane_graph_count": card.get("counts", {}).get("lane_graphs", 0),
            }

    # Session health — conversation-scoped. ``active_sessions.json`` is the
    # older operations surface; live Ray GOD sessions are durable in
    # ``god_sessions.json``.
    raw_sessions = _read_session_rows(xmuse_root)
    conv_sessions = [
        s for s in raw_sessions
        if isinstance(s, dict) and s.get("conversation_id") == conversation_id
    ]
    session_status_counts: dict[str, int] = {}
    for s in conv_sessions:
        st = s.get("status", "unknown")
        session_status_counts[st] = session_status_counts.get(st, 0) + 1

    # Graph worklist — conversation-scoped
    lanes_payload = _read_json(xmuse_root / "feature_lanes.json", {"lanes": []})
    raw_lanes = lanes_payload.get("lanes") if isinstance(lanes_payload, dict) else []
    if not isinstance(raw_lanes, list):
        raw_lanes = []
    conv_lanes = [
        ln for ln in raw_lanes
        if isinstance(ln, dict) and ln.get("conversation_id") == conversation_id
    ]
    lane_summary: dict[str, int] = {}
    for ln in conv_lanes:
        lst = ln.get("status", "unknown")
        lane_summary[lst] = lane_summary.get(lst, 0) + 1

    # Authoritative graph — conversation-scoped via spawned_conversation_id or lane_graph lookup
    conv_graph_ids = _find_conversation_graph_ids(xmuse_root, conversation_id)
    lineage_payload = _read_json(xmuse_root / "self_evolution" / "lineage.json", {"lineage": []})
    auth_graph_id: str | None = None
    if isinstance(lineage_payload, dict):
        raw_lg = lineage_payload.get("lineage", [])
        if isinstance(raw_lg, list):
            # Prefer direct spawned_conversation_id match
            matching = [
                r for r in raw_lg if isinstance(r, dict)
                and r.get("spawned_conversation_id") == conversation_id
                and r.get("spawned_graph_id")
            ]
            # Fall back to graph ID set from lane_graphs/ files
            if not matching and conv_graph_ids:
                matching = [
                    r for r in raw_lg if isinstance(r, dict)
                    and r.get("spawned_graph_id") in conv_graph_ids
                ]
            if matching:
                matching.sort(key=lambda r: str(r.get("created_at", "")), reverse=True)
                auth_graph_id = str(matching[0].get("spawned_graph_id"))

    # Artifacts from proposals + resolutions
    proposals = chat.list_proposals(conversation_id)
    artifact_items: list[dict[str, Any]] = []
    for prop in proposals:
        artifact_items.append({
            "type": "proposal",
            "subtype": prop.proposal_type,
            "id": prop.id,
            "title": prop.content[:80] if prop.content else "",
            "status": prop.status.value,
            "created_at": prop.created_at,
        })
    resolutions = chat.list_resolutions(conversation_id)
    for res in resolutions:
        ctype = res.content.get("type", "resolution")
        artifact_items.append({
            "type": ctype,
            "id": res.id,
            "title": res.goal_summary,
            "status": res.status.value,
            "version": res.version,
            "created_at": res.created_at,
        })

    # Degradation — conversation-scoped via lane_id cross-reference
    conv_lane_ids = {ln.get("feature_id") for ln in conv_lanes if ln.get("feature_id")}
    raw_errors: list[dict] = []
    if conv_lane_ids:
        err_payload = _read_json(xmuse_root / "error_knowledge.json", {})
        if isinstance(err_payload, dict):
            all_entries = err_payload.get("entries") or err_payload.get("errors") or []
            raw_errors = [
                e for e in all_entries if isinstance(e, dict)
                and e.get("lane_id") in conv_lane_ids
            ]
    error_summary = [
        {"id": e.get("entry_id") or e.get("id", f"err-{i}"),
         "message": e.get("message") or e.get("pit", "")}
        for i, e in enumerate(raw_errors[:5])
    ]

    peer_latency = PeerTurnLatencyTraceStore(db_path).list_recent(conversation_id, limit=20)
    collaboration_store = ChatCollaborationStore(db_path)
    collaboration_runs = collaboration_store.list_runs(conversation_id)
    collaboration_blockers = collaboration_store.list_blockers(conversation_id)
    collaboration_gate_events = collaboration_store.list_dispatch_gate_events(conversation_id)
    active_blockers = [blocker for blocker in collaboration_blockers if blocker.active]
    dispatch_entries = ChatDispatchQueueStore(db_path).list_entries(conversation_id)
    queued_dispatch_entries = [entry for entry in dispatch_entries if entry.status == "queued"]
    processing_dispatch_entries = [
        entry for entry in dispatch_entries if entry.status == "processing"
    ]
    dispatched_dispatch_entries = [
        entry for entry in dispatch_entries if entry.status == "dispatched"
    ]
    failed_dispatch_entries = [
        entry for entry in dispatch_entries if entry.status == "failed"
    ]
    closure_evidence = _closure_evidence_summary(db_path, conversation_id)

    return {
        "conversation": conversation.model_dump(mode="json"),
        "participants": {
            "total": len(participant_rows),
            "summary": role_counts,
            "provider_summary": _participant_provider_summary(participant_rows),
            "items": [p.model_dump(mode="json") for p in participant_rows],
            "inbox_summary": inbox_summary,
        },
        "session_health": {
            "total": len(conv_sessions),
            "by_status": session_status_counts,
            "items": conv_sessions,
        },
        "graph_worklist": {
            "authoritative_graph_id": auth_graph_id,
            "total_lanes": len(conv_lanes),
            "lane_summary": lane_summary,
        },
        "artifacts": {
            "total": len(artifact_items),
            "items": artifact_items,
        },
        "degradation": {
            "error_count": len(raw_errors),
            "errors": error_summary,
        },
        "peer_latency": {
            "recent_turns": peer_latency,
        },
        "collaboration": {
            "total_runs": len(collaboration_runs),
            "active_runs": len([
                run for run in collaboration_runs
                if run.status.value in {"running", "partial"}
            ]),
            "runs": [
                {
                    "run_id": run.run_id,
                    "status": run.status.value,
                    "orchestration_mode": run.orchestration_mode,
                    "initiator": run.initiator,
                    "targets": run.targets,
                    "callback_target": run.callback_target,
                    "response_count": len(run.responses),
                    "responses": [
                        {
                            "response_id": response.response_id,
                            "run_id": response.run_id,
                            "target": response.target,
                            "status": response.status,
                            "content": response.content,
                            "created_at": response.created_at,
                        }
                        for response in run.responses
                    ],
                    "blocker_count": len(run.blockers),
                    "created_at": run.created_at,
                    "updated_at": run.updated_at,
                }
                for run in collaboration_runs
            ],
            "dispatch_gates": [
                event.model_dump(mode="json")
                for event in collaboration_gate_events
            ],
        },
        "blockers": {
            "total": len(collaboration_blockers),
            "active": len(active_blockers),
            "items": [
                blocker.model_dump(mode="json")
                for blocker in collaboration_blockers
            ],
        },
        "dispatch_queue": {
            "total": len(dispatch_entries),
            "queued": len(queued_dispatch_entries),
            "processing": len(processing_dispatch_entries),
            "dispatched": len(dispatched_dispatch_entries),
            "failed": len(failed_dispatch_entries),
            "entries": [
                entry.model_dump(mode="json")
                for entry in dispatch_entries
            ],
        },
        "closure_evidence": closure_evidence,
        "recent_activity": {
            "message_count": len(messages),
            "card_count": len(cards),
            "messages": messages,
            "cards": cards,
        },
        "current_blueprint": bp,
        "current_feature_plan": fp,
        "current_graph_set": gs,
    }


def _read_session_rows(xmuse_root: Path) -> list[dict[str, Any]]:
    rows_by_key: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for filename in ("active_sessions.json", "god_sessions.json"):
        payload = _read_json(xmuse_root / filename, {})
        raw = payload.get("sessions") if isinstance(payload, dict) else []
        if not isinstance(raw, list):
            continue
        for item in raw:
            if not isinstance(item, dict):
                continue
            session_id = str(item.get("god_session_id") or "").strip()
            dedupe_key = session_id or json.dumps(item, sort_keys=True, default=str)
            if dedupe_key not in rows_by_key:
                ordered_keys.append(dedupe_key)
                rows_by_key[dedupe_key] = dict(item)
                continue
            rows_by_key[dedupe_key] = _merge_session_rows(
                rows_by_key[dedupe_key],
                item,
            )
    return [rows_by_key[key] for key in ordered_keys]


def _merge_session_rows(
    current: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    merged = dict(current)
    for key, value in incoming.items():
        if value is None:
            continue
        merged[key] = value
    return merged
