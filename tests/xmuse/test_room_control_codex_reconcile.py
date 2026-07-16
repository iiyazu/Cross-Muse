from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.room_codex_scopes import ROOM_DELIVERY_SESSION_SCOPE
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_codex_transport import CodexRoomObservationTransport
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_host import (
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

NOW = datetime(2026, 1, 1, tzinfo=UTC)


class _GodLayer:
    def __init__(self, record: GodSessionRecord) -> None:
        self.record = record
        self.ensure_calls = []
        self.binding_calls = []
        self.abort_calls = []
        self.abort_error: Exception | None = None
        self.messages = []
        self.promote_on_ensure = False

    async def ensure_conversation_session(self, **kwargs):
        self.ensure_calls.append(kwargs)
        if self.promote_on_ensure:
            self.record = replace(
                self.record,
                status="running",
                provider_session_id="thread-recovered-during-ensure",
                provider_session_kind="codex_app_server_thread",
                provider_binding_status="active",
            )
        return self.record

    def require_live_provider_session_binding(self, **kwargs):
        self.binding_calls.append(kwargs)
        return self.record

    async def send_message(self, *args, **kwargs):
        return None

    async def receive_message(self, god_session_id):
        return self.messages.pop(0)

    async def abort_session(self, god_session_id):
        self.abort_calls.append(god_session_id)
        if self.abort_error is not None:
            raise self.abort_error


def _bound_delivery(tmp_path):
    path = tmp_path / "chat.db"
    conversation = RoomTestStore(path).create_conversation("Codex controlled room")
    participant = ParticipantStore(path).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    kernel = RoomKernelStore(path)
    kernel.post_human_activity(
        conversation_id=conversation.id,
        human_id="alice",
        content="review",
        client_request_id="human-1",
    )
    claim = kernel.claim_next_observation(
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        lease_owner="host-1",
        lease_ttl_s=30,
        now=NOW,
    )
    assert claim is not None
    controls = RoomObservationControlStore(path)
    attempt_id = claim["attempt"]["attempt_id"]
    RoomAttemptSkillDecisionStore(path).bind_for_attempt(
        attempt_id=attempt_id,
        catalog=SkillCatalog.load_bundled(),
        now=NOW,
    )
    controls.bind_delivery(
        observation_id=claim["observation"]["observation_id"],
        attempt_id=attempt_id,
        lease_token=claim["observation"]["lease_token"],
        delivery_task_id=f"room-observation:{claim['observation']['observation_id']}",
        provider_session_generation=attempt_id,
        now=NOW,
    )
    source = claim["activity"]
    context = {
        key: source.get(key)
        for key in (
            "activity_id",
            "seq",
            "activity_type",
            "actor_kind",
            "actor_identity",
            "actor_participant_id",
            "causation_id",
            "correlation_id",
            "causal_depth",
            "created_at",
        )
    } | {"payload_preview": "{}"}
    delivery = RoomObservationDelivery(
        conversation_id=conversation.id,
        participant=participant,
        observation=claim["observation"],
        source_activity=context,
        recent_activities=(context,),
        active_participants=(
            {
                "participant_id": participant.participant_id,
                "display_name": participant.display_name,
                "role": participant.role,
            },
        ),
        transport_request_id="room-observation:test",
        outcome_client_request_id="room-outcome:test",
        attempt_id=attempt_id,
    )
    record = GodSessionRecord(
        god_session_id="god-room-review",
        role=participant.role,
        agent_name=participant.display_name,
        runtime="codex",
        session_address="@room-review",
        session_inbox_id="inbox-room-review",
        conversation_id=conversation.id,
        participant_id=participant.participant_id,
        status="running",
        model=participant.model,
        feature_scope_id=ROOM_DELIVERY_SESSION_SCOPE,
        provider_session_id="thread-room-review",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
    )
    return path, conversation.id, participant, controls, delivery, record


def test_codex_delivery_persists_exact_reconcile_binding_without_projecting_it(tmp_path):
    path, _, _, controls, delivery, record = _bound_delivery(tmp_path)
    layer = _GodLayer(record)
    layer.messages = [
        StdoutMessage(
            type="result",
            request_id=delivery.transport_request_id,
            status="success",
        )
    ]
    result = asyncio.run(
        CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            control_store=controls,
        ).deliver(delivery, timeout_s=2)
    )

    assert result.status == "finished"
    with sqlite3.connect(path) as conn:
        binding = conn.execute(
            "select god_session_id, provider_session_id, provider_session_generation "
            "from room_observation_attempts where attempt_id = ?",
            (delivery.attempt_id,),
        ).fetchone()
    assert binding == (
        record.god_session_id,
        record.provider_session_id,
        delivery.attempt_id,
    )
    public = controls.projection(delivery.observation["observation_id"])
    assert record.god_session_id not in repr(public)
    assert record.provider_session_id not in repr(public)


