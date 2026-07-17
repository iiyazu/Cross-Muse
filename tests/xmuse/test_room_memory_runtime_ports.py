from __future__ import annotations

from typing import get_type_hints

from xmuse.room_runner_memory import run_room_memory_pump
from xmuse_core.chat.room_codex_transport import CodexRoomObservationTransport
from xmuse_core.chat.room_host import RoomParticipantHost
from xmuse_core.chat.room_memory_runtime import (
    RoomMemoryContextReceiptPort,
    RoomMemoryDeliveryPumpPort,
    RoomMemoryRecallPort,
)


def _declared_capabilities(protocol: type[object]) -> set[str]:
    return {
        name
        for name in protocol.__dict__
        if not name.startswith("_") and name not in {"__module__", "__doc__"}
    }


def test_room_memory_runtime_ports_are_disjoint_consumer_capabilities() -> None:
    recall = _declared_capabilities(RoomMemoryRecallPort)
    context = _declared_capabilities(RoomMemoryContextReceiptPort)
    delivery = _declared_capabilities(RoomMemoryDeliveryPumpPort)

    assert recall == {"recall_timeout_s", "recall", "record_recall_receipt"}
    assert context == {"bind_context_receipt"}
    assert delivery == {"pump_once"}
    assert recall.isdisjoint(context | delivery)
    assert context.isdisjoint(delivery)


def test_each_production_consumer_accepts_only_its_memory_port() -> None:
    host = get_type_hints(RoomParticipantHost.__init__)
    transport = get_type_hints(CodexRoomObservationTransport.__init__)
    pump = get_type_hints(run_room_memory_pump)

    assert host["memory_runtime"] == RoomMemoryRecallPort | None
    assert transport["memory_runtime"] == RoomMemoryContextReceiptPort | None
    assert pump["runtime"] is RoomMemoryDeliveryPumpPort
