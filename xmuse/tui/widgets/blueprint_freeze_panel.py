from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


class BlueprintFreezePanel(Static):
    def __init__(self, **kwargs) -> None:
        panel = render_blueprint_freeze_panel(None)
        super().__init__(panel, **kwargs)
        self.renderable_text = panel.renderable.plain

    def load(self, vision: dict[str, Any] | None) -> None:
        panel = render_blueprint_freeze_panel(vision)
        self.renderable_text = panel.renderable.plain
        self.update(panel)


def render_blueprint_freeze_panel(vision: dict[str, Any] | None) -> Panel:
    freeze = _section(vision, "blueprint_freeze")
    fact_state = _text(freeze.get("fact_state")) or "manual_gap"
    lines = [
        f"Proof: {_text(freeze.get('proof_level')) or 'manual_gap'}",
        f"State: {fact_state}",
        f"Ready: {_yes_no(freeze.get('ready_to_freeze'))}",
        f"Frozen: {_yes_no(freeze.get('frozen'))}",
    ]
    blockers = _dicts(freeze.get("blockers"))
    if blockers:
        lines.append("Blockers:")
        lines.extend(f"  {_blocker_line(blocker)}" for blocker in blockers[:4])
    else:
        lines.append("Blockers: none")
    _append_refs(lines, "Targets", freeze.get("target_refs"))
    _append_refs(lines, "Sources", freeze.get("source_refs"))
    gap = _text(freeze.get("manual_gap_reason"))
    if gap:
        lines.append(f"Gap: {gap}")
    return Panel(
        Text("\n".join(lines), overflow="fold", no_wrap=False),
        title="[bold]Blueprint Freeze[/bold]",
        border_style=_style(fact_state),
        padding=(0, 1),
    )


def _section(vision: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if isinstance(vision, dict) and isinstance(vision.get(key), dict):
        return vision[key]
    return {
        "proof_level": "manual_gap",
        "fact_state": "manual_gap",
        "manual_gap_reason": "blueprint freeze evidence unavailable",
    }


def _blocker_line(blocker: dict[str, Any]) -> str:
    return _text(blocker.get("reason")) or _text(blocker.get("message_id")) or "blocked"


def _append_refs(lines: list[str], label: str, value: Any) -> None:
    refs = _strings(value)
    if refs:
        lines.append(f"{label}: {_compact(refs)}")


def _compact(values: list[str]) -> str:
    visible = values[:3]
    suffix = f" +{len(values) - 3}" if len(values) > 3 else ""
    return ", ".join(visible) + suffix


def _style(fact_state: str) -> str:
    if fact_state == "blocked":
        return "#bf616a"
    if fact_state == "frozen":
        return "#a3be8c"
    if fact_state == "ready_to_freeze":
        return "#ebcb8b"
    return "#616e88"


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value else []
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _yes_no(value: Any) -> str:
    return "yes" if value is True else "no"
