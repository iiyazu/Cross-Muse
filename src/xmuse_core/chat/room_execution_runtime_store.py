"""Reconciler-only capability adapter for exact-patch execution."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xmuse_core.chat.room_execution_store import RoomExecutionStore


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

    def reconcile_consensus_candidate(self, **kwargs: Any) -> dict[str, Any]:
        return self._ledger.reconcile_consensus_candidate(**kwargs)

    def list_controller_recovery(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return self._ledger.list_controller_recovery(limit=limit)
