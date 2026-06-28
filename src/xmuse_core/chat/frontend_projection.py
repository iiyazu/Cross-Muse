from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

SOURCE_AUTHORITY = [
    "chat.db:conversations",
    "chat.db:messages",
    "chat.db:participants",
    "chat.db:chat_inbox_items",
    "chat.db:proposals",
    "chat.db:chat_dispatch_queue",
    "chat.db:collaboration_runs",
    "chat.db:collaboration_blockers",
    "chat.db:acceptance_spines",
    "chat.db:peer_turn_latency_traces",
    "final_actions.json",
    "active_sessions.json",
    "god_sessions.json",
]
_SUPPORTING_CONTEXT_SOURCE_REF_LIMIT = 20
_SUPPORTING_CONTEXT_SOURCE_REF_MAX_CHARS = 240


def build_peer_chat_ux_projection(
    conversation_id: str,
    xmuse_root: Path | str,
) -> dict[str, Any]:
    """Strictly read-only frontend projection for one peer chat conversation."""
    root = Path(xmuse_root)
    db_path = root / "chat.db"
    with _read_only_connection(db_path) as conn:
        conversation = _conversation(conn, conversation_id)
        if conversation is None:
            raise KeyError(f"conversation not found: {conversation_id}")
        participants = _participants(conn, conversation_id)
        inbox_items = _inbox_items(conn, conversation_id)
        messages = _messages(conn, conversation_id)
        proposals = _proposals(conn, conversation_id)
        dispatch_entries = _dispatch_entries(conn, conversation_id)
        collaboration_runs = _collaboration_runs(conn, conversation_id)
        blockers = _blockers(conn, conversation_id)
        closure_evidence = _closure_evidence(conn, conversation_id)
        supporting_context = _supporting_context(conn, conversation_id)
    sessions = _conversation_sessions(root, conversation_id)
    final_action_holds = _final_action_holds(root, closure_evidence)

    return {
        "schema_version": "peer_chat_ux_projection/v1",
        "projection_only": True,
        "write_capabilities": [],
        "source_authority": SOURCE_AUTHORITY,
        "conversation": conversation,
        "links": _links(conversation_id),
        "timeline": {
            "messages": messages,
            "items": _timeline_items(messages, proposals),
        },
        "cards": [_proposal_card(proposal) for proposal in proposals],
        "agent_cards": _agent_cards(
            participants=participants,
            inbox_items=inbox_items,
            sessions=sessions,
        ),
        "worklist": _worklist_items(
            conversation_id=conversation_id,
            inbox_items=inbox_items,
            dispatch_entries=dispatch_entries,
            blockers=blockers,
            final_action_holds=final_action_holds["items"],
        ),
        "artifacts": {
            "total": len(proposals),
            "items": [
                {
                    "type": "proposal",
                    "subtype": proposal.get("proposal_type"),
                    "id": proposal.get("id"),
                    "status": proposal.get("status"),
                    "created_at": proposal.get("created_at"),
                    "source_refs": proposal.get("references", []),
                }
                for proposal in proposals
            ],
        },
        "blockers": {
            "total": len(blockers),
            "active": sum(1 for blocker in blockers if blocker.get("active")),
            "items": blockers,
        },
        "dispatch_queue": {
            "total": len(dispatch_entries),
            "queued": sum(1 for entry in dispatch_entries if entry.get("status") == "queued"),
            "processing": sum(
                1 for entry in dispatch_entries if entry.get("status") == "processing"
            ),
            "dispatched": sum(
                1 for entry in dispatch_entries if entry.get("status") == "dispatched"
            ),
            "failed": sum(1 for entry in dispatch_entries if entry.get("status") == "failed"),
            "entries": dispatch_entries,
        },
        "collaboration": {
            "total_runs": len(collaboration_runs),
            "active_runs": sum(
                1 for run in collaboration_runs if run.get("status") in {"running", "partial"}
            ),
            "runs": collaboration_runs,
        },
        "supporting_context": supporting_context,
        "closure_evidence": closure_evidence,
        "final_action_holds": final_action_holds,
    }


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    if not db_path.is_file():
        raise KeyError("chat.db not found")
    uri = f"file:{db_path.as_posix()}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _conversation(conn: sqlite3.Connection, conversation_id: str) -> dict[str, Any] | None:
    row = _fetch_one(
        conn,
        "select id, title, created_at from conversations where id = ?",
        (conversation_id,),
    )
    return dict(row) if row is not None else None


