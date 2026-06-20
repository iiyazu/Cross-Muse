from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from xmuse_core.agents.registry import AgentRuntime
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_scheduler import (
    PeerChatScheduler,
    _peer_session_prompt_fingerprint,
)
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import ChatStreamStore, PeerTurnLatencyTraceStore


class FakeGodLayer:
    def __init__(self) -> None:
        self.ensured = []
        self.sent = []
        self.prompt_contracts = []
        self.receive_result = type(
            "Message",
            (),
            {
                "type": "result",
                "status": "success",
                "request_id": "unused",
            },
        )()

    async def ensure_conversation_session(self, **kwargs):
        self.ensured.append(kwargs)
        return type("Record", (), {"god_session_id": "god-live"})()

    async def send_message(self, god_session_id, message_type, prompt, context, request_id=None):
        self.sent.append((god_session_id, message_type, prompt, context, request_id))

    def record_prompt_contract(self, god_session_id, **kwargs):
        self.prompt_contracts.append((god_session_id, kwargs))

    async def receive_message(self, god_session_id):
        return self.receive_result


class FakeClock:
    def __init__(self, values: list[float]) -> None:
        self._values = list(values)

    def __call__(self) -> float:
        if not self._values:
            raise AssertionError("fake clock exhausted")
        return self._values.pop(0)


@pytest.mark.asyncio
async def test_scheduler_claims_and_nudges_oldest_item(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler")
    participants = ParticipantStore(tmp_path / "chat.db")
    participant = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    chat.add_message(conv.id, execute.participant_id, "assistant", "I am here too.")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )
    layer = FakeGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 0
    assert outcome.happy_path == 0
    assert outcome.failed == 1
    ensured = layer.ensured[0]
    assert ensured["conversation_id"] == conv.id
    assert ensured["participant_id"] == participant.participant_id
    assert ensured["role"] == "architect"
    assert ensured["agent"].runtime is AgentRuntime.CODEX
    assert ensured["agent"].name == "Architect GOD"
    assert ensured["model"] == "gpt-5.4"
    assert str(ensured["prompt_fingerprint"]).startswith("sha256:")
    assert ensured["feature_scope_id"] is None
    assert ensured["worktree"] == tmp_path
    assert layer.sent[0][1] == "peer_chat_nudge"
    assert "must use chat_read_inbox" not in layer.sent[0][2]
    assert "call chat_post_message directly" in layer.sent[0][2]
    assert "reply_to_inbox_item_id=xmuse_context.inbox_item.id" in layer.sent[0][2]
    assert "chat_read_inbox is only for recovery or batch inspection" in layer.sent[0][2]
    assert "answer, report, review" in layer.sent[0][2]
    assert "do not use chat_mention back to the sender for simple answers" in layer.sent[0][2]
    assert (
        "Natural-language @mentions inside chat_post_message are display-only"
        in layer.sent[0][2]
    )
    assert "call chat_mention with" in layer.sent[0][2]
    assert "closes your current inbox item" in layer.sent[0][2]
    assert "chat_emit_proposal" in layer.sent[0][2]
    assert "collaboration:<run_id>" in layer.sent[0][2]
    assert '"status":"executable"' in layer.sent[0][2]
    assert '"evidence_refs":["<ref>"]' in layer.sent[0][2]
    assert "verdict=feasible do not satisfy dispatch" in layer.sent[0][2]
    assert "Human approval is still required before dispatch" in layer.sent[0][2]

    assert "Only if MCP tools are unavailable" in layer.sent[0][2]
    assert "This is a group chat" in layer.sent[0][2]
    assert "Architect GOD" in layer.sent[0][2]
    assert "Execute GOD" in layer.sent[0][2]
    assert "Do not greet repeatedly" in layer.sent[0][2]
    context = json.loads(layer.sent[0][3])
    assert context["conversation_id"] == conv.id
    assert context["participant_id"] == participant.participant_id
    assert context["god_session_id"] == "god-live"
    assert context["inbox_item"]["id"] == item.id
    assert context["group_chat"]["participants"] == [
        {
            "participant_id": participant.participant_id,
            "role": "architect",
            "display_name": "Architect GOD",
            "status": "active",
        },
        {
            "participant_id": execute.participant_id,
            "role": "execute",
            "display_name": "Execute GOD",
            "status": "active",
        },
    ]
    assert context["group_chat"]["recent_messages"][-1]["content"] == "I am here too."
    assert context["context_capsule"]["version"] == "xmuse-local-context-capsule-v1"
    assert context["xmuse_prompt"]["version"] == "xmuse-peer-chat-prompt-v2"
    assert context["xmuse_prompt"]["layer_order"] == [
        "xmuse_governance_l0",
        "member_identity",
        "roster_and_capabilities",
        "local_context_capsule",
        "tool_and_writeback_contract",
    ]
    assert context["xmuse_prompt"]["fingerprint"].startswith("sha256:")
    assert layer.prompt_contracts[0][0] == "god-live"
    assert layer.prompt_contracts[0][1]["prompt_contract_version"] == (
        "xmuse-peer-chat-prompt-v2"
    )
    assert layer.prompt_contracts[0][1]["prompt_layer_order"] == (
        context["xmuse_prompt"]["layer_order"]
    )
    assert layer.prompt_contracts[0][1]["prompt_artifact_fingerprint"] == (
        context["xmuse_prompt"]["fingerprint"]
    )

    claimed = inbox.get(item.id)
    assert claimed.status == "unread"
    assert claimed.claim_owner == "sched-test"
    assert claimed.nudge_count == 1


