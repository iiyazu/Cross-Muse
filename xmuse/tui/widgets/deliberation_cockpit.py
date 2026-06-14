from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


class DeliberationCockpit(Static):
    def __init__(self, **kwargs) -> None:
        panel = render_deliberation_cockpit(None)
        super().__init__(panel, **kwargs)
        self.renderable_text = panel.renderable.plain

    def load(self, vision: dict[str, Any] | None) -> None:
        panel = render_deliberation_cockpit(vision)
        self.renderable_text = panel.renderable.plain
        self.update(panel)


def render_deliberation_cockpit(vision: dict[str, Any] | None) -> Panel:
    deliberation = _deliberation(vision)
    proof_level = _text(deliberation.get("proof_level")) or "manual_gap"
    fact_state = _text(deliberation.get("fact_state")) or "manual_gap"
    lines = [
        f"Proof: {proof_level}",
        f"State: {fact_state}",
        f"Speech acts: {_format_counts(deliberation.get('speech_act_counts'))}",
    ]
    blockers = _dicts(deliberation.get("blockers"))
    if blockers:
        lines.append("Blockers:")
        for blocker in blockers[:4]:
            lines.append(
                "  "
                + _format_blocker(blocker)
            )
    else:
        lines.append("Blockers: none")

    target_refs = _strings(deliberation.get("target_refs"))
    source_refs = _strings(deliberation.get("source_refs"))
    if target_refs:
        lines.append(f"Targets: {_compact_refs(target_refs)}")
    if source_refs:
        lines.append(f"Sources: {_compact_refs(source_refs)}")
    manual_gap_reason = _text(deliberation.get("manual_gap_reason"))
    if manual_gap_reason:
        lines.append(f"No deliberation evidence: {manual_gap_reason}")

    border_style = "#bf616a" if fact_state == "blocked" else "#88c0d0"
    if proof_level == "manual_gap":
        border_style = "#616e88"
    return Panel(
        Text("\n".join(lines), overflow="fold", no_wrap=False),
        title="[bold]Deliberation Cockpit[/bold]",
        border_style=border_style,
        padding=(0, 1),
    )


def _deliberation(vision: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(vision, dict):
        return {
            "proof_level": "manual_gap",
            "fact_state": "manual_gap",
            "speech_act_counts": {},
            "blockers": [],
            "target_refs": [],
            "source_refs": [],
            "manual_gap_reason": "No deliberation evidence",
        }
    deliberation = vision.get("deliberation")
    return deliberation if isinstance(deliberation, dict) else _deliberation(None)


def _format_counts(value: Any) -> str:
    if not isinstance(value, dict) or not value:
        return "none"
    parts = [
        f"{key}: {value[key]}"
        for key in sorted(value)
        if isinstance(key, str)
    ]
    return ", ".join(parts) if parts else "none"


def _format_blocker(blocker: dict[str, Any]) -> str:
    speech_act = _text(blocker.get("speech_act")) or "blocker"
    message_id = _text(blocker.get("message_id"))
    reason = _text(blocker.get("reason")) or "unresolved"
    target_refs = _strings(blocker.get("target_refs"))
    label = f"{speech_act}"
    if message_id:
        label += f" {message_id}"
    if target_refs:
        label += f" -> {_compact_refs(target_refs)}"
    return f"{label}: {reason}"


def _compact_refs(refs: list[str]) -> str:
    visible = refs[:3]
    suffix = f" +{len(refs) - 3}" if len(refs) > 3 else ""
    return ", ".join(visible) + suffix


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
