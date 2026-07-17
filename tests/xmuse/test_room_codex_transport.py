from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRecord, GodSessionRegistry
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentDescriptor, AgentRuntime
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_agent_stream import RoomAgentStreamCache, RoomAgentStreamProjector
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_codex_transport import CodexRoomObservationTransport
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_execution_store import RoomExecutionStoreError
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
)
from xmuse_core.chat.room_kernel import RoomKernelStore


class _GodLayer:
    def __init__(
        self,
        record: GodSessionRecord,
        messages: list[StdoutMessage | None],
        *,
        receive_hook: Callable[[], None] | None = None,
        binding_error: Exception | None = None,
        ensure_error: Exception | None = None,
        abort_error: Exception | None = None,
    ) -> None:
        self.record = record
        self.messages = messages
        self.receive_hook = receive_hook
        self.binding_error = binding_error
        self.ensure_error = ensure_error
        self.abort_error = abort_error
        self.ensure_calls: list[dict[str, object]] = []
        self.binding_calls: list[dict[str, object]] = []
        self.send_calls: list[dict[str, object]] = []
        self.abort_calls: list[str] = []

    async def ensure_conversation_session(self, **kwargs):
        self.ensure_calls.append(kwargs)
        if self.ensure_error is not None:
            raise self.ensure_error
        return self.record

    def require_live_provider_session_binding(self, **kwargs):
        self.binding_calls.append(kwargs)
        if self.binding_error is not None:
            raise self.binding_error
        return self.record

    async def send_message(
        self,
        god_session_id: str,
        message_type: str,
        prompt: str,
        context: str,
        request_id: str | None = None,
    ) -> None:
        self.send_calls.append(
            {
                "god_session_id": god_session_id,
                "message_type": message_type,
                "prompt": prompt,
                "context": context,
                "request_id": request_id,
            }
        )

    async def receive_message(self, god_session_id: str):
        if self.receive_hook is not None:
            hook, self.receive_hook = self.receive_hook, None
            hook()
        return self.messages.pop(0)

    async def abort_session(self, god_session_id: str) -> None:
        self.abort_calls.append(god_session_id)
        if self.abort_error is not None:
            raise self.abort_error


class _ExecutionReceiptStore:
    def __init__(self, error: RoomExecutionStoreError | None = None) -> None:
        self.error = error
        self.calls: list[dict[str, object]] = []

    def bind_review_material_receipt(self, **kwargs):
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return {**kwargs, "full_material_available": True}


class _MemoryRuntime:
    def __init__(self) -> None:
        self.binds: list[dict[str, object]] = []

    async def recall(self, _request):
        raise AssertionError("transport does not perform recall")

    def record_recall_receipt(self, **_kwargs):
        raise AssertionError("Host records recall before transport")

    def bind_context_receipt(self, **kwargs):
        self.binds.append(kwargs)

    async def pump_once(self):
        return False


class _ControlStore:
    def __init__(self) -> None:
        self.cleanup_calls: list[dict[str, object]] = []

    def mark_provider_ensure_started(self, **_kwargs) -> None:
        return None

    def bind_provider_session(self, **_kwargs) -> None:
        return None

    def mark_provider_cleanup(self, **kwargs) -> None:
        self.cleanup_calls.append(kwargs)


class _FailingSendGodLayer(_GodLayer):
    async def send_message(self, *args, **kwargs) -> None:
        await super().send_message(*args, **kwargs)
        raise OSError("provider send failed")


class _PreviewEventStream:
    def __init__(self) -> None:
        self.queue: asyncio.Queue[dict[str, object]] = asyncio.Queue()
        self.closed = False

    async def receive(self) -> dict[str, object]:
        return await self.queue.get()

    def close(self) -> None:
        self.closed = True


class _StreamingGodLayer(_GodLayer):
    def __init__(self, record: GodSessionRecord, messages: list[StdoutMessage | None]) -> None:
        super().__init__(record, messages)
        self.stream = _PreviewEventStream()

    def subscribe_native_events(self, _god_session_id: str) -> _PreviewEventStream:
        return self.stream

    async def send_message(self, *args, **kwargs) -> None:
        await super().send_message(*args, **kwargs)
        for event in (
            {"method": "turn/started", "params": {"turn": {"id": "turn-1"}}},
            {
                "method": "item/agentMessage/delta",
                "params": {"turnId": "turn-1", "delta": "Visible draft "},
            },
            {
                "method": "item/started",
                "params": {
                    "turnId": "turn-1",
                    "item": {"name": "chat_room_submit_outcome"},
                },
            },
            {
                "method": "item/agentMessage/delta",
                "params": {"turnId": "turn-1", "delta": "diagnostic"},
            },
            {
                "method": "item/completed",
                "params": {
                    "turnId": "turn-1",
                    "item": {"name": "chat_room_submit_outcome"},
                },
            },
            {
                "method": "turn/completed",
                "params": {"turn": {"id": "turn-1", "status": "completed"}},
            },
            {
                "method": "item/agentMessage/delta",
                "params": {"turnId": "turn-1", "delta": " late stale delta"},
            },
        ):
            self.stream.queue.put_nowait(event)