@pytest.mark.asyncio
async def test_scheduler_releases_turn_after_durable_writeback_before_provider_result(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler early writeback")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class SlowGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            await asyncio.sleep(30)
            return None

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=SlowGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=10,
        post_writeback_grace_s=0.1,
    )
    task = asyncio.create_task(scheduler.tick_once())
    await asyncio.sleep(0.1)
    result = chat.create_message_inbox_and_log(
        conversation_id=conv.id,
        tool_name="chat_mention",
        caller_identity="god:god-live:architect",
        client_request_id="handoff-1",
        author=participant.participant_id,
        role="assistant",
        content="Handing off to execute.",
        envelope_type="mention",
        envelope_json={"type": "mention"},
        mentions=["@execute"],
        inbox_items=[],
        reply_to_inbox_item_id=item.id,
        reply_owner_participant_id=participant.participant_id,
    )
    PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
        conversation_id=conv.id,
        inbox_item_id=item.id,
        tool_name="chat_mention",
        called_at=100.0,
    )

    outcome = await asyncio.wait_for(task, timeout=3)

    assert result["message"]["id"] == inbox.get(item.id).responded_message_id
    assert outcome.happy_path == 1
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] == "peer_writeback_before_provider_result"


def test_peer_session_prompt_fingerprint_is_stable_across_inbox_content(tmp_path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Stable fingerprint")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    first = _peer_session_prompt_fingerprint(participant)
    first_message = chat.add_message(conv.id, "Human", "human", "@architect first")
    second_message = chat.add_message(conv.id, "Human", "human", "@architect second")

    ChatInboxStore(tmp_path / "chat.db").create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=first_message.id,
        item_type="mention",
        payload={"content": "@architect first"},
    )
    ChatInboxStore(tmp_path / "chat.db").create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role=participant.role,
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=second_message.id,
        item_type="mention",
        payload={"content": "@architect second"},
    )

    assert _peer_session_prompt_fingerprint(participant) == first


