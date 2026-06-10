from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from textual.message import Message

from xmuse.tui.adapter.xmuse_adapter import StateDelta


@dataclass
class AppState:
    active_conversation_id: str | None = None
    conversations: list[dict] = field(default_factory=list)
    participants: dict[str, list[dict]] = field(default_factory=dict)
    messages: dict[str, list[dict]] = field(default_factory=dict)
    cards: dict[str, list[dict]] = field(default_factory=dict)
    features: dict[str, Any] = field(default_factory=dict)
    lanes: list[dict] = field(default_factory=list)
    run_health: dict | None = None
    lanes_changed: bool = False
    consecutive_error_ticks: int = 0
    has_errors: bool = False
    tui_command_events: list[dict] = field(default_factory=list)

    def apply(self, delta: StateDelta) -> None:
        self.consecutive_error_ticks = self.consecutive_error_ticks + 1 if delta.errors else 0
        self.has_errors = bool(delta.errors)
        if delta.lanes:
            self.lanes = delta.lanes
        if delta.features:
            self.features = delta.features
        if delta.run_health is not None:
            self.run_health = delta.run_health
        if delta.participants:
            for cid, participants in delta.participants.items():
                self.participants[cid] = list(participants)
        self.lanes_changed = delta.lanes_changed
        if delta.replace_peer_status_cards:
            for cid, cards in list(self.cards.items()):
                self.cards[cid] = [
                    card for card in cards if not _is_peer_status_card(card)
                ]
        if delta.messages:
            for msg in delta.messages:
                cid = msg.get("conversation_id", "_unknown")
                messages = self.messages.setdefault(cid, [])
                _remove_completed_stream_messages(messages, msg)
                _remove_replaced_pending_peer_messages(messages, msg)
                _upsert(messages, msg, _message_key)
        if delta.cards:
            for card in delta.cards:
                cid = card.get("conversation_id", "_unknown")
                _upsert(self.cards.setdefault(cid, []), card, _card_key)

    def features_for(self, conv_id: str) -> dict[str, Any]:
        return self.features

    def messages_for(self, conv_id: str) -> list[dict]:
        return self.messages.get(conv_id, [])

    def cards_for(self, conv_id: str) -> list[dict]:
        return self.cards.get(conv_id, [])

    def participants_for(self, conv_id: str) -> list[dict]:
        return self.participants.get(conv_id, [])

    def all_features(self) -> dict[str, Any]:
        return self.features

    def clear_conversation_state(self, conv_id: str) -> None:
        self.messages.pop(conv_id, None)
        self.cards.pop(conv_id, None)

    def latest_lanes(self) -> list[dict]:
        return self.lanes

    def record_tui_command_event(self, event: dict) -> None:
        self.tui_command_events.append(dict(event))
        if len(self.tui_command_events) > 100:
            self.tui_command_events = self.tui_command_events[-100:]


class StateUpdated(Message):
    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state


def _upsert(items: list[dict], item: dict, key_fn) -> None:
    key = key_fn(item)
    if key is None:
        items.append(item)
        return
    for index, existing in enumerate(items):
        if key_fn(existing) == key:
            items[index] = item
            return
    items.append(item)


def _message_key(message: dict) -> tuple[str, str] | None:
    message_id = message.get("id")
    if not message_id:
        return None
    return ("message", str(message_id))


def _remove_completed_stream_messages(messages: list[dict], message: dict) -> None:
    if _is_stream_message(message):
        return
    if str(message.get("role") or "") != "assistant":
        return
    source_inbox_item_id = _source_inbox_item_id(message)
    author = str(message.get("author") or "")
    content = str(message.get("content") or "")
    kept = []
    for existing in messages:
        if not _is_stream_message(existing):
            kept.append(existing)
            continue
        if source_inbox_item_id and _source_inbox_item_id(existing) == source_inbox_item_id:
            continue
        if (
            author
            and str(existing.get("author") or "") == author
            and _same_completed_stream_content(str(existing.get("content") or ""), content)
        ):
            continue
        kept.append(existing)
    if len(kept) != len(messages):
        messages[:] = kept


def _remove_replaced_pending_peer_messages(messages: list[dict], message: dict) -> None:
    if _is_pending_peer_message(message):
        return
    if not (_is_stream_message(message) or _is_final_assistant_message(message)):
        return
    kept = [
        existing
        for existing in messages
        if not (
            _is_pending_peer_message(existing)
            and _same_peer_message_target(existing, message)
        )
    ]
    if len(kept) != len(messages):
        messages[:] = kept


def _is_final_assistant_message(message: dict) -> bool:
    return (
        str(message.get("role") or "") == "assistant"
        and not _is_stream_message(message)
        and not _is_pending_peer_message(message)
    )


def _same_peer_message_target(left: dict, right: dict) -> bool:
    left_target_id = _target_participant_id(left)
    right_target_id = _target_participant_id(right) or str(right.get("author") or "")
    if left_target_id and right_target_id and left_target_id == right_target_id:
        return True
    left_author = str(left.get("author") or "")
    right_author = str(right.get("author") or "")
    if left_author and right_author and left_author == right_author:
        return True
    left_role = _target_role(left)
    right_role = _target_role(right)
    return bool(left_role and right_role and left_role == right_role)


def _same_completed_stream_content(stream_content: str, final_content: str) -> bool:
    if not stream_content or not final_content:
        return False
    return (
        stream_content == final_content
        or stream_content.startswith(final_content)
        or final_content.startswith(stream_content)
    )


def _is_stream_message(message: dict) -> bool:
    return (
        str(message.get("id") or "").startswith("stream_")
        or str(message.get("envelope_type") or "") == "stream"
    )


def _is_pending_peer_message(message: dict) -> bool:
    return (
        str(message.get("id") or "").startswith("peer_pending_")
        or str(message.get("envelope_type") or "") == "peer_pending"
    )


def _source_inbox_item_id(message: dict) -> str | None:
    envelope = message.get("envelope_json")
    if not isinstance(envelope, dict):
        return None
    value = envelope.get("source_inbox_item_id")
    return str(value) if value else None


def _target_participant_id(message: dict) -> str | None:
    envelope = message.get("envelope_json")
    if not isinstance(envelope, dict):
        return None
    value = envelope.get("target_participant_id")
    return str(value) if value else None


def _target_role(message: dict) -> str | None:
    envelope = message.get("envelope_json")
    if not isinstance(envelope, dict):
        return None
    value = envelope.get("target_role")
    return str(value) if value else None


def _card_key(card: dict) -> tuple[str, str] | None:
    card_type = str(card.get("card_type") or "")
    source_id = card.get("source_id")
    if card_type in {"peer_route_status", "peer_pending"} and source_id:
        return ("peer_inbox", str(source_id))
    for field_name in ("id", "intent_id", "source_id"):
        value = card.get(field_name)
        if value:
            return ("card", str(value))
    return None


def _is_peer_status_card(card: dict) -> bool:
    return str(card.get("card_type") or "") in {"peer_route_status", "peer_pending"}
