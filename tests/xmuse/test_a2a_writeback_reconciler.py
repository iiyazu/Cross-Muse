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
