"""Reconciler-only capability adapter for exact-patch execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_candidates import (
    _ensure_policy_conn,
    _participant_fingerprint,
    _refresh_consensus_state_conn,
    patch_from_candidate,
    workspace_guard_digest,
)
from xmuse_core.chat.room_execution_common import (
    RoomExecutionStoreError,
    require_digest,
    timestamp,
)
from xmuse_core.chat.room_execution_contracts import (
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
    low_risk_patch_eligible,
)
from xmuse_core.chat.room_execution_events import record_execution_event_conn
from xmuse_core.chat.room_execution_profiles import ExecutionGatePlan
from xmuse_core.chat.room_execution_read_store import RoomExecutionLedgerReader
from xmuse_core.chat.room_execution_runs import (
    authorize_execution_conn,
    required_gate_plan_for_run_conn,
    trusted_gate_plan,
)
from xmuse_core.chat.room_execution_views import run_view_conn


class ExecutionRuntimeStore(Protocol):
    """Minimal durable capability required by the long-lived reconciler."""

    def get_candidate(
        self, candidate_id: str, *, include_patch: bool = False
    ) -> Mapping[str, Any] | None: ...

    def list_endorsed_candidate_ids(self, *, limit: int = 20) -> Sequence[str]: ...

    def reconcile_consensus_candidate(
        self,
        *,
        candidate_id: str,
        kill_switch_enabled: bool,
        workspace_guard: ExecutionWorkspaceGuard,
        risk_evaluation: ExecutionRiskEvaluation,
        gate_plan: ExecutionGatePlan | None = None,
        now: datetime | None = None,
    ) -> Mapping[str, Any]: ...

    def list_controller_recovery(self, *, limit: int = 100) -> Sequence[Mapping[str, Any]]: ...


class RoomExecutionRuntimeStore:
    """Expose consensus discovery and controller recovery to the long-lived runtime."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)
        self._reader = RoomExecutionLedgerReader(db_path)

    def get_candidate(
        self, candidate_id: str, *, include_patch: bool = False
    ) -> dict[str, Any] | None:
        return self._reader.get_candidate(candidate_id, include_patch=include_patch)

    def list_endorsed_candidate_ids(self, *, limit: int = 20) -> list[str]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select candidate_id from room_execution_candidates
                   where state = 'open' and consensus_state = 'endorsed'
                   order by created_at, candidate_id limit ?""",
                (clean_limit,),
            ).fetchall()
        return [str(row["candidate_id"]) for row in rows]

    def reconcile_consensus_candidate(
        self,
        *,
        candidate_id: str,
        kill_switch_enabled: bool,
        workspace_guard: ExecutionWorkspaceGuard,
        risk_evaluation: ExecutionRiskEvaluation,
        gate_plan: ExecutionGatePlan | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Create at most one consensus authorization/run after all trusted guards."""

        if not isinstance(kill_switch_enabled, bool):
            raise RoomExecutionStoreError("room_execution_kill_switch_invalid")
        stamp = timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                candidate = conn.execute(
                    "select * from room_execution_candidates where candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                if candidate is None:
                    raise RoomExecutionStoreError("room_execution_candidate_not_found")
                if candidate["state"] == "authorized":
                    run = conn.execute(
                        "select * from room_execution_runs where candidate_id = ?",
                        (candidate_id,),
                    ).fetchone()
                    if run is None:
                        raise RoomExecutionStoreError("room_execution_authorization_corrupt")
                    required_gate_plan_for_run_conn(conn, run)
                    conn.rollback()
                    return {
                        "created": False,
                        "status": "authorized",
                        "run": run_view_conn(conn, run),
                    }
                candidate = _refresh_consensus_state_conn(conn, candidate_id, stamp=stamp)
                reason: str | None = None
                policy = _ensure_policy_conn(conn, candidate["conversation_id"], stamp=stamp)
                if not kill_switch_enabled:
                    reason = "consensus_kill_switch_disabled"
                elif candidate["policy_mode_snapshot"] != "consensus":
                    reason = "consensus_not_enabled_at_creation"
                elif (
                    policy["mode"] != "consensus"
                    or int(policy["revision"]) != int(candidate["policy_revision_snapshot"])
                    or policy["risk_policy_revision"] != candidate["risk_policy_revision_snapshot"]
                ):
                    reason = "consensus_policy_drift"
                elif not bool(candidate["direct_human_root"]):
                    reason = "consensus_human_root_required"
                elif not bool(candidate["context_fit_eligible"]):
                    reason = "review_material_context_too_large"
                elif candidate["consensus_state"] != "endorsed":
                    reason = str(candidate["reason_code"] or "consensus_incomplete")
                elif gate_plan is None:
                    reason = "execution_gate_profile_unavailable"
                members = conn.execute(
                    """select cm.*, p.status current_status, p.role, p.display_name, p.cli_kind,
                              p.model, p.role_template_id, p.persona_snapshot_sha256,
                              p.participant_id
                       from room_execution_candidate_members cm
                       join participants p on p.participant_id = cm.participant_id
                       where cm.candidate_id = ? order by cm.ordinal""",
                    (candidate_id,),
                ).fetchall()
                if not members:
                    reason = reason or "consensus_peer_required"
                if reason is None:
                    author = conn.execute(
                        "select * from participants where participant_id = ?",
                        (candidate["author_participant_id"],),
                    ).fetchone()
                    if (
                        author is None
                        or author["status"] != "active"
                        or author["cli_kind"] != "codex"
                        or _participant_fingerprint(author)
                        != candidate["author_identity_fingerprint"]
                    ):
                        reason = "consensus_author_drift"
                if reason is None:
                    for member in members:
                        if (
                            member["current_status"] != "active"
                            or member["cli_kind"] != "codex"
                            or _participant_fingerprint(member) != member["identity_fingerprint"]
                        ):
                            reason = "consensus_member_drift"
                            break
                        if not bool(member["full_material_available"]):
                            reason = "consensus_review_material_unproven"
                            break
                patch = patch_from_candidate(candidate)
                if reason is None and not low_risk_patch_eligible(patch):
                    reason = "consensus_low_risk_ceiling_failed"
                if reason is None and (
                    not risk_evaluation.approved
                    or risk_evaluation.policy_revision != candidate["risk_policy_revision_snapshot"]
                ):
                    reason = risk_evaluation.reason_code or "consensus_risk_rejected"
                if reason is not None:
                    if (
                        reason
                        in {
                            "consensus_policy_drift",
                            "consensus_member_drift",
                            "consensus_author_drift",
                            "review_material_context_too_large",
                            "execution_gate_profile_unavailable",
                        }
                        and candidate["consensus_state"] != "invalidated"
                    ):
                        conn.execute(
                            """update room_execution_candidates set consensus_state = 'invalidated',
                               reason_code = ?, revision = revision + 1, updated_at = ?
                               where candidate_id = ?""",
                            (reason, stamp, candidate_id),
                        )
                        conn.commit()
                    else:
                        conn.rollback()
                    return {
                        "created": False,
                        "status": "manual_required",
                        "candidate_id": candidate_id,
                        "reason_code": reason,
                        "run": None,
                    }
                try:
                    workspace_digest = workspace_guard_digest(candidate, workspace_guard)
                except RoomExecutionStoreError as exc:
                    if exc.code not in {
                        "room_execution_workspace_guard_mismatch",
                        "room_execution_workspace_guard_digest_invalid",
                    }:
                        raise
                    reason = "consensus_workspace_guard_drift"
                    conn.execute(
                        """update room_execution_candidates
                           set consensus_state = 'invalidated', reason_code = ?,
                               revision = revision + 1, updated_at = ?
                           where candidate_id = ? and state = 'open'""",
                        (reason, stamp, candidate_id),
                    )
                    conn.commit()
                    return {
                        "created": False,
                        "status": "manual_required",
                        "candidate_id": candidate_id,
                        "reason_code": reason,
                        "run": None,
                    }
                risk_digest = require_digest(
                    risk_evaluation.evidence_digest,
                    "room_execution_risk_evidence_invalid",
                )
                trusted_plan = trusted_gate_plan(candidate, gate_plan)
                _, run, created = authorize_execution_conn(
                    conn,
                    candidate=candidate,
                    authorization_mode="consensus",
                    workspace_guard_digest=workspace_digest,
                    risk_evidence_digest=risk_digest,
                    gate_plan=trusted_plan,
                    stamp=stamp,
                )
                if created:
                    record_execution_event_conn(
                        conn,
                        conversation_id=candidate["conversation_id"],
                        event_type="projection.changed",
                        resource_ref=f"room:execution-run:{run['run_id']}",
                        source_ref=f"room:execution-candidate:{candidate_id}",
                        payload={
                            "change": "execution.run_requested",
                            "candidate_id": candidate_id,
                            "run_id": run["run_id"],
                        },
                        client_action_id=None,
                        stamp=stamp,
                    )
                result = {
                    "created": created,
                    "status": "authorized",
                    "candidate_id": candidate_id,
                    "run": run_view_conn(conn, run),
                }
                conn.commit()
                return result
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    def list_controller_recovery(self, *, limit: int = 100) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 500))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                """select run_id, state, revision, execution_generation, controller_id,
                          controller_generation, controller_pid, controller_start_identity,
                          updated_at
                   from room_execution_runs where state not in
                     ('cancelled','succeeded','failed','blocked')
                   order by requested_at, run_id limit ?""",
                (clean_limit,),
            ).fetchall()
        return [
            {
                "run_id": row["run_id"],
                "state": row["state"],
                "revision": int(row["revision"]),
                "execution_generation": int(row["execution_generation"]),
                "controller_id": row["controller_id"],
                "controller_generation": row["controller_generation"],
                "controller_pid": (
                    int(row["controller_pid"]) if row["controller_pid"] is not None else None
                ),
                "controller_start_identity": row["controller_start_identity"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]


def _execution_runtime_store_protocol_proof(
    store: RoomExecutionRuntimeStore,
) -> ExecutionRuntimeStore:
    """Keep the adapter structurally aligned with the reconciler's narrow port."""

    return store