def _room(tmp_path: Path) -> tuple[Path, Path, str, Participant, GodSessionRecord]:
    db, registry = tmp_path / "chat.db", tmp_path / "god_sessions.json"
    conversation_id = RoomTestStore(db).create_conversation("room").id
    participant = ParticipantStore(db).add(
        conversation_id=conversation_id,
        role="review",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    record = GodSessionRegistry(registry).create(
        participant.role,
        participant.display_name,
        "codex",
        "@review",
        "inbox-review",
        conversation_id,
        participant.participant_id,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
    )
    return db, registry, conversation_id, participant, record


def _delivery(
    db: Path,
    conversation_id: str,
    participant: Participant,
) -> RoomObservationDelivery:
    kernel = RoomKernelStore(db)
    kernel.post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="Please inspect the failure mode",
        client_request_id="human-1",
    )
    claim = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="test-host",
    )
    assert claim is not None
    source = claim["activity"]
    activity = {
        "activity_id": source["activity_id"],
        "seq": source["seq"],
        "activity_type": source["activity_type"],
        "actor_kind": source["actor_kind"],
        "actor_identity": source["actor_identity"],
        "actor_participant_id": source["actor_participant_id"],
        "causation_id": source["causation_id"],
        "correlation_id": source["correlation_id"],
        "causal_depth": source["causal_depth"],
        "created_at": source["created_at"],
        "payload_preview": json.dumps(source["payload"], ensure_ascii=False),
    }
    return RoomObservationDelivery(
        conversation_id=conversation_id,
        participant=participant,
        observation=claim["observation"],
        source_activity=activity,
        recent_activities=(activity,),
        active_participants=(
            {
                "participant_id": participant.participant_id,
                "display_name": participant.display_name,
                "role": participant.role,
            },
        ),
        transport_request_id="room-observation:request-1",
        outcome_client_request_id="room-outcome:request-1",
    )


def _review_delivery(
    delivery: RoomObservationDelivery,
    material: dict[str, object],
) -> RoomObservationDelivery:
    source = {
        **delivery.source_activity,
        "activity_type": "proposal.created",
    }
    batch = {
        "schema_version": "room_observation_batch/v1",
        "batch_id": "batch-review-1",
        "phase": "peer",
        "correlation_id": source["correlation_id"],
        "primary_observation_id": delivery.observation["observation_id"],
        "cutoff_seq": source["seq"],
        "member_count": 1,
        "digest": "sha256:batch-review",
        "members": [
            {
                "ordinal": 0,
                "observation_id": delivery.observation["observation_id"],
                "activity": source,
            }
        ],
    }
    return replace(
        delivery,
        source_activity=source,
        recent_activities=(source,),
        batch=batch,
        human_root=source,
        attempt_id="attempt-review-1",
        execution_review_materials=(material,),
    )


def _review_material(activity_id: str, *, unified_diff: str = "@@ exact patch @@"):
    return {
        "schema_version": "room_execution_review_material/v1",
        "candidate_id": "execution_candidate_1",
        "proposal_id": "proposal_1",
        "proposal_activity_id": activity_id,
        "base_head": "a" * 40,
        "summary": "Review this exact patch",
        "allowed_files": ["src/example.py"],
        "candidate_digest": f"sha256:{'b' * 64}",
        "patch_sha256": f"sha256:{'c' * 64}",
        "patch_bytes": len(unified_diff.encode("utf-8")),
        "file_count": 1,
        "modify_only": True,
        "unified_diff": unified_diff,
    }


