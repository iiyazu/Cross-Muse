# xmuse/tui/__main__.py
"""Entry point: uv run python -m xmuse.tui"""
from __future__ import annotations

import os
from pathlib import Path

from xmuse.tui.adapter.xmuse_adapter import XmuseAdapter
from xmuse.tui.app import XmuseTUI
from xmuse_core.chat.inspector_builder import build_conversation_inspector_payload
from xmuse_core.chat.terminal_tui_demo import terminal_tui_demo_scripted_inputs
from xmuse_core.runtime.paths import default_xmuse_root


def main() -> None:
    root = default_xmuse_root(Path(__file__).resolve().parent.parent)
    if _run_terminal_demo_autorun_if_requested(root):
        return
    app = XmuseTUI(xmuse_root=root)
    app.run()


def _run_terminal_demo_autorun_if_requested(root: Path) -> bool:
    if os.environ.get("XMUSE_TUI_TERMINAL_DEMO_AUTORUN") != "1":
        return False
    conversation_id = os.environ.get("XMUSE_TUI_DEMO_CONVERSATION_ID", "").strip()
    terminal_run_id = os.environ.get("XMUSE_TUI_TERMINAL_RUN_ID", "").strip()
    if not conversation_id or not terminal_run_id:
        return False
    adapter = XmuseAdapter(root)
    for scripted_input in terminal_tui_demo_scripted_inputs(conversation_id):
        command, _, _ = scripted_input.partition(" ")
        inspector = build_conversation_inspector_payload(conversation_id, root)
        if not isinstance(inspector, dict):
            continue
        adapter.record_tui_command_event(
            {
                "command": command,
                "conversation_id": conversation_id,
                "read_surface_authority": "chat_inspector",
                "surface_ref": f"chat_inspector:{conversation_id}",
                "terminal_run_id": terminal_run_id,
            }
        )
    return True


if __name__ == "__main__":
    main()
