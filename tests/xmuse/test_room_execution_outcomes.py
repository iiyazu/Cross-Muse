from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from tests.xmuse.execution_store_testkit import TestExecutionStore
from tests.xmuse.test_room_participant_outcomes import root_and_claims, submit
from xmuse_core.chat.room_errors import RoomApplicationError
from xmuse_core.chat.room_execution_candidates import record_proposal_assessments_conn
from xmuse_core.chat.room_execution_common import RoomExecutionStoreError
from xmuse_core.chat.room_execution_contracts import (
    EXECUTION_RISK_POLICY_REVISION,
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
    ProposalAssessment,
)
from xmuse_core.chat.room_execution_profiles import build_execution_gate_plan
from xmuse_core.chat.room_kernel import RoomKernelStore

PATH = "src/xmuse_core/example.py"
PATCH = (
    f"diff --git a/{PATH} b/{PATH}\n"
    "index 1111111..2222222 100644\n"
    f"--- a/{PATH}\n+++ b/{PATH}\n"
    "@@ -1 +1 @@\n-old\n+new\n"
)
DIGEST = "sha256:" + "1" * 64


def trusted_gate_plan():
    return build_execution_gate_plan(
        profile_id="xmuse-monorepo/v2",
        changed_paths=(PATH,),
        repository_manifest_digest=DIGEST,
        toolchain_capability_digest=DIGEST,
    )


def patch_outcome() -> dict[str, object]:
    return {
        "proposal_type": "execution_patch",
        "content": "raw content must be replaced",
        "references": [],
        "execution_patch": {
            "schema_version": "room_execution_patch/v1",
            "base_head": "a" * 40,
            "summary": "Change the example",
            "unified_diff": PATCH,
            "allowed_files": [PATH],
        },
    }


def make_candidate(tmp_path: Path, *, consensus: bool = False):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    execution = TestExecutionStore(db)
    if consensus:
        execution.set_policy(
            conversation_id=conversation_id,
            mode="consensus",
            client_action_id="policy",
            operator_identity="operator",
            expected_revision=0,
        )
    author, reviewer, third = records
    result = submit(
        db,
        registry,
        conversation_id,
        author[0],
        author[1],
        claims[author[0].participant_id],
        "candidate",
        outcome_type="propose",
        outcome_payload=patch_outcome(),
    )
    return db, registry, conversation_id, records, claims, result, execution


def bind_review(execution, candidate_result, claim, participant_id):
    candidate = candidate_result["execution_candidate"]
    material = execution.get_review_material_for_batch(
        candidate_id=candidate["candidate_id"],
        proposal_activity_id=candidate_result["produced_activity"]["activity_id"],
        observation_batch_id=claim["batch"]["batch_id"],
        participant_id=participant_id,
        attempt_id=claim["attempt"]["attempt_id"],
    )
    material_digest = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    execution.bind_review_material_receipt(
        candidate_id=candidate["candidate_id"],
        proposal_activity_id=candidate_result["produced_activity"]["activity_id"],
        observation_batch_id=claim["batch"]["batch_id"],
        participant_id=participant_id,
        attempt_id=claim["attempt"]["attempt_id"],
        review_material_digest=material_digest,
        context_payload_sha256=DIGEST,
    )


def finish_roots_and_vote(
    db,
    registry,
    conversation_id,
    records,
    claims,
    result,
    execution,
    assessments,
):
    peers = records[1:]
    for index, pair in enumerate(peers):
        submit(
            db,
            registry,
            conversation_id,
            pair[0],
            pair[1],
            claims[pair[0].participant_id],
            f"root-{index}",
            outcome_type="noop",
            outcome_payload={},
        )
    for index, (pair, assessment) in enumerate(zip(peers, assessments, strict=False)):
        claim = RoomKernelStore(db).claim_next_observation(
            conversation_id=conversation_id,
            participant_id=pair[0].participant_id,
            lease_owner=f"peer-{index}",
        )
        assert claim is not None
        bind_review(execution, result, claim, pair[0].participant_id)
        submit(
            db,
            registry,
            conversation_id,
            pair[0],
            pair[1],
            claim,
            f"vote-{index}",
            outcome_type="noop",
            outcome_payload={},
            proposal_assessments=[
                {
                    "proposal_id": result["produced_proposal"]["id"],
                    "candidate_digest": result["execution_candidate"]["candidate_digest"],
                    "assessment": assessment,
                    "rationale": "reviewed exact material",
                }
            ],
        )


