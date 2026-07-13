from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.test_room_execution_gate_plan_ledger import _authorize
from xmuse_core.chat import room_execution_store as execution_store_module
from xmuse_core.chat.room_execution_store import RoomExecutionStore


def _authority_snapshot(path: Path) -> tuple[object, ...]:
    with sqlite3.connect(path) as conn:
        candidate = conn.execute(
            "select state, revision, authorized_at, rejected_at from room_execution_candidates"
        ).fetchall()
        counts = tuple(
            int(conn.execute(f"select count(*) from {table}").fetchone()[0])
            for table in (
                "room_execution_operator_actions",
                "room_execution_authorizations",
                "room_execution_runs",
                "room_execution_gate_plan_bindings",
                "chat_frontend_events",
            )
        )
    return candidate, counts


@pytest.mark.parametrize(
    "stage",
    [
        "reserve_execution_action_conn",
        "authorize_execution_conn",
        "complete_execution_action_conn",
        "projection_event",
    ],
)
def test_manual_execution_decision_rolls_back_every_durable_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    stage: str,
) -> None:
    db, _conversation_id, execution, _candidate, plan, kwargs = _authorize(tmp_path)
    before = _authority_snapshot(db)

    if stage == "projection_event":
        original = RoomExecutionStore._record_event_conn

        def fail_after_event(*args: Any, **values: Any) -> None:
            original(*args, **values)
            raise RuntimeError("injected_execution_stage_failure")

        monkeypatch.setattr(
            RoomExecutionStore,
            "_record_event_conn",
            staticmethod(fail_after_event),
        )
    else:
        original = getattr(execution_store_module, stage)

        def fail_after_write(*args: Any, **values: Any) -> None:
            original(*args, **values)
            raise RuntimeError("injected_execution_stage_failure")

        monkeypatch.setattr(execution_store_module, stage, fail_after_write)

    with pytest.raises(RuntimeError, match="injected_execution_stage_failure"):
        execution.apply_operator_decision(**kwargs, gate_plan=plan)

    assert _authority_snapshot(db) == before
