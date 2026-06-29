from __future__ import annotations

import sqlite3

import pytest

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.groupchat_runtime import GroupchatPeerRuntime
from xmuse_core.chat.groupchat_worklist import (
    GroupchatWorklistScheduler,
    GroupchatWorklistStore,
)
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.providers.adapters.base import ProviderInvocationResult
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderId, ProviderProfileId


def _conversation_with_groupchat_roster(
    tmp_path,
    *,
    root_content: str = "Please discuss the next A1 boundary.",
):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A1 kernel")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    review = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    critic = participants.add(
        conversation_id=conversation.id,
        role="critic",
        display_name="Critic GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    root = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content=root_content,
    )
    return db, chat, conversation, root, architect, review, critic


def _writeback_reply(
    chat: ChatStore,
    *,
    conversation_id: str,
    participant_id: str,
    inbox_item_id: str,
    content: str,
    client_request_id: str = "structured-writeback-1",
) -> str:
    result = chat.create_message_inbox_and_log(
        conversation_id=conversation_id,
        tool_name="chat_post_message",
        caller_identity=participant_id,
        client_request_id=client_request_id,
        author=participant_id,
        role="assistant",
        content=content,
        envelope_type="message",
        envelope_json={
            "writeback_path": "groupchat_worklist_test",
            "reply_to_inbox_item_id": inbox_item_id,
        },
        mentions=[],
        inbox_items=[],
        reply_to_inbox_item_id=inbox_item_id,
        reply_owner_participant_id=participant_id,
    )
    return result["message"]["id"]


def _acceptance_spine_for_dispatch(
    db,
    *,
    conversation_id: str,
    intake_message_id: str,
    proposal_id: str,
    dispatch_item_id: str,
) -> str:
    store = AcceptanceSpineStore(db)
    spine = store.create_for_intake(
        conversation_id=conversation_id,
        intake_message_id=intake_message_id,
    )
    store.attach_proposal(
        conversation_id=conversation_id,
        intake_message_id=intake_message_id,
        proposal_id=proposal_id,
    )
    store.attach_dispatch_for_proposal(
        proposal_id=proposal_id,
        dispatch_item_id=dispatch_item_id,
    )
    return f"chat.db#acceptance_spine={spine.spine_id}"


def test_groupchat_worklist_claims_links_and_completes_from_durable_writeback(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    item = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )

    linked = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).claim_and_link_one(chain_id=chain.chain_id)

    assert linked is not None
    assert linked.item_id == item.item_id
    assert linked.status == "claimed"
    assert linked.claim_owner == "groupchat-a1"
    assert linked.inbox_item_id is not None

    inbox_item = ChatInboxStore(db).get(linked.inbox_item_id)
    assert inbox_item.item_type == "groupchat_route"
    assert inbox_item.target_participant_id == architect.participant_id
    assert inbox_item.payload["groupchat_worklist_item_id"] == item.item_id

    reply_id = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=linked.inbox_item_id,
        content="@critic I propose we inspect the worklist boundary first.",
    )
    completed = store.complete_item(item.item_id, completed_message_id=reply_id)

    assert completed.status == "completed"
    assert completed.completed_message_id == reply_id
    assert store.get_chain(chain.chain_id).status == "open"

    routed = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == reply_id
    assert routed[0].target_participant_id == _critic.participant_id
    assert routed[0].route_kind == "mention"
    assert routed[0].depth == 1
    assert store.get_chain(chain.chain_id).last_scanned_message_id == reply_id


def test_groupchat_proposal_emitted_from_worklist_inbox_carries_source_refs(tmp_path):
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    created = service.create_conversation(title="A2 proposal refs")
    conversation_id = created["conversation"]["id"]
    participants = {item["role"]: item for item in created["participants"]}
    sessions = {
        item["role"]: item["god_session_id"] for item in created["participant_sessions"]
    }
    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="human-1",
        content="Discuss and propose the next groupchat decision boundary.",
        client_request_id="groupchat-a2-source-ref-intake",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(
        conversation_id=conversation_id,
        root_message_id=intake.message.id,
    )
    item = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=intake.message.id,
        target_participant_id=participants["architect"]["participant_id"],
        route_kind="router",
        depth=0,
    )
    linked = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a2",
    ).claim_and_link_one(chain_id=chain.chain_id)
    assert linked is not None
    assert linked.inbox_item_id is not None

    proposal = service.emit_proposal(
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation_id,
        participant_id=participants["architect"]["participant_id"],
        god_session_id=sessions["architect"],
        client_request_id="groupchat-a2-source-ref-proposal",
        summary="Preserve groupchat source refs on durable proposals",
        lanes=[
            {
                "feature_id": "groupchat-a2-source-refs",
                "prompt": "Carry groupchat worklist authority refs into proposals.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
        references=[f"intake_message:{intake.message.id}"],
        reply_to_inbox_item_id=linked.inbox_item_id,
    )

    expected_refs = {
        f"intake_message:{intake.message.id}",
        f"groupchat_chain:{chain.chain_id}",
        f"groupchat_worklist:{item.item_id}",
    }
    proposal_refs = set(proposal["proposal"]["references"])
    message = next(
        msg
        for msg in ChatStore(db).list_messages(conversation_id)
        if msg.id == proposal["message"]["id"]
    )

    assert expected_refs <= proposal_refs
    assert expected_refs <= set(message.envelope_json["references"])


def test_scan_routes_root_human_message_with_local_router_and_advances_cursor(
    tmp_path,
):
    db, _chat, conversation, root, _architect, review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="Please review the A1 acceptance boundary.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    assert chain.last_scanned_message_id is None

    routed = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == root.id
    assert routed[0].target_participant_id == review.participant_id
    assert routed[0].target_role == "review"
    assert routed[0].route_kind == "router"
    assert routed[0].status == "queued"
    assert store.get_chain(chain.chain_id).last_scanned_message_id == root.id


def test_groupchat_tick_runs_scan_delivery_completion_and_followup_scan(tmp_path):
    db, chat, conversation, root, _architect, _review, critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="Please design the next A1 boundary.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    delivered = []

    def durable_writeback(item):
        delivered.append(item)
        assert item.inbox_item_id is not None
        return _writeback_reply(
            chat,
            conversation_id=conversation.id,
            participant_id=item.target_participant_id,
            inbox_item_id=item.inbox_item_id,
            content="@critic Please challenge this A1 tick boundary.",
        )

    outcome = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).tick_once(chain_id=chain.chain_id, deliver=durable_writeback)

    assert outcome.scanned == 1
    assert outcome.claimed_item_id == delivered[0].item_id
    assert outcome.completed_message_id is not None
    assert outcome.followup_scanned == 1
    completed = store.get_item(outcome.claimed_item_id)
    assert completed.status == "completed"
    assert completed.completed_message_id == outcome.completed_message_id
    items = store.list_items(chain.chain_id)
    followups = [
        item
        for item in items
        if item.source_message_id == outcome.completed_message_id
        and item.target_participant_id == critic.participant_id
    ]
    assert len(followups) == 1
    assert followups[0].status == "queued"
    assert followups[0].depth == 1


def test_groupchat_tick_requires_structured_inbox_writeback_to_complete(tmp_path):
    db, _chat, conversation, root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="Please design the next A1 boundary.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    outcome = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).tick_once(
        chain_id=chain.chain_id,
        deliver=lambda _item: "provider_stdout_only",
    )

    assert outcome.failed_item_id is not None
    assert outcome.failure_reason == "callback_missing"
    failed = store.get_item(outcome.failed_item_id)
    assert failed.status == "failed"
    assert failed.terminal_reason == "callback_missing"
    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "callback_missing"