def test_delivers_exact_live_binding_with_complete_room_context(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    delivery = _delivery(db, conversation_id, participant)
    layer = _GodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
                message="provider final text",
            )
        ],
    )

    result = asyncio.run(
        CodexRoomObservationTransport(layer, worktree=tmp_path).deliver(delivery, timeout_s=3)
    )

    assert result.status == "finished"
    assert result.diagnostic_text == "provider final text"
    assert len(layer.ensure_calls) == 1
    ensured = layer.ensure_calls[0]
    assert ensured["conversation_id"] == conversation_id
    assert ensured["participant_id"] == participant.participant_id
    assert ensured["role"] == participant.role

    assert ensured["worktree"] == tmp_path
    assert ensured["model"] == participant.model
    assert ensured["feature_scope_id"] == ROOM_DELIVERY_SESSION_SCOPE
    assert str(ensured["prompt_fingerprint"]).startswith("sha256:")
    agent = ensured["agent"]
    assert agent == AgentDescriptor(
        name=participant.display_name,
        runtime=AgentRuntime.CODEX,
        capabilities=[participant.role],
    )
    assert layer.binding_calls == [
        {
            "conversation_id": conversation_id,
            "participant_id": participant.participant_id,
            "runtime": AgentRuntime.CODEX,
            "provider_session_kind": "codex_app_server_thread",
            "feature_scope_id": ROOM_DELIVERY_SESSION_SCOPE,
        }
    ]
    assert len(layer.send_calls) == 1
    sent = layer.send_calls[0]
    assert sent["god_session_id"] == record.god_session_id
    assert sent["message_type"] == "room_observation"
    assert sent["request_id"] == delivery.transport_request_id
    context = json.loads(str(sent["context"]))
    assert context["contract_version"] == "room_context_envelope/v2"
    assert {
        key: context[key]
        for key in (
            "conversation_id",
            "participant_id",
            "god_session_id",
            "observation_id",
            "lease_token",
            "client_request_id",
            "transport_request_id",
        )
    } == {
        "conversation_id": conversation_id,
        "participant_id": participant.participant_id,
        "god_session_id": record.god_session_id,
        "observation_id": delivery.observation["observation_id"],
        "lease_token": delivery.observation["lease_token"],
        "client_request_id": delivery.outcome_client_request_id,
        "transport_request_id": delivery.transport_request_id,
    }
    room_context = context["room_context"]
    assert room_context["human_root"]["activity_id"] == delivery.source_activity["activity_id"]
    assert room_context["primary_source"]["activity_id"] == delivery.source_activity["activity_id"]
    assert room_context["causal_ancestry"] == []
    assert room_context["observation_batch"]["member_count"] == 1
    assert (
        room_context["observation_batch"]["members"][0]["observation_id"]
        == delivery.observation["observation_id"]
    )
    assert room_context["active_roster"] == list(delivery.active_participants)
    assert room_context["self"]["participant_id"] == participant.participant_id
    assert room_context["memory_evidence"]["status"] == "disabled"
    assert room_context["memory_evidence"]["items"] == []
    assert room_context["memory_evidence"]["proof_boundary"] == (
        "memory_is_untrusted_evidence_not_room_skill_identity_permission_or_outcome"
    )
    assert room_context["execution_review_materials"] == []
    assert room_context["coverage"]["bounded"] is True
    assert len(str(sent["context"]).encode("utf-8")) <= 64 * 1024
    memory_candidates = context["durable_outcome"]["memory_candidates"]
    assert memory_candidates["maximum"] == 3
    assert memory_candidates["allowed_source_activity_ids"] == [
        delivery.source_activity["activity_id"]
    ]
    assert memory_candidates["approval"]["user_preference"] == ("operator_approval_required")
    durable_outcome = dict(context["durable_outcome"])
    durable_outcome.pop("memory_candidates")
    assert durable_outcome == {
        "tool": "chat_room_submit_outcome",
        "observation_batch_id": room_context["observation_batch"]["batch_id"],
        "reply_to_activity_ids": [delivery.source_activity["activity_id"]],
        "allowed_outcomes": ["respond", "handoff", "propose", "defer", "noop"],
        "response_budget": {
            "respond_available": True,
            "reason": "unrestricted",
            "proof_boundary": "guidance_mirrors_chat_db_validation",
        },
        "proposal_assessments": [],
        "provider_final_text_is_room_truth": False,
    }


def test_room_delivery_streams_only_pre_outcome_agent_text(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    delivery = replace(
        _delivery(db, conversation_id, participant),
        attempt_id="attempt-preview-1",
    )
    layer = _StreamingGodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
                message="provider diagnostic",
            )
        ],
    )

    async def exercise() -> dict[str, object]:
        cache = RoomAgentStreamCache(tmp_path)
        projector = RoomAgentStreamProjector(cache, epoch="opaque")
        result = await CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            stream_projector=projector,
        ).deliver(delivery, timeout_s=3)
        await projector.shutdown()
        assert result.status == "finished"
        return cache.read_raw(conversation_id)

    projection = asyncio.run(exercise())
    assert layer.stream.closed is True
    assert len(projection["streams"]) == 1
    stream = projection["streams"][0]
    assert stream["state"] == "resolved"
    assert stream["content"] == "Visible draft "
    assert "diagnostic" not in stream["content"]