@pytest.mark.asyncio
async def test_scheduler_tick_many_claims_multiple_inbox_items_concurrently(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    participants = ParticipantStore(tmp_path / "chat.db")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    items = []
    participant_by_id = {}
    for index in range(3):
        conv = chat.create_conversation(f"Scheduler parallel {index}")
        participant = participants.add(
            conversation_id=conv.id,
            role="architect",
            display_name=f"Architect GOD {index}",
            cli_kind="codex",
            model="gpt-5.4",
        )
        participant_by_id[participant.participant_id] = participant
        message = chat.add_message(conv.id, "Human", "human", "@architect")
        items.append(
            inbox.create_item(
                conversation_id=conv.id,
                target_participant_id=participant.participant_id,
                target_role="architect",
                target_address="@architect",
                sender_participant_id=None,
                sender_address="@human",
                source_message_id=message.id,
                item_type="mention",
                payload={"content": "@architect"},
            )
        )

    class ConcurrentGodLayer(FakeGodLayer):
        def __init__(self) -> None:
            super().__init__()
            self.context_by_session = {}
            self.active_receives = 0
            self.max_active_receives = 0

        async def ensure_conversation_session(self, **kwargs):
            self.ensured.append(kwargs)
            return type(
                "Record",
                (),
                {"god_session_id": kwargs["participant_id"]},
            )()

        async def send_message(
            self,
            god_session_id,
            message_type,
            prompt,
            context,
            request_id=None,
        ):
            self.sent.append((god_session_id, message_type, prompt, context, request_id))
            self.context_by_session[god_session_id] = json.loads(context)

        async def receive_message(self, god_session_id):
            import asyncio

            self.active_receives += 1
            self.max_active_receives = max(
                self.max_active_receives,
                self.active_receives,
            )
            try:
                await asyncio.sleep(0.02)
                context = self.context_by_session[god_session_id]
                item = context["inbox_item"]
                participant = participant_by_id[context["participant_id"]]
                reply = chat.add_message(
                    item["conversation_id"],
                    participant.participant_id,
                    "assistant",
                    f"{participant.display_name}: parallel reply.",
                )
                inbox.mark_read(item["id"], responded_message_id=reply.id)
                PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                    conversation_id=item["conversation_id"],
                    inbox_item_id=item["id"],
                    tool_name="chat_post_message",
                    called_at=1.0,
                )
                return self.receive_result
            finally:
                self.active_receives -= 1

    layer = ConcurrentGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_many(max_concurrent=3)

    assert outcome.happy_path == 3
    assert outcome.failed == 0
    assert layer.max_active_receives > 1
    assert {inbox.get(item.id).status for item in items} == {"read"}


@pytest.mark.asyncio
async def test_scheduler_tick_many_serializes_same_participant_delivery(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler same participant")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    inbox = ChatInboxStore(tmp_path / "chat.db")
    items = []
    for index in range(2):
        message = chat.add_message(
            conv.id,
            "Human",
            "human",
            f"@architect request {index}",
        )
        items.append(
            inbox.create_item(
                conversation_id=conv.id,
                target_participant_id=participant.participant_id,
                target_role="architect",
                target_address="@architect",
                sender_participant_id=None,
                sender_address="@human",
                source_message_id=message.id,
                item_type="mention",
                payload={"content": f"@architect request {index}"},
            )
        )

    class SameParticipantGodLayer(FakeGodLayer):
        def __init__(self) -> None:
            super().__init__()
            self.context_by_session = {}
            self.active_receives = 0
            self.max_active_receives = 0

        async def ensure_conversation_session(self, **kwargs):
            self.ensured.append(kwargs)
            return type(
                "Record",
                (),
                {"god_session_id": kwargs["participant_id"]},
            )()

        async def send_message(
            self,
            god_session_id,
            message_type,
            prompt,
            context,
            request_id=None,
        ):
            self.sent.append((god_session_id, message_type, prompt, context, request_id))
            self.context_by_session[god_session_id] = json.loads(context)

        async def receive_message(self, god_session_id):
            self.active_receives += 1
            self.max_active_receives = max(
                self.max_active_receives,
                self.active_receives,
            )
            try:
                await asyncio.sleep(0.02)
                context = self.context_by_session[god_session_id]
                item = context["inbox_item"]
                reply = chat.add_message(
                    item["conversation_id"],
                    participant.participant_id,
                    "assistant",
                    f"serialized reply for {item['id']}",
                )
                inbox.mark_read(item["id"], responded_message_id=reply.id)
                PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                    conversation_id=item["conversation_id"],
                    inbox_item_id=item["id"],
                    tool_name="chat_post_message",
                    called_at=1.0,
                )
                return self.receive_result
            finally:
                self.active_receives -= 1

    layer = SameParticipantGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_many(max_concurrent=2)

    assert outcome.happy_path == 2
    assert outcome.failed == 0
    assert layer.max_active_receives == 1
    assert len(layer.sent) == 2
    assert {inbox.get(item.id).status for item in items} == {"read"}


