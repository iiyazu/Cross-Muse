from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from xmuse_core.agents.god_session_layer import GodSessionLayer
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentRuntime
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_scheduler import (
    PeerChatScheduler,
    _peer_session_prompt_fingerprint,
)
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.review_trigger_verdicts import build_review_trigger_verdict_envelope
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import ChatStreamStore, PeerTurnLatencyTraceStore
from xmuse_core.integrations.a2a_writeback_reconciler import (
    A2AProviderWritebackReconciler,
)
from xmuse_core.providers.adapters.base import ProviderFailureKind, ProviderInvocationResult
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderId, ProviderProfileId, TaskCapability
from xmuse_core.providers.registry import DEFAULT_A2A_REMOTE_ENDPOINT_ENV_NAME
from xmuse_core.providers.service import RunnerProviderService


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
async def test_scheduler_restores_participant_sessions_after_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    chat = ChatStore(db_path)
    participants = ParticipantStore(db_path)
    inbox = ChatInboxStore(db_path)
    conv = chat.create_conversation("Restartable groupchat")
    roster = {
        role: participants.add(
            conversation_id=conv.id,
            role=role,
            display_name=f"{role.title()} GOD",
            cli_kind="codex",
            model="gpt-5.4",
        )
        for role in ("architect", "review", "execute")
    }
    writebacks: list[dict[str, str]] = []
    spawned_sessions: list[object] = []

    class PersistentTestLauncher:
        supports_persistent_sessions = True

        def __init__(self) -> None:
            self.build_persistent_command_calls: list[tuple[str, Path]] = []

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            self.build_persistent_command_calls.append((role, worktree))
            return ["fake-peer", role, str(worktree)]

        def build_env(self, role: str):
            return None

    class DurableWritebackSession:
        def __init__(self) -> None:
            self.sent: list[tuple[str, dict[str, object]]] = []
            self.aborted = False

        def is_alive(self) -> bool:
            return not self.aborted

        async def send_typed(self, msg_type: str, **kwargs) -> None:
            self.sent.append((msg_type, kwargs))

        async def receive(self):
            _, payload = self.sent[-1]
            context = json.loads(str(payload["context"]))
            item = context["inbox_item"]
            participant_id = str(context["participant_id"])
            god_session_id = str(payload["god_session_id"])
            participant = participants.get(participant_id)
            reply = chat.add_message(
                item["conversation_id"],
                participant_id,
                "assistant",
                f"{participant.display_name}: durable reply for {item['id']}",
            )
            inbox.mark_read(item["id"], responded_message_id=reply.id)
            PeerTurnLatencyTraceStore(db_path).record_mcp_tool_stage(
                conversation_id=item["conversation_id"],
                inbox_item_id=item["id"],
                tool_name="chat_post_message",
                called_at=1.0,
            )
            writebacks.append(
                {
                    "god_session_id": god_session_id,
                    "participant_id": participant_id,
                    "role": participant.role,
                    "inbox_item_id": item["id"],
                    "message_id": reply.id,
                }
            )
            return StdoutMessage(
                type="result",
                request_id=str(payload.get("request_id") or ""),
                status="success",
            )

        async def abort(self) -> None:
            self.aborted = True

    async def fake_spawn(command, env=None):
        session = DurableWritebackSession()
        spawned_sessions.append(session)
        return session

    monkeypatch.setattr(
        "xmuse_core.agents.god_session_layer.LocalSession.spawn",
        fake_spawn,
    )
    launcher = PersistentTestLauncher()

    def enqueue(role: str, content: str):
        participant = roster[role]
        message = chat.add_message(conv.id, "Human", "human", content)
        return inbox.create_item(
            conversation_id=conv.id,
            target_participant_id=participant.participant_id,
            target_role=participant.role,
            target_address=f"@{role}",
            sender_participant_id=None,
            sender_address="@human",
            source_message_id=message.id,
            item_type="mention",
            payload={"content": content},
        )

    first_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: launcher},
    )
    first_scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=first_layer,
        worktree=tmp_path,
        scheduler_id="sched-first",
        response_wait_s=1.0,
    )
    first_items = {
        role: enqueue(role, f"@{role} first turn")
        for role in ("architect", "review", "execute")
    }

    for _role in ("architect", "review", "execute"):
        outcome = await first_scheduler.tick_once()
        assert outcome.happy_path == 1
        assert outcome.failed == 0

    registry = GodSessionRegistry(registry_path)
    first_sessions = {
        role: registry.find_by_conversation_participant(
            conv.id,
            roster[role].participant_id,
        )
        for role in ("architect", "review", "execute")
    }
    assert len({session.god_session_id for session in first_sessions.values()}) == 3
    assert {inbox.get(item.id).status for item in first_items.values()} == {"read"}

    restarted_layer = GodSessionLayer(
        registry_path=registry_path,
        launchers={AgentRuntime.CODEX: launcher},
    )
    restarted_scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=restarted_layer,
        worktree=tmp_path,
        scheduler_id="sched-restarted",
        response_wait_s=1.0,
    )
    restarted_items = {
        role: enqueue(role, f"@{role} after restart")
        for role in ("architect", "review", "execute")
    }

    for _role in ("architect", "review", "execute"):
        outcome = await restarted_scheduler.tick_once()
        assert outcome.happy_path == 1
        assert outcome.failed == 0

    restarted_sessions = {
        role: registry.find_by_conversation_participant(
            conv.id,
            roster[role].participant_id,
        )
        for role in ("architect", "review", "execute")
    }
    assert {
        role: session.god_session_id
        for role, session in restarted_sessions.items()
    } == {
        role: session.god_session_id
        for role, session in first_sessions.items()
    }
    assert {inbox.get(item.id).status for item in restarted_items.values()} == {"read"}
    assert len(spawned_sessions) == 6
    assert len(writebacks) == 6
    for role, participant in roster.items():
        participant_writebacks = [
            writeback
            for writeback in writebacks
            if writeback["participant_id"] == participant.participant_id
        ]
        assert [writeback["role"] for writeback in participant_writebacks] == [
            role,
            role,
        ]
        assert {
            writeback["god_session_id"]
            for writeback in participant_writebacks
        } == {first_sessions[role].god_session_id}

    traces = PeerTurnLatencyTraceStore(db_path).list_recent(conv.id, limit=10)
    assert len(traces) == 6
    assert {trace["delivery_mode"] for trace in traces} == {"mcp_writeback"}
    messages = chat.list_messages(conv.id)
    for _role, participant in roster.items():
        assistant_messages = [
            message
            for message in messages
            if message.author == participant.participant_id
            and message.role == "assistant"
        ]
        assert len(assistant_messages) == 2
        assert all(
            participant.display_name in message.content
            for message in assistant_messages
        )


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
    assert '"execution_performed":false' in layer.sent[0][2]
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
    assert context["group_chat"]["source_refs"] == [
        f"chat.db:conversation:{conv.id}",
        "god_sessions:god_sessions.json",
        f"chat.db:structured_state:{conv.id}",
    ]
    assert context["group_chat"]["session_bindings"][0]["participant_id"] == (
        participant.participant_id
    )
    assert context["group_chat"]["session_bindings"][0]["session_status"] == "unbound"
    assert context["group_chat"]["participant_profiles"][0]["mention_handle"] == (
        "@architect"
    )
    assert context["group_chat"]["structured_state"]["source"] == "chat.db"
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
        response_wait_s=1.0,
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
async def test_scheduler_terminalizes_claim_and_spine_when_peer_turn_times_out(
    tmp_path: Path,
) -> None:
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
    AcceptanceSpineStore(tmp_path / "chat.db").create_for_intake(
        conversation_id=conv.id,
        intake_message_id=message.id,
    )
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

        async def active_latency_stages(self, god_session_id):
            assert god_session_id == "god-live"
            return {
                "mcp_tools_ready": {"at": 10.0},
                "codex_app_server_turn_start": {"at": 10.5},
                "first_stream_delta": {"at": 11.0},
            }

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
    assert updated.status == "failed"
    assert updated.nudge_count == 0
    assert updated.failure_reason == "provider_no_mcp_writeback_before_deadline"
    assert layer.aborted == "god-live"
    streams = ChatStreamStore(tmp_path / "chat.db")
    assert streams.list_active(conv.id) == []
    assert streams.get(stream.id).status == "error"
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "failed"
    assert trace["degraded_reason"] == "provider_no_mcp_writeback_before_deadline"
    assert trace["stage_timings"]["mcp_tools_ready"] == {"at": 10.0}
    assert trace["stage_timings"]["codex_app_server_turn_start"] == {"at": 10.5}
    assert trace["stage_timings"]["first_stream_delta"] == {"at": 11.0}
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(message.id)
    assert spine.status is AcceptanceSpineStatus.FAILED
    assert spine.blocked_reason == "provider_no_mcp_writeback_before_deadline"
    assert spine.execution_evidence_refs == [
        f"peer_turn_latency_traces#trace={trace['id']}"
    ]


