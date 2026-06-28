from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.review_trigger_verdicts import build_review_trigger_verdict_envelope
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


def _a2a_provider_result_with_proposal(
    *,
    proposal_payload: dict,
) -> ProviderInvocationResult:
    provider_result = _a2a_provider_result()
    diagnostic = dict(provider_result.diagnostic_payload)
    metadata = dict(diagnostic["a2a_metadata"])
    metadata["xmuse_proposal"] = proposal_payload
    diagnostic["a2a_metadata"] = metadata
    diagnostic["a2a_content"] = "Remote A2A provider returned a structured proposal."
    return provider_result.model_copy(update={"diagnostic_payload": diagnostic})


def _a2a_provider_result_with_review_handoff(
    *,
    metadata: dict[str, object] | None = None,
) -> ProviderInvocationResult:
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
            "a2a_metadata": dict(metadata or {}),
            "a2a_source_refs": ["a2a_task:req-a2a-architect"],
            "a2a_sdk_task": {
                "id": "req-a2a-architect",
                "status": {"state": "TASK_STATE_COMPLETED"},
            },
            "a2a_jsonrpc_id": "req-a2a-architect",
        },
    )


def _a2a_provider_result_with_review_verdict(
    *,
    review_trigger_inbox_id: str,
    source_message_id: str,
    proposal_id: str,
) -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request_id="req-a2a-review-verdict",
        provider_id=ProviderId.A2A,
        profile_id=ProviderProfileId.REMOTE,
        status=WorkerResultStatus.COMPLETED,
        evidence_refs=[
            "a2a_task:req-a2a-review-verdict",
            "a2a_context:conv-a2a",
        ],
        diagnostic_payload={
            "a2a_task_id": "req-a2a-review-verdict",
            "a2a_context_id": "conv-a2a",
            "a2a_state": "TASK_STATE_COMPLETED",
            "a2a_disposition": "completed",
            "a2a_terminal": True,
            "a2a_content": "A2A review verdict: dispatch allowed.",
            "a2a_artifacts": [],
            "a2a_history": [],
            "a2a_metadata": {
                "xmuse_review_trigger_verdict": build_review_trigger_verdict_envelope(
                    review_trigger_inbox_id=review_trigger_inbox_id,
                    source_message_id=source_message_id,
                    proposal_id=proposal_id,
                    decision="dispatch_allowed",
                    summary="A2A review verdict is structured and source-linked.",
                    evidence_refs=[
                        f"inbox:{review_trigger_inbox_id}",
                        f"proposal:{proposal_id}",
                        "a2a_task:req-a2a-review-verdict",
                    ],
                )
            },
            "a2a_source_refs": ["a2a_task:req-a2a-review-verdict"],
            "a2a_sdk_task": {
                "id": "req-a2a-review-verdict",
                "status": {"state": "TASK_STATE_COMPLETED"},
            },
            "a2a_jsonrpc_id": "req-a2a-review-verdict",
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


def test_a2a_provider_metadata_proposal_enters_proposal_authority(
    tmp_path: Path,
) -> None:
    db, chat, conversation, participant, inbox_item = _setup_inbox(tmp_path)

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        reply_to_inbox_item_id=inbox_item.id,
        provider_result=_a2a_provider_result_with_proposal(
            proposal_payload={
                "schema_version": 1,
                "proposal_type": "lane_graph",
                "summary": "A2A lane graph candidate",
                "content": {
                    "summary": "A2A lane graph candidate",
                    "lanes": [
                        {
                            "feature_id": "a2a-proposal-lane",
                            "prompt": "Validate structured A2A proposal writeback.",
                            "depends_on": [],
                            "capabilities": ["code", "test"],
                            "gate_profiles": ["xmuse-core"],
                        }
                    ],
                },
                "references": ["artifact:a2a-proposal"],
            },
        ),
    )

    assert result["proposal_writeback"]["status"] == "accepted"
    assert result["proposal_writeback"]["authority"] == "chat.db/proposal"
    assert result["proposal_writeback"]["a2a_is_authority"] is False
    [proposal] = ChatStore(db).list_proposals(conversation.id)
    assert proposal.author == participant.participant_id
    assert proposal.proposal_type == "lane_graph"
    assert proposal.status.value == "open"
    assert "inbox:" + inbox_item.id in proposal.references
    assert "a2a_task:req-a2a-review" in proposal.references
    assert "artifact:a2a-proposal" in proposal.references
    assert json.loads(proposal.content)["lanes"][0]["feature_id"] == "a2a-proposal-lane"
    assert json.loads(proposal.content)["lanes"][0]["gate_profiles"] == ["xmuse-core"]
    writeback = result["message"]
    assert writeback["envelope_type"] == "a2a_provider_result"
    assert writeback["envelope_json"]["proposal_writeback"]["proposal_id"] == proposal.id
    updated = ChatInboxStore(db).get(inbox_item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == writeback["id"]
    [review_item] = [
        item
        for item in ChatInboxStore(db).list_by_conversation(
            conversation.id,
            include_terminal=True,
        )
        if item.item_type == "review_trigger"
    ]
    assert 'gate_profiles=["xmuse-core"]' in review_item.payload["content"]


def test_a2a_lane_graph_proposal_missing_gate_profiles_blocks_without_proposal(
    tmp_path: Path,
) -> None:
    db, _chat, conversation, participant, inbox_item = _setup_inbox(tmp_path)

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        reply_to_inbox_item_id=inbox_item.id,
        provider_result=_a2a_provider_result_with_proposal(
            proposal_payload={
                "schema_version": 1,
                "proposal_type": "lane_graph",
                "summary": "Ungated A2A lane graph candidate",
                "content": {
                    "summary": "Ungated A2A lane graph candidate",
                    "lanes": [
                        {
                            "feature_id": "a2a-ungated-lane",
                            "prompt": "This must not become dispatchable.",
                            "depends_on": [],
                            "capabilities": ["code", "test"],
                        }
                    ],
                },
                "references": ["artifact:a2a-ungated-proposal"],
            },
        ),
    )

    assert ChatStore(db).list_proposals(conversation.id) == []
    blocked = result["proposal_writeback"]
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "missing_gate_profiles"
    assert "missing_gate_profiles" in blocked["detail"]
    assert blocked["authority"] == "chat.db/inbox"
    assert blocked["a2a_is_authority"] is False
    assert result["message"]["envelope_json"]["proposal_writeback"]["status"] == "blocked"
    updated = ChatInboxStore(db).get(inbox_item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == result["message"]["id"]


def test_invalid_a2a_provider_proposal_metadata_blocks_without_proposal(
    tmp_path: Path,
) -> None:
    db, _chat, conversation, participant, inbox_item = _setup_inbox(tmp_path)

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        reply_to_inbox_item_id=inbox_item.id,
        provider_result=_a2a_provider_result_with_proposal(
            proposal_payload={
                "schema_version": 1,
                "proposal_type": "lane_graph",
                "summary": "Invalid A2A lane graph candidate",
                "content": {"summary": "missing lanes"},
            },
        ),
    )

    assert ChatStore(db).list_proposals(conversation.id) == []
    blocked = result["proposal_writeback"]
    assert blocked["status"] == "blocked"
    assert blocked["reason"] == "invalid_xmuse_proposal"
    assert blocked["authority"] == "chat.db/inbox"
    assert blocked["a2a_is_authority"] is False
    assert result["message"]["envelope_json"]["proposal_writeback"]["status"] == "blocked"
    updated = ChatInboxStore(db).get(inbox_item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == result["message"]["id"]


def test_a2a_review_trigger_verdict_reconciles_to_review_authority(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    created = service.create_conversation(title="A2A review verdict")
    conversation_id = created["conversation"]["id"]
    participants = {
        participant["role"]: participant["participant_id"]
        for participant in created["participants"]
    }
    intake = ChatStore(db).add_message(
        conversation_id,
        "human",
        "human",
        "Please prove A2A review verdict authority.",
    )
    AcceptanceSpineStore(db).create_for_intake(
        conversation_id=conversation_id,
        intake_message_id=intake.id,
    )
    proposal = service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=participants["architect"],
        client_request_id="a2a-review-verdict-proposal",
        summary="A2A review verdict proposal",
        lanes=[
            {
                "feature_id": "a2a-review-verdict",
                "prompt": "Prove A2A verdicts must enter review authority.",
                "depends_on": [],
                "capabilities": ["code", "test"],
            }
        ],
        references=[f"intake_message:{intake.id}"],
    )
    review_item = next(
        item
        for item in ChatInboxStore(db).list_by_conversation(conversation_id)
        if item.item_type == "review_trigger"
    )

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation_id,
        participant_id=participants["review"],
        reply_to_inbox_item_id=review_item.id,
        provider_result=_a2a_provider_result_with_review_verdict(
            review_trigger_inbox_id=review_item.id,
            source_message_id=review_item.source_message_id,
            proposal_id=proposal["proposal"]["id"],
        ),
    )

    response = result["message"]
    assert response["author"] == participants["review"]
    assert response["envelope_type"] == "review_trigger_verdict"
    assert response["envelope_json"]["type"] == "review_trigger_verdict"
    assert response["envelope_json"]["review_trigger_inbox_id"] == review_item.id
    assert response["envelope_json"]["a2a_source_refs"] == [
        "a2a_task:req-a2a-review-verdict",
        "a2a_context:conv-a2a",
    ]
    updated = ChatInboxStore(db).get(review_item.id)
    assert updated.status == "read"
    assert updated.responded_message_id == response["id"]
    spine = AcceptanceSpineStore(db).list_by_conversation(conversation_id)[0]
    assert spine.status is AcceptanceSpineStatus.REVIEW_CLEARED
    assert spine.review_or_execute_verdict_ref == (f"review_trigger_verdict:{response['id']}")
    assert ChatStore(db).list_proposals(conversation_id)[0].status.value == "open"


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
        provider_result=_a2a_provider_result_with_review_handoff(
            metadata={"feature_scope_id": "feature_scope:a2a-provider"}
        ),
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
    assert routed["payload"]["handoff_envelope"]["source_inbox_item_id"] == (source_inbox.id)
    assert routed["payload"]["handoff_envelope"]["feature_scope_id"] == "feature_scope:a2a-provider"
    stored_review_items = [
        item
        for item in ChatInboxStore(db).list_by_conversation(conversation.id)
        if item.target_participant_id == review.participant_id
    ]
    assert len(stored_review_items) == 1
    assert stored_review_items[0].payload["route_key"] == routed["payload"]["route_key"]
    assert ChatStore(db).list_proposals(conversation.id) == []


