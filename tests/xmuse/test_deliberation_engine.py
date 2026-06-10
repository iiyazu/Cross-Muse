from __future__ import annotations

from xmuse_core.chat.deliberation_engine import (
    BlueprintArbitrationPolicy,
    DeliberationFreezeGuard,
    FreezeDecisionStatus,
)
from xmuse_core.chat.protocol_v2 import (
    DeliberationMessageKind,
    DeliberationMessageV1,
    ObjectionLevel,
)


def test_blocking_challenge_without_response_denies_freeze() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        payload={"blueprint_id": "bp-1", "summary": "Freeze the contract."},
        target_ref="blueprint:bp-1:1",
    )
    challenge = _message(
        "msg-challenge",
        kind=DeliberationMessageKind.CHALLENGE,
        parent_id=proposal.msg_id,
        target_ref=proposal.target_ref,
        payload={"question": "Where is the source evidence?"},
        objection_level=ObjectionLevel.BLOCKING,
    )

    decision = DeliberationFreezeGuard(required_commits=1).evaluate(
        [proposal, challenge],
        target_ref="blueprint:bp-1:1",
    )

    assert decision.status is FreezeDecisionStatus.DENIED
    assert decision.can_freeze is False
    assert decision.blocking_challenge_ids == ["msg-challenge"]
    assert decision.evidence_refs == ["message:msg-proposal", "message:msg-challenge"]
    assert decision.reason == "unresolved blocking challenges"


def test_resolved_blocking_challenge_allows_freeze_with_commit_quorum() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1"},
    )
    challenge = _message(
        "msg-challenge",
        kind=DeliberationMessageKind.CHALLENGE,
        parent_id=proposal.msg_id,
        target_ref=proposal.target_ref,
        payload={"question": "What proves this is testable?"},
        objection_level=ObjectionLevel.BLOCKING,
    )
    response = _message(
        "msg-response",
        kind=DeliberationMessageKind.EVIDENCE,
        parent_id=challenge.msg_id,
        target_ref=proposal.target_ref,
        payload={"resolves": "msg-challenge", "evidence": "tests added"},
    )
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
        agent_id="god-review",
    )

    decision = DeliberationFreezeGuard(required_commits=1).evaluate(
        [commit, challenge, response, proposal],
        target_ref="blueprint:bp-1:1",
    )

    assert decision.status is FreezeDecisionStatus.ALLOWED
    assert decision.can_freeze is True
    assert decision.resolved_challenge_ids == ["msg-challenge"]
    assert decision.commit_agent_ids == ["god-review"]


def test_non_blocking_objections_are_carried_into_open_questions() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1"},
    )
    objection = _message(
        "msg-objection",
        kind=DeliberationMessageKind.CHALLENGE,
        parent_id=proposal.msg_id,
        target_ref=proposal.target_ref,
        payload={"question": "Should MemoryOS writeback be deferred?"},
        objection_level=ObjectionLevel.NON_BLOCKING,
    )
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
    )

    decision = DeliberationFreezeGuard(required_commits=1).evaluate(
        [proposal, objection, commit],
        target_ref="blueprint:bp-1:1",
    )

    assert decision.status is FreezeDecisionStatus.ALLOWED
    assert decision.open_questions == [
        {
            "message_id": "msg-objection",
            "question": "Should MemoryOS writeback be deferred?",
            "source_refs": ["message:msg-objection"],
        }
    ]


def test_duplicate_votes_and_commits_are_idempotent_by_message_content() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1"},
    )
    vote = _message(
        "msg-vote-a",
        kind=DeliberationMessageKind.VOTE,
        target_ref=proposal.target_ref,
        payload={"vote": "approve"},
        agent_id="god-review",
    )
    duplicate_vote = vote.model_copy(update={"msg_id": "msg-vote-b"})
    no_objection = _message(
        "msg-review",
        kind=DeliberationMessageKind.NOTE,
        target_ref=proposal.target_ref,
        payload={"review": "no_objection"},
        agent_id="god-review",
    )
    commit = _message(
        "msg-commit-a",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
        agent_id="god-review",
    )
    duplicate_commit = commit.model_copy(update={"msg_id": "msg-commit-b"})

    decision = DeliberationFreezeGuard(required_commits=1).evaluate(
        [proposal, vote, duplicate_vote, no_objection, commit, duplicate_commit],
        target_ref="blueprint:bp-1:1",
    )

    assert decision.status is FreezeDecisionStatus.ALLOWED
    assert decision.vote_tally == {"approve": 1, "reject": 0, "abstain": 0}
    assert decision.commit_agent_ids == ["god-review"]
    assert decision.duplicate_message_ids == ["msg-commit-b", "msg-vote-b"]


