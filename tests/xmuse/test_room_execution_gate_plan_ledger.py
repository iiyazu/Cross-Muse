from __future__ import annotations

import json
import sqlite3

import pytest

from tests.xmuse.test_room_execution_outcomes import (
    DIGEST,
    PATH,
    make_candidate,
    trusted_gate_plan,
)
from xmuse_core.chat.room_execution_contracts import ExecutionWorkspaceGuard
from xmuse_core.chat.room_execution_profiles import build_execution_gate_plan
from xmuse_core.chat.room_execution_store import (
    RoomExecutionStoreError,
    create_room_execution_schema,
)

CONTROLLER = {
    "controller_id": "controller",
    "controller_generation": "boot-1",
    "controller_pid": 4242,
    "controller_start_identity": "proc-start-1",
}
POST_DIGEST = "sha256:" + "2" * 64


def _authorize(tmp_path):
    db, _registry, conversation_id, _records, _claims, result, execution = make_candidate(tmp_path)
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None
    plan = trusted_gate_plan()
    kwargs = {
        "candidate_id": candidate["candidate_id"],
        "decision": "execute",
        "client_action_id": "execute-profile",
        "operator_identity": "operator",
        "expected_candidate_digest": candidate["candidate_digest"],
        "expected_candidate_revision": candidate["revision"],
        "expected_policy_revision": 0,
        "workspace_guard": ExecutionWorkspaceGuard(
            "a" * 40,
            True,
            DIGEST,
            frozenset({PATH}),
        ),
    }
    return db, conversation_id, execution, candidate, plan, kwargs


def _ready_to_promote(execution, run_id: str):
    current = execution.claim_requested_run(run_id=run_id, **CONTROLLER)
    for target in ("staging", "verifying", "ready_to_promote"):
        current = execution.advance_run(
            run_id=run_id,
            expected_state=current["state"],
            expected_revision=current["revision"],
            execution_generation=current["execution_generation"],
            target_state=target,
            **CONTROLLER,
        )
    return current


def _prepare(execution, current):
    return execution.prepare_promotion(
        run_id=current["run_id"],
        expected_revision=current["revision"],
        execution_generation=current["execution_generation"],
        target_head="a" * 40,
        pre_manifest_digest=DIGEST,
        post_manifest_digest=POST_DIGEST,
        file_entries=[
            {
                "path": PATH,
                "pre_sha256": DIGEST,
                "post_sha256": POST_DIGEST,
            }
        ],
        **CONTROLLER,
    )


def test_manual_execute_requires_and_durably_freezes_complete_trusted_plan(tmp_path) -> None:
    db, _conversation_id, execution, candidate, plan, kwargs = _authorize(tmp_path)

    with pytest.raises(RoomExecutionStoreError) as missing:
        execution.apply_operator_decision(**kwargs)
    assert missing.value.code == "room_execution_gate_plan_required"

    result = execution.apply_operator_decision(**kwargs, gate_plan=plan)
    run_id = result["run"]["run_id"]
    assert result["run"]["gate_profile"] == plan.safe_reference()
    assert result["run"]["gate_ids"] == list(plan.gate_ids)
    public = execution.get_candidate(candidate["candidate_id"])
    assert public is not None
    encoded = json.dumps({"run": result["run"], "candidate": public})
    assert "repository_manifest_digest" not in encoded
    assert "toolchain_capability_digest" not in encoded
    assert "gate_plan_digest" not in encoded

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        binding = conn.execute(
            "select * from room_execution_gate_plan_bindings where run_id = ?",
            (run_id,),
        ).fetchone()
    assert binding is not None
    assert binding["gate_plan_digest"] == plan.gate_plan_digest
    assert json.loads(binding["gate_ids_json"]) == list(plan.gate_ids)

    claimed = execution.claim_requested_run(
        run_id=run_id,
        controller_id="controller",
        controller_generation="boot-1",
        controller_pid=4242,
        controller_start_identity="proc-start-1",
    )
    assert claimed["gate_plan"] == plan.internal_mapping()


def test_replayed_authorization_returns_original_run_despite_toolchain_drift(tmp_path) -> None:
    _db, _conversation_id, execution, _candidate, plan, kwargs = _authorize(tmp_path)
    first = execution.apply_operator_decision(**kwargs, gate_plan=plan)
    changed = build_execution_gate_plan(
        profile_id=plan.profile_id,
        changed_paths=(PATH,),
        repository_manifest_digest=plan.repository_manifest_digest,
        toolchain_capability_digest="sha256:" + "2" * 64,
    )

    replay = execution.apply_operator_decision(**kwargs, gate_plan=changed)
    assert replay == first


