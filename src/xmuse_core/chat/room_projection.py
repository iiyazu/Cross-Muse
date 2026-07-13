"""Bounded, Room-authority-only read models for the browser chat experience."""

from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.mentions import normalize_address
from xmuse_core.chat.participant_store import INIT_GOD_ROLE
from xmuse_core.chat.room_database import RoomDatabase

ROOM_CHAT_SCHEMA_VERSION = "room_chat_projection/v3"
ROOM_LIST_SCHEMA_VERSION = "room_list_projection/v1"
ROOM_PROJECTION_PROOF_BOUNDARY = "derived_from_room_authority"


def _has_skill_decision_table(conn: sqlite3.Connection) -> bool:
    return (
        conn.execute(
            "select 1 from sqlite_master where type = 'table' "
            "and name = 'room_attempt_skill_decisions'"
        ).fetchone()
        is not None
    )


def _has_observation_batch_tables(conn: sqlite3.Connection) -> bool:
    rows = conn.execute(
        "select name from sqlite_master where type = 'table' "
        "and name in ('room_observation_batches', 'room_observation_batch_members')"
    ).fetchall()
    has_tables = {str(row["name"]) for row in rows} == {
        "room_observation_batches",
        "room_observation_batch_members",
    }
    if not has_tables:
        return False
    attempt_columns = {
        str(row["name"]) for row in conn.execute("pragma table_info(room_observation_attempts)")
    }
    return "batch_id" in attempt_columns


def _batch_membership_join(
    observation_alias: str,
    *,
    member_alias: str,
    batch_alias: str,
    available: bool,
) -> str:
    if not available:
        return ""
    return (
        f" left join room_observation_batch_members {member_alias} "
        f"on {member_alias}.observation_id = {observation_alias}.observation_id "
        f"left join room_observation_batches {batch_alias} "
        f"on {batch_alias}.batch_id = {member_alias}.batch_id "
    )


def _canonical_outcome_predicate(
    observation_alias: str, *, batch_alias: str, available: bool
) -> str:
    if not available:
        return "1 = 1"
    return (
        f"({batch_alias}.primary_observation_id is null "
        f"or {batch_alias}.primary_observation_id = {observation_alias}.observation_id)"
    )


def _skill_decision_columns(alias: str, *, available: bool) -> str:
    if not available:
        return ""
    return f""",
           {alias}.decision skill_decision,
           {alias}.skill_id skill_id,
           {alias}.skill_version skill_version,
           {alias}.skill_content_sha256 skill_content_sha256,
           {alias}.selection_reason skill_selection_reason,
           {alias}.matched_terms_json skill_matched_terms_json,
           {alias}.context_submitted_at skill_context_submitted_at"""


def _skill_decision_join(attempt_expression: str, *, available: bool) -> str:
    if not available:
        return ""
    return (
        " left join room_attempt_skill_decisions skill_decision "
        f"on skill_decision.attempt_id = {attempt_expression}"
    )


def _attempt_recovery_columns(alias: str) -> str:
    return f""",
           {alias}.recovery_state current_attempt_recovery_state,
           {alias}.recovery_reason_code current_attempt_recovery_reason_code,
           {alias}.recovery_started_at current_attempt_recovery_started_at,
           {alias}.recovery_completed_at current_attempt_recovery_completed_at"""


def _now() -> datetime:
    return datetime.now(UTC)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _decode(value: str | None, default: Any) -> Any:
    if value is None:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _connect(path: Path | str) -> sqlite3.Connection:
    return RoomDatabase(path).connect(readonly=True)


def _mention_handles(rows: Iterable[sqlite3.Row | dict[str, Any]]) -> dict[str, str]:
    values = [dict(row) for row in rows]
    active = [
        row
        for row in values
        if row.get("status") == "active"
        and row.get("cli_kind", "codex") == "codex"
        and row.get("role") != INIT_GOD_ROLE
    ]
    handles: dict[str, str] = {}
    for participant in values:
        participant_id = str(participant["participant_id"])
        role_handle = f"@{participant['role']}"
        normalized = normalize_address(role_handle)
        matches = [
            candidate
            for candidate in active
            if normalized
            in {
                normalize_address(f"@{candidate['role']}"),
                normalize_address(f"@{candidate['display_name']}"),
            }
        ]
        handles[participant_id] = (
            role_handle
            if len(matches) == 1 and matches[0]["participant_id"] == participant_id
            else f"@participant:{participant_id}"
        )
    return handles


def _participant_payload(row: sqlite3.Row | dict[str, Any], handle: str) -> dict[str, Any]:
    value = dict(row)
    status = value["status"] if value.get("cli_kind", "codex") == "codex" else "stopped"
    return {
        "participant_id": value["participant_id"],
        "role": value["role"],
        "display_name": value["display_name"],
        "status": status,
        "participant_status": status,
        "mention_handle": handle,
    }


def _expired(expires_at: str | None, current: datetime) -> bool:
    if not expires_at:
        return False
    try:
        return datetime.fromisoformat(expires_at.replace("Z", "+00:00")) <= current
    except ValueError:
        return False