def test_groupchat_tick_rejects_inbox_read_with_unowned_response_message(tmp_path):
    db, chat, conversation, root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="Please design the next A1 boundary.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    def forged_read(item):
        assert item.inbox_item_id is not None
        unrelated = chat.add_message(
            conversation_id=conversation.id,
            author="human",
            role="human",
            content="This is not a participant writeback.",
        )
        ChatInboxStore(db).mark_read(
            item.inbox_item_id,
            responded_message_id=unrelated.id,
        )

    outcome = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).tick_once(chain_id=chain.chain_id, deliver=forged_read)

    assert outcome.failed_item_id is not None
    assert outcome.failure_reason == "callback_missing"
    failed = store.get_item(outcome.failed_item_id)
    assert failed.status == "failed"
    assert failed.terminal_reason == "callback_missing"


@pytest.mark.asyncio
async def test_groupchat_peer_runtime_delivers_linked_inbox_with_a2a_writeback(
    tmp_path,
):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A1 peer runtime")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Remote A2A Architect GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    critic = participants.add(
        conversation_id=conversation.id,
        role="critic",
        display_name="Critic GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    root = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please design the next A1 runtime bridge.",
    )
    chain = GroupchatWorklistStore(db).create_chain(
        conversation_id=conversation.id,
        root_message_id=root.id,
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("A2A participant should use provider writeback")

    class FakeProviderService:
        def __init__(self) -> None:
            self.invocations = []

        def invoke_provider_adapter(self, invocation):
            self.invocations.append(invocation)
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=ProviderId.A2A,
                profile_id=ProviderProfileId.REMOTE,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=[f"a2a_task:{invocation.request_id}"],
                diagnostic_payload={
                    "a2a_task_id": invocation.request_id,
                    "a2a_context_id": invocation.request_id,
                    "a2a_state": "TASK_STATE_COMPLETED",
                    "a2a_disposition": "completed",
                    "a2a_terminal": True,
                    "a2a_content": (
                        "@critic Please challenge whether this runtime bridge "
                        "preserves chat.db authority."
                    ),
                    "a2a_artifacts": [],
                    "a2a_history": [],
                    "a2a_metadata": {},
                    "a2a_source_refs": [f"a2a_task:{invocation.request_id}"],
                    "a2a_sdk_task": {
                        "id": invocation.request_id,
                        "status": {"state": "TASK_STATE_COMPLETED"},
                    },
                    "a2a_jsonrpc_id": invocation.request_id,
                },
            )

    provider_service = FakeProviderService()
    outcome = await GroupchatPeerRuntime(
        db_path=db,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="groupchat-peer-a1",
        response_wait_s=0.1,
        provider_service=provider_service,
    ).tick_once(chain_id=chain.chain_id)

    assert outcome.peer is not None
    assert outcome.peer.happy_path == 1
    assert outcome.worklist.scanned == 1
    assert outcome.worklist.completed_message_id is not None
    assert outcome.worklist.followup_scanned == 1
    [invocation] = provider_service.invocations
    assert invocation.request_id == outcome.worklist.linked_inbox_item_id
    assert invocation.writeback_context is not None
    assert invocation.writeback_context.reply_to_inbox_item_id == (
        outcome.worklist.linked_inbox_item_id
    )
    assert invocation.runtime_context["authority"] == "chat.db/inbox"
    assert invocation.runtime_context["a2a_is_authority"] is False

    completed = GroupchatWorklistStore(db).get_item(outcome.worklist.claimed_item_id)
    assert completed.status == "completed"
    assert completed.target_participant_id == architect.participant_id
    assert completed.completed_message_id == outcome.worklist.completed_message_id
    provider_reply = next(
        message
        for message in chat.list_messages(conversation.id)
        if message.id == outcome.worklist.completed_message_id
    )
    assert provider_reply.author == architect.participant_id
    assert provider_reply.envelope_type == "a2a_provider_result"
    assert provider_reply.envelope_json["authority"] == "chat.db/inbox"
    assert provider_reply.envelope_json["a2a_is_authority"] is False

    followups = [
        item
        for item in GroupchatWorklistStore(db).list_items(chain.chain_id)
        if item.source_message_id == provider_reply.id
        and item.target_participant_id == critic.participant_id
    ]
    assert len(followups) == 1
    assert followups[0].status == "queued"
    assert followups[0].depth == 1