def test_proposal_requires_challenge_or_explicit_no_objection_review() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1"},
    )
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
    )

    decision = DeliberationFreezeGuard(required_commits=1).evaluate(
        [proposal, commit],
        target_ref="blueprint:bp-1:1",
    )

    assert decision.status is FreezeDecisionStatus.DENIED
    assert decision.reason == "missing challenge or explicit no-objection review"


def test_objection_window_blocks_freeze_until_lamport_bound_is_reached() -> None:
    proposal = _message(
        "msg-001",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1"},
    )
    objection = _message(
        "msg-002",
        kind=DeliberationMessageKind.CHALLENGE,
        parent_id=proposal.msg_id,
        target_ref=proposal.target_ref,
        payload={"question": "Should this wait for review?"},
        objection_level=ObjectionLevel.NON_BLOCKING,
    )
    commit = _message(
        "msg-003",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
    )
    clock = _message(
        "msg-006",
        kind=DeliberationMessageKind.NOTE,
        target_ref=proposal.target_ref,
        payload={"clock": "objection_window_elapsed"},
    )

    guard = DeliberationFreezeGuard(required_commits=1, objection_window_lamports=5)
    early = guard.evaluate([proposal, objection, commit], target_ref="blueprint:bp-1:1")
    elapsed = guard.evaluate(
        [proposal, objection, commit, clock],
        target_ref="blueprint:bp-1:1",
    )

    assert early.status is FreezeDecisionStatus.DENIED
    assert early.reason == "objection window still open"
    assert elapsed.status is FreezeDecisionStatus.ALLOWED


def test_freeze_requires_explicit_proposal_or_no_objection_review_note() -> None:
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref="blueprint:bp-1:1",
        payload={"commitment": "ready_to_freeze"},
    )

    denied = DeliberationFreezeGuard(required_commits=1).evaluate(
        [commit],
        target_ref="blueprint:bp-1:1",
    )
    allowed = DeliberationFreezeGuard(required_commits=1).evaluate(
        [
            commit,
            _message(
                "msg-review",
                kind=DeliberationMessageKind.NOTE,
                target_ref="blueprint:bp-1:1",
                payload={"review": "no_objection"},
                agent_id="god-review",
            ),
        ],
        target_ref="blueprint:bp-1:1",
    )

    assert denied.status is FreezeDecisionStatus.DENIED
    assert denied.reason == "missing proposal or explicit no-objection review"
    assert allowed.status is FreezeDecisionStatus.ALLOWED


def test_arbitration_quorum_requires_two_thirds_approval() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1"},
    )
    review = _message(
        "msg-review",
        kind=DeliberationMessageKind.NOTE,
        target_ref=proposal.target_ref,
        payload={"review": "no_objection"},
        agent_id="god-review",
    )
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
    )
    first_vote = _message(
        "msg-vote-a",
        kind=DeliberationMessageKind.VOTE,
        target_ref=proposal.target_ref,
        payload={"vote": "approve"},
        agent_id="god-architect",
    )
    second_vote = _message(
        "msg-vote-b",
        kind=DeliberationMessageKind.VOTE,
        target_ref=proposal.target_ref,
        payload={"vote": "approve"},
        agent_id="god-review",
    )
    guard = DeliberationFreezeGuard(
        required_commits=1,
        arbitration_policy=BlueprintArbitrationPolicy(
            eligible_voter_ids=["god-architect", "god-review", "god-execute"],
            approval_ratio=2 / 3,
        ),
    )

    denied = guard.evaluate(
        [proposal, review, commit, first_vote],
        target_ref="blueprint:bp-1:1",
    )
    allowed = guard.evaluate(
        [proposal, review, commit, first_vote, second_vote],
        target_ref="blueprint:bp-1:1",
    )

    assert denied.status is FreezeDecisionStatus.DENIED
    assert denied.reason == "arbitration quorum not satisfied"
    assert denied.arbitration_required_approvals == 2
    assert denied.arbitration_approval_agent_ids == ["god-architect"]
    assert allowed.status is FreezeDecisionStatus.ALLOWED
    assert allowed.arbitration_approval_agent_ids == ["god-architect", "god-review"]


