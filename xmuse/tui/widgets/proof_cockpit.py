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
    _append_virtual_soak(lines, cockpit)
    section_statuses = _dicts(cockpit.get("section_statuses"))
    if section_statuses:
        lines.append("Sections:")
        lines.extend(f"  {_section_line(section)}" for section in section_statuses[:6])
    _append_github_truth(lines, cockpit)
    _append_deliberation_transcript(lines, cockpit)
    _append_memory_governance(lines, cockpit)
    _append_feature_lineage(lines, cockpit)
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
    recovery_queue = _dicts(cockpit.get("recovery_queue"))
    if recovery_queue:
        lines.append("Recovery queue:")
        lines.extend(f"  {_recovery_line(item)}" for item in recovery_queue[:5])
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
    line = f"{kind} {identifier}: {reason}"
    next_action = _text(blocker.get("next_action"))
    if next_action is not None:
        line += f" next={next_action}"
    return line


def _recovery_line(item: dict[str, Any]) -> str:
    source = _text(item.get("source")) or "release_evidence_pack"
    kind = _text(item.get("kind")) or "recovery_item"
    identifier = _text(item.get("id")) or "unknown"
    reason = _text(item.get("reason")) or "blocked"
    line = f"{source} {kind} {identifier}: {reason}"
    next_action = _text(item.get("next_action"))
    if next_action is not None:
        line += f" next={next_action}"
    artifact = _text(item.get("artifact"))
    if artifact is not None:
        line += f" artifact={artifact}"
    return line


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


def _append_github_truth(lines: list[str], cockpit: dict[str, Any]) -> None:
    github_truth = cockpit.get("github_truth")
    if not isinstance(github_truth, dict):
        return
    repo = _text(github_truth.get("repo")) or "unknown"
    pull_request_number = _number(github_truth.get("pull_request_number"))
    target = f"{repo}#{pull_request_number}" if pull_request_number else repo
    proof_level = _text(github_truth.get("proof_level")) or "manual_gap"
    head_sha = _text(github_truth.get("head_sha")) or "-"
    expected_head_sha = _text(github_truth.get("expected_head_sha")) or "-"
    lines.append(
        "GitHub truth: "
        f"{target} {proof_level} head={head_sha} "
        f"expected={expected_head_sha} "
        f"match={_yes_no(github_truth.get('head_sha_matches_expected'))}"
    )
    lines.append(
        "  "
        f"checks={_number(github_truth.get('required_check_count'))}; "
        f"check_runs={_number(github_truth.get('check_run_count'))}; "
        f"app={_text(github_truth.get('expected_source_app')) or '-'}; "
        f"enforcement={_text(github_truth.get('server_enforcement')) or 'missing'}"
    )
    lines.append(
        "  "
        f"review={_text(github_truth.get('review_truth')) or 'missing'}; "
        f"merge={_text(github_truth.get('merge_truth')) or 'missing'}; "
        f"can_emit_pr_merged={_yes_no(github_truth.get('can_emit_pr_merged'))}; "
        f"merged={_yes_no(github_truth.get('merged'))}"
    )
    workflow_run_id = _text(github_truth.get("workflow_run_id"))
    capture_mode = _text(github_truth.get("capture_mode"))
    if workflow_run_id is not None or capture_mode is not None:
        lines.append(
            "  "
            f"workflow={workflow_run_id or '-'}; "
            f"capture={capture_mode or '-'}"
        )
    gap_reason = _text(github_truth.get("gap_reason"))
    if gap_reason is not None:
        lines.append(f"  gap={gap_reason}")


def _append_deliberation_transcript(
    lines: list[str],
    cockpit: dict[str, Any],
) -> None:
    transcript = cockpit.get("deliberation_transcript")
    if not isinstance(transcript, dict):
        return
    conversation_id = _text(transcript.get("conversation_id")) or "unknown"
    lines.append(
        "Deliberation transcript: "
        f"{conversation_id} "
        f"messages={_number(transcript.get('message_count'))}; "
        f"gods={_number(transcript.get('distinct_god_count'))}; "
        f"natural={_yes_no(transcript.get('natural_deliberation'))}; "
        f"real_provider={_yes_no(transcript.get('real_provider_proof'))}"
    )
    lines.append(
        "  "
        f"runtime_required={_yes_no(transcript.get('runtime_required'))}; "
        f"runtime_artifact={_yes_no(transcript.get('runtime_artifact_attached'))}; "
        "runtime_ready="
        f"{_number(transcript.get('runtime_peer_god_ready_count'))}; "
        f"runtime_blocked={_number(transcript.get('runtime_blocked_count'))}"
    )
    speech_acts = transcript.get("speech_act_counts")
    if isinstance(speech_acts, dict) and speech_acts:
        lines.append(f"  acts={_format_mapping(speech_acts)}")
    missing = _strings(transcript.get("missing_provider_session_god_ids"))
    if missing:
        lines.append(f"  missing_sessions={_compact(missing)}")
    blocker_count = _number(transcript.get("blocker_count"))
    if blocker_count:
        lines.append(f"  blockers={blocker_count}")


