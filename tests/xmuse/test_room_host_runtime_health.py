from __future__ import annotations

import asyncio
from pathlib import Path

from xmuse_core.chat.room_host import RoomParticipantHost, RoomTransportResult


class _UnusedTransport:
    async def deliver(self, delivery, *, timeout_s):
        del delivery, timeout_s
        return RoomTransportResult("failed", "unused")


def test_host_runtime_health_counts_active_delivery_without_degrading(
    tmp_path: Path,
) -> None:
    host = RoomParticipantHost(tmp_path / "chat.db", _UnusedTransport())

    assert host.runtime_health_snapshot() == {
        "state": "healthy",
        "code": "ready",
        "active_delivery_count": 0,
        "retained_cleanup_count": 0,
    }

    host._active_deliveries["observation-1"] = object()  # type: ignore[assignment]
    assert host.runtime_health_snapshot() == {
        "state": "healthy",
        "code": "ready",
        "active_delivery_count": 1,
        "retained_cleanup_count": 0,
    }


def test_host_runtime_health_prioritizes_skill_blocker_over_retained_cleanup(
    tmp_path: Path,
) -> None:
    async def scenario() -> None:
        host = RoomParticipantHost(tmp_path / "chat.db", _UnusedTransport())
        retained = asyncio.create_task(asyncio.Event().wait())
        host._retained_tasks.add(retained)  # type: ignore[arg-type]
        try:
            assert host.runtime_health_snapshot() == {
                "state": "attention",
                "code": "room_transport_cleanup_pending",
                "active_delivery_count": 0,
                "retained_cleanup_count": 1,
            }

            host._skill_runtime_unhealthy_reason = "room_skill_catalog_drift"
            assert host.runtime_health_snapshot() == {
                "state": "blocked",
                "code": "room_skill_catalog_drift",
                "active_delivery_count": 0,
                "retained_cleanup_count": 1,
            }
        finally:
            retained.cancel()
            await asyncio.gather(retained, return_exceptions=True)

    asyncio.run(scenario())


def test_host_runtime_health_normalizes_unsafe_internal_reason(tmp_path: Path) -> None:
    host = RoomParticipantHost(tmp_path / "chat.db", _UnusedTransport())
    host._skill_runtime_unhealthy_reason = "provider output: secret"

    assert host.runtime_health_snapshot() == {
        "state": "blocked",
        "code": "room_host_skill_runtime_unhealthy",
        "active_delivery_count": 0,
        "retained_cleanup_count": 0,
    }