def test_readonly_operator_replay_is_exact_and_never_reserves_an_action(tmp_path) -> None:
    db, _conversation_id, execution, _candidate, plan, kwargs = _authorize(tmp_path)
    replay_kwargs = {
        key: kwargs[key]
        for key in (
            "candidate_id",
            "decision",
            "client_action_id",
            "operator_identity",
            "expected_candidate_digest",
            "expected_candidate_revision",
            "expected_policy_revision",
        )
    }

    assert execution.replay_operator_decision(**replay_kwargs) is None
    with sqlite3.connect(db) as conn:
        before = conn.execute("select count(*) from room_execution_operator_actions").fetchone()[0]
    assert before == 0

    applied = execution.apply_operator_decision(**kwargs, gate_plan=plan)
    assert execution.replay_operator_decision(**replay_kwargs) == applied
    with pytest.raises(RoomExecutionStoreError) as conflict:
        execution.replay_operator_decision(**{**replay_kwargs, "expected_candidate_revision": 999})
    assert conflict.value.code == "room_execution_action_idempotency_conflict"
    with sqlite3.connect(db) as conn:
        after = conn.execute("select count(*) from room_execution_operator_actions").fetchone()[0]
    assert after == 1


def test_policy_update_winning_before_prepare_durably_blocks_promotion(tmp_path) -> None:
    db, conversation_id, execution, _candidate, plan, kwargs = _authorize(tmp_path)
    run = execution.apply_operator_decision(**kwargs, gate_plan=plan)["run"]
    ready = _ready_to_promote(execution, run["run_id"])
    execution.set_policy(
        conversation_id=conversation_id,
        mode="consensus",
        client_action_id="policy-wins",
        operator_identity="operator",
        expected_revision=0,
    )

    blocked = _prepare(execution, ready)

    assert blocked["state"] == "blocked"
    assert blocked["reason_code"] == "execution_policy_guard_changed"
    with sqlite3.connect(db) as conn:
        journal_count = conn.execute(
            "select count(*) from room_execution_promotion_journal"
        ).fetchone()[0]
    assert journal_count == 0


def test_prepare_winning_before_policy_update_fences_the_update(tmp_path) -> None:
    db, conversation_id, execution, _candidate, plan, kwargs = _authorize(tmp_path)
    run = execution.apply_operator_decision(**kwargs, gate_plan=plan)["run"]
    ready = _ready_to_promote(execution, run["run_id"])

    promoting = _prepare(execution, ready)
    with pytest.raises(RoomExecutionStoreError) as raised:
        execution.set_policy(
            conversation_id=conversation_id,
            mode="consensus",
            client_action_id="promotion-wins",
            operator_identity="operator",
            expected_revision=0,
        )

    assert promoting["state"] == "promoting"
    assert raised.value.code == "room_execution_policy_promotion_conflict"
    policy = execution.get_policy(conversation_id)
    assert policy is not None
    assert policy["mode"] == "manual" and policy["revision"] == 0
    with sqlite3.connect(db) as conn:
        action_count = conn.execute(
            "select count(*) from room_execution_operator_actions"
        ).fetchone()[0]
    assert action_count == 1


@pytest.mark.parametrize(
    ("prior_state", "expected_state"),
    [
        ("requested", "blocked"),
        ("verifying", "blocked"),
        ("cancel_pending", "blocked"),
        ("succeeded", "succeeded"),
    ],
)
def test_additive_schema_fences_only_unbound_nonterminal_legacy_runs(
    tmp_path, prior_state, expected_state
) -> None:
    db, _conversation_id, execution, _candidate, plan, kwargs = _authorize(tmp_path)
    result = execution.apply_operator_decision(**kwargs, gate_plan=plan)
    run_id = result["run"]["run_id"]
    with sqlite3.connect(db) as conn:
        conn.execute("delete from room_execution_gate_plan_bindings where run_id = ?", (run_id,))
        conn.execute(
            "update room_execution_runs set state = ? where run_id = ?",
            (prior_state, run_id),
        )
        create_room_execution_schema(conn)
        row = conn.execute(
            "select state, reason_code from room_execution_runs where run_id = ?",
            (run_id,),
        ).fetchone()
        authorization = conn.execute(
            "select status, reason_code from room_execution_authorizations "
            "where authorization_id = (select authorization_id from room_execution_runs "
            "where run_id = ?)",
            (run_id,),
        ).fetchone()

    assert row is not None and row[0] == expected_state
    if expected_state == "blocked":
        assert row[1] == "execution_gate_plan_missing"
        assert authorization == ("invalidated", "execution_gate_plan_missing")
    else:
        assert authorization == ("consumed", None)