@pytest.mark.asyncio
async def test_groupchat_peer_runtime_run_until_idle_reaches_route_exhausted_chain(
    tmp_path,
):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A1 peer runtime loop")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Remote A2A Architect GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    critic = participants.add(
        conversation_id=conversation.id,
        role="critic",
        display_name="Remote A2A Critic GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    root = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please design the next A1 runtime loop.",
    )
    chain = GroupchatWorklistStore(db).create_chain(
        conversation_id=conversation.id,
        root_message_id=root.id,
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("A2A participants should use provider writeback")

    class TwoTurnProviderService:
        def __init__(self) -> None:
            self.invocations = []

        def invoke_provider_adapter(self, invocation):
            self.invocations.append(invocation)
            if len(self.invocations) == 1:
                content = "@critic Please challenge this A1 runtime loop."
            else:
                content = "No further route. The A1 loop can stop at route exhaustion."
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=ProviderId.A2A,
                profile_id=ProviderProfileId.REMOTE,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=[f"a2a_task:{invocation.request_id}"],
                diagnostic_payload={
                    "a2a_task_id": invocation.request_id,
                    "a2a_context_id": invocation.request_id,
                    "a2a_state": "TASK_STATE_COMPLETED",
                    "a2a_disposition": "completed",
                    "a2a_terminal": True,
                    "a2a_content": content,
                    "a2a_artifacts": [],
                    "a2a_history": [],
                    "a2a_metadata": {},
                    "a2a_source_refs": [f"a2a_task:{invocation.request_id}"],
                    "a2a_sdk_task": {
                        "id": invocation.request_id,
                        "status": {"state": "TASK_STATE_COMPLETED"},
                    },
                    "a2a_jsonrpc_id": invocation.request_id,
                },
            )

    provider_service = TwoTurnProviderService()
    outcome = await GroupchatPeerRuntime(
        db_path=db,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="groupchat-peer-a1",
        response_wait_s=0.1,
        provider_service=provider_service,
    ).run_until_idle(chain_id=chain.chain_id, max_ticks=4)

    assert outcome.ticks == 2
    assert outcome.stop_reason == "chain_completed"
    assert len(outcome.tick_outcomes) == 2
    assert len(provider_service.invocations) == 2
    items = GroupchatWorklistStore(db).list_items(chain.chain_id)
    completed = [item for item in items if item.status == "completed"]
    assert len(completed) == 2
    completed_by_target = {item.target_participant_id: item for item in completed}
    assert set(completed_by_target) == {
        architect.participant_id,
        critic.participant_id,
    }
    assert [invocation.request_id for invocation in provider_service.invocations] == [
        completed_by_target[architect.participant_id].inbox_item_id,
        completed_by_target[critic.participant_id].inbox_item_id,
    ]
    assert all(item.completed_message_id is not None for item in completed)
    refreshed = GroupchatWorklistStore(db).get_chain(chain.chain_id)
    assert refreshed.status == "completed"
    assert refreshed.status_reason == "route_exhausted"


@pytest.mark.asyncio
async def test_groupchat_peer_runtime_continues_to_dispatch_ack_authority_wait(
    tmp_path,
):
    db, chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="@execute no natural route from the root.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    dispatch_ack = chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "authority": "chat.db/messages/dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proposal_id": "proposal-a",
            "resolution_id": "resolution-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": [
                "chat_dispatch_queue:dispatch-a",
                "proposal:proposal-a",
                "resolution:resolution-a",
            ],
        },
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("runtime must not deliver provider work for ack wait")

    outcome = await GroupchatPeerRuntime(
        db_path=db,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="groupchat-peer-a5",
        response_wait_s=0.1,
    ).run_until_idle(chain_id=chain.chain_id, max_ticks=4)

    assert outcome.ticks == 2
    assert outcome.stop_reason == (
        "waiting_for_authority:dispatch_acknowledgement_not_execution_proof"
    )
    assert outcome.chain_status == "open"
    assert outcome.chain_status_reason is None
    wait_tick = outcome.tick_outcomes[-1].worklist
    assert wait_tick.scanned == 1
    assert wait_tick.claimed_item_id is None
    assert wait_tick.terminal_item_id is not None
    assert wait_tick.terminal_reason == "dispatch_acknowledgement_not_execution_proof"
    assert wait_tick.terminal_source_message_id == dispatch_ack.id
    waiting_item = store.get_item(wait_tick.terminal_item_id)
    assert waiting_item.status == "blocked"
    assert waiting_item.source_message_id == dispatch_ack.id
    assert waiting_item.target_participant_id == architect.participant_id
    assert waiting_item.inbox_item_id is None


@pytest.mark.asyncio
async def test_groupchat_peer_runtime_resumes_past_ack_when_final_action_is_available(
    tmp_path,
):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A5 final action resume")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Remote A2A Architect GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    participants.add(
        conversation_id=conversation.id,
        role="critic",
        display_name="Critic GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    root = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    dispatch_ack = chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "authority": "chat.db/messages/dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proposal_id": "proposal-a",
            "resolution_id": "resolution-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": ["chat_dispatch_queue:dispatch-a"],
        },
    )
    spine_ref = _acceptance_spine_for_dispatch(
        db,
        conversation_id=conversation.id,
        intake_message_id=root.id,
        proposal_id="proposal-a",
        dispatch_item_id="dispatch-a",
    )
    final_action = chat.add_message(
        conversation_id=conversation.id,
        author="final-action-gate",
        role="system",
        content="Final action merge for lane lane-a is accepted.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "authority": "chat.db/messages/final_action_result",
            "lane_id": "lane-a",
            "action": "merge",
            "status": "accepted",
            "github_gate_evidence_ref": "github_gate_evidence:lane-a",
            "github_gate": {"status": "accepted"},
            "acceptance_spine_ref": spine_ref,
            "source_refs": [
                "final_actions.json#hold=final-a",
                spine_ref,
                "github_gate_evidence:lane-a",
            ],
        },
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("A2A architect should use provider writeback")

    class FinalActionProviderService:
        def __init__(self) -> None:
            self.invocations = []

        def invoke_provider_adapter(self, invocation):
            self.invocations.append(invocation)
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=ProviderId.A2A,
                profile_id=ProviderProfileId.REMOTE,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=[f"a2a_task:{invocation.request_id}"],
                diagnostic_payload={
                    "a2a_task_id": invocation.request_id,
                    "a2a_context_id": invocation.request_id,
                    "a2a_state": "TASK_STATE_COMPLETED",
                    "a2a_disposition": "completed",
                    "a2a_terminal": True,
                    "a2a_content": "Final action evidence accepted; no further route.",
                    "a2a_artifacts": [],
                    "a2a_history": [],
                    "a2a_metadata": {},
                    "a2a_source_refs": [f"a2a_task:{invocation.request_id}"],
                    "a2a_sdk_task": {
                        "id": invocation.request_id,
                        "status": {"state": "TASK_STATE_COMPLETED"},
                    },
                    "a2a_jsonrpc_id": invocation.request_id,
                },
            )

    provider_service = FinalActionProviderService()
    outcome = await GroupchatPeerRuntime(
        db_path=db,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="groupchat-peer-a5",
        response_wait_s=0.1,
        provider_service=provider_service,
    ).run_until_idle(chain_id=chain.chain_id, max_ticks=5)

    assert outcome.stop_reason == "chain_completed"
    assert outcome.chain_status == "completed"
    assert len(provider_service.invocations) == 1
    items = store.list_items(chain.chain_id)
    ack_items = [item for item in items if item.source_message_id == dispatch_ack.id]
    assert len(ack_items) == 1
    assert ack_items[0].status == "canceled"
    assert ack_items[0].terminal_reason == f"superseded_by_authority:{final_action.id}"
    final_action_items = [
        item
        for item in items
        if item.source_message_id == final_action.id
        and item.target_participant_id == architect.participant_id
    ]
    assert len(final_action_items) == 1
    assert final_action_items[0].status == "completed"
    assert final_action_items[0].completed_message_id is not None
    assert outcome.tick_outcomes[-1].worklist.completed_message_id == (
        final_action_items[0].completed_message_id
    )


