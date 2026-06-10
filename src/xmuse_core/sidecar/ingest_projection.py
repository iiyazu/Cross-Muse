from __future__ import annotations

from xmuse_core.sidecar.memoryos_adapter import SidecarIngestRecord
from xmuse_core.sidecar.replay_packet import ReplayPacket, ReplayPacketItem


def _taxonomy_scope_for_item(item: ReplayPacketItem) -> str:
    st = item.source_type
    env = item.envelope_type or ""
    if st == "blueprint" or "blueprint" in env:
        return "blueprint_decision"
    if st == "verdict":
        return "blueprint_decision"
    return "conversation_shared"


def _ingest_intent_for_item(item: ReplayPacketItem) -> str:
    st = item.source_type
    env = item.envelope_type or ""
    if st == "blueprint" or "blueprint" in env:
        return "blueprint_version"
    if st == "verdict":
        return "decision"
    if item.metadata.get("proposal_status") == "accepted":
        return "decision"
    return "raw_message"


def project_item(record: ReplayPacketItem) -> SidecarIngestRecord | None:
    return SidecarIngestRecord(
        session_id=_session_id_for_conversation(record.conversation_id),
        source_type=record.source_type,
        source_id=record.source_id,
        conversation_id=record.conversation_id,
        participant_id=record.participant_id,
        content=record.content,
        timestamp=record.timestamp,
        taxonomy_scope=_taxonomy_scope_for_item(record),
        ingest_intent=_ingest_intent_for_item(record),
        envelope_type=record.envelope_type,
        metadata=dict(record.metadata),
    )


def project_packet(packet: ReplayPacket) -> list[SidecarIngestRecord]:
    return [
        record
        for item in packet.items
        if (record := project_item(item)) is not None
    ]


def project_packets(packets: list[ReplayPacket]) -> list[SidecarIngestRecord]:
    records: list[SidecarIngestRecord] = []
    for p in packets:
        records.extend(project_packet(p))
    return records


def _session_id_for_conversation(conversation_id: str) -> str:
    return f"ses_v6_{conversation_id}"
