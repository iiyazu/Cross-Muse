"""Controller-only capability adapter for the exact-patch execution ledger."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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

    def claim_requested_run(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.claim_requested_run(**kwargs)

    def reclaim_run_controller(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.reclaim_run_controller(**kwargs)

    def get_controller_material(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.get_controller_material(**kwargs)

    def advance_run(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.advance_run(**kwargs)

    def record_gate_evidence(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.record_gate_evidence(**kwargs)

    def prepare_promotion(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.prepare_promotion(**kwargs)

    def mark_promotion_applying(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.mark_promotion_applying(**kwargs)

    def resolve_promotion(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.resolve_promotion(**kwargs)

    def acknowledge_cancel(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.acknowledge_cancel(**kwargs)

    def finalize_run(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.finalize_run(**kwargs)
