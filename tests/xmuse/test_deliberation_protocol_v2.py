from __future__ import annotations

import pytest
from pydantic import ValidationError

from xmuse_core.chat.protocol_v2 import (
    DeliberationMessageKind,
    DeliberationMessageV1,
    ObjectionLevel,
    sort_deliberation_messages,
)


def test_deliberation_message_serialization_and_idempotency_are_stable() -> None:
    message = DeliberationMessageV1(
        msg_id="msg-2",
        conversation_id="conv-1",
        agent_id="god-review",
        lamport_ts=7,
        kind=DeliberationMessageKind.CHALLENGE,
        parent_id="msg-1",
        target_ref="blueprint:conv-1:1",
        mentions=["god-architect"],
        payload={"question": "What acceptance evidence proves freeze readiness?"},
        source_refs=["message:msg-1"],
        objection_level=ObjectionLevel.BLOCKING,
        decision_scope="blueprint.freeze",
    )
    same_content_different_msg_id = message.model_copy(update={"msg_id": "msg-duplicate"})

    assert message.stable_json() == (
        '{"agent_id":"god-review","conversation_id":"conv-1",'
        '"decision_scope":"blueprint.freeze","kind":"challenge",'
        '"lamport_ts":7,"mentions":["god-architect"],"msg_id":"msg-2",'
        '"objection_level":"blocking","parent_id":"msg-1",'
        '"payload":{"question":"What acceptance evidence proves freeze readiness?"},'
        '"source_refs":["message:msg-1"],"target_ref":"blueprint:conv-1:1",'
        '"version":"deliberation_message.v1"}'
    )
    assert message.idempotency_key() == same_content_different_msg_id.idempotency_key()


def test_deliberation_messages_sort_by_lamport_then_msg_id() -> None:
    messages = [
        _message("msg-c", lamport_ts=2),
        _message("msg-b", lamport_ts=1),
        _message("msg-a", lamport_ts=1),
    ]

    assert [msg.msg_id for msg in sort_deliberation_messages(messages)] == [
        "msg-a",
        "msg-b",
        "msg-c",
    ]


def test_deliberation_message_rejects_invalid_payloads_and_refs() -> None:
    with pytest.raises(ValidationError):
        _message("msg-empty", payload={})

    with pytest.raises(ValidationError):
        _message("msg-bad-kind", kind="unsupported")  # type: ignore[arg-type]

    with pytest.raises(ValidationError):
        _message("msg-bad-ref", source_refs=[""])

    with pytest.raises(ValidationError):
        _message("msg-bad-vote", kind=DeliberationMessageKind.VOTE, payload={"vote": "maybe"})


def test_vote_and_commit_payloads_are_explicit() -> None:
    vote = _message("msg-vote", kind=DeliberationMessageKind.VOTE, payload={"vote": "approve"})
    commit = _message(
        "msg-commit",
        kind=DeliberationMessageKind.COMMIT,
        target_ref="blueprint:conv-1:1",
        payload={"commitment": "ready_to_freeze"},
    )

    assert vote.kind is DeliberationMessageKind.VOTE
    assert commit.target_ref == "blueprint:conv-1:1"


def _message(
    msg_id: str,
    *,
    lamport_ts: int = 1,
    kind: DeliberationMessageKind | str = DeliberationMessageKind.NOTE,
    target_ref: str | None = None,
    payload: dict[str, object] | None = None,
    source_refs: list[str] | None = None,
) -> DeliberationMessageV1:
    return DeliberationMessageV1(
        msg_id=msg_id,
        conversation_id="conv-1",
        agent_id="god-architect",
        lamport_ts=lamport_ts,
        kind=kind,
        parent_id=None,
        target_ref=target_ref,
        mentions=[],
        payload=payload if payload is not None else {"body": "Discuss the blueprint."},
        source_refs=source_refs or ["message:root"],
        objection_level=ObjectionLevel.NONE,
        decision_scope="blueprint",
    )
