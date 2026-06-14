from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


class GitHubTruthPanel(Static):
    def __init__(self, **kwargs) -> None:
        panel = render_github_truth_panel(None)
        super().__init__(panel, **kwargs)
        self.renderable_text = panel.renderable.plain

    def load(self, vision: dict[str, Any] | None) -> None:
        panel = render_github_truth_panel(vision)
        self.renderable_text = panel.renderable.plain
        self.update(panel)


def render_github_truth_panel(vision: dict[str, Any] | None) -> Panel:
    github = _section(vision, "github")
    fact_state = _text(github.get("fact_state")) or "manual_gap"
    lines = [
        f"Proof: {_text(github.get('proof_level')) or 'manual_gap'}",
        f"State: {fact_state}",
        f"Can emit merge fact: {_yes_no(github.get('can_emit_pr_merged'))}",
    ]
    required_checks = github.get("required_checks")
    if isinstance(required_checks, dict) and required_checks:
        lines.append(f"Checks: {_format_mapping(required_checks)}")
    review_truth = github.get("review_truth")
    if isinstance(review_truth, dict) and review_truth:
        lines.append(f"Review: {_format_mapping(review_truth)}")
    merge = github.get("merge")
    if isinstance(merge, dict) and merge:
        lines.append(f"Merge: {_format_mapping(merge)}")
    blockers = _dicts(github.get("blockers"))
    if blockers:
        lines.append("Blockers:")
        lines.extend(f"  {_blocker_line(blocker)}" for blocker in blockers[:4])
    _append_refs(lines, "Sources", github.get("source_refs"))
    gap = _text(github.get("manual_gap_reason"))
    if gap:
        lines.append(f"Gap: {gap}")
    return Panel(
        Text("\n".join(lines), overflow="fold", no_wrap=False),
        title="[bold]GitHub Truth[/bold]",
        border_style=_style(fact_state),
        padding=(0, 1),
    )


def _section(vision: dict[str, Any] | None, key: str) -> dict[str, Any]:
    if isinstance(vision, dict) and isinstance(vision.get(key), dict):
        return vision[key]
    return {
        "proof_level": "manual_gap",
        "fact_state": "manual_gap",
        "manual_gap_reason": "GitHub truth unavailable",
        "can_emit_pr_merged": False,
    }


def _format_mapping(value: dict[str, Any]) -> str:
    parts = []
    for key in sorted(value):
        item = value[key]
        if isinstance(item, list):
            rendered = ",".join(str(part) for part in item)
        else:
            rendered = str(item)
        parts.append(f"{key}={rendered}")
    return "; ".join(parts)


def _blocker_line(blocker: dict[str, Any]) -> str:
    kind = _text(blocker.get("kind")) or "blocker"
    reason = _text(blocker.get("reason")) or "blocked"
    return f"{kind}: {reason}"


def _append_refs(lines: list[str], label: str, value: Any) -> None:
    refs = _strings(value)
    if refs:
        lines.append(f"{label}: {_compact(refs)}")


def _compact(values: list[str]) -> str:
    visible = values[:3]
    suffix = f" +{len(values) - 3}" if len(values) > 3 else ""
    return ", ".join(visible) + suffix


def _style(fact_state: str) -> str:
    if fact_state == "manual_gap":
        return "#616e88"
    if fact_state == "pr_merged":
        return "#a3be8c"
    if fact_state in {"blocked", "merge_ready"}:
        return "#ebcb8b"
    return "#88c0d0"


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