@pytest.mark.asyncio
async def test_groupchat_peer_runtime_runs_from_root_message_idempotently(tmp_path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A1 root run entry")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Remote A2A Architect GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    critic = participants.add(
        conversation_id=conversation.id,
        role="critic",
        display_name="Remote A2A Critic GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    root = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please design the root-run A1 entry.",
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("A2A participants should use provider writeback")

    class TwoTurnProviderService:
        def __init__(self) -> None:
            self.invocations = []

        def invoke_provider_adapter(self, invocation):
            self.invocations.append(invocation)
            content = (
                "@critic Please challenge this root-run entry."
                if len(self.invocations) == 1
                else "No further route from root-run entry."
            )
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=ProviderId.A2A,
                profile_id=ProviderProfileId.REMOTE,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=[f"a2a_task:{invocation.request_id}"],
                diagnostic_payload={
                    "a2a_task_id": invocation.request_id,
                    "a2a_context_id": invocation.request_id,
                    "a2a_state": "TASK_STATE_COMPLETED",
                    "a2a_disposition": "completed",
                    "a2a_terminal": True,
                    "a2a_content": content,
                    "a2a_artifacts": [],
                    "a2a_history": [],
                    "a2a_metadata": {},
                    "a2a_source_refs": [f"a2a_task:{invocation.request_id}"],
                    "a2a_sdk_task": {
                        "id": invocation.request_id,
                        "status": {"state": "TASK_STATE_COMPLETED"},
                    },
                    "a2a_jsonrpc_id": invocation.request_id,
                },
            )

    provider_service = TwoTurnProviderService()
    runtime = GroupchatPeerRuntime(
        db_path=db,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="groupchat-peer-a1",
        response_wait_s=0.1,
        provider_service=provider_service,
    )

    first = await runtime.run_from_root_message(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_ticks=1,
    )
    second = await runtime.run_from_root_message(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_ticks=4,
    )
    third = await runtime.run_from_root_message(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_ticks=4,
    )

    assert first.created_chain is True
    assert first.run.ticks == 1
    assert first.run.stop_reason == "max_ticks"
    assert first.run.chain_status == "open"
    assert second.created_chain is False
    assert second.chain_id == first.chain_id
    assert second.run.ticks == 1
    assert second.run.stop_reason == "chain_completed"
    assert third.created_chain is False
    assert third.chain_id == first.chain_id
    assert third.run.ticks == 0
    assert third.run.stop_reason == "chain_completed"
    assert len(provider_service.invocations) == 2
    chains = GroupchatWorklistStore(db).list_chains(conversation.id)
    assert len(chains) == 1
    assert chains[0].chain_id == first.chain_id
    assert chains[0].root_message_id == root.id
    completed = [
        item
        for item in GroupchatWorklistStore(db).list_items(first.chain_id)
        if item.status == "completed"
    ]
    assert {item.target_participant_id for item in completed} == {
        architect.participant_id,
        critic.participant_id,
    }


@pytest.mark.asyncio
async def test_groupchat_peer_runtime_root_run_uses_policy_guards(tmp_path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conversation = chat.create_conversation("A1 root policy guards")
    participants = ParticipantStore(db)
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Remote A2A Architect GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    critic = participants.add(
        conversation_id=conversation.id,
        role="critic",
        display_name="Remote A2A Critic GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    root = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please design the guarded root-run entry.",
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("A2A participants should use provider writeback")

    class FollowupProviderService:
        def __init__(self) -> None:
            self.invocations: list[object] = []

        def invoke_provider_adapter(self, invocation):
            self.invocations.append(invocation)
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=ProviderId.A2A,
                profile_id=ProviderProfileId.REMOTE,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=[f"a2a_task:{invocation.request_id}"],
                diagnostic_payload={
                    "a2a_task_id": invocation.request_id,
                    "a2a_context_id": invocation.request_id,
                    "a2a_state": "TASK_STATE_COMPLETED",
                    "a2a_disposition": "completed",
                    "a2a_terminal": True,
                    "a2a_content": "@critic This follow-up should hit depth guard.",
                    "a2a_artifacts": [],
                    "a2a_history": [],
                    "a2a_metadata": {},
                    "a2a_source_refs": [f"a2a_task:{invocation.request_id}"],
                    "a2a_sdk_task": {
                        "id": invocation.request_id,
                        "status": {"state": "TASK_STATE_COMPLETED"},
                    },
                    "a2a_jsonrpc_id": invocation.request_id,
                },
            )

    provider_service = FollowupProviderService()
    outcome = await GroupchatPeerRuntime(
        db_path=db,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="groupchat-peer-a1",
        response_wait_s=0.1,
        provider_service=provider_service,
    ).run_from_root_message(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_ticks=4,
        max_depth=1,
    )

    assert outcome.created_chain is True
    assert outcome.run.ticks == 1
    assert outcome.run.stop_reason == "chain_blocked"
    assert outcome.run.chain_status == "blocked"
    assert outcome.run.chain_status_reason == "depth_limit"
    assert len(provider_service.invocations) == 1
    chain = GroupchatWorklistStore(db).get_chain(outcome.chain_id)
    assert chain.max_depth == 1
    items = GroupchatWorklistStore(db).list_items(outcome.chain_id)
    assert len([item for item in items if item.status == "completed"]) == 1
    blocked = [
        item
        for item in items
        if item.status == "blocked" and item.terminal_reason == "depth_limit"
    ]
    assert len(blocked) == 1
    assert blocked[0].source_participant_id == architect.participant_id
    assert blocked[0].target_participant_id == critic.participant_id
    assert blocked[0].inbox_item_id is None


@pytest.mark.asyncio
async def test_groupchat_peer_runtime_rejects_peer_stdout_fallback_as_proof(tmp_path):
    db, _chat, conversation, root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="Please design the next A1 runtime bridge.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    class StdoutFallbackGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            return type(
                "Record",
                (),
                {
                    "god_session_id": "god-live",
                    "provider_session_id": "provider-thread-live",
                    "provider_session_kind": "codex_app_server_thread",
                    "provider_binding_status": "active",
                    "provider_binding_failure_reason": None,
                },
            )()

        async def send_message(self, *args, **kwargs):
            return None

        async def receive_message(self, god_session_id):
            return type(
                "Message",
                (),
                {
                    "type": "result",
                    "status": "success",
                    "request_id": "unused",
                    "message": ("@critic This stdout fallback must not complete worklist proof."),
                    "artifacts": {},
                },
            )()

    outcome = await GroupchatPeerRuntime(
        db_path=db,
        god_layer=StdoutFallbackGodLayer(),
        worktree=tmp_path,
        scheduler_id="groupchat-peer-a1",
        response_wait_s=0.1,
        degraded_fallback_enabled=True,
    ).tick_once(chain_id=chain.chain_id)

    assert outcome.peer is not None
    assert outcome.peer.fallback_replies == 1
    assert outcome.worklist.completed_message_id is None
    assert outcome.worklist.failed_item_id is not None
    assert outcome.worklist.failure_reason == "callback_missing"
    failed = store.get_item(outcome.worklist.failed_item_id)
    assert failed.status == "failed"
    assert failed.terminal_reason == "callback_missing"
    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "callback_missing"


