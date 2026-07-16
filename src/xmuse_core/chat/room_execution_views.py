"""Private ledger views for exact-patch candidates and runs.

These helpers only assemble already-durable execution facts.  They intentionally
own no transaction, operator action, controller transition, or promotion policy.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from xmuse_core.chat.room_execution_common import RoomExecutionStoreError, decode_json
from xmuse_core.chat.room_execution_runs import gate_plan_for_candidate_conn


def _assessment_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "assessment_id": row["assessment_id"],
        "assessor_participant_id": row["assessor_participant_id"],
        "assessment": row["assessment"],
        "rationale": row["rationale"],
        "candidate_digest": row["candidate_digest"],
        "review_material_digest": row["review_material_digest"],
        "source_attempt_id": row["source_attempt_id"],
        "source_batch_id": row["source_batch_id"],
        "source_activity_id": row["source_activity_id"],
        "created_at": row["created_at"],
    }


def candidate_view_conn(
    conn: sqlite3.Connection, row: sqlite3.Row, *, include_patch: bool
) -> dict[str, Any]:
    members = [
        {
            "participant_id": member["participant_id"],
            "identity_fingerprint": member["identity_fingerprint"],
            "status_snapshot": member["status_snapshot"],
            "ordinal": int(member["ordinal"]),
            "full_material_available": bool(member["full_material_available"]),
        }
        for member in conn.execute(
            "select * from room_execution_candidate_members where candidate_id = ? "
            "order by ordinal",
            (row["candidate_id"],),
        )
    ]
    assessments = [
        _assessment_view(item)
        for item in conn.execute(
            "select * from room_execution_assessments where candidate_id = ? "
            "order by created_at, assessment_id",
            (row["candidate_id"],),
        )
    ]
    authorization = conn.execute(
        "select * from room_execution_authorizations where candidate_id = ?",
        (row["candidate_id"],),
    ).fetchone()
    run = conn.execute(
        "select run_id, state, revision from room_execution_runs where candidate_id = ?",
        (row["candidate_id"],),
    ).fetchone()
    gate_plan = (
        gate_plan_for_candidate_conn(
            conn,
            row,
            authorization_id=str(authorization["authorization_id"]),
            run_id=str(run["run_id"]),
            required=False,
        )
        if authorization is not None and run is not None
        else None
    )
    result: dict[str, Any] = {
        "schema_version": "room_execution_candidate/v1",
        "candidate_id": row["candidate_id"],
        "proposal_id": row["proposal_id"],
        "conversation_id": row["conversation_id"],
        "author_participant_id": row["author_participant_id"],
        "author_identity_fingerprint": row["author_identity_fingerprint"],
        "source": {
            "observation_id": row["source_observation_id"],
            "batch_id": row["source_batch_id"],
            "attempt_id": row["source_attempt_id"],
            "activity_id": row["source_activity_id"],
            "correlation_id": row["source_correlation_id"],
        },
        "base_head": row["base_head"],
        "summary": row["summary"],
        "allowed_files": decode_json(row["allowed_files_json"], []),
        "files": decode_json(row["files_json"], []),
        "candidate_digest": row["candidate_digest"],
        "patch_sha256": row["patch_sha256"],
        "review_material_digest": row["review_material_digest"],
        "patch_bytes": int(row["patch_bytes"]),
        "file_count": int(row["file_count"]),
        "modify_only": bool(row["modify_only"]),
        "context_fit_eligible": bool(row["context_fit_eligible"]),
        "direct_human_root": bool(row["direct_human_root"]),
        "peer_snapshot_digest": row["peer_snapshot_digest"],
        "policy_snapshot": {
            "mode": row["policy_mode_snapshot"],
            "revision": int(row["policy_revision_snapshot"]),
            "risk_policy_revision": row["risk_policy_revision_snapshot"],
        },
        "state": row["state"],
        "consensus_state": row["consensus_state"],
        "reason_code": row["reason_code"],
        "revision": int(row["revision"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "authorized_at": row["authorized_at"],
        "rejected_at": row["rejected_at"],
        "members": members,
        "assessments": assessments,
        "authorization": (
            {
                "authorization_id": authorization["authorization_id"],
                "mode": authorization["authorization_mode"],
                "status": authorization["status"],
                "created_at": authorization["created_at"],
                "gate_profile": gate_plan.safe_reference() if gate_plan is not None else None,
            }
            if authorization is not None
            else None
        ),
        "run": (
            {
                **dict(run),
                "gate_profile": gate_plan.safe_reference() if gate_plan is not None else None,
            }
            if run is not None
            else None
        ),
    }
    if include_patch:
        result["unified_diff"] = row["unified_diff"]
    return result


def _gate_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "evidence_id": row["evidence_id"],
        "gate_id": row["gate_id"],
        "status": row["status"],
        "evidence_digest": row["evidence_digest"],
        "reason_code": row["reason_code"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def run_view_conn(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    gates = [
        _gate_view(item)
        for item in conn.execute(
            "select * from room_execution_gate_evidence where run_id = ? "
            "order by execution_generation, created_at, gate_id",
            (row["run_id"],),
        )
    ]
    journal = conn.execute(
        "select * from room_execution_promotion_journal where run_id = ?", (row["run_id"],)
    ).fetchone()
    candidate = conn.execute(
        "select * from room_execution_candidates where candidate_id = ?", (row["candidate_id"],)
    ).fetchone()
    if candidate is None:
        raise RoomExecutionStoreError("room_execution_run_authority_corrupt")
    gate_plan = gate_plan_for_candidate_conn(
        conn,
        candidate,
        authorization_id=str(row["authorization_id"]),
        run_id=str(row["run_id"]),
        required=False,
    )
    return {
        "schema_version": "room_execution_run/v1",
        "run_id": row["run_id"],
        "authorization_id": row["authorization_id"],
        "candidate_id": row["candidate_id"],
        "conversation_id": row["conversation_id"],
        "state": row["state"],
        "revision": int(row["revision"]),
        "control_seq": int(row["control_seq"]),
        "attempt_number": int(row["execution_generation"]),
        "reason_code": row["reason_code"],
        "changed_files": decode_json(row["changed_files_json"], []),
        "gate_ids": decode_json(row["gate_ids_json"], []),
        "gate_profile": gate_plan.safe_reference() if gate_plan is not None else None,
        "evidence_digest": row["evidence_digest"],
        "requested_at": row["requested_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "updated_at": row["updated_at"],
        "gates": gates,
        "promotion_journal": (
            {
                "journal_id": journal["journal_id"],
                "target_head": journal["target_head"],
                "pre_manifest_digest": journal["pre_manifest_digest"],
                "post_manifest_digest": journal["post_manifest_digest"],
                "file_entries": decode_json(journal["file_entries_json"], []),
                "status": journal["status"],
                "observed_manifest_digest": journal["observed_manifest_digest"],
                "prepared_at": journal["prepared_at"],
                "applied_at": journal["applied_at"],
                "updated_at": journal["updated_at"],
            }
            if journal is not None
            else None
        ),
    }
