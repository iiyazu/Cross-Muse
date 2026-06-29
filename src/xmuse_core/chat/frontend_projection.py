from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from xmuse_core.chat.failure_taxonomy import classify_failure_boundary

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
    "review_plane.json",
    "final_actions.json",
    "final_action_prs.json",
    "github_gate_evidence.json",
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
    conversation_lanes = _conversation_lanes(root, conversation_id)
    review_state = _review_state(root, closure_evidence, conversation_lanes)
    final_action_holds = _final_action_holds(
        root,
        closure_evidence,
        conversation_lanes,
    )
    final_action_state = _final_action_state(
        root,
        closure_evidence,
        conversation_lanes,
    )
    evidence_summary = _evidence_summary(
        root=root,
        conversation_id=conversation_id,
        conversation=conversation,
        proposals=proposals,
        dispatch_entries=dispatch_entries,
        blockers=blockers,
        closure_evidence=closure_evidence,
        supporting_context=supporting_context,
        review_state=review_state,
        final_action_state=final_action_state,
    )

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
        "review_state": review_state,
        "final_action_holds": final_action_holds,
        "final_action_state": final_action_state,
        "evidence_summary": evidence_summary,
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
    continuity_refs = _supporting_context_continuity_refs(context)
    item = {
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
        "continuity_refs": continuity_refs,
    }
    continuity_attempt_ref = _supporting_context_continuity_attempt_ref(context)
    if continuity_attempt_ref and not continuity_refs:
        item["continuity_attempt_ref"] = continuity_attempt_ref
    return item


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


