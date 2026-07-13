from __future__ import annotations

import asyncio
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_controls import RoomControlError, RoomObservationControlStore
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomHostPolicy,
    RoomParticipantHost,
    RoomTransportResult,
)
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_runtime import run_room_participant_host_loop
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog

NOW = datetime(2026, 7, 11, tzinfo=UTC)


def _room(tmp_path: Path) -> tuple[Path, str, object]:
    db_path = tmp_path / "chat.db"
    conversation_id = RoomTestStore(db_path).create_conversation("dead-attempt").id
    participant = ParticipantStore(db_path).add(
        conversation_id=conversation_id,
        role="reviewer",
        display_name="Reviewer",
        cli_kind="codex",
        model="gpt-5",
    )
    RoomKernelStore(db_path).post_human_activity(
        conversation_id=conversation_id,
        human_id="human",
        content="recover this turn",
        client_request_id="dead-attempt-root",
    )
    return db_path, conversation_id, participant


def _policy() -> RoomHostPolicy:
    return RoomHostPolicy(
        delivery_timeout_s=1,
        cleanup_grace_s=1,
        lease_ttl_s=3,
        participant_cooldown_s=0,
        max_attempts_per_observation=3,
        max_batch_size=1,
    )


class _FinishedTransport:
    async def deliver(self, delivery, *, timeout_s):
        return RoomTransportResult("failed", "test_transport_failed")


def test_runner_identity_is_paired_and_claim_is_boot_bound(tmp_path: Path) -> None:
    db_path, conversation_id, _participant = _room(tmp_path)
    with pytest.raises(ValueError, match="room_runner_identity_pair_required"):
        RoomParticipantHost(
            db_path,
            _FinishedTransport(),
            runner_generation="generation-new",
        )

    host = RoomParticipantHost(
        db_path,
        _FinishedTransport(),
        policy=_policy(),
        clock=lambda: NOW,
        runner_generation="generation-new",
        runner_boot_id="boot-new",
    )
    result = asyncio.run(host.pump_once(conversation_id=conversation_id))
    assert len(result.deliveries) == 1
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "select runner_generation, runner_boot_id "
            "from room_observation_attempts order by attempt_number"
        ).fetchall() == [("generation-new", "boot-new")]