@pytest.mark.asyncio
async def test_scheduler_releases_claim_when_peer_turn_times_out(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler timeout")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )
    stream = ChatStreamStore(tmp_path / "chat.db").start_or_reset(
        conversation_id=conv.id,
        author=participant.participant_id,
        role="assistant",
        request_id=item.id,
        source_inbox_item_id=item.id,
    )
    ChatStreamStore(tmp_path / "chat.db").append_delta(stream.id, "Drafting...")

    class SlowGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            import asyncio

            await asyncio.sleep(1)
            return None

        async def abort_session(self, god_session_id):
            self.aborted = god_session_id

    layer = SlowGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.01,
        post_writeback_grace_s=0.01,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 0
    assert outcome.happy_path == 0
    assert outcome.failed == 1
    updated = inbox.get(item.id)
    assert updated.status == "unread"
    assert updated.nudge_count == 1
    assert updated.failure_reason is None
    assert layer.aborted == "god-live"
    streams = ChatStreamStore(tmp_path / "chat.db")
    assert streams.list_active(conv.id) == []
    assert streams.get(stream.id).status == "error"


@pytest.mark.asyncio
async def test_scheduler_preserves_latency_trace_for_retry_attempt(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler retry latency")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class RetryGodLayer(FakeGodLayer):
        def __init__(self) -> None:
            super().__init__()
            self.receive_attempts = 0

        async def receive_message(self, god_session_id):
            self.receive_attempts += 1
            if self.receive_attempts == 1:
                await asyncio.sleep(1)
                return None
            reply = chat.add_message(
                conv.id,
                participant.participant_id,
                "assistant",
                "Architect GOD: retry writeback succeeded.",
            )
            inbox.mark_read(item.id, responded_message_id=reply.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_post_message",
                called_at=100.0,
            )
            return self.receive_result

        async def abort_session(self, god_session_id):
            self.aborted = god_session_id

    layer = RetryGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.01,
        post_writeback_grace_s=0.01,
    )

    first = await scheduler.tick_once()
    second = await scheduler.tick_once()

    assert first.failed == 1
    assert second.happy_path == 1
    assert inbox.get(item.id).nudge_count == 1
    traces = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)
    assert [trace["delivery_mode"] for trace in traces] == [
        "mcp_writeback",
        "failed",
    ]
    assert traces[0]["id"] == f"peer_latency_{item.id}_attempt_2"
    assert traces[1]["id"] == f"peer_latency_{item.id}"
    assert traces[1]["degraded_reason"] == "peer_response_timeout"


@pytest.mark.asyncio
async def test_scheduler_accepts_timeout_after_real_mcp_writeback(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler timeout after writeback")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )
    stream = ChatStreamStore(tmp_path / "chat.db").start_or_reset(
        conversation_id=conv.id,
        author=participant.participant_id,
        role="assistant",
        request_id=item.id,
        source_inbox_item_id=item.id,
    )

    class LateReturningGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            import asyncio

            reply = chat.add_message(
                conv.id,
                participant.participant_id,
                "assistant",
                "I created the collaboration and routed the peer requests.",
            )
            inbox.mark_read(item.id, responded_message_id=reply.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_post_message",
                called_at=1.0,
            )
            await asyncio.sleep(1)
            return self.receive_result

        async def abort_session(self, god_session_id):
            self.aborted = god_session_id

    layer = LateReturningGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.01,
        post_writeback_grace_s=0.01,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 1
    assert outcome.happy_path == 1
    assert outcome.failed == 0
    assert layer.aborted == "god-live"
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    streams = ChatStreamStore(tmp_path / "chat.db")
    assert streams.list_active(conv.id) == []
    assert streams.get(stream.id).status == "done"
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] == "peer_writeback_before_provider_result"


