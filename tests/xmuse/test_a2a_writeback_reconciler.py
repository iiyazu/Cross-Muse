from __future__ import annotations

from pathlib import Path

import pytest

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.integrations.a2a_writeback_reconciler import (
    A2AProviderWritebackReconciler,
    A2AWritebackReconcilerError,
)
from xmuse_core.providers.adapters.base import ProviderInvocationResult
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderId, ProviderProfileId


def _setup_inbox(tmp_path: Path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A writeback")
    participant = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    source = chat.add_message(
        conversation.id,
        "a2a:remote-planner",
        "assistant",
        "@review inspect the result.",
        envelope_type="a2a_task",
        envelope_json={
            "type": "a2a_task",
            "source_refs": ["a2a_task:task-review"],
        },
        mentions=["@review"],
    )
    inbox_item = ChatInboxStore(db).create_item(
        conversation_id=conversation.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@review",
        sender_participant_id=None,
        sender_address="a2a:remote-planner",
        source_message_id=source.id,
        item_type="a2a_task",
        payload={
            "content": source.content,
            "source_refs": ["a2a_task:task-review"],
        },
    )
    return db, chat, conversation, participant, inbox_item


def _a2a_provider_result() -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request_id="req-a2a-review",
        provider_id=ProviderId.A2A,
        profile_id=ProviderProfileId.REMOTE,
        status=WorkerResultStatus.COMPLETED,
        evidence_refs=[
            "a2a_task:req-a2a-review",
            "a2a_context:conv-a2a",
            "a2a_state:TASK_STATE_COMPLETED",
        ],
        diagnostic_payload={
            "a2a_task_id": "req-a2a-review",
            "a2a_context_id": "conv-a2a",
            "a2a_state": "TASK_STATE_COMPLETED",
            "a2a_disposition": "completed",
            "a2a_terminal": True,
            "a2a_content": "Remote A2A review says the handoff is bounded.",
            "a2a_artifacts": [{"artifact_id": "artifact-review", "text": "bounded"}],
            "a2a_history": [{"message_id": "message-review", "text": "bounded"}],
            "a2a_metadata": {"purpose": "review_request"},
            "a2a_source_refs": ["a2a_task:req-a2a-review", "a2a_context:conv-a2a"],
            "a2a_sdk_task": {
                "id": "req-a2a-review",
                "status": {"state": "TASK_STATE_COMPLETED"},
            },
            "a2a_jsonrpc_id": "req-a2a-review",
        },
    )


def _a2a_provider_result_with_review_handoff() -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request_id="req-a2a-architect",
        provider_id=ProviderId.A2A,
        profile_id=ProviderProfileId.REMOTE,
        status=WorkerResultStatus.COMPLETED,
        evidence_refs=[
            "a2a_task:req-a2a-architect",
            "a2a_context:conv-a2a",
        ],
        diagnostic_payload={
            "a2a_task_id": "req-a2a-architect",
            "a2a_context_id": "conv-a2a",
            "a2a_state": "TASK_STATE_COMPLETED",
            "a2a_disposition": "completed",
            "a2a_terminal": True,
            "a2a_content": (
                "@review Please inspect this candidate.\n"
                "what: Review the A2A handoff candidate.\n"
                "why: The next step needs independent review before dispatch.\n"
                "tradeoffs: Keep this as an inbox handoff, not approval.\n"
                "open_questions: none.\n"
                "next_action: Record a structured review verdict.\n"
                "evidence_refs: a2a_task:req-a2a-architect"
            ),
            "a2a_artifacts": [{"artifact_id": "artifact-candidate", "text": "bounded"}],
            "a2a_history": [],
            "a2a_metadata": {},
            "a2a_source_refs": ["a2a_task:req-a2a-architect"],
            "a2a_sdk_task": {
                "id": "req-a2a-architect",
                "status": {"state": "TASK_STATE_COMPLETED"},
            },
            "a2a_jsonrpc_id": "req-a2a-architect",
        },
    )


