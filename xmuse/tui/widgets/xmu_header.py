# xmuse/tui/widgets/xmu_header.py
from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from xmuse.tui.state import AppState


class XmuHeader(Static):
    """Header bar showing app name, conversation, and run health."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._connection_style = "idle"

    DEFAULT_CSS = """
    XmuHeader {
        dock: top;
        height: 1;
        background: $boost;
        color: $text;
    }
    """

    def load(self, state: AppState) -> None:
        conv_id = state.active_conversation_id or ""
        conv_title = conv_id[:40] if conv_id else "(no conversation)"
        counts = _run_health_counts(state.run_health)
        live = counts.get("live", 0)
        failed = counts.get("failed", 0)
        self._connection_style = _connection_style_for(state)
        conn_symbol, conn_color = _connection_visuals(self._connection_style)
        t = Text.assemble(
            (" xmuse ", "bold #88c0d0"),
            ("│", "#4c566a"),
            (f" {conv_title} ", "#eceff4"),
            ("│", "#4c566a"),
            (conn_symbol, conn_color),
            (f"{live} live", "#a3be8c" if live > 0 else "#616e88"),
            (" │ ", "#4c566a"),
            (" ● ", "#bf616a"),
            (f"{failed} failed", "#bf616a"),
            (" │ ", "#4c566a"),
            (f" {conv_id[:20]} ", "#616e88"),
        )
        self.update(t)


def _run_health_counts(run_health: dict | None) -> dict:
    if not run_health:
        return {}
    counts = run_health.get("counts")
    if isinstance(counts, dict):
        return counts
    return run_health


def _connection_style_for(state: AppState) -> str:
    if state.has_errors:
        return "degraded"
    counts = _run_health_counts(state.run_health)
    if counts.get("degraded_fallback", 0) > 0:
        return "degraded"
    if counts.get("stale", 0) > 0:
        return "degraded"
    if counts.get("live", 0) > 0:
        return "connected"
    return "idle"


def _connection_visuals(style: str) -> tuple[str, str]:
    return {
        "degraded": (" ◆ ", "#d08770"),
        "connected": (" ● ", "#a3be8c"),
        "idle": (" ◇ ", "#616e88"),
    }.get(style, (" ◇ ", "#616e88"))
