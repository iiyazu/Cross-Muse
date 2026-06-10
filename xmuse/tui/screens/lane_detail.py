# xmuse/tui/screens/lane_detail.py
from __future__ import annotations

from rich.text import Text
from textual.app import ComposeResult
from textual.screen import Screen
from textual.widgets import Label, Static


class LaneContentPanel(Static):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.renderable = ""

    def update(self, renderable="") -> None:
        self.renderable = renderable
        super().update(renderable)


class LaneDetailScreen(Screen):
    CSS = """
    #lane-header {
        height: auto;
        padding: 1;
        background: $boost;
        color: $primary;
    }
    #lane-content {
        height: 1fr;
        margin: 1;
    }
    """

    def __init__(self, lane_id: str = "") -> None:
        super().__init__()
        self.lane_id = lane_id

    def compose(self) -> ComposeResult:
        yield Label(f"Lane: {self.lane_id}", id="lane-header")
        yield LaneContentPanel(id="lane-content")

    def on_mount(self) -> None:
        conversation_id = getattr(self.app.state, "active_conversation_id", None)
        payload = self.app.adapter.get_workbench_lane_detail(conversation_id, self.lane_id)
        task = payload.get("task") if isinstance(payload, dict) else None
        if not isinstance(task, dict):
            self.query_one("#lane-content", LaneContentPanel).update("[red]Lane not found[/red]")
            return
        lines = [
            str(task.get("feature_label") or task.get("lane_id") or self.lane_id),
            f"Status: {task.get('effective_status', task.get('status', '?'))}",
            f"Source: {payload.get('source_authority', 'tui_worklist_envelope')}",
            f"Feature: {task.get('plan_feature_id', '?')}",
            f"Priority: {task.get('priority', 0)}",
            "",
            "--- Prompt Summary ---",
            str(task.get("prompt_summary") or "")[:500],
        ]
        execution_log = payload.get("execution_log")
        if isinstance(execution_log, dict) and isinstance(execution_log.get("events"), list):
            lines.extend(["", "--- Execution Log ---"])
            for event in execution_log["events"]:
                if not isinstance(event, dict):
                    continue
                summary = str(event.get("summary") or "").strip()
                title = str(event.get("title") or event.get("event_type") or "").strip()
                status = str(event.get("status") or "").strip()
                lines.append(" ".join(part for part in (title, status, summary) if part))
        self.query_one("#lane-content", LaneContentPanel).update(Text("\n".join(lines)))