@pytest.mark.asyncio
async def test_scheduler_records_success_when_peer_marks_inbox_read(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler success")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class ReplyingGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            reply = chat.add_message(
                conv.id,
                participant.participant_id,
                "assistant",
                "Architect GOD: received via MCP.",
            )
            inbox.mark_read(item.id, responded_message_id=reply.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_post_message",
                called_at=1.0,
            )
            return self.receive_result

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=ReplyingGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 1
    assert outcome.happy_path == 1
    assert outcome.failed == 0
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    replies = [
        msg
        for msg in chat.list_messages(conv.id)
        if msg.author == participant.participant_id
    ]
    assert [reply.id for reply in replies] == [updated.responded_message_id]


@pytest.mark.asyncio
async def test_scheduler_keeps_writeback_truth_when_provider_returns_error(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler writeback then provider error")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class ErrorAfterWritebackGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            reply = chat.add_message(
                conv.id,
                participant.participant_id,
                "assistant",
                "Architect GOD: persisted before provider exit.",
            )
            inbox.mark_read(item.id, responded_message_id=reply.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_post_message",
                called_at=1.0,
            )
            return type(
                "Message",
                (),
                {
                    "type": "error",
                    "code": "codex_exit_1",
                    "request_id": item.id,
                },
            )()

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=ErrorAfterWritebackGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 1
    assert outcome.happy_path == 1
    assert outcome.failed == 0
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] == "codex_exit_1_after_writeback"


@pytest.mark.asyncio
async def test_scheduler_records_success_when_peer_closes_inbox_with_proposal(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler proposal success")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@execute propose")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="execute",
        target_address="@execute",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@execute propose"},
    )

    class ProposalGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            proposal = chat.add_message(
                conv.id,
                participant.participant_id,
                "assistant",
                "Proposal: bounded execution lane_graph.",
                envelope_json={"envelope_type": "proposal"},
            )
            inbox.mark_read(item.id, responded_message_id=proposal.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_emit_proposal",
                called_at=1.0,
            )
            return self.receive_result

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=ProposalGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 1
    assert outcome.happy_path == 1
    assert outcome.failed == 0
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] is None


@pytest.mark.asyncio
async def test_scheduler_accepts_collaboration_request_tool_writeback(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler collaboration request writeback")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class CollaborationRequestGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            reply = chat.add_message(
                conv.id,
                participant.participant_id,
                "assistant",
                "Collaboration run created for @execute.",
                envelope_type="collaboration_request",
                envelope_json={"type": "collaboration_request"},
            )
            inbox.mark_read(item.id, responded_message_id=reply.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_create_collaboration_request",
                called_at=100.0,
            )
            return self.receive_result

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=CollaborationRequestGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 1
    assert outcome.failed == 0
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] is None


@pytest.mark.asyncio
async def test_scheduler_rejects_read_without_real_writeback_message(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler fake writeback")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class FakeWritebackGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            inbox.mark_read(item.id, responded_message_id="missing-reply-message")
            return self.receive_result

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=FakeWritebackGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 0
    assert outcome.failed == 1
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "failed"
    assert trace["degraded_reason"] == "peer_no_inbox_writeback_message"


@pytest.mark.asyncio
async def test_scheduler_accepts_structured_collaboration_response_writeback(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler structured collaboration writeback")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="execute",
        display_name="Execute GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Architect", "assistant", "Collaboration request")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="execute",
        target_address="@execute",
        sender_participant_id=None,
        sender_address="@architect",
        source_message_id=message.id,
        item_type="collaboration_request",
        payload={"content": "Use chat_record_collaboration_response."},
    )

    class StructuredWritebackGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            inbox.mark_read(item.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_record_collaboration_response",
                called_at=100.0,
            )
            return self.receive_result

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=StructuredWritebackGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 1
    assert outcome.failed == 0
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] is None


