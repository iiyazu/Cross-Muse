from __future__ import annotations

from typing import Any

from rich.panel import Panel
from rich.text import Text
from textual.widgets import Static


class ProofCockpit(Static):
    def __init__(self, **kwargs) -> None:
        panel = render_proof_cockpit(None)
        super().__init__(panel, **kwargs)
        self.renderable_text = panel.renderable.plain

    def load(self, vision: dict[str, Any] | None) -> None:
        panel = render_proof_cockpit(vision)
        self.renderable_text = panel.renderable.plain
        self.update(panel)


def render_proof_cockpit(vision: dict[str, Any] | None) -> Panel:
    cockpit = _section(vision)
    fact_state = _text(cockpit.get("fact_state")) or "manual_gap"
    lines = [
        f"Proof: {_text(cockpit.get('proof_level')) or 'manual_gap'}",
        f"State: {fact_state}",
    ]
    authority = _text(cockpit.get("authority"))
    if authority is not None:
        lines.append(f"Authority: {authority}")
    replay_decision = _text(cockpit.get("replay_decision"))
    if replay_decision is not None:
        lines.append(f"Replay: {replay_decision}")
    release_decision = _text(cockpit.get("release_decision"))
    if release_decision is not None:
        lines.append(f"Release: {release_decision}")
    contamination = _text(cockpit.get("proof_contamination_decision"))
    if contamination is not None:
        lines.append(f"Proof contamination: {contamination}")
    lines.append(
        "Counts: "
        f"sections={_number(cockpit.get('section_count'))}; "
        f"artifacts={_number(cockpit.get('artifact_count'))}; "
        f"blockers={_number(cockpit.get('blocker_count'))}; "
        f"findings={_number(cockpit.get('finding_count'))}"
    )
    proof_summary = cockpit.get("proof_level_summary")
    if isinstance(proof_summary, dict) and proof_summary:
        lines.append(f"Proof summary: {_format_mapping(proof_summary)}")
    section_statuses = _dicts(cockpit.get("section_statuses"))
    if section_statuses:
        lines.append("Sections:")
        lines.extend(f"  {_section_line(section)}" for section in section_statuses[:6])
    stage_results = _dicts(cockpit.get("stage_results"))
    if stage_results:
        summary = cockpit.get("stage_result_summary")
        if isinstance(summary, dict):
            lines.append(
                "Goal stages: "
                f"ok={_number(summary.get('ok'))}; "
                f"blocked={_number(summary.get('blocked'))}; "
                f"retry={_number(summary.get('retry'))}; "
                f"manual_gap={_number(summary.get('manual_gap'))}; "
                f"total={_number(summary.get('total'))}"
            )
        lines.extend(
            f"  {_stage_result_line(stage_result)}"
            for stage_result in stage_results[:6]
        )
    _append_god_runtime(lines, vision)
    blockers = _dicts(cockpit.get("blockers"))
    if blockers:
        lines.append("Blockers:")
        lines.extend(f"  {_blocker_line(blocker)}" for blocker in blockers[:5])
    _append_refs(lines, "Artifacts", cockpit.get("artifacts"))
    _append_refs(lines, "Sources", cockpit.get("source_refs"))
    gap = _text(cockpit.get("manual_gap_reason"))
    if gap:
        lines.append(f"Gap: {gap}")
    return Panel(
        Text("\n".join(lines), overflow="fold", no_wrap=False),
        title="[bold]Proof Cockpit[/bold]",
        border_style=_style(fact_state),
        padding=(0, 1),
    )


def _section(vision: dict[str, Any] | None) -> dict[str, Any]:
    if isinstance(vision, dict) and isinstance(vision.get("proof_cockpit"), dict):
        return vision["proof_cockpit"]
    return {
        "proof_level": "manual_gap",
        "fact_state": "manual_gap",
        "manual_gap_reason": "No proof cockpit evidence",
    }


