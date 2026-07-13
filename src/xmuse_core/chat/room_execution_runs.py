"""Connection-only run, gate-plan, and controller-fencing primitives."""

from __future__ import annotations

import sqlite3
from typing import Any, Literal

from xmuse_core.chat.room_execution_common import (
    CONTROLLER_RUN_STATES,
    RUN_TRANSITIONS,
    TERMINAL_RUN_STATES,
    RoomExecutionStoreError,
    decode_json,
    json_value,
    new_id,
    require_digest,
    require_text,
)
from xmuse_core.chat.room_execution_profiles import (
    EXECUTION_GATE_PROFILE_SCHEMA,
    ExecutionGatePlan,
    RoomExecutionProfileError,
    execution_gate_plan_from_mapping,
    validate_execution_gate_plan,
)


def gate_plan_mapping_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": row["schema_version"],
        "profile_id": row["profile_id"],
        "revision": int(row["profile_revision"]),
        "profile_digest": row["profile_digest"],
        "gate_ids": decode_json(row["gate_ids_json"], []),
        "repository_manifest_digest": row["repository_manifest_digest"],
        "toolchain_capability_digest": row["toolchain_capability_digest"],
        "gate_plan_digest": row["gate_plan_digest"],
    }


def gate_plan_for_candidate_conn(
    conn: sqlite3.Connection,
    candidate: sqlite3.Row,
    *,
    authorization_id: str,
    run_id: str,
    required: bool,
) -> ExecutionGatePlan | None:
    row = conn.execute(
        """select * from room_execution_gate_plan_bindings
           where authorization_id = ? and run_id = ?""",
        (authorization_id, run_id),
    ).fetchone()
    if row is None:
        if required:
            raise RoomExecutionStoreError("room_execution_gate_plan_missing")
        return None
    try:
        return execution_gate_plan_from_mapping(
            gate_plan_mapping_from_row(row),
            changed_paths=tuple(decode_json(candidate["allowed_files_json"], [])),
        )
    except RoomExecutionProfileError as exc:
        raise RoomExecutionStoreError("room_execution_gate_plan_corrupt") from exc


def trusted_gate_plan(candidate: sqlite3.Row, plan: ExecutionGatePlan | None) -> ExecutionGatePlan:
    if plan is None:
        raise RoomExecutionStoreError("room_execution_gate_plan_required")
    try:
        return validate_execution_gate_plan(
            plan,
            changed_paths=tuple(decode_json(candidate["allowed_files_json"], [])),
        )
    except RoomExecutionProfileError as exc:
        raise RoomExecutionStoreError(exc.code) from exc


def required_gate_plan_for_run_conn(
    conn: sqlite3.Connection, run: sqlite3.Row
) -> ExecutionGatePlan:
    candidate = conn.execute(
        "select * from room_execution_candidates where candidate_id = ?", (run["candidate_id"],)
    ).fetchone()
    if candidate is None:
        raise RoomExecutionStoreError("room_execution_run_authority_corrupt")
    plan = gate_plan_for_candidate_conn(
        conn,
        candidate,
        authorization_id=str(run["authorization_id"]),
        run_id=str(run["run_id"]),
        required=True,
    )
    assert plan is not None
    if tuple(decode_json(run["gate_ids_json"], [])) != plan.gate_ids:
        raise RoomExecutionStoreError("room_execution_gate_plan_corrupt")
    return plan