def test_scan_routes_human_mentions_strip_code_fences_and_cap_targets(tmp_path):
    db, _chat, conversation, root, architect, review, critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content=(
                "Ignore this example:\n"
                "```\n"
                "@architect not a real route\n"
                "```\n"
                "@critic @review @architect please discuss"
            ),
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    routed = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).scan_routes_once(chain_id=chain.chain_id)
    items = store.list_items(chain.chain_id)

    queued_targets = [
        item.target_participant_id for item in routed if item.status == "queued"
    ]
    assert queued_targets == [critic.participant_id, review.participant_id]
    blocked = [
        item
        for item in items
        if item.status == "blocked" and item.terminal_reason == "fanout_limit"
    ]
    assert len(blocked) == 1
    assert blocked[0].target_participant_id == architect.participant_id
    assert store.get_chain(chain.chain_id).status == "open"


def test_scan_routes_ignores_active_participants_outside_fixed_a1_roster(tmp_path):
    db, chat, conversation, root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="@execute should not be a natural groupchat target.",
        )
    )
    execute = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="@execute still should not route.",
    )

    first_scan = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).scan_routes_once(chain_id=chain.chain_id)
    second_scan = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).scan_routes_once(chain_id=chain.chain_id)

    assert first_scan == []
    assert second_scan == []
    assert all(
        item.target_participant_id != execute.participant_id
        for item in store.list_items(chain.chain_id)
    )


def test_scan_routes_hands_accepted_final_action_back_to_architect(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    accepted = chat.add_message(
        conversation_id=conversation.id,
        author="final-action-gate",
        role="system",
        content="Final action merge for lane lane-a is accepted.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "lane_id": "lane-a",
            "action": "merge",
            "status": "accepted",
            "github_gate_evidence_ref": "github_gate_evidence:lane-a",
            "github_gate": {
                "status": "accepted",
                "exact_head_sha": "abc123",
                "pr": {"number": 42},
            },
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == accepted.id
    assert routed[0].target_participant_id == architect.participant_id
    assert routed[0].route_kind == "handoff"
    assert routed[0].status == "queued"
    assert store.get_chain(chain.chain_id).status == "open"


def test_scan_routes_uses_final_action_envelope_before_text_mentions(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    accepted = chat.add_message(
        conversation_id=conversation.id,
        author="final-action-gate",
        role="system",
        content="@critic Final action merge for lane lane-a is accepted.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "lane_id": "lane-a",
            "action": "merge",
            "status": "accepted",
            "github_gate_evidence_ref": "github_gate_evidence:lane-a",
            "github_gate": {"status": "accepted"},
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == accepted.id
    assert routed[0].target_participant_id == architect.participant_id
    assert routed[0].route_kind == "handoff"


def test_scan_routes_blocks_final_action_github_gate_gap(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    blocked_result = chat.add_message(
        conversation_id=conversation.id,
        author="final-action-gate",
        role="system",
        content="Final action merge for lane lane-a is blocked by GitHub gate.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "lane_id": "lane-a",
            "action": "merge",
            "status": "blocked",
            "github_gate_gap_ref": "github_gate_gap:lane-a",
            "status_reason": "github_gate_unverified",
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == blocked_result.id
    assert routed[0].target_participant_id == architect.participant_id
    assert routed[0].route_kind == "handoff"
    assert routed[0].status == "blocked"
    assert routed[0].terminal_reason == "final_action_github_gate_gap"
    chain_after = store.get_chain(chain.chain_id)
    assert chain_after.status == "blocked"
    assert chain_after.status_reason == "final_action_github_gate_gap"


def test_scan_routes_dispatch_ack_waits_for_execution_authority(tmp_path):
    db, chat, conversation, root, architect, _review, critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    dispatch_ack = chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="@critic DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "authority": "chat.db/messages/dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proposal_id": "proposal-a",
            "resolution_id": "resolution-a",
            "collaboration_run_id": "collab-a",
            "artifact_ref": "artifact:lane_graph",
            "dispatch_evidence_ref": "mcp_writeback:inbox-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": [
                "chat_dispatch_queue:dispatch-a",
                "proposal:proposal-a",
                "resolution:resolution-a",
            ],
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == dispatch_ack.id
    assert routed[0].target_participant_id == architect.participant_id
    assert routed[0].target_participant_id != critic.participant_id
    assert routed[0].route_kind == "handoff"
    assert routed[0].status == "blocked"
    assert routed[0].terminal_reason == "dispatch_acknowledgement_not_execution_proof"
    assert store.get_chain(chain.chain_id).status == "open"

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    assert store.get_chain(chain.chain_id).status == "open"


def test_scan_routes_final_action_supersedes_dispatch_ack_wait(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    dispatch_ack = chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": ["chat_dispatch_queue:dispatch-a"],
        },
    )
    spine_ref = _acceptance_spine_for_dispatch(
        db,
        conversation_id=conversation.id,
        intake_message_id=root.id,
        proposal_id="proposal-a",
        dispatch_item_id="dispatch-a",
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    waiting = scheduler.scan_routes_once(chain_id=chain.chain_id)
    assert len(waiting) == 1
    assert waiting[0].source_message_id == dispatch_ack.id
    assert waiting[0].status == "blocked"

    final_action = chat.add_message(
        conversation_id=conversation.id,
        author="final-action-gate",
        role="system",
        content="Final action merge for lane lane-a is accepted.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "lane_id": "lane-a",
            "action": "merge",
            "status": "accepted",
            "github_gate_evidence_ref": "github_gate_evidence:lane-a",
            "github_gate": {"status": "accepted"},
            "acceptance_spine_ref": spine_ref,
        },
    )

    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == final_action.id
    assert routed[0].target_participant_id == architect.participant_id
    assert routed[0].status == "queued"
    ack_item = store.get_item(waiting[0].item_id)
    assert ack_item.status == "canceled"
    assert ack_item.terminal_reason == f"superseded_by_authority:{final_action.id}"
    assert store.get_chain(chain.chain_id).status == "open"


def test_scan_routes_final_action_cancels_only_matching_dispatch_ack_wait(
    tmp_path,
):
    db, chat, conversation, root, architect, _review, _critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": ["chat_dispatch_queue:dispatch-a"],
        },
    )
    chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-b",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "dispatch_queue_entry_id": "dispatch-b",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": ["chat_dispatch_queue:dispatch-b"],
        },
    )
    spine_ref = _acceptance_spine_for_dispatch(
        db,
        conversation_id=conversation.id,
        intake_message_id=root.id,
        proposal_id="proposal-a",
        dispatch_item_id="dispatch-a",
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    wait_a = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]
    wait_b = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]
    assert wait_a.status == "blocked"
    assert wait_b.status == "blocked"

    final_action = chat.add_message(
        conversation_id=conversation.id,
        author="final-action-gate",
        role="system",
        content="Final action merge for lane lane-a is accepted.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "lane_id": "lane-a",
            "action": "merge",
            "status": "accepted",
            "github_gate_evidence_ref": "github_gate_evidence:lane-a",
            "github_gate": {"status": "accepted"},
            "acceptance_spine_ref": spine_ref,
        },
    )

    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == final_action.id
    assert routed[0].target_participant_id == architect.participant_id
    assert store.get_item(wait_a.item_id).status == "canceled"
    assert store.get_item(wait_a.item_id).terminal_reason == (
        f"superseded_by_authority:{final_action.id}"
    )
    assert store.get_item(wait_b.item_id).status == "blocked"
    assert store.get_item(wait_b.item_id).terminal_reason == (
        "dispatch_acknowledgement_not_execution_proof"
    )
    assert store.get_chain(chain.chain_id).status == "open"


