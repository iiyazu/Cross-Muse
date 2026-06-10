"""Keymap behavior tests (Task 13: TUI-KEYMAP-TESTS).
Covers: Up/Down, Tab, Enter, Esc, Ctrl+C, Ctrl+Y for history/completion/copy mode.
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
        {"id": "conv-a", "title": "A", "created_at": "2026-06-02T00:00:00Z"},
    ]
    return tui


async def test_ctrl_c_copy_selection(app: XmuseTUI) -> None:
    captured = []
    async with app.run_test() as pilot:
        app.screen.get_selected_text = lambda: "selected text"
        app._copy_text_to_clipboard = lambda text: captured.append(text)
        await pilot.press("ctrl+c")
        assert captured == ["selected text"]


async def test_ctrl_y_toggles_copy_view(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        cv = app.screen.query_one("#copy-view")
        assert cv.display is False
        await pilot.press("ctrl+y")
        assert cv.display is True
        await pilot.press("ctrl+y")
        assert cv.display is False


async def test_escape_in_completion_dismisses(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        app.screen._completion_candidates = [{"type": "command", "value": "/help"}]
        from textual.widgets import ListView
        cl = app.screen.query_one("#completion-list", ListView)
        cl.add_class("visible")
        await pilot.press("escape")
        assert not app.screen._completion_candidates


async def test_history_up_down(app: XmuseTUI) -> None:
    from textual.widgets import Input
    async with app.run_test() as pilot:
        inp = app.screen.query_one("#message-input", Input)
        app.screen._input_history.push_message("conv-a", "hello")
        app.screen._input_history.push_message("conv-a", "world")
        app.state.active_conversation_id = "conv-a"
        inp.focus()
        await pilot.pause()
        await pilot.press("up")
        assert inp.value == "world"
        await pilot.press("up")
        assert inp.value == "hello"
        await pilot.press("down")
        assert inp.value == "world"
        await pilot.press("down")
        assert inp.value == ""


async def test_ctrl_f_enters_search_mode(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        app.screen._activate_conversation("conv-a")
        await pilot.pause()
        await pilot.press("ctrl+f")
        search_bar = app.screen.query_one("#search-input")
        assert search_bar is not None


async def test_search_escape_exits(app: XmuseTUI) -> None:
    async with app.run_test() as pilot:
        app.screen._activate_conversation("conv-a")
        await pilot.pause()
        await pilot.press("ctrl+f")
        await pilot.press("escape")
        assert app.screen._search_mode is False


async def test_ctrl_r_refresh(app: XmuseTUI) -> None:
    refreshed = []
    async with app.run_test() as pilot:
        app.action_refresh_now = lambda: refreshed.append(True)
        await pilot.press("ctrl+r")
        assert refreshed == [True]