def _evidence_summary(
    *,
    root: Path,
    conversation_id: str,
    conversation: dict[str, Any],
    proposals: list[dict[str, Any]],
    dispatch_entries: list[dict[str, Any]],
    blockers: list[dict[str, Any]],
    closure_evidence: dict[str, Any],
    supporting_context: dict[str, Any],
    review_state: dict[str, Any],
    final_action_state: dict[str, Any],
) -> dict[str, Any]:
    items: list[dict[str, Any]] = [
        _evidence_item(
            kind="conversation",
            proof_class="authority",
            ref=f"chat.db:conversations#conversation={conversation_id}",
            status="observed" if conversation else "missing",
            producer="chat.db:conversations",
            condition="conversation_exists",
            proof_boundary="conversation_authority_not_execution_or_github_truth",
        )
    ]
    failure_boundaries: list[dict[str, Any]] = []
    proposals_by_id = {
        str(proposal.get("id")): proposal
        for proposal in proposals
        if _projection_text(proposal.get("id"))
    }
    dispatch_by_id = {
        str(entry.get("entry_id")): entry
        for entry in dispatch_entries
        if _projection_text(entry.get("entry_id"))
    }
    reviews_by_ref = {
        f"review_plane.json#verdict={item.get('id')}": item
        for item in _dict_items(review_state.get("items"))
        if _projection_text(item.get("id"))
    }
    final_actions_by_ref = {
        f"final_actions.json#hold={item.get('id')}": item
        for item in _dict_items(final_action_state.get("items"))
        if _projection_text(item.get("id"))
    }
    include_lane_context = _has_multiple_evidence_lanes(review_state, final_action_state)

    def lane_kwargs(
        *items: dict[str, Any] | None,
        source_refs: Any = None,
    ) -> dict[str, Any]:
        if not include_lane_context:
            return {}
        return _evidence_context_kwargs(*items, source_refs=source_refs)

    acceptance_spine_items: list[dict[str, Any]] = []
    execution_evidence_items: list[dict[str, Any]] = []
    dispatch_evidence_items: list[dict[str, Any]] = []
    final_action_items: list[dict[str, Any]] = []
    github_gate_items: list[dict[str, Any]] = []

    for blocker in blockers:
        if not (blocker.get("active") and blocker.get("blocks_dispatch")):
            continue
        blocker_id = _projection_text(blocker.get("blocker_id")) or "unknown"
        failure_boundaries.append(
            _failure_boundary(
                kind="collaboration_blocker",
                ref=f"chat.db:collaboration_blockers#blocker={blocker_id}",
                status="blocked",
                producer="chat.db:collaboration_blockers",
                condition=_projection_text(blocker.get("reason"))
                or "collaboration_blocker_active",
                proof_boundary="collaboration_blocker_boundary",
                next_recovery_action="resolve_collaboration_blocker_with_evidence",
            )
        )

    for spine in _dict_items(closure_evidence.get("items")):
        review_ref = _projection_text(spine.get("review_verdict_ref"))
        review = reviews_by_ref.get(review_ref) if review_ref else None
        final_action_ref = _projection_text(spine.get("final_action_ref"))
        final_action = (
            final_actions_by_ref.get(final_action_ref) if final_action_ref else None
        )
        lane_context = lane_kwargs(review, final_action)
        proposal_id = _projection_text(spine.get("proposal_id"))
        if proposal_id:
            proposal = proposals_by_id.get(proposal_id)
            if proposal is None:
                failure_boundaries.append(
                    _failure_boundary(
                        kind="proposal",
                        ref=f"proposal:{proposal_id}",
                        status="missing",
                        producer="chat.db:proposals",
                        condition="proposal_ref_unresolved",
                        proof_boundary="proposal_artifact_boundary",
                        next_recovery_action="recreate_or_relink_proposal",
                    )
                )
            else:
                proposal_status = _projection_text(proposal.get("status")) or "linked"
                if proposal_status not in {"accepted", "approved"} and spine.get(
                    "review_or_execute_verdict_ref"
                ):
                    proposal_status = "accepted"
                items.append(
                    _evidence_item(
                        kind="proposal",
                        proof_class="authority",
                        ref=f"proposal:{proposal_id}",
                        status=proposal_status,
                        producer="chat.db:proposals",
                        condition="proposal_linked_to_acceptance_spine",
                        proof_boundary="proposal_authority_not_execution_or_github_truth",
                    )
                )

        if review_ref:
            if review is None:
                failure_boundaries.append(
                    _failure_boundary(
                        kind="review_verdict",
                        ref=review_ref,
                        status="missing",
                        producer="review_plane.json",
                        condition="review_verdict_ref_unresolved",
                        proof_boundary="review_verdict_artifact_boundary",
                        next_recovery_action="recreate_or_relink_review_verdict",
                    )
                )
            else:
                items.append(
                    _evidence_item(
                        kind="review_verdict",
                        proof_class="authority",
                        ref=review_ref,
                        status=_projection_text(review.get("verdict_status")) or "observed",
                        producer="review_plane.json",
                        condition="review_verdict_linked_to_acceptance_spine",
                        proof_boundary="review_verdict_authority_not_github_or_merge_truth",
                        **lane_kwargs(review),
                    )
                )
                for ref in _summary_execution_refs_from_review(review):
                    execution_evidence_items.append(
                        _evidence_item(
                            kind="execution_proof",
                            proof_class="execution_proof",
                            ref=ref,
                            status="observed",
                            producer="review_plane.json",
                            condition="review_verdict_evidence_ref",
                            proof_boundary="execution_proof_not_review_github_or_merge_truth",
                            **lane_kwargs(
                                review,
                                source_refs=[ref],
                            ),
                        )
                    )

        dispatch_item_id = _projection_text(spine.get("dispatch_item_id"))
        if dispatch_item_id:
            dispatch = dispatch_by_id.get(dispatch_item_id)
            if dispatch is None:
                failure_boundaries.append(
                    _failure_boundary(
                        kind="dispatch_queue_entry",
                        ref=f"chat_dispatch_queue:{dispatch_item_id}",
                        status="missing",
                        producer="chat.db:chat_dispatch_queue",
                        condition="dispatch_entry_ref_unresolved",
                        proof_boundary="dispatch_queue_artifact_boundary",
                        next_recovery_action="recreate_or_relink_dispatch_queue_entry",
                    )
                )
            else:
                items.append(
                    _evidence_item(
                        kind="dispatch_queue_entry",
                        proof_class="authority",
                        ref=f"chat_dispatch_queue:{dispatch_item_id}",
                        status=_projection_text(dispatch.get("status")) or "observed",
                        producer="chat.db:chat_dispatch_queue",
                        condition="dispatch_entry_linked_to_acceptance_spine",
                        proof_boundary="dispatch_queue_authority_not_execution_proof",
                        **lane_kwargs(
                            review,
                            final_action,
                            source_refs=dispatch.get("source_refs"),
                        ),
                    )
                )
                dispatch_evidence = _projection_text(dispatch.get("dispatch_evidence"))
                if dispatch_evidence:
                    dispatch_evidence_items.append(
                        _evidence_item(
                            kind="execution_proof",
                            proof_class="execution_proof",
                            ref=dispatch_evidence,
                            status="observed",
                            producer="chat_dispatch_bridge",
                            condition="dispatch_entry_dispatch_evidence",
                            proof_boundary="worker_writeback_not_authority_or_github_truth",
                            **lane_kwargs(
                                review,
                                final_action,
                                source_refs=[dispatch_evidence],
                            ),
                        )
                    )
                if dispatch.get("status") == "failed":
                    failure_boundaries.append(
                        _failure_boundary(
                            kind="dispatch_queue_entry",
                            ref=f"chat_dispatch_queue:{dispatch_item_id}",
                            status="failed",
                            producer="chat.db:chat_dispatch_queue",
                            condition=(
                                _projection_text(dispatch.get("failure_reason"))
                                or "dispatch_entry_failed"
                            ),
                            proof_boundary="dispatch_failure_boundary",
                            next_recovery_action="inspect_dispatch_failure_reason",
                        )
                    )

        for ref in _string_items(spine.get("execution_evidence_refs")):
            execution_evidence_items.append(
                _evidence_item(
                    kind="execution_proof",
                    proof_class="execution_proof",
                    ref=ref,
                    status="observed",
                    producer="lane_execution_or_gate",
                    condition="acceptance_spine_execution_evidence_ref",
                    proof_boundary="execution_proof_not_review_github_or_merge_truth",
                    **lane_kwargs(
                        review,
                        final_action,
                        source_refs=[ref],
                    ),
                )
            )

        if final_action_ref:
            if final_action is None:
                failure_boundaries.append(
                    _failure_boundary(
                        kind="final_action",
                        ref=final_action_ref,
                        status="missing",
                        producer="final_actions.json",
                        condition="final_action_ref_unresolved",
                        proof_boundary="final_action_artifact_boundary",
                        next_recovery_action="recreate_or_relink_final_action_hold",
                    )
                )
            else:
                final_action_status = _projection_text(final_action.get("status")) or "observed"
                final_action_items.append(
                    _evidence_item(
                        kind="final_action",
                        proof_class="authority",
                        ref=final_action_ref,
                        status=final_action_status,
                        producer="final_actions.json",
                        condition="final_action_linked_to_acceptance_spine",
                        proof_boundary="final_action_authority_not_github_or_merge_truth",
                        **lane_kwargs(final_action),
                    )
                )
                final_action_id = _final_action_id_from_ref(final_action_ref)
                github_gate_evidence_ref = _projection_text(
                    final_action.get("github_gate_evidence_ref")
                )
                if github_gate_evidence_ref:
                    github_record = _accepted_github_gate_record(
                        root,
                        github_gate_evidence_ref,
                        final_action_id=final_action_id,
                    )
                    if github_record is None:
                        failure_boundaries.append(
                            _failure_boundary(
                                kind="github_gate",
                                ref=github_gate_evidence_ref,
                                status="blocked",
                                producer="github_gate_evidence.json",
                                condition="github_gate_evidence_ref_missing_or_invalid",
                                proof_boundary="github_gate_evidence_ref_boundary",
                                next_recovery_action="capture_exact_head_github_gate_evidence",
                            )
                        )
                    else:
                        details = _github_gate_details(github_record)
                        github_gate_items.append(
                            _evidence_item(
                                kind="github_gate",
                                proof_class="github_server_truth",
                                ref=github_gate_evidence_ref,
                                status="accepted",
                                producer="github_gate_evidence.json",
                                condition="final_action_contains_github_gate_evidence_ref",
                                proof_boundary="github_gate_evidence_not_main_ci_truth",
                                details=details,
                                **lane_kwargs(
                                    final_action,
                                    source_refs=[github_gate_evidence_ref],
                                ),
                            )
                        )
                        main_ci_status = str(
                            _dict_value(details.get("main_ci")).get("status") or ""
                        )
                        if main_ci_status != "success":
                            failure_boundaries.append(
                                _failure_boundary(
                                    kind="main_ci",
                                    ref=github_gate_evidence_ref,
                                    status=main_ci_status or "missing",
                                    producer="github_gate_evidence.json",
                                    condition="github_gate_evidence_missing_main_ci",
                                    proof_boundary="main_ci_server_truth_boundary",
                                    next_recovery_action="capture_post_merge_main_ci_evidence",
                                )
                            )
                github_gate_gap_ref = _projection_text(final_action.get("github_gate_gap_ref"))
                if github_gate_gap_ref:
                    failure_boundaries.append(
                        _failure_boundary(
                            kind="github_gate",
                            ref=github_gate_gap_ref,
                            status="blocked",
                            producer="final_actions.json",
                            condition="final_action_contains_github_gate_gap_ref",
                            proof_boundary="github_gate_gap_boundary",
                            next_recovery_action="capture_exact_head_github_gate_evidence",
                        )
                    )

        spine_id = _projection_text(spine.get("spine_id"))
        if spine_id:
            acceptance_spine_items.append(
                _evidence_item(
                    kind="acceptance_spine",
                    proof_class="authority",
                    ref=f"chat.db:acceptance_spines#spine={spine_id}",
                    status=_projection_text(spine.get("status")) or "observed",
                    producer="chat.db:acceptance_spines",
                    condition="acceptance_spine_tracks_chain",
                    proof_boundary="acceptance_spine_authority_not_github_or_merge_truth",
                    **lane_context,
                )
            )
        blocked_reason = _projection_text(spine.get("blocked_reason"))
        if blocked_reason:
            failure_boundaries.append(
                _failure_boundary(
                    kind="acceptance_spine",
                    ref=f"chat.db:acceptance_spines#spine={spine_id or 'unknown'}",
                    status="blocked",
                    producer="chat.db:acceptance_spines",
                    condition=blocked_reason,
                    proof_boundary="acceptance_spine_blocker_boundary",
                    next_recovery_action="resume_from_recorded_acceptance_spine_boundary",
                )
            )

    for proposal in proposals:
        proposal_id = _projection_text(proposal.get("id"))
        if proposal_id is None:
            continue
        items.append(
            _evidence_item(
                kind="proposal",
                proof_class="authority",
                ref=f"proposal:{proposal_id}",
                status=_projection_text(proposal.get("status")) or "observed",
                producer="chat.db:proposals",
                condition="proposal_present_for_conversation",
                proof_boundary="proposal_authority_not_execution_or_github_truth",
            )
        )

    for dispatch in dispatch_entries:
        dispatch_item_id = _projection_text(dispatch.get("entry_id"))
        if dispatch_item_id is None:
            continue
        items.append(
            _evidence_item(
                kind="dispatch_queue_entry",
                proof_class="authority",
                ref=f"chat_dispatch_queue:{dispatch_item_id}",
                status=_projection_text(dispatch.get("status")) or "observed",
                producer="chat.db:chat_dispatch_queue",
                condition="dispatch_entry_present_for_conversation",
                proof_boundary="dispatch_queue_authority_not_execution_proof",
                **lane_kwargs(source_refs=dispatch.get("source_refs")),
            )
        )
        dispatch_evidence = _projection_text(dispatch.get("dispatch_evidence"))
        if dispatch_evidence:
            dispatch_evidence_items.append(
                _evidence_item(
                    kind="execution_proof",
                    proof_class="execution_proof",
                    ref=dispatch_evidence,
                    status="observed",
                    producer="chat_dispatch_bridge",
                    condition="dispatch_entry_dispatch_evidence",
                    proof_boundary="worker_writeback_not_authority_or_github_truth",
                    **lane_kwargs(source_refs=[dispatch_evidence]),
                )
            )

    for review in _dict_items(review_state.get("items")):
        review_id = _projection_text(review.get("id"))
        if review_id is None:
            continue
        review_ref = f"review_plane.json#verdict={review_id}"
        items.append(
            _evidence_item(
                kind="review_verdict",
                proof_class="authority",
                ref=review_ref,
                status=_projection_text(review.get("verdict_status")) or "observed",
                producer="review_plane.json",
                condition="review_verdict_projected_from_review_state",
                proof_boundary="review_verdict_authority_not_github_or_merge_truth",
                **lane_kwargs(review),
            )
        )
        for ref in _summary_execution_refs_from_review(review):
            execution_evidence_items.append(
                _evidence_item(
                    kind="execution_proof",
                    proof_class="execution_proof",
                    ref=ref,
                    status="observed",
                    producer="review_plane.json",
                    condition="review_verdict_evidence_ref",
                    proof_boundary="execution_proof_not_review_github_or_merge_truth",
                    **lane_kwargs(review, source_refs=[ref]),
                )
            )

    for final_action in _dict_items(final_action_state.get("items")):
        final_action_id = _projection_text(final_action.get("id"))
        if final_action_id is None:
            continue
        final_action_ref = f"final_actions.json#hold={final_action_id}"
        final_action_status = _projection_text(final_action.get("status")) or "observed"
        final_action_items.append(
            _evidence_item(
                kind="final_action",
                proof_class="authority",
                ref=final_action_ref,
                status=final_action_status,
                producer="final_actions.json",
                condition="final_action_projected_from_final_action_state",
                proof_boundary="final_action_authority_not_github_or_merge_truth",
                **lane_kwargs(final_action),
            )
        )
        github_gate_evidence_ref = _projection_text(
            final_action.get("github_gate_evidence_ref")
        )
        if github_gate_evidence_ref:
            github_record = _accepted_github_gate_record(
                root,
                github_gate_evidence_ref,
                final_action_id=final_action_id,
            )
            if github_record is None:
                failure_boundaries.append(
                    _failure_boundary(
                        kind="github_gate",
                        ref=github_gate_evidence_ref,
                        status="blocked",
                        producer="github_gate_evidence.json",
                        condition="github_gate_evidence_ref_missing_or_invalid",
                        proof_boundary="github_gate_evidence_ref_boundary",
                        next_recovery_action="capture_exact_head_github_gate_evidence",
                    )
                )
            else:
                details = _github_gate_details(github_record)
                github_gate_items.append(
                    _evidence_item(
                        kind="github_gate",
                        proof_class="github_server_truth",
                        ref=github_gate_evidence_ref,
                        status="accepted",
                        producer="github_gate_evidence.json",
                        condition="final_action_contains_github_gate_evidence_ref",
                        proof_boundary="github_gate_evidence_not_main_ci_truth",
                        details=details,
                        **lane_kwargs(
                            final_action,
                            source_refs=[github_gate_evidence_ref],
                        ),
                    )
                )
                main_ci_status = str(
                    _dict_value(details.get("main_ci")).get("status") or ""
                )
                if main_ci_status != "success":
                    failure_boundaries.append(
                        _failure_boundary(
                            kind="main_ci",
                            ref=github_gate_evidence_ref,
                            status=main_ci_status or "missing",
                            producer="github_gate_evidence.json",
                            condition="github_gate_evidence_missing_main_ci",
                            proof_boundary="main_ci_server_truth_boundary",
                            next_recovery_action="capture_post_merge_main_ci_evidence",
                        )
                    )
        github_gate_gap_ref = _projection_text(final_action.get("github_gate_gap_ref"))
        if github_gate_gap_ref:
            failure_boundaries.append(
                _failure_boundary(
                    kind="github_gate",
                    ref=github_gate_gap_ref,
                    status="blocked",
                    producer="final_actions.json",
                    condition="final_action_contains_github_gate_gap_ref",
                    proof_boundary="github_gate_gap_boundary",
                    next_recovery_action="capture_exact_head_github_gate_evidence",
                )
            )

    items.extend(execution_evidence_items)
    items.extend(dispatch_evidence_items)
    items.extend(final_action_items)
    items.extend(github_gate_items)
    memoryos_summary = _memoryos_evidence_item(supporting_context)
    if memoryos_summary is not None:
        items.append(memoryos_summary)
    items.append(
        _evidence_item(
            kind="frontend_projection",
            proof_class="read_projection",
            ref=f"/api/dashboard/peer-chat/conversations/{conversation_id}/ux-projection",
            status="available",
            producer="frontend.peer_chat_ux_projection",
            consumer="operator",
            condition="read_only_projection_built_from_authority",
            proof_boundary="frontend_projection_not_truth_producer",
        )
    )
    items.extend(acceptance_spine_items)
    items = _dedupe_evidence_items(items)
    failure_boundaries = _dedupe_evidence_items(failure_boundaries)
    counts = _evidence_counts(items, failure_boundaries)
    return {
        "schema_version": "natural_groupchat_evidence_summary/v1",
        "projection_only": True,
        "conversation_id": conversation_id,
        "status": _evidence_summary_status(items, failure_boundaries),
        "active_blocker": failure_boundaries[0] if failure_boundaries else None,
        "counts": counts,
        "items": items,
        "failure_boundaries": failure_boundaries,
    }