def test_scan_routes_gate_gap_final_action_supersedes_matching_dispatch_ack_wait(
    tmp_path,
):
    db, chat, conversation, root, architect, _review, _critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": ["chat_dispatch_queue:dispatch-a"],
        },
    )
    spine_ref = _acceptance_spine_for_dispatch(
        db,
        conversation_id=conversation.id,
        intake_message_id=root.id,
        proposal_id="proposal-a",
        dispatch_item_id="dispatch-a",
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    waiting = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]
    assert waiting.status == "blocked"

    final_action = chat.add_message(
        conversation_id=conversation.id,
        author="final-action-gate",
        role="system",
        content="Final action merge for lane lane-a is blocked by GitHub gate.",
        envelope_type="final_action_result",
        envelope_json={
            "type": "final_action_result",
            "lane_id": "lane-a",
            "action": "merge",
            "status": "blocked",
            "github_gate_gap_ref": "github_gate_gap:lane-a",
            "status_reason": "github_gate_unverified",
            "acceptance_spine_ref": spine_ref,
        },
    )

    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == final_action.id
    assert routed[0].target_participant_id == architect.participant_id
    assert routed[0].status == "blocked"
    assert routed[0].terminal_reason == "final_action_github_gate_gap"
    ack_item = store.get_item(waiting.item_id)
    assert ack_item.status == "canceled"
    assert ack_item.terminal_reason == f"superseded_by_authority:{final_action.id}"
    assert store.get_chain(chain.chain_id).status == "blocked"
    assert store.get_chain(chain.chain_id).status_reason == "final_action_github_gate_gap"


def test_scan_routes_consumes_unknown_dispatch_result_without_text_routing(tmp_path):
    db, chat, conversation, root, _architect, _review, critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="@critic DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proof_boundary": "unknown_dispatch_boundary",
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert routed == []
    assert all(
        item.target_participant_id != critic.participant_id
        for item in store.list_items(chain.chain_id)
    )