def test_a2a_provider_result_fanout_excess_writes_durable_route_blocker(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A provider fanout guard")
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
    execute = participants.add(
        conversation_id=conversation.id,
        role="execute",
        display_name="Execute GOD",
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
    provider_result = _a2a_provider_result_with_review_handoff()
    diagnostic = dict(provider_result.diagnostic_payload)
    diagnostic["a2a_content"] = (
        "@review, @execute\n"
        "what: Review and execute the A2A handoff candidate.\n"
        "why: This intentionally exceeds the provider-result fanout cap.\n"
        "tradeoffs: Keep multi-target routing blocked until explicitly split.\n"
        "open_questions: none.\n"
        "next_action: Record a durable route blocker.\n"
        "evidence_refs: a2a_task:req-a2a-architect"
    )

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        reply_to_inbox_item_id=source_inbox.id,
        provider_result=provider_result.model_copy(update={"diagnostic_payload": diagnostic}),
    )

    assert result["inbox_items"] == []
    blocker = result["message"]["envelope_json"]["route_blocker"]
    assert blocker == result["route_blocker"]
    assert blocker["reason"] == "a2a_provider_result_fanout_exceeded"
    assert blocker["max_fanout"] == 1
    assert blocker["target_participant_ids"] == [
        review.participant_id,
        execute.participant_id,
    ]
    assert blocker["target_addresses"] == ["@review", "@execute"]
    assert blocker["authority"] == "chat.db/inbox"
    assert blocker["a2a_is_authority"] is False
    assert blocker["blocks_dispatch"] is True
    assert ChatInboxStore(db).get(source_inbox.id).status == "read"
    assert [
        item
        for item in ChatInboxStore(db).list_by_conversation(
            conversation.id,
            include_terminal=True,
        )
        if item.source_message_id == result["message"]["id"]
    ] == []


def test_a2a_provider_result_markdown_leading_mention_creates_durable_route(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A2A markdown provider route")
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
    provider_result = _a2a_provider_result_with_review_handoff()
    diagnostic = dict(provider_result.diagnostic_payload)
    diagnostic["a2a_content"] = (
        "- @review\n"
        "what: Review the A2A handoff candidate.\n"
        "why: The next step needs independent review before dispatch.\n"
        "tradeoffs: Keep this as an inbox handoff, not approval.\n"
        "open_questions: none.\n"
        "next_action: Record a structured review verdict.\n"
        "evidence_refs: a2a_task:req-a2a-architect"
    )

    result = A2AProviderWritebackReconciler(db).record_provider_result(
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        reply_to_inbox_item_id=source_inbox.id,
        provider_result=provider_result.model_copy(update={"diagnostic_payload": diagnostic}),
    )

    response = result["message"]
    assert response["mentions"] == ["@review"]
    routed = result["inbox_items"][0]
    assert routed["target_participant_id"] == review.participant_id
    assert routed["target_role"] == "review"
    assert routed["payload"]["route_kind"] == "review_request"
    assert routed["payload"]["handoff_assessment"]["is_complete"] is True


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