def test_live_cancel_abort_failure_cannot_be_marked_cancelled_without_retry(tmp_path):
    async def run():
        _, _, _, controls, delivery, record = _bound_delivery(tmp_path)
        layer = _GodLayer(record)
        receiving = asyncio.Event()

        async def hang(_god_session_id):
            receiving.set()
            await asyncio.Event().wait()

        layer.receive_message = hang
        layer.abort_error = RuntimeError("abort failed")
        transport = CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            control_store=controls,
        )
        task = asyncio.create_task(transport.deliver(delivery, timeout_s=5))
        await asyncio.wait_for(receiving.wait(), timeout=1)
        controls.request_cancel(
            observation_id=delivery.observation["observation_id"],
            client_action_id="cancel-live-abort-failure",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        internal = controls.reconcile_state(delivery.observation["observation_id"])
        assert internal["reconcile_binding"]["provider_phase"] == "cleanup_pending"
        with pytest.raises(RoomControlError, match="room_provider_cleanup_unproven"):
            controls.mark_cancelled(
                observation_id=delivery.observation["observation_id"],
                attempt_id=delivery.attempt_id,
                expected_control_seq=internal["control_seq"],
                now=NOW + timedelta(seconds=2),
            )

        host = RoomParticipantHost(
            tmp_path / "chat.db",
            transport,
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=3),
            control_store=controls,
        )
        await host.reconcile_controls()
        assert (
            controls.projection(delivery.observation["observation_id"])["control_state"]
            == "cancel_pending"
        )

        layer.abort_error = None
        await host.reconcile_controls()
        assert (
            controls.projection(delivery.observation["observation_id"])["control_state"]
            == "cancelled"
        )

    asyncio.run(run())