@pytest.mark.asyncio
async def test_scheduler_terminalizes_claim_and_spine_when_peer_turn_is_cancelled(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler cancellation")
    participant = ParticipantStore(tmp_path / "chat.db").add(
        conversation_id=conv.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "Human", "human", "@architect")
    AcceptanceSpineStore(tmp_path / "chat.db").create_for_intake(
        conversation_id=conv.id,
        intake_message_id=message.id,
    )
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

    class HangingGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            await asyncio.sleep(60)
            return None

        async def active_latency_stages(self, god_session_id):
            assert god_session_id == "god-live"
            return {"mcp_tools_ready": {"at": 20.0}}

        async def abort_session(self, god_session_id):
            self.aborted = god_session_id

    layer = HangingGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=180.0,
    )
    task = asyncio.create_task(scheduler.tick_once())
    for _ in range(50):
        if layer.sent:
            break
        await asyncio.sleep(0.01)
    assert layer.sent

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    updated = inbox.get(item.id)
    assert updated.status == "failed"
    assert updated.failure_reason == "provider_turn_cancelled_before_mcp_writeback"
    assert layer.aborted == "god-live"
    trace = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "failed"
    assert trace["degraded_reason"] == "provider_turn_cancelled_before_mcp_writeback"
    assert trace["stage_timings"]["mcp_tools_ready"] == {"at": 20.0}
    spine = AcceptanceSpineStore(tmp_path / "chat.db").get_by_intake_message(message.id)
    assert spine.status is AcceptanceSpineStatus.FAILED
    assert spine.blocked_reason == "provider_turn_cancelled_before_mcp_writeback"
    assert spine.execution_evidence_refs == [
        f"peer_turn_latency_traces#trace={trace['id']}"
    ]


