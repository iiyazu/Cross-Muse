from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field

PacketSourceType = Literal[
    "message",
    "card",
    "proposal",
    "blueprint",
    "verdict",
    "artifact",
]


class IngestIntent(StrEnum):
    RAW_MESSAGE = "raw_message"
    DECISION = "decision"
    SUMMARY_CANDIDATE = "summary_candidate"
    UNRESOLVED_THREAD = "unresolved_thread"
    BLUEPRINT_VERSION = "blueprint_version"
    PARTICIPANT_NOTE = "participant_note"


_ENVELOPE_TO_SOURCE_TYPE: dict[str, PacketSourceType] = {
    "message": "message",
    "card": "card",
    "proposal": "proposal",
    "mission_blueprint": "blueprint",
    "feature_plan": "blueprint",
    "lane_graph": "proposal",
    "verdict": "verdict",
    "health_card": "card",
}


def source_type_for_envelope(envelope_type: str) -> PacketSourceType:
    return _ENVELOPE_TO_SOURCE_TYPE.get(envelope_type, "message")


def _new_packet_id() -> str:
    return f"replay_{uuid4().hex[:12]}"


class ReplayPacketItem(BaseModel):
    source_type: PacketSourceType
    source_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    participant_id: str = Field(min_length=1)
    content: str
    timestamp: datetime
    thread_id: str | None = None
    envelope_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReplayPacket(BaseModel):
    packet_id: str = Field(default_factory=_new_packet_id)
    conversation_id: str = Field(min_length=1)
    ingest_intent: IngestIntent
    scope_note: str | None = None
    items: list[ReplayPacketItem] = Field(min_length=1)
    created_at: datetime = Field(default_factory=datetime.now)


def build_message_item(
    source_id: str,
    conversation_id: str,
    participant_id: str,
    content: str,
    timestamp: datetime,
    *,
    thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReplayPacketItem:
    return ReplayPacketItem(
        source_type="message",
        source_id=source_id,
        conversation_id=conversation_id,
        participant_id=participant_id,
        content=content,
        timestamp=timestamp,
        thread_id=thread_id,
        metadata=metadata or {},
    )


def build_proposal_item(
    source_id: str,
    conversation_id: str,
    participant_id: str,
    content: str,
    timestamp: datetime,
    *,
    envelope_type: str | None = None,
    thread_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ReplayPacketItem:
    source_type = source_type_for_envelope(envelope_type or "proposal")
    return ReplayPacketItem(
        source_type=source_type,
        source_id=source_id,
        conversation_id=conversation_id,
        participant_id=participant_id,
        content=content,
        timestamp=timestamp,
        thread_id=thread_id,
        envelope_type=envelope_type,
        metadata=metadata or {},
    )


def build_replay_packet(
    conversation_id: str,
    items: list[ReplayPacketItem],
    ingest_intent: IngestIntent,
    *,
    scope_note: str | None = None,
) -> ReplayPacket:
    return ReplayPacket(
        conversation_id=conversation_id,
        ingest_intent=ingest_intent,
        scope_note=scope_note,
        items=sorted(items, key=lambda i: i.timestamp),
    )
