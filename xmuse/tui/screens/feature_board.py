# xmuse/tui/screens/feature_board.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import TabbedContent, TabPane

from xmuse.tui.screens.feature_detail import FeatureDetailScreen
from xmuse.tui.screens.system_screen import SystemPlaceholder
from xmuse.tui.state import StateUpdated
from xmuse.tui.widgets.feature_row import FeatureClicked, FeatureTable
from xmuse.tui.widgets.health_panel import HealthPanel
from xmuse.tui.widgets.xmu_header import XmuHeader


class FeatureBoardScreen(Screen):
    CSS = """
    FeatureTable {
        height: 1fr;
    }
    HealthPanel {
        height: auto;
        margin: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield XmuHeader(id="header")
        with TabbedContent("Features", "System"):
            with TabPane("Features"):
                yield FeatureTable(id="feature-table")
                yield HealthPanel(id="board-health")
            with TabPane("System"):
                yield SystemPlaceholder(id="system-pane")

    def on_state_updated(self, event: StateUpdated) -> None:
        self.query_one(XmuHeader).load(event.state)
        if not event.state.lanes_changed and not event.state.has_errors:
            return
        features = event.state.all_features()
        self.query_one("#feature-table", FeatureTable).update_data(features)
        self.query_one("#board-health", HealthPanel).show_health(
            event.state.run_health or {}
        )

    def on_feature_clicked(self, event: FeatureClicked) -> None:
        screen = FeatureDetailScreen(graph_id=event.feature_id)
        self.app.push_screen(screen)