def _frontier_payload(row: sqlite3.Row | dict[str, Any], current: datetime) -> dict[str, Any]:
    value = dict(row)
    expired = value["status"] == "claimed" and _expired(value.get("expires_at"), current)
    control_state = value.get("control_state", "active")
    observation_id = value["observation_id"]
    control_seq = int(value.get("control_seq", 0))
    attempt_count = int(value["attempt_count"])
    attempt_state = value.get("current_attempt_state")
    cancel_available = bool(
        control_state == "active"
        and value["status"] == "claimed"
        and attempt_state in {"claimed", "delivering"}
    )
    retry_available = bool(
        control_state in {"cancelled", "exhausted"}
        and attempt_state not in {"claimed", "delivering", "cancel_requested", "cancel_pending"}
        and value.get("current_attempt_provider_phase") not in {"ensure_started", "cleanup_pending"}
    )

    def action(action_type: str, available: bool) -> dict[str, Any]:
        return {
            "available": available,
            "method": "POST",
            "href": (
                f"/api/chat/operator/room-observations/{observation_id}/{action_type}"
                if available
                else None
            ),
            "expected_state": control_state,
            "expected_attempt_count": attempt_count,
            "expected_control_seq": control_seq,
        }

    current_attempt = (
        {
            "attempt_number": int(value["current_attempt_number"]),
            "effective_attempt_limit": int(value["current_attempt_limit"]),
            "state": attempt_state,
            "reason_code": value.get("current_attempt_reason_code"),
            "claimed_at": value.get("current_attempt_claimed_at"),
            "expires_at": value.get("current_attempt_expires_at"),
            "transport_started_at": value.get("current_attempt_transport_started_at"),
            "finished_at": value.get("current_attempt_finished_at"),
            "updated_at": value.get("current_attempt_updated_at"),
        }
        if value.get("current_attempt_id") and attempt_state
        else None
    )
    if current_attempt is not None:
        recovery_state = value.get("current_attempt_recovery_state") or "none"
        if recovery_state in {"fenced", "cleanup_pending"}:
            next_action = "cleanup_pending"
        elif recovery_state == "recovered" and control_state == "exhausted":
            next_action = "will_exhaust"
        elif recovery_state == "recovered" and value["status"] == "pending":
            next_action = "will_retry"
        else:
            next_action = "none"
        current_attempt["recovery"] = {
            "state": recovery_state,
            "reason_code": value.get("current_attempt_recovery_reason_code"),
            "started_at": value.get("current_attempt_recovery_started_at"),
            "completed_at": value.get("current_attempt_recovery_completed_at"),
            "next_action": next_action,
        }
        skill_decision = _skill_decision_payload(value)
        if skill_decision is not None:
            current_attempt["skill_decision"] = skill_decision
    return {
        "observation_id": observation_id,
        "activity_id": value["activity_id"],
        "room_seq": int(value["room_seq"]),
        "correlation_id": value["correlation_id"],
        "status": value["status"],
        "expired": expired,
        "expires_at": value.get("expires_at"),
        "attempt_count": attempt_count,
        "unresolved_count": int(value.get("unresolved_count", 1)),
        "priority": int(value["priority"]),
        "mentioned": int(value["priority"]) > 0,
        "control_state": control_state,
        "control_seq": control_seq,
        "manual_retry_budget": int(value.get("manual_retry_budget", 0)),
        "current_attempt": current_attempt,
        "actions": {
            "cancel": action("cancel", cancel_available),
            "retry": action("retry", retry_available),
        },
        "created_at": value["created_at"],
    }


def _outcome_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    value = dict(row)
    payload = {
        "observation_id": value["observation_id"],
        "outcome_type": value["outcome_type"],
        "completed_at": value["completed_at"],
        "produced_activity_id": value.get("produced_activity_id"),
        "produced_message_id": value.get("produced_message_id"),
        "produced_proposal_id": value.get("produced_proposal_id"),
    }
    skill_decision = _skill_decision_payload(value)
    if skill_decision is not None:
        payload["skill_decision"] = skill_decision
    return payload


def _skill_decision_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any] | None:
    value = dict(row)
    if value.get("skill_decision") != "selected" or not value.get("skill_id"):
        return None
    context_submitted_at = value.get("skill_context_submitted_at")
    decoded_terms = _decode(value.get("skill_matched_terms_json"), [])
    matched_terms = (
        [term for term in decoded_terms if isinstance(term, str)]
        if isinstance(decoded_terms, list)
        else []
    )
    return {
        "skill_id": value["skill_id"],
        "version": value["skill_version"],
        "content_sha256": value["skill_content_sha256"],
        "selection_reason": value["skill_selection_reason"],
        "matched_terms": matched_terms,
        "context_status": "submitted" if context_submitted_at else "selected",
        "context_submitted_at": context_submitted_at,
    }


def _participant_state(
    *, participant_status: str, frontier: dict[str, Any] | None, outcome: dict[str, Any] | None
) -> str:
    if participant_status == "stopped":
        return "stopped"
    if frontier is not None:
        recovery_state = ((frontier.get("current_attempt") or {}).get("recovery") or {}).get(
            "state"
        )
        if recovery_state in {"fenced", "cleanup_pending"}:
            return "runtime_recovery"
        control_state = frontier.get("control_state", "active")
        if control_state in {"cancel_requested", "cancel_pending"}:
            return "cancel_pending"
        if control_state in {"cancelled", "exhausted"}:
            return control_state
        if frontier["status"] == "pending":
            return "pending"
        return "runtime_recovery" if frontier["expired"] else "thinking"
    outcome_type = outcome.get("outcome_type") if outcome else None
    outcome_key = outcome_type if isinstance(outcome_type, str) else ""
    return {
        "respond": "responded",
        "handoff": "handoff",
        "propose": "proposed",
        "noop": "noop",
        "defer": "deferred",
    }.get(outcome_key, "settled")


def _room_status(active_count: int, attention_count: int) -> str:
    if attention_count:
        return "attention"
    if active_count:
        return "active"
    return "settled"


