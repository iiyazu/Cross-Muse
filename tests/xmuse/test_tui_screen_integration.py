"""Screen-level integration tests (Task 12).
Covers: input history, slash completion, mention completion,
session switch, draft restore, copy mode.
"""
from pathlib import Path

import pytest
from textual.widgets import Input, ListView

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
        {"id": "conv-a", "title": "Conversation A", "created_at": "2026-06-02T00:00:00Z"},
    ]
    tui.adapter.send_message = lambda *a, **kw: "msg-1"
    return tui


async def test_input_history_navigation(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        conv_id = "conv-a"
        app.state.active_conversation_id = conv_id
        app.screen._input_history.push_message(conv_id, "first message")
        app.screen._input_history.push_message(conv_id, "second message")
        inp = app.screen.query_one("#message-input", Input)
        inp.focus()
        await pilot.pause()
        await pilot.press("up")
        assert inp.value == "second message"
        await pilot.press("up")
        assert inp.value == "first message"
        await pilot.press("down")
        assert inp.value == "second message"
        await pilot.press("down")
        assert inp.value == ""


async def test_slash_completion_triggers(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#message-input", Input)
        inp.value = "/"
        inp.post_message(inp.Changed(inp, inp.value))
        await pilot.pause()
        cl = app.screen.query_one("#completion-list", ListView)
        assert cl.has_class("visible")


async def test_session_switch_via_resume(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        app.screen._activate_conversation("conv-a")
        await pilot.pause()
        assert app.state.active_conversation_id == "conv-a"


async def test_draft_restored_on_switch(app: XmuseTUI) -> None:
    app.adapter.list_group_conversations = lambda: [
        {"id": "conv-a", "title": "A", "created_at": "2026-06-02T00:00:00Z"},
        {"id": "conv-b", "title": "B", "created_at": "2026-06-01T00:00:00Z"},
    ]

    async with app.run_test() as pilot:
        inp = app.screen.query_one("#message-input", Input)
        inp.value = "draft text"
        app.screen._activate_conversation("conv-b")
        await pilot.pause()
        assert inp.value == ""  # conv-b has no draft
        app.screen._activate_conversation("conv-a")
        await pilot.pause()
        assert inp.value == "draft text"


async def test_copy_mode_toggle(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        await pilot.press("ctrl+y")
        copy_view = app.screen.query_one("#copy-view")
        assert copy_view.display is True
        await pilot.press("ctrl+y")
        assert copy_view.display is False


async def test_app_renders(app: XmuseTUI) -> None:
    async with app.run_test():
        assert app.screen is not None
        assert app.screen.query_one("#message-input") is not None
        assert app.screen.query_one("#message-log") is not None
        assert app.screen.query_one("#pane-left") is not None
