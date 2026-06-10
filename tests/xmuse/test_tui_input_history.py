"""Tests for TUI input history (Task 1: TUI-INPUT-HISTORY)."""

import pytest

from xmuse.tui.screens.chat_screen import InputHistory


@pytest.fixture
def history():
    return InputHistory(max_per_type=10)


class TestInputHistoryCore:
    def test_push_and_navigate_forward(self, history):
        history.push_message("conv-1", "hello")
        history.push_message("conv-1", "world")
        assert history.navigate_up("conv-1") == "world"
        assert history.navigate_up("conv-1") == "hello"

    def test_navigate_down_returns_to_empty(self, history):
        history.push_message("conv-1", "hello")
        history.push_message("conv-1", "world")
        history.navigate_up("conv-1")  # -> world
        history.navigate_up("conv-1")  # -> hello
        assert history.navigate_down("conv-1") == "world"
        assert history.navigate_down("conv-1") == ""
        assert history.navigate_down("conv-1") == ""

    def test_empty_history_up_does_nothing(self, history):
        assert history.navigate_up("conv-1") == ""

    def test_empty_history_down_does_nothing(self, history):
        assert history.navigate_down("conv-1") == ""

    def test_slash_history_separate(self, history):
        history.push_message("conv-1", "hello")
        history.push_slash("conv-1", "/help")
        history.push_message("conv-1", "world")
        assert history.navigate_up("conv-1") == "world"
        assert history.navigate_up("conv-1") == "hello"

    def test_slash_history_isolated(self, history):
        history.push_message("conv-1", "hello")
        history.push_slash("conv-1", "/help")
        assert history.navigate_up_slash("conv-1") == "/help"
        assert history.navigate_down_slash("conv-1") == ""

    def test_per_conversation_isolation(self, history):
        history.push_message("conv-1", "msg in conv1")
        history.push_message("conv-2", "msg in conv2")
        assert history.navigate_up("conv-1") == "msg in conv1"
        assert history.navigate_up("conv-2") == "msg in conv2"
        assert history.navigate_down("conv-1") == ""

    def test_history_capped(self):
        h = InputHistory(max_per_type=3)
        for i in range(5):
            h.push_message("conv-1", f"msg-{i}")
        assert h.navigate_up("conv-1") == "msg-4"
        assert h.navigate_up("conv-1") == "msg-3"
        assert h.navigate_up("conv-1") == "msg-2"
        assert h.navigate_up("conv-1") == ""  # no older

    def test_edit_does_not_push_duplicate_consecutive(self, history):
        history.push_message("conv-1", "hello")
        history.push_message("conv-1", "hello")
        assert history.navigate_up("conv-1") == "hello"
        assert history.navigate_down("conv-1") == ""

    def test_slash_history_does_not_pollute_message_history(self, history):
        history.push_message("conv-1", "hello")
        history.push_slash("conv-1", "/sessions")
        assert history.navigate_up("conv-1") == "hello"
        assert history.navigate_down("conv-1") == ""

    def test_navigate_up_returns_current_edit_if_dirty(self, history):
        history.push_message("conv-1", "hello")
        history.push_message("conv-1", "world")
        # navigate up to "world"
        assert history.navigate_up("conv-1") == "world"
        # navigate up again to "hello"
        assert history.navigate_up("conv-1") == "hello"
        # navigate down should restore "world"
        assert history.navigate_down("conv-1") == "world"