class _RecoveryTransport:
    def __init__(self) -> None:
        self.result = RoomCancelReconcileResult("pending", "provider_abort_pending")
        self.calls: list[dict[str, object]] = []

    async def deliver(self, delivery, *, timeout_s):
        raise AssertionError("startup recovery must finish before redelivery")

    async def reconcile_cancel(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


def _bound_prior_attempt(
    db_path: Path,
    conversation_id: str,
    participant: object,
) -> str:
    kernel = RoomKernelStore(db_path)
    claimed = kernel.claim_next_observation(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner="dead-runner",
        lease_ttl_s=240,
        base_attempt_limit=3,
        runner_generation="generation-old",
        runner_boot_id="boot-old",
        now=NOW,
    )
    assert claimed is not None
    observation = claimed["observation"]
    attempt = claimed["attempt"]
    decisions = RoomAttemptSkillDecisionStore(db_path)
    decisions.bind_for_attempt(
        attempt_id=attempt["attempt_id"],
        catalog=SkillCatalog.load_bundled(),
        now=NOW,
    )
    controls = RoomObservationControlStore(db_path)
    controls.bind_delivery(
        observation_id=observation["observation_id"],
        attempt_id=attempt["attempt_id"],
        lease_token=observation["lease_token"],
        delivery_task_id="dead-delivery",
        provider_session_generation=attempt["attempt_id"],
        now=NOW,
    )
    controls.mark_provider_ensure_started(
        observation_id=observation["observation_id"],
        attempt_id=attempt["attempt_id"],
        delivery_generation=attempt["attempt_id"],
        now=NOW,
    )
    controls.bind_provider_session(
        observation_id=observation["observation_id"],
        attempt_id=attempt["attempt_id"],
        delivery_generation=attempt["attempt_id"],
        god_session_id="god-old",
        provider_session_id="provider-old",
        now=NOW,
    )
    return observation["observation_id"]


def test_startup_fence_waits_for_exact_cleanup_then_finalizes(tmp_path: Path) -> None:
    db_path, conversation_id, participant = _room(tmp_path)
    observation_id = _bound_prior_attempt(db_path, conversation_id, participant)
    transport = _RecoveryTransport()
    controls = RoomObservationControlStore(db_path)
    host = RoomParticipantHost(
        db_path,
        transport,
        policy=_policy(),
        clock=lambda: NOW,
        control_store=controls,
        runner_generation="generation-new",
        runner_boot_id="boot-new",
    )

    fenced = host.fence_prior_runner_attempts()
    assert fenced is not None
    assert controls.list_pending_runner_recoveries()
    asyncio.run(host.reconcile_runner_recoveries())
    assert len(transport.calls) == 1
    assert controls.list_pending_runner_recoveries()
    assert (
        RoomKernelStore(db_path).list_claimable_conversation_ids(
            max_attempts_per_observation=3,
            now=NOW,
        )
        == []
    )

    transport.result = RoomCancelReconcileResult("settled", "provider_abort_succeeded")
    asyncio.run(host.reconcile_runner_recoveries())
    assert len(transport.calls) == 2
    assert controls.list_pending_runner_recoveries() == []
    assert RoomKernelStore(db_path).list_claimable_conversation_ids(
        max_attempts_per_observation=3,
        now=NOW,
    ) == [conversation_id]
    observation = RoomKernelStore(db_path).get_observation(observation_id)
    assert observation["status"] == "pending"
    assert observation["control_state"] == "active"


def test_cancel_owned_recovery_is_never_auto_reopened(tmp_path: Path) -> None:
    class _CancelControls:
        def __init__(self) -> None:
            self.finalize_calls = 0

        def list_pending_runner_recoveries(self):
            return [
                {
                    "conversation_id": "room-cancel",
                    "participant_id": "participant-cancel",
                    "observation_id": "observation-cancel",
                    "control_state": "cancel_pending",
                    "reconcile_binding": {
                        "attempt_id": "attempt-cancel",
                        "provider_phase": "cleanup_succeeded",
                    },
                }
            ]

        def finalize_runner_recovery(self, **_kwargs):
            self.finalize_calls += 1
            raise AssertionError("cancel recovery must remain owned by cancel reconciliation")

    controls = _CancelControls()
    transport = _RecoveryTransport()
    host = RoomParticipantHost(
        tmp_path / "chat.db",
        transport,
        policy=_policy(),
        control_store=controls,
        runner_generation="generation-new",
        runner_boot_id="boot-new",
    )
    asyncio.run(host.reconcile_runner_recoveries())
    assert transport.calls == []
    assert controls.finalize_calls == 0


def test_runner_recovery_does_not_hide_unexpected_finalize_errors(tmp_path: Path) -> None:
    class _BrokenControls:
        def list_pending_runner_recoveries(self):
            return [
                {
                    "conversation_id": "room-broken",
                    "participant_id": "participant-broken",
                    "observation_id": "observation-broken",
                    "control_state": "active",
                    "reconcile_binding": {
                        "attempt_id": "attempt-broken",
                        "provider_phase": "cleanup_succeeded",
                    },
                }
            ]

        def finalize_runner_recovery(self, **_kwargs):
            raise RoomControlError("room_runner_recovery_not_pending")

    host = RoomParticipantHost(
        tmp_path / "chat.db",
        _RecoveryTransport(),
        policy=_policy(),
        control_store=_BrokenControls(),
        runner_generation="generation-new",
        runner_boot_id="boot-new",
    )
    with pytest.raises(RoomControlError, match="room_runner_recovery_not_pending"):
        asyncio.run(host.reconcile_runner_recoveries())


def test_room_loop_reconciles_controls_then_runner_recovery_before_claim() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()
        started = asyncio.Event()
        calls: list[str] = []

        class _Host:
            async def reconcile_controls(self) -> None:
                calls.append("controls")

            async def reconcile_runner_recoveries(self) -> None:
                calls.append("recoveries")

            def list_claimable_conversation_ids(self) -> list[str]:
                calls.append("claim")
                stop.set()
                return []

        await run_room_participant_host_loop(
            _Host(),
            stop=stop,
            max_concurrent_rooms=1,
            idle_wait_s=0.01,
            started=started,
        )
        assert started.is_set()
        assert calls == ["controls", "recoveries", "claim"]

    asyncio.run(scenario())
