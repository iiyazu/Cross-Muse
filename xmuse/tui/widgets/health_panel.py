# xmuse/tui/widgets/health_panel.py
from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static


class HealthPanel(Static):
    def show_health(self, health: dict | None) -> None:
        if not health:
            super().update(Text("No run health data", style="dim"))
            return
        t = Table(box=None, expand=True)
        t.add_column("Status", style="bold")
        t.add_column("Count", style="#ebcb8b")
        t.add_row("Live", str(health.get("live", 0)))
        t.add_row("Merged", str(health.get("merged", 0)))
        t.add_row("Failed", str(health.get("failed", 0)))
        t.add_row("Total", str(health.get("total", 0)))
        super().update(t)