def test_memory_context_hash_binds_only_after_provider_submission(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    delivery = replace(
        _delivery(db, conversation_id, participant),
        attempt_id="attempt-memory-success",
    )
    memory = _MemoryRuntime()
    success = _GodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
            )
        ],
    )

    result = asyncio.run(
        CodexRoomObservationTransport(
            success,
            worktree=tmp_path,
            memory_runtime=memory,
        ).deliver(delivery, timeout_s=2)
    )

    assert result.status == "finished"
    assert len(memory.binds) == 1
    assert memory.binds[0]["attempt_id"] == delivery.attempt_id
    assert str(memory.binds[0]["context_payload_sha256"]).startswith("sha256:")

    db2, _, conversation_id2, participant2, record2 = _room(tmp_path / "failed")
    failed_delivery = replace(
        _delivery(db2, conversation_id2, participant2),
        attempt_id="attempt-memory-failed",
    )
    failed_memory = _MemoryRuntime()
    failure = _FailingSendGodLayer(record2, [])
    failed_result = asyncio.run(
        CodexRoomObservationTransport(
            failure,
            worktree=tmp_path,
            memory_runtime=failed_memory,
        ).deliver(failed_delivery, timeout_s=2)
    )
    assert failed_result.status == "failed"
    assert failed_memory.binds == []


def test_echo_response_budget_is_explicit_in_provider_context(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    delivery = replace(
        _delivery(db, conversation_id, participant),
        allowed_outcomes=("handoff", "propose", "defer", "noop"),
        outcome_policy_reason="untargeted_peer_speech_after_response",
    )
    layer = _GodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
            )
        ],
    )

    result = asyncio.run(
        CodexRoomObservationTransport(layer, worktree=tmp_path).deliver(
            delivery,
            timeout_s=2,
        )
    )

    assert result.status == "finished"
    context = json.loads(str(layer.send_calls[0]["context"]))
    durable_outcome = dict(context["durable_outcome"])
    memory_candidates = durable_outcome.pop("memory_candidates")
    assert memory_candidates["maximum"] == 3
    assert durable_outcome == {
        "tool": "chat_room_submit_outcome",
        "observation_batch_id": context["room_context"]["observation_batch"]["batch_id"],
        "reply_to_activity_ids": [delivery.source_activity["activity_id"]],
        "allowed_outcomes": ["handoff", "propose", "defer", "noop"],
        "response_budget": {
            "respond_available": False,
            "reason": "untargeted_peer_speech_after_response",
            "proof_boundary": "guidance_mirrors_chat_db_validation",
        },
        "proposal_assessments": [],
        "provider_final_text_is_room_truth": False,
    }
    assert "Obey durable_outcome.allowed_outcomes" in str(layer.send_calls[0]["prompt"])


def test_legacy_oversized_roster_metadata_is_bounded_before_delivery(
    tmp_path: Path,
) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    delivery = _delivery(db, conversation_id, participant)
    oversized_participant = participant.model_copy(update={"display_name": "N" * 70_000})
    delivery = replace(
        delivery,
        participant=oversized_participant,
        active_participants=(
            {
                "participant_id": participant.participant_id,
                "display_name": "N" * 70_000,
                "role": "R" * 70_000,
                "persona_snapshot": None,
                "persona_snapshot_sha256": None,
            },
        ),
    )
    layer = _GodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
            )
        ],
    )

    result = asyncio.run(
        CodexRoomObservationTransport(layer, worktree=tmp_path).deliver(
            delivery,
            timeout_s=2,
        )
    )

    assert result.status == "finished"
    submitted = str(layer.send_calls[0]["context"])
    context = json.loads(submitted)
    assert len(submitted.encode("utf-8")) <= 64 * 1024
    assert len(context["room_context"]["self"]["display_name"]) == 120
    assert len(context["room_context"]["active_roster"][0]["role"]) == 64
    assert context["room_context"]["coverage"]["bounded"] is True