def _blocker_line(blocker: dict[str, Any]) -> str:
    kind = _text(blocker.get("kind")) or "blocker"
    identifier = _text(blocker.get("id")) or "unknown"
    reason = _text(blocker.get("reason")) or "blocked"
    return f"{kind} {identifier}: {reason}"


def _section_line(section: dict[str, Any]) -> str:
    section_id = _text(section.get("section_id")) or "unknown"
    status = _text(section.get("status")) or "not_evaluated"
    proof_level = _text(section.get("proof_level")) or "manual_gap"
    authority = _text(section.get("source_authority")) or "unknown"
    return f"{section_id} {status}/{proof_level} via {authority}"


def _stage_result_line(stage_result: dict[str, Any]) -> str:
    stage_id = _text(stage_result.get("stage_id")) or "unknown"
    status = _text(stage_result.get("status")) or "not_evaluated"
    proof_level = _text(stage_result.get("proof_level")) or "manual_gap"
    authority = _text(stage_result.get("source_authority")) or "goal_stage_harness"
    engine = _text(stage_result.get("engine")) or "unknown"
    line = f"{stage_id} {status}/{proof_level} via {authority} ({engine})"
    reason = _text(stage_result.get("blocked_reason"))
    if reason is not None:
        line += f": {reason}"
    next_stage_id = _text(stage_result.get("next_stage_id"))
    if next_stage_id is not None:
        line += f" -> {next_stage_id}"
    return line


def _append_god_runtime(
    lines: list[str],
    vision: dict[str, Any] | None,
) -> None:
    if not isinstance(vision, dict):
        return
    runtime = vision.get("god_runtime")
    if not isinstance(runtime, dict):
        return
    items = _dicts(runtime.get("items"))
    if not items:
        return
    ready = sum(1 for item in items if item.get("peer_god_ready") is True)
    bounded = sum(1 for item in items if item.get("bounded") is True)
    blocked = sum(1 for item in items if _god_waiting_reason(item) is not None)
    lines.append(
        "GOD runtime: "
        f"ready={ready}; bounded={bounded}; blocked={blocked}; total={len(items)}"
    )
    for item in items[:4]:
        lines.append(f"  {_god_runtime_line(item)}")


def _god_runtime_line(item: dict[str, Any]) -> str:
    god_id = _text(item.get("god_id")) or "unknown"
    cli_id = _text(item.get("cli_id")) or "unknown"
    if item.get("peer_god_ready") is True:
        state = "ready"
    elif item.get("bounded") is True:
        state = "bounded"
    elif _god_waiting_reason(item) is not None:
        state = "blocked"
    else:
        state = "waiting"
    proof_level = _text(item.get("proof_level")) or "manual_gap"
    line = f"{god_id} {cli_id} {state} {proof_level}"
    heartbeat_freshness = _text(item.get("heartbeat_freshness"))
    if heartbeat_freshness is not None:
        line += f" heartbeat={heartbeat_freshness}"
    reason = _god_waiting_reason(item)
    if reason is not None:
        line += f": {reason}"
    return line


def _god_waiting_reason(item: dict[str, Any]) -> str | None:
    reason = _text(item.get("waiting_reason"))
    if reason is not None:
        return reason
    if item.get("provider_session_ready") is False:
        return "provider session metadata unavailable"
    return None


def _append_refs(lines: list[str], label: str, value: Any) -> None:
    refs = _strings(value)
    if refs:
        lines.append(f"{label}: {_compact(refs)}")


def _compact(values: list[str]) -> str:
    visible = values[:3]
    suffix = f" +{len(values) - 3}" if len(values) > 3 else ""
    return ", ".join(visible) + suffix


def _format_mapping(value: dict[Any, Any]) -> str:
    parts = []
    for key in sorted(value):
        item = value[key]
        parts.append(f"{key}={item}")
    return "; ".join(parts)


def _style(fact_state: str) -> str:
    if fact_state == "manual_gap":
        return "#616e88"
    if fact_state == "blocked":
        return "#ebcb8b"
    if fact_state == "ready":
        return "#a3be8c"
    return "#88c0d0"


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
