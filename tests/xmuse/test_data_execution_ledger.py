from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.xmuse.test_room_execution_outcomes import (
    DIGEST,
    PATH,
    make_candidate,
    trusted_gate_plan,
)
from xmuse import data_cli, data_restore
from xmuse.data_authority import authority_invariants
from xmuse.data_inspection import readonly_connection
from xmuse_core.chat.room_execution_contracts import ExecutionWorkspaceGuard

CONTROLLER = {
    "controller_id": "controller",
    "controller_generation": "boot-1",
    "controller_pid": 4242,
    "controller_start_identity": "proc-start-1",
}
POST_DIGEST = "sha256:" + "2" * 64


def _authorized_run(path: Path):
    db, _registry, _conversation_id, _records, _claims, result, execution = make_candidate(path)
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None
    authorized = execution.apply_operator_decision(
        candidate_id=candidate["candidate_id"],
        decision="execute",
        client_action_id="execute",
        operator_identity="operator",
        expected_candidate_digest=candidate["candidate_digest"],
        expected_candidate_revision=candidate["revision"],
        expected_policy_revision=0,
        workspace_guard=ExecutionWorkspaceGuard("a" * 40, True, DIGEST, frozenset({PATH})),
        gate_plan=trusted_gate_plan(),
    )
    return db, execution, authorized["run"]["run_id"]


def _move_to(execution, run_id: str, state: str) -> None:
    if state == "requested":
        return
    current = execution.claim_requested_run(run_id=run_id, **CONTROLLER)
    if state == "preparing":
        return
    for target in ("staging", "verifying"):
        current = execution.advance_run(
            run_id=run_id,
            expected_state=current["state"],
            expected_revision=current["revision"],
            execution_generation=current["execution_generation"],
            target_state=target,
            **CONTROLLER,
        )
        if state == target:
            return
    current = execution.advance_run(
        run_id=run_id,
        expected_state="verifying",
        expected_revision=current["revision"],
        execution_generation=current["execution_generation"],
        target_state="ready_to_promote",
        **CONTROLLER,
    )
    current = execution.prepare_promotion(
        run_id=run_id,
        expected_revision=current["revision"],
        execution_generation=current["execution_generation"],
        target_head="a" * 40,
        pre_manifest_digest=DIGEST,
        post_manifest_digest=POST_DIGEST,
        file_entries=[{"path": PATH, "pre_sha256": DIGEST, "post_sha256": POST_DIGEST}],
        **CONTROLLER,
    )
    if state == "applying":
        execution.mark_promotion_applying(
            run_id=run_id,
            expected_revision=current["revision"],
            execution_generation=current["execution_generation"],
            **CONTROLLER,
        )


@pytest.mark.parametrize(
    ("state", "reason", "promotion_count"),
    [
        ("requested", "room_execution_restore_reauthorization_required", 0),
        ("preparing", "room_execution_restore_reauthorization_required", 0),
        ("verifying", "room_execution_restore_reauthorization_required", 0),
        ("promoting", "room_execution_promotion_unverifiable", 1),
        ("applying", "room_execution_promotion_unverifiable", 1),
    ],
)
def test_restore_fences_nonterminal_execution_authority(
    tmp_path: Path, state: str, reason: str, promotion_count: int
) -> None:
    db, execution, run_id = _authorized_run(tmp_path)
    _move_to(execution, run_id, state)

    result = data_restore.fence_restored_execution_runs(db, operation_id="restore-test")

    assert result == {"blocked": 1, "promotion_unverifiable": promotion_count}
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        run = conn.execute(
            "select * from room_execution_runs where run_id = ?", (run_id,)
        ).fetchone()
        authorization = conn.execute(
            """select z.* from room_execution_authorizations z
               join room_execution_runs r on r.authorization_id = z.authorization_id
               where r.run_id = ?""",
            (run_id,),
        ).fetchone()
    assert run is not None and authorization is not None
    assert (run["state"], run["reason_code"]) == ("blocked", reason)
    assert run["controller_id"] is None
    assert run["controller_generation"] is None
    assert run["controller_pid"] is None
    assert run["controller_start_identity"] is None
    assert (authorization["status"], authorization["reason_code"]) == (
        "invalidated",
        reason,
    )