def test_a2a_provider_result_reconciles_to_durable_inbox_writeback(
    tmp_path: Path,
) -> None:
    db, chat, conversation, participant, inbox_item = _setup_inbox(tmp_path)

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        reply_to_inbox_item_id=inbox_item.id,
        provider_result=_a2a_provider_result(),
    )

    response = result["message"]
    assert response["author"] == participant.participant_id
    assert response["role"] == "assistant"
    assert response["content"] == "Remote A2A review says the handoff is bounded."
    assert response["envelope_type"] == "a2a_provider_result"
    assert response["envelope_json"]["a2a_is_authority"] is False
    assert response["envelope_json"]["authority"] == "chat.db/inbox"
    assert response["envelope_json"]["provider_status"] == "completed"
    assert response["envelope_json"]["source_refs"] == [
        "a2a_task:req-a2a-review",
        "a2a_context:conv-a2a",
        "a2a_state:TASK_STATE_COMPLETED",
    ]
    assert response["envelope_json"]["diagnostic_payload"]["a2a_artifacts"] == [
        {"artifact_id": "artifact-review", "text": "bounded"}
    ]
    assert result["a2a_writeback"] == {
        "provider_request_id": "req-a2a-review",
        "provider_profile_ref": "a2a.remote",
        "provider_status": "completed",
        "source_refs": [
            "a2a_task:req-a2a-review",
            "a2a_context:conv-a2a",
            "a2a_state:TASK_STATE_COMPLETED",
        ],
        "authority": "chat.db/inbox",
        "a2a_is_authority": False,
    }
    updated = ChatInboxStore(db).get(inbox_item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == response["id"]
    assert ChatStore(db).list_proposals(conversation.id) == []
    assert AcceptanceSpineStore(db).list_by_conversation(conversation.id) == []
    assert chat.list_messages(conversation.id)[-1].id == response["id"]


def test_a2a_provider_result_leading_mention_creates_durable_route(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A provider route")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="A2A Architect",
        cli_kind="a2a",
        model="a2a-remote",
    )
    review = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    source = chat.add_message(
        conversation.id,
        "human",
        "human",
        "@architect create a candidate.",
    )
    source_inbox = ChatInboxStore(db).create_item(
        conversation_id=conversation.id,
        target_participant_id=architect.participant_id,
        target_role=architect.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload={"content": source.content},
    )

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        reply_to_inbox_item_id=source_inbox.id,
        provider_result=_a2a_provider_result_with_review_handoff(),
    )

    response = result["message"]
    assert response["mentions"] == ["@review"]
    routed = result["inbox_items"][0]
    assert routed["target_participant_id"] == review.participant_id
    assert routed["target_role"] == "review"
    assert routed["sender_participant_id"] == architect.participant_id
    assert routed["payload"]["source_kind"] == "a2a_provider_result"
    assert routed["payload"]["route_kind"] == "review_request"
    assert routed["payload"]["source_a2a_provider_request_id"] == "req-a2a-architect"
    assert routed["payload"]["natural_route"]["source_refs"] == [
        f"inbox:{source_inbox.id}",
        "a2a_task:req-a2a-architect",
        "a2a_context:conv-a2a",
    ]
    assert routed["payload"]["handoff_assessment"]["is_complete"] is True
    assert routed["payload"]["handoff_envelope"]["source_inbox_item_id"] == (
        source_inbox.id
    )
    stored_review_items = [
        item
        for item in ChatInboxStore(db).list_by_conversation(conversation.id)
        if item.target_participant_id == review.participant_id
    ]
    assert len(stored_review_items) == 1
    assert stored_review_items[0].payload["route_key"] == routed["payload"]["route_key"]
    assert ChatStore(db).list_proposals(conversation.id) == []


def test_a2a_provider_writeback_is_idempotent_by_request_and_inbox(
    tmp_path: Path,
) -> None:
    db, chat, conversation, participant, inbox_item = _setup_inbox(tmp_path)
    reconciler = A2AProviderWritebackReconciler(db)

    first = reconciler.record_provider_result(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        reply_to_inbox_item_id=inbox_item.id,
        provider_result=_a2a_provider_result(),
    )
    second = reconciler.record_provider_result(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        reply_to_inbox_item_id=inbox_item.id,
        provider_result=_a2a_provider_result(),
    )

    assert second == first
    assert len(chat.list_messages(conversation.id)) == 2


def test_a2a_provider_writeback_rejects_non_a2a_result_before_write(
    tmp_path: Path,
) -> None:
    db, chat, conversation, participant, inbox_item = _setup_inbox(tmp_path)
    non_a2a = ProviderInvocationResult(
        request_id="req-codex-review",
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.REVIEW,
        status=WorkerResultStatus.COMPLETED,
    )

    with pytest.raises(A2AWritebackReconcilerError, match="unsupported_provider_result"):
        A2AProviderWritebackReconciler(db).record_provider_result(
            conversation_id=conversation.id,
            participant_id=participant.participant_id,
            reply_to_inbox_item_id=inbox_item.id,
            provider_result=non_a2a,
        )

    assert ChatInboxStore(db).get(inbox_item.id).status == "unread"
    assert len(chat.list_messages(conversation.id)) == 1