def test_restart_aborts_exact_codex_binding_before_marking_cancelled(tmp_path):
    async def run():
        _, _, _, controls, delivery, record = _bound_delivery(tmp_path)
        controls.bind_provider_session(
            observation_id=delivery.observation["observation_id"],
            attempt_id=delivery.attempt_id,
            delivery_generation=delivery.attempt_id,
            god_session_id=record.god_session_id,
            provider_session_id=record.provider_session_id,
            now=NOW,
        )
        controls.request_cancel(
            observation_id=delivery.observation["observation_id"],
            client_action_id="cancel-before-restart",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        layer = _GodLayer(record)
        transport = CodexRoomObservationTransport(
            layer,
            worktree=tmp_path,
            control_store=controls,
        )
        restarted = RoomParticipantHost(
            tmp_path / "chat.db",
            transport,
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            control_store=controls,
        )

        await restarted.reconcile_controls()

        assert layer.abort_calls == [record.god_session_id]
        assert (
            controls.projection(delivery.observation["observation_id"])["control_state"]
            == "cancelled"
        )
        ensured = layer.ensure_calls[0]
        assert (
            ensured["conversation_id"],
            ensured["participant_id"],
            ensured["feature_scope_id"],
        ) == (
            delivery.conversation_id,
            delivery.participant.participant_id,
            ROOM_DELIVERY_SESSION_SCOPE,
        )

    asyncio.run(run())


def test_restart_fences_confirmed_dead_delivery_without_reviving_provider(tmp_path):
    async def run():
        _, _, _, controls, delivery, record = _bound_delivery(tmp_path)
        controls.bind_provider_session(
            observation_id=delivery.observation["observation_id"],
            attempt_id=delivery.attempt_id,
            delivery_generation=delivery.attempt_id,
            god_session_id=record.god_session_id,
            provider_session_id=record.provider_session_id,
            now=NOW,
        )
        controls.request_cancel(
            observation_id=delivery.observation["observation_id"],
            client_action_id="cancel-dead-provider",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        layer = _GodLayer(record)
        layer.provider_binding_process_state = lambda **_kwargs: "confirmed_dead"  # type: ignore[attr-defined]
        host = RoomParticipantHost(
            tmp_path / "chat.db",
            CodexRoomObservationTransport(
                layer,
                worktree=tmp_path,
                control_store=controls,
            ),
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            control_store=controls,
        )

        await host.reconcile_controls()

        assert layer.ensure_calls == []
        assert layer.abort_calls == []
        state = controls.reconcile_state(delivery.observation["observation_id"])
        assert state["control_state"] == "cancelled"
        assert state["reconcile_binding"]["provider_cleanup_reason"] == (
            "runner_reconciled_provider_process_dead"
        )

    asyncio.run(run())


def test_restart_ensure_started_without_binding_is_ensured_and_aborted(tmp_path):
    async def run():
        _, _, _, controls, delivery, record = _bound_delivery(tmp_path)
        controls.mark_provider_ensure_started(
            observation_id=delivery.observation["observation_id"],
            attempt_id=delivery.attempt_id,
            delivery_generation=delivery.attempt_id,
            now=NOW,
        )
        controls.request_cancel(
            observation_id=delivery.observation["observation_id"],
            client_action_id="cancel-in-ensure-window",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        starting = replace(
            record,
            status="starting",
            provider_session_id=None,
            provider_session_kind=None,
            provider_binding_status=None,
        )
        layer = _GodLayer(starting)
        layer.promote_on_ensure = True
        host = RoomParticipantHost(
            tmp_path / "chat.db",
            CodexRoomObservationTransport(
                layer,
                worktree=tmp_path,
                control_store=controls,
            ),
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            control_store=controls,
        )

        await host.reconcile_controls()

        assert len(layer.ensure_calls) == 1
        assert layer.binding_calls == []
        assert layer.abort_calls == [record.god_session_id]
        internal = controls.reconcile_state(delivery.observation["observation_id"])
        assert internal["control_state"] == "cancelled"
        assert internal["reconcile_binding"]["provider_cleanup_reason"] == (
            "runner_reconciled_provider_abort"
        )

    asyncio.run(run())


def test_failed_ensure_without_binding_cleanup_does_not_create_session(tmp_path):
    async def run():
        _, _, _, controls, delivery, record = _bound_delivery(tmp_path)
        controls.mark_provider_ensure_started(
            observation_id=delivery.observation["observation_id"],
            attempt_id=delivery.attempt_id,
            delivery_generation=delivery.attempt_id,
            now=NOW,
        )
        controls.finish_attempt(
            observation_id=delivery.observation["observation_id"],
            attempt_id=delivery.attempt_id,
            reason_code="room_codex_session_ensure_failed",
            base_attempt_limit=3,
            now=NOW + timedelta(seconds=1),
        )
        starting = replace(
            record,
            status="starting",
            provider_session_id=None,
            provider_session_kind=None,
            provider_binding_status=None,
        )
        layer = _GodLayer(starting)
        layer.promote_on_ensure = True
        host = RoomParticipantHost(
            tmp_path / "chat.db",
            CodexRoomObservationTransport(
                layer,
                worktree=tmp_path,
                control_store=controls,
            ),
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            control_store=controls,
        )

        await host.reconcile_controls()

        assert layer.ensure_calls == []
        assert layer.abort_calls == []
        binding = controls.reconcile_state(delivery.observation["observation_id"])[
            "reconcile_binding"
        ]
        assert binding["provider_phase"] == "cleanup_succeeded"
        assert binding["provider_cleanup_reason"] == ("room_provider_start_failed_before_binding")

    asyncio.run(run())


def test_restart_abort_failure_stays_pending_then_superseded_binding_settles(tmp_path):
    async def run():
        _, _, _, controls, delivery, record = _bound_delivery(tmp_path)
        controls.bind_provider_session(
            observation_id=delivery.observation["observation_id"],
            attempt_id=delivery.attempt_id,
            delivery_generation=delivery.attempt_id,
            god_session_id=record.god_session_id,
            provider_session_id=record.provider_session_id,
            now=NOW,
        )
        controls.request_cancel(
            observation_id=delivery.observation["observation_id"],
            client_action_id="cancel-before-failed-restart",
            operator_identity="operator:local",
            expected_state="active",
            expected_attempt_count=1,
            expected_control_seq=0,
            now=NOW + timedelta(seconds=1),
        )
        layer = _GodLayer(record)
        layer.abort_error = RuntimeError("abort failed")
        host = RoomParticipantHost(
            tmp_path / "chat.db",
            CodexRoomObservationTransport(
                layer,
                worktree=tmp_path,
                control_store=controls,
            ),
            policy=RoomHostPolicy(
                delivery_timeout_s=2,
                cleanup_grace_s=0.2,
                lease_ttl_s=3,
            ),
            clock=lambda: NOW + timedelta(seconds=2),
            control_store=controls,
        )

        await host.reconcile_controls()
        assert (
            controls.projection(delivery.observation["observation_id"])["control_state"]
            == "cancel_pending"
        )
        failed_abort_count = len(layer.abort_calls)

        layer.abort_error = None
        layer.record = replace(record, provider_session_id="thread-new-generation")
        await host.reconcile_controls()
        assert len(layer.abort_calls) == failed_abort_count + 1
        assert (
            controls.projection(delivery.observation["observation_id"])["control_state"]
            == "cancelled"
        )
        assert (
            controls.reconcile_state(delivery.observation["observation_id"])["reconcile_binding"][
                "provider_cleanup_reason"
            ]
            == "room_codex_cancel_binding_superseded_and_fenced"
        )

    asyncio.run(run())