@pytest.mark.asyncio
async def test_scheduler_rejects_read_pointing_to_unrelated_message(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler unrelated writeback")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    unrelated = chat.add_message(conv.id, "human-1", "human", "existing unrelated message")
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class FakeWritebackGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            inbox.mark_read(item.id, responded_message_id=unrelated.id)
            return self.receive_result

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=FakeWritebackGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 0
    assert outcome.failed == 1
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "failed"
    assert trace["degraded_reason"] == "peer_no_inbox_writeback_message"


@pytest.mark.asyncio
async def test_scheduler_records_latency_trace_with_injected_clock(tmp_path: Path) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler latency")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class ReplyingGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            reply = chat.add_message(
                conv.id,
                participant.participant_id,
                "assistant",
                "Architect GOD: latency reply.",
            )
            inbox.mark_read(item.id, responded_message_id=reply.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_post_message",
                called_at=100.9,
            )
            return type(
                "Message",
                (),
                {
                    "type": "result",
                    "status": "success",
                    "request_id": item.id,
                    "message": "",
                    "artifacts": {
                        "latency_stages": {
                            "codex_app_server_turn_start": {"at": 100.45},
                            "mcp_tools_ready": {"at": 100.5},
                            "first_stream_delta": {"at": 100.6},
                            "chat_post_message": {"at": 100.9},
                        }
                    },
                },
            )()

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=ReplyingGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
        clock=FakeClock([100.0, 100.1, 100.4, 101.0, 101.3]),
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 1
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["message_created_at"] == item.created_at
    assert trace["inbox_claimed_at"] is not None
    assert trace["delivery_started_at"] == 100.1
    assert trace["provider_turn_started_at"] == 100.4
    assert trace["first_delta_at"] == 100.6
    assert trace["writeback_at"] == 101.3
    assert trace["total_latency_ms"] == 1300
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] is None
    assert trace["stage_timings"] == {
        "inbox_claim": {"at": 100.0},
        "ray_actor_delivery_start": {"at": 100.1},
        "codex_app_server_turn_start": {"at": 100.45},
        "mcp_tools_ready": {"at": 100.5},
        "first_stream_delta": {"at": 100.6},
        "first_visible": {"at": 100.6},
        "chat_post_message": {"at": 100.9},
        "scheduler_observed_result": {"at": 101.0},
        "trace_persisted": {"at": 101.3},
    }
    assert "scheduler_observed_inbox_read" not in trace["stage_timings"]


@pytest.mark.asyncio
async def test_scheduler_posts_peer_stdout_when_mcp_side_effect_is_missing(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler stdout reply")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class StdoutReplyGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            return type(
                "Message",
                (),
                {
                    "type": "result",
                    "status": "success",
                    "request_id": item.id,
                    "message": "Architect GOD: 我会先确认你的目标，再收敛为蓝图。",
                    "artifacts": {},
                },
            )()

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=StdoutReplyGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
        degraded_fallback_enabled=True,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 0
    assert outcome.happy_path == 0
    assert outcome.fallback_replies == 1
    assert outcome.failed == 0
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    reply = next(
        msg for msg in chat.list_messages(conv.id) if msg.id == updated.responded_message_id
    )
    assert reply.author == participant.participant_id
    assert reply.content == "Architect GOD: 我会先确认你的目标，再收敛为蓝图。"
    assert reply.envelope_json["degraded_reason"] == "stdout_fallback"
    assert reply.envelope_json["source_inbox_item_id"] == item.id
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "stdout_fallback"
    assert trace["degraded_reason"] == "stdout_fallback"


