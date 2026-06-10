# xmuse/tui/widgets/dag_tree.py
from __future__ import annotations

from rich.text import Text
from rich.tree import Tree
from textual.widgets import Static


def topological_sort(lanes: list[dict]) -> list[list[dict]]:
    ids = {
        lane.get("lane_local_id") or lane.get("feature_id", ""): lane
        for lane in lanes
    }
    deps = {k: list(set(v.get("lane_depends_on_ids") or [])) for k, v in ids.items()}
    layers: list[list[dict]] = []
    remaining = set(ids.keys())
    while remaining:
        current = {n for n in remaining if not any(d in remaining for d in deps.get(n, []))}
        if not current:
            break
        layers.append([ids[n] for n in sorted(current)])
        remaining -= current
    return layers


class DagTree(Static):
    def load_graph(self, graph: dict) -> None:
        lanes = graph.get("lanes", [])
        if not lanes:
            super().update(Text("No lanes in this graph", style="dim"))
            return
        tree = Tree(f"[bold]{graph.get('id', '?')}[/bold] (v{graph.get('version', '?')})")
        layers = topological_sort(lanes)
        for i, layer in enumerate(layers):
            branch = tree.add(f"[bold #88c0d0]Layer {i}[/bold #88c0d0]")
            for lane in layer:
                status = lane.get("status", "?")
                lane_id = lane.get("lane_local_id", "?")
                label = (
                    f"[#a3be8c]●[/#a3be8c] {lane_id} "
                    f"[dim #616e88]({status})[/dim #616e88]"
                )
                leaf = branch.add(label)
                deps = lane.get("lane_depends_on_ids") or []
                if deps:
                    leaf.add(f"[dim #616e88]depends: {', '.join(deps)}[/dim #616e88]")
        super().update(tree)