def _observation_batch_metadata(
    conn: sqlite3.Connection,
    observation_ids: Iterable[str],
    *,
    available: bool,
) -> dict[str, dict[str, Any]]:
    """Load bounded batch evidence for already-selected projection observations.

    Read models deliberately select their frontiers/outcomes first and only then
    hydrate those observation ids in one query.  This keeps the projection query
    count constant and avoids reading every historical batch in a busy Room.
    """
    selected = sorted({value for value in observation_ids if value})
    if not selected:
        return {}
    placeholders = ",".join("?" for _ in selected)
    if available:
        rows = conn.execute(
            f"""with attempt_totals as (
                    select batch_id, count(*) attempt_count
                    from room_observation_attempts
                    where batch_id is not null
                    group by batch_id
                  )
                  select o.observation_id lookup_observation_id,
                         o.attempt_count singleton_attempt_count,
                         source.activity_id source_activity_id,
                         source.seq source_room_seq,
                         source.actor_kind source_actor_kind,
                         source.delivery_mode source_delivery_mode,
                         produced.payload_json produced_payload_json,
                         b.batch_id, b.phase, b.cutoff_seq, b.member_count,
                         coalesce(attempt_totals.attempt_count, 0) batch_attempt_count,
                         member.ordinal member_ordinal,
                         member.activity_id member_activity_id,
                         member.activity_seq member_activity_seq
                  from room_observations o
                  join room_activities source on source.activity_id = o.activity_id
                  left join room_observation_attempts current_attempt
                    on current_attempt.attempt_id = o.current_attempt_id
                  left join room_observation_batch_members lookup_member
                    on lookup_member.observation_id = o.observation_id
                  left join room_observation_batches b
                    on b.batch_id = coalesce(current_attempt.batch_id, lookup_member.batch_id)
                  left join room_observation_batch_members member
                    on member.batch_id = b.batch_id
                  left join attempt_totals on attempt_totals.batch_id = b.batch_id
                  left join room_activities produced
                    on produced.activity_id = o.produced_activity_id
                  where o.observation_id in ({placeholders})
                  order by o.observation_id, member.ordinal""",
            selected,
        ).fetchall()
    else:
        rows = conn.execute(
            f"""select o.observation_id lookup_observation_id,
                       o.attempt_count singleton_attempt_count,
                       source.activity_id source_activity_id,
                       source.seq source_room_seq,
                       source.actor_kind source_actor_kind,
                       source.delivery_mode source_delivery_mode,
                       produced.payload_json produced_payload_json
                from room_observations o
                join room_activities source on source.activity_id = o.activity_id
                left join room_activities produced
                  on produced.activity_id = o.produced_activity_id
                where o.observation_id in ({placeholders})
                order by o.observation_id""",
            selected,
        ).fetchall()

    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        value = dict(row)
        observation_id = str(value["lookup_observation_id"])
        batch_id = value.get("batch_id")
        item = grouped.get(observation_id)
        if item is None:
            source_seq = int(value["source_room_seq"])
            actual_member_count = int(value.get("member_count") or 1)
            item = {
                "batch_id": batch_id,
                "phase": (
                    value.get("phase")
                    or ("root" if value["source_actor_kind"] == "human" else "peer")
                ),
                "member_count": actual_member_count,
                "member_activity_refs": [],
                "attempt_count": int(
                    (value.get("batch_attempt_count") or 0)
                    if batch_id is not None
                    else value["singleton_attempt_count"]
                ),
                "context_only_tail": bool(
                    _decode(value.get("produced_payload_json"), {}).get("context_only")
                ),
                "coverage": {
                    "mode": "batch" if batch_id is not None else "singleton_fallback",
                    "cutoff_room_seq": int(value.get("cutoff_seq") or source_seq),
                    "included_member_count": 0,
                    "omitted_member_count": actual_member_count,
                },
            }
            grouped[observation_id] = item
        member_activity_id = value.get("member_activity_id")
        if member_activity_id:
            item["member_activity_refs"].append(
                {
                    "activity_id": member_activity_id,
                    "room_seq": int(value["member_activity_seq"]),
                }
            )
        elif not item["member_activity_refs"]:
            item["member_activity_refs"].append(
                {
                    "activity_id": value["source_activity_id"],
                    "room_seq": int(value["source_room_seq"]),
                }
            )

    for item in grouped.values():
        included = len(item["member_activity_refs"])
        item["coverage"]["included_member_count"] = included
        item["coverage"]["omitted_member_count"] = max(0, item["member_count"] - included)
    return grouped


def _attach_observation_batch_metadata(
    participants: list[dict[str, Any]],
    turns: list[dict[str, Any]],
    metadata: dict[str, dict[str, Any]],
) -> None:
    summaries: list[dict[str, Any]] = []
    for participant in participants:
        for key in ("frontier", "last_completed_outcome"):
            value = participant.get(key)
            if isinstance(value, dict):
                summaries.append(value)
    for turn in turns:
        for participant in turn["participants"]:
            for key in ("frontier", "latest_outcome"):
                value = participant.get(key)
                if isinstance(value, dict):
                    summaries.append(value)
    for summary in summaries:
        batch = metadata.get(str(summary.get("observation_id") or ""))
        if batch is not None:
            summary.update(batch)


def _timeline_item(
    row: sqlite3.Row, participant_names: dict[str, str] | None = None
) -> dict[str, Any]:
    payload = _decode(row["payload_json"], {})
    envelope = _decode(row["envelope_json"], {})
    references = _decode(row["references_json"], [])
    outcome_type = payload.get("outcome_type")
    kind = (
        "proposal"
        if row["materialized_proposal_id"]
        else ("handoff" if outcome_type == "handoff" else "message")
    )
    content = row["message_content"] if row["materialized_message_id"] else row["proposal_content"]
    if row["actor_kind"] == "human":
        actor = {
            "kind": "human",
            "identity": row["actor_identity"],
            "participant_id": None,
            "role": "human",
            "display_name": row["message_author"] or row["actor_identity"].removeprefix("human:"),
        }
    else:
        participant_id = row["actor_participant_id"]
        actor = {
            "kind": row["actor_kind"],
            # The durable authority identity contains the provider/GOD session id.
            # The browser needs stable authorship, not a reusable internal binding.
            "identity": f"participant:{participant_id}" if participant_id else None,
            "participant_id": participant_id,
            "role": envelope.get("participant_role") or row["participant_role"],
            "display_name": envelope.get("display_name") or row["participant_display_name"],
        }
    target_participant_ids = list(payload.get("target_participant_ids") or [])
    names = participant_names or {}
    reply_envelope = _decode(row["reply_target_envelope_json"], {})
    reply_author = row["reply_target_author"]
    reply_target_display_name = (
        reply_envelope.get("display_name")
        or row["reply_target_participant_display_name"]
        or names.get(str(row["reply_target_proposal_author"] or ""))
        or names.get(str(reply_author or ""))
        or reply_author
    )
    return {
        "kind": kind,
        "room_seq": int(row["seq"]),
        "activity_id": row["activity_id"],
        "activity_type": row["activity_type"],
        "correlation_id": row["correlation_id"],
        "causation_id": row["causation_id"],
        "causal_depth": int(row["causal_depth"]),
        "created_at": row["created_at"],
        "actor": actor,
        "content": content or payload.get("content") or "",
        "message_id": row["materialized_message_id"],
        "proposal_id": row["materialized_proposal_id"],
        "reply_to_activity_id": (
            payload.get("reply_to_activity_id") or row["resolved_reply_activity_id"]
        ),
        "reply_to_message_id": row["reply_to_message_id"],
        "reply_target_display_name": reply_target_display_name,
        "mentions": _decode(row["mentions_json"], []),
        "target_participant_ids": target_participant_ids,
        "handoff_targets": [names.get(value, value) for value in target_participant_ids],
        "context_only_tail": bool(payload.get("context_only")),
        "proposal": (
            {
                "proposal_type": row["proposal_type"],
                "references": references,
                "status": row["proposal_status"],
            }
            if row["materialized_proposal_id"]
            else None
        ),
        "proof_boundary": envelope.get(
            "proof_boundary",
            (
                "durable_room_activity"
                if row["actor_kind"] == "human"
                else ROOM_PROJECTION_PROOF_BOUNDARY
            ),
        ),
    }