def _append_memory_governance(lines: list[str], cockpit: dict[str, Any]) -> None:
    governance = cockpit.get("memory_governance")
    if not isinstance(governance, dict):
        return
    lines.append(
        "Memory governance: "
        f"plans={_number(governance.get('plan_count'))}; "
        f"ingest={_number(governance.get('ingest_count'))}; "
        f"promote={_number(governance.get('promote_to_shared_count'))}; "
        "provider_binding="
        f"{_number(governance.get('provider_session_binding_only_count'))}; "
        f"blocked={_number(governance.get('blocked_count'))}; "
        f"live_trace={_yes_no(governance.get('live_trace_proof'))}"
    )
    for plan in _dicts(governance.get("plans"))[:4]:
        lines.append(f"  {_memory_governance_plan_line(plan)}")
        blocked_reason = _text(plan.get("blocked_reason"))
        if blocked_reason is not None:
            lines.append(f"    reason={blocked_reason}")


def _memory_governance_plan_line(plan: dict[str, Any]) -> str:
    plan_id = _text(plan.get("plan_id")) or "unknown"
    scope = _text(plan.get("scope")) or "task"
    decision = _text(plan.get("decision")) or "blocked"
    status = _text(plan.get("status")) or "manual_gap"
    write = _yes_no(plan.get("write_request_allowed"))
    target = _text(plan.get("target_namespace_uri")) or "memory://unknown"
    line = f"{plan_id} {scope} {decision} {status} write={write} -> {target}"
    shared = _text(plan.get("shared_namespace_uri"))
    if shared is not None:
        line += f" shared={shared}"
    return line


def _append_feature_lineage(lines: list[str], cockpit: dict[str, Any]) -> None:
    lineage = cockpit.get("feature_lineage")
    if not isinstance(lineage, dict):
        return
    lines.append(
        "Feature lineage: "
        f"contracts={_number(lineage.get('contract_count'))}; "
        f"lanes={_number(lineage.get('lane_count'))}; "
        f"ready={_number(lineage.get('ready_lane_count'))}; "
        f"blocked={_number(lineage.get('blocked_lane_count'))}; "
        f"completed={_number(lineage.get('completed_lane_count'))}"
    )
    for feature in _dicts(lineage.get("features"))[:4]:
        lines.append(f"  {_feature_lineage_feature_line(feature)}")
        for blocker in _dicts(feature.get("lane_blockers"))[:3]:
            lines.append(f"    {_feature_lineage_blocker_line(blocker)}")


def _feature_lineage_feature_line(feature: dict[str, Any]) -> str:
    feature_id = _text(feature.get("feature_id")) or "unknown"
    graph_id = _text(feature.get("feature_graph_id")) or "unknown"
    ready = _compact_or_none(_strings(feature.get("ready_lane_ids")))
    blocked = _compact_or_none(_strings(feature.get("blocked_lane_ids")))
    return f"{feature_id} {graph_id} ready={ready} blocked={blocked}"


def _feature_lineage_blocker_line(blocker: dict[str, Any]) -> str:
    lane_id = _text(blocker.get("lane_id")) or "unknown"
    blocker_type = _text(blocker.get("blocker_type")) or "blocked"
    blocker_ref = _text(blocker.get("blocker_ref")) or "unknown"
    blocker_status = _text(blocker.get("blocker_status")) or "unknown"
    return f"{lane_id} {blocker_type} {blocker_ref} status={blocker_status}"


def _compact_or_none(values: list[str]) -> str:
    return _compact(values) if values else "-"


def _append_virtual_soak(lines: list[str], cockpit: dict[str, Any]) -> None:
    summary = cockpit.get("virtual_soak_summary")
    if isinstance(summary, dict) and _number(summary.get("total")):
        lines.append(
            "Virtual soak: "
            f"ok={_number(summary.get('ok'))}; "
            f"violated={_number(summary.get('violated'))}; "
            f"total={_number(summary.get('total'))}"
        )
    latest = cockpit.get("latest_virtual_soak")
    if not isinstance(latest, dict):
        return
    run_id = _text(latest.get("run_id")) or "unknown"
    total_minutes = _number(latest.get("total_minutes"))
    status = _text(latest.get("slo_status")) or "not_evaluated"
    line = f"Latest soak: {run_id} {total_minutes}m SLO={status}"
    violations = _strings(latest.get("slo_violations"))
    if violations:
        line += f": {_compact(violations)}"
    lines.append(line)


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


def _yes_no(value: Any) -> str:
    return "yes" if value is True else "no"


def _text(value: Any) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None
