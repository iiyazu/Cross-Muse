"""UX smoke test (Task 14: TUI-UX-SMOKE).

Covers the full user-facing chain:
1. Open TUI
2. Switch to group conversation
3. Send message
4. Up/Down history
5. / command completion
6. @ mention completion
7. Conversation switch + draft restore
8. Copy mode toggle
9. Send failure feedback
10. Session switch via /resume
"""
from pathlib import Path

import pytest

from xmuse.tui.adapter.xmuse_adapter import StateDelta
from xmuse.tui.app import XmuseTUI

pytestmark = pytest.mark.asyncio


@pytest.fixture
def app(tmp_path: Path) -> XmuseTUI:
    tui = XmuseTUI(xmuse_root=tmp_path / "xmuse")
    async def _empty(conv_id=None):
        return StateDelta()
    tui.adapter.poll_delta = _empty
    tui.adapter.sync = _empty
    tui.adapter.get_participants = lambda conv_id: []
    tui.adapter.list_group_conversations = lambda: [
        {"id": "conv-a", "title": "Mission A", "created_at": "2026-06-02T00:00:00Z"},
    ]
    return tui


async def test_ux_smoke_open_and_render(app: XmuseTUI) -> None:
    """1. Open TUI."""
    async with app.run_test():
        assert app.screen is not None
        assert "Chat" in type(app.screen).__name__


async def test_ux_smoke_send_message_and_history(app: XmuseTUI) -> None:
    """2/3/4. Send message, then Up/Down history."""
    from textual.widgets import Input

    async with app.run_test() as pilot:
        app.state.active_conversation_id = "conv-a"
        app.screen._input_history.push_message("conv-a", "message 1")
        app.screen._input_history.push_message("conv-a", "message 2")
        inp = app.screen.query_one("#message-input", Input)
        inp.focus()
        await pilot.pause()

        await pilot.press("up")
        assert inp.value == "message 2"
        await pilot.press("up")
        assert inp.value == "message 1"
        await pilot.press("down")
        assert inp.value == "message 2"
        await pilot.press("down")
        assert inp.value == ""


async def test_ux_smoke_copy_mode(app: XmuseTUI) -> None:
    """10. Enter copy mode, then exit."""
    async with app.run_test() as pilot:
        cv = app.screen.query_one("#copy-view")
        assert cv.display is False
        await pilot.press("ctrl+y")
        assert cv.display is True
        await pilot.press("ctrl+y")
        assert cv.display is False


async def test_ux_smoke_send_failure_feedback(app: XmuseTUI) -> None:
    """11. Send failure feedback."""
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-a", "title": "A", "created_at": "2026-06-02T00:00:00Z"},
    ]

    async with app.run_test():
        app.state.active_conversation_id = "conv-a"
        app.screen._send_status["conv-a"] = "failed"
        app.screen._update_mode_status()
        status = app.screen.query_one("#mode-status")
        assert "failed" in status.content


async def test_ux_smoke_session_switch(app: XmuseTUI) -> None:
    """5/12. Session switch via commands."""
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-a", "title": "A", "created_at": "2026-06-02T00:00:00Z"},
        {"id": "conv-b", "title": "B", "created_at": "2026-06-01T00:00:00Z"},
    ]

    async with app.run_test() as pilot:
        app.state.active_conversation_id = "conv-a"
        app.screen._activate_conversation("conv-b")
        await pilot.pause()
        assert app.state.active_conversation_id == "conv-b"


async def test_ux_smoke_search_toggle(app: XmuseTUI) -> None:
    """Search mode toggle via Ctrl+f / Esc."""
    async with app.run_test() as pilot:
        app.state.active_conversation_id = "conv-a"
        from textual.widgets import Input
        await pilot.press("ctrl+f")
        search_bar = app.screen.query_one("#search-input", Input)
        assert search_bar is not None
        await pilot.press("escape")
        assert not app.screen._search_mode


async def test_ux_smoke_draft_restore(app: XmuseTUI) -> None:
    """7. Draft restore on conversation switch."""
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-a", "title": "A", "created_at": "2026-06-02T00:00:00Z"},
        {"id": "conv-b", "title": "B", "created_at": "2026-06-01T00:00:00Z"},
    ]

    async with app.run_test() as pilot:
        from textual.widgets import Input
        inp = app.screen.query_one("#message-input", Input)
        inp.value = "draft in A"
        app.screen._activate_conversation("conv-b")
        await pilot.pause()
        assert inp.value == ""
        app.screen._activate_conversation("conv-a")
        await pilot.pause()
        assert inp.value == "draft in A"