@pytest.mark.asyncio
async def test_scheduler_preserves_latency_trace_for_terminal_timeout(
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
    assert first.failed == 1
    assert inbox.get(item.id).status == "failed"
    assert inbox.get(item.id).failure_reason == "provider_no_mcp_writeback_before_deadline"
    traces = PeerTurnLatencyTraceStore(tmp_path / "chat.db").list_recent(conv.id)
    assert [trace["delivery_mode"] for trace in traces] == ["failed"]
    assert traces[0]["id"] == f"peer_latency_{item.id}"
    assert traces[0]["degraded_reason"] == "provider_no_mcp_writeback_before_deadline"


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
async def test_scheduler_accepts_a2a_provider_result_writeback_without_mcp_stage(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conv = chat.create_conversation("Scheduler A2A provider writeback")
    participant = ParticipantStore(db_path).add(
        conversation_id=conv.id,
        role="review",
        display_name="Remote Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "a2a:external-planner", "assistant", "@review")
    inbox = ChatInboxStore(db_path)
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="review",
        target_address="@review",
        sender_participant_id=None,
        sender_address="a2a:external-planner",
        source_message_id=message.id,
        item_type="a2a_task",
        payload={"content": "@review inspect this remote task."},
    )

    class A2AWritebackGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            A2AProviderWritebackReconciler(db_path).record_provider_result(
                conversation_id=conv.id,
                participant_id=participant.participant_id,
                reply_to_inbox_item_id=item.id,
                provider_result=ProviderInvocationResult(
                    request_id="lane-a2a:review",
                    provider_id=ProviderId.A2A,
                    profile_id=ProviderProfileId.REMOTE,
                    status=WorkerResultStatus.COMPLETED,
                    evidence_refs=[
                        "a2a_task:lane-a2a:review",
                        "a2a_context:lane-a2a",
                    ],
                    diagnostic_payload={
                        "a2a_content": "Remote A2A review completed.",
                        "a2a_source_refs": [
                            "a2a_task:lane-a2a:review",
                            "a2a_context:lane-a2a",
                        ],
                    },
                ),
            )
            return self.receive_result

    scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=A2AWritebackGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 1
    assert outcome.failed == 0
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    reply = next(
        msg for msg in chat.list_messages(conv.id) if msg.id == updated.responded_message_id
    )
    assert reply.envelope_type == "a2a_provider_result"
    assert reply.envelope_json["authority"] == "chat.db/inbox"
    assert reply.envelope_json["a2a_is_authority"] is False
    trace = PeerTurnLatencyTraceStore(db_path).list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "mcp_writeback"
    assert trace["degraded_reason"] is None


@pytest.mark.asyncio
async def test_scheduler_delivers_a2a_participant_via_provider_writeback(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conv = chat.create_conversation("Scheduler A2A provider participant")
    participant = ParticipantStore(db_path).add(
        conversation_id=conv.id,
        role="review",
        display_name="Remote A2A Review GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    source = chat.add_message(conv.id, "Human", "human", "@review inspect this.")
    inbox = ChatInboxStore(db_path)
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="review",
        target_address="@review",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload={"content": "@review inspect this."},
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("A2A participants must not use GodSessionLayer")

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
                evidence_refs=[
                    f"a2a_task:{invocation.request_id}",
                    f"a2a_context:{invocation.request_id}",
                ],
                diagnostic_payload={
                    "a2a_task_id": invocation.request_id,
                    "a2a_context_id": invocation.request_id,
                    "a2a_state": "TASK_STATE_COMPLETED",
                    "a2a_disposition": "completed",
                    "a2a_terminal": True,
                    "a2a_content": "Remote A2A participant completed review.",
                    "a2a_artifacts": [],
                    "a2a_history": [],
                    "a2a_metadata": {},
                    "a2a_source_refs": [
                        f"a2a_task:{invocation.request_id}",
                        f"a2a_context:{invocation.request_id}",
                    ],
                    "a2a_sdk_task": {
                        "id": invocation.request_id,
                        "status": {"state": "TASK_STATE_COMPLETED"},
                    },
                    "a2a_jsonrpc_id": invocation.request_id,
                },
            )

    provider_service = FakeProviderService()
    scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
        provider_service=provider_service,
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 1
    assert outcome.failed == 0
    [invocation] = provider_service.invocations
    assert invocation.provider_profile_ref == "a2a.remote"
    assert invocation.task_type is TaskCapability.REVIEW
    assert invocation.writeback_context is not None
    assert invocation.writeback_context.conversation_id == conv.id
    assert invocation.writeback_context.participant_id == participant.participant_id
    assert invocation.writeback_context.reply_to_inbox_item_id == item.id
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    reply = next(
        msg for msg in chat.list_messages(conv.id) if msg.id == updated.responded_message_id
    )
    assert reply.author == participant.participant_id
    assert reply.envelope_type == "a2a_provider_result"
    assert reply.envelope_json["authority"] == "chat.db/inbox"
    assert reply.envelope_json["a2a_is_authority"] is False
    assert reply.envelope_json["provider_status"] == "completed"
    trace = PeerTurnLatencyTraceStore(db_path).list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "a2a_provider_writeback"
    assert trace["degraded_reason"] is None


@pytest.mark.asyncio
async def test_scheduler_writes_durable_a2a_config_error_when_endpoint_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv(DEFAULT_A2A_REMOTE_ENDPOINT_ENV_NAME, raising=False)
    db_path = tmp_path / "chat.db"
    chat = ChatStore(db_path)
    conv = chat.create_conversation("Scheduler A2A provider config blocker")
    participant = ParticipantStore(db_path).add(
        conversation_id=conv.id,
        role="architect",
        display_name="Remote A2A Architect GOD",
        cli_kind="a2a",
        model="a2a-remote",
    )
    source = chat.add_message(conv.id, "Human", "human", "@architect plan this.")
    inbox = ChatInboxStore(db_path)
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=participant.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=source.id,
        item_type="mention",
        payload={"content": "@architect plan this."},
    )

    class ForbiddenGodLayer:
        async def ensure_conversation_session(self, **kwargs):
            raise AssertionError("A2A participants must not use GodSessionLayer")

    scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=ForbiddenGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
        provider_service=RunnerProviderService(),
    )

    outcome = await scheduler.tick_once()

    assert outcome.happy_path == 1
    assert outcome.failed == 0
    updated = inbox.get(item.id)
    assert updated.status == "read"
    assert updated.responded_message_id is not None
    reply = next(
        msg for msg in chat.list_messages(conv.id) if msg.id == updated.responded_message_id
    )
    assert reply.envelope_type == "a2a_provider_result"
    assert reply.envelope_json["provider_status"] == "failed"
    assert reply.envelope_json["failure_kind"] == ProviderFailureKind.CONFIG_ERROR.value
    assert reply.envelope_json["diagnostic_payload"]["a2a_disposition"] == "failed"
    assert reply.envelope_json["diagnostic_payload"]["a2a_content"].startswith(
        "A2A provider is not configured:"
    )
    trace = PeerTurnLatencyTraceStore(db_path).list_recent(conv.id)[0]
    assert trace["delivery_mode"] == "a2a_provider_writeback"
    assert trace["degraded_reason"] == "a2a_provider_failed:config_error"


@pytest.mark.asyncio
async def test_scheduler_retries_collaboration_request_with_writeback_feedback(
    tmp_path: Path,
) -> None:
    chat = ChatStore(tmp_path / "chat.db")
    conv = chat.create_conversation("Scheduler collaboration retry")
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

    class RetryGodLayer(FakeGodLayer):
        def __init__(self) -> None:
            super().__init__()
            self.received = 0

        async def receive_message(self, god_session_id):
            self.received += 1
            if self.received == 1:
                return self.receive_result
            inbox.mark_read(item.id)
            PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                conversation_id=conv.id,
                inbox_item_id=item.id,
                tool_name="chat_record_collaboration_response",
                called_at=100.0,
            )
            return self.receive_result

    god_layer = RetryGodLayer()
    scheduler = PeerChatScheduler(
        db_path=tmp_path / "chat.db",
        god_layer=god_layer,
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
    )

    first = await scheduler.tick_once()
    second = await scheduler.tick_once()

    assert first.failed == 1
    assert second.happy_path == 1
    assert len(god_layer.sent) == 2
    retry_prompt = god_layer.sent[1][2]
    assert "Retry feedback for this same collaboration_request" in retry_prompt
    assert "Plain final text or stream output was not accepted" in retry_prompt
    assert "chat_record_collaboration_response" in retry_prompt


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
            for tool_stage in (
                "mcp_tool_call_detected",
                "mcp_tool_call_started",
                "mcp_tool_call_completed",
                "chat_post_message_persisted",
            ):
                PeerTurnLatencyTraceStore(tmp_path / "chat.db").record_mcp_tool_stage(
                    conversation_id=conv.id,
                    inbox_item_id=item.id,
                    tool_name=tool_stage,
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
                            "provider_session_started": {"at": 100.4},
                            "mcp_tools_ready": {"at": 100.5},
                            "first_stream_delta": {"at": 100.6},
                            "mcp_tool_call_detected": {"at": 100.9},
                            "mcp_tool_call_started": {"at": 100.9},
                            "mcp_tool_call_completed": {"at": 100.9},
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
    assert trace["god_session_id"] == "god-live"
    assert trace["provider_session_id"] == "provider-thread-live"
    assert trace["provider_session_kind"] == "codex_app_server_thread"
    assert trace["provider_binding_status"] == "active"
    assert trace["provider_binding_failure_reason"] is None
    assert trace["stage_timings"] == {
        "inbox_claim": {"at": 100.0},
        "ray_actor_delivery_start": {"at": 100.1},
        "codex_app_server_turn_start": {"at": 100.45},
        "provider_session_started": {"at": 100.4},
        "mcp_tools_ready": {"at": 100.5},
        "first_stream_delta": {"at": 100.6},
        "first_visible": {"at": 100.6},
        "mcp_tool_call_detected": {"at": 100.9},
        "mcp_tool_call_started": {"at": 100.9},
        "mcp_tool_call_completed": {"at": 100.9},
        "chat_post_message": {"at": 100.9},
        "chat_post_message_persisted": {"at": 100.9},
        "provider_raw_result_received": {"at": 101.0},
        "scheduler_observed_durable_writeback": {"at": 101.0},
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
async def test_scheduler_does_not_consume_review_trigger_with_stdout_fallback(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "chat.db"
    registry_path = tmp_path / "god_sessions.json"
    service = PeerChatService(db_path)
    created = service.create_conversation(title="Review trigger stdout guard")
    conversation_id = created["conversation"]["id"]
    participants = {
        participant["role"]: participant["participant_id"]
        for participant in created["participants"]
    }
    sessions = {
        session["role"]: session["god_session_id"]
        for session in created["participant_sessions"]
    }
    proposal = service.emit_proposal_without_session_for_test(
        conversation_id=conversation_id,
        participant_id=participants["architect"],
        client_request_id="proposal-review-trigger-stdout-guard",
        summary="Review trigger stdout fallback must not clear authority",
        lanes=[
            {
                "feature_id": "review-trigger-stdout-guard",
                "prompt": "Keep review trigger retryable until structured verdict writeback.",
                "depends_on": [],
                "capabilities": ["code"],
            }
        ],
    )
    inbox = ChatInboxStore(db_path)
    review_item = next(
        item
        for item in inbox.list_by_conversation(conversation_id)
        if item.item_type == "review_trigger"
    )

    class StdoutReviewGodLayer(FakeGodLayer):
        async def receive_message(self, god_session_id):
            return type(
                "Message",
                (),
                {
                    "type": "result",
                    "status": "success",
                    "request_id": review_item.id,
                    "message": (
                        "REVIEW_VERDICT: dispatch_allowed\n"
                        "stdout-only review must remain diagnostic."
                    ),
                    "artifacts": {},
                },
            )()

    scheduler = PeerChatScheduler(
        db_path=db_path,
        god_layer=StdoutReviewGodLayer(),
        worktree=tmp_path,
        scheduler_id="sched-test",
        response_wait_s=0.1,
        degraded_fallback_enabled=True,
    )

    outcome = await scheduler.tick_once()

    assert outcome.fallback_replies == 0
    assert outcome.failed == 1
    updated = inbox.get(review_item.id)
    assert updated.status == "unread"
    assert updated.responded_message_id is None
    review_messages = [
        message
        for message in ChatStore(db_path).list_messages(conversation_id)
        if message.author == participants["review"]
    ]
    assert review_messages == []
    trace = PeerTurnLatencyTraceStore(db_path).list_recent(conversation_id)[0]
    assert trace["delivery_mode"] == "failed"
    assert trace["degraded_reason"] == "peer_no_inbox_side_effect"

    structured = service.post_god_message(
        registry_path=registry_path,
        conversation_id=conversation_id,
        participant_id=participants["review"],
        god_session_id=sessions["review"],
        client_request_id="review-trigger-structured-verdict-after-stdout",
        content="Structured review verdict clears the still-unread review trigger.",
        envelope=build_review_trigger_verdict_envelope(
            review_trigger_inbox_id=review_item.id,
            source_message_id=review_item.source_message_id,
            proposal_id=proposal["proposal"]["id"],
            decision="dispatch_allowed",
            summary="Structured review verdict clears the still-unread review trigger.",
            evidence_refs=[f"inbox:{review_item.id}", f"proposal:{proposal['proposal']['id']}"],
        ),
        reply_to_inbox_item_id=review_item.id,
    )

    reread = inbox.get(review_item.id)
    assert reread.status == "read"
    assert reread.responded_message_id == structured["message"]["id"]


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
    assert '"execution_performed":false' in prompt
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
    assert "provider_no_mcp_writeback_before_deadline" in reply.content
    streams = ChatStreamStore(tmp_path / "chat.db")
    assert streams.list_active(conv.id) == []
    assert streams.get(stream.id).status == "error"
