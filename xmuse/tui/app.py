# xmuse/tui/app.py
from __future__ import annotations

import asyncio
from pathlib import Path

from textual.app import App
from textual.binding import Binding

from xmuse.tui.adapter.xmuse_adapter import StateDelta, XmuseAdapter
from xmuse.tui.clipboard import copy_to_system_clipboard
from xmuse.tui.screens.chat_screen import ChatScreen
from xmuse.tui.screens.feature_board import FeatureBoardScreen
from xmuse.tui.screens.feature_detail import FeatureDetailScreen
from xmuse.tui.screens.lane_detail import LaneDetailScreen
from xmuse.tui.screens.planning_run import PlanningRunScreen
from xmuse.tui.screens.provider_board import ProviderBoardScreen
from xmuse.tui.state import AppState, StateUpdated


class XmuseTUI(App):
    CSS_PATH = "style/theme.tcss"

    BINDINGS = [
        Binding("ctrl+d", "switch_screen('board')", "Feature Board"),
        Binding("ctrl+1", "switch_screen('chat')", "Chat"),
        Binding("ctrl+a", "toggle_archive", "Archive"),
        Binding("ctrl+c", "copy_selection", "Copy"),
        Binding("ctrl+r", "refresh_now", "Refresh"),
        Binding("ctrl+y", "toggle_copy_view", "Copy View"),
        Binding("escape", "pop_screen", "Back"),
    ]

    SCREENS = {
        "chat": ChatScreen,
        "board": FeatureBoardScreen,
        "feature_detail": FeatureDetailScreen,
        "lane_detail": LaneDetailScreen,
        "planning_run": PlanningRunScreen,
        "provider_board": ProviderBoardScreen,
    }

    def __init__(self, xmuse_root: Path) -> None:
        super().__init__()
        self.adapter = XmuseAdapter(xmuse_root)
        self.state = AppState()

    def on_mount(self) -> None:
        self.push_screen("chat")
        self.set_interval(2.5, self._tick)

    async def _tick(self) -> None:
        conv_id = self.state.active_conversation_id
        try:
            if self.state.consecutive_error_ticks >= 3:
                if conv_id:
                    self.state.clear_conversation_state(conv_id)
                delta = await self.adapter.sync(conv_id)
            else:
                delta = await self.adapter.poll_delta(conv_id)
        except Exception as exc:
            delta = StateDelta(errors={"tick": str(exc)})
        self.state.apply(delta)
        if self.screen_stack:
            self.screen.post_message(StateUpdated(self.state))

    def action_refresh_now(self) -> None:
        asyncio.create_task(self._tick())

    def action_toggle_archive(self) -> None:
        if hasattr(self.screen, "action_toggle_archive"):
            self.screen.action_toggle_archive()

    def action_copy_selection(self) -> None:
        selected = self.screen.get_selected_text() if self.screen_stack else None
        text = selected or self._screen_copy_text()
        if text:
            self._copy_text_to_clipboard(text)

    def _screen_copy_text(self) -> str | None:
        if not self.screen_stack:
            return None
        provider = getattr(self.screen, "get_copy_text_for_clipboard", None)
        if not callable(provider):
            return None
        text = provider()
        return str(text) if text else None

    def _copy_text_to_clipboard(self, text: str) -> None:
        self.copy_to_clipboard(text)
        copy_to_system_clipboard(text)

    def action_toggle_copy_view(self) -> None:
        if hasattr(self.screen, "action_toggle_copy_view"):
            self.screen.action_toggle_copy_view()

    def action_pop_screen(self) -> None:
        if len(self.screen_stack) > 1:
            super().pop_screen()
