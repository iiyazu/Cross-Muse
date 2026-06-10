from __future__ import annotations

from pathlib import Path

from xmuse_core.chat.peer_cards import PeerChatCardAssembler
from xmuse_core.chat.peer_service import PeerChatService


def test_peer_chat_service_uses_extracted_card_assembler(tmp_path: Path) -> None:
    service = PeerChatService(tmp_path / "chat.db")

    assembler = service._card_assembler()

    assert isinstance(assembler, PeerChatCardAssembler)
