# xmuse/tui/screens/provider_board.py
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Static


class ProviderOverviewStatic(Static):
    def __init__(self, renderable="", **kwargs) -> None:
        self.renderable = renderable
        super().__init__(renderable, **kwargs)

    def update(self, renderable="") -> None:
        self.renderable = renderable
        super().update(renderable)


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
        yield ProviderOverviewStatic("GOD Runtime Overview", id="provider-header")
        yield ProviderOverviewStatic(id="provider-table")

    def on_mount(self) -> None:
        inventory = self.app.adapter.get_provider_inventory()
        if not inventory:
            self.query_one("#provider-table", ProviderOverviewStatic).update(
                Text(
                    "[dim]Provider runtime evidence unavailable — "
                    "manual_gap until inventory or runtime rows land[/dim]"
                )
            )
            return
        rows = [
            "Provider | Boundary | Profile | Runtime | Transport | Session | "
            "Heartbeat | Waiting | Proof",
            "-" * 86,
        ]
        for item in inventory:
            rows.append(
                " | ".join(
                    [
                        _value(item, "provider_id"),
                        _value(item, "boundary_role"),
                        _value(item, "profile_id"),
                        _value(item, "runtime_kind", "runtime"),
                        _value(item, "transport"),
                        _value(item, "session_continuity", "provider_binding_status"),
                        _value(item, "heartbeat"),
                        _value(item, "waiting_reason"),
                        _value(item, "proof_level"),
                    ]
                )
            )
        self.query_one("#provider-table", ProviderOverviewStatic).update(
            Text("\n".join(rows))
        )


def _value(item: dict, *keys: str) -> str:
    for key in keys:
        value = item.get(key)
        if isinstance(value, list):
            return ",".join(str(part) for part in value)
        if value is not None and value != "":
            return str(value)
    return "manual_gap"
