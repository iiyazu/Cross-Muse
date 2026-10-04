from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_application import RoomApplicationService
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_host import (
    LongTurnPolicy,
    RoomHostPolicy,
    RoomObservationDelivery,
    RoomParticipantHost,
    RoomTransportResult,
    RoomTurnProgress,
)
from xmuse_core.chat.room_kernel import RoomKernelStore

Behavior = Callable[[RoomObservationDelivery], Awaitable[RoomTransportResult]]


def _room(tmp_path: Path):
    db, registry = tmp_path / "chat.db", tmp_path / "god_sessions.json"
    conversation = RoomTestStore(db).create_conversation("room")
    participant = ParticipantStore(db).add(
        conversation_id=conversation.id,
        role="owner",
        display_name="P",
        cli_kind="codex",
        model="gpt-5",
    )
    session = GodSessionRegistry(registry).create(
        participant.role,
        participant.display_name,
        "codex",
        "addr-1",
        "inbox-1",
        conversation.id,
        participant.participant_id,
    )
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="h",
        content="work long",
        client_request_id="h1",
    )
    return db, registry, conversation.id, participant, session


class _FakeTransport:
    """Fake provider transport driven by a per-test async behavior."""

    def __init__(self, behavior: Behavior) -> None:
        self._behavior = behavior
        self.deliveries: list[RoomObservationDelivery] = []
        self.seen_timeout_s: float | None = None
        self.cancelled = False

    async def deliver(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> RoomTransportResult:
        self.deliveries.append(delivery)
        self.seen_timeout_s = timeout_s
        try:
            return await self._behavior(delivery)
        except asyncio.CancelledError:
            self.cancelled = True
            raise


def _policy() -> RoomHostPolicy:
    return RoomHostPolicy(
        delivery_timeout_s=0.2,
        cleanup_grace_s=0.05,
        lease_ttl_s=0.3,
        participant_cooldown_s=0,
    )


def _long_turn(**overrides) -> LongTurnPolicy:
    values: dict = {
        "renew_interval_s": 0.05,
        "lease_chunk_s": 0.5,
        "stall_timeout_s": 0.4,
        "max_turn_s": 5.0,
        "loop_repeat_limit": 8,
    }
    values.update(overrides)
    return LongTurnPolicy(**values)


def _host(
    db: Path,
    transport: _FakeTransport,
    *,
    policy: RoomHostPolicy | None = None,
    long_turn: LongTurnPolicy | None = None,
    selected: bool = True,
    **kwargs,
) -> RoomParticipantHost:
    selector = None if long_turn is None else (lambda _p: selected)
    return RoomParticipantHost(
        db,
        transport,
        policy=policy or _policy(),
        long_turn_policy=long_turn,
        long_turn_selector=selector,
        **kwargs,
    )


def _submit_noop(
    db: Path, registry: Path, delivery: RoomObservationDelivery, god_session_id: str
) -> None:
    RoomApplicationService(db, registry).submit_participant_outcome(
        conversation_id=delivery.conversation_id,
        participant_id=delivery.participant.participant_id,
        god_session_id=god_session_id,
        observation_id=delivery.observation["observation_id"],
        lease_token=delivery.observation["lease_token"],
        client_request_id=delivery.outcome_client_request_id,
        outcome_type="noop",
        outcome_payload={},
    )


def test_long_turn_outlives_fixed_lease_and_late_outcome_commits(tmp_path: Path) -> None:
    db, registry, cid, participant, session = _room(tmp_path)

    async def behavior(delivery: RoomObservationDelivery) -> RoomTransportResult:
        assert delivery.progress is not None
        for _ in range(12):
            delivery.progress(RoomTurnProgress(kind="message"))
            await asyncio.sleep(0.08)
        _submit_noop(db, registry, delivery, session.god_session_id)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    host = _host(db, transport, long_turn=_long_turn())
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    outcome = result.deliveries[0]
    assert outcome.state == "completed"
    assert transport.seen_timeout_s == 5.0
    # The ~1s turn lasted several times the 0.3s fixed lease; completion
    # proves the lease was renewed and the late outcome passed the check.


def test_long_turn_without_progress_is_stalled_and_permit_released(
    tmp_path: Path,
) -> None:
    db, _registry, cid, _participant, _session = _room(tmp_path)

    async def behavior(_delivery: RoomObservationDelivery) -> RoomTransportResult:
        await asyncio.sleep(5.0)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    policy = _policy()
    host = _host(db, transport, long_turn=_long_turn(stall_timeout_s=0.15))
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    outcome = result.deliveries[0]
    assert outcome.state == "failed"
    assert outcome.reason == "room_turn_stalled"
    assert transport.cancelled
    assert not host._retained_tasks
    assert host._delivery_slots._value == policy.max_batch_size


def test_long_turn_repeated_tool_call_is_looping(tmp_path: Path) -> None:
    db, _registry, cid, _participant, _session = _room(tmp_path)

    async def behavior(delivery: RoomObservationDelivery) -> RoomTransportResult:
        assert delivery.progress is not None
        for _ in range(6):
            delivery.progress(RoomTurnProgress(kind="tool_call", fingerprint="fp-same"))
        await asyncio.sleep(5.0)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    host = _host(db, transport, long_turn=_long_turn(loop_repeat_limit=3))
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    assert result.deliveries[0].reason == "room_turn_looping"
    assert transport.cancelled


def test_long_turn_interleaved_tool_calls_do_not_trip_loop(tmp_path: Path) -> None:
    db, registry, cid, _participant, session = _room(tmp_path)

    async def behavior(delivery: RoomObservationDelivery) -> RoomTransportResult:
        assert delivery.progress is not None
        for index in range(10):
            delivery.progress(RoomTurnProgress(kind="message"))
            delivery.progress(
                RoomTurnProgress(
                    kind="tool_call",
                    fingerprint=f"fp-{index % 2}",
                )
            )
        _submit_noop(db, registry, delivery, session.god_session_id)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    host = _host(db, transport, long_turn=_long_turn(loop_repeat_limit=3))
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    assert result.deliveries[0].state == "completed"


def test_long_turn_wrap_up_after_own_outcome_is_not_cancelled(tmp_path: Path) -> None:
    db, registry, cid, _participant, session = _room(tmp_path)

    async def behavior(delivery: RoomObservationDelivery) -> RoomTransportResult:
        _submit_noop(db, registry, delivery, session.god_session_id)
        # The provider keeps wrapping up across several renewal slices; the
        # committed outcome makes renewal fail, which must not cancel the
        # turn (cancelling rotates the participant's provider session).
        await asyncio.sleep(0.3)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    host = _host(db, transport, long_turn=_long_turn(post_outcome_grace_s=2.0))
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    assert result.deliveries[0].state == "completed"
    assert not transport.cancelled


def test_long_turn_wrap_up_past_grace_is_cancelled_but_completed(tmp_path: Path) -> None:
    db, registry, cid, _participant, session = _room(tmp_path)

    async def behavior(delivery: RoomObservationDelivery) -> RoomTransportResult:
        _submit_noop(db, registry, delivery, session.god_session_id)
        await asyncio.sleep(5.0)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    host = _host(db, transport, long_turn=_long_turn(post_outcome_grace_s=0.1))
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    assert result.deliveries[0].state == "completed"
    assert transport.cancelled


def test_long_turn_superseded_attempt_ends_lease_lost(tmp_path: Path) -> None:
    db, _registry, cid, _participant, _session = _room(tmp_path)
    controls = RoomObservationControlStore(db)

    async def behavior(delivery: RoomObservationDelivery) -> RoomTransportResult:
        assert delivery.progress is not None
        for _ in range(3):
            delivery.progress(RoomTurnProgress(kind="message"))
            await asyncio.sleep(0.05)
        # A new runner boot fences the attempt mid-turn: fresh token, cleared
        # lease, attempt no longer live.
        controls.fence_prior_runner_attempts(
            current_runner_generation="gen-1",
            current_runner_boot_id="boot-B",
            base_attempt_limit=3,
        )
        await asyncio.sleep(5.0)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    host = _host(
        db,
        transport,
        long_turn=_long_turn(),
        runner_generation="gen-1",
        runner_boot_id="boot-A",
    )
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    outcome = result.deliveries[0]
    assert outcome.state == "lease_lost"
    assert outcome.reason == "lease_lost"
    assert transport.cancelled


def test_unselected_participant_keeps_fixed_delivery_timeout(tmp_path: Path) -> None:
    db, _registry, cid, _participant, _session = _room(tmp_path)

    async def behavior(delivery: RoomObservationDelivery) -> RoomTransportResult:
        assert delivery.progress is None
        await asyncio.sleep(5.0)
        return RoomTransportResult("finished")

    transport = _FakeTransport(behavior)
    host = _host(db, transport, long_turn=_long_turn(), selected=False)
    result = asyncio.run(host.pump_once(conversation_id=cid))

    assert len(result.deliveries) == 1
    assert result.deliveries[0].reason == "delivery_timeout"
    assert transport.seen_timeout_s == 0.2
    assert transport.cancelled


def test_long_turn_policy_validation() -> None:
    import pytest

    with pytest.raises(ValueError, match="stall_timeout_s_too_short"):
        LongTurnPolicy(renew_interval_s=60.0, stall_timeout_s=30.0)
    with pytest.raises(ValueError, match="room_long_turn_policy_pair_required"):
        RoomParticipantHost(
            Path("/nonexistent.db"),
            _FakeTransport(lambda _d: asyncio.sleep(0, result=RoomTransportResult("finished"))),  # type: ignore[arg-type]
            long_turn_policy=_long_turn(),
        )
    with pytest.raises(ValueError, match="room_long_turn_lease_chunk_too_short"):
        RoomParticipantHost(
            Path("/nonexistent.db"),
            _FakeTransport(lambda _d: asyncio.sleep(0, result=RoomTransportResult("finished"))),  # type: ignore[arg-type]
            long_turn_policy=_long_turn(lease_chunk_s=0.05),
            long_turn_selector=lambda _p: True,
        )
