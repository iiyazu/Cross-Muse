from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry

_MEMORYOS_REQUIRED_ENV = ("XMUSE_LIVE_MEMORYOS_LITE", "XMUSE_MEMORYOS_LITE_URL")
_MEMORYOS_REQUIRED_PAYLOAD = (
    "repo_id",
    "workspace_id",
    "god_id",
    "conversation_id",
    "thread_id",
    "blueprint_id",
    "feature_id",
    "lane_id",
    "content",
    "query",
)


def build_release_evidence_candidate_report(
    xmuse_root: str | Path,
    *,
    conversation_id: str | None = None,
    env: Mapping[str, str] | None = None,
    memoryos_payload: Mapping[str, Any] | None = None,
    trace_limit: int = 20,
) -> dict[str, Any]:
    root = Path(xmuse_root)
    chat_db_path = root / "chat.db"
    sessions = _session_index(root / "god_sessions.json")
    memoryos_inputs = dict(memoryos_payload or {})
    if conversation_id and not _text(memoryos_inputs.get("conversation_id")):
        memoryos_inputs["conversation_id"] = conversation_id
    return {
        "schema_version": "xmuse.release_evidence_candidates.v1",
        "generated_at": _utc_now(),
        "conversation_id": conversation_id,
        "natural_deliberation": _natural_candidates(
            chat_db_path,
            sessions=sessions,
            conversation_id=conversation_id,
        ),
        "real_provider_runtime": _provider_candidates(
            chat_db_path,
            sessions=sessions,
            conversation_id=conversation_id,
            trace_limit=trace_limit,
        ),
        "live_memoryos": _memoryos_candidates(
            env=dict(env or {}),
            payload=memoryos_inputs,
        ),
    }


def _natural_candidates(
    chat_db_path: Path,
    *,
    sessions: Mapping[tuple[str, str], GodSessionRecord],
    conversation_id: str | None,
) -> dict[str, Any]:
    conversations = []
    if not chat_db_path.exists():
        return {
            "conversation_count": 0,
            "conversations": [],
            "blockers": ["chat_db_missing"],
        }
    with _connect(chat_db_path) as conn:
        for conversation in _conversation_rows(conn, conversation_id=conversation_id):
            message_rows = conn.execute(
                """
                select id, author, role, envelope_type, envelope_json
                from messages
                where conversation_id = ?
                order by created_at asc
                """,
                (conversation["id"],),
            ).fetchall()
            messages = [
                message
                for message in (_speech_message(row) for row in message_rows)
                if message is not None
            ]
            god_ids = _ordered_unique(
                _text(message.get("god_id")) for message in messages
            )
            participant_ids = _ordered_unique(
                _text(message.get("participant_id")) for message in messages
            )
            missing_sessions = [
                participant_id
                for participant_id in participant_ids
                if not _provider_session_id(
                    sessions.get((conversation["id"], participant_id))
                )
            ]
            blockers = []
            if not messages:
                blockers.append("natural_god_speech_act_messages_missing")
            if messages and len(god_ids) < 2:
                blockers.append("natural_deliberation_requires_two_gods")
            if missing_sessions:
                blockers.append("provider_session_metadata_missing")
            conversations.append(
                {
                    "conversation_id": conversation["id"],
                    "title": conversation["title"],
                    "god_speech_act_count": len(messages),
                    "distinct_god_count": len(god_ids),
                    "god_ids": god_ids,
                    "participant_ids": participant_ids,
                    "missing_provider_session_participant_ids": missing_sessions,
                    "export_ready": not blockers,
                    "blockers": blockers,
                }
            )
    return {
        "conversation_count": len(conversations),
        "conversations": conversations,
        "export_ready": any(item["export_ready"] for item in conversations),
    }


def _provider_candidates(
    chat_db_path: Path,
    *,
    sessions: Mapping[tuple[str, str], GodSessionRecord],
    conversation_id: str | None,
    trace_limit: int,
) -> dict[str, Any]:
    if not chat_db_path.exists():
        return _provider_gap("chat_db_missing", trace_table_present=False)
    with _connect(chat_db_path) as conn:
        if not _table_exists(conn, "peer_turn_latency_traces"):
            return _provider_gap(
                "peer_turn_latency_traces_table_missing",
                trace_table_present=False,
            )
        query = (
            "select * from peer_turn_latency_traces "
            "where conversation_id = ? "
            "order by writeback_at asc limit ?"
            if conversation_id
            else "select * from peer_turn_latency_traces order by writeback_at asc limit ?"
        )
        params: tuple[Any, ...] = (
            (conversation_id, trace_limit) if conversation_id else (trace_limit,)
        )
        rows = conn.execute(query, params).fetchall()
    traces = [_trace_candidate(dict(row), sessions=sessions) for row in rows]
    eligible = [
        trace
        for trace in traces
        if trace["delivery_mode"] == "mcp_writeback"
        and trace["degraded_reason"] is None
        and trace["provider_session_id"]
    ]
    suggested = _suggest_fresh_resume(eligible)
    blockers = []
    if len(eligible) < 2:
        blockers.append("provider_runtime_requires_two_mcp_writeback_traces")
    if any(trace["provider_session_id_missing"] for trace in traces):
        blockers.append("provider_session_metadata_missing")
    export_ready = suggested is not None and not blockers
    return {
        "trace_table_present": True,
        "trace_count": len(traces),
        "traces": traces,
        "export_ready": export_ready,
        "suggested_fresh_inbox_item_id": suggested[0] if suggested else None,
        "suggested_resume_inbox_item_id": suggested[1] if suggested else None,
        "blockers": [] if export_ready else blockers,
    }