def test_veto_agent_blocking_challenge_denies_freeze_until_resolved() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1"},
    )
    veto = _message(
        "msg-veto",
        kind=DeliberationMessageKind.CHALLENGE,
        parent_id=proposal.msg_id,
        target_ref=proposal.target_ref,
        payload={"question": "Privacy impact is unspecified.", "veto": True},
        objection_level=ObjectionLevel.BLOCKING,
        agent_id="god-review",
    )
    response = _message(
        "msg-response",
        kind=DeliberationMessageKind.EVIDENCE,
        parent_id=veto.msg_id,
        target_ref=proposal.target_ref,
        payload={"resolves": veto.msg_id, "evidence": "privacy impact added"},
    )
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
    )
    guard = DeliberationFreezeGuard(
        required_commits=1,
        arbitration_policy=BlueprintArbitrationPolicy(veto_agent_ids=["god-review"]),
    )

    denied = guard.evaluate([proposal, veto, commit], target_ref="blueprint:bp-1:1")
    allowed = guard.evaluate(
        [proposal, veto, response, commit],
        target_ref="blueprint:bp-1:1",
    )

    assert denied.status is FreezeDecisionStatus.DENIED
    assert denied.reason == "unresolved veto blockers"
    assert denied.veto_blocker_ids == ["msg-veto"]
    assert allowed.status is FreezeDecisionStatus.ALLOWED
    assert allowed.resolved_challenge_ids == ["msg-veto"]


def test_operator_approval_is_required_for_sensitive_freeze_policy() -> None:
    proposal = _message(
        "msg-proposal",
        kind=DeliberationMessageKind.PROPOSAL,
        target_ref="blueprint:bp-1:1",
        payload={"blueprint_id": "bp-1", "privacy_sensitive": True},
    )
    review = _message(
        "msg-review",
        kind=DeliberationMessageKind.NOTE,
        target_ref=proposal.target_ref,
        payload={"review": "no_objection"},
        agent_id="god-review",
    )
    architect_vote = _message(
        "msg-vote-a",
        kind=DeliberationMessageKind.VOTE,
        target_ref=proposal.target_ref,
        payload={"vote": "approve"},
        agent_id="god-architect",
    )
    review_vote = _message(
        "msg-vote-b",
        kind=DeliberationMessageKind.VOTE,
        target_ref=proposal.target_ref,
        payload={"vote": "approve"},
        agent_id="god-review",
    )
    operator_vote = _message(
        "msg-vote-c",
        kind=DeliberationMessageKind.VOTE,
        target_ref=proposal.target_ref,
        payload={"vote": "approve"},
        agent_id="operator",
    )
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
    )
    guard = DeliberationFreezeGuard(
        required_commits=1,
        arbitration_policy=BlueprintArbitrationPolicy(
            eligible_voter_ids=["god-architect", "god-review", "operator"],
            require_operator_approval=True,
            operator_agent_ids=["operator"],
        ),
    )

    denied = guard.evaluate(
        [proposal, review, architect_vote, review_vote, commit],
        target_ref="blueprint:bp-1:1",
    )
    allowed = guard.evaluate(
        [proposal, review, architect_vote, review_vote, operator_vote, commit],
        target_ref="blueprint:bp-1:1",
    )

    assert denied.status is FreezeDecisionStatus.DENIED
    assert denied.reason == "operator approval required"
    assert denied.operator_approval_agent_ids == []
    assert allowed.status is FreezeDecisionStatus.ALLOWED
    assert allowed.operator_approval_agent_ids == ["operator"]


def _message(
    msg_id: str,
    *,
    kind: DeliberationMessageKind,
    target_ref: str | None,
    payload: dict[str, object],
    parent_id: str | None = None,
    objection_level: ObjectionLevel = ObjectionLevel.NONE,
    agent_id: str = "god-architect",
) -> DeliberationMessageV1:
    return DeliberationMessageV1(
        msg_id=msg_id,
        conversation_id="conv-1",
        agent_id=agent_id,
        lamport_ts=int(msg_id.rsplit("-", maxsplit=1)[-1], 36)
        if msg_id.rsplit("-", maxsplit=1)[-1].isalnum()
        else 1,
        kind=kind,
        parent_id=parent_id,
        target_ref=target_ref,
        mentions=[],
        payload=payload,
        source_refs=[f"message:{msg_id}"],
        objection_level=objection_level,
        decision_scope="blueprint.freeze",
    )
