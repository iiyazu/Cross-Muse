"""Connection-only candidate, policy, consensus, and review-material primitives."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from xmuse_core.chat.participant_store import INIT_GOD_ROLE
from xmuse_core.chat.room_execution_common import (
    RoomExecutionStoreError,
    decode_json,
    digest,
    json_value,
    new_id,
    require_digest,
)
from xmuse_core.chat.room_execution_contracts import (
    EXECUTION_RISK_POLICY_REVISION,
    ExecutionPatch,
    ExecutionPatchFile,
    ExecutionWorkspaceGuard,
    ProposalAssessment,
    canonical_execution_path,
)


def _participant_fingerprint(row: sqlite3.Row) -> str:
    return digest(
        {
            "participant_id": row["participant_id"],
            "role": row["role"],
            "display_name": row["display_name"],
            "cli_kind": row["cli_kind"],
            "model": row["model"],
            "role_template_id": row["role_template_id"],
            "persona_snapshot_sha256": row["persona_snapshot_sha256"],
        }
    )


def _ensure_policy_conn(
    conn: sqlite3.Connection, conversation_id: str, *, stamp: str
) -> sqlite3.Row:
    conn.execute(
        """insert into room_execution_policies
           (conversation_id, mode, revision, risk_policy_revision, created_at, updated_at)
           values (?, 'manual', 0, ?, ?, ?) on conflict(conversation_id) do nothing""",
        (conversation_id, EXECUTION_RISK_POLICY_REVISION, stamp, stamp),
    )
    row = conn.execute(
        "select * from room_execution_policies where conversation_id = ?", (conversation_id,)
    ).fetchone()
    if row is None:
        raise RoomExecutionStoreError("room_execution_policy_missing")
    return row


def _safe_patch_reference(candidate_id: str, patch: ExecutionPatch) -> dict[str, Any]:
    return {"candidate_id": candidate_id, **patch.safe_reference()}


def _review_material(
    *, candidate_id: str, proposal_id: str, source_activity_id: str, patch: ExecutionPatch
) -> dict[str, Any]:
    return {
        "schema_version": "room_execution_review_material/v1",
        "candidate_id": candidate_id,
        "proposal_id": proposal_id,
        "proposal_activity_id": source_activity_id,
        **patch.safe_reference(),
        "unified_diff": patch.unified_diff,
    }


def prepare_execution_candidate_conn(
    conn: sqlite3.Connection,
    *,
    conversation_id: str,
    author_participant_id: str,
    source_observation_id: str,
    source_batch_id: str | None,
    source_attempt_id: str,
    source_activity_id: str,
    source_correlation_id: str,
    proposal_id: str,
    patch: ExecutionPatch,
    direct_human_root: bool,
    stamp: str,
) -> dict[str, Any]:
    """Freeze policy and active peer identities before activity insertion."""

    policy = _ensure_policy_conn(conn, conversation_id, stamp=stamp)
    author = conn.execute(
        "select * from participants where conversation_id = ? and participant_id = ?",
        (conversation_id, author_participant_id),
    ).fetchone()
    if author is None or author["status"] != "active" or author["cli_kind"] != "codex":
        raise RoomExecutionStoreError("room_execution_candidate_author_invalid")
    peers = conn.execute(
        """select * from participants where conversation_id = ? and status = 'active'
           and cli_kind = 'codex'
           and role <> ? and participant_id <> ? order by participant_id""",
        (conversation_id, INIT_GOD_ROLE, author_participant_id),
    ).fetchall()
    members = [
        {
            "participant_id": str(row["participant_id"]),
            "identity_fingerprint": _participant_fingerprint(row),
            "status_snapshot": str(row["status"]),
            "ordinal": ordinal,
        }
        for ordinal, row in enumerate(peers)
    ]
    snapshot_digest = digest(members)
    candidate_id = new_id("execution_candidate")
    material = _review_material(
        candidate_id=candidate_id,
        proposal_id=proposal_id,
        source_activity_id=source_activity_id,
        patch=patch,
    )
    material_digest = digest(material)
    context_fit = len(json_value(material).encode("utf-8")) <= 64 * 1024
    consensus_state = "collecting"
    reason_code: str | None = None
    if policy["mode"] != "consensus":
        consensus_state, reason_code = "invalidated", "manual_policy"
    elif not members:
        consensus_state, reason_code = "invalidated", "consensus_peer_required"
    elif not direct_human_root:
        consensus_state, reason_code = "invalidated", "consensus_human_root_required"
    elif not context_fit:
        consensus_state, reason_code = "invalidated", "review_material_context_too_large"
    return {
        "candidate_id": candidate_id,
        "proposal_id": proposal_id,
        "conversation_id": conversation_id,
        "author_participant_id": author_participant_id,
        "author_identity_fingerprint": _participant_fingerprint(author),
        "source_observation_id": source_observation_id,
        "source_batch_id": source_batch_id,
        "source_attempt_id": source_attempt_id,
        "source_activity_id": source_activity_id,
        "source_correlation_id": source_correlation_id,
        "patch": patch,
        "review_material_digest": material_digest,
        "context_fit_eligible": context_fit,
        "direct_human_root": direct_human_root,
        "peer_snapshot_digest": snapshot_digest,
        "policy_mode_snapshot": str(policy["mode"]),
        "policy_revision_snapshot": int(policy["revision"]),
        "risk_policy_revision_snapshot": str(policy["risk_policy_revision"]),
        "consensus_state": consensus_state,
        "reason_code": reason_code,
        "members": members,
        "created_at": stamp,
        "safe_reference": _safe_patch_reference(candidate_id, patch),
    }


def insert_execution_candidate_conn(
    conn: sqlite3.Connection, prepared: Mapping[str, Any]
) -> dict[str, Any]:
    patch = prepared["patch"]
    if not isinstance(patch, ExecutionPatch):
        raise RoomExecutionStoreError("room_execution_candidate_invalid")
    stamp = str(prepared["created_at"])
    conn.execute(
        """insert into room_execution_candidates
           (candidate_id, proposal_id, conversation_id, author_participant_id,
            author_identity_fingerprint,
            source_observation_id, source_batch_id, source_attempt_id, source_activity_id,
            source_correlation_id, base_head, summary, unified_diff, allowed_files_json,
            files_json, candidate_digest, patch_sha256, review_material_digest,
            patch_bytes, file_count,
            modify_only, context_fit_eligible, direct_human_root, peer_snapshot_digest,
            policy_mode_snapshot, policy_revision_snapshot, risk_policy_revision_snapshot,
            state, consensus_state, revision, reason_code, created_at, updated_at)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                   ?, ?, 'open', ?, 0, ?, ?, ?)""",
        (
            prepared["candidate_id"],
            prepared["proposal_id"],
            prepared["conversation_id"],
            prepared["author_participant_id"],
            prepared["author_identity_fingerprint"],
            prepared["source_observation_id"],
            prepared["source_batch_id"],
            prepared["source_attempt_id"],
            prepared["source_activity_id"],
            prepared["source_correlation_id"],
            patch.base_head,
            patch.summary,
            patch.unified_diff,
            json_value(list(patch.allowed_files)),
            json_value(
                [
                    {
                        "path": item.path,
                        "change_type": item.change_type,
                        "hunk_count": item.hunk_count,
                    }
                    for item in patch.files
                ]
            ),
            patch.candidate_digest,
            patch.patch_sha256,
            prepared["review_material_digest"],
            patch.patch_bytes,
            len(patch.files),
            int(patch.modify_only),
            int(bool(prepared["context_fit_eligible"])),
            int(bool(prepared["direct_human_root"])),
            prepared["peer_snapshot_digest"],
            prepared["policy_mode_snapshot"],
            prepared["policy_revision_snapshot"],
            prepared["risk_policy_revision_snapshot"],
            prepared["consensus_state"],
            prepared["reason_code"],
            stamp,
            stamp,
        ),
    )
    conn.executemany(
        """insert into room_execution_candidate_members
           (candidate_id, participant_id, identity_fingerprint, ordinal, status_snapshot)
           values (?, ?, ?, ?, ?)""",
        [
            (
                prepared["candidate_id"],
                item["participant_id"],
                item["identity_fingerprint"],
                item["ordinal"],
                item["status_snapshot"],
            )
            for item in prepared["members"]
        ],
    )
    return dict(prepared["safe_reference"])


def _refresh_consensus_state_conn(
    conn: sqlite3.Connection, candidate_id: str, *, stamp: str
) -> sqlite3.Row:
    candidate = conn.execute(
        "select * from room_execution_candidates where candidate_id = ?", (candidate_id,)
    ).fetchone()
    if candidate is None:
        raise RoomExecutionStoreError("room_execution_candidate_not_found")
    if candidate["consensus_state"] == "invalidated" or candidate["state"] != "open":
        return candidate
    counts = {
        str(row["assessment"]): int(row["count"])
        for row in conn.execute(
            "select assessment, count(*) count from room_execution_assessments "
            "where candidate_id = ? group by assessment",
            (candidate_id,),
        )
    }
    member_count = int(
        conn.execute(
            "select count(*) from room_execution_candidate_members where candidate_id = ?",
            (candidate_id,),
        ).fetchone()[0]
    )
    state = "collecting"
    reason: str | None = None
    if counts.get("object", 0):
        state, reason = "objected", "peer_objected"
    elif counts.get("abstain", 0):
        state, reason = "abstained", "peer_abstained"
    elif member_count > 0 and counts.get("endorse", 0) == member_count:
        state, reason = "endorsed", None
    if state != candidate["consensus_state"] or reason != candidate["reason_code"]:
        conn.execute(
            "update room_execution_candidates set consensus_state = ?, reason_code = ?, "
            "revision = revision + 1, updated_at = ? where candidate_id = ?",
            (state, reason, stamp, candidate_id),
        )
        candidate = conn.execute(
            "select * from room_execution_candidates where candidate_id = ?", (candidate_id,)
        ).fetchone()
    assert candidate is not None
    return candidate


def record_proposal_assessments_conn(
    conn: sqlite3.Connection,
    *,
    assessor_participant_id: str,
    source_attempt_id: str,
    source_batch_id: str | None,
    batch_activity_ids: set[str],
    assessments: Sequence[ProposalAssessment],
    stamp: str,
) -> list[dict[str, Any]]:
    """Validate current-batch review provenance and atomically record assessments."""

    if not assessments:
        return []
    if source_batch_id is None:
        raise RoomExecutionStoreError("room_execution_assessment_batch_required")
    participant = conn.execute(
        "select * from participants where participant_id = ?", (assessor_participant_id,)
    ).fetchone()
    if (
        participant is None
        or participant["status"] != "active"
        or participant["cli_kind"] != "codex"
    ):
        raise RoomExecutionStoreError("room_execution_assessor_invalid")
    current_fingerprint = _participant_fingerprint(participant)
    recorded: list[dict[str, Any]] = []
    touched: set[str] = set()
    for assessment in assessments:
        candidate = conn.execute(
            "select * from room_execution_candidates where proposal_id = ?",
            (assessment.proposal_id,),
        ).fetchone()
        if candidate is None or candidate["source_activity_id"] not in batch_activity_ids:
            raise RoomExecutionStoreError("room_execution_assessment_source_invalid")
        if candidate["candidate_digest"] != assessment.candidate_digest:
            raise RoomExecutionStoreError("room_execution_assessment_digest_mismatch")
        if candidate["author_participant_id"] == assessor_participant_id:
            raise RoomExecutionStoreError("room_execution_assessment_self_forbidden")
        member = conn.execute(
            """select * from room_execution_candidate_members
               where candidate_id = ? and participant_id = ?""",
            (candidate["candidate_id"], assessor_participant_id),
        ).fetchone()
        if member is None:
            raise RoomExecutionStoreError("room_execution_assessor_not_snapshot_peer")
        if member["identity_fingerprint"] != current_fingerprint:
            raise RoomExecutionStoreError("room_execution_assessor_identity_drift")
        if (
            not bool(member["full_material_available"])
            or member["review_attempt_id"] != source_attempt_id
            or member["review_batch_id"] != source_batch_id
            or member["review_activity_id"] != candidate["source_activity_id"]
            or member["review_material_digest"] != candidate["review_material_digest"]
        ):
            raise RoomExecutionStoreError("room_execution_review_material_unproven")
        try:
            assessment_id = new_id("execution_assessment")
            conn.execute(
                """insert into room_execution_assessments
                   (assessment_id, candidate_id, assessor_participant_id,
                    assessor_identity_fingerprint, assessment, rationale, candidate_digest,
                    review_material_digest, source_attempt_id, source_batch_id,
                    source_activity_id, created_at)
                   values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    assessment_id,
                    candidate["candidate_id"],
                    assessor_participant_id,
                    current_fingerprint,
                    assessment.assessment,
                    assessment.rationale,
                    assessment.candidate_digest,
                    candidate["review_material_digest"],
                    source_attempt_id,
                    source_batch_id,
                    candidate["source_activity_id"],
                    stamp,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise RoomExecutionStoreError("room_execution_assessment_duplicate") from exc
        touched.add(str(candidate["candidate_id"]))
        recorded.append(
            {
                "assessment_id": assessment_id,
                "candidate_id": candidate["candidate_id"],
                "proposal_id": assessment.proposal_id,
                "candidate_digest": assessment.candidate_digest,
                "assessment": assessment.assessment,
            }
        )
    for candidate_id in touched:
        _refresh_consensus_state_conn(conn, candidate_id, stamp=stamp)
    return recorded