def _dict_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dict_value(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _jsonish_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def _accepted_github_gate_record(
    root: Path,
    ref: str,
    *,
    final_action_id: str | None,
) -> dict[str, Any] | None:
    if final_action_id is None:
        return None
    prefix = "github_gate_evidence.json#evidence="
    if not ref.startswith(prefix):
        return None
    evidence_id = ref.removeprefix(prefix).strip()
    if not evidence_id:
        return None
    payload = _read_json_file(root / "github_gate_evidence.json")
    for item in _dict_items(payload.get("items")):
        if item.get("id") != evidence_id:
            continue
        evidence = _dict_value(item.get("evidence"))
        if (
            item.get("final_action_id") == final_action_id
            and item.get("can_accept") is True
            and evidence.get("proof_level") == "server_side_merge_proof"
        ):
            return item
        return None
    return None


def _github_gate_details(record: dict[str, Any]) -> dict[str, Any]:
    evidence = _dict_value(record.get("evidence"))
    merge_commit_sha = _projection_text(evidence.get("merge_commit_sha"))
    return {
        "pull_request": {
            "repo": _projection_text(evidence.get("repo")),
            "number": evidence.get("pull_request_number"),
            "head_sha": _projection_text(evidence.get("head_sha")),
        },
        "exact_head_ci": {
            "workflow_run_id": evidence.get("workflow_run_id"),
            "check_run_ids": _jsonish_list(evidence.get("check_run_ids")),
            "check_run_names": _string_items(evidence.get("check_run_names")),
            "check_run_head_shas": _string_items(evidence.get("check_run_head_shas")),
        },
        "merge": {
            "merge_commit_sha": merge_commit_sha,
            "merged_at": _projection_text(evidence.get("merged_at")),
            "merge_event_id": evidence.get("merge_event_id"),
        },
        "main_ci": _github_main_ci_details(record.get("main_ci"), merge_commit_sha),
    }


def _github_main_ci_details(value: Any, merge_commit_sha: str | None) -> dict[str, Any]:
    main_ci = _dict_value(value)
    if not main_ci:
        return {"status": "missing"}
    conclusion = _projection_text(main_ci.get("conclusion")) or _projection_text(
        main_ci.get("status")
    )
    head_sha = _projection_text(main_ci.get("head_sha"))
    status = conclusion or "unknown"
    if conclusion == "success" and merge_commit_sha and head_sha and head_sha != merge_commit_sha:
        status = "head_mismatch"
    return {
        "workflow_run_id": main_ci.get("workflow_run_id"),
        "head_sha": head_sha,
        "conclusion": conclusion,
        "status": status,
    }


def _evidence_item(
    *,
    kind: str,
    proof_class: str,
    ref: str,
    status: str,
    producer: str,
    condition: str,
    proof_boundary: str,
    consumer: str = "natural_groupchat_evidence_summary",
    details: dict[str, Any] | None = None,
    lane_id: str | None = None,
    source_refs: list[str] | None = None,
) -> dict[str, Any]:
    item: dict[str, Any] = {
        "kind": kind,
        "proof_class": proof_class,
        "ref": ref,
        "status": status,
        "producer": producer,
        "consumer": consumer,
        "condition": condition,
        "proof_boundary": proof_boundary,
    }
    if details is not None:
        item["details"] = details
    if lane_id is not None:
        item["lane_id"] = lane_id
    if source_refs:
        item["source_refs"] = list(source_refs)
    return item


def _evidence_context_kwargs(
    *items: dict[str, Any] | None,
    source_refs: Any = None,
) -> dict[str, Any]:
    lane_id: str | None = None
    refs: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        lane_id = lane_id or _projection_text(item.get("lane_id"))
        refs.extend(_string_items(item.get("source_refs")))
    refs.extend(_string_items(source_refs))
    kwargs: dict[str, Any] = {}
    if lane_id is not None:
        kwargs["lane_id"] = lane_id
    refs = _dedupe(refs)
    if refs:
        kwargs["source_refs"] = refs
    return kwargs


def _has_multiple_evidence_lanes(
    review_state: dict[str, Any],
    final_action_state: dict[str, Any],
) -> bool:
    lane_ids: set[str] = set()
    for item in [
        *_dict_items(review_state.get("items")),
        *_dict_items(final_action_state.get("items")),
    ]:
        lane_id = _projection_text(item.get("lane_id"))
        if lane_id is not None:
            lane_ids.add(lane_id)
        if len(lane_ids) > 1:
            return True
    return False


def _failure_boundary(
    *,
    kind: str,
    ref: str,
    status: str,
    producer: str,
    condition: str,
    proof_boundary: str,
    next_recovery_action: str,
) -> dict[str, Any]:
    item = _evidence_item(
        kind=kind,
        proof_class="failure_boundary",
        ref=ref,
        status=status,
        producer=producer,
        condition=condition,
        proof_boundary=proof_boundary,
    )
    item["next_recovery_action"] = next_recovery_action
    classification = classify_failure_boundary(item)
    item["taxonomy"] = classification["taxonomy"]
    item["proof_level"] = classification["proof_level"]
    item["classification"] = classification
    return item


def _memoryos_evidence_item(supporting_context: dict[str, Any]) -> dict[str, Any] | None:
    memoryos = supporting_context.get("memoryos_sidecar")
    if not isinstance(memoryos, dict):
        return None
    latest = _dict_items(memoryos.get("latest"))
    if not latest:
        return None
    item = latest[0]
    refs = _string_items(item.get("continuity_refs"))
    attempt_ref = _projection_text(item.get("continuity_attempt_ref"))
    ref = refs[0] if refs else attempt_ref
    if not ref:
        namespace_uri = _projection_text(item.get("namespace_uri"))
        if namespace_uri and namespace_uri != "unknown":
            ref = namespace_uri
    if not ref:
        return None
    return _evidence_item(
        kind="memoryos_sidecar",
        proof_class="sidecar_continuity",
        ref=ref,
        status=_projection_text(item.get("status")) or "unknown",
        producer="chat.db:peer_turn_latency_traces.supporting_context_json",
        condition="memoryos_sidecar_projection_present",
        proof_boundary="sidecar_continuity_not_proposal_review_dispatch_or_github_truth",
    )


def _dedupe_evidence_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict[str, Any]] = []
    for item in items:
        key = (
            str(item.get("kind") or ""),
            str(item.get("proof_class") or ""),
            str(item.get("ref") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def _evidence_counts(
    items: list[dict[str, Any]],
    failure_boundaries: list[dict[str, Any]],
) -> dict[str, int]:
    counts = {
        "authority": 0,
        "execution_proof": 0,
        "github_server_truth": 0,
        "sidecar_continuity": 0,
        "read_projection": 0,
        "failure_boundary": len(failure_boundaries),
    }
    for item in items:
        proof_class = str(item.get("proof_class") or "")
        if proof_class in counts and proof_class != "failure_boundary":
            counts[proof_class] += 1
    return counts


def _evidence_summary_status(
    items: list[dict[str, Any]],
    failure_boundaries: list[dict[str, Any]],
) -> str:
    if failure_boundaries:
        return "blocked"
    kinds = {str(item.get("kind") or "") for item in items}
    final_statuses = {
        str(item.get("status") or "")
        for item in items
        if item.get("kind") == "final_action"
    }
    if (
        "conversation" in kinds
        and "proposal" in kinds
        and "review_verdict" in kinds
        and "dispatch_queue_entry" in kinds
        and "execution_proof" in kinds
        and "final_action" in kinds
        and "github_gate" in kinds
        and final_statuses.intersection({"approved", "accepted", "resolved"})
    ):
        return "complete"
    return "in_progress"


def _summary_execution_refs_from_review(review: dict[str, Any]) -> list[str]:
    refs = _string_items(review.get("evidence_refs"))
    gate_report_ref = _projection_text(review.get("gate_report_ref"))
    if gate_report_ref:
        refs.append(gate_report_ref)
    return _dedupe(
        [
            ref
            for ref in refs
            if not ref.startswith("feature_lanes.json#lane=")
            and not ref.startswith("review_plane.json#task=")
        ]
    )


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
    conversation_lanes: list[dict[str, Any]],
) -> dict[str, Any]:
    holds_by_id = _final_actions_by_id(root)
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    used_lane_projection = False
    for hold_id, spine, lane in _final_action_links(closure_evidence, conversation_lanes):
        if hold_id in seen:
            continue
        hold = holds_by_id.get(hold_id)
        if not isinstance(hold, dict):
            continue
        if hold.get("status") != "pending":
            continue
        item = _final_action_projection(hold, spine=spine, lane=lane)
        if item is not None:
            items.append(item)
            seen.add(hold_id)
            used_lane_projection = used_lane_projection or lane is not None
    result: dict[str, Any] = {
        "source_authority": ["final_actions.json", "chat.db:acceptance_spines"],
        "projection_only": True,
        "total": len(items),
        "pending": sum(1 for item in items if item.get("status") == "pending"),
        "items": items,
    }
    if used_lane_projection:
        result["projection_source"] = ["feature_lanes.json"]
    return result


def _final_action_state(
    root: Path,
    closure_evidence: dict[str, Any],
    conversation_lanes: list[dict[str, Any]],
) -> dict[str, Any]:
    holds_by_id = _final_actions_by_id(root)
    items: list[dict[str, Any]] = []
    status_summary: dict[str, int] = {}
    seen: set[str] = set()
    used_lane_projection = False
    for hold_id, spine, lane in _final_action_links(closure_evidence, conversation_lanes):
        if hold_id in seen:
            continue
        hold = holds_by_id.get(hold_id)
        if not isinstance(hold, dict):
            continue
        item = _final_action_projection(hold, root=root, spine=spine, lane=lane)
        if item is None:
            continue
        items.append(item)
        seen.add(hold_id)
        used_lane_projection = used_lane_projection or lane is not None
        item_status = str(item.get("status") or "unknown")
        status_summary[item_status] = status_summary.get(item_status, 0) + 1
    source_authority = ["final_actions.json", "chat.db:acceptance_spines"]
    if any("pull_request" in item for item in items):
        source_authority.append("final_action_prs.json")
    if any("github_gate" in item for item in items):
        source_authority.append("github_gate_evidence.json")
    result: dict[str, Any] = {
        "source_authority": source_authority,
        "projection_only": True,
        "total": len(items),
        "status_summary": status_summary,
        "items": items,
    }
    if used_lane_projection:
        result["projection_source"] = ["feature_lanes.json"]
    return result


def _final_actions_by_id(root: Path) -> dict[str, dict[str, Any]]:
    raw_holds = _read_json_file(root / "final_actions.json").get("holds")
    if not isinstance(raw_holds, list):
        raw_holds = []
    return {
        str(hold.get("id")): hold
        for hold in raw_holds
        if isinstance(hold, dict) and isinstance(hold.get("id"), str)
    }


def _final_action_prs_by_final_action_id(root: Path) -> dict[str, dict[str, Any]]:
    raw_items = _read_json_file(root / "final_action_prs.json").get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    by_final_action_id: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        final_action_id = item.get("final_action_id")
        if isinstance(final_action_id, str) and final_action_id:
            by_final_action_id[final_action_id] = item
    return by_final_action_id


def _final_action_prs_by_ref(root: Path) -> dict[str, dict[str, Any]]:
    raw_items = _read_json_file(root / "final_action_prs.json").get("items")
    if not isinstance(raw_items, list):
        raw_items = []
    by_ref: dict[str, dict[str, Any]] = {}
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        pr_id = _projection_text(item.get("id"))
        if pr_id:
            by_ref[f"final_action_prs.json#pr={pr_id}"] = item
    return by_ref


def _final_action_pr_record(
    root: Path,
    hold_id: str,
    lane: dict[str, Any] | None,
) -> dict[str, Any] | None:
    lane_ref = _projection_text(lane.get("pull_request_ref") if lane is not None else None)
    if lane_ref:
        record = _final_action_prs_by_ref(root).get(lane_ref)
        if record is None or record.get("final_action_id") != hold_id:
            return None
        return record
    return _final_action_prs_by_final_action_id(root).get(hold_id)


def _final_action_links(
    closure_evidence: dict[str, Any],
    conversation_lanes: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any] | None, dict[str, Any] | None]]:
    links_by_hold_id: dict[str, tuple[dict[str, Any] | None, dict[str, Any] | None]] = {}
    order: list[str] = []

    def merge_link(
        hold_id: str,
        *,
        spine: dict[str, Any] | None = None,
        lane: dict[str, Any] | None = None,
    ) -> None:
        existing_spine, existing_lane = links_by_hold_id.get(hold_id, (None, None))
        if hold_id not in links_by_hold_id:
            order.append(hold_id)
        links_by_hold_id[hold_id] = (
            existing_spine if existing_spine is not None else spine,
            existing_lane if existing_lane is not None else lane,
        )

    for spine in closure_evidence.get("items") or []:
        if not isinstance(spine, dict):
            continue
        hold_id = _final_action_id_from_ref(spine.get("final_action_ref"))
        if hold_id is not None:
            merge_link(hold_id, spine=spine)
    for lane in conversation_lanes:
        hold_id = _projection_text(lane.get("final_action_hold_id"))
        if hold_id:
            merge_link(hold_id, lane=lane)
    return [
        (hold_id, links_by_hold_id[hold_id][0], links_by_hold_id[hold_id][1])
        for hold_id in order
    ]