def test_batch_context_preserves_root_ancestry_members_and_reply_contract(
    tmp_path: Path,
) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    singleton = _delivery(db, conversation_id, participant)
    source = dict(singleton.source_activity)
    source["causation_id"] = "activity-parent"
    root = {
        **source,
        "activity_id": "activity-root",
        "seq": 1,
        "room_seq": 1,
        "causation_id": "causation-root",
        "actor_kind": "human",
        "content": "Human root",
    }
    ancestor = {
        **source,
        "activity_id": "activity-parent",
        "seq": 2,
        "room_seq": 2,
        "causation_id": "activity-root",
        "content": "Prior peer evidence",
    }
    second = {
        **source,
        "activity_id": "activity-peer-two",
        "seq": int(source["seq"]) + 1,
        "room_seq": int(source["seq"]) + 1,
        "content": "Second peer observation",
    }
    batch = {
        "schema_version": "room_observation_batch/v1",
        "batch_id": "batch-1",
        "phase": "peer",
        "correlation_id": "correlation-1",
        "primary_observation_id": singleton.observation["observation_id"],
        "cutoff_seq": second["seq"],
        "member_count": 2,
        "digest": "sha256:batch",
        "members": [
            {
                "ordinal": 0,
                "observation_id": singleton.observation["observation_id"],
                "activity": source,
            },
            {
                "ordinal": 1,
                "observation_id": "observation-peer-two",
                "activity": second,
            },
        ],
    }
    delivery = replace(
        singleton,
        source_activity=source,
        batch=batch,
        human_root=root,
        causal_ancestry=(ancestor,),
        recent_activities=(root, ancestor, source, second),
        context_coverage={
            "schema_version": "room_context_coverage/v1",
            "recent_burst_included_count": 4,
            "recent_burst_omitted_count": 7,
            "causal_ancestry_included_count": 1,
            "causal_ancestry_omitted_count": 0,
        },
    )
    layer = _GodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
            )
        ],
    )

    result = asyncio.run(
        CodexRoomObservationTransport(layer, worktree=tmp_path).deliver(
            delivery,
            timeout_s=2,
        )
    )

    assert result.status == "finished"
    sent = layer.send_calls[0]
    context = json.loads(str(sent["context"]))
    room = context["room_context"]
    assert room["human_root"]["activity_id"] == "activity-root"
    assert [item["activity_id"] for item in room["causal_ancestry"]] == ["activity-parent"]
    assert [item["activity"]["activity_id"] for item in room["observation_batch"]["members"]] == [
        source["activity_id"],
        "activity-peer-two",
    ]
    assert room["coverage"]["recent_burst_omitted_count"] == 7
    assert "Make one decision for the whole batch" in str(sent["prompt"])
    assert "reply_to_activity_id" in str(sent["prompt"])
    assert context["durable_outcome"]["observation_batch_id"] == delivery.batch["batch_id"]
    assert context["durable_outcome"]["reply_to_activity_ids"] == [
        delivery.source_activity["activity_id"],
        "activity-peer-two",
    ]
    assert (
        room["human_root"]["activity_id"] not in context["durable_outcome"]["reply_to_activity_ids"]
    )
    assert "xmuse_context.durable_outcome.reply_to_activity_ids" in str(sent["prompt"])
    assert "reply_to_activity_id is optional" in str(sent["prompt"])
    assert "including the Human root when absent from that list" in str(sent["prompt"])
    assert "context-only" in str(sent["prompt"])
    assert "plain-text assignment is only a suggestion" in str(sent["prompt"])
    assert "use a handoff outcome" in str(sent["prompt"])
    assert "durable attempt or outcome proving it" in str(sent["prompt"])
    assert "treat it as a directed baton" in str(sent["prompt"])
    assert "do the bounded investigation in this turn" in str(sent["prompt"])
    assert "Submit noop when it would only repeat" in str(sent["prompt"])
    assert "handoff author must not echo" in str(sent["prompt"])
    assert "first emit exactly one plain assistant draft" in str(sent["prompt"])
    assert "It must be the answer, not a preamble" in str(sent["prompt"])
    assert "call chat_room_submit_outcome with the same decision and content" in str(sent["prompt"])
    assert "For noop or defer, emit no assistant draft" in str(sent["prompt"])
    assert "code-mode-only surface" in str(sent["prompt"])
    assert "tools.mcp__xmuse_room__chat_room_submit_outcome" in str(sent["prompt"])
    assert "outcome_payload" in str(sent["prompt"])
    assert "never substitute content, message" in str(sent["prompt"])
    assert "built-in read-only workspace inspection tools" in str(sent["prompt"])
    assert "Never use the network, modify workspace bytes" in str(sent["prompt"])
    assert "inspection does not complete the observation" in str(sent["prompt"])
    assert "never end after inspection or an assistant draft alone" in str(sent["prompt"])
    assert "Do not inspect files" not in str(sent["prompt"])