def _policy_view(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema_version": "room_execution_policy/v1",
        "conversation_id": row["conversation_id"],
        "mode": row["mode"],
        "revision": int(row["revision"]),
        "risk_policy_revision": row["risk_policy_revision"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


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


def workspace_guard_digest(candidate: sqlite3.Row, workspace_guard: ExecutionWorkspaceGuard) -> str:
    require_digest(
        workspace_guard.target_files_digest,
        "room_execution_workspace_guard_digest_invalid",
    )
    if workspace_guard.base_head != candidate["base_head"] or not workspace_guard.workspace_clean:
        raise RoomExecutionStoreError("room_execution_workspace_guard_mismatch")
    allowed = set(decode_json(candidate["allowed_files_json"], []))
    files = decode_json(candidate["files_json"], [])
    existing = {canonical_execution_path(path) for path in workspace_guard.existing_regular_files}
    for item in files:
        path = item["path"]
        if item["change_type"] in {"modify", "delete"} and path not in existing:
            raise RoomExecutionStoreError("room_execution_workspace_guard_mismatch")
        if item["change_type"] == "add" and path in existing:
            raise RoomExecutionStoreError("room_execution_workspace_guard_mismatch")
    if not {item["path"] for item in files} == allowed:
        raise RoomExecutionStoreError("room_execution_candidate_corrupt")
    return workspace_guard.target_files_digest


def patch_from_candidate(candidate: sqlite3.Row) -> ExecutionPatch:
    return ExecutionPatch(
        schema_version="room_execution_patch/v1",
        base_head=candidate["base_head"],
        summary=candidate["summary"],
        unified_diff=candidate["unified_diff"],
        allowed_files=tuple(decode_json(candidate["allowed_files_json"], [])),
        files=tuple(
            ExecutionPatchFile(item["path"], item["change_type"], int(item["hunk_count"]))
            for item in decode_json(candidate["files_json"], [])
        ),
        candidate_digest=candidate["candidate_digest"],
        patch_sha256=candidate["patch_sha256"],
        patch_bytes=int(candidate["patch_bytes"]),
    )


def review_material_for_batch_conn(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    proposal_activity_id: str,
    observation_batch_id: str,
    participant_id: str,
    attempt_id: str,
) -> dict[str, Any]:
    row = conn.execute(
        """select c.* from room_execution_candidates c
           join room_execution_candidate_members cm
             on cm.candidate_id = c.candidate_id and cm.participant_id = ?
           join room_observation_batch_members bm
             on bm.batch_id = ? and bm.activity_id = c.source_activity_id
           join room_observation_attempts t
             on t.attempt_id = ? and t.batch_id = bm.batch_id
           join room_observations o
             on o.observation_id = t.observation_id and o.participant_id = ?
           where c.candidate_id = ? and c.source_activity_id = ?""",
        (
            participant_id,
            observation_batch_id,
            attempt_id,
            participant_id,
            candidate_id,
            proposal_activity_id,
        ),
    ).fetchone()
    if row is None:
        raise RoomExecutionStoreError("room_execution_review_source_invalid")
    if not bool(row["context_fit_eligible"]):
        raise RoomExecutionStoreError("room_execution_review_material_too_large")
    patch = patch_from_candidate(row)
    material = _review_material(
        candidate_id=row["candidate_id"],
        proposal_id=row["proposal_id"],
        source_activity_id=row["source_activity_id"],
        patch=patch,
    )
    if digest(material) != row["review_material_digest"]:
        raise RoomExecutionStoreError("room_execution_review_material_corrupt")
    return material


def bind_review_material_receipt_conn(
    conn: sqlite3.Connection,
    *,
    candidate_id: str,
    proposal_activity_id: str,
    observation_batch_id: str,
    participant_id: str,
    attempt_id: str,
    review_material_digest: str,
    context_payload_sha256: str,
    stamp: str,
) -> dict[str, Any]:
    review_material_digest = require_digest(
        review_material_digest, "room_execution_review_material_digest_invalid"
    )
    context_payload_sha256 = require_digest(
        context_payload_sha256, "room_execution_review_context_digest_invalid"
    )
    material = review_material_for_batch_conn(
        conn,
        candidate_id=candidate_id,
        proposal_activity_id=proposal_activity_id,
        observation_batch_id=observation_batch_id,
        participant_id=participant_id,
        attempt_id=attempt_id,
    )
    expected = digest(material)
    if review_material_digest != expected:
        raise RoomExecutionStoreError("room_execution_review_material_digest_mismatch")
    member = conn.execute(
        "select * from room_execution_candidate_members "
        "where candidate_id = ? and participant_id = ?",
        (candidate_id, participant_id),
    ).fetchone()
    if member is None:
        raise RoomExecutionStoreError("room_execution_assessor_not_snapshot_peer")
    facts = (
        attempt_id,
        observation_batch_id,
        proposal_activity_id,
        expected,
        context_payload_sha256,
    )
    prior = (
        member["review_attempt_id"],
        member["review_batch_id"],
        member["review_activity_id"],
        member["review_material_digest"],
        member["review_context_payload_sha256"],
    )
    if bool(member["full_material_available"]):
        if prior != facts:
            raise RoomExecutionStoreError("room_execution_review_receipt_conflict")
    else:
        conn.execute(
            """update room_execution_candidate_members
               set review_attempt_id = ?, review_batch_id = ?, review_activity_id = ?,
                   review_material_digest = ?, review_context_payload_sha256 = ?,
                   full_material_available = 1, review_bound_at = ?
               where candidate_id = ? and participant_id = ?""",
            (*facts, stamp, candidate_id, participant_id),
        )
    return {
        "candidate_id": candidate_id,
        "participant_id": participant_id,
        "attempt_id": attempt_id,
        "observation_batch_id": observation_batch_id,
        "proposal_activity_id": proposal_activity_id,
        "review_material_digest": expected,
        "context_payload_sha256": context_payload_sha256,
        "full_material_available": True,
    }
