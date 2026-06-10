# xmuse/tui/screens/provider_board.py
from __future__ import annotations

from rich import box
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static


class ProviderBoardScreen(Screen):
    CSS = """
    #provider-header {
        height: auto;
        padding: 1;
        background: $boost;
        color: $primary;
    }
    #provider-table {
        height: 1fr;
        margin: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Label("Provider Inventory", id="provider-header")
        yield Static(id="provider-table")

    def on_mount(self) -> None:
        inventory = self.app.adapter.get_provider_inventory()
        if not inventory:
            self.query_one("#provider-table", Static).update(
                Text("[dim]Provider store not available — waiting for C0a/C0b to land[/dim]")
            )
            return
        t = Table(box=box.ROUNDED)
        t.add_column("Provider", style="#88c0d0")
        t.add_column("Profile", style="#a3be8c")
        t.add_column("Capability", style="#ebcb8b")
        for item in inventory:
            t.add_row(
                item.get("provider_id", "?"),
                item.get("profile_id", "?"),
                ", ".join(item.get("capabilities", [])),
            )
        self.query_one("#provider-table", Static).update(t)
