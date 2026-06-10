from __future__ import annotations

from xmuse.tui.adapter.xmuse_adapter import StateDelta
from xmuse.tui.state import AppState


def test_app_state_replaces_peer_status_card_for_same_inbox_item() -> None:
    state = AppState()

    state.apply(
        StateDelta(
            cards=[
                {
                    "id": "card_inbox_route_inbox-1",
                    "conversation_id": "conv-1",
                    "card_type": "peer_route_status",
                    "source_id": "inbox-1",
                    "status": "routed",
                    "title": "Routed to Architect GOD",
                }
            ]
        )
    )
    state.apply(
        StateDelta(
            cards=[
                {
                    "id": "card_inbox_pending_inbox-1",
                    "conversation_id": "conv-1",
                    "card_type": "peer_pending",
                    "source_id": "inbox-1",
                    "status": "pending",
                    "title": "Architect GOD is thinking",
                }
            ]
        )
    )

    assert state.cards_for("conv-1") == [
        {
            "id": "card_inbox_pending_inbox-1",
            "conversation_id": "conv-1",
            "card_type": "peer_pending",
            "source_id": "inbox-1",
            "status": "pending",
            "title": "Architect GOD is thinking",
        }
    ]


def test_app_state_deduplicates_messages_by_id() -> None:
    state = AppState()
    message = {
        "id": "msg-1",
        "conversation_id": "conv-1",
        "author": "user",
        "content": "hello",
    }

    state.apply(StateDelta(messages=[message]))
    state.apply(StateDelta(messages=[dict(message)]))

    assert state.messages_for("conv-1") == [message]


def test_app_state_replaces_peer_status_cards_with_empty_current_set() -> None:
    state = AppState()
    state.apply(
        StateDelta(
            cards=[
                {
                    "id": "card_inbox_pending_inbox-1",
                    "conversation_id": "conv-1",
                    "card_type": "peer_pending",
                    "source_id": "inbox-1",
                },
                {
                    "id": "worklist-1",
                    "conversation_id": "conv-1",
                    "card_type": "worklist_summary",
                },
            ]
        )
    )

    state.apply(StateDelta(replace_peer_status_cards=True))

    assert state.cards_for("conv-1") == [
        {
            "id": "worklist-1",
            "conversation_id": "conv-1",
            "card_type": "worklist_summary",
        }
    ]


def test_app_state_removes_matching_stream_when_final_reply_arrives() -> None:
    state = AppState()
    state.apply(
        StateDelta(
            messages=[
                {
                    "id": "stream_inbox-1",
                    "conversation_id": "conv-1",
                    "author": "architect-god",
                    "role": "assistant",
                    "content": "hello world",
                    "envelope_type": "stream",
                    "envelope_json": {
                        "type": "stream",
                        "source_inbox_item_id": "inbox-1",
                    },
                }
            ]
        )
    )

    final = {
        "id": "msg-1",
        "conversation_id": "conv-1",
        "author": "architect-god",
        "role": "assistant",
        "content": "hello world",
        "envelope_type": "peer_reply",
        "envelope_json": {"source_inbox_item_id": "inbox-1"},
    }
    state.apply(StateDelta(messages=[final]))

    assert state.messages_for("conv-1") == [final]


def test_app_state_replaces_pending_peer_message_with_active_stream() -> None:
    state = AppState()
    state.apply(
        StateDelta(
            messages=[
                {
                    "id": "peer_pending_conv-1_part-architect",
                    "conversation_id": "conv-1",
                    "author": "part-architect",
                    "display_author": "architect-god",
                    "role": "assistant",
                    "content": "architect-god ...",
                    "envelope_type": "peer_pending",
                    "envelope_json": {
                        "type": "peer_pending",
                        "target_role": "architect",
                        "target_participant_id": "part-architect",
                    },
                }
            ]
        )
    )

    stream = {
        "id": "stream_inbox-1",
        "conversation_id": "conv-1",
        "author": "part-architect",
        "display_author": "architect-god",
        "role": "assistant",
        "content": "Drafting...",
        "envelope_type": "stream",
        "envelope_json": {
            "type": "stream",
            "source_inbox_item_id": "inbox-1",
        },
    }
    state.apply(StateDelta(messages=[stream]))

    assert state.messages_for("conv-1") == [stream]


def test_app_state_removes_pending_peer_message_when_final_reply_arrives() -> None:
    state = AppState()
    state.apply(
        StateDelta(
            messages=[
                {
                    "id": "peer_pending_conv-1_part-architect",
                    "conversation_id": "conv-1",
                    "author": "part-architect",
                    "display_author": "architect-god",
                    "role": "assistant",
                    "content": "architect-god ...",
                    "envelope_type": "peer_pending",
                    "envelope_json": {
                        "type": "peer_pending",
                        "target_role": "architect",
                        "target_participant_id": "part-architect",
                    },
                }
            ]
        )
    )

    final = {
        "id": "msg-1",
        "conversation_id": "conv-1",
        "author": "part-architect",
        "display_author": "architect-god",
        "role": "assistant",
        "content": "Here is the blueprint.",
        "envelope_type": "peer_reply",
        "envelope_json": {"source_inbox_item_id": "inbox-1"},
    }
    state.apply(StateDelta(messages=[final]))

    assert state.messages_for("conv-1") == [final]


def test_app_state_removes_legacy_stream_by_author_and_content() -> None:
    state = AppState()
    state.apply(
        StateDelta(
            messages=[
                {
                    "id": "stream_req-1",
                    "conversation_id": "conv-1",
                    "author": "architect-god",
                    "role": "assistant",
                    "content": "same content",
                    "envelope_type": "stream",
                    "envelope_json": {"type": "stream"},
                }
            ]
        )
    )

    final = {
        "id": "msg-1",
        "conversation_id": "conv-1",
        "author": "architect-god",
        "role": "assistant",
        "content": "same content",
    }
    state.apply(StateDelta(messages=[final]))

    assert state.messages_for("conv-1") == [final]


def test_app_state_tracks_participants_by_conversation() -> None:
    state = AppState()
    state.apply(
        StateDelta(
            participants={
                "conv-1": [
                    {
                        "participant_id": "part-architect",
                        "role": "architect",
                        "display_name": "architect-god",
                    }
                ]
            }
        )
    )

    assert state.participants_for("conv-1") == [
        {
            "participant_id": "part-architect",
            "role": "architect",
            "display_name": "architect-god",
        }
    ]
    assert state.participants_for("missing") == []
