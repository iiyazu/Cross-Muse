from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def build_peer_progress_events(
    *,
    db_path: Path,
    conversation_id: str,
    inbox_items: list[Any],
) -> list[dict[str, Any]]:
    traces_by_inbox = {
        str(trace.get("inbox_item_id")): trace
        for trace in _read_peer_latency_traces(db_path, conversation_id, limit=200)
        if str(trace.get("inbox_item_id") or "").strip()
    }
    active_streams_by_inbox = {
        stream["source_inbox_item_id"]: stream
        for stream in _read_active_peer_streams(db_path, conversation_id)
        if stream.get("source_inbox_item_id")
    }
    events: list[dict[str, Any]] = []
    seen_inbox_ids: set[str] = set()
    for item in inbox_items:
        trace = traces_by_inbox.get(item.id)
        stream = active_streams_by_inbox.get(item.id)
        if trace is not None:
            event = _event_from_trace(item=item, trace=trace)
        else:
            event = _event_from_inbox(item=item, stream=stream)
        events.append(event)
        seen_inbox_ids.add(item.id)

    for inbox_id, trace in traces_by_inbox.items():
        if inbox_id in seen_inbox_ids:
            continue
        events.append(_event_from_trace(item=None, trace=trace))
    events.sort(
        key=lambda event: (
            str(event.get("updated_at") or event.get("created_at") or ""),
            str(event.get("inbox_item_id") or event.get("source_id") or ""),
        )
    )
    return events


def peer_progress_counts(events: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for event in events:
        status = _string_value(event.get("status")) or "unknown"
        counts[status] = counts.get(status, 0) + 1
    counts["total"] = len(events)
    return counts


def _event_from_inbox(
    *,
    item: Any,
    stream: dict[str, Any] | None,
) -> dict[str, Any]:
    status_by_inbox = {
        "unread": "waiting",
        "claimed": "running",
        "read": "done",
        "failed": "failed",
    }
    status = status_by_inbox.get(str(item.status), str(item.status))
    if stream is not None and stream.get("status") == "active":
        status = "running"
    event = {
        "id": f"peer_progress_{item.id}",
        "conversation_id": item.conversation_id,
        "source_authority": "chat_inbox_items",
        "source_id": item.id,
        "event_type": "peer_turn_progress",
        "status": status,
        "inbox_item_id": item.id,
        "inbox_status": item.status,
        "target_participant_id": item.target_participant_id,
        "target_role": item.target_role,
        "target_address": item.target_address,
        "sender_participant_id": item.sender_participant_id,
        "sender_address": item.sender_address,
        "source_message_id": item.source_message_id,
        "responded_message_id": item.responded_message_id,
        "failure_reason": item.failure_reason,
        "claim_owner": item.claim_owner,
        "claimed_at": item.claimed_at,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
        "api_href": f"/api/chat/conversations/{item.conversation_id}/messages",
    }
    if stream is not None:
        event.update(
            {
                "stream_id": stream.get("id"),
                "stream_status": stream.get("status"),
                "first_delta_at": stream.get("first_delta_at"),
            }
        )
    event["summary"] = _summary(event)
    return event


def _event_from_trace(
    *,
    item: Any | None,
    trace: dict[str, Any],
) -> dict[str, Any]:
    delivery_mode = _string_value(trace.get("delivery_mode")) or "unknown"
    degraded_reason = _string_value(trace.get("degraded_reason"))
    if delivery_mode == "failed":
        status = "failed"
    elif degraded_reason:
        status = "degraded"
    else:
        status = "done"
    stage_timings = trace.get("stage_timings")
    if not isinstance(stage_timings, dict):
        stage_timings = {}
    conversation_id = (
        item.conversation_id
        if item is not None
        else _string_value(trace.get("conversation_id")) or ""
    )
    inbox_item_id = item.id if item is not None else _string_value(trace.get("inbox_item_id"))
    event = {
        "id": str(trace.get("id") or f"peer_progress_{inbox_item_id}"),
        "conversation_id": conversation_id,
        "source_authority": "peer_turn_latency_traces",
        "source_id": str(trace.get("id") or ""),
        "event_type": "peer_turn_progress",
        "status": status,
        "inbox_item_id": inbox_item_id,
        "inbox_status": item.status if item is not None else None,
        "target_participant_id": (
            item.target_participant_id
            if item is not None
            else _string_value(trace.get("participant_id"))
        ),
        "target_role": (
            item.target_role if item is not None else _string_value(trace.get("target_role"))
        ),
        "target_address": item.target_address if item is not None else None,
        "sender_participant_id": item.sender_participant_id if item is not None else None,
        "sender_address": item.sender_address if item is not None else None,
        "source_message_id": item.source_message_id if item is not None else None,
        "responded_message_id": item.responded_message_id if item is not None else None,
        "delivery_mode": delivery_mode,
        "degraded_reason": degraded_reason,
        "latency_ms": trace.get("total_latency_ms"),
        "stage_names": sorted(str(key) for key in stage_timings),
        "claimed_at": trace.get("inbox_claimed_at"),
        "created_at": item.created_at if item is not None else None,
        "updated_at": item.updated_at if item is not None else None,
        "api_href": f"/api/chat/conversations/{conversation_id}/messages",
    }
    event["summary"] = _summary(event)
    return event


def _summary(event: dict[str, Any]) -> str:
    role = _string_value(event.get("target_role")) or "peer"
    status = _string_value(event.get("status")) or "unknown"
    delivery_mode = _string_value(event.get("delivery_mode"))
    degraded_reason = _string_value(event.get("degraded_reason") or event.get("failure_reason"))
    parts = [role, status]
    if delivery_mode:
        parts.append(delivery_mode)
    if degraded_reason:
        parts.append(degraded_reason)
    return " ".join(parts)


def _read_peer_latency_traces(
    db_path: Path,
    conversation_id: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if not _table_exists_readonly(db_path, "peer_turn_latency_traces"):
        return []
    with _connect_readonly(db_path) as conn:
        rows = conn.execute(
            """
            select * from peer_turn_latency_traces
            where conversation_id = ?
            order by writeback_at desc
            limit ?
            """,
            (conversation_id, limit),
        ).fetchall()
    traces = []
    for row in rows:
        trace = dict(row)
        raw_stage_timings = trace.pop("stage_timings_json", None)
        try:
            parsed = json.loads(raw_stage_timings) if isinstance(raw_stage_timings, str) else {}
        except json.JSONDecodeError:
            parsed = {}
        trace["stage_timings"] = parsed if isinstance(parsed, dict) else {}
        traces.append(trace)
    return traces


def _read_active_peer_streams(db_path: Path, conversation_id: str) -> list[dict[str, Any]]:
    if not _table_exists_readonly(db_path, "chat_streams"):
        return []
    with _connect_readonly(db_path) as conn:
        rows = conn.execute(
            """
            select * from chat_streams
            where conversation_id = ? and status = 'active'
            order by rowid asc
            """,
            (conversation_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def _table_exists_readonly(db_path: Path, table_name: str) -> bool:
    with _connect_readonly(db_path) as conn:
        row = conn.execute(
            "select 1 from sqlite_master where type = 'table' and name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _string_value(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