def _participants(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        select participant_id, conversation_id, role, display_name, cli_kind, model,
               role_template_id, status, last_seen_at, created_at
        from participants
        where conversation_id = ?
        order by rowid asc
        """,
        (conversation_id,),
    )
    return [_participant_payload(row) for row in rows]


def _messages(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        select id, conversation_id, author, role, content, created_at,
               envelope_type, envelope_json, mentions_json, reply_to_message_id
        from messages
        where conversation_id = ?
        order by created_at asc, rowid asc
        limit 100
        """,
        (conversation_id,),
    )
    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "author": row["author"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
            "envelope_type": row["envelope_type"],
            "envelope_json": _json_object(row["envelope_json"]),
            "mentions": _json_list(row["mentions_json"]),
            "reply_to_message_id": row["reply_to_message_id"],
        }
        for row in rows
    ]


def _inbox_items(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        select id, conversation_id, target_participant_id, target_role,
               target_address, sender_participant_id, sender_address,
               source_message_id, item_type, payload_json, status, claim_owner,
               claimed_at, claim_expires_at, nudge_count, last_nudged_at,
               responded_message_id, failure_reason, created_at, updated_at
        from chat_inbox_items
        where conversation_id = ?
        order by rowid asc
        limit 200
        """,
        (conversation_id,),
    )
    return [
        {
            **dict(row),
            "payload": _json_object(row["payload_json"]),
            "nudge_count": int(row["nudge_count"] or 0),
        }
        for row in rows
    ]


def _proposals(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        select id, conversation_id, author, proposal_type, content,
               references_json, status, created_at, accepted_resolution_id
        from proposals
        where conversation_id = ?
        order by rowid asc
        limit 100
        """,
        (conversation_id,),
    )
    return [
        {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "author": row["author"],
            "proposal_type": row["proposal_type"],
            "content": row["content"],
            "references": _json_list(row["references_json"]),
            "status": row["status"],
            "created_at": row["created_at"],
            "accepted_resolution_id": row["accepted_resolution_id"],
        }
        for row in rows
    ]


