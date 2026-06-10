from __future__ import annotations

from xmuse_core.chat.deliberation_engine import (
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
    commit = _message(
        "msg-commit-a",
        kind=DeliberationMessageKind.COMMIT,
        target_ref=proposal.target_ref,
        payload={"commitment": "ready_to_freeze"},
        agent_id="god-review",
    )
    duplicate_commit = commit.model_copy(update={"msg_id": "msg-commit-b"})

    decision = DeliberationFreezeGuard(required_commits=1).evaluate(
        [proposal, vote, duplicate_vote, commit, duplicate_commit],
        target_ref="blueprint:bp-1:1",
    )

    assert decision.status is FreezeDecisionStatus.ALLOWED
    assert decision.vote_tally == {"approve": 1, "reject": 0, "abstain": 0}
    assert decision.commit_agent_ids == ["god-review"]
    assert decision.duplicate_message_ids == ["msg-commit-b", "msg-vote-b"]


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
