"""Operator-only capability adapter for exact-patch execution actions."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_execution_contracts import (
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
)
from xmuse_core.chat.room_execution_profiles import ExecutionGatePlan
from xmuse_core.chat.room_execution_store import RoomExecutionStore


class RoomExecutionOperatorStore:
    """Expose fixed operator commands without controller lifecycle methods."""

    def __init__(self, db_path: Path | str) -> None:
        self._ledger = RoomExecutionStore(db_path)

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
        return self._ledger.set_policy(
            conversation_id=conversation_id,
            mode=mode,
            client_action_id=client_action_id,
            operator_identity=operator_identity,
            expected_revision=expected_revision,
            now=now,
        )

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
        return self._ledger.replay_operator_decision(
            candidate_id=candidate_id,
            decision=decision,
            client_action_id=client_action_id,
            operator_identity=operator_identity,
            expected_candidate_digest=expected_candidate_digest,
            expected_candidate_revision=expected_candidate_revision,
            expected_policy_revision=expected_policy_revision,
        )

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
        workspace_guard: ExecutionWorkspaceGuard | None,
        risk_evaluation: ExecutionRiskEvaluation | None,
        gate_plan: ExecutionGatePlan | None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        return self._ledger.apply_operator_decision(
            candidate_id=candidate_id,
            decision=decision,
            client_action_id=client_action_id,
            operator_identity=operator_identity,
            expected_candidate_digest=expected_candidate_digest,
            expected_candidate_revision=expected_candidate_revision,
            expected_policy_revision=expected_policy_revision,
            workspace_guard=workspace_guard,
            risk_evaluation=risk_evaluation,
            gate_plan=gate_plan,
            now=now,
        )

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
        return self._ledger.request_cancel(
            run_id=run_id,
            client_action_id=client_action_id,
            operator_identity=operator_identity,
            expected_state=expected_state,
            expected_revision=expected_revision,
            now=now,
        )
