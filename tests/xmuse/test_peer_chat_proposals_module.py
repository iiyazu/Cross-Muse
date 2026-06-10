from __future__ import annotations

from pathlib import Path

from xmuse_core.chat.peer_proposals import PeerProposalEmitter
from xmuse_core.chat.peer_service import PeerChatService


def test_peer_chat_service_uses_extracted_proposal_emitter(tmp_path: Path) -> None:
    service = PeerChatService(tmp_path / "chat.db")

    emitter = service._proposal_emitter()

    assert isinstance(emitter, PeerProposalEmitter)