def _memoryos_candidates(
    *,
    env: Mapping[str, str],
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    missing_env = [
        key
        for key in _MEMORYOS_REQUIRED_ENV
        if not _text(env.get(key))
        or (key == "XMUSE_LIVE_MEMORYOS_LITE" and env.get(key) != "1")
    ]
    missing_payload = [
        key for key in _MEMORYOS_REQUIRED_PAYLOAD if not _text(payload.get(key))
    ]
    return {
        "configured": not missing_env,
        "export_ready": not missing_env and not missing_payload,
        "env_keys_present": sorted(key for key in _MEMORYOS_REQUIRED_ENV if key in env),
        "missing_env_keys": missing_env,
        "missing_payload_keys": missing_payload,
        "blockers": [
            *(
                ["memoryos_lite_live_environment_missing"]
                if missing_env
                else []
            ),
            *(
                ["memoryos_task_payload_incomplete"]
                if missing_payload
                else []
            ),
        ],
    }


def _session_index(registry_path: Path) -> dict[tuple[str, str], GodSessionRecord]:
    if not registry_path.exists():
        return {}
    sessions: dict[tuple[str, str], GodSessionRecord] = {}
    for session in GodSessionRegistry(registry_path).list():
        if session.conversation_id and session.participant_id:
            sessions[(session.conversation_id, session.participant_id)] = session
    return sessions


def _conversation_rows(
    conn: sqlite3.Connection,
    *,
    conversation_id: str | None,
) -> list[sqlite3.Row]:
    if conversation_id:
        return conn.execute(
            "select id, title, created_at from conversations where id = ?",
            (conversation_id,),
        ).fetchall()
    return conn.execute(
        "select id, title, created_at from conversations order by created_at desc",
    ).fetchall()


def _speech_message(row: sqlite3.Row) -> dict[str, str] | None:
    if row["role"] != "assistant":
        return None
    envelope_type = _text(row["envelope_type"])
    envelope = _json_object(row["envelope_json"])
    if envelope_type != "god_speech_act" and envelope.get("type") != "god_speech_act":
        return None
    payload = envelope.get("message") or envelope.get("god_speech_act")
    if not isinstance(payload, dict):
        return None
    return {
        "message_id": _text(payload.get("message_id")) or row["id"],
        "participant_id": row["author"],
        "god_id": _text(payload.get("sender_god")) or row["author"],
    }


def _trace_candidate(
    row: dict[str, Any],
    *,
    sessions: Mapping[tuple[str, str], GodSessionRecord],
) -> dict[str, Any]:
    conversation_id = str(row.get("conversation_id") or "")
    participant_id = _text(row.get("participant_id"))
    session = sessions.get((conversation_id, participant_id or ""))
    provider_session_id = _provider_session_id(session)
    return {
        "conversation_id": conversation_id,
        "inbox_item_id": str(row.get("inbox_item_id") or ""),
        "participant_id": participant_id,
        "target_role": _text(row.get("target_role")),
        "delivery_mode": str(row.get("delivery_mode") or ""),
        "degraded_reason": row.get("degraded_reason"),
        "provider_session_id": provider_session_id,
        "provider_session_id_missing": not bool(provider_session_id),
        "writeback_at": row.get("writeback_at"),
    }


def _suggest_fresh_resume(traces: list[dict[str, Any]]) -> tuple[str, str] | None:
    by_session: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for trace in traces:
        key = (trace["conversation_id"], trace["provider_session_id"])
        by_session.setdefault(key, []).append(trace)
    for grouped in by_session.values():
        if len(grouped) < 2:
            continue
        grouped.sort(key=lambda item: item.get("writeback_at") or 0)
        return (
            str(grouped[0]["inbox_item_id"]),
            str(grouped[-1]["inbox_item_id"]),
        )
    return None


def _provider_gap(reason: str, *, trace_table_present: bool) -> dict[str, Any]:
    return {
        "trace_table_present": trace_table_present,
        "trace_count": 0,
        "traces": [],
        "export_ready": False,
        "suggested_fresh_inbox_item_id": None,
        "suggested_resume_inbox_item_id": None,
        "blockers": [reason],
    }


def _provider_session_id(session: GodSessionRecord | None) -> str:
    if session is None or not session.provider_session_id:
        return ""
    return session.provider_session_id


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "select 1 from sqlite_master where type = 'table' and name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip():
        return {}
    try:
        loaded = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _ordered_unique(values: Any) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = ["build_release_evidence_candidate_report"]