def test_scan_routes_dispatch_ack_uses_envelope_authority_when_column_is_message(
    tmp_path,
):
    db, chat, conversation, root, architect, _review, _critic = _conversation_with_groupchat_roster(
        tmp_path,
        root_content="@execute no natural route from the root.",
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    dispatch_ack = chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="@critic DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="message",
        envelope_json={
            "type": "message",
            "authority": "chat.db/messages/dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == dispatch_ack.id
    assert routed[0].target_participant_id == architect.participant_id
    assert routed[0].status == "blocked"
    assert routed[0].terminal_reason == "dispatch_acknowledgement_not_execution_proof"


def test_scan_routes_dispatch_ack_wait_is_idempotent_on_cursor_replay(tmp_path):
    db, chat, conversation, root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="@execute no natural route from the root.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    dispatch_ack = chat.add_message(
        conversation_id=conversation.id,
        author="execute",
        role="assistant",
        content="DISPATCH_ACKNOWLEDGED dispatch-a",
        envelope_type="dispatch_result",
        envelope_json={
            "type": "dispatch_result",
            "dispatch_queue_entry_id": "dispatch-a",
            "proof_boundary": "dispatch_acknowledgement_not_execution_proof",
            "source_refs": ["chat_dispatch_queue:dispatch-a"],
        },
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    first = scheduler.scan_routes_once(chain_id=chain.chain_id)
    assert len(first) == 1
    assert first[0].status == "blocked"
    with sqlite3.connect(db) as conn:
        conn.execute(
            "update groupchat_chains set last_scanned_message_id = ? where chain_id = ?",
            (root.id, chain.chain_id),
        )

    replayed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert replayed == []
    items = [
        item
        for item in store.list_items(chain.chain_id)
        if item.source_message_id == dispatch_ack.id
    ]
    assert len(items) == 1
    assert items[0].status == "blocked"


def test_scan_routes_ignores_inline_mentions_even_when_mentions_json_contains_target(
    tmp_path,
):
    db, chat, conversation, root, _architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=_architect.participant_id,
        route_kind="router",
        depth=0,
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")
    linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert linked is not None
    inline_reply = chat.create_message_inbox_and_log(
        conversation_id=conversation.id,
        tool_name="chat_post_message",
        caller_identity=_architect.participant_id,
        client_request_id="inline-mentions-json",
        author=_architect.participant_id,
        role="assistant",
        content="Please ask @review later, but this line is not a route.",
        envelope_type="message",
        envelope_json={
            "writeback_path": "groupchat_worklist_test",
            "reply_to_inbox_item_id": linked.inbox_item_id,
        },
        mentions=["@review"],
        inbox_items=[],
        reply_to_inbox_item_id=linked.inbox_item_id,
        reply_owner_participant_id=_architect.participant_id,
    )["message"]["id"]
    store.complete_item(first.item_id, completed_message_id=inline_reply)

    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert routed == []
    assert all(
        item.target_participant_id != review.participant_id
        for item in store.list_items(chain.chain_id)
    )


def test_scan_routes_agent_mentions_only_first_target_and_records_fanout_limit(
    tmp_path,
):
    db, chat, conversation, root, architect, review, critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )
    linked = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).claim_and_link_one(chain_id=chain.chain_id)
    assert linked is not None
    reply_id = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=linked.inbox_item_id,
        content="@critic @review please challenge the design.",
    )
    store.complete_item(first.item_id, completed_message_id=reply_id)

    routed = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).scan_routes_once(chain_id=chain.chain_id)
    items = store.list_items(chain.chain_id)

    queued = [item for item in routed if item.status == "queued"]
    assert [item.target_participant_id for item in queued] == [critic.participant_id]
    assert queued[0].depth == 1
    blocked = [
        item
        for item in items
        if item.status == "blocked" and item.terminal_reason == "fanout_limit"
    ]
    assert len(blocked) == 1
    assert blocked[0].target_participant_id == review.participant_id
    assert store.get_chain(chain.chain_id).status == "open"


def test_scan_routes_does_not_complete_chain_when_later_messages_remain(tmp_path):
    db, chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")
    linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert linked is not None
    no_route_reply = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=linked.inbox_item_id,
        content="I have no next handoff yet.",
    )
    store.complete_item(first.item_id, completed_message_id=no_route_reply)
    later_human = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please review the later boundary.",
    )

    first_scan = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert first_scan == []
    assert store.get_chain(chain.chain_id).status == "open"
    assert store.get_chain(chain.chain_id).last_scanned_message_id == no_route_reply

    second_scan = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(second_scan) == 1
    assert second_scan[0].source_message_id == later_human.id
    assert second_scan[0].target_participant_id == review.participant_id


def test_enqueue_route_does_not_jump_scan_cursor_past_unscanned_messages(tmp_path):
    db, chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(
            tmp_path,
            root_content="@execute no natural route from the root.",
        )
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    middle = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please review the middle message.",
    )
    later = chat.add_message(
        conversation_id=conversation.id,
        author="human",
        role="human",
        content="Please route this later message manually.",
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")

    assert scheduler.scan_routes_once(chain_id=chain.chain_id) == []
    assert store.get_chain(chain.chain_id).last_scanned_message_id == root.id

    store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=later.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )

    routed = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(routed) == 1
    assert routed[0].source_message_id == middle.id
    assert routed[0].target_participant_id == review.participant_id


def test_scan_routes_blocks_fourth_pingpong_pair_as_durable_policy_state(
    tmp_path,
):
    db, chat, conversation, root, architect, _review, critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_depth=10,
        pingpong_block_after=4,
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )

    first_linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert first_linked is not None
    architect_reply_1 = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=first_linked.inbox_item_id,
        content="@critic challenge this.",
        client_request_id="structured-writeback-architect-1",
    )
    store.complete_item(first.item_id, completed_message_id=architect_reply_1)
    critic_item_1 = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]

    critic_linked_1 = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert critic_linked_1 is not None
    critic_reply_1 = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=critic.participant_id,
        inbox_item_id=critic_linked_1.inbox_item_id,
        content="@architect answer the challenge.",
        client_request_id="structured-writeback-critic-1",
    )
    store.complete_item(critic_item_1.item_id, completed_message_id=critic_reply_1)
    architect_item_2 = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]

    architect_linked_2 = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert architect_linked_2 is not None
    architect_reply_2 = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=architect_linked_2.inbox_item_id,
        content="@critic one more challenge.",
        client_request_id="structured-writeback-architect-2",
    )
    store.complete_item(architect_item_2.item_id, completed_message_id=architect_reply_2)
    critic_item_2 = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]

    critic_linked_2 = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert critic_linked_2 is not None
    critic_reply_2 = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=critic.participant_id,
        inbox_item_id=critic_linked_2.inbox_item_id,
        content="@architect this would be the fourth pair handoff.",
        client_request_id="structured-writeback-critic-2",
    )
    store.complete_item(critic_item_2.item_id, completed_message_id=critic_reply_2)

    blocked = scheduler.scan_routes_once(chain_id=chain.chain_id)

    assert len(blocked) == 1
    assert blocked[0].status == "blocked"
    assert blocked[0].terminal_reason == "pingpong_blocked"
    assert blocked[0].target_participant_id == architect.participant_id
    assert store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id) is None
    assert store.get_chain(chain.chain_id).status == "blocked"
    assert store.get_chain(chain.chain_id).status_reason == "pingpong_blocked"


