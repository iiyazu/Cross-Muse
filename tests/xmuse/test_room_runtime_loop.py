from __future__ import annotations

import asyncio
from collections import Counter
from types import SimpleNamespace

from xmuse_core.chat.room_runtime import run_room_participant_host_loop


class _ConcurrentRoomHost:
    def __init__(self) -> None:
        self._claimable = {"slow", "fast", "waiting"}
        self.calls: Counter[str] = Counter()
        self.active_by_room: Counter[str] = Counter()
        self.active_total = 0
        self.max_active_total = 0
        self.max_active_by_room: Counter[str] = Counter()
        self.slow_started = asyncio.Event()
        self.waiting_started = asyncio.Event()

    def list_claimable_conversation_ids(self) -> list[str]:
        return [
            conversation_id
            for conversation_id in ("slow", "fast", "waiting")
            if conversation_id in self._claimable
        ]

    async def pump_once(self, *, conversation_id: str):
        self.calls[conversation_id] += 1
        self.active_by_room[conversation_id] += 1
        self.active_total += 1
        self.max_active_total = max(self.max_active_total, self.active_total)
        self.max_active_by_room[conversation_id] = max(
            self.max_active_by_room[conversation_id],
            self.active_by_room[conversation_id],
        )
        try:
            if conversation_id == "slow":
                # Keep advertising this room while it is active. The runtime must
                # not start a second pump for the same conversation.
                self.slow_started.set()
                await asyncio.Event().wait()
            self._claimable.discard(conversation_id)
            if conversation_id == "waiting":
                self.waiting_started.set()
            await asyncio.sleep(0)
            return SimpleNamespace(deliveries=())
        finally:
            self.active_by_room[conversation_id] -= 1
            self.active_total -= 1


def test_room_loop_is_bounded_fair_and_single_pump_per_conversation() -> None:
    async def scenario() -> None:
        host = _ConcurrentRoomHost()
        stop = asyncio.Event()
        loop_task = asyncio.create_task(
            run_room_participant_host_loop(
                host,
                stop=stop,
                max_concurrent_rooms=2,
                idle_wait_s=0.01,
            )
        )

        await asyncio.wait_for(host.slow_started.wait(), timeout=1)
        await asyncio.wait_for(host.waiting_started.wait(), timeout=1)

        assert host.active_by_room["slow"] == 1
        assert host.calls["slow"] == 1
        assert host.max_active_total == 2
        assert max(host.max_active_by_room.values()) == 1

        stop.set()
        await asyncio.wait_for(loop_task, timeout=1)
        assert host.active_total == 0

    asyncio.run(scenario())


def test_room_loop_rejects_unbounded_or_busy_poll_configuration() -> None:
    class _IdleHost:
        def list_claimable_conversation_ids(self) -> list[str]:
            return []

    async def invalid_concurrency() -> None:
        await run_room_participant_host_loop(
            _IdleHost(),
            stop=asyncio.Event(),
            max_concurrent_rooms=0,
        )

    async def invalid_wait() -> None:
        await run_room_participant_host_loop(
            _IdleHost(),
            stop=asyncio.Event(),
            max_concurrent_rooms=1,
            idle_wait_s=0,
        )

    for coroutine, code in (
        (invalid_concurrency(), "room_host_max_concurrent_rooms_invalid"),
        (invalid_wait(), "room_host_idle_wait_invalid"),
    ):
        try:
            asyncio.run(coroutine)
        except ValueError as exc:
            assert str(exc) == code
        else:
            raise AssertionError(f"expected {code}")


def test_room_loop_never_pumps_when_durable_scan_has_no_claimable_room() -> None:
    async def scenario() -> None:
        stop = asyncio.Event()

        class _NoClaimableHost:
            def __init__(self) -> None:
                self.scanned = asyncio.Event()
                self.pump_calls = 0

            def list_claimable_conversation_ids(self) -> list[str]:
                self.scanned.set()
                return []

            async def pump_once(self, *, conversation_id: str):
                self.pump_calls += 1
                raise AssertionError(f"unexpected pump for {conversation_id}")

        host = _NoClaimableHost()
        loop_task = asyncio.create_task(
            run_room_participant_host_loop(
                host,
                stop=stop,
                max_concurrent_rooms=2,
                idle_wait_s=0.01,
            )
        )
        await asyncio.wait_for(host.scanned.wait(), timeout=1)
        stop.set()
        await asyncio.wait_for(loop_task, timeout=1)
        assert host.pump_calls == 0

    asyncio.run(scenario())