def test_candidate_is_atomic_replayable_and_raw_diff_has_one_storage_location(tmp_path):
    db, registry, conversation_id, records, claims, result, execution = make_candidate(tmp_path)
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None and "unified_diff" not in candidate
    detail = execution.get_candidate(candidate["candidate_id"], include_patch=True)
    assert detail is not None and detail["unified_diff"] == PATCH
    assert result["produced_proposal"]["content"] == "Change the example"

    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            """select 'candidate' source, unified_diff value from room_execution_candidates
               union all select 'activity', payload_json from room_activities
               union all select 'observation', coalesce(outcome_payload_json, '')
                 from room_observations
               union all select 'request', result_json from chat_request_log
               union all select 'proposal', content from proposals"""
        ).fetchall()
        assert [(source, PATCH in value) for source, value in rows].count(("candidate", True)) == 1
        assert all(source == "candidate" for source, value in rows if PATCH in value)
        before = {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0]
            for table in (
                "room_execution_candidates",
                "room_execution_candidate_members",
                "room_activities",
                "proposals",
                "chat_request_log",
            )
        }
    replay = submit(
        db,
        registry,
        conversation_id,
        records[0][0],
        records[0][1],
        claims[records[0][0].participant_id],
        "candidate",
        outcome_type="propose",
        outcome_payload=patch_outcome(),
    )
    assert replay == result
    with sqlite3.connect(db) as conn:
        assert before == {
            table: conn.execute(f"select count(*) from {table}").fetchone()[0] for table in before
        }


def test_candidate_peer_snapshot_excludes_retired_provider_rows(tmp_path):
    db, registry, conversation_id, records, _, claims = root_and_claims(tmp_path)
    with sqlite3.connect(db) as conn:
        conn.execute(
            """insert into participants (
                   participant_id, conversation_id, role, display_name, cli_kind, model,
                   status, created_at
               ) values ('part_historical_a2a', ?, 'review', 'Historical A2A',
                         'a2a', 'historical', 'active', '2026-07-12T00:00:00Z')""",
            (conversation_id,),
        )
    author = records[0]
    result = submit(
        db,
        registry,
        conversation_id,
        author[0],
        author[1],
        claims[author[0].participant_id],
        "candidate-current-peers",
        outcome_type="propose",
        outcome_payload=patch_outcome(),
    )
    candidate_id = result["execution_candidate"]["candidate_id"]
    with sqlite3.connect(db) as conn:
        member_ids = {
            row[0]
            for row in conn.execute(
                "select participant_id from room_execution_candidate_members "
                "where candidate_id = ?",
                (candidate_id,),
            )
        }

    assert member_ids == {record[0].participant_id for record in records[1:]}


