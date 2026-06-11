from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


class MemoryTraceDrawer(Static):
    def __init__(self, **kwargs) -> None:
        panel = render_memory_trace_drawer(None)
        super().__init__(panel, **kwargs)
        self.renderable_text = panel.renderable.plain

    def load(self, vision: dict[str, Any] | None) -> None:
        panel = render_memory_trace_drawer(vision)
        self.renderable_text = panel.renderable.plain
        self.update(panel)


def render_memory_trace_drawer(vision: dict[str, Any] | None) -> Panel:
    memory = _section(vision, "memory")
    fact_state = _text(memory.get("fact_state")) or "manual_gap"
    lines = [
        f"Proof: {_text(memory.get('proof_level')) or 'manual_gap'}",
        f"State: {fact_state}",
        f"Session: {_text(memory.get('session_id')) or 'none'}",
        f"Trace events: {_number(memory.get('trace_events_count'))}",
        f"Pinned core: {_number(memory.get('pinned_core_count'))}",
        f"Active task pages: {_number(memory.get('active_task_pages_count'))}",
        f"Recent messages: {_number(memory.get('recent_messages_count'))}",
        f"Retrieved pages: {_number(memory.get('retrieved_pages_count'))}",
        f"Dropped pages: {_number(memory.get('dropped_pages_count'))}",
        f"Tokens: {_number(memory.get('token_estimate'))}",
    ]
    namespace = memory.get("namespace")
    if isinstance(namespace, dict) and namespace:
        lines.append(f"Namespace: {_format_mapping(namespace)}")
    _append_refs(lines, "Targets", memory.get("target_refs"))
    _append_refs(lines, "Sources", memory.get("source_refs"))
    gap = _text(memory.get("manual_gap_reason"))
    if gap:
        lines.append(f"Gap: {gap}")
    return Panel(
        Text("\n".join(lines), overflow="fold", no_wrap=False),
        title="[bold]Memory Trace[/bold]",
        border_style="#a3be8c" if fact_state == "observed" else "#616e88",
        padding=(0, 1),
    )


def _section(vision: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if isinstance(vision, dict) and isinstance(vision.get(key), dict):
        return vision[key]
    return {
        "proof_level": "manual_gap",
        "fact_state": "manual_gap",
        "manual_gap_reason": "memory trace unavailable",
    }


def _append_refs(lines: list[str], label: str, value: Any) -> None:
    refs = _strings(value)
    if refs:
        lines.append(f"{label}: {_compact(refs)}")


def _compact(values: list[str]) -> str:
    visible = values[:3]
    suffix = f" +{len(values) - 3}" if len(values) > 3 else ""
    return ", ".join(visible) + suffix


def _format_mapping(value: dict[str, Any]) -> str:
    parts = []
    for key in sorted(value):
        item = value[key]
        if item is None:
            continue
        parts.append(f"{key}={item}")
    return "; ".join(parts) or "none"


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _number(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
