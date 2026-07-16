"""Read-only access to durable exact-patch execution ledgers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_candidates import policy_view
from xmuse_core.chat.room_execution_views import candidate_view_conn, run_view_conn


class RoomExecutionLedgerReader:
    """Concrete projection source without operator or controller methods."""

    def __init__(self, db_path: Path | str) -> None:
        self._database = RoomDatabase(db_path)

    def get_policy(self, conversation_id: str) -> dict[str, Any] | None:
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                "select * from room_execution_policies where conversation_id = ?",
                (conversation_id,),
            ).fetchone()
        return policy_view(row) if row is not None else None

    def get_candidate(
        self, candidate_id: str, *, include_patch: bool = False
    ) -> dict[str, Any] | None:
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                "select * from room_execution_candidates where candidate_id = ?", (candidate_id,)
            ).fetchone()
            return (
                candidate_view_conn(conn, row, include_patch=include_patch)
                if row is not None
                else None
            )

    def list_conversation_candidates(
        self, conversation_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                "select * from room_execution_candidates where conversation_id = ? "
                "order by created_at desc, candidate_id desc limit ?",
                (conversation_id, clean_limit),
            ).fetchall()
            return [candidate_view_conn(conn, row, include_patch=False) for row in rows]

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._database.connect(readonly=True) as conn:
            row = conn.execute(
                "select * from room_execution_runs where run_id = ?", (run_id,)
            ).fetchone()
            return run_view_conn(conn, row) if row is not None else None

    def list_conversation_runs(
        self, conversation_id: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        clean_limit = max(1, min(int(limit), 100))
        with self._database.connect(readonly=True) as conn:
            rows = conn.execute(
                "select * from room_execution_runs where conversation_id = ? "
                "order by requested_at desc, run_id desc limit ?",
                (conversation_id, clean_limit),
            ).fetchall()
            return [run_view_conn(conn, row) for row in rows]