def test_assessment_requires_current_full_material_and_is_atomic(tmp_path):
    db, registry, conversation_id, records, claims, result, execution = make_candidate(
        tmp_path, consensus=True
    )
    author, reviewer, third = records
    for index, pair in enumerate((reviewer, third)):
        submit(
            db,
            registry,
            conversation_id,
            pair[0],
            pair[1],
            claims[pair[0].participant_id],
            f"root-noop-{index}",
            outcome_type="noop",
            outcome_payload={},
        )
    claim = RoomKernelStore(db).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=reviewer[0].participant_id,
        lease_owner="reviewer",
    )
    assert claim is not None
    vote = {
        "proposal_id": result["produced_proposal"]["id"],
        "candidate_digest": result["execution_candidate"]["candidate_digest"],
        "assessment": "endorse",
        "rationale": "complete diff reviewed",
    }
    with pytest.raises(RoomApplicationError) as exc_info:
        submit(
            db,
            registry,
            conversation_id,
            reviewer[0],
            reviewer[1],
            claim,
            "unproven",
            outcome_type="noop",
            outcome_payload={},
            proposal_assessments=[vote],
        )
    assert exc_info.value.code == "room_execution_review_material_unproven"
    with pytest.raises(RoomApplicationError) as source_error:
        submit(
            db,
            registry,
            conversation_id,
            reviewer[0],
            reviewer[1],
            claim,
            "ordinary-or-missing-proposal",
            outcome_type="noop",
            outcome_payload={},
            proposal_assessments=[dict(vote, proposal_id="prop_not_execution_candidate")],
        )
    assert source_error.value.code == "room_execution_assessment_source_invalid"
    bind_review(execution, result, claim, reviewer[0].participant_id)
    wrong = dict(vote, candidate_digest="sha256:" + "2" * 64)
    with pytest.raises(RoomApplicationError) as exc_info:
        submit(
            db,
            registry,
            conversation_id,
            reviewer[0],
            reviewer[1],
            claim,
            "wrong-digest",
            outcome_type="noop",
            outcome_payload={},
            proposal_assessments=[wrong],
        )
    assert exc_info.value.code == "room_execution_assessment_digest_mismatch"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "update participants set display_name = 'drifted' where participant_id = ?",
            (reviewer[0].participant_id,),
        )
    with pytest.raises(RoomApplicationError) as identity_error:
        submit(
            db,
            registry,
            conversation_id,
            reviewer[0],
            reviewer[1],
            claim,
            "identity-drift",
            outcome_type="noop",
            outcome_payload={},
            proposal_assessments=[vote],
        )
    assert identity_error.value.code == "room_execution_assessor_identity_drift"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "update participants set display_name = ? where participant_id = ?",
            (reviewer[0].display_name, reviewer[0].participant_id),
        )
    accepted = submit(
        db,
        registry,
        conversation_id,
        reviewer[0],
        reviewer[1],
        claim,
        "accepted",
        outcome_type="noop",
        outcome_payload={},
        proposal_assessments=[vote],
    )
    assert accepted["proposal_assessments"][0]["assessment"] == "endorse"
    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row
        conn.execute("begin immediate")
        with pytest.raises(RoomExecutionStoreError) as self_vote:
            record_proposal_assessments_conn(
                conn,
                assessor_participant_id=author[0].participant_id,
                source_attempt_id=claims[author[0].participant_id]["attempt"]["attempt_id"],
                source_batch_id=claims[author[0].participant_id]["batch"]["batch_id"],
                batch_activity_ids={result["produced_activity"]["activity_id"]},
                assessments=(
                    ProposalAssessment(
                        vote["proposal_id"], vote["candidate_digest"], "endorse", "self"
                    ),
                ),
                stamp="2026-01-01T00:00:00Z",
            )
        assert self_vote.value.code == "room_execution_assessment_self_forbidden"
        with pytest.raises(RoomExecutionStoreError) as duplicate:
            record_proposal_assessments_conn(
                conn,
                assessor_participant_id=reviewer[0].participant_id,
                source_attempt_id=claim["attempt"]["attempt_id"],
                source_batch_id=claim["batch"]["batch_id"],
                batch_activity_ids={result["produced_activity"]["activity_id"]},
                assessments=(
                    ProposalAssessment(
                        vote["proposal_id"], vote["candidate_digest"], "endorse", "again"
                    ),
                ),
                stamp="2026-01-01T00:00:00Z",
            )
        assert duplicate.value.code == "room_execution_assessment_duplicate"
        conn.rollback()


def test_manual_default_and_consensus_all_endorse_create_exactly_one_run(tmp_path):
    *_, manual_result, manual_store = make_candidate(tmp_path / "manual")
    manual_candidate = manual_store.get_candidate(
        manual_result["execution_candidate"]["candidate_id"]
    )
    assert manual_candidate is not None
    assert manual_candidate["policy_snapshot"]["mode"] == "manual"
    assert manual_candidate["consensus_state"] == "invalidated"

    db, registry, conversation_id, records, claims, result, execution = make_candidate(
        tmp_path / "consensus", consensus=True
    )
    finish_roots_and_vote(
        db,
        registry,
        conversation_id,
        records,
        claims,
        result,
        execution,
        ["endorse", "endorse"],
    )
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None and candidate["consensus_state"] == "endorsed"
    guard = ExecutionWorkspaceGuard("a" * 40, True, DIGEST, frozenset({PATH}))
    risk = ExecutionRiskEvaluation(True, EXECUTION_RISK_POLICY_REVISION, DIGEST)
    disabled = execution.reconcile_consensus_candidate(
        candidate_id=candidate["candidate_id"],
        kill_switch_enabled=False,
        workspace_guard=guard,
        risk_evaluation=risk,
        gate_plan=trusted_gate_plan(),
    )
    assert disabled["status"] == "manual_required" and disabled["run"] is None
    first = execution.reconcile_consensus_candidate(
        candidate_id=candidate["candidate_id"],
        kill_switch_enabled=True,
        workspace_guard=guard,
        risk_evaluation=risk,
        gate_plan=trusted_gate_plan(),
    )
    drifted_plan = build_execution_gate_plan(
        profile_id="xmuse-monorepo/v2",
        changed_paths=(PATH,),
        repository_manifest_digest=DIGEST,
        toolchain_capability_digest="sha256:" + "3" * 64,
    )
    second = execution.reconcile_consensus_candidate(
        candidate_id=candidate["candidate_id"],
        kill_switch_enabled=True,
        workspace_guard=guard,
        risk_evaluation=risk,
        gate_plan=drifted_plan,
    )
    assert first["created"] is True
    assert second["created"] is False
    assert second["run"]["run_id"] == first["run"]["run_id"]
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from room_execution_runs").fetchone()[0] == 1
        assert conn.execute("select count(*) from room_execution_authorizations").fetchone()[0] == 1


