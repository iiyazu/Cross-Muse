from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.models import ChatCard
from xmuse_core.chat.store import ChatStore
from xmuse_core.sidecar.replay_packet import (
    IngestIntent,
    ReplayPacket,
    ReplayPacketItem,
    build_replay_packet,
    source_type_for_envelope,
)

_CARD_TYPE_TO_SOURCE_TYPE: dict[str, str] = {
    "mission_blueprint": "blueprint",
    "feature_plan": "blueprint",
    "lane_graph": "proposal",
    "feature_graph_set": "blueprint",
    "blueprint_execution_started": "card",
    "feature_plan_ready": "card",
    "lane_blocked": "card",
    "run_progress": "card",
    "takeover_requested": "card",
    "run_takeover": "card",
    "run_terminal": "card",
    "review_verdict": "verdict",
    "takeover": "card",
    "proposal": "proposal",
    "health_summary": "card",
    "worklist_summary": "card",
    "peer_request": "card",
    "peer_result": "card",
}


def _card_source_type(card: ChatCard) -> str:
    return _CARD_TYPE_TO_SOURCE_TYPE.get(card.card_type, "card")


class ChatReplayExporter:
    def __init__(self, chat_store: ChatStore, base_dir: Path | str | None = None) -> None:
        self._store = chat_store
        self._base_dir = Path(base_dir) if base_dir else Path(chat_store._path).parent

    def export_conversation(
        self,
        conversation_id: str,
        *,
        max_items: int | None = None,
    ) -> list[ReplayPacket]:
        conversations = self._store.list_conversations()
        if not any(c.id == conversation_id for c in conversations):
            return []
        items: list[ReplayPacketItem] = []
        self._add_message_items(items, conversation_id, max_items=max_items)
        self._add_proposal_items(items, conversation_id)
        self._add_resolution_items(items, conversation_id)
        self._add_card_items(items, conversation_id)
        items.sort(key=lambda i: i.timestamp)
        return [
            build_replay_packet(
                conversation_id=conversation_id,
                items=items,
                ingest_intent=IngestIntent.RAW_MESSAGE,
                scope_note="conversation_shared",
            ),
        ]

    def _add_message_items(
        self,
        items: list[ReplayPacketItem],
        conversation_id: str,
        *,
        max_items: int | None = None,
    ) -> None:
        messages = self._store.list_messages(conversation_id)
        if max_items is not None:
            messages = messages[:max_items]
        for msg in messages:
            ts = _parse_timestamp(msg.created_at)
            participant_id = _author_to_participant_id(msg.author)
            source_type = source_type_for_envelope(msg.envelope_type or "message")
            items.append(
                ReplayPacketItem(
                    source_type=source_type,
                    source_id=msg.id,
                    conversation_id=msg.conversation_id,
                    participant_id=participant_id,
                    content=msg.content,
                    timestamp=ts,
                    thread_id=msg.reply_to_message_id,
                    envelope_type=msg.envelope_type,
                    metadata=dict(msg.envelope_json or {}),
                )
            )

    def _add_proposal_items(
        self,
        items: list[ReplayPacketItem],
        conversation_id: str,
    ) -> None:
        for prop in self._store.list_proposals(conversation_id):
            if prop.conversation_id != conversation_id:
                continue
            ts = _parse_timestamp(prop.created_at)
            participant_id = _author_to_participant_id(prop.author)
            items.append(
                ReplayPacketItem(
                    source_type="proposal",
                    source_id=prop.id,
                    conversation_id=prop.conversation_id,
                    participant_id=participant_id,
                    content=prop.content,
                    timestamp=ts,
                    envelope_type=prop.proposal_type,
                    metadata={"proposal_status": prop.status.value, "references": prop.references},
                )
            )

    def _add_resolution_items(
        self,
        items: list[ReplayPacketItem],
        conversation_id: str,
    ) -> None:
        for resolution in self._store.list_resolutions(conversation_id):
            if resolution.conversation_id != conversation_id:
                continue
            ts = _parse_timestamp(resolution.created_at)
            source_type = _resolution_source_type(resolution)
            content = resolution.goal_summary or str(resolution.content)
            items.append(
                ReplayPacketItem(
                    source_type=source_type,
                    source_id=resolution.id,
                    conversation_id=resolution.conversation_id,
                    participant_id="participant_system",
                    content=content,
                    timestamp=ts,
                    envelope_type="resolution",
                    metadata={
                        "resolution_status": resolution.status.value,
                        "version": resolution.version,
                        "derived_from_proposal_ids": list(resolution.derived_from_proposal_ids),
                        "approved_by": list(resolution.approved_by),
                        "approval_mode": resolution.approval_mode,
                    },
                )
            )

    def _add_card_items(
        self,
        items: list[ReplayPacketItem],
        conversation_id: str,
    ) -> None:
        try:
            from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter

            emitter = ChatExecutionCardEmitter(self._base_dir)
            cards = emitter.list_cards(conversation_id)
        except Exception:
            return
        for card in cards:
            if card.conversation_id != conversation_id:
                continue
            ts = _parse_timestamp(card.created_at)
            items.append(
                ReplayPacketItem(
                    source_type=_card_source_type(card),
                    source_id=card.id,
                    conversation_id=card.conversation_id,
                    participant_id="participant_system",
                    content=card.summary,
                    timestamp=ts,
                    envelope_type=card.card_type,
                    metadata={
                        "card_title": card.title,
                        "card_status": card.status,
                        "card_href": card.href,
                    },
                )
            )


def export_all_conversations(
    chat_store: ChatStore,
    *,
    max_items_per_conversation: int | None = None,
    base_dir: Path | str | None = None,
) -> dict[str, list[ReplayPacket]]:
    exporter = ChatReplayExporter(chat_store, base_dir=base_dir)
    result: dict[str, list[ReplayPacket]] = {}
    for conv in chat_store.list_conversations():
        packets = exporter.export_conversation(
            conv.id,
            max_items=max_items_per_conversation,
        )
        if packets:
            result[conv.id] = packets
    return result


def _resolution_source_type(resolution: Any) -> str:
    content = resolution.content if hasattr(resolution, "content") else {}
    if isinstance(content, dict):
        rtype = content.get("type") or content.get("resolution_type") or ""
        if "blueprint" in rtype or "mission" in rtype:
            return "blueprint"
        if "feature_plan" in rtype:
            return "blueprint"
    return "blueprint"


def _parse_timestamp(ts_str: str) -> datetime:
    if ts_str.endswith("Z"):
        ts_str = ts_str[:-1] + "+00:00"
    return datetime.fromisoformat(ts_str)


def _author_to_participant_id(author: str) -> str:
    return f"participant_{author}"