def _conversation_lanes(root: Path, conversation_id: str) -> list[dict[str, Any]]:
    raw_lanes = _read_json_file(root / "feature_lanes.json").get("lanes")
    if not isinstance(raw_lanes, list):
        return []
    return [
        lane
        for lane in raw_lanes
        if isinstance(lane, dict) and lane.get("conversation_id") == conversation_id
    ]


def _lane_feature_id(lane: dict[str, Any] | None) -> str | None:
    if lane is None:
        return None
    return _projection_text(lane.get("feature_id")) or _projection_text(lane.get("lane_id"))


def _lane_source_ref(lane: dict[str, Any] | None) -> str | None:
    feature_id = _lane_feature_id(lane)
    if feature_id is None:
        return None
    return f"feature_lanes.json#lane={feature_id}"


def _review_state(
    root: Path,
    closure_evidence: dict[str, Any],
    conversation_lanes: list[dict[str, Any]],
) -> dict[str, Any]:
    review_plane = _read_json_file(root / "review_plane.json")
    raw_tasks = review_plane.get("review_tasks")
    raw_verdicts = review_plane.get("review_verdicts")
    tasks = (
        [task for task in raw_tasks if isinstance(task, dict)]
        if isinstance(raw_tasks, list)
        else []
    )
    verdicts = (
        [verdict for verdict in raw_verdicts if isinstance(verdict, dict)]
        if isinstance(raw_verdicts, list)
        else []
    )
    tasks_by_verdict_id = {
        str(task.get("verdict_id")): task
        for task in tasks
        if isinstance(task.get("verdict_id"), str) and task.get("verdict_id")
    }
    verdicts_by_id = {
        str(verdict.get("id")): verdict
        for verdict in verdicts
        if isinstance(verdict.get("id"), str) and verdict.get("id")
    }
    lanes_by_verdict_id: dict[str, dict[str, Any]] = {}
    for lane in conversation_lanes:
        verdict_id = _projection_text(lane.get("review_verdict_id"))
        if verdict_id and verdict_id not in lanes_by_verdict_id:
            lanes_by_verdict_id[verdict_id] = lane

    items: list[dict[str, Any]] = []
    decision_summary: dict[str, int] = {}
    seen: set[str] = set()
    used_lane_projection = False
    for spine in closure_evidence.get("items") or []:
        if not isinstance(spine, dict):
            continue
        verdict_id = _review_verdict_id_from_ref(spine.get("review_verdict_ref"))
        if verdict_id is None or verdict_id in seen:
            continue
        verdict = verdicts_by_id.get(verdict_id)
        if not isinstance(verdict, dict):
            continue
        task = tasks_by_verdict_id.get(verdict_id)
        lane = lanes_by_verdict_id.get(verdict_id)
        item = _review_verdict_projection(
            verdict_id,
            verdict,
            task,
            spine=spine,
            lane=lane,
        )
        items.append(item)
        seen.add(verdict_id)
        used_lane_projection = used_lane_projection or lane is not None
        decision = str(item.get("decision") or "unknown")
        decision_summary[decision] = decision_summary.get(decision, 0) + 1
    for lane in conversation_lanes:
        verdict_id = _projection_text(lane.get("review_verdict_id"))
        if verdict_id is None or verdict_id in seen:
            continue
        verdict = verdicts_by_id.get(verdict_id)
        if not isinstance(verdict, dict):
            continue
        task = tasks_by_verdict_id.get(verdict_id)
        item = _review_verdict_projection(verdict_id, verdict, task, lane=lane)
        items.append(item)
        seen.add(verdict_id)
        used_lane_projection = True
        decision = str(item.get("decision") or "unknown")
        decision_summary[decision] = decision_summary.get(decision, 0) + 1

    result: dict[str, Any] = {
        "source_authority": ["review_plane.json", "chat.db:acceptance_spines"],
        "projection_only": True,
        "total": len(items),
        "decision_summary": decision_summary,
        "items": items,
    }
    if used_lane_projection:
        result["projection_source"] = ["feature_lanes.json"]
    return result