def test_exact_execution_review_material_is_sent_and_receipted_with_final_context_hash(
    tmp_path: Path,
) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    base = _delivery(db, conversation_id, participant)
    material = _review_material(base.source_activity["activity_id"])
    delivery = _review_delivery(base, material)
    layer = _GodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
            )
        ],
    )
    receipts = _ExecutionReceiptStore()

    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            execution_store=receipts,  # type: ignore[arg-type]
        ).deliver(delivery, timeout_s=2)
    )

    assert result.status == "finished"
    submitted = str(layer.send_calls[0]["context"])
    context = json.loads(submitted)
    assert context["room_context"]["execution_review_materials"] == [material]
    assert context["durable_outcome"]["proposal_assessments"] == [
        {
            "proposal_id": material["proposal_id"],
            "candidate_digest": material["candidate_digest"],
            "allowed_assessments": ["endorse", "object", "abstain"],
        }
    ]
    assert "never vote from an activity summary" in str(layer.send_calls[0]["prompt"])
    assert len(receipts.calls) == 1
    receipt = receipts.calls[0]
    assert receipt["candidate_id"] == material["candidate_id"]
    assert receipt["proposal_activity_id"] == material["proposal_activity_id"]
    assert receipt["observation_batch_id"] == delivery.batch["batch_id"]
    assert receipt["attempt_id"] == delivery.attempt_id
    assert receipt["context_payload_sha256"] == (
        f"sha256:{hashlib.sha256(submitted.encode('utf-8')).hexdigest()}"
    )
    canonical_material = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    assert receipt["review_material_digest"] == (
        f"sha256:{hashlib.sha256(canonical_material.encode('utf-8')).hexdigest()}"
    )


def test_oversized_execution_review_material_is_omitted_atomically_and_cannot_vote(
    tmp_path: Path,
) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    base = _delivery(db, conversation_id, participant)
    material = _review_material(
        base.source_activity["activity_id"],
        unified_diff="x" * (70 * 1024),
    )
    delivery = _review_delivery(base, material)
    layer = _GodLayer(
        record,
        [
            StdoutMessage(
                type="result",
                request_id=delivery.transport_request_id,
                runtime="codex-app-server",
                status="success",
            )
        ],
    )
    receipts = _ExecutionReceiptStore()

    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            execution_store=receipts,  # type: ignore[arg-type]
        ).deliver(delivery, timeout_s=2)
    )

    assert result.status == "finished"
    submitted = str(layer.send_calls[0]["context"])
    context = json.loads(submitted)
    assert len(submitted.encode("utf-8")) <= 64 * 1024
    assert context["room_context"]["execution_review_materials"] == []
    assert context["durable_outcome"]["proposal_assessments"] == []
    assert context["room_context"]["coverage"]["execution_review_material_omitted_count"] == 1
    assert receipts.calls == []


def test_execution_review_receipt_conflict_fails_and_aborts_sent_turn(
    tmp_path: Path,
) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    base = _delivery(db, conversation_id, participant)
    material = _review_material(base.source_activity["activity_id"])
    delivery = _review_delivery(base, material)
    layer = _GodLayer(record, [])
    receipts = _ExecutionReceiptStore(
        RoomExecutionStoreError("room_execution_review_receipt_conflict")
    )

    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            execution_store=receipts,  # type: ignore[arg-type]
        ).deliver(delivery, timeout_s=2)
    )

    assert result.status == "failed"
    assert result.reason == "room_execution_review_receipt_conflict"
    assert len(layer.send_calls) == 1
    assert layer.abort_calls == [record.god_session_id]


def test_provider_final_text_cannot_complete_room_observation(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    record = replace(
        record,
        provider_session_id="provider-room-final-only",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
    )
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="hello",
        client_request_id="human-1",
    )
    layer = _GodLayer(record, [])

    async def receive(god_session_id: str):
        assert god_session_id == record.god_session_id
        return StdoutMessage(
            type="result",
            request_id=str(layer.send_calls[0]["request_id"]),
            status="success",
            message="This must not become a room message",
        )

    layer.receive_message = receive  # type: ignore[method-assign]
    controls = RoomObservationControlStore(db)
    outcome = asyncio.run(
        RoomParticipantHost(
            db,
            CodexRoomObservationTransport(
                layer,
                worktree=tmp_path,
                control_store=controls,
            ),
            policy=RoomHostPolicy(participant_cooldown_s=0),
            control_store=controls,
        ).pump_once(conversation_id=conversation_id)
    ).deliveries[0]

    assert (outcome.state, outcome.reason) == ("incomplete", "durable_outcome_missing")
    assert outcome.diagnostic_text == "This must not become a room message"
    observation = RoomKernelStore(db).get_observation(outcome.observation_id)
    assert observation["status"] == "pending" and observation["outcome_type"] is None
    assert observation["lease_token"] is None
    assert layer.abort_calls == [record.god_session_id]
    attempt = controls.reconcile_state(outcome.observation_id)["reconcile_binding"]
    assert attempt["provider_phase"] == "cleanup_succeeded"
    assert attempt["provider_cleanup_reason"] == (
        "room_codex_durable_outcome_missing:abort_succeeded"
    )
    messages = RoomTestStore(db).list_messages(conversation_id)
    assert [message.content for message in messages] == ["hello"]


