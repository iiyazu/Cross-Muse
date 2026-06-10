from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.chat.protocol_v2 import (
    GodSpeechAct,
    GodSpeechActMessageV1,
    dedupe_god_speech_act_messages,
    derive_active_challenge_tasks,
    derive_unanswered_reply_blockers,
    sort_god_speech_act_messages,
)


def test_god_speech_act_message_serialization_and_idempotency_are_stable() -> None:
    message = _message(
        "msg-2",
        speech_act=GodSpeechAct.CHALLENGE,
        sender_god="god-review",
        targets=["god-architect"],
        causal_parent_id="msg-1",
        references=["blueprint:bp-1:1"],
        memory_refs=["memory://conversation/conv-1/decision/1"],
        payload={"question": "Which evidence proves this assumption?"},
        requires_reply_by=9,
    )
    duplicate = message.model_copy(update={"message_id": "msg-duplicate"})

    assert message.stable_json() == (
        '{"causal_parent_id":"msg-1","confidence":0.82,'
        '"conversation_id":"conv-1","lane_scope":null,'
        '"memory_refs":["memory://conversation/conv-1/decision/1"],'
        '"message_id":"msg-2",'
        '"payload":{"question":"Which evidence proves this assumption?"},'
        '"references":["blueprint:bp-1:1"],"requires_reply_by":9,'
        '"sender_god":"god-review","speech_act":"challenge",'
        '"targets":["god-architect"],"thread_id":"thread-1",'
        '"version":"god_speech_act_message.v1"}'
    )
    assert message.idempotency_key() == duplicate.idempotency_key()


def test_god_speech_act_supports_required_act_set_and_validates_shape() -> None:
    for speech_act in GodSpeechAct:
        payload = {"body": f"{speech_act.value} payload"}
        kwargs = {}
        if speech_act in {GodSpeechAct.CHALLENGE, GodSpeechAct.OBJECT}:
            kwargs["causal_parent_id"] = "msg-parent"
        if speech_act is GodSpeechAct.VOTE:
            payload = {"vote": "approve"}
        message = _message(
            f"msg-{speech_act.value}",
            speech_act=speech_act,
            payload=payload,
            **kwargs,
        )
        assert message.speech_act is speech_act

    with pytest.raises(ValidationError):
        _message(
            "msg-bad-object",
            speech_act=GodSpeechAct.OBJECT,
            causal_parent_id=None,
            references=[],
        )

    with pytest.raises(ValidationError):
        _message("msg-bad-vote", speech_act=GodSpeechAct.VOTE, payload={"vote": "maybe"})


def test_god_speech_act_sorting_preserves_causal_parent_before_child() -> None:
    parent = _message("msg-parent", speech_act=GodSpeechAct.PROPOSE)
    child = _message(
        "msg-child",
        speech_act=GodSpeechAct.CHALLENGE,
        causal_parent_id=parent.message_id,
    )

    assert [message.message_id for message in sort_god_speech_act_messages([child, parent])] == [
        "msg-parent",
        "msg-child",
    ]


def test_proposal_with_unverified_assumptions_derives_review_challenge_task() -> None:
    proposal = _message(
        "msg-proposal",
        speech_act=GodSpeechAct.PROPOSE,
        payload={
            "summary": "Adopt the new execution path.",
            "unverified_assumptions": ["GitHub branch protection exists"],
        },
        references=["source:human-request"],
    )

    tasks = derive_active_challenge_tasks([proposal], review_god="god-review")

    assert len(tasks) == 1
    assert tasks[0].task_id == "challenge:msg-proposal:god-review"
    assert tasks[0].assigned_to == "god-review"
    assert tasks[0].target_message_id == "msg-proposal"
    assert tasks[0].source_refs == ["message:msg-proposal", "source:human-request"]


def test_existing_challenge_satisfies_active_challenge_task_derivation() -> None:
    proposal = _message(
        "msg-proposal",
        speech_act=GodSpeechAct.PROPOSE,
        payload={"assumptions": ["MemoryOS service is reachable"]},
    )
    challenge = _message(
        "msg-challenge",
        speech_act=GodSpeechAct.CHALLENGE,
        sender_god="god-review",
        causal_parent_id=proposal.message_id,
        payload={"question": "Where is the service health evidence?"},
    )

    assert derive_active_challenge_tasks([proposal, challenge]) == []


def test_unanswered_required_replies_become_blockers_and_replies_resolve_them() -> None:
    ask = _message(
        "msg-ask",
        speech_act=GodSpeechAct.ASK,
        sender_god="god-review",
        targets=["god-architect", "god-execute"],
        payload={"question": "Confirm acceptance evidence."},
        requires_reply_by=5,
    )
    architect_reply = _message(
        "msg-reply",
        speech_act=GodSpeechAct.EVIDENCE,
        sender_god="god-architect",
        targets=["god-review"],
        causal_parent_id=ask.message_id,
        payload={"evidence": "contract tests exist"},
    )

    blockers = derive_unanswered_reply_blockers(
        [ask, architect_reply],
        current_lamport=6,
    )
    resolved = derive_unanswered_reply_blockers(
        [
            ask,
            architect_reply,
            _message(
                "msg-execute-reply",
                speech_act=GodSpeechAct.EVIDENCE,
                sender_god="god-execute",
                targets=["god-review"],
                causal_parent_id=ask.message_id,
                payload={"evidence": "execution plan is bounded"},
            ),
        ],
        current_lamport=6,
    )

    assert len(blockers) == 1
    assert blockers[0].blocker_id == "reply-blocker:msg-ask"
    assert blockers[0].missing_targets == ["god-execute"]
    assert blockers[0].blocks_dispatch is True
    assert resolved == []


def test_duplicate_speech_acts_are_reported_by_content() -> None:
    message = _message("msg-a", speech_act=GodSpeechAct.EVIDENCE)
    duplicate = message.model_copy(update={"message_id": "msg-b"})

    unique, duplicate_ids = dedupe_god_speech_act_messages([duplicate, message])

    assert [item.message_id for item in unique] == ["msg-a"]
    assert duplicate_ids == ["msg-b"]


def _message(
    message_id: str,
    *,
    speech_act: GodSpeechAct,
    sender_god: str = "god-architect",
    targets: list[str] | None = None,
    references: list[str] | None = None,
    causal_parent_id: str | None = None,
    memory_refs: list[str] | None = None,
    requires_reply_by: int | None = None,
    payload: dict[str, object] | None = None,
) -> GodSpeechActMessageV1:
    return GodSpeechActMessageV1(
        message_id=message_id,
        conversation_id="conv-1",
        thread_id="thread-1",
        sender_god=sender_god,
        targets=targets or ["god-review"],
        speech_act=speech_act,
        references=references or [],
        causal_parent_id=causal_parent_id,
        lane_scope=None,
        confidence=0.82,
        memory_refs=memory_refs or [],
        requires_reply_by=requires_reply_by,
        payload=payload if payload is not None else {"body": "Discuss the proposal."},
    )
