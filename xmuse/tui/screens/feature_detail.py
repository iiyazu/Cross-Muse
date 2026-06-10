# xmuse/tui/screens/feature_detail.py
from __future__ import annotations

from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label

from xmuse.tui.widgets.dag_tree import DagTree


class FeatureDetailScreen(Screen):
    CSS = """
    #detail-header {
        height: auto;
        padding: 1;
        background: $boost;
        color: $primary;
    }
    DagTree {
        height: 1fr;
    }
    """

    def __init__(self, graph_id: str = "") -> None:
        super().__init__()
        self.graph_id = graph_id

    def compose(self) -> ComposeResult:
        yield Label(f"Feature Graph: {self.graph_id}", id="detail-header")
        yield DagTree(id="dag-view")

    def on_mount(self) -> None:
        graph = self.app.adapter.get_feature_graph(self.graph_id)
        if graph:
            self.query_one("#dag-view", DagTree).load_graph(graph)
        else:
            self.query_one("#dag-view", DagTree).update(
                "[dim]Graph not found[/dim]"
            )