@pytest.mark.asyncio
async def test_scheduler_rejects_peer_stdout_without_degraded_fallback(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler stdout reply disabled")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )

    class StdoutReplyGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            return type(
                "Message",
                (),
                {
                    "type": "result",
                    "status": "success",
                    "request_id": item.id,
                    "message": "Architect GOD: stdout should not be persisted.",
                    "artifacts": {},
                },
            )()

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=StdoutReplyGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.fallback_replies == 0
    assert outcome.failed == 1
    updated = inbox.get(item.id)
    assert updated.status == "unread"
    replies = [
        msg
        for msg in chat.list_messages(conv.id)
        if msg.author == participant.participant_id
    ]
    assert replies == []
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "failed"
    assert trace["degraded_reason"] == "peer_no_inbox_side_effect"


@pytest.mark.asyncio
async def test_scheduler_records_mentions_from_peer_stdout_reply_without_routing(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler stdout mention")
    participants = ParticipantStore(tmp_path / "chat.db")
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="architect-god",
        cli_kind="codex",
        model="gpt-5.4",
    )
    execute = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="execute-god",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect ping execute")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=architect.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )

    class StdoutMentionGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            return type(
                "Message",
                (),
                {
                    "type": "result",
                    "status": "success",
                    "request_id": item.id,
                    "message": "@execute 你好呀。@human 这只是可见文本。@architect 不要回环。",
                    "artifacts": {},
                },
            )()

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=StdoutMentionGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
        degraded_fallback_enabled=True,
    )

    outcome = await scheduler.tick_once()

    assert outcome.nudged == 0
    assert outcome.happy_path == 0
    assert outcome.fallback_replies == 1
    updated = inbox.get(item.id)
    assert updated.status == "read"
    reply = next(
        msg for msg in chat.list_messages(conv.id) if msg.id == updated.responded_message_id
    )
    assert reply.envelope_json["degraded_reason"] == "stdout_fallback"
    assert reply.mentions == ["@execute"]

    assert execute.participant_id != architect.participant_id
    assert inbox.list_by_conversation(conv.id) == []


def test_peer_chat_nudge_prompt_has_short_turn_contract(tmp_path: Path) -> None:
    from xmuse_core.agents.codex_persistent import RunnerConfig, _format_turn_prompt

    prompt = _format_turn_prompt(
        RunnerConfig(
            model="gpt-5.4",
            mcp_port=8100,
            worktree=tmp_path,
            role="architect",
            timeout_s=900.0,
        ),
        msg_type="peer_chat_nudge",
        prompt="Use MCP tool chat_read_inbox, then respond.",
        context='{"conversation_id":"conv-1"}',
    )

    assert "## Peer chat expected result contract" in prompt
    assert "Keep this turn short" in prompt
    assert "chat_post_message" in prompt
    assert "chat_mention" in prompt
    assert "display-only" in prompt
    assert '"status":"executable"' in prompt
    assert '"evidence_refs":["<ref>"]' in prompt
    assert "verdict=feasible" in prompt
    assert "If MCP tools are unavailable" in prompt


@pytest.mark.asyncio
async def test_scheduler_degraded_fallback_posts_visible_reply_on_timeout(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler fallback")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    inbox = ChatInboxStore(tmp_path / "chat.db")
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": "@architect"},
    )
    stream = ChatStreamStore(tmp_path / "chat.db").start_or_reset(
        conversation_id=conv.id,
        author=participant.participant_id,
        role="assistant",
        request_id=item.id,
        source_inbox_item_id=item.id,
    )
    ChatStreamStore(tmp_path / "chat.db").append_delta(stream.id, "Drafting...")

    class SlowGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            import asyncio

            await asyncio.sleep(1)
            return None

        async def abort_session(self, god_session_id):
            self.aborted = god_session_id

    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=SlowGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.01,
        degraded_fallback_enabled=True,
    )

    outcome = await scheduler.tick_once()

    assert outcome.fallback_replies == 1
    assert outcome.happy_path == 0
    assert outcome.failed == 0
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    reply = next(
        msg for msg in chat.list_messages(conv.id) if msg.id == updated.responded_message_id
    )
    assert reply.author == participant.participant_id
    assert "快速确认兜底" in reply.content
    assert "peer_response_timeout" in reply.content
    streams = ChatStreamStore(tmp_path / "chat.db")
    assert streams.list_active(conv.id) == []
    assert streams.get(stream.id).status == "error"
