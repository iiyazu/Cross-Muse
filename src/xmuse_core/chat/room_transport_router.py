"""Route each Room delivery to the transport of its participant's provider."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from xmuse_core.chat.participant_store import Participant
from xmuse_core.chat.room_host import (
    RoomCancelReconcileResult,
    RoomObservationDelivery,
    RoomObservationTransport,
    RoomTransportResult,
)


class RoutingRoomObservationTransport:
    """Dispatch to the transport registered for the participant's cli_kind.

    Unknown kinds fail closed instead of borrowing another provider's session
    semantics; a provider task must register its transport explicitly.
    """

    def __init__(self, routes: Mapping[str, RoomObservationTransport]) -> None:
        self._routes = dict(routes)

    async def deliver(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> RoomTransportResult:
        route = self._routes.get(delivery.participant.cli_kind)
        if route is None:
            return RoomTransportResult("failed", "room_transport_unavailable")
        return await route.deliver(delivery, timeout_s=timeout_s)

    async def reconcile_cancel(
        self,
        *,
        conversation_id: str,
        participant: Participant,
        attempt: dict[str, Any],
        timeout_s: float,
    ) -> RoomCancelReconcileResult:
        """Forward cancel reconciliation, staying pending when unsupported."""

        route = self._routes.get(participant.cli_kind)
        hook = getattr(route, "reconcile_cancel", None)
        if not callable(hook):
            return RoomCancelReconcileResult("pending", "room_cancel_reconcile_unavailable")
        return await hook(
            conversation_id=conversation_id,
            participant=participant,
            attempt=attempt,
            timeout_s=timeout_s,
        )

    async def reset_after_missing_outcome(
        self,
        delivery: RoomObservationDelivery,
        *,
        timeout_s: float,
    ) -> bool:
        """Forward thread rotation, keeping the host's retry decision when unsupported."""

        route = self._routes.get(delivery.participant.cli_kind)
        hook = getattr(route, "reset_after_missing_outcome", None)
        if not callable(hook):
            # The host only calls this hook when it would already reopen the
            # observation immediately; an unsupported route must not change that.
            return True
        return bool(await hook(delivery, timeout_s=timeout_s))
