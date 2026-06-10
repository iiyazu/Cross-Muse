from __future__ import annotations

from pathlib import Path


def test_groupchat_bootstrap_modules_do_not_import_memoryos() -> None:
    repo = Path(__file__).resolve().parents[2]
    files = [
        repo / "src/xmuse_core/chat/bootstrap_contracts.py",
        repo / "src/xmuse_core/chat/bootstrap_store.py",
        repo / "src/xmuse_core/chat/peer_service.py",
        repo / "xmuse/chat_api.py",
        repo / "xmuse/tui/slash_commands.py",
    ]
    offenders = [
        str(path.relative_to(repo))
        for path in files
        if "memoryos" in path.read_text(encoding="utf-8").lower()
    ]
    assert offenders == []
