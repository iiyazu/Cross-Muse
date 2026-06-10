# xmuse/tui/screens/system_screen.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Label


class SystemPlaceholder(Widget):
    def compose(self) -> ComposeResult:
        yield Label(
            "\n\n"
            "  System Monitoring\n\n"
            "  \u23f3 LangGraph runtime adapter  \u2014 planned for R1\n"
            "  \u23f3 Ray actor backend          \u2014 planned for R2\n"
            "  \u23f3 Rollout gates              \u2014 planned for R3\n",
            id="system-label",
        )
