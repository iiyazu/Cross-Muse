"""Reconciler-only capability adapter for exact-patch execution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from xmuse_core.chat.room_execution_contracts import (
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
)
from xmuse_core.chat.room_execution_profiles import ExecutionGatePlan
from xmuse_core.chat.room_execution_store import RoomExecutionStore


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
        self._ledger = RoomExecutionStore(db_path)

    def get_candidate(
        self, candidate_id: str, *, include_patch: bool = False
    ) -> dict[str, Any] | None:
        return self._ledger.get_candidate(candidate_id, include_patch=include_patch)

    def list_endorsed_candidate_ids(self, *, limit: int = 20) -> list[str]:
        return self._ledger.list_endorsed_candidate_ids(limit=limit)

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
        return self._ledger.reconcile_consensus_candidate(
            candidate_id=candidate_id,
            kill_switch_enabled=kill_switch_enabled,
            workspace_guard=workspace_guard,
            risk_evaluation=risk_evaluation,
            gate_plan=gate_plan,
            now=now,
        )

    def list_controller_recovery(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._ledger.list_controller_recovery(limit=limit)


def _execution_runtime_store_protocol_proof(
    store: RoomExecutionRuntimeStore,
) -> ExecutionRuntimeStore:
    """Keep the adapter structurally aligned with the reconciler's narrow port."""

    return store
