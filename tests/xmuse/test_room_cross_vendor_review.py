from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from tests.xmuse.execution_store_testkit import TestExecutionStore
from tests.xmuse.room_fixtures import RoomTestStore
from tests.xmuse.test_room_execution_outcomes import (
    DIGEST,
    PATH,
    bind_review,
    finish_roots_and_vote,
    patch_outcome,
    trusted_gate_plan,
)
from tests.xmuse.test_room_participant_outcomes import submit
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_execution_contracts import (
    EXECUTION_RISK_POLICY_REVISION,
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
)
from xmuse_core.chat.room_execution_projection import (
    build_room_execution_candidate_projection,
)
from xmuse_core.chat.room_kernel import RoomKernelStore

CROSS_FAMILY_MISSING = "room_execution_cross_family_review_missing"
REVIEW_ROUND_LIMIT = "room_execution_review_round_limit"


def mixed_room(tmp_path: Path, cli_kinds: tuple[str, ...]):
    """One Room whose participants span the given provider kinds."""

    db, registry_path = tmp_path / "chat.db", tmp_path / "god_sessions.json"
    conversation_id = RoomTestStore(db).create_conversation("room").id
    participants = ParticipantStore(db)
    records = []
    for index, cli_kind in enumerate(cli_kinds):
        participant = participants.add(
            conversation_id=conversation_id,
            role=f"arbitrary-{index}",
            display_name=f"Agent {index}",
            cli_kind=cli_kind,
            model="gpt-5" if cli_kind == "codex" else f"{cli_kind}-model",
        )
        session = GodSessionRegistry(registry_path).create(
            participant.role,
            participant.display_name,
            cli_kind,
            f"addr-{index}",
            f"inbox-{index}",
            conversation_id,
            participant.participant_id,
        )
        records.append((participant, session))
    return db, registry_path, conversation_id, records


def consensus_room(tmp_path: Path, cli_kinds: tuple[str, ...]):
    db, registry, conversation_id, records = mixed_room(tmp_path, cli_kinds)
    execution = TestExecutionStore(db)
    execution.set_policy(
        conversation_id=conversation_id,
        mode="consensus",
        client_action_id="policy",
        operator_identity="operator",
        expected_revision=0,
    )
    return db, registry, conversation_id, records, execution


def propose_candidate(tmp_path: Path, cli_kinds: tuple[str, ...]):
    db, registry, conversation_id, records, execution = consensus_room(tmp_path, cli_kinds)
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="hello",
        client_request_id="human-1",
    )
    claims = {
        participant.participant_id: kernel.claim_next_observation(
            conversation_id=conversation_id,
            participant_id=participant.participant_id,
            lease_owner=f"lease-{index}",
        )
        for index, (participant, _session) in enumerate(records)
    }
    author = records[0]
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


def workspace_guard() -> ExecutionWorkspaceGuard:
    return ExecutionWorkspaceGuard("a" * 40, True, DIGEST, frozenset({PATH}))


def risk_evaluation() -> ExecutionRiskEvaluation:
    return ExecutionRiskEvaluation(True, EXECUTION_RISK_POLICY_REVISION, DIGEST)


def reconcile(execution, candidate_id: str, *, kill_switch_enabled: bool = True):
    return execution.reconcile_consensus_candidate(
        candidate_id=candidate_id,
        kill_switch_enabled=kill_switch_enabled,
        workspace_guard=workspace_guard(),
        risk_evaluation=risk_evaluation(),
        gate_plan=trusted_gate_plan(),
    )


def claim(db, conversation_id: str, record, tag: str):
    return RoomKernelStore(db).claim_next_observation(
        conversation_id=conversation_id,
        participant_id=record[0].participant_id,
        lease_owner=f"lease-{tag}",
    )


def complete_root_phase(db, registry, conversation_id, records, tag: str) -> None:
    for index, pair in enumerate(records[1:], start=1):
        root_claim = claim(db, conversation_id, pair, f"{tag}-root-{index}")
        assert root_claim is not None
        submit(
            db,
            registry,
            conversation_id,
            pair[0],
            pair[1],
            root_claim,
            f"{tag}-root-outcome-{index}",
            outcome_type="noop",
            outcome_payload={},
        )


def drain_all(db, registry, conversation_id, records, tag: str) -> None:
    for pass_index in range(20):
        progressed = False
        for index, pair in enumerate(records):
            tag_index = f"{tag}-drain-{pass_index}-{index}"
            observation_claim = claim(db, conversation_id, pair, tag_index)
            if observation_claim is None:
                continue
            progressed = True
            submit(
                db,
                registry,
                conversation_id,
                pair[0],
                pair[1],
                observation_claim,
                f"{tag}-drain-outcome-{pass_index}-{index}",
                outcome_type="noop",
                outcome_payload={},
            )
        if not progressed:
            return
    raise AssertionError("room did not drain")