def authorize_execution_conn(
    conn: sqlite3.Connection,
    *,
    candidate: sqlite3.Row,
    authorization_mode: Literal["manual", "consensus"],
    workspace_guard_digest: str,
    risk_evidence_digest: str | None,
    gate_plan: ExecutionGatePlan,
    stamp: str,
) -> tuple[sqlite3.Row, sqlite3.Row, bool]:
    prior = conn.execute(
        "select * from room_execution_authorizations where candidate_id = ?",
        (candidate["candidate_id"],),
    ).fetchone()
    if prior is not None:
        run = conn.execute(
            "select * from room_execution_runs where candidate_id = ?",
            (candidate["candidate_id"],),
        ).fetchone()
        if run is None:
            raise RoomExecutionStoreError("room_execution_authorization_corrupt")
        bound_plan = gate_plan_for_candidate_conn(
            conn,
            candidate,
            authorization_id=str(prior["authorization_id"]),
            run_id=str(run["run_id"]),
            required=True,
        )
        if bound_plan != gate_plan:
            raise RoomExecutionStoreError("room_execution_gate_plan_guard_changed")
        return prior, run, False
    authorization_id = new_id("execution_authorization")
    run_id = new_id("execution_run")
    conn.execute(
        """insert into room_execution_authorizations
           (authorization_id, candidate_id, conversation_id, authorization_mode,
            candidate_digest, candidate_revision, policy_revision, risk_policy_revision,
            peer_snapshot_digest, workspace_guard_digest, risk_evidence_digest,
            status, created_at, consumed_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'consumed', ?, ?)""",
        (
            authorization_id,
            candidate["candidate_id"],
            candidate["conversation_id"],
            authorization_mode,
            candidate["candidate_digest"],
            int(candidate["revision"]),
            int(candidate["policy_revision_snapshot"]),
            candidate["risk_policy_revision_snapshot"],
            candidate["peer_snapshot_digest"],
            workspace_guard_digest,
            risk_evidence_digest,
            stamp,
            stamp,
        ),
    )
    conn.execute(
        """insert into room_execution_runs
           (run_id, authorization_id, candidate_id, conversation_id, state, revision,
            control_seq, execution_generation, changed_files_json, gate_ids_json,
            requested_at, updated_at)
           values (?, ?, ?, ?, 'requested', 0, 0, 0, '[]', ?, ?, ?)""",
        (
            run_id,
            authorization_id,
            candidate["candidate_id"],
            candidate["conversation_id"],
            json_value(list(gate_plan.gate_ids)),
            stamp,
            stamp,
        ),
    )
    conn.execute(
        """insert into room_execution_gate_plan_bindings
           (binding_id, authorization_id, run_id, schema_version, profile_id,
            profile_revision, profile_digest, gate_ids_json,
            repository_manifest_digest, toolchain_capability_digest, gate_plan_digest,
            created_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            new_id("execution_gate_plan"),
            authorization_id,
            run_id,
            EXECUTION_GATE_PROFILE_SCHEMA,
            gate_plan.profile_id,
            gate_plan.revision,
            gate_plan.profile_digest,
            json_value(list(gate_plan.gate_ids)),
            gate_plan.repository_manifest_digest,
            gate_plan.toolchain_capability_digest,
            gate_plan.gate_plan_digest,
            stamp,
        ),
    )
    conn.execute(
        """update room_execution_candidates
           set state = 'authorized', revision = revision + 1, reason_code = null,
               authorized_at = ?, updated_at = ? where candidate_id = ? and state = 'open'""",
        (stamp, stamp, candidate["candidate_id"]),
    )
    authorization = conn.execute(
        "select * from room_execution_authorizations where authorization_id = ?",
        (authorization_id,),
    ).fetchone()
    run = conn.execute("select * from room_execution_runs where run_id = ?", (run_id,)).fetchone()
    assert authorization is not None and run is not None
    return authorization, run, True


def controller_identity(
    *,
    controller_id: str,
    controller_generation: str,
    controller_pid: int,
    controller_start_identity: str,
) -> tuple[str, str, int, str]:
    clean_id = require_text(controller_id, "room_execution_controller_id_required")
    clean_generation = require_text(
        controller_generation, "room_execution_controller_generation_required"
    )
    clean_start = require_text(
        controller_start_identity,
        "room_execution_controller_start_identity_required",
        maximum=256,
    )
    if (
        isinstance(controller_pid, bool)
        or not isinstance(controller_pid, int)
        or controller_pid <= 0
    ):
        raise RoomExecutionStoreError("room_execution_controller_pid_invalid")
    return clean_id, clean_generation, controller_pid, clean_start


def assert_controller_conn(
    row: sqlite3.Row,
    *,
    controller_id: str,
    controller_generation: str,
    controller_pid: int,
    controller_start_identity: str,
    execution_generation: int,
) -> None:
    if (
        row["controller_id"] != controller_id
        or row["controller_generation"] != controller_generation
        or int(row["controller_pid"] or 0) != controller_pid
        or row["controller_start_identity"] != controller_start_identity
        or int(row["execution_generation"]) != execution_generation
    ):
        raise RoomExecutionStoreError("room_execution_controller_fenced")


def bound_run_conn(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    expected_state: str,
    expected_revision: int,
    execution_generation: int,
    identity: tuple[str, str, int, str],
) -> sqlite3.Row:
    row = conn.execute("select * from room_execution_runs where run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise RoomExecutionStoreError("room_execution_run_not_found")
    if row["state"] != expected_state or int(row["revision"]) != expected_revision:
        raise RoomExecutionStoreError("room_execution_run_guard_mismatch")
    assert_controller_conn(
        row,
        controller_id=identity[0],
        controller_generation=identity[1],
        controller_pid=identity[2],
        controller_start_identity=identity[3],
        execution_generation=execution_generation,
    )
    return row


def claim_requested_run_conn(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    identity: tuple[str, str, int, str],
    stamp: str,
) -> sqlite3.Row:
    run = conn.execute("select * from room_execution_runs where run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise RoomExecutionStoreError("room_execution_run_not_found")
    if run["state"] not in {"requested", "cancel_requested"} or run["controller_id"] is not None:
        raise RoomExecutionStoreError("room_execution_run_claim_conflict")
    target = "preparing" if run["state"] == "requested" else "cancel_requested"
    changed = conn.execute(
        """update room_execution_runs set state = ?, revision = revision + 1,
           execution_generation = execution_generation + 1, controller_id = ?,
           controller_generation = ?, controller_pid = ?, controller_start_identity = ?,
           started_at = coalesce(started_at, ?), updated_at = ?
           where run_id = ? and revision = ? and state = ? and controller_id is null""",
        (
            target,
            identity[0],
            identity[1],
            identity[2],
            identity[3],
            stamp,
            stamp,
            run_id,
            int(run["revision"]),
            run["state"],
        ),
    ).rowcount
    if changed != 1:
        raise RoomExecutionStoreError("room_execution_run_claim_conflict")
    updated = conn.execute(
        "select * from room_execution_runs where run_id = ?", (run_id,)
    ).fetchone()
    assert updated is not None
    return updated


def reclaim_run_controller_conn(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    expected_state: str,
    expected_revision: int,
    expected_execution_generation: int,
    old_identity: tuple[str, str, int, str],
    new_identity: tuple[str, str, int, str],
    stamp: str,
) -> sqlite3.Row:
    if expected_state not in CONTROLLER_RUN_STATES:
        raise RoomExecutionStoreError("room_execution_takeover_state_invalid")
    run = conn.execute("select * from room_execution_runs where run_id = ?", (run_id,)).fetchone()
    if run is None:
        raise RoomExecutionStoreError("room_execution_run_not_found")
    if run["state"] != expected_state or int(run["revision"]) != expected_revision:
        raise RoomExecutionStoreError("room_execution_takeover_guard_mismatch")
    assert_controller_conn(
        run,
        controller_id=old_identity[0],
        controller_generation=old_identity[1],
        controller_pid=old_identity[2],
        controller_start_identity=old_identity[3],
        execution_generation=expected_execution_generation,
    )
    conn.execute(
        """update room_execution_runs set revision = revision + 1,
           execution_generation = execution_generation + 1, controller_id = ?,
           controller_generation = ?, controller_pid = ?, controller_start_identity = ?,
           updated_at = ? where run_id = ?""",
        (*new_identity, stamp, run_id),
    )
    updated = conn.execute(
        "select * from room_execution_runs where run_id = ?", (run_id,)
    ).fetchone()
    assert updated is not None
    return updated


def advance_run_conn(
    conn: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    target_state: str,
    reason_code: str | None,
    stamp: str,
) -> sqlite3.Row:
    expected_state = str(run["state"])
    if (
        target_state not in RUN_TRANSITIONS.get(expected_state, frozenset())
        or target_state in TERMINAL_RUN_STATES
        or target_state in {"promoting", "cancel_requested"}
    ):
        raise RoomExecutionStoreError("room_execution_run_transition_invalid")
    conn.execute(
        """update room_execution_runs set state = ?, revision = revision + 1,
           reason_code = ?, updated_at = ? where run_id = ?""",
        (target_state, reason_code, stamp, run["run_id"]),
    )
    updated = conn.execute(
        "select * from room_execution_runs where run_id = ?", (run["run_id"],)
    ).fetchone()
    assert updated is not None
    return updated


def validate_gate_evidence(
    *,
    gate_id: str,
    status: Literal["running", "passed", "failed", "cancelled"],
    evidence_digest: str,
    started_at: str,
    finished_at: str | None,
) -> tuple[str, str, str, str | None]:
    clean_gate = require_text(gate_id, "room_execution_gate_id_invalid", maximum=128)
    clean_digest = require_digest(evidence_digest, "room_execution_gate_evidence_digest_invalid")
    clean_started = require_text(started_at, "room_execution_gate_started_at_invalid", maximum=64)
    clean_finished = (
        require_text(finished_at, "room_execution_gate_finished_at_invalid", maximum=64)
        if finished_at is not None
        else None
    )
    if status not in {"running", "passed", "failed", "cancelled"}:
        raise RoomExecutionStoreError("room_execution_gate_status_invalid")
    if (status == "running") != (clean_finished is None):
        raise RoomExecutionStoreError("room_execution_gate_time_invalid")
    return clean_gate, clean_digest, clean_started, clean_finished


def record_gate_evidence_conn(
    conn: sqlite3.Connection,
    *,
    run: sqlite3.Row,
    execution_generation: int,
    gate_id: str,
    status: Literal["running", "passed", "failed", "cancelled"],
    evidence_digest: str,
    started_at: str,
    finished_at: str | None,
    reason_code: str | None,
    stamp: str,
) -> tuple[sqlite3.Row, bool]:
    gate_id, evidence_digest, started_at, finished_at = validate_gate_evidence(
        gate_id=gate_id,
        status=status,
        evidence_digest=evidence_digest,
        started_at=started_at,
        finished_at=finished_at,
    )
    gate_plan = required_gate_plan_for_run_conn(conn, run)
    if gate_id not in gate_plan.gate_ids:
        raise RoomExecutionStoreError("room_execution_gate_id_unplanned")
    prior = conn.execute(
        """select * from room_execution_gate_evidence
           where run_id = ? and execution_generation = ? and gate_id = ?""",
        (run["run_id"], execution_generation, gate_id),
    ).fetchone()
    if prior is not None:
        if (
            prior["status"] == status
            and prior["evidence_digest"] == evidence_digest
            and prior["started_at"] == started_at
            and prior["finished_at"] == finished_at
            and prior["reason_code"] == reason_code
        ):
            return run, False
        if prior["status"] != "running" or status == "running":
            raise RoomExecutionStoreError("room_execution_gate_evidence_conflict")
        conn.execute(
            """update room_execution_gate_evidence set status = ?, evidence_digest = ?,
               reason_code = ?, finished_at = ?, updated_at = ? where evidence_id = ?""",
            (status, evidence_digest, reason_code, finished_at, stamp, prior["evidence_id"]),
        )
    else:
        conn.execute(
            """insert into room_execution_gate_evidence
               (evidence_id, run_id, execution_generation, gate_id, status,
                evidence_digest, reason_code, started_at, finished_at, created_at, updated_at)
               values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                new_id("execution_gate"),
                run["run_id"],
                execution_generation,
                gate_id,
                status,
                evidence_digest,
                reason_code,
                started_at,
                finished_at,
                stamp,
                stamp,
            ),
        )
    conn.execute(
        "update room_execution_runs set revision = revision + 1, updated_at = ? where run_id = ?",
        (stamp, run["run_id"]),
    )
    updated = conn.execute(
        "select * from room_execution_runs where run_id = ?", (run["run_id"],)
    ).fetchone()
    assert updated is not None
    return updated, True
