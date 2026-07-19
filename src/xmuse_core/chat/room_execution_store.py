"""Durable authority for exact-patch candidates, consensus, and runs.

Room Agents can create candidates and assessments through the single outcome
transaction.  Only privileged callers may authorize or control a run; this store
never starts a process.
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.participant_store import INIT_GOD_ROLE
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_actions import (
    complete_execution_action_conn,
    replay_execution_action,
    reserve_execution_action_conn,
)
from xmuse_core.chat.room_execution_actions import (
    operator_decision_fingerprint as _operator_decision_fingerprint,
)
from xmuse_core.chat.room_execution_candidates import (
    _ensure_policy_conn,
    _participant_fingerprint,
    _refresh_consensus_state_conn,
    patch_from_candidate,
    workspace_guard_digest,
)
from xmuse_core.chat.room_execution_candidates import (
    insert_execution_candidate_conn as insert_execution_candidate_conn,
)
from xmuse_core.chat.room_execution_candidates import (
    policy_view as _policy_view,
)
from xmuse_core.chat.room_execution_candidates import (
    prepare_execution_candidate_conn as prepare_execution_candidate_conn,
)
from xmuse_core.chat.room_execution_candidates import (
    record_proposal_assessments_conn as record_proposal_assessments_conn,
)
from xmuse_core.chat.room_execution_common import (
    RUN_TRANSITIONS as _RUN_TRANSITIONS,
)
from xmuse_core.chat.room_execution_common import (
    TERMINAL_RUN_STATES,
    RoomExecutionStoreError,
)
from xmuse_core.chat.room_execution_common import (
    decode_json as _decode,
)
from xmuse_core.chat.room_execution_common import (
    digest as _digest,
)
from xmuse_core.chat.room_execution_common import (
    json_value as _json,
)
from xmuse_core.chat.room_execution_common import (
    new_id as _id,
)
from xmuse_core.chat.room_execution_common import (
    require_digest as _require_digest,
)
from xmuse_core.chat.room_execution_common import (
    require_text as _require_text,
)
from xmuse_core.chat.room_execution_common import (
    timestamp as _timestamp,
)
from xmuse_core.chat.room_execution_contracts import (
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
    canonical_execution_path,
    low_risk_patch_eligible,
)
from xmuse_core.chat.room_execution_events import record_execution_event_conn
from xmuse_core.chat.room_execution_profiles import ExecutionGatePlan
from xmuse_core.chat.room_execution_promotion import (
    mark_promotion_applying_conn,
    normalize_promotion_entries,
    prepare_promotion_journal_conn,
    resolve_promotion_journal_conn,
)
from xmuse_core.chat.room_execution_read_store import RoomExecutionLedgerReader
from xmuse_core.chat.room_execution_review_store import RoomExecutionReviewStore
from xmuse_core.chat.room_execution_runs import (
    advance_run_conn,
    assert_controller_conn,
    authorize_execution_conn,
    bound_run_conn,
    claim_requested_run_conn,
    controller_identity,
    reclaim_run_controller_conn,
    record_gate_evidence_conn,
)
from xmuse_core.chat.room_execution_runs import (
    required_gate_plan_for_run_conn as _required_gate_plan_for_run_conn,
)
from xmuse_core.chat.room_execution_runs import (
    trusted_gate_plan as _trusted_gate_plan,
)
from xmuse_core.chat.room_execution_schema import (
    create_room_execution_schema as create_room_execution_schema,
)
from xmuse_core.chat.room_execution_views import (
    candidate_view_conn as _candidate_view_conn,
)
from xmuse_core.chat.room_execution_views import run_view_conn as _run_view_conn


class _ExecutionLedger(RoomExecutionReviewStore, RoomExecutionLedgerReader):
    """Internal durable implementation shared only by narrow execution adapters.

    Its methods deliberately retain the existing transaction boundaries while the
    public ``RoomExecutionStore`` name remains a compatibility facade for older
    in-process callers.
    """

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

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

    _reserve_action_conn = staticmethod(reserve_execution_action_conn)
    _complete_action_conn = staticmethod(complete_execution_action_conn)
    _record_event_conn = staticmethod(record_execution_event_conn)
    _workspace_guard_digest = staticmethod(workspace_guard_digest)
    _patch_from_candidate = staticmethod(patch_from_candidate)
    _authorize_conn = staticmethod(authorize_execution_conn)
    _action_replay = staticmethod(replay_execution_action)
    _controller_identity = staticmethod(controller_identity)
    _assert_controller_conn = staticmethod(assert_controller_conn)
    _bound_run_conn = staticmethod(bound_run_conn)
    _promotion_entries = staticmethod(normalize_promotion_entries)

    def set_policy(
        self,
        *,
        conversation_id: str,
        mode: Literal["manual", "consensus"],
        client_action_id: str,
        operator_identity: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if mode not in {"manual", "consensus"}:
            raise RoomExecutionStoreError("room_execution_policy_mode_invalid")
        client_action_id = _require_text(
            client_action_id, "room_execution_client_action_id_required"
        )
        operator_identity = _require_text(
            operator_identity, "room_execution_operator_identity_required"
        )
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise RoomExecutionStoreError("room_execution_policy_revision_invalid")
        request = {
            "conversation_id": conversation_id,
            "mode": mode,
            "expected_revision": expected_revision,
        }
        fingerprint = _digest(request)
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                if (
                    conn.execute(
                        "select 1 from conversations where id = ?", (conversation_id,)
                    ).fetchone()
                    is None
                ):
                    raise RoomExecutionStoreError("room_execution_conversation_not_found")
                policy = _ensure_policy_conn(conn, conversation_id, stamp=stamp)
                action, created = self._reserve_action_conn(
                    conn,
                    conversation_id=conversation_id,
                    candidate_id=None,
                    action_type="policy_update",
                    client_action_id=client_action_id,
                    operator_identity=operator_identity,
                    fingerprint=fingerprint,
                    expected_candidate_digest=None,
                    expected_candidate_revision=None,
                    expected_policy_revision=expected_revision,
                    expected_run_state=None,
                    expected_run_revision=None,
                    stamp=stamp,
                )
                if not created:
                    conn.rollback()
                    return _decode(action["result_json"], {})
                if (
                    conn.execute(
                        """select 1 from room_execution_runs
                           where conversation_id = ? and state = 'promoting' limit 1""",
                        (conversation_id,),
                    ).fetchone()
                    is not None
                ):
                    raise RoomExecutionStoreError("room_execution_policy_promotion_conflict")
                if int(policy["revision"]) != expected_revision:
                    raise RoomExecutionStoreError("room_execution_policy_guard_mismatch")
                if policy["mode"] != mode:
                    conn.execute(
                        """update room_execution_policies set mode = ?, revision = revision + 1,
                           updated_at = ? where conversation_id = ? and revision = ?""",
                        (mode, stamp, conversation_id, expected_revision),
                    )
                updated = conn.execute(
                    "select * from room_execution_policies where conversation_id = ?",
                    (conversation_id,),
                ).fetchone()
                assert updated is not None
                result = _policy_view(updated)
                self._complete_action_conn(
                    conn,
                    action_id=action["action_id"],
                    status="applied",
                    result=result,
                    reason_code=None,
                    run_id=None,
                    stamp=stamp,
                )
                self._record_event_conn(
                    conn,
                    conversation_id=conversation_id,
                    event_type="projection.changed",
                    resource_ref=f"room:execution-policy:{conversation_id}",
                    source_ref=f"room:execution-policy:{conversation_id}",
                    payload={"change": "execution.policy_changed", "revision": result["revision"]},
                    client_action_id=client_action_id,
                    stamp=stamp,
                )
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def replay_operator_decision(
        self,
        *,
        candidate_id: str,
        decision: Literal["execute", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_candidate_revision: int,
        expected_policy_revision: int,
    ) -> dict[str, Any] | None:
        """Read an exact durable decision replay without reserving an action."""

        if decision not in {"execute", "reject"}:
            raise RoomExecutionStoreError("room_execution_decision_invalid")
        client_action_id = _require_text(
            client_action_id,
            "room_execution_client_action_id_required",
        )
        operator_identity = _require_text(
            operator_identity,
            "room_execution_operator_identity_required",
        )
        expected_candidate_digest = _require_digest(
            expected_candidate_digest,
            "room_execution_candidate_digest_invalid",
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (expected_candidate_revision, expected_policy_revision)
        ):
            raise RoomExecutionStoreError("room_execution_revision_invalid")
        fingerprint = _operator_decision_fingerprint(
            candidate_id=candidate_id,
            decision=decision,
            expected_candidate_digest=expected_candidate_digest,
            expected_candidate_revision=expected_candidate_revision,
            expected_policy_revision=expected_policy_revision,
        )
        with self._database.connect(readonly=True) as conn:
            action = conn.execute(
                """select * from room_execution_operator_actions
                   where operator_identity = ? and client_action_id = ?""",
                (operator_identity, client_action_id),
            ).fetchone()
        if action is None:
            return None
        expected_type = "candidate_execute" if decision == "execute" else "candidate_reject"
        if (
            action["candidate_id"] != candidate_id
            or action["action_type"] != expected_type
            or action["request_fingerprint"] != fingerprint
            or action["expected_candidate_digest"] != expected_candidate_digest
            or action["expected_candidate_revision"] != expected_candidate_revision
            or action["expected_policy_revision"] != expected_policy_revision
        ):
            raise RoomExecutionStoreError("room_execution_action_idempotency_conflict")
        return self._action_replay(action)

    def apply_operator_decision(
        self,
        *,
        candidate_id: str,
        decision: Literal["execute", "reject"],
        client_action_id: str,
        operator_identity: str,
        expected_candidate_digest: str,
        expected_candidate_revision: int,
        expected_policy_revision: int,
        workspace_guard: ExecutionWorkspaceGuard | None = None,
        risk_evaluation: ExecutionRiskEvaluation | None = None,
        gate_plan: ExecutionGatePlan | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if decision not in {"execute", "reject"}:
            raise RoomExecutionStoreError("room_execution_decision_invalid")
        client_action_id = _require_text(
            client_action_id, "room_execution_client_action_id_required"
        )
        operator_identity = _require_text(
            operator_identity, "room_execution_operator_identity_required"
        )
        expected_candidate_digest = _require_digest(
            expected_candidate_digest, "room_execution_candidate_digest_invalid"
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (expected_candidate_revision, expected_policy_revision)
        ):
            raise RoomExecutionStoreError("room_execution_revision_invalid")
        stamp = _timestamp(now)
        fingerprint = _operator_decision_fingerprint(
            candidate_id=candidate_id,
            decision=decision,
            expected_candidate_digest=expected_candidate_digest,
            expected_candidate_revision=expected_candidate_revision,
            expected_policy_revision=expected_policy_revision,
        )
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                candidate = conn.execute(
                    "select * from room_execution_candidates where candidate_id = ?",
                    (candidate_id,),
                ).fetchone()
                if candidate is None:
                    raise RoomExecutionStoreError("room_execution_candidate_not_found")
                action, created = self._reserve_action_conn(
                    conn,
                    conversation_id=candidate["conversation_id"],
                    candidate_id=candidate_id,
                    action_type=(
                        "candidate_execute" if decision == "execute" else "candidate_reject"
                    ),
                    client_action_id=client_action_id,
                    operator_identity=operator_identity,
                    fingerprint=fingerprint,
                    expected_candidate_digest=expected_candidate_digest,
                    expected_candidate_revision=expected_candidate_revision,
                    expected_policy_revision=expected_policy_revision,
                    expected_run_state=None,
                    expected_run_revision=None,
                    stamp=stamp,
                )
                if not created:
                    conn.rollback()
                    return self._action_replay(action)
                policy = _ensure_policy_conn(conn, candidate["conversation_id"], stamp=stamp)
                if (
                    candidate["candidate_digest"] != expected_candidate_digest
                    or int(candidate["revision"]) != expected_candidate_revision
                    or int(policy["revision"]) != expected_policy_revision
                    or candidate["state"] != "open"
                ):
                    reason = "room_execution_candidate_guard_mismatch"
                    self._complete_action_conn(
                        conn,
                        action_id=action["action_id"],
                        status="rejected",
                        result={
                            "candidate_id": candidate_id,
                            "status": "rejected",
                            "reason_code": reason,
                        },
                        reason_code=reason,
                        run_id=None,
                        stamp=stamp,
                    )
                    conn.commit()
                    raise RoomExecutionStoreError(reason)
                if decision == "reject":
                    conn.execute(
                        """update room_execution_candidates set state = 'rejected',
                           consensus_state = 'invalidated', revision = revision + 1,
                           reason_code = 'operator_rejected', rejected_at = ?, updated_at = ?
                           where candidate_id = ? and state = 'open'""",
                        (stamp, stamp, candidate_id),
                    )
                    result = {
                        "candidate_id": candidate_id,
                        "state": "rejected",
                        "reason_code": "operator_rejected",
                    }
                    self._complete_action_conn(
                        conn,
                        action_id=action["action_id"],
                        status="applied",
                        result=result,
                        reason_code=None,
                        run_id=None,
                        stamp=stamp,
                    )
                    self._record_event_conn(
                        conn,
                        conversation_id=candidate["conversation_id"],
                        event_type="projection.changed",
                        resource_ref=f"room:execution-candidate:{candidate_id}",
                        source_ref=f"room:execution-candidate:{candidate_id}",
                        payload={
                            "change": "execution.candidate_rejected",
                            "candidate_id": candidate_id,
                        },
                        client_action_id=client_action_id,
                        stamp=stamp,
                    )
                    conn.commit()
                    return result
                if workspace_guard is None:
                    raise RoomExecutionStoreError("room_execution_workspace_guard_required")
                trusted_plan = _trusted_gate_plan(candidate, gate_plan)
                workspace_digest = self._workspace_guard_digest(candidate, workspace_guard)
                risk_digest: str | None = None
                if risk_evaluation is not None:
                    risk_digest = _require_digest(
                        risk_evaluation.evidence_digest,
                        "room_execution_risk_evidence_invalid",
                    )
                    if not risk_evaluation.approved:
                        raise RoomExecutionStoreError(
                            risk_evaluation.reason_code or "room_execution_risk_rejected"
                        )
                _, run, _ = self._authorize_conn(
                    conn,
                    candidate=candidate,
                    authorization_mode="manual",
                    workspace_guard_digest=workspace_digest,
                    risk_evidence_digest=risk_digest,
                    gate_plan=trusted_plan,
                    stamp=stamp,
                )
                execute_result: dict[str, Any] = {
                    "candidate_id": candidate_id,
                    "state": "authorized",
                    "authorization_mode": "manual",
                    "run": _run_view_conn(conn, run),
                }
                self._complete_action_conn(
                    conn,
                    action_id=action["action_id"],
                    status="applied",
                    result=execute_result,
                    reason_code=None,
                    run_id=run["run_id"],
                    stamp=stamp,
                )
                self._record_event_conn(
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
                    client_action_id=client_action_id,
                    stamp=stamp,
                )
                conn.commit()
                return execute_result
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

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
        stamp = _timestamp(now)
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
                    _required_gate_plan_for_run_conn(conn, run)
                    conn.rollback()
                    return {
                        "created": False,
                        "status": "authorized",
                        "run": _run_view_conn(conn, run),
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
                patch = self._patch_from_candidate(candidate)
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
                    workspace_digest = self._workspace_guard_digest(candidate, workspace_guard)
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
                risk_digest = _require_digest(
                    risk_evaluation.evidence_digest,
                    "room_execution_risk_evidence_invalid",
                )
                trusted_plan = _trusted_gate_plan(candidate, gate_plan)
                _, run, created = self._authorize_conn(
                    conn,
                    candidate=candidate,
                    authorization_mode="consensus",
                    workspace_guard_digest=workspace_digest,
                    risk_evidence_digest=risk_digest,
                    gate_plan=trusted_plan,
                    stamp=stamp,
                )
                if created:
                    self._record_event_conn(
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
                    "run": _run_view_conn(conn, run),
                }
                conn.commit()
                return result
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    @staticmethod
    def _controller_material_conn(conn: sqlite3.Connection, run: sqlite3.Row) -> dict[str, Any]:
        candidate = conn.execute(
            "select * from room_execution_candidates where candidate_id = ?",
            (run["candidate_id"],),
        ).fetchone()
        authorization = conn.execute(
            "select * from room_execution_authorizations where authorization_id = ?",
            (run["authorization_id"],),
        ).fetchone()
        if candidate is None or authorization is None:
            raise RoomExecutionStoreError("room_execution_run_authority_corrupt")
        gate_plan = _required_gate_plan_for_run_conn(conn, run)
        public = _run_view_conn(conn, run)
        public["execution_generation"] = int(run["execution_generation"])
        public["controller"] = {
            "id": run["controller_id"],
            "generation": run["controller_generation"],
            "pid": int(run["controller_pid"]),
            "start_identity": run["controller_start_identity"],
        }
        public["candidate"] = _candidate_view_conn(conn, candidate, include_patch=True)
        public["gate_plan"] = gate_plan.internal_mapping()
        public["authorization"] = {
            "authorization_id": authorization["authorization_id"],
            "mode": authorization["authorization_mode"],
            "candidate_digest": authorization["candidate_digest"],
            "candidate_revision": int(authorization["candidate_revision"]),
            "policy_revision": int(authorization["policy_revision"]),
            "risk_policy_revision": authorization["risk_policy_revision"],
            "peer_snapshot_digest": authorization["peer_snapshot_digest"],
            "workspace_guard_digest": authorization["workspace_guard_digest"],
            "risk_evidence_digest": authorization["risk_evidence_digest"],
            "status": authorization["status"],
        }
        return public

    def get_controller_material(
        self,
        *,
        run_id: str,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        execution_generation: int,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        with self._database.connect(readonly=True) as conn:
            run = conn.execute(
                "select * from room_execution_runs where run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise RoomExecutionStoreError("room_execution_run_not_found")
            self._assert_controller_conn(
                run,
                controller_id=identity[0],
                controller_generation=identity[1],
                controller_pid=identity[2],
                controller_start_identity=identity[3],
                execution_generation=execution_generation,
            )
            return self._controller_material_conn(conn, run)

    def claim_requested_run(
        self,
        *,
        run_id: str,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        return self._claim_requested_run(run_id=run_id, identity=identity, now=now)

    def _claim_requested_run(
        self,
        *,
        run_id: str,
        identity: tuple[str, str, int, str],
        now: datetime | None,
    ) -> dict[str, Any]:
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                updated = claim_requested_run_conn(
                    conn,
                    run_id=run_id,
                    identity=identity,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def claim_next_requested_run(
        self,
        *,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                """select run_id from room_execution_runs
                   where state in ('requested','cancel_requested') and controller_id is null
                   order by requested_at, run_id limit 1"""
            ).fetchone()
        if row is None:
            return None
        try:
            return self._claim_requested_run(run_id=str(row["run_id"]), identity=identity, now=now)
        except RoomExecutionStoreError as exc:
            if exc.code == "room_execution_run_claim_conflict":
                return None
            raise

    def reclaim_run_controller(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        expected_execution_generation: int,
        prior_controller_id: str,
        prior_controller_generation: str,
        prior_controller_pid: int,
        prior_controller_start_identity: str,
        confirmed_dead: bool,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if confirmed_dead is not True:
            raise RoomExecutionStoreError("room_execution_takeover_death_unconfirmed")
        old = self._controller_identity(
            controller_id=prior_controller_id,
            controller_generation=prior_controller_generation,
            controller_pid=prior_controller_pid,
            controller_start_identity=prior_controller_start_identity,
        )
        new = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                updated = reclaim_run_controller_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_state,
                    expected_revision=expected_revision,
                    expected_execution_generation=expected_execution_generation,
                    old_identity=old,
                    new_identity=new,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def list_controller_recovery(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Return private bindings for a trusted supervisor's /proc identity checks."""

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

    def advance_run(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        target_state: str,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_state,
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                updated = advance_run_conn(
                    conn,
                    run=run,
                    target_state=target_state,
                    reason_code=reason_code,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def record_gate_evidence(
        self,
        *,
        run_id: str,
        expected_run_state: str,
        expected_run_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        gate_id: str,
        status: Literal["running", "passed", "failed", "cancelled"],
        evidence_digest: str,
        started_at: str,
        finished_at: str | None = None,
        reason_code: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_run_state,
                    expected_revision=expected_run_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                updated, changed = record_gate_evidence_conn(
                    conn,
                    run=run,
                    execution_generation=execution_generation,
                    gate_id=gate_id,
                    status=status,
                    evidence_digest=evidence_digest,
                    started_at=started_at,
                    finished_at=finished_at,
                    reason_code=reason_code,
                    stamp=stamp,
                )
                if not changed:
                    conn.rollback()
                    return _run_view_conn(conn, updated)
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def prepare_promotion(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        target_head: str,
        pre_manifest_digest: str,
        post_manifest_digest: str,
        file_entries: Sequence[Mapping[str, Any]],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        pre_manifest_digest = _require_digest(
            pre_manifest_digest, "room_execution_promotion_digest_invalid"
        )
        post_manifest_digest = _require_digest(
            post_manifest_digest, "room_execution_promotion_digest_invalid"
        )
        target_head = _require_text(target_head, "room_execution_target_head_invalid", maximum=64)
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state="ready_to_promote",
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                candidate = conn.execute(
                    "select * from room_execution_candidates where candidate_id = ?",
                    (run["candidate_id"],),
                ).fetchone()
                if candidate is None or target_head != candidate["base_head"]:
                    raise RoomExecutionStoreError("room_execution_promotion_head_mismatch")
                authorization = conn.execute(
                    "select * from room_execution_authorizations where authorization_id = ?",
                    (run["authorization_id"],),
                ).fetchone()
                policy = conn.execute(
                    "select * from room_execution_policies where conversation_id = ?",
                    (run["conversation_id"],),
                ).fetchone()
                policy_drift = (
                    authorization is None
                    or policy is None
                    or authorization["status"] != "consumed"
                    or policy["mode"] != candidate["policy_mode_snapshot"]
                    or int(policy["revision"]) != int(authorization["policy_revision"])
                    or policy["risk_policy_revision"] != authorization["risk_policy_revision"]
                    or int(authorization["policy_revision"])
                    != int(candidate["policy_revision_snapshot"])
                    or authorization["risk_policy_revision"]
                    != candidate["risk_policy_revision_snapshot"]
                )
                if policy_drift:
                    gate_plan = _required_gate_plan_for_run_conn(conn, run)
                    evidence = {
                        str(row["gate_id"]): str(row["status"])
                        for row in conn.execute(
                            """select gate_id, status from room_execution_gate_evidence
                               where run_id = ? and execution_generation = ?""",
                            (run_id, execution_generation),
                        )
                    }
                    completed_gates = tuple(
                        gate_id
                        for gate_id in gate_plan.gate_ids
                        if evidence.get(gate_id) == "passed"
                    )
                    blocked = self._finalize_run_conn(
                        conn,
                        run=run,
                        terminal_state="blocked",
                        reason_code="execution_policy_guard_changed",
                        changed_files=(),
                        gate_ids=completed_gates,
                        evidence_digest=None,
                        stamp=stamp,
                    )
                    result = self._controller_material_conn(conn, blocked)
                    conn.commit()
                    return result
                entries_json = self._promotion_entries(candidate, file_entries)
                updated = prepare_promotion_journal_conn(
                    conn,
                    run_id=run_id,
                    journal_id=_id("execution_promotion"),
                    execution_generation=execution_generation,
                    target_head=target_head,
                    pre_manifest_digest=pre_manifest_digest,
                    post_manifest_digest=post_manifest_digest,
                    file_entries_json=entries_json,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def mark_promotion_applying(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state="promoting",
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                updated = mark_promotion_applying_conn(conn, run_id=run_id, stamp=stamp)
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def resolve_promotion(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        observed_manifest_digest: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        observed_manifest_digest = _require_digest(
            observed_manifest_digest, "room_execution_promotion_digest_invalid"
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state="promoting",
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )

                def finalize_ambiguous(
                    target_conn: sqlite3.Connection,
                    target_run: sqlite3.Row,
                    digest: str,
                    target_stamp: str,
                ) -> sqlite3.Row:
                    return self._finalize_run_conn(
                        target_conn,
                        run=target_run,
                        terminal_state="blocked",
                        reason_code="promotion_ambiguous",
                        changed_files=(),
                        gate_ids=(),
                        evidence_digest=digest,
                        stamp=target_stamp,
                    )

                resolution, updated = resolve_promotion_journal_conn(
                    conn,
                    run=run,
                    observed_manifest_digest=observed_manifest_digest,
                    stamp=stamp,
                    finalize_ambiguous=finalize_ambiguous,
                )
                result = {
                    "resolution": resolution,
                    "run": self._controller_material_conn(conn, updated),
                }
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def request_cancel(
        self,
        *,
        run_id: str,
        client_action_id: str,
        operator_identity: str,
        expected_state: str,
        expected_revision: int,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if expected_state not in {
            "requested",
            "preparing",
            "staging",
            "verifying",
            "ready_to_promote",
        }:
            raise RoomExecutionStoreError("room_execution_cancel_state_invalid")
        client_action_id = _require_text(
            client_action_id, "room_execution_client_action_id_required"
        )
        operator_identity = _require_text(
            operator_identity, "room_execution_operator_identity_required"
        )
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int):
            raise RoomExecutionStoreError("room_execution_revision_invalid")
        fingerprint = _digest(
            {
                "run_id": run_id,
                "expected_state": expected_state,
                "expected_revision": expected_revision,
            }
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = conn.execute(
                    "select * from room_execution_runs where run_id = ?", (run_id,)
                ).fetchone()
                if run is None:
                    raise RoomExecutionStoreError("room_execution_run_not_found")
                action, created = self._reserve_action_conn(
                    conn,
                    conversation_id=run["conversation_id"],
                    candidate_id=run["candidate_id"],
                    action_type="run_cancel",
                    client_action_id=client_action_id,
                    operator_identity=operator_identity,
                    fingerprint=fingerprint,
                    expected_candidate_digest=None,
                    expected_candidate_revision=None,
                    expected_policy_revision=None,
                    expected_run_state=expected_state,
                    expected_run_revision=expected_revision,
                    stamp=stamp,
                )
                if not created:
                    conn.rollback()
                    return self._action_replay(action)
                if run["state"] != expected_state or int(run["revision"]) != expected_revision:
                    reason = "room_execution_run_guard_mismatch"
                    self._complete_action_conn(
                        conn,
                        action_id=action["action_id"],
                        status="rejected",
                        result={"run_id": run_id, "status": "rejected", "reason_code": reason},
                        reason_code=reason,
                        run_id=run_id,
                        stamp=stamp,
                    )
                    conn.commit()
                    raise RoomExecutionStoreError(reason)
                if run["state"] == "requested":
                    # No controller has acquired transport or target-byte authority yet.
                    # Terminal cancellation in this transaction also wins a concurrent
                    # child claim, which will observe the terminal state and exit.
                    conn.execute(
                        """update room_execution_runs
                           set control_seq = control_seq + 1, updated_at = ?
                           where run_id = ?""",
                        (stamp, run_id),
                    )
                    pending = conn.execute(
                        "select * from room_execution_runs where run_id = ?", (run_id,)
                    ).fetchone()
                    assert pending is not None
                    updated = self._finalize_run_conn(
                        conn,
                        run=pending,
                        terminal_state="cancelled",
                        reason_code="operator_cancelled_before_start",
                        changed_files=(),
                        gate_ids=(),
                        evidence_digest=None,
                        stamp=stamp,
                    )
                    change = "execution.cancelled"
                else:
                    conn.execute(
                        """update room_execution_runs set state = 'cancel_requested',
                           revision = revision + 1, control_seq = control_seq + 1,
                           reason_code = 'operator_cancel_requested', updated_at = ?
                           where run_id = ?""",
                        (stamp, run_id),
                    )
                    updated = conn.execute(
                        "select * from room_execution_runs where run_id = ?", (run_id,)
                    ).fetchone()
                    assert updated is not None
                    change = "execution.cancel_requested"
                result = _run_view_conn(conn, updated)
                self._complete_action_conn(
                    conn,
                    action_id=action["action_id"],
                    status="applied",
                    result=result,
                    reason_code=None,
                    run_id=run_id,
                    stamp=stamp,
                )
                self._record_event_conn(
                    conn,
                    conversation_id=run["conversation_id"],
                    event_type="projection.changed",
                    resource_ref=f"room:execution-run:{run_id}",
                    source_ref=f"room:execution-run:{run_id}",
                    payload={"change": change, "run_id": run_id},
                    client_action_id=client_action_id,
                    stamp=stamp,
                )
                conn.commit()
                return result
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise

    @staticmethod
    def _insert_terminal_activity_conn(
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

    @classmethod
    def _finalize_run_conn(
        cls,
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
        activity_id = cls._insert_terminal_activity_conn(
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
        cls._record_event_conn(
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

    def acknowledge_cancel(
        self,
        *,
        run_id: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        transport_stopped: bool,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if not isinstance(transport_stopped, bool):
            raise RoomExecutionStoreError("room_execution_cancel_transport_state_invalid")
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                row = conn.execute(
                    "select * from room_execution_runs where run_id = ?", (run_id,)
                ).fetchone()
                if row is None or row["state"] not in {"cancel_requested", "cancel_pending"}:
                    raise RoomExecutionStoreError("room_execution_cancel_guard_mismatch")
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=str(row["state"]),
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                if transport_stopped:
                    updated = self._finalize_run_conn(
                        conn,
                        run=run,
                        terminal_state="cancelled",
                        reason_code="operator_cancelled",
                        changed_files=(),
                        gate_ids=(),
                        evidence_digest=None,
                        stamp=stamp,
                    )
                else:
                    if run["state"] != "cancel_requested":
                        raise RoomExecutionStoreError("room_execution_cancel_cleanup_pending")
                    conn.execute(
                        """update room_execution_runs set state = 'cancel_pending',
                           revision = revision + 1, reason_code = 'cancel_cleanup_pending',
                           updated_at = ? where run_id = ?""",
                        (stamp, run_id),
                    )
                    updated = conn.execute(
                        "select * from room_execution_runs where run_id = ?", (run_id,)
                    ).fetchone()
                    assert updated is not None
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise

    def finalize_run(
        self,
        *,
        run_id: str,
        expected_state: str,
        expected_revision: int,
        execution_generation: int,
        controller_id: str,
        controller_generation: str,
        controller_pid: int,
        controller_start_identity: str,
        terminal_state: Literal["succeeded", "failed", "blocked", "cancelled"],
        reason_code: str,
        changed_files: Sequence[str] = (),
        gate_ids: Sequence[str] = (),
        evidence_digest: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if terminal_state not in TERMINAL_RUN_STATES or terminal_state == "cancelled":
            raise RoomExecutionStoreError("room_execution_run_terminal_state_invalid")
        identity = self._controller_identity(
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
        )
        reason_code = _require_text(reason_code, "room_execution_run_reason_required", maximum=128)
        clean_changed = tuple(canonical_execution_path(item) for item in changed_files)
        if len(clean_changed) != len(set(clean_changed)):
            raise RoomExecutionStoreError("room_execution_changed_files_invalid")
        clean_gates = tuple(
            _require_text(item, "room_execution_gate_id_invalid", maximum=128) for item in gate_ids
        )
        if len(clean_gates) != len(set(clean_gates)):
            raise RoomExecutionStoreError("room_execution_gate_ids_invalid")
        if evidence_digest is not None:
            evidence_digest = _require_digest(
                evidence_digest, "room_execution_evidence_digest_invalid"
            )
        stamp = _timestamp(now)
        with self._database.connect() as conn:
            conn.execute("begin immediate")
            try:
                run = self._bound_run_conn(
                    conn,
                    run_id=run_id,
                    expected_state=expected_state,
                    expected_revision=expected_revision,
                    execution_generation=execution_generation,
                    identity=identity,
                )
                gate_plan = _required_gate_plan_for_run_conn(conn, run)
                if clean_gates != gate_plan.gate_ids[: len(clean_gates)]:
                    raise RoomExecutionStoreError("room_execution_gate_ids_invalid")
                if terminal_state not in _RUN_TRANSITIONS.get(expected_state, frozenset()):
                    raise RoomExecutionStoreError("room_execution_run_transition_invalid")
                candidate = conn.execute(
                    "select * from room_execution_candidates where candidate_id = ?",
                    (run["candidate_id"],),
                ).fetchone()
                if candidate is None:
                    raise RoomExecutionStoreError("room_execution_run_authority_corrupt")
                allowed = set(_decode(candidate["allowed_files_json"], []))
                if terminal_state == "succeeded":
                    journal = conn.execute(
                        "select * from room_execution_promotion_journal where run_id = ?",
                        (run_id,),
                    ).fetchone()
                    if (
                        expected_state != "promoting"
                        or journal is None
                        or journal["status"] != "applied"
                        or set(clean_changed) != allowed
                        or clean_gates != gate_plan.gate_ids
                    ):
                        raise RoomExecutionStoreError("room_execution_promotion_not_proven")
                elif clean_changed:
                    raise RoomExecutionStoreError("room_execution_changed_files_invalid")
                known_gates = {
                    str(row["gate_id"])
                    for row in conn.execute(
                        "select gate_id from room_execution_gate_evidence where run_id = ?",
                        (run_id,),
                    )
                }
                if not set(clean_gates).issubset(known_gates):
                    raise RoomExecutionStoreError("room_execution_gate_ids_invalid")
                updated = self._finalize_run_conn(
                    conn,
                    run=run,
                    terminal_state=terminal_state,
                    reason_code=reason_code,
                    changed_files=clean_changed,
                    gate_ids=clean_gates,
                    evidence_digest=evidence_digest,
                    stamp=stamp,
                )
                result = self._controller_material_conn(conn, updated)
                conn.commit()
                return result
            except Exception:
                conn.rollback()
                raise


class RoomExecutionStore(_ExecutionLedger):
    """Compatibility facade for legacy in-process callers.

    New production composition must receive one of the controller, runtime,
    operator, read, or review capability stores instead.
    """
