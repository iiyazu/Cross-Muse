from __future__ import annotations

from pathlib import Path

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat.participant_store import Participant, ParticipantStore
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomObservationDelivery,
    RoomTransportResult,
)
from xmuse_core.chat.room_transport_router import RoutingRoomObservationTransport


class _RecordingTransport:
    def __init__(self, result: RoomTransportResult | None = None) -> None:
        self.result = result or RoomTransportResult("finished")
        self.deliveries: list[RoomObservationDelivery] = []
        self.timeouts: list[float] = []

    async def deliver(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> RoomTransportResult:
        self.deliveries.append(delivery)
        self.timeouts.append(timeout_s)
        return self.result


class _HookedTransport(_RecordingTransport):
    def __init__(self, *, reset_result: bool = False) -> None:
        super().__init__()
        self.reset_result = reset_result
        self.reconcile_calls: list[dict[str, object]] = []
        self.reset_calls: list[tuple[RoomObservationDelivery, float]] = []

    async def reconcile_cancel(self, **kwargs) -> RoomCancelReconcileResult:
        self.reconcile_calls.append(kwargs)
        return RoomCancelReconcileResult("settled", "route_reconciled")

    async def reset_after_missing_outcome(
        self, delivery: RoomObservationDelivery, *, timeout_s: float
    ) -> bool:
        self.reset_calls.append((delivery, timeout_s))
        return self.reset_result


def _participant(tmp_path: Path, cli_kind: str) -> Participant:
    path = tmp_path / f"chat-{cli_kind}.db"
    conversation = RoomTestStore(path).create_conversation(f"{cli_kind} room")
    return ParticipantStore(path).add(
        conversation_id=conversation.id,
        role="review",
        display_name="Reviewer",
        cli_kind=cli_kind,  # type: ignore[arg-type]
        model="claude-sonnet" if cli_kind == "claude" else "gpt-5",
    )


def _delivery(participant: Participant) -> RoomObservationDelivery:
    return RoomObservationDelivery(
        conversation_id=participant.conversation_id,
        participant=participant,
        observation={"observation_id": "observation-1"},
        source_activity={"activity_id": "activity-1"},
        recent_activities=(),
        active_participants=(),
        transport_request_id="room-observation:request-1",
        outcome_client_request_id="room-outcome:request-1",
    )


async def test_deliver_routes_to_the_transport_of_the_participant_kind(tmp_path: Path) -> None:
    codex = _RecordingTransport(RoomTransportResult("finished", diagnostic_text="codex"))
    claude = _RecordingTransport(RoomTransportResult("finished", diagnostic_text="claude"))
    router = RoutingRoomObservationTransport({"codex": codex, "claude": claude})

    codex_delivery = _delivery(_participant(tmp_path, "codex"))
    claude_delivery = _delivery(_participant(tmp_path, "claude"))
    result = await router.deliver(claude_delivery, timeout_s=7.5)
    await router.deliver(codex_delivery, timeout_s=2.0)

    assert result == RoomTransportResult("finished", diagnostic_text="claude")
    assert codex.deliveries == [codex_delivery] and codex.timeouts == [2.0]
    assert claude.deliveries == [claude_delivery] and claude.timeouts == [7.5]


async def test_deliver_fails_closed_when_no_route_exists(tmp_path: Path) -> None:
    participant = _participant(tmp_path, "antigravity")
    delivery = _delivery(participant)

    for routes in ({}, {"codex": _RecordingTransport(), "claude": _RecordingTransport()}):
        result = await RoutingRoomObservationTransport(routes).deliver(delivery, timeout_s=1.0)
        assert result == RoomTransportResult("failed", "room_transport_unavailable")


async def test_reconcile_cancel_is_forwarded_to_the_participant_route(tmp_path: Path) -> None:
    codex = _HookedTransport()
    claude = _HookedTransport()
    router = RoutingRoomObservationTransport({"codex": codex, "claude": claude})
    participant = _participant(tmp_path, "claude")
    attempt = {"attempt_id": "attempt-1", "provider_phase": "bound"}

    result = await router.reconcile_cancel(
        conversation_id=participant.conversation_id,
        participant=participant,
        attempt=attempt,
        timeout_s=3.0,
    )

    assert result == RoomCancelReconcileResult("settled", "route_reconciled")
    assert codex.reconcile_calls == []
    assert claude.reconcile_calls == [
        {
            "conversation_id": participant.conversation_id,
            "participant": participant,
            "attempt": attempt,
            "timeout_s": 3.0,
        }
    ]


async def test_reconcile_cancel_without_route_or_hook_stays_pending(tmp_path: Path) -> None:
    participant = _participant(tmp_path, "claude")
    plain = _RecordingTransport()
    router = RoutingRoomObservationTransport({"codex": plain})
    missing = RoutingRoomObservationTransport({})

    for candidate in (router, missing):
        result = await candidate.reconcile_cancel(
            conversation_id=participant.conversation_id,
            participant=participant,
            attempt={"attempt_id": "attempt-1"},
            timeout_s=1.0,
        )
        assert result == RoomCancelReconcileResult("pending", "room_cancel_reconcile_unavailable")


async def test_reset_after_missing_outcome_is_forwarded_with_unsupported_default(
    tmp_path: Path,
) -> None:
    participant = _participant(tmp_path, "claude")
    delivery = _delivery(participant)
    resetting = _HookedTransport(reset_result=False)
    refusing = _HookedTransport(reset_result=True)
    plain = _RecordingTransport()
    router = RoutingRoomObservationTransport({"codex": plain, "claude": resetting})
    missing = RoutingRoomObservationTransport({"codex": refusing})

    assert await router.reset_after_missing_outcome(delivery, timeout_s=2.0) is False
    assert resetting.reset_calls == [(delivery, 2.0)]
    # A route without the hook keeps the host's reopen decision unchanged, and
    # an absent route must not raise out of the optional hook.
    assert await missing.reset_after_missing_outcome(delivery, timeout_s=2.0) is True
    empty = RoutingRoomObservationTransport({})
    assert await empty.reset_after_missing_outcome(delivery, timeout_s=2.0) is True