def propose_round(db, registry, conversation_id, records, tag: str):
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content=f"round {tag}",
        client_request_id=f"human-{tag}",
    )
    author = records[0]
    root_claim = claim(db, conversation_id, author, f"{tag}-author-root")
    assert root_claim is not None
    result = submit(
        db,
        registry,
        conversation_id,
        author[0],
        author[1],
        root_claim,
        f"{tag}-propose",
        outcome_type="propose",
        outcome_payload=patch_outcome(),
    )
    complete_root_phase(db, registry, conversation_id, records, tag)
    return result


def assessment(result, kind: str, rationale: str) -> dict[str, object]:
    return {
        "proposal_id": result["produced_proposal"]["id"],
        "candidate_digest": result["execution_candidate"]["candidate_digest"],
        "assessment": kind,
        "rationale": rationale,
    }


def objected_round(db, registry, conversation_id, records, execution, tag: str):
    result = propose_round(db, registry, conversation_id, records, tag)
    reviewer = records[1]
    review_claim = claim(db, conversation_id, reviewer, f"{tag}-object")
    assert review_claim is not None
    bind_review(execution, result, review_claim, reviewer[0].participant_id)
    submit(
        db,
        registry,
        conversation_id,
        reviewer[0],
        reviewer[1],
        review_claim,
        f"{tag}-object-outcome",
        outcome_type="noop",
        outcome_payload={},
        proposal_assessments=[assessment(result, "object", f"change requested in {tag}")],
    )
    drain_all(db, registry, conversation_id, records, tag)
    return result


def endorsed_round(db, registry, conversation_id, records, execution, tag: str):
    result = propose_round(db, registry, conversation_id, records, tag)
    for index, pair in enumerate(records[1:], start=1):
        vote_claim = claim(db, conversation_id, pair, f"{tag}-endorse-{index}")
        assert vote_claim is not None
        bind_review(execution, result, vote_claim, pair[0].participant_id)
        submit(
            db,
            registry,
            conversation_id,
            pair[0],
            pair[1],
            vote_claim,
            f"{tag}-endorse-outcome-{index}",
            outcome_type="noop",
            outcome_payload={},
            proposal_assessments=[assessment(result, "endorse", f"reviewed in {tag}")],
        )
    drain_all(db, registry, conversation_id, records, tag)
    return result


def test_claude_author_and_antigravity_endorsement_authorize_consensus(tmp_path):
    db, registry, conversation_id, records, claims, result, execution = propose_candidate(
        tmp_path, ("claude", "antigravity", "codex")
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
    assert {member["participant_id"] for member in candidate["members"]} == {
        records[1][0].participant_id,
        records[2][0].participant_id,
    }
    assert candidate["cross_family_review"] == {
        "required": True,
        "satisfied": True,
        "author_family": "claude",
        "reviewer_families": ["antigravity", "codex"],
    }

    detail = build_room_execution_candidate_projection(execution, candidate["candidate_id"])
    assert detail["candidate"]["cross_family_review"] == {
        "required": True,
        "satisfied": True,
        "author_family": "claude",
        "reviewer_families": ["antigravity", "codex"],
    }

    reconciled = reconcile(execution, candidate["candidate_id"])
    assert reconciled["status"] == "authorized"
    assert reconciled["created"] is True


def test_same_family_endorsement_only_fails_closed_and_manual_still_executes(tmp_path):
    db, registry, conversation_id, records, claims, result, execution = propose_candidate(
        tmp_path, ("claude", "claude")
    )
    ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="late-reviewer",
        display_name="Late Antigravity",
        cli_kind="antigravity",
        model="antigravity-model",
    )
    finish_roots_and_vote(
        db,
        registry,
        conversation_id,
        records,
        claims,
        result,
        execution,
        ["endorse"],
    )
    candidate = execution.get_candidate(result["execution_candidate"]["candidate_id"])
    assert candidate is not None and candidate["consensus_state"] == "endorsed"
    assert candidate["cross_family_review"] == {
        "required": True,
        "satisfied": False,
        "author_family": "claude",
        "reviewer_families": ["claude"],
    }

    paused = reconcile(execution, candidate["candidate_id"])
    assert paused["status"] == "manual_required"
    assert paused["reason_code"] == CROSS_FAMILY_MISSING
    assert paused["run"] is None
    assert execution.list_conversation_runs(conversation_id) == []
    refreshed = execution.get_candidate(candidate["candidate_id"])
    assert refreshed is not None and refreshed["consensus_state"] == "endorsed"

    detail = build_room_execution_candidate_projection(execution, candidate["candidate_id"])
    assert detail["candidate"]["cross_family_review"]["required"] is True
    assert detail["candidate"]["cross_family_review"]["satisfied"] is False

    manual = execution.apply_operator_decision(
        candidate_id=candidate["candidate_id"],
        decision="execute",
        client_action_id="manual-cross-family",
        operator_identity="operator",
        expected_candidate_digest=candidate["candidate_digest"],
        expected_candidate_revision=refreshed["revision"],
        expected_policy_revision=1,
        workspace_guard=workspace_guard(),
        risk_evaluation=risk_evaluation(),
        gate_plan=trusted_gate_plan(),
    )
    assert manual["state"] == "authorized"
    assert manual["authorization_mode"] == "manual"
    assert manual["run"]["state"] == "requested"


