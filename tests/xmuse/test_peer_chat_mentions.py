from pathlib import Path

import pytest

from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.peer_service import PeerChatError, PeerChatService
from xmuse_core.chat.store import ChatStore


def _conversation(tmp_path: Path, title: str = "Mentions"):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation(title)
    participants = ParticipantStore(db)
    return db, conv, participants


def test_human_message_routes_by_lowercase_multiword_display_name(tmp_path: Path) -> None:
    db, conv, participants = _conversation(tmp_path)
    lead = participants.add(
        conversation_id=conv.id,
        role="execute",
        display_name="execution lead",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(db)

    result = service.post_human_message(
        conversation_id=conv.id,
        author="Human operator",
        content="please @execution lead pick this up",
        client_request_id="display-lowercase-1",
    )

    assert result.message.mentions == ["@execution-lead"]
    assert result.inbox_items[0].target_participant_id == lead.participant_id


def test_participant_id_mentions_do_not_cross_conversations(tmp_path: Path) -> None:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    conv_a = chat.create_conversation("A")
    conv_b = chat.create_conversation("B")
    participants = ParticipantStore(db)
    participants.add(
        conversation_id=conv_a.id,
        role="review",
        display_name="Review A",
        cli_kind="codex",
        model="gpt-5.5",
    )
    other = participants.add(
        conversation_id=conv_b.id,
        role="review",
        display_name="Review B",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(db)

    with pytest.raises(PeerChatError) as exc_info:
        service.post_human_message(
            conversation_id=conv_a.id,
            author="Human operator",
            content=f"please @participant:{other.participant_id} inspect",
            client_request_id="cross-conv-participant-id",
        )

    assert exc_info.value.code == "unknown_target"
    assert ChatStore(db).list_messages(conv_a.id) == []


def test_unknown_mentions_are_explicit_and_do_not_create_messages(tmp_path: Path) -> None:
    db, conv, participants = _conversation(tmp_path)
    participants.add(
        conversation_id=conv.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    service = PeerChatService(db)

    with pytest.raises(PeerChatError) as exc_info:
        service.post_human_message(
            conversation_id=conv.id,
            author="Human operator",
            content="please @missing role inspect",
            client_request_id="unknown-explicit",
        )

    assert exc_info.value.code == "unknown_target"
    assert exc_info.value.message == "@missing"
    assert ChatStore(db).list_messages(conv.id) == []


def test_ambiguous_display_names_are_explicit(tmp_path: Path) -> None:
    db, conv, participants = _conversation(tmp_path)
    for role in ("review-primary", "review-backup"):
        participants.add(
            conversation_id=conv.id,
            role=role,
            display_name="Review GOD",
            cli_kind="codex",
            model="gpt-5.5",
        )
    service = PeerChatService(db)

    with pytest.raises(PeerChatError) as exc_info:
        service.post_human_message(
            conversation_id=conv.id,
            author="Human operator",
            content="@Review GOD please inspect",
            client_request_id="ambiguous-display",
        )

    assert exc_info.value.code == "ambiguous_target"
    assert ChatStore(db).list_messages(conv.id) == []