def test_claimed_pingpong_route_at_warn_threshold_carries_durable_warning(
    tmp_path,
):
    db, chat, conversation, root, architect, _review, critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_depth=10,
        pingpong_warn_after=2,
        pingpong_block_after=4,
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )

    first_linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert first_linked is not None
    architect_reply = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=first_linked.inbox_item_id,
        content="@critic challenge this.",
        client_request_id="structured-writeback-architect-warn-1",
    )
    store.complete_item(first.item_id, completed_message_id=architect_reply)
    critic_item = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]

    critic_linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    assert critic_linked is not None
    critic_reply = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=critic.participant_id,
        inbox_item_id=critic_linked.inbox_item_id,
        content="@architect answer the challenge.",
        client_request_id="structured-writeback-critic-warn-1",
    )
    store.complete_item(critic_item.item_id, completed_message_id=critic_reply)
    architect_item = scheduler.scan_routes_once(chain_id=chain.chain_id)[0]

    warned = scheduler.claim_and_link_one(chain_id=chain.chain_id)

    assert warned is not None
    assert warned.item_id == architect_item.item_id
    assert warned.status == "claimed"
    assert warned.inbox_item_id is not None
    inbox_item = ChatInboxStore(db).get(warned.inbox_item_id)
    assert inbox_item.payload["groupchat_policy_warning"] == {
        "type": "pingpong_warn",
        "streak": 2,
        "warn_after": 2,
        "block_after": 4,
        "source_participant_id": critic.participant_id,
        "target_participant_id": architect.participant_id,
    }
    assert store.get_chain(chain.chain_id).status == "open"


def test_groupchat_worklist_schema_records_migration_marker(tmp_path):
    db, _chat, _conversation, _root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )

    with sqlite3.connect(db) as conn:
        versions = {
            row[0]
            for row in conn.execute(
                "select version from schema_migrations",
            ).fetchall()
        }

    assert "groupchat_worklist_a1" in versions


def test_depth_limit_blocks_route_without_schedulable_provider_work(tmp_path):
    db, _chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(
        conversation_id=conversation.id,
        root_message_id=root.id,
        max_depth=1,
    )

    blocked = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="handoff",
        depth=1,
    )

    assert blocked.status == "blocked"
    assert blocked.terminal_reason == "depth_limit"
    assert store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id) is None
    assert store.get_chain(chain.chain_id).status == "blocked"
    assert store.get_chain(chain.chain_id).status_reason == "depth_limit"


def test_duplicate_route_returns_existing_schedulable_item(tmp_path):
    db, _chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    second = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )

    assert second.item_id == first.item_id
    assert len(store.list_items(chain.chain_id)) == 1


def test_link_inbox_item_rejects_wrong_target_payload(tmp_path):
    db, _chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    item = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    claimed = store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id)
    wrong_inbox = ChatInboxStore(db).create_item(
        conversation_id=conversation.id,
        target_participant_id=review.participant_id,
        target_role=review.role,
        target_address="@review",
        sender_participant_id=None,
        sender_address="@groupchat-worklist",
        source_message_id=root.id,
        item_type="groupchat_route",
        payload={
            "groupchat_chain_id": chain.chain_id,
            "groupchat_worklist_item_id": item.item_id,
            "route_kind": "mention",
        },
    )

    assert claimed is not None
    with pytest.raises(ValueError, match="inbox_item_worklist_mismatch"):
        store.link_inbox_item(item.item_id, wrong_inbox.id)


def test_worklist_completion_requires_structured_writeback(tmp_path):
    db, chat, conversation, root, architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    item = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="router",
        depth=0,
    )
    linked = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).claim_and_link_one(chain_id=chain.chain_id)

    assert linked is not None
    with pytest.raises(ValueError, match="completed_message_missing"):
        store.complete_item(item.item_id, completed_message_id="provider_stdout_only")
    unrelated = chat.add_message(
        conversation_id=conversation.id,
        author="architect",
        role="assistant",
        content="Durable but unrelated message.",
    )
    with pytest.raises(ValueError, match="structured_writeback_missing"):
        store.complete_item(item.item_id, completed_message_id=unrelated.id)

    failed = GroupchatWorklistScheduler(
        db_path=db,
        scheduler_id="groupchat-a1",
    ).fail_missing_callback(item.item_id)

    assert failed.status == "failed"
    assert failed.terminal_reason == "callback_missing"
    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "callback_missing"


def test_missing_target_is_durable_failed_audit_item_not_schedulable(tmp_path):
    db, _chat, conversation, root, _architect, _review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)

    failed = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id="part_missing",
        route_kind="mention",
        depth=0,
    )

    assert failed.status == "failed"
    assert failed.target_participant_id == "part_missing"
    assert failed.terminal_reason == "target_participant_missing"
    assert store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id) is None
    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "target_participant_missing"


def test_failed_chain_is_not_overwritten_by_later_completion(tmp_path):
    db, chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    second = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=review.participant_id,
        route_kind="review_request",
        depth=0,
    )
    scheduler = GroupchatWorklistScheduler(db_path=db, scheduler_id="groupchat-a1")
    first_linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)
    second_linked = scheduler.claim_and_link_one(chain_id=chain.chain_id)

    assert first_linked is not None
    assert second_linked is not None
    store.fail_item(second.item_id, reason="callback_missing")
    reply_id = _writeback_reply(
        chat,
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        inbox_item_id=first_linked.inbox_item_id,
        content="Durable writeback for the first item.",
        client_request_id="structured-writeback-first",
    )
    store.complete_item(first.item_id, completed_message_id=reply_id)

    assert store.get_chain(chain.chain_id).status == "failed"
    assert store.get_chain(chain.chain_id).status_reason == "callback_missing"


def test_terminal_chain_cancels_queued_siblings_and_stops_claiming(tmp_path):
    db, _chat, conversation, root, architect, review, _critic = (
        _conversation_with_groupchat_roster(tmp_path)
    )
    store = GroupchatWorklistStore(db)
    chain = store.create_chain(conversation_id=conversation.id, root_message_id=root.id)
    first = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=architect.participant_id,
        route_kind="mention",
        depth=0,
    )
    second = store.enqueue_route(
        chain_id=chain.chain_id,
        source_message_id=root.id,
        target_participant_id=review.participant_id,
        route_kind="review_request",
        depth=0,
    )

    store.fail_item(first.item_id, reason="callback_missing")

    assert store.get_item(second.item_id).status == "canceled"
    assert store.get_item(second.item_id).terminal_reason == "chain_failed:callback_missing"
    assert store.claim_next(owner="groupchat-a1", chain_id=chain.chain_id) is None
