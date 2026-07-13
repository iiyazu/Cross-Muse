"""Connection-only operator action and projection-event primitives."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any, Literal

from xmuse_core.chat.room_execution_common import (
    RoomExecutionStoreError,
    decode_json,
    digest,
    json_value,
    new_id,
)


def operator_decision_fingerprint(
    *,
    candidate_id: str,
    decision: Literal["execute", "reject"],
    expected_candidate_digest: str,
    expected_candidate_revision: int,
    expected_policy_revision: int,
) -> str:
    return digest(
        {
            "candidate_id": candidate_id,
            "decision": decision,
            "expected_candidate_digest": expected_candidate_digest,
            "expected_candidate_revision": expected_candidate_revision,
            "expected_policy_revision": expected_policy_revision,
        }
    )


def reserve_execution_action_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    candidate_id: str | None,
    action_type: str,
    client_action_id: str,
    operator_identity: str,
    fingerprint: str,
    expected_candidate_digest: str | None,
    expected_candidate_revision: int | None,
    expected_policy_revision: int | None,
    expected_run_state: str | None,
    expected_run_revision: int | None,
    stamp: str,
) -> tuple[sqlite3.Row, bool]:
    prior = conn.execute(
        """select * from room_execution_operator_actions
           where operator_identity = ? and client_action_id = ?""",
        (operator_identity, client_action_id),
    ).fetchone()
    if prior is not None:
        if prior["request_fingerprint"] != fingerprint:
            raise RoomExecutionStoreError("room_execution_action_idempotency_conflict")
        return prior, False
    action_id = new_id("execution_action")
    conn.execute(
        """insert into room_execution_operator_actions
           (action_id, conversation_id, candidate_id, action_type, client_action_id,
            operator_identity, request_fingerprint, expected_candidate_digest,
            expected_candidate_revision, expected_policy_revision, expected_run_state,
            expected_run_revision, status, result_json, requested_at, updated_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'requested', '{}', ?, ?)""",
        (
            action_id,
            conversation_id,
            candidate_id,
            action_type,
            client_action_id,
            operator_identity,
            fingerprint,
            expected_candidate_digest,
            expected_candidate_revision,
            expected_policy_revision,
            expected_run_state,
            expected_run_revision,
            stamp,
            stamp,
        ),
    )
    row = conn.execute(
        "select * from room_execution_operator_actions where action_id = ?", (action_id,)
    ).fetchone()
    assert row is not None
    return row, True


def complete_execution_action_conn(
    conn: sqlite3.Connection,
    *,
    action_id: str,
    status: Literal["applied", "rejected", "failed"],
    result: Mapping[str, Any],
    reason_code: str | None,
    run_id: str | None,
    stamp: str,
) -> None:
    conn.execute(
        """update room_execution_operator_actions
           set status = ?, result_json = ?, reason_code = ?, run_id = ?, applied_at = ?,
               updated_at = ? where action_id = ?""",
        (status, json_value(dict(result)), reason_code, run_id, stamp, stamp, action_id),
    )


def replay_execution_action(row: sqlite3.Row) -> dict[str, Any]:
    result = decode_json(row["result_json"], {})
    if row["status"] == "applied":
        return result
    raise RoomExecutionStoreError(str(row["reason_code"] or "room_execution_action_rejected"))
