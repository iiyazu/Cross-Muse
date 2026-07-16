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

from xmuse.memoryos_delivery_pump import MemoryOSDeliveryPump
from xmuse.memoryos_evidence import MemoryOSEvidenceDecoder
from xmuse.memoryos_http_client import MemoryOSArchiveAdapter
from xmuse.memoryos_recall_runtime import MemoryOSRecallRuntime
from xmuse.memoryos_runtime_adapter import DisabledRoomMemoryRuntime, MemoryOSRoomMemoryRuntime
from xmuse_core.chat.room_memory_advisory_store import RoomMemoryAdvisoryStore
from xmuse_core.chat.room_memory_binding_store import RoomMemoryBindingStore
from xmuse_core.chat.room_memory_document_outbox_store import RoomMemoryDocumentOutboxStore
from xmuse_core.chat.room_memory_message_outbox_store import RoomMemoryMessageOutboxStore
from xmuse_core.chat.room_memory_recall_receipt_store import RoomMemoryRecallReceiptStore
from xmuse_core.chat.room_memory_recall_source_store import RoomMemoryRecallSourceStore
from xmuse_core.chat.room_memory_runtime import RoomMemoryRuntime


def compose_room_runner_memory(
    db_path: Path,
    *,
    worker_id: str,
    environ: Mapping[str, str] | None = None,
) -> tuple[RoomMemoryRuntime, bool]:
    """Build optional derived memory without making it a Runner prerequisite."""

    binding_store = RoomMemoryBindingStore(db_path)
    message_store = RoomMemoryMessageOutboxStore(db_path)
    document_store = RoomMemoryDocumentOutboxStore(db_path)
    source_store = RoomMemoryRecallSourceStore(db_path)
    receipt_store = RoomMemoryRecallReceiptStore(db_path)
    advisory_store = RoomMemoryAdvisoryStore(db_path)
    values = os.environ if environ is None else environ
    url = values.get("XMUSE_MEMORYOS_URL")
    api_key = values.get("XMUSE_MEMORYOS_API_KEY")
    profile = values.get("XMUSE_MEMORYOS_PROFILE", "archive-only")
    if url and api_key:
        try:
            client = MemoryOSArchiveAdapter(
                base_url=url,
                api_key=api_key,
                profile=cast(Literal["archive-only", "full-local"], profile),
            )
            return (
                MemoryOSRoomMemoryRuntime(
                    MemoryOSRecallRuntime(
                        source_store=source_store,
                        receipt_store=receipt_store,
                        advisory_store=advisory_store,
                        client=client,
                        decoder=MemoryOSEvidenceDecoder(source_store),
                    ),
                    MemoryOSDeliveryPump(
                        binding_store=binding_store,
                        message_store=message_store,
                        document_store=document_store,
                        client=client,
                        worker_id=worker_id,
                    ),
                ),
                True,
            )
        except Exception:
            # Memory is derived and optional. Invalid sidecar configuration must
            # not prevent the isolated Room Host from starting.
            return DisabledRoomMemoryRuntime(receipt_store), False
    return DisabledRoomMemoryRuntime(receipt_store), False


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