_VISIBLE_ACTIVITY_SELECT = """
select a.*, m.author as message_author, m.content as message_content,
       m.envelope_json, m.mentions_json, m.reply_to_message_id,
       reply_message.author as reply_target_author,
       reply_message.envelope_json as reply_target_envelope_json,
       reply_activity.activity_id as resolved_reply_activity_id,
       reply_participant.display_name as reply_target_participant_display_name,
       reply_proposal.author as reply_target_proposal_author,
       p.role as participant_role, p.display_name as participant_display_name,
       pr.content as proposal_content, pr.proposal_type, pr.references_json,
       pr.status as proposal_status
from room_activities a
left join messages m on m.id = a.materialized_message_id
left join messages reply_message on reply_message.id = m.reply_to_message_id
left join room_activities reply_activity
  on reply_activity.activity_id = coalesce(
       nullif(json_extract(a.payload_json, '$.reply_to_activity_id'), ''),
       a.causation_id
     )
left join participants reply_participant
  on reply_participant.participant_id = reply_activity.actor_participant_id
left join proposals reply_proposal
  on reply_proposal.id = reply_activity.materialized_proposal_id
left join proposals pr on pr.id = a.materialized_proposal_id
left join participants p on p.participant_id = a.actor_participant_id
where a.conversation_id = ? and a.delivery_mode = 'active'
  and (a.materialized_message_id is not null or a.materialized_proposal_id is not null)
"""