@pytest.mark.parametrize("state", ["cancelled", "succeeded", "failed", "blocked"])
def test_restore_leaves_terminal_execution_rows_unchanged(tmp_path: Path, state: str) -> None:
    db, _execution, run_id = _authorized_run(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            "update room_execution_runs set state = ?, reason_code = 'existing-terminal' "
            "where run_id = ?",
            (state, run_id),
        )
        before = conn.execute(
            "select * from room_execution_runs where run_id = ?", (run_id,)
        ).fetchone()
        authorization_before = conn.execute(
            """select z.* from room_execution_authorizations z
               join room_execution_runs r on r.authorization_id = z.authorization_id
               where r.run_id = ?""",
            (run_id,),
        ).fetchone()

    assert data_restore.fence_restored_execution_runs(db, operation_id="restore-terminal") == {
        "blocked": 0,
        "promotion_unverifiable": 0,
    }

    with sqlite3.connect(db) as conn:
        after = conn.execute(
            "select * from room_execution_runs where run_id = ?", (run_id,)
        ).fetchone()
        authorization_after = conn.execute(
            """select z.* from room_execution_authorizations z
               join room_execution_runs r on r.authorization_id = z.authorization_id
               where r.run_id = ?""",
            (run_id,),
        ).fetchone()
    assert after == before
    assert authorization_after == authorization_before


def test_data_authority_accepts_ledger_and_rejects_broken_authorization_binding(
    tmp_path: Path,
) -> None:
    db, _execution, run_id = _authorized_run(tmp_path)
    with readonly_connection(db) as conn:
        valid = authority_invariants(conn)
    assert valid["valid"] is True
    assert valid["execution_binding_mismatch_count"] == 0
    assert valid["execution_run_mismatch_count"] == 0

    with sqlite3.connect(db) as conn:
        conn.execute(
            """update room_execution_authorizations set candidate_digest = ?
               where authorization_id = (
                 select authorization_id from room_execution_runs where run_id = ?
               )""",
            (POST_DIGEST, run_id),
        )
    with readonly_connection(db) as conn:
        broken = authority_invariants(conn)
    assert broken["valid"] is False
    assert broken["execution_run_mismatch_count"] == 1


def test_backup_restore_preserves_the_private_gate_plan_binding(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    db, _execution, run_id = _authorized_run(source)
    with sqlite3.connect(db) as conn:
        before = conn.execute(
            "select * from room_execution_gate_plan_bindings where run_id = ?",
            (run_id,),
        ).fetchone()
    assert before is not None
    (source / data_cli.SESSION_NAME).unlink()

    backup = tmp_path / "backup"
    data_cli.backup_data(source, backup)
    target = tmp_path / "target"
    data_cli.restore_data(target, backup, replace=False)

    with sqlite3.connect(target / data_cli.CHAT_DB_NAME) as conn:
        restored = conn.execute(
            "select * from room_execution_gate_plan_bindings where run_id = ?",
            (run_id,),
        ).fetchone()
        run = conn.execute(
            "select state, reason_code from room_execution_runs where run_id = ?",
            (run_id,),
        ).fetchone()
    assert restored == before
    assert run == ("blocked", "room_execution_restore_reauthorization_required")


@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("profile_digest", POST_DIGEST),
        ("profile_id", "docs/v1"),
        (
            "gate_ids_json",
            '["backend_pytest","backend_mypy","backend_ruff","patch_diff_check"]',
        ),
    ],
)
def test_doctor_blocks_tampered_gate_profile_authority(
    tmp_path: Path,
    column: str,
    value: str,
) -> None:
    root = tmp_path / "root"
    root.mkdir()
    db, _execution, run_id = _authorized_run(root)
    (root / data_cli.SESSION_NAME).unlink()
    statements = {
        "profile_digest": (
            "update room_execution_gate_plan_bindings set profile_digest = ? where run_id = ?"
        ),
        "profile_id": (
            "update room_execution_gate_plan_bindings set profile_id = ? where run_id = ?"
        ),
        "gate_ids_json": (
            "update room_execution_gate_plan_bindings set gate_ids_json = ? where run_id = ?"
        ),
    }
    with sqlite3.connect(db) as conn:
        conn.execute(statements[column], (value, run_id))

    status, report = data_cli.doctor_data(root)

    assert status == 1
    chat_db = next(item for item in report["checks"] if item["name"] == "chat_db")
    assert chat_db["status"] == "blocker"
    assert chat_db["detail"]["code"] == "chat_db_corrupt"