def _review_verdict_projection(
    verdict_id: str,
    verdict: dict[str, Any],
    task: dict[str, Any] | None,
    *,
    spine: dict[str, Any] | None = None,
    lane: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task_id = _projection_text(task.get("task_id")) if isinstance(task, dict) else None
    return {
        "id": verdict_id,
        "lane_id": _projection_text(verdict.get("lane_id")),
        "decision": _projection_text(verdict.get("decision")) or "unknown",
        "verdict_status": _projection_text(verdict.get("status")) or "unknown",
        "summary": _projection_text(verdict.get("summary")),
        "task_id": task_id,
        "task_status": _projection_text(task.get("status")) if isinstance(task, dict) else None,
        "graph_id": _projection_text(task.get("graph_id")) if isinstance(task, dict) else None,
        "resolution_id": _projection_text(task.get("resolution_id"))
        if isinstance(task, dict)
        else None,
        "gate_report_ref": _projection_text(task.get("gate_report_ref"))
        if isinstance(task, dict)
        else None,
        "evidence_refs": _string_items(verdict.get("evidence_refs")),
        "patch_instructions": _projection_text(verdict.get("patch_instructions")),
        "terminate_reason": _projection_text(verdict.get("terminate_reason")),
        "created_at": _projection_text(verdict.get("created_at")),
        "source_refs": _review_source_refs(
            verdict_id,
            task_id,
            spine=spine,
            lane=lane,
        ),
        "authority_boundary": _review_authority_boundary(),
    }


def _review_verdict_id_from_ref(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    prefix = "review_plane.json#verdict="
    if not value.startswith(prefix):
        return None
    verdict_id = value.removeprefix(prefix).strip()
    return verdict_id or None


def _review_source_refs(
    verdict_id: str,
    task_id: str | None,
    *,
    spine: dict[str, Any] | None = None,
    lane: dict[str, Any] | None = None,
) -> list[str]:
    refs = [f"review_plane.json#verdict={verdict_id}"]
    if task_id:
        refs.append(f"review_plane.json#task={task_id}")
    if spine is not None:
        spine_id = spine.get("spine_id")
        if isinstance(spine_id, str) and spine_id:
            refs.append(f"chat.db:acceptance_spines#spine={spine_id}")
    lane_ref = _lane_source_ref(lane)
    if lane_ref:
        refs.append(lane_ref)
    return _dedupe(refs)


def _review_authority_boundary() -> dict[str, str]:
    return {
        "producer": "review_plane.json",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "review_verdict_authority_not_github_or_merge_truth",
    }


def _final_action_projection(
    hold: dict[str, Any],
    *,
    root: Path | None = None,
    spine: dict[str, Any] | None = None,
    lane: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    hold_id = _projection_text(hold.get("id"))
    if not hold_id:
        return None
    item = {
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
        "source_refs": _final_action_source_refs(hold_id, hold, spine=spine, lane=lane),
        "authority_boundary": _final_action_authority_boundary(),
    }
    if root is not None:
        pr_record = _final_action_pr_record(root, hold_id, lane)
        pr_projection = _final_action_pr_projection(pr_record)
        if pr_projection is not None:
            item["pull_request"] = pr_projection
        github_gate = _final_action_github_gate_projection(root, hold_id, item, lane=lane)
        if github_gate is not None:
            item["github_gate"] = github_gate
    return item


def _final_action_pr_projection(record: dict[str, Any] | None) -> dict[str, Any] | None:
    if record is None:
        return None
    pr_id = _projection_text(record.get("id"))
    if pr_id is None:
        return None
    draft = record.get("draft")
    return {
        "id": pr_id,
        "ref": f"final_action_prs.json#pr={pr_id}",
        "status": _projection_text(record.get("status")) or "unknown",
        "repo": _projection_text(record.get("repo")),
        "base_branch": _projection_text(record.get("base_branch")),
        "head_branch": _projection_text(record.get("head_branch")),
        "commit_sha": _projection_text(record.get("commit_sha")),
        "pull_request_number": record.get("pull_request_number"),
        "pull_request_url": _projection_text(record.get("pull_request_url")),
        "head_sha": _projection_text(record.get("head_sha")),
        "draft": draft if isinstance(draft, bool) else None,
        "created_at": _projection_text(record.get("created_at")),
        "proof_boundary": _projection_text(record.get("proof_boundary")),
        "authority_boundary": _final_action_pr_authority_boundary(),
    }


def _final_action_github_gate_projection(
    root: Path,
    hold_id: str,
    item: dict[str, Any],
    *,
    lane: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    ref = _projection_text(item.get("github_gate_evidence_ref")) or _projection_text(
        lane.get("github_gate_evidence_ref") if lane is not None else None
    )
    if ref is None:
        return None
    record = _accepted_github_gate_record(root, ref, final_action_id=hold_id)
    if record is None:
        return None
    return {
        "ref": ref,
        "status": "accepted",
        "details": _github_gate_details(record),
        "authority_boundary": _github_gate_authority_boundary(),
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
    *,
    spine: dict[str, Any] | None = None,
    lane: dict[str, Any] | None = None,
) -> list[str]:
    refs = [f"final_actions.json#hold={hold_id}"]
    verdict_ref = spine.get("review_verdict_ref") if spine is not None else None
    if isinstance(verdict_ref, str) and verdict_ref:
        refs.append(verdict_ref)
    elif isinstance(hold.get("verdict_id"), str) and hold["verdict_id"]:
        refs.append(f"review_plane.json#verdict={hold['verdict_id']}")
    if spine is not None:
        spine_id = spine.get("spine_id")
        if isinstance(spine_id, str) and spine_id:
            refs.append(f"chat.db:acceptance_spines#spine={spine_id}")
    lane_ref = _lane_source_ref(lane)
    if lane_ref:
        refs.append(lane_ref)
    return _dedupe(refs)


def _final_action_authority_boundary() -> dict[str, str]:
    return {
        "producer": "final_actions.json",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "final_action_hold_not_github_or_merge_truth",
    }


def _final_action_pr_authority_boundary() -> dict[str, str]:
    return {
        "producer": "final_action_prs.json",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "pull_request_record_not_ci_or_merge_truth",
    }


def _github_gate_authority_boundary() -> dict[str, str]:
    return {
        "producer": "github_gate_evidence.json",
        "consumer": "frontend.peer_chat_ux_projection",
        "condition": "read_only_projection",
        "proof_boundary": "server_side_merge_proof_projection_not_new_truth",
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


def _supporting_context_continuity_attempt_ref(context: dict[str, Any]) -> str | None:
    attempt_ref = _projection_text(context.get("continuity_attempt_ref"))
    if attempt_ref is None:
        return None
    return attempt_ref[:_SUPPORTING_CONTEXT_SOURCE_REF_MAX_CHARS]


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped
