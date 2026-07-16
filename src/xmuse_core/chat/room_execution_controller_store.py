"""Controller-only capability adapter for the exact-patch execution ledger."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from xmuse_core.chat.room_execution_controller import ExecutionStore
from xmuse_core.chat.room_execution_store import RoomExecutionStore


class RoomExecutionControllerStore:
    """Expose only the durable operations required by a one-shot controller."""

    def __init__(self, db_path: Path | str) -> None:
        self._ledger = RoomExecutionStore(db_path)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        return self._ledger.get_run(run_id)

    def get_policy(self, conversation_id: str) -> dict[str, Any] | None:
        return self._ledger.get_policy(conversation_id)

    def list_controller_recovery(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._ledger.list_controller_recovery(limit=limit)

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
        return self._ledger.claim_requested_run(
            run_id=run_id,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            now=now,
        )

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
        return self._ledger.reclaim_run_controller(
            run_id=run_id,
            expected_state=expected_state,
            expected_revision=expected_revision,
            expected_execution_generation=expected_execution_generation,
            prior_controller_id=prior_controller_id,
            prior_controller_generation=prior_controller_generation,
            prior_controller_pid=prior_controller_pid,
            prior_controller_start_identity=prior_controller_start_identity,
            confirmed_dead=confirmed_dead,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            now=now,
        )

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
        return self._ledger.get_controller_material(
            run_id=run_id,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            execution_generation=execution_generation,
        )

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
        return self._ledger.advance_run(
            run_id=run_id,
            expected_state=expected_state,
            expected_revision=expected_revision,
            execution_generation=execution_generation,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            target_state=target_state,
            reason_code=reason_code,
            now=now,
        )

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
        return self._ledger.record_gate_evidence(
            run_id=run_id,
            expected_run_state=expected_run_state,
            expected_run_revision=expected_run_revision,
            execution_generation=execution_generation,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            gate_id=gate_id,
            status=status,
            evidence_digest=evidence_digest,
            started_at=started_at,
            finished_at=finished_at,
            reason_code=reason_code,
            now=now,
        )

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
        return self._ledger.prepare_promotion(
            run_id=run_id,
            expected_revision=expected_revision,
            execution_generation=execution_generation,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            target_head=target_head,
            pre_manifest_digest=pre_manifest_digest,
            post_manifest_digest=post_manifest_digest,
            file_entries=file_entries,
            now=now,
        )

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
        return self._ledger.mark_promotion_applying(
            run_id=run_id,
            expected_revision=expected_revision,
            execution_generation=execution_generation,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            now=now,
        )

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
        return self._ledger.resolve_promotion(
            run_id=run_id,
            expected_revision=expected_revision,
            execution_generation=execution_generation,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            observed_manifest_digest=observed_manifest_digest,
            now=now,
        )

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
        return self._ledger.acknowledge_cancel(
            run_id=run_id,
            expected_revision=expected_revision,
            execution_generation=execution_generation,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            transport_stopped=transport_stopped,
            now=now,
        )

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
        return self._ledger.finalize_run(
            run_id=run_id,
            expected_state=expected_state,
            expected_revision=expected_revision,
            execution_generation=execution_generation,
            controller_id=controller_id,
            controller_generation=controller_generation,
            controller_pid=controller_pid,
            controller_start_identity=controller_start_identity,
            terminal_state=terminal_state,
            reason_code=reason_code,
            changed_files=changed_files,
            gate_ids=gate_ids,
            evidence_digest=evidence_digest,
            now=now,
        )


def _execution_store_protocol_proof(store: RoomExecutionControllerStore) -> ExecutionStore:
    """Keep the adapter structurally aligned with the controller's narrow port."""

    return store
