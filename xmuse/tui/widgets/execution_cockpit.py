from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


class ExecutionCockpit(Static):
    def __init__(self, **kwargs) -> None:
        panel = render_execution_cockpit(None)
        super().__init__(panel, **kwargs)
        self.renderable_text = panel.renderable.plain

    def load(self, vision: dict[str, Any] | None) -> None:
        panel = render_execution_cockpit(vision)
        self.renderable_text = panel.renderable.plain
        self.update(panel)


def render_execution_cockpit(vision: dict[str, Any] | None) -> Panel:
    execution = _section(vision, "execution")
    fact_state = _text(execution.get("fact_state")) or "manual_gap"
    lines = [
        f"Proof: {_text(execution.get('proof_level')) or 'manual_gap'}",
        f"State: {fact_state}",
        f"Lanes: {_number(execution.get('lane_count'))}",
    ]
    ready = _strings(execution.get("ready_lane_ids"))
    blocked = _strings(execution.get("blocked_lane_ids"))
    if ready:
        lines.append(f"Ready: {_compact(ready)}")
    if blocked:
        lines.append(f"Blocked: {_compact(blocked)}")
    deps = _dicts(execution.get("dependency_edges"))
    if deps:
        lines.append("Dependencies:")
        lines.extend(f"  {_dep_line(dep)}" for dep in deps[:4])
    blockers = _dicts(execution.get("blockers"))
    if blockers:
        lines.append("Blockers:")
        lines.extend(f"  {_blocker_line(blocker)}" for blocker in blockers[:4])
    review_items = _dicts(execution.get("review_items"))
    if review_items:
        lines.append("Review:")
        lines.extend(f"  {_review_line(item)}" for item in review_items[:4])
    patch_lineage = _dicts(execution.get("patch_forward_lineage"))
    if patch_lineage:
        lines.append("Patch-forward:")
        lines.extend(f"  {_patch_forward_line(item)}" for item in patch_lineage[:4])
    _append_refs(lines, "Targets", execution.get("target_refs"))
    _append_refs(lines, "Sources", execution.get("source_refs"))
    gap = _text(execution.get("manual_gap_reason"))
    if gap:
        lines.append(f"Gap: {gap}")
    return Panel(
        Text("\n".join(lines), overflow="fold", no_wrap=False),
        title="[bold]Execution Cockpit[/bold]",
        border_style="#bf616a" if fact_state == "blocked" else "#88c0d0",
        padding=(0, 1),
    )


def _section(vision: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if isinstance(vision, dict) and isinstance(vision.get(key), dict):
        return vision[key]
    return {
        "proof_level": "manual_gap",
        "fact_state": "manual_gap",
        "lane_count": 0,
        "manual_gap_reason": "execution evidence unavailable",
    }


def _dep_line(dep: dict[str, Any]) -> str:
    lane_id = _text(dep.get("lane_id")) or "lane"
    depends_on = _strings(dep.get("depends_on"))
    return f"{lane_id} <- {_compact(depends_on)}" if depends_on else lane_id


def _blocker_line(blocker: dict[str, Any]) -> str:
    lane_id = _text(blocker.get("lane_id")) or "lane"
    reason = _text(blocker.get("reason")) or "blocked"
    return f"{lane_id}: {reason}"


def _review_line(item: dict[str, Any]) -> str:
    lane_id = _text(item.get("lane_id")) or "lane"
    decision = _text(item.get("decision")) or "observed"
    summary = _text(item.get("summary"))
    verdict_id = _text(item.get("verdict_id"))
    suffix = f" [{verdict_id}]" if verdict_id is not None else ""
    return (
        f"{lane_id} {decision}: {summary}{suffix}"
        if summary
        else f"{lane_id} {decision}{suffix}"
    )


def _patch_forward_line(item: dict[str, Any]) -> str:
    source = _text(item.get("source_lane_id")) or "source"
    patch = _text(item.get("patch_lane_id")) or "patch"
    return f"{source} -> {patch}"


def _append_refs(lines: list[str], label: str, value: Any) -> None:
    refs = _strings(value)
    if refs:
        lines.append(f"{label}: {_compact(refs)}")


def _compact(values: list[str]) -> str:
    visible = values[:3]
    suffix = f" +{len(values) - 3}" if len(values) > 3 else ""
    return ", ".join(visible) + suffix


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


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
