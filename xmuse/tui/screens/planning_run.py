# xmuse/tui/screens/planning_run.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static


class PlanningRunScreen(Screen):
    CSS = """
    #run-header {
        height: auto;
        padding: 1;
        background: $boost;
        color: $primary;
    }
    #run-content {
        height: 1fr;
        margin: 1;
    }
    """

    def __init__(self, run_id: str = "") -> None:
        super().__init__()
        self.run_id = run_id

    def compose(self) -> ComposeResult:
        yield Label(f"Planning Run: {self.run_id}", id="run-header")
        yield Static(id="run-content", disabled=True)
        yield Label("[dim]PlanningRun store not yet wired[/dim]", id="run-notice")