def test_terminal_execution_activity_fans_out_to_every_vendor(tmp_path):
    db, registry, conversation_id, records, claims, result, execution = propose_candidate(
        tmp_path, ("claude", "antigravity", "codex")
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
    assert candidate is not None
    reconciled = reconcile(execution, candidate["candidate_id"])
    assert reconciled["created"] is True

    cancelled = execution.request_cancel(
        run_id=reconciled["run"]["run_id"],
        client_action_id="cancel-terminal",
        operator_identity="operator",
        expected_state="requested",
        expected_revision=0,
    )
    assert cancelled["state"] == "cancelled"

    with sqlite3.connect(db) as conn:
        activity = conn.execute(
            "select activity_id from room_activities where conversation_id = ? "
            "and activity_type = 'execution.cancelled'",
            (conversation_id,),
        ).fetchone()
        assert activity is not None
        observed = {
            row[0]
            for row in conn.execute(
                "select participant_id from room_observations where activity_id = ?",
                (activity[0],),
            )
        }
    assert observed == {participant.participant_id for participant, _session in records}


@pytest.mark.parametrize("cli_kind", ["codex", "claude"])
def test_single_family_room_keeps_consensus_without_cross_family(tmp_path, cli_kind):
    db, registry, conversation_id, records, claims, result, execution = propose_candidate(
        tmp_path, (cli_kind, cli_kind, cli_kind)
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
    assert candidate["cross_family_review"] == {
        "required": False,
        "satisfied": False,
        "author_family": cli_kind,
        "reviewer_families": [cli_kind],
    }
    reconciled = reconcile(execution, candidate["candidate_id"])
    assert reconciled["status"] == "authorized"
    assert reconciled["created"] is True


def test_review_round_brake_pauses_consensus_after_four_questioned_rounds(tmp_path):
    db, registry, conversation_id, records, execution = consensus_room(
        tmp_path, ("codex", "codex", "codex")
    )
    for index in range(3):
        objected_round(db, registry, conversation_id, records, execution, f"question-{index}")

    below_limit = endorsed_round(db, registry, conversation_id, records, execution, "below-limit")
    allowed_candidate = execution.get_candidate(below_limit["execution_candidate"]["candidate_id"])
    assert allowed_candidate is not None and allowed_candidate["consensus_state"] == "endorsed"
    allowed = reconcile(execution, allowed_candidate["candidate_id"])
    assert allowed["status"] == "authorized"
    assert allowed["created"] is True

    objected_round(db, registry, conversation_id, records, execution, "question-3")
    paused_round = endorsed_round(db, registry, conversation_id, records, execution, "paused")
    paused_id = paused_round["execution_candidate"]["candidate_id"]
    paused_candidate = execution.get_candidate(paused_id)
    assert paused_candidate is not None and paused_candidate["consensus_state"] == "endorsed"

    paused = reconcile(execution, paused_id)
    assert paused["status"] == "manual_required"
    assert paused["reason_code"] == REVIEW_ROUND_LIMIT
    assert paused["run"] is None
    assert len(execution.list_conversation_runs(conversation_id)) == 1

    manual = execution.apply_operator_decision(
        candidate_id=paused_id,
        decision="execute",
        client_action_id="manual-review-round",
        operator_identity="operator",
        expected_candidate_digest=paused_candidate["candidate_digest"],
        expected_candidate_revision=paused_candidate["revision"],
        expected_policy_revision=1,
        workspace_guard=workspace_guard(),
        risk_evaluation=risk_evaluation(),
        gate_plan=trusted_gate_plan(),
    )
    assert manual["state"] == "authorized"
    assert manual["authorization_mode"] == "manual"
    assert manual["run"]["state"] == "requested"
