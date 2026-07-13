from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_actions import (
    complete_execution_action_conn,
    reserve_execution_action_conn,
)
from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_runs import controller_identity, validate_gate_evidence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LEAVES = (
    PROJECT_ROOT / "src/xmuse_core/chat/room_execution_actions.py",
    PROJECT_ROOT / "src/xmuse_core/chat/room_execution_runs.py",
)
DIGEST = "sha256:" + "1" * 64


def test_execution_action_run_leaves_do_not_own_connections_or_transactions() -> None:
    forbidden_imports = {
        "xmuse_core.chat.room_database",
        "xmuse_core.chat.room_execution_store",
        "xmuse_core.chat.room_execution_controller",
    }
    for path in LEAVES:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imports = {
            node.module
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        calls = {
            node.func.attr
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        assert not imports & forbidden_imports
        assert not calls & {"connect", "commit", "rollback", "close"}
        assert "begin immediate" not in source.lower()


def test_action_primitives_share_the_caller_rollback_boundary(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db).create_conversation("action leaf").id
    with RoomDatabase(db).connect() as conn:
        conn.execute("begin immediate")
        action, created = reserve_execution_action_conn(
            conn,
            conversation_id=conversation_id,
            candidate_id=None,
            action_type="policy_update",
            client_action_id="action-1",
            operator_identity="operator",
            fingerprint=DIGEST,
            expected_candidate_digest=None,
            expected_candidate_revision=None,
            expected_policy_revision=0,
            expected_run_state=None,
            expected_run_revision=None,
            stamp="2026-07-13T01:02:03.456789Z",
        )
        assert created and action["status"] == "requested" and conn.in_transaction
        complete_execution_action_conn(
            conn,
            action_id=action["action_id"],
            status="applied",
            result={"revision": 1},
            reason_code=None,
            run_id=None,
            stamp="2026-07-13T01:02:03.456789Z",
        )
        conn.rollback()
    with RoomDatabase(db).connect(readonly=True) as conn:
        assert (
            conn.execute("select count(*) from room_execution_operator_actions").fetchone()[0] == 0
        )


def test_controller_and_gate_validation_preserve_stable_guards() -> None:
    assert controller_identity(
        controller_id="controller",
        controller_generation="generation",
        controller_pid=123,
        controller_start_identity="start",
    ) == ("controller", "generation", 123, "start")
    with pytest.raises(RoomExecutionStoreError) as invalid_pid:
        controller_identity(
            controller_id="controller",
            controller_generation="generation",
            controller_pid=0,
            controller_start_identity="start",
        )
    assert invalid_pid.value.code == "room_execution_controller_pid_invalid"
    assert validate_gate_evidence(
        gate_id="backend-tests",
        status="running",
        evidence_digest=DIGEST,
        started_at="2026-07-13T01:02:03Z",
        finished_at=None,
    ) == ("backend-tests", DIGEST, "2026-07-13T01:02:03Z", None)
    with pytest.raises(RoomExecutionStoreError) as invalid_time:
        validate_gate_evidence(
            gate_id="backend-tests",
            status="passed",
            evidence_digest=DIGEST,
            started_at="2026-07-13T01:02:03Z",
            finished_at=None,
        )
    assert invalid_time.value.code == "room_execution_gate_time_invalid"