def _dispatch_entries(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    gate_refs_expr = (
        "gate_refs_json"
        if _table_has_column(conn, "chat_dispatch_queue", "gate_refs_json")
        else "'[]' as gate_refs_json"
    )
    rows = _fetch_all(
        conn,
        f"""
        select entry_id, conversation_id, source, target, status, auto_execute,
               proposal_id, resolution_id, collaboration_run_id, artifact_ref,
               {gate_refs_expr}, dispatch_policy, claimed_by, claimed_at, provider_run_ref,
               dispatch_evidence, failure_reason, completed_at, created_at, updated_at
        from chat_dispatch_queue
        where conversation_id = ?
        order by rowid asc
        limit 100
        """,
        (conversation_id,),
    )
    entries: list[dict[str, Any]] = []
    for row in rows:
        entry = {
            **dict(row),
            "auto_execute": bool(row["auto_execute"]),
            "gate_refs": _json_list(row["gate_refs_json"]),
        }
        source_refs = _dispatch_source_refs(entry)
        entry["source_refs"] = source_refs
        entry["authority_boundary"] = _dispatch_authority_boundary()
        entry["sidecar_continuity"] = _dispatch_sidecar_continuity(source_refs)
        entries.append(entry)
    return entries


def _collaboration_runs(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        select run_id, conversation_id, goal, orchestration_mode, status,
               initiator, targets_json, callback_target, question, context_refs_json,
               timeout_s, max_depth, current_depth, created_at, updated_at
        from collaboration_runs
        where conversation_id = ?
        order by rowid asc
        limit 100
        """,
        (conversation_id,),
    )
    return [
        {
            **dict(row),
            "targets": _json_list(row["targets_json"]),
            "context_refs": _json_list(row["context_refs_json"]),
            "timeout_s": int(row["timeout_s"] or 0),
            "max_depth": int(row["max_depth"] or 0),
            "current_depth": int(row["current_depth"] or 0),
        }
        for row in rows
    ]


def _blockers(conn: sqlite3.Connection, conversation_id: str) -> list[dict[str, Any]]:
    rows = _fetch_all(
        conn,
        """
        select blocker_id, run_id, conversation_id, issuer, severity, reason,
               affected_ref, suggested_fix, active, blocks_dispatch,
               resolution_evidence, resolved_by, created_at, resolved_at
        from collaboration_blockers
        where conversation_id = ?
        order by rowid asc
        limit 100
        """,
        (conversation_id,),
    )
    return [
        {
            **dict(row),
            "active": bool(row["active"]),
            "blocks_dispatch": bool(row["blocks_dispatch"]),
        }
        for row in rows
    ]


def _closure_evidence(conn: sqlite3.Connection, conversation_id: str) -> dict[str, Any]:
    rows = _fetch_all(
        conn,
        """
        select spine_id, status, intake_message_id, proposal_id, review_trigger_inbox_id,
               review_or_execute_verdict_ref, dispatch_item_id,
               execution_evidence_refs_json, review_verdict_ref, final_action_ref,
               github_gate_evidence_ref, manual_gaps_json, blocked_reason,
               created_at, updated_at
        from acceptance_spines
        where conversation_id = ?
        order by rowid asc
        limit 100
        """,
        (conversation_id,),
    )
    items = []
    status_summary: dict[str, int] = {}
    for row in rows:
        status = str(row["status"] or "unknown")
        status_summary[status] = status_summary.get(status, 0) + 1
        items.append(
            {
                **dict(row),
                "execution_evidence_refs": _json_list(row["execution_evidence_refs_json"]),
                "manual_gaps": _json_list(row["manual_gaps_json"]),
            }
        )
    return {
        "source_authority": "chat.db.acceptance_spines",
        "total": len(items),
        "status_summary": status_summary,
        "items": items,
    }


def _supporting_context(conn: sqlite3.Connection, conversation_id: str) -> dict[str, Any]:
    rows = _fetch_all(
        conn,
        """
        select id, inbox_item_id, participant_id, target_role, supporting_context_json
        from peer_turn_latency_traces
        where conversation_id = ?
        order by writeback_at desc
        limit 50
        """,
        (conversation_id,),
    )
    memoryos_items = []
    status_summary: dict[str, int] = {}
    for row in rows:
        raw_context = _json_object(row["supporting_context_json"])
        memoryos_context = raw_context.get("memoryos_sidecar")
        if not isinstance(memoryos_context, dict):
            continue
        item = _memoryos_sidecar_projection(row, memoryos_context)
        status = str(item.get("status") or "unknown")
        status_summary[status] = status_summary.get(status, 0) + 1
        memoryos_items.append(item)
    return {
        "projection_only": True,
        "source_authority": ["chat.db:peer_turn_latency_traces.supporting_context_json"],
        "memoryos_sidecar": {
            "status_summary": status_summary,
            "latest": memoryos_items[:10],
        },
    }


def _memoryos_sidecar_projection(
    row: sqlite3.Row,
    context: dict[str, Any],
) -> dict[str, Any]:
    return {
        "trace_id": row["id"],
        "inbox_item_id": row["inbox_item_id"],
        "participant_id": row["participant_id"],
        "target_role": row["target_role"],
        "status": _projection_text(context.get("status")) or "unknown",
        "authority": _projection_text(context.get("authority")) or "memoryos_sidecar",
        "proof_level": _projection_text(context.get("proof_level")) or "unknown",
        "namespace_uri": _projection_text(context.get("namespace_uri")) or "unknown",
        "degraded_reason": _projection_text(context.get("degraded_reason")),
        "source_refs": _supporting_context_source_refs(context.get("source_refs")),
        "continuity_refs": _supporting_context_continuity_refs(context),
    }


def _conversation_sessions(root: Path, conversation_id: str) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    seen: set[str] = set()
    for filename in ("active_sessions.json", "god_sessions.json"):
        payload = _read_json_file(root / filename)
        raw_sessions = payload.get("sessions") if isinstance(payload, dict) else []
        if not isinstance(raw_sessions, list):
            continue
        for session in raw_sessions:
            if not isinstance(session, dict) or session.get("conversation_id") != conversation_id:
                continue
            key = str(session.get("god_session_id") or session.get("session_id") or len(seen))
            if key in seen:
                continue
            seen.add(key)
            sessions.append(dict(session))
    return sessions


def _links(conversation_id: str) -> dict[str, str]:
    base = f"/api/dashboard/peer-chat/conversations/{conversation_id}"
    return {
        "conversation_api_href": base,
        "inspector_api_href": f"{base}/inspector",
        "runtime_timeline_api_href": f"{base}/runtime-timeline",
        "dashboard_href": f"/dashboard/peer-chat/conversations/{conversation_id}",
    }


def _timeline_items(
    messages: list[dict[str, Any]],
    proposals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    items = [
        {"kind": "message", "created_at": message["created_at"], "message": message}
        for message in messages
    ]
    items.extend(
        {
            "kind": "card",
            "created_at": proposal["created_at"],
            "card": _proposal_card(proposal),
        }
        for proposal in proposals
    )
    return sorted(items, key=lambda item: str(item.get("created_at") or ""))


def _proposal_card(proposal: dict[str, Any]) -> dict[str, Any]:
    proposal_id = str(proposal.get("id") or "")
    conversation_id = str(proposal.get("conversation_id") or "")
    return {
        "id": f"card_proposal_{proposal_id}",
        "kind": "card",
        "card_type": "proposal",
        "source_id": proposal_id,
        "title": _proposal_title(proposal),
        "summary": _proposal_title(proposal),
        "status": proposal.get("status"),
        "created_at": proposal.get("created_at"),
        "counts": {"references": len(proposal.get("references") or [])},
        "detail_kind": "proposal",
        "detail_api_href": f"/api/chat/proposals/{proposal_id}",
        "detail_href": (
            f"/dashboard/peer-chat/conversations/{conversation_id}#proposal-{proposal_id}"
        ),
        "source_refs": _dedupe([f"proposal:{proposal_id}", *proposal.get("references", [])]),
        "compact_detail": {"proposal_type": proposal.get("proposal_type")},
    }


def _agent_cards(
    *,
    participants: list[dict[str, Any]],
    inbox_items: list[dict[str, Any]],
    sessions: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    inbox_by_participant: dict[str, dict[str, int]] = {}
    for item in inbox_items:
        participant_id = str(item.get("target_participant_id") or "__unknown__")
        counts = inbox_by_participant.setdefault(
            participant_id,
            {"unread": 0, "claimed": 0, "read": 0, "failed": 0},
        )
        status = str(item.get("status") or "")
        if status in counts:
            counts[status] += 1
    session_by_participant = {
        str(session.get("participant_id") or ""): session
        for session in sessions
        if session.get("participant_id")
    }
    cards = []
    for participant in participants:
        participant_id = str(participant.get("participant_id") or "")
        session = session_by_participant.get(participant_id)
        cards.append(
            {
                "kind": "agent_card",
                "participant_id": participant_id,
                "role": participant.get("role"),
                "display_name": participant.get("display_name"),
                "provider_id": participant.get("provider_id"),
                "profile_id": participant.get("profile_id"),
                "cli_kind": participant.get("cli_kind"),
                "model": participant.get("model"),
                "status": str(session.get("status") or "session_bound")
                if isinstance(session, dict)
                else "unbound",
                "inbox_counts": inbox_by_participant.get(
                    participant_id,
                    {"unread": 0, "claimed": 0, "read": 0, "failed": 0},
                ),
                "session": session,
                "detail_kind": "peer_session" if session else "participant",
                "detail_api_href": _session_api_href(session),
            }
        )
    return cards


def _worklist_items(
    *,
    conversation_id: str,
    inbox_items: list[dict[str, Any]],
    dispatch_entries: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    final_action_holds: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    links = _links(conversation_id)
    items: list[dict[str, Any]] = []
    for item in inbox_items:
        items.append(
            {
                "kind": "inbox_item",
                "id": item.get("id"),
                "status": item.get("status"),
                "target_role": item.get("target_role"),
                "target_participant_id": item.get("target_participant_id"),
                "item_type": item.get("item_type"),
                "created_at": item.get("created_at"),
                "updated_at": item.get("updated_at"),
                "next_action": _next_action_for_inbox(item),
                "detail_kind": "inbox_item",
                "detail_api_href": links["conversation_api_href"],
                "source_refs": _inbox_source_refs(item),
                "compact_detail": {
                    "source_message_id": item.get("source_message_id"),
                    "failure_reason": item.get("failure_reason"),
                },
            }
        )
    for blocker in blockers:
        items.append(
            {
                "kind": "blocker",
                "id": blocker.get("blocker_id"),
                "status": "active" if blocker.get("active") else "resolved",
                "target_role": blocker.get("issuer"),
                "created_at": blocker.get("created_at"),
                "updated_at": blocker.get("resolved_at") or blocker.get("created_at"),
                "next_action": "resolve_blocker" if blocker.get("active") else "none",
                "detail_kind": "collaboration_blocker",
                "detail_api_href": links["inspector_api_href"],
                "source_refs": _string_items(blocker.get("affected_ref")),
                "compact_detail": {
                    "reason": blocker.get("reason"),
                    "suggested_fix": blocker.get("suggested_fix"),
                    "blocks_dispatch": bool(blocker.get("blocks_dispatch")),
                },
            }
        )
    for entry in dispatch_entries:
        items.append(
            {
                "kind": "dispatch_queue_entry",
                "id": entry.get("entry_id"),
                "status": entry.get("status"),
                "target_role": entry.get("target"),
                "created_at": entry.get("created_at"),
                "updated_at": entry.get("updated_at"),
                "next_action": _next_action_for_dispatch(entry),
                "detail_kind": "dispatch_queue_entry",
                "detail_api_href": links["inspector_api_href"],
                "source_refs": _dispatch_source_refs(entry),
                "compact_detail": {
                    "failure_reason": entry.get("failure_reason"),
                    "dispatch_policy": entry.get("dispatch_policy"),
                    "provider_run_ref": entry.get("provider_run_ref"),
                },
            }
        )
    for hold in final_action_holds:
        items.append(
            {
                "kind": "final_action_hold",
                "id": hold.get("id"),
                "status": hold.get("status"),
                "target_role": "operator",
                "created_at": hold.get("created_at"),
                "updated_at": hold.get("updated_at"),
                "next_action": _next_action_for_final_action(hold),
                "detail_kind": "final_action_hold",
                "detail_api_href": links["inspector_api_href"],
                "source_refs": list(hold.get("source_refs") or []),
                "compact_detail": {
                    "action": hold.get("action"),
                    "lane_id": hold.get("lane_id"),
                    "target_status": hold.get("target_status"),
                    "github_gate_evidence_ref": hold.get("github_gate_evidence_ref"),
                    "github_gate_gap_ref": hold.get("github_gate_gap_ref"),
                },
            }
        )
    return sorted(items, key=lambda item: str(item.get("created_at") or ""))


def _final_action_holds(
    root: Path,
    closure_evidence: dict[str, Any],
) -> dict[str, Any]:
    raw_holds = _read_json_file(root / "final_actions.json").get("holds")
    if not isinstance(raw_holds, list):
        raw_holds = []
    holds_by_id = {
        str(hold.get("id")): hold
        for hold in raw_holds
        if isinstance(hold, dict) and isinstance(hold.get("id"), str)
    }
    items: list[dict[str, Any]] = []
    for spine in closure_evidence.get("items") or []:
        if not isinstance(spine, dict):
            continue
        final_action_ref = spine.get("final_action_ref")
        hold_id = _final_action_id_from_ref(final_action_ref)
        if hold_id is None:
            continue
        hold = holds_by_id.get(hold_id)
        if not isinstance(hold, dict):
            continue
        if hold.get("status") != "pending":
            continue
        item = _final_action_hold_projection(hold, spine)
        if item is not None:
            items.append(item)
    return {
        "source_authority": ["final_actions.json", "chat.db:acceptance_spines"],
        "projection_only": True,
        "total": len(items),
        "pending": sum(1 for item in items if item.get("status") == "pending"),
        "items": items,
    }


def _final_action_hold_projection(
    hold: dict[str, Any],
    spine: dict[str, Any],
) -> dict[str, Any] | None:
    hold_id = _projection_text(hold.get("id"))
    if not hold_id:
        return None
    return {
        "id": hold_id,
        "lane_id": _projection_text(hold.get("lane_id")),
        "verdict_id": _projection_text(hold.get("verdict_id")),
        "action": _projection_text(hold.get("action")),
        "target_status": _projection_text(hold.get("target_status")),
        "status": _projection_text(hold.get("status")) or "unknown",
        "summary": _projection_text(hold.get("summary")),
        "resolved_by": _projection_text(hold.get("resolved_by")),
        "github_gate_evidence_ref": _projection_text(hold.get("github_gate_evidence_ref")),
        "github_gate_gap_ref": _projection_text(hold.get("github_gate_gap_ref")),
        "source_refs": _final_action_source_refs(hold_id, hold, spine),
        "authority_boundary": _final_action_authority_boundary(),
    }


def _participant_payload(row: sqlite3.Row) -> dict[str, Any]:
    cli_kind = str(row["cli_kind"] or "codex")
    role = str(row["role"] or "")
    provider_id = "a2a" if cli_kind == "a2a" else "opencode" if cli_kind == "opencode" else "codex"
    profile_id = "remote" if cli_kind == "a2a" else _profile_id_for_role(role)
    return {
        **dict(row),
        "provider_id": provider_id,
        "profile_id": profile_id,
    }


def _profile_id_for_role(role: str) -> str:
    if role in {"architect", "init"}:
        return "god"
    if role == "review":
        return "review"
    if role == "execute":
        return "worker"
    return "default"


def _proposal_title(proposal: dict[str, Any]) -> str:
    content = str(proposal.get("content") or "")
    parsed = _json_object(content)
    summary = parsed.get("summary")
    if isinstance(summary, str) and summary.strip():
        return summary.strip()
    return content[:80]


def _next_action_for_inbox(item: dict[str, Any]) -> str:
    status = str(item.get("status") or "")
    if status == "unread":
        return "deliver_peer_turn"
    if status == "claimed":
        return "wait_for_peer_writeback"
    if status == "failed":
        return "inspect_failure"
    return "none"


def _next_action_for_dispatch(entry: dict[str, Any]) -> str:
    status = str(entry.get("status") or "")
    if status == "queued":
        return "dispatch_execute_peer"
    if status == "processing":
        return "wait_for_dispatch_ack"
    if status == "failed":
        return "inspect_dispatch_failure"
    return "none"


def _next_action_for_final_action(hold: dict[str, Any]) -> str:
    if hold.get("status") != "pending":
        return "none"
    if hold.get("action") == "merge":
        return "verify_github_gate_and_resolve_final_action"
    return "resolve_final_action"


def _session_api_href(session: dict[str, Any] | None) -> str | None:
    if not isinstance(session, dict):
        return None
    session_id = str(session.get("god_session_id") or session.get("session_id") or "")
    if not session_id:
        return None
    return f"/api/dashboard/peer-chat/sessions/{session_id}"


def _inbox_source_refs(item: dict[str, Any]) -> list[str]:
    refs = []
    source_message_id = item.get("source_message_id")
    if isinstance(source_message_id, str) and source_message_id:
        refs.append(f"chat:message:{source_message_id}")
    responded_message_id = item.get("responded_message_id")
    if isinstance(responded_message_id, str) and responded_message_id:
        refs.append(f"chat:message:{responded_message_id}")
    return refs


def _dispatch_source_refs(entry: dict[str, Any]) -> list[str]:
    refs = []
    entry_id = entry.get("entry_id")
    if isinstance(entry_id, str) and entry_id:
        refs.append(f"chat_dispatch_queue:{entry_id}")
    proposal_id = entry.get("proposal_id")
    if isinstance(proposal_id, str) and proposal_id:
        refs.append(f"proposal:{proposal_id}")
    refs.extend(_string_items(entry.get("gate_refs")))
    for prefix, key in (
        ("resolution", "resolution_id"),
        ("collaboration", "collaboration_run_id"),
    ):
        value = entry.get(key)
        if isinstance(value, str) and value:
            refs.append(f"{prefix}:{value}")
    refs.extend(_string_items(entry.get("artifact_ref")))
    return _dedupe(refs)


def _dispatch_authority_boundary() -> dict[str, str]:
    return {
        "producer": "chat.db:chat_dispatch_queue",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "dispatch_queue_authority_not_execution_proof",
    }


def _dispatch_sidecar_continuity(source_refs: list[str]) -> dict[str, Any]:
    return {
        "producer": "chat.db:chat_dispatch_queue",
        "consumer": "memoryos_sidecar",
        "condition": "explicit_memoryos_configuration",
        "proof_boundary": "sidecar_continuity_not_execution_truth",
        "projection_only": True,
        "handoff_state": "contract_available",
        "source_refs": list(source_refs),
    }


def _final_action_id_from_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = "final_actions.json#hold="
    if not value.startswith(prefix):
        return None
    hold_id = value.removeprefix(prefix).strip()
    return hold_id or None


def _final_action_source_refs(
    hold_id: str,
    hold: dict[str, Any],
    spine: dict[str, Any],
) -> list[str]:
    refs = [f"final_actions.json#hold={hold_id}"]
    verdict_ref = spine.get("review_verdict_ref")
    if isinstance(verdict_ref, str) and verdict_ref:
        refs.append(verdict_ref)
    elif isinstance(hold.get("verdict_id"), str) and hold["verdict_id"]:
        refs.append(f"review_verdict:{hold['verdict_id']}")
    spine_id = spine.get("spine_id")
    if isinstance(spine_id, str) and spine_id:
        refs.append(f"chat.db:acceptance_spines#spine={spine_id}")
    return _dedupe(refs)


def _final_action_authority_boundary() -> dict[str, str]:
    return {
        "producer": "final_actions.json",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "final_action_hold_not_github_or_merge_truth",
    }


def _fetch_one(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[object, ...],
) -> sqlite3.Row | None:
    try:
        return conn.execute(query, params).fetchone()
    except sqlite3.OperationalError:
        return None


def _fetch_all(
    conn: sqlite3.Connection,
    query: str,
    params: tuple[object, ...],
) -> list[sqlite3.Row]:
    try:
        return list(conn.execute(query, params).fetchall())
    except sqlite3.OperationalError:
        return []


def _table_has_column(
    conn: sqlite3.Connection,
    table_name: str,
    column_name: str,
) -> bool:
    try:
        rows = conn.execute(f"pragma table_info({table_name})").fetchall()
    except sqlite3.OperationalError:
        return False
    return any(row["name"] == column_name for row in rows)


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed if str(item).strip()]


def _string_items(value: Any) -> list[str]:
    if isinstance(value, str):
        clean = value.strip()
        return [clean] if clean else []
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _projection_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _supporting_context_source_refs(value: Any) -> list[str]:
    refs = []
    for ref in _json_list(value):
        clean = ref.strip()
        if not clean:
            continue
        refs.append(clean[:_SUPPORTING_CONTEXT_SOURCE_REF_MAX_CHARS])
        if len(refs) >= _SUPPORTING_CONTEXT_SOURCE_REF_LIMIT:
            break
    return refs


def _supporting_context_continuity_refs(context: dict[str, Any]) -> list[str]:
    refs = _supporting_context_source_refs(context.get("continuity_refs"))
    if refs:
        return refs
    single_ref = _projection_text(context.get("continuity_ref"))
    if single_ref is None:
        return []
    return [single_ref[:_SUPPORTING_CONTEXT_SOURCE_REF_MAX_CHARS]]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
