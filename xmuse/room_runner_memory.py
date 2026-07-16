"""Optional MemoryOS composition for the isolated Room Runner.

This is the only Room Runner module that knows the MemoryOS HTTP adapter,
environment configuration, and concrete memory stores.  The process entrypoint
receives one runtime capability and a boolean lifecycle flag.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal, cast

from xmuse.memoryos_adapter import (
    ArchiveOnlyRoomMemoryRuntime,
    DisabledRoomMemoryRuntime,
    MemoryOSArchiveAdapter,
)
from xmuse_core.chat.room_memory_delivery_store import RoomMemoryDeliveryStore
from xmuse_core.chat.room_memory_recall_store import RoomMemoryRecallStore
from xmuse_core.chat.room_memory_runtime import RoomMemoryRuntime


def compose_room_runner_memory(
    db_path: Path,
    *,
    worker_id: str,
    environ: Mapping[str, str] | None = None,
) -> tuple[RoomMemoryRuntime, bool]:
    """Build optional derived memory without making it a Runner prerequisite."""

    delivery_store = RoomMemoryDeliveryStore(db_path)
    recall_store = RoomMemoryRecallStore(db_path)
    values = os.environ if environ is None else environ
    url = values.get("XMUSE_MEMORYOS_URL")
    api_key = values.get("XMUSE_MEMORYOS_API_KEY")
    profile = values.get("XMUSE_MEMORYOS_PROFILE", "archive-only")
    if url and api_key:
        try:
            return (
                ArchiveOnlyRoomMemoryRuntime(
                    delivery_store,
                    recall_store,
                    MemoryOSArchiveAdapter(
                        base_url=url,
                        api_key=api_key,
                        profile=cast(Literal["archive-only", "full-local"], profile),
                    ),
                    worker_id=worker_id,
                ),
                True,
            )
        except Exception:
            # Memory is derived and optional. Invalid sidecar configuration must
            # not prevent the isolated Room Host from starting.
            return DisabledRoomMemoryRuntime(recall_store), False
    return DisabledRoomMemoryRuntime(recall_store), False


async def run_room_memory_pump(
    runtime: RoomMemoryRuntime,
    *,
    report_attention: Callable[[str | None], None],
    stop: asyncio.Event,
) -> None:
    """Drive the optional outbox while reporting only bounded Host attention."""

    backoff_s = 1.0
    while not stop.is_set():
        try:
            progressed = await runtime.pump_once()
            report_attention(None)
            backoff_s = 1.0
            delay = 0.05 if progressed else 1.0
        except asyncio.CancelledError:
            raise
        except Exception:
            report_attention("room_memory_degraded")
            delay = backoff_s
            backoff_s = min(backoff_s * 2.0, 30.0)
        try:
            await asyncio.wait_for(stop.wait(), timeout=delay)
        except TimeoutError:
            pass