def test_missing_outcome_abort_failure_does_not_reopen_lease(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    record = replace(
        record,
        provider_session_id="provider-room-abort-failure",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
    )
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="hello",
        client_request_id="human-abort-failure",
    )
    layer = _GodLayer(record, [], abort_error=RuntimeError("abort failed"))

    async def receive(god_session_id: str):
        assert god_session_id == record.god_session_id
        return StdoutMessage(
            type="result",
            request_id=str(layer.send_calls[0]["request_id"]),
            status="success",
            message="diagnostic only",
        )

    layer.receive_message = receive  # type: ignore[method-assign]
    controls = RoomObservationControlStore(db)
    outcome = asyncio.run(
        RoomParticipantHost(
            db,
            CodexRoomObservationTransport(
                layer,
                worktree=tmp_path,
                control_store=controls,
            ),
            policy=RoomHostPolicy(participant_cooldown_s=0),
            control_store=controls,
        ).pump_once(conversation_id=conversation_id)
    ).deliveries[0]

    assert (outcome.state, outcome.reason) == ("incomplete", "durable_outcome_missing")
    observation = RoomKernelStore(db).get_observation(outcome.observation_id)
    assert observation["status"] == "claimed"
    assert isinstance(observation["lease_token"], str)
    assert isinstance(outcome.retry_at, str)
    attempt = controls.reconcile_state(outcome.observation_id)["reconcile_binding"]
    assert attempt["provider_phase"] == "cleanup_pending"
    assert attempt["provider_cleanup_reason"] == ("room_codex_durable_outcome_missing:abort_failed")


def test_mcp_equivalent_durable_outcome_is_the_only_completion_evidence(
    tmp_path: Path,
) -> None:
    db, registry, conversation_id, participant, record = _room(tmp_path)
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="hello",
        client_request_id="human-1",
    )
    layer = _GodLayer(record, [])

    def submit_outcome() -> None:
        context = json.loads(str(layer.send_calls[0]["context"]))
        RoomApplicationService(db, registry).submit_participant_outcome(
            conversation_id=context["conversation_id"],
            participant_id=context["participant_id"],
            god_session_id=context["god_session_id"],
            observation_id=context["observation_id"],
            lease_token=context["lease_token"],
            client_request_id=context["client_request_id"],
            outcome_type="noop",
            outcome_payload={},
        )

    async def receive(god_session_id: str):
        submit_outcome()
        return StdoutMessage(
            type="result",
            request_id=str(layer.send_calls[0]["request_id"]),
            status="success",
            message="diagnostic after MCP",
        )

    layer.receive_message = receive  # type: ignore[method-assign]
    outcome = asyncio.run(
        RoomParticipantHost(
            db,
            CodexRoomObservationTransport(layer, worktree=tmp_path),
            policy=RoomHostPolicy(participant_cooldown_s=0),
        ).pump_once(conversation_id=conversation_id)
    ).deliveries[0]

    assert outcome.state == "completed" and outcome.outcome_type == "noop"
    assert outcome.diagnostic_text == "diagnostic after MCP"
    observation = RoomKernelStore(db).get_observation(outcome.observation_id)
    assert observation["status"] == "completed"
    assert observation["outcome_client_request_id"].startswith("room-outcome:")


