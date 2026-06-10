from __future__ import annotations

from rich.text import Text
from textual.widgets import Static


class LoadingIndicator(Static):
    def on_mount(self) -> None:
        self.update(Text("[dim]Loading...[/dim]"))


class EmptyIndicator(Static):
    def __init__(self, message: str = "No data") -> None:
        super().__init__()
        self._msg = message

    def on_mount(self) -> None:
        self.update(Text(f"[dim]{self._msg}[/dim]"))


class ErrorIndicator(Static):
    def __init__(self, error: str = "") -> None:
        super().__init__()
        self._error = error

    def on_mount(self) -> None:
        self.update(Text(f"[#bf616a]\u2717 {self._error}[/#bf616a]"))