def build_room_chat_projection(
    conversation_id: str,
    base_dir: Path | str,
    *,
    limit: int = 60,
    before_room_seq: int | None = None,
    after_room_seq: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build one bounded room timeline and its durable convergence state."""
    if before_room_seq is not None and after_room_seq is not None:
        raise ValueError("room_projection_cursors_mutually_exclusive")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise ValueError("room_projection_limit_invalid")
    for cursor in (before_room_seq, after_room_seq):
        if cursor is not None and (isinstance(cursor, bool) or cursor < 0):
            raise ValueError("room_projection_cursor_invalid")

    db_path = Path(base_dir) / "chat.db"
    current = now or _now()
    if current.tzinfo is None:
        raise ValueError("room_projection_now_timezone_required")
    with _connect(db_path) as conn:
        # Keep the timeline, convergence facts, and invalidation cursor on one
        # SQLite read snapshot so consumers never skip a newer event for state
        # that this response could not yet observe.
        conn.execute("begin")
        conversation = conn.execute(
            "select id, title, created_at from conversations where id = ?",
            (conversation_id,),
        ).fetchone()
        if conversation is None:
            raise KeyError(conversation_id)
        participant_rows = conn.execute(
            "select participant_id, role, display_name, cli_kind, status from participants "
            "where conversation_id = ? and role <> ? order by rowid",
            (conversation_id, INIT_GOD_ROLE),
        ).fetchall()
        handles = _mention_handles(participant_rows)
        participant_names = {
            str(row["participant_id"]): str(row["display_name"]) for row in participant_rows
        }
        has_skill_decisions = _has_skill_decision_table(conn)
        has_observation_batches = _has_observation_batch_tables(conn)

        mode = (
            "before"
            if before_room_seq is not None
            else "after"
            if after_room_seq is not None
            else "latest"
        )
        params: list[Any] = [conversation_id]
        predicate = ""
        order = "order by a.seq desc"
        if before_room_seq is not None:
            predicate = " and a.seq < ?"
            params.append(before_room_seq)
        elif after_room_seq is not None:
            predicate = " and a.seq > ?"
            params.append(after_room_seq)
            order = "order by a.seq asc"
        rows = conn.execute(
            f"{_VISIBLE_ACTIVITY_SELECT}{predicate} {order} limit ?",
            (*params, limit),
        ).fetchall()
        if mode in {"latest", "before"}:
            rows = list(reversed(rows))
        timeline_items = [_timeline_item(row, participant_names) for row in rows]
        bounds = conn.execute(
            "select coalesce(min(seq), 0) earliest, coalesce(max(seq), 0) latest "
            "from room_activities "
            "where conversation_id = ? and delivery_mode = 'active' "
            "and (materialized_message_id is not null or materialized_proposal_id is not null)",
            (conversation_id,),
        ).fetchone()
        earliest_visible = int(bounds["earliest"])
        latest_visible = int(bounds["latest"])
        min_seq = int(rows[0]["seq"]) if rows else None
        max_seq = int(rows[-1]["seq"]) if rows else None
        if min_seq is not None:
            has_older = bool(earliest_visible and earliest_visible < min_seq)
        elif mode == "after" and after_room_seq is not None:
            has_older = bool(earliest_visible and earliest_visible <= after_room_seq)
        else:
            has_older = False
        if max_seq is not None:
            has_newer = bool(latest_visible and latest_visible > max_seq)
        elif mode == "before" and before_room_seq is not None:
            has_newer = bool(latest_visible and latest_visible >= before_room_seq)
        else:
            has_newer = False
        next_before = (
            min_seq
            if has_older and min_seq is not None
            else after_room_seq + 1
            if has_older and mode == "after" and after_room_seq is not None
            else None
        )
        next_after = (
            max_seq
            if max_seq is not None
            else max(0, before_room_seq - 1)
            if has_newer and mode == "before" and before_room_seq is not None
            else after_room_seq
        )

        global_frontiers = _global_frontiers(
            conn, conversation_id, current, has_skill_decisions=has_skill_decisions
        )
        global_outcomes = _global_outcomes(
            conn,
            conversation_id,
            has_skill_decisions=has_skill_decisions,
            has_observation_batches=has_observation_batches,
        )
        participants = []
        for row in participant_rows:
            participant_id = row["participant_id"]
            runtime_supported = row["cli_kind"] == "codex"
            frontier = global_frontiers.get(participant_id) if runtime_supported else None
            outcome = global_outcomes.get(participant_id)
            participants.append(
                {
                    **_participant_payload(row, handles[participant_id]),
                    "state": _participant_state(
                        participant_status=(row["status"] if runtime_supported else "stopped"),
                        frontier=frontier,
                        outcome=outcome,
                    ),
                    "frontier": frontier,
                    "last_completed_outcome": outcome,
                    "unresolved_count": (
                        int(frontier["unresolved_count"]) if frontier is not None else 0
                    ),
                }
            )

        turn_rows = conn.execute(
            "select activity_id, seq, correlation_id, materialized_message_id, created_at "
            "from room_activities where conversation_id = ? and actor_kind = 'human' "
            "and delivery_mode = 'active' order by seq desc limit 8",
            (conversation_id,),
        ).fetchall()
        turns, total_active, total_attention, excluded_stopped = _turns(
            conn,
            conversation_id,
            turn_rows,
            participant_rows,
            handles,
            current,
            has_skill_decisions=has_skill_decisions,
            has_observation_batches=has_observation_batches,
        )
        projected_observation_ids = {
            str(value["observation_id"])
            for participant in participants
            for key in ("frontier", "last_completed_outcome")
            if isinstance((value := participant.get(key)), dict) and value.get("observation_id")
        }
        projected_observation_ids.update(
            str(value["observation_id"])
            for turn in turns
            for participant in turn["participants"]
            for key in ("frontier", "latest_outcome")
            if isinstance((value := participant.get(key)), dict) and value.get("observation_id")
        )
        batch_metadata = _observation_batch_metadata(
            conn,
            projected_observation_ids,
            available=has_observation_batches,
        )
        _attach_observation_batch_metadata(participants, turns, batch_metadata)
        event_cursor = int(
            conn.execute(
                "select coalesce(max(seq), 0) from chat_frontend_events where conversation_id = ?",
                (conversation_id,),
            ).fetchone()[0]
        )

    returned_active = sum(turn["status"] != "settled" for turn in turns)
    return {
        "schema_version": ROOM_CHAT_SCHEMA_VERSION,
        "projection_only": True,
        "proof_boundary": ROOM_PROJECTION_PROOF_BOUNDARY,
        "source_authority": [
            "chat.db:room_activities",
            "chat.db:room_observations",
            "chat.db:room_observation_attempts",
            "chat.db:participants",
            "chat.db:messages",
            "chat.db:proposals",
        ]
        + (["chat.db:room_attempt_skill_decisions"] if has_skill_decisions else [])
        + (
            [
                "chat.db:room_observation_batches",
                "chat.db:room_observation_batch_members",
            ]
            if has_observation_batches
            else []
        ),
        "generated_at": _stamp(current),
        "conversation_id": conversation_id,
        "event_cursor": event_cursor,
        "event_cursor_source": "chat.db:chat_frontend_events",
        "event_cursor_proof_boundary": "projection_invalidation_cursor_not_room_authority",
        "conversation": dict(conversation),
        "latest_visible_room_seq": latest_visible,
        "status": _room_status(total_active, total_attention),
        "participants": participants,
        "turns": turns,
        "active_turn_count": total_active,
        "attention_turn_count": total_attention,
        "additional_active_turn_count": max(0, total_active - returned_active),
        "excluded_stopped_count": excluded_stopped,
        "timeline_items": timeline_items,
        "page": {
            "mode": mode,
            "limit": limit,
            "before_room_seq": before_room_seq,
            "after_room_seq": after_room_seq,
            "has_older": has_older,
            "has_newer": has_newer,
            "next_before_room_seq": next_before,
            "next_after_room_seq": next_after,
        },
    }


def _global_frontiers(
    conn: sqlite3.Connection,
    conversation_id: str,
    current: datetime,
    *,
    has_skill_decisions: bool,
) -> dict[str, dict[str, Any]]:
    decision_columns = _skill_decision_columns("skill_decision", available=has_skill_decisions)
    decision_join = _skill_decision_join(
        "current_attempt.attempt_id", available=has_skill_decisions
    )
    recovery_columns = _attempt_recovery_columns("current_attempt")
    rows = conn.execute(
        f"""with ranked as (
            select o.*, a.seq room_seq, a.correlation_id,
                   count(*) over (partition by o.participant_id) unresolved_count,
                   current_attempt.state current_attempt_state,
                   current_attempt.provider_phase current_attempt_provider_phase,
                   current_attempt.attempt_number current_attempt_number,
                   current_attempt.effective_attempt_limit current_attempt_limit,
                   current_attempt.reason_code current_attempt_reason_code,
                   current_attempt.claimed_at current_attempt_claimed_at,
                   current_attempt.expires_at current_attempt_expires_at,
                   current_attempt.transport_started_at current_attempt_transport_started_at,
                   current_attempt.finished_at current_attempt_finished_at,
                   current_attempt.updated_at current_attempt_updated_at
                   {recovery_columns}
                   {decision_columns},
                   row_number() over (
                       partition by o.participant_id order by a.seq, o.rowid
                   ) rank
            from room_observations o
            join room_activities a on a.activity_id = o.activity_id
            left join room_observation_attempts current_attempt
              on current_attempt.attempt_id = o.current_attempt_id
            {decision_join}
            where o.conversation_id = ? and o.delivery_mode = 'active'
              and o.status <> 'completed'
        ) select * from ranked where rank = 1""",
        (conversation_id,),
    ).fetchall()
    return {row["participant_id"]: _frontier_payload(row, current) for row in rows}


def _global_outcomes(
    conn: sqlite3.Connection,
    conversation_id: str,
    *,
    has_skill_decisions: bool,
    has_observation_batches: bool,
) -> dict[str, dict[str, Any]]:
    decision_columns = _skill_decision_columns("skill_decision", available=has_skill_decisions)
    decision_join = _skill_decision_join("o.current_attempt_id", available=has_skill_decisions)
    batch_join = _batch_membership_join(
        "o",
        member_alias="outcome_member",
        batch_alias="outcome_batch",
        available=has_observation_batches,
    )
    canonical = _canonical_outcome_predicate(
        "o", batch_alias="outcome_batch", available=has_observation_batches
    )
    rows = conn.execute(
        f"""with ranked as (
            select o.*, a.seq room_seq
                   {decision_columns},
                   row_number() over (
                       partition by o.participant_id order by a.seq desc, o.rowid desc
                   ) rank
            from room_observations o join room_activities a on a.activity_id = o.activity_id
            {decision_join}
            {batch_join}
            where o.conversation_id = ? and o.delivery_mode = 'active'
              and o.status = 'completed' and {canonical}
        ) select * from ranked where rank = 1""",
        (conversation_id,),
    ).fetchall()
    return {row["participant_id"]: _outcome_payload(row) for row in rows}


def _turns(
    conn: sqlite3.Connection,
    conversation_id: str,
    root_rows: list[sqlite3.Row],
    participant_rows: list[sqlite3.Row],
    handles: dict[str, str],
    current: datetime,
    *,
    has_skill_decisions: bool,
    has_observation_batches: bool,
) -> tuple[list[dict[str, Any]], int, int, int]:
    counts = conn.execute(
        """select count(distinct case when p.status = 'active' and p.cli_kind = 'codex'
                                   and o.status <> 'completed'
                                   then a.correlation_id end) active_turn_count,
                  count(distinct case when p.status = 'active' and p.cli_kind = 'codex'
                                   and o.status <> 'completed'
                                   and ((o.status = 'claimed' and o.expires_at <= ?)
                                        or o.control_state <> 'active'
                                        or current_attempt.recovery_state
                                           in ('fenced', 'cleanup_pending'))
                                   then a.correlation_id end) attention_turn_count,
                  sum(case when (p.status = 'stopped' or p.cli_kind <> 'codex')
                           and o.status <> 'completed'
                           then 1 else 0 end) excluded_stopped_count
           from room_observations o
           join room_activities a on a.activity_id = o.activity_id
           join participants p on p.participant_id = o.participant_id
           left join room_observation_attempts current_attempt
             on current_attempt.attempt_id = o.current_attempt_id
           where o.conversation_id = ? and o.delivery_mode = 'active'""",
        (_stamp(current), conversation_id),
    ).fetchone()
    total_active = int(counts["active_turn_count"] or 0)
    total_attention = int(counts["attention_turn_count"] or 0)
    total_excluded_stopped = int(counts["excluded_stopped_count"] or 0)
    if not root_rows:
        return [], total_active, total_attention, total_excluded_stopped
    correlations = [row["correlation_id"] for row in root_rows]
    placeholders = ",".join("?" for _ in correlations)
    decision_columns = _skill_decision_columns("skill_decision", available=has_skill_decisions)
    current_decision_join = _skill_decision_join(
        "current_attempt.attempt_id", available=has_skill_decisions
    )
    recovery_columns = _attempt_recovery_columns("current_attempt")
    observation_decision_join = _skill_decision_join(
        "o.current_attempt_id", available=has_skill_decisions
    )
    aggregate_batch_join = _batch_membership_join(
        "o",
        member_alias="aggregate_member",
        batch_alias="aggregate_batch",
        available=has_observation_batches,
    )
    canonical_aggregate_outcome = _canonical_outcome_predicate(
        "o", batch_alias="aggregate_batch", available=has_observation_batches
    )
    aggregates = conn.execute(
        f"""select a.correlation_id, o.participant_id, count(*) observation_count,
                    sum(case when o.status <> 'completed' then 1 else 0 end) unresolved_count,
                    count(distinct case
                        when o.status = 'completed' and o.outcome_type = 'respond'
                             and {canonical_aggregate_outcome}
                        then coalesce(o.produced_activity_id, o.observation_id)
                    end) response_count
             from room_observations o join room_activities a on a.activity_id = o.activity_id
             {aggregate_batch_join}
             where o.conversation_id = ? and o.delivery_mode = 'active'
               and a.correlation_id in ({placeholders})
             group by a.correlation_id, o.participant_id""",
        (conversation_id, *correlations),
    ).fetchall()
    evidence_join = (
        "left join room_attempt_skill_decisions evidence_skill "
        "on evidence_skill.attempt_id = evidence_attempt.attempt_id"
        if has_skill_decisions
        else ""
    )
    skill_count = "count(distinct evidence_skill.attempt_id)" if has_skill_decisions else "0"
    evidence_rows = conn.execute(
        f"""select a.correlation_id,
                   count(distinct o.observation_id) observation_count,
                   count(distinct evidence_attempt.attempt_id) attempt_count,
                   {skill_count} skill_decision_count
            from room_observations o
            join room_activities a on a.activity_id = o.activity_id
            left join room_observation_attempts evidence_attempt
              on evidence_attempt.observation_id = o.observation_id
            {evidence_join}
            where o.conversation_id = ? and o.delivery_mode = 'active'
              and a.correlation_id in ({placeholders})
            group by a.correlation_id""",
        (conversation_id, *correlations),
    ).fetchall()
    frontiers = conn.execute(
        f"""with ranked as (
              select a.correlation_id, o.*, a.seq room_seq,
                     current_attempt.state current_attempt_state,
                     current_attempt.provider_phase current_attempt_provider_phase,
                     current_attempt.attempt_number current_attempt_number,
                     current_attempt.effective_attempt_limit current_attempt_limit,
                     current_attempt.reason_code current_attempt_reason_code,
                     current_attempt.claimed_at current_attempt_claimed_at,
                     current_attempt.expires_at current_attempt_expires_at,
                     current_attempt.transport_started_at current_attempt_transport_started_at,
                     current_attempt.finished_at current_attempt_finished_at,
                     current_attempt.updated_at current_attempt_updated_at
                     {recovery_columns}
                     {decision_columns},
                     row_number() over (partition by a.correlation_id, o.participant_id
                                        order by a.seq, o.rowid) rank
              from room_observations o
              join room_activities a on a.activity_id = o.activity_id
              left join room_observation_attempts current_attempt
                on current_attempt.attempt_id = o.current_attempt_id
              {current_decision_join}
              where o.conversation_id = ? and o.delivery_mode = 'active'
                and o.status <> 'completed' and a.correlation_id in ({placeholders})
            ) select * from ranked where rank = 1""",
        (conversation_id, *correlations),
    ).fetchall()
    outcomes = conn.execute(
        # Batch members mirror terminal outcome facts for lifecycle/control
        # compatibility.  Only the primary observation represents the one
        # Agent decision and owns its produced activity.
        f"""with ranked as (
              select a.correlation_id, o.*, a.seq room_seq
                     {decision_columns},
                     row_number() over (partition by a.correlation_id, o.participant_id
                                        order by a.seq desc, o.rowid desc) rank
              from room_observations o join room_activities a on a.activity_id = o.activity_id
              {observation_decision_join}
              {
            _batch_membership_join(
                "o",
                member_alias="turn_outcome_member",
                batch_alias="turn_outcome_batch",
                available=has_observation_batches,
            )
        }
              where o.conversation_id = ? and o.delivery_mode = 'active'
                and o.status = 'completed'
                and {
            _canonical_outcome_predicate(
                "o",
                batch_alias="turn_outcome_batch",
                available=has_observation_batches,
            )
        }
                and a.correlation_id in ({placeholders})
            ) select * from ranked where rank = 1""",
        (conversation_id, *correlations),
    ).fetchall()
    aggregate_map = {(r["correlation_id"], r["participant_id"]): r for r in aggregates}
    evidence_map = {str(row["correlation_id"]): dict(row) for row in evidence_rows}
    frontier_map = {
        (r["correlation_id"], r["participant_id"]): _frontier_payload(r, current) for r in frontiers
    }
    outcome_map = {
        (r["correlation_id"], r["participant_id"]): _outcome_payload(r) for r in outcomes
    }
    root_decision_map: dict[tuple[str, str], dict[str, Any]] = {}
    if has_skill_decisions:
        root_activity_ids = [row["activity_id"] for row in root_rows]
        root_placeholders = ",".join("?" for _ in root_activity_ids)
        root_decisions = conn.execute(
            f"""select o.activity_id, o.participant_id
                       {_skill_decision_columns("skill_decision", available=True)}
                from room_observations o
                left join room_attempt_skill_decisions skill_decision
                  on skill_decision.attempt_id = o.current_attempt_id
                where o.conversation_id = ? and o.delivery_mode = 'active'
                  and o.activity_id in ({root_placeholders})""",
            (conversation_id, *root_activity_ids),
        ).fetchall()
        root_decision_map = {
            (row["activity_id"], row["participant_id"]): decision
            for row in root_decisions
            if (decision := _skill_decision_payload(row)) is not None
        }
    participant_by_id = {row["participant_id"]: row for row in participant_rows}
    turns = []
    for root in reversed(root_rows):
        correlation_id = root["correlation_id"]
        members = []
        excluded_stopped = 0
        attention = False
        active = False
        for (correlation, participant_id), aggregate in aggregate_map.items():
            if correlation != correlation_id or participant_id not in participant_by_id:
                continue
            row = participant_by_id[participant_id]
            frontier = frontier_map.get((correlation_id, participant_id))
            outcome = outcome_map.get((correlation_id, participant_id))
            unresolved = int(aggregate["unresolved_count"] or 0)
            runtime_status = row["status"] if row["cli_kind"] == "codex" else "stopped"
            if runtime_status == "stopped" and unresolved:
                excluded_stopped += 1
            elif runtime_status == "active" and unresolved:
                active = True
                attention = attention or bool(
                    frontier
                    and (
                        frontier["expired"]
                        or frontier.get("control_state", "active") != "active"
                        or (
                            ((frontier.get("current_attempt") or {}).get("recovery") or {}).get(
                                "state"
                            )
                            in {"fenced", "cleanup_pending"}
                        )
                    )
                )
            members.append(
                {
                    **_participant_payload(row, handles[participant_id]),
                    "observation_count": int(aggregate["observation_count"]),
                    "unresolved_count": unresolved,
                    "response_count": int(aggregate["response_count"] or 0),
                    "frontier": frontier,
                    "latest_outcome": outcome,
                    "state": _participant_state(
                        participant_status=runtime_status, frontier=frontier, outcome=outcome
                    ),
                    **(
                        {"root_skill_decision": root_skill_decision}
                        if (
                            root_skill_decision := root_decision_map.get(
                                (root["activity_id"], participant_id)
                            )
                        )
                        else {}
                    ),
                }
            )
        turns.append(
            {
                "correlation_id": correlation_id,
                "root_activity_id": root["activity_id"],
                "root_room_seq": int(root["seq"]),
                "root_message_id": root["materialized_message_id"],
                "created_at": root["created_at"],
                "status": "attention" if attention else "active" if active else "settled",
                "excluded_stopped_count": excluded_stopped,
                "observation_count": int(
                    (evidence_map.get(str(correlation_id)) or {}).get("observation_count", 0)
                ),
                "attempt_count": int(
                    (evidence_map.get(str(correlation_id)) or {}).get("attempt_count", 0)
                ),
                "skill_decision_count": int(
                    (evidence_map.get(str(correlation_id)) or {}).get("skill_decision_count", 0)
                ),
                "participants": sorted(members, key=lambda item: item["participant_id"]),
            }
        )
    return turns, total_active, total_attention, total_excluded_stopped


def build_room_list_projection(
    base_dir: Path | str, *, now: datetime | None = None
) -> dict[str, Any]:
    """Build all lightweight room summaries with a fixed number of batch queries."""
    db_path = Path(base_dir) / "chat.db"
    current = now or _now()
    if current.tzinfo is None:
        raise ValueError("room_projection_now_timezone_required")
    with _connect(db_path) as conn:
        conversations = conn.execute(
            "select id, title, created_at from conversations order by rowid"
        ).fetchall()
        participant_rows = conn.execute(
            "select participant_id, conversation_id, role, display_name, cli_kind, status, rowid "
            "from participants where role <> ? order by conversation_id, rowid",
            (INIT_GOD_ROLE,),
        ).fetchall()
        latest_rows = conn.execute(
            """with visible as (
                 select a.*, m.author message_author, m.content message_content,
                        m.envelope_json, m.mentions_json, m.reply_to_message_id,
                        reply_message.author reply_target_author,
                        reply_message.envelope_json reply_target_envelope_json,
                        reply_activity.activity_id resolved_reply_activity_id,
                        reply_participant.display_name reply_target_participant_display_name,
                        reply_proposal.author reply_target_proposal_author,
                        p.role participant_role, p.display_name participant_display_name,
                        pr.content proposal_content, pr.proposal_type,
                        pr.references_json, pr.status proposal_status,
                        row_number() over (partition by a.conversation_id order by a.seq desc) rank
                 from room_activities a
                 left join messages m on m.id = a.materialized_message_id
                 left join messages reply_message on reply_message.id = m.reply_to_message_id
                 left join room_activities reply_activity
                   on reply_activity.activity_id = coalesce(
                        nullif(json_extract(a.payload_json, '$.reply_to_activity_id'), ''),
                        a.causation_id
                      )
                 left join participants reply_participant
                   on reply_participant.participant_id = reply_activity.actor_participant_id
                 left join proposals reply_proposal
                   on reply_proposal.id = reply_activity.materialized_proposal_id
                 left join proposals pr on pr.id = a.materialized_proposal_id
                 left join participants p on p.participant_id = a.actor_participant_id
                 where a.delivery_mode = 'active'
                   and (a.materialized_message_id is not null
                        or a.materialized_proposal_id is not null)
               ) select * from visible where rank = 1"""
        ).fetchall()
        status_rows = conn.execute(
            """select o.conversation_id,
                 count(distinct case when p.status = 'active' and p.cli_kind = 'codex'
                                and o.status <> 'completed'
                                then a.correlation_id end) active_turn_count,
                 count(distinct case when p.status = 'active' and p.cli_kind = 'codex'
                                and o.status <> 'completed'
                                and ((o.status = 'claimed' and o.expires_at <= ?)
                                     or o.control_state <> 'active'
                                     or current_attempt.recovery_state
                                        in ('fenced', 'cleanup_pending'))
                                then a.correlation_id end) attention_turn_count,
                 max(o.updated_at) observation_updated_at
               from room_observations o
               join room_activities a on a.activity_id = o.activity_id
               join participants p on p.participant_id = o.participant_id
               left join room_observation_attempts current_attempt
                 on current_attempt.attempt_id = o.current_attempt_id
               where o.delivery_mode = 'active' group by o.conversation_id""",
            (_stamp(current),),
        ).fetchall()
    participants_by_room: dict[str, list[sqlite3.Row]] = defaultdict(list)
    for row in participant_rows:
        participants_by_room[row["conversation_id"]].append(row)
    latest_by_room = {row["conversation_id"]: row for row in latest_rows}
    status_by_room = {row["conversation_id"]: row for row in status_rows}
    rooms = []
    for conversation in conversations:
        conversation_id = conversation["id"]
        member_rows = participants_by_room.get(conversation_id, [])
        handles = _mention_handles(member_rows)
        latest = latest_by_room.get(conversation_id)
        state = status_by_room.get(conversation_id)
        active_turns = int(state["active_turn_count"] or 0) if state else 0
        attention_turns = int(state["attention_turn_count"] or 0) if state else 0
        latest_item = None
        if latest is not None:
            latest_item = _timeline_item(
                latest,
                {str(row["participant_id"]): str(row["display_name"]) for row in member_rows},
            )
        updated_candidates = [conversation["created_at"]]
        if latest is not None:
            updated_candidates.append(latest["created_at"])
        if state is not None and state["observation_updated_at"]:
            updated_candidates.append(state["observation_updated_at"])
        active_members = [
            row for row in member_rows if row["status"] == "active" and row["cli_kind"] == "codex"
        ]
        inactive_members = [row for row in member_rows if row not in active_members]
        rooms.append(
            {
                "conversation_id": conversation_id,
                "title": conversation["title"],
                "created_at": conversation["created_at"],
                "updated_at": max(updated_candidates),
                "href": f"/rooms/{conversation_id}",
                "status": _room_status(active_turns, attention_turns),
                "latest_visible_room_seq": int(latest["seq"]) if latest else 0,
                "latest_visible_item": latest_item,
                "participant_count": len(member_rows),
                "active_participant_count": len(active_members),
                "participants": [
                    _participant_payload(row, handles[row["participant_id"]])
                    for row in (active_members + inactive_members)[:4]
                ],
                "active_turn_count": active_turns,
                "attention_turn_count": attention_turns,
            }
        )
    rooms.sort(key=lambda room: (room["updated_at"], room["conversation_id"]), reverse=True)
    return {
        "schema_version": ROOM_LIST_SCHEMA_VERSION,
        "projection_only": True,
        "proof_boundary": ROOM_PROJECTION_PROOF_BOUNDARY,
        "source_authority": [
            "chat.db:conversations",
            "chat.db:room_activities",
            "chat.db:room_observations",
            "chat.db:room_observation_attempts",
            "chat.db:participants",
            "chat.db:messages",
            "chat.db:proposals",
        ],
        "generated_at": _stamp(current),
        "rooms": rooms,
    }