def test_binding_and_terminal_protocol_fail_closed(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    delivery = _delivery(db, conversation_id, participant)
    unavailable = _GodLayer(
        record,
        [],
        binding_error=RuntimeError("provider_session_binding_not_live"),
    )
    result = asyncio.run(
        CodexRoomObservationTransport(unavailable, worktree=tmp_path).deliver(delivery, timeout_s=3)
    )
    assert result.status == "failed" and result.reason == "room_codex_binding_unavailable"
    assert unavailable.send_calls == []

    wrong_scope = _GodLayer(replace(record, feature_scope_id="legacy"), [])
    result = asyncio.run(
        CodexRoomObservationTransport(wrong_scope, worktree=tmp_path).deliver(delivery, timeout_s=3)
    )
    assert result.status == "failed"
    assert result.reason == "room_codex_binding_identity_mismatch"
    assert wrong_scope.send_calls == []

    ensure_failed = _GodLayer(
        record,
        [],
        ensure_error=RuntimeError("spawn failed"),
    )
    result = asyncio.run(
        CodexRoomObservationTransport(ensure_failed, worktree=tmp_path).deliver(
            delivery, timeout_s=3
        )
    )
    assert result.status == "failed" and result.reason == "room_codex_session_ensure_failed"
    assert ensure_failed.binding_calls == [] and ensure_failed.send_calls == []

    mismatch = _GodLayer(
        record,
        [StdoutMessage(type="result", request_id="another", status="success")],
    )
    result = asyncio.run(
        CodexRoomObservationTransport(mismatch, worktree=tmp_path).deliver(delivery, timeout_s=3)
    )
    assert result.status == "failed" and result.reason == "room_codex_request_mismatch"
    assert mismatch.abort_calls == [record.god_session_id]

    provider_error = _GodLayer(
        record,
        [
            StdoutMessage(
                type="error",
                request_id=delivery.transport_request_id,
                code="codex_app_server_error",
                message="turn failed",
            )
        ],
    )
    result = asyncio.run(
        CodexRoomObservationTransport(provider_error, worktree=tmp_path).deliver(
            delivery, timeout_s=3
        )
    )
    assert result.status == "failed" and result.reason == "room_codex_turn_failed"
    assert result.diagnostic_text == "turn failed"
    assert provider_error.abort_calls == [record.god_session_id]


def test_terminal_eof_records_identity_bound_provider_cleanup(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    bound = replace(
        record,
        provider_session_id="thread-eof",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
    )
    delivery = replace(
        _delivery(db, conversation_id, participant),
        attempt_id="attempt-eof",
    )
    layer = _GodLayer(bound, [None])
    controls = _ControlStore()

    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            control_store=controls,  # type: ignore[arg-type]
        ).deliver(delivery, timeout_s=3)
    )

    assert result.status == "failed" and result.reason == "room_codex_session_closed"
    assert layer.abort_calls == [record.god_session_id]
    assert [call["succeeded"] for call in controls.cleanup_calls] == [False, True]
    assert controls.cleanup_calls[-1]["attempt_id"] == "attempt-eof"
    assert controls.cleanup_calls[-1]["reason_code"] == (
        "room_codex_session_closed:abort_succeeded"
    )


def test_native_session_rebind_fences_terminal_and_never_aborts_replacement(
    tmp_path: Path,
) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    record = replace(
        record,
        provider_session_id="provider-session-fenced",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
    )
    delivery = replace(_delivery(db, conversation_id, participant), attempt_id="attempt-fenced")

    class RebindingLayer(_GodLayer):
        def __init__(self) -> None:
            super().__init__(
                record,
                [
                    StdoutMessage(
                        type="result",
                        request_id=delivery.transport_request_id,
                        status="success",
                    )
                ],
            )
            self.incarnation = 1

        def native_session_incarnation(self, _god_session_id: str) -> int:
            return self.incarnation

        async def receive_message(self, god_session_id: str):
            self.incarnation = 2
            return await super().receive_message(god_session_id)

    layer = RebindingLayer()
    controls = _ControlStore()
    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            control_store=controls,  # type: ignore[arg-type]
        ).deliver(delivery, timeout_s=3)
    )

    assert (result.status, result.reason) == ("failed", "room_codex_session_fenced")
    assert layer.abort_calls == []
    assert controls.cleanup_calls[-1]["reason_code"] == "room_codex_session_fenced:session_fenced"


def test_timeout_and_cancellation_abort_the_active_session(tmp_path: Path) -> None:
    db, _, conversation_id, participant, record = _room(tmp_path)
    delivery = _delivery(db, conversation_id, participant)

    class HangingLayer(_GodLayer):
        def __init__(self) -> None:
            super().__init__(record, [])
            self.receiving = asyncio.Event()

        async def receive_message(self, god_session_id: str):
            self.receiving.set()
            await asyncio.Event().wait()

    async def internal_timeout() -> None:
        layer = HangingLayer()
        result = await CodexRoomObservationTransport(layer, worktree=tmp_path).deliver(
            delivery, timeout_s=0.01
        )
        assert result.status == "failed" and result.reason == "room_codex_turn_timeout"
        assert layer.abort_calls == [record.god_session_id]

    async def caller_cancel() -> None:
        layer = HangingLayer()
        task = asyncio.create_task(
            CodexRoomObservationTransport(layer, worktree=tmp_path).deliver(delivery, timeout_s=3)
        )
        await layer.receiving.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert layer.abort_calls == [record.god_session_id]

    asyncio.run(internal_timeout())
    asyncio.run(caller_cancel())