def test_consensus_profile_unavailable_is_durable_manual_required(tmp_path):
    db, registry, conversation_id, records, claims, result, execution = make_candidate(
        tmp_path,
        consensus=True,
    )
    finish_roots_and_vote(
        db,
        registry,
        conversation_id,
        records,
        claims,
        result,
        execution,
        ["endorse", "endorse"],
    )
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None and candidate["consensus_state"] == "endorsed"

    reconciled = execution.reconcile_consensus_candidate(
        candidate_id=candidate["candidate_id"],
        kill_switch_enabled=True,
        workspace_guard=ExecutionWorkspaceGuard("a" * 40, True, DIGEST, frozenset({PATH})),
        risk_evaluation=ExecutionRiskEvaluation(True, EXECUTION_RISK_POLICY_REVISION, DIGEST),
        gate_plan=None,
    )

    assert reconciled["status"] == "manual_required"
    assert reconciled["reason_code"] == "execution_gate_profile_unavailable"
    assert execution.list_conversation_runs(conversation_id) == []
    refreshed = execution.get_candidate(candidate["candidate_id"])
    assert refreshed is not None
    assert refreshed["consensus_state"] == "invalidated"
    assert refreshed["reason_code"] == "execution_gate_profile_unavailable"


@pytest.mark.parametrize(
    ("assessment", "expected_state"),
    [("object", "objected"), ("abstain", "abstained")],
)
def test_object_or_abstain_forces_manual_required(tmp_path, assessment, expected_state):
    db, registry, conversation_id, records, claims, result, execution = make_candidate(
        tmp_path, consensus=True
    )
    finish_roots_and_vote(
        db,
        registry,
        conversation_id,
        records,
        claims,
        result,
        execution,
        [assessment],
    )
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None and candidate["consensus_state"] == expected_state
    reconciled = execution.reconcile_consensus_candidate(
        candidate_id=candidate["candidate_id"],
        kill_switch_enabled=True,
        workspace_guard=ExecutionWorkspaceGuard("a" * 40, True, DIGEST, frozenset({PATH})),
        risk_evaluation=ExecutionRiskEvaluation(True, EXECUTION_RISK_POLICY_REVISION, DIGEST),
        gate_plan=trusted_gate_plan(),
    )
    assert reconciled["status"] == "manual_required"
    assert execution.list_conversation_runs(conversation_id) == []


@pytest.mark.parametrize("drift", ["author_identity", "policy", "workspace"])
def test_author_identity_or_policy_drift_invalidates_consensus(tmp_path, drift):
    db, registry, conversation_id, records, claims, result, execution = make_candidate(
        tmp_path, consensus=True
    )
    finish_roots_and_vote(
        db,
        registry,
        conversation_id,
        records,
        claims,
        result,
        execution,
        ["endorse", "endorse"],
    )
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None and candidate["consensus_state"] == "endorsed"
    if drift == "author_identity":
        with sqlite3.connect(db) as conn:
            conn.execute(
                "update participants set display_name = 'changed' where participant_id = ?",
                (records[0][0].participant_id,),
            )
    elif drift == "policy":
        execution.set_policy(
            conversation_id=conversation_id,
            mode="manual",
            client_action_id="policy-drift",
            operator_identity="operator",
            expected_revision=1,
        )
    workspace_guard = ExecutionWorkspaceGuard(
        "b" * 40 if drift == "workspace" else "a" * 40,
        drift != "workspace",
        DIGEST,
        frozenset({PATH}),
    )
    reconciled = execution.reconcile_consensus_candidate(
        candidate_id=candidate["candidate_id"],
        kill_switch_enabled=True,
        workspace_guard=workspace_guard,
        risk_evaluation=ExecutionRiskEvaluation(True, EXECUTION_RISK_POLICY_REVISION, DIGEST),
        gate_plan=trusted_gate_plan(),
    )
    assert reconciled["status"] == "manual_required"
    refreshed = execution.get_candidate(candidate["candidate_id"])
    assert refreshed is not None and refreshed["consensus_state"] == "invalidated"
    assert execution.list_endorsed_candidate_ids() == []
