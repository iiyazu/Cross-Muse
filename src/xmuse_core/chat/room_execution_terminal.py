"""Caller-owned terminal execution activity helpers."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Sequence
from typing import Literal

from xmuse_core.chat.participant_store import INIT_GOD_ROLE
from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_common import json_value as _json
from xmuse_core.chat.room_execution_common import new_id as _id
from xmuse_core.chat.room_execution_events import record_execution_event_conn


def insert_terminal_activity_conn(
    conn: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    terminal_state: str,
    reason_code: str,
    changed_files: Sequence[str],
    gate_ids: Sequence[str],
    evidence_digest: str | None,
    stamp: str,
) -> str:
    candidate = conn.execute(
        "select * from room_execution_candidates where candidate_id = ?",
        (run["candidate_id"],),
    ).fetchone()
    source = (
        conn.execute(
            "select * from room_activities where activity_id = ?",
            (candidate["source_activity_id"],),
        ).fetchone()
        if candidate is not None
        else None
    )
    if candidate is None or source is None:
        raise RoomExecutionStoreError("room_execution_run_authority_corrupt")
    activity_id = _id("activity")
    sequence = int(
        conn.execute(
            "select coalesce(max(seq), 0) + 1 from room_activities where conversation_id = ?",
            (run["conversation_id"],),
        ).fetchone()[0]
    )
    correlation_id = (
        f"execution_correlation_{hashlib.sha256(str(run['run_id']).encode()).hexdigest()}"
    )
    payload = {
        "schema_version": "room_execution_activity/v1",
        "run_id": run["run_id"],
        "candidate_id": run["candidate_id"],
        "status": terminal_state,
        "reason_code": reason_code,
        "changed_files": list(changed_files),
        "gate_ids": list(gate_ids),
        "evidence_digest": evidence_digest,
        "source_correlation_id": candidate["source_correlation_id"],
        "proof_boundary": "execution_infrastructure_not_agent_speech",
    }
    conn.execute(
        """insert into room_activities
               (activity_id, conversation_id, seq, activity_type, actor_kind, actor_identity,
                actor_participant_id, causation_id, correlation_id, visibility, audience_json,
                payload_json, materialized_message_id, causal_depth,
                materialized_proposal_id, delivery_mode, created_at)
               values (?, ?, ?, ?, 'infrastructure', 'infrastructure:execution-harness', null,
                       ?, ?, 'room', ?, ?, null, ?, null, 'active', ?)""",
        (
            activity_id,
            run["conversation_id"],
            sequence,
            f"execution.{terminal_state}",
            source["activity_id"],
            correlation_id,
            _json({"type": "room", "conversation_id": run["conversation_id"]}),
            _json(payload),
            int(source["causal_depth"]) + 1,
            stamp,
        ),
    )
    active = conn.execute(
        """select participant_id from participants where conversation_id = ?
               and status = 'active' and cli_kind = 'codex'
               and role <> ? order by participant_id""",
        (run["conversation_id"], INIT_GOD_ROLE),
    ).fetchall()
    for participant in active:
        observation_id = _id("observation")
        conn.execute(
            """insert into room_observations
                   (observation_id, conversation_id, activity_id, participant_id, priority,
                    delivery_mode, status, attempt_count, created_at, updated_at)
                   values (?, ?, ?, ?, 0, 'active', 'pending', 0, ?, ?)""",
            (
                observation_id,
                run["conversation_id"],
                activity_id,
                participant["participant_id"],
                stamp,
                stamp,
            ),
        )
        conn.execute(
            """insert or ignore into room_participant_cursors
                   (conversation_id, participant_id, last_acknowledged_seq, updated_at)
                   values (?, ?, 0, ?)""",
            (run["conversation_id"], participant["participant_id"], stamp),
        )
    return activity_id


def finalize_run_conn(
    conn: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    terminal_state: Literal["succeeded", "failed", "blocked", "cancelled"],
    reason_code: str,
    changed_files: Sequence[str],
    gate_ids: Sequence[str],
    evidence_digest: str | None,
    stamp: str,
) -> sqlite3.Row:
    activity_id = insert_terminal_activity_conn(
        conn,
        run=run,
        terminal_state=terminal_state,
        reason_code=reason_code,
        changed_files=changed_files,
        gate_ids=gate_ids,
        evidence_digest=evidence_digest,
        stamp=stamp,
    )
    conn.execute(
        """update room_execution_runs set state = ?, revision = revision + 1,
               reason_code = ?, changed_files_json = ?, evidence_digest = ?, finished_at = ?,
               updated_at = ? where run_id = ?""",
        (
            terminal_state,
            reason_code,
            _json(list(changed_files)),
            evidence_digest,
            stamp,
            stamp,
            run["run_id"],
        ),
    )
    record_execution_event_conn(
        conn,
        conversation_id=run["conversation_id"],
        event_type="projection.changed",
        resource_ref=f"room:execution-run:{run['run_id']}",
        source_ref=f"room:activity:{activity_id}",
        payload={
            "change": f"execution.{terminal_state}",
            "run_id": run["run_id"],
            "candidate_id": run["candidate_id"],
            "activity_id": activity_id,
        },
        client_action_id=None,
        stamp=stamp,
    )
    updated = conn.execute(
        "select * from room_execution_runs where run_id = ?", (run["run_id"],)
    ).fetchone()
    assert updated is not None
    return updated
