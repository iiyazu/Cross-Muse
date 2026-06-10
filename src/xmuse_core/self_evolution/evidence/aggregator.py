from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.state_normalizer import normalize_lane_state, summarize_lane_states
from xmuse_core.self_evolution.evidence import gate_report as gate_report_signals
from xmuse_core.self_evolution.evidence import review_text, signal_order
from xmuse_core.self_evolution.evidence import text as evidence_text
from xmuse_core.self_evolution.models import (
    RunTerminalAggregation,
    RunTerminalStatus,
    StructuredEvidenceBundle,
)
from xmuse_core.self_evolution.store import SelfEvolutionStore
from xmuse_core.structuring.verdict_store import VerdictStore

_DEFAULT_SELECTION_POLICY_ID = "xmuse-self-evolution-bootstrap"
_DEFAULT_SELECTION_POLICY_VERSION = "21"


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def aggregate_run_terminal(
    graph_id: str,
    *,
    lanes_reader: Any,
    store: SelfEvolutionStore | None = None,
    verdict_store: VerdictStore | None = None,
) -> RunTerminalAggregation:
    """Aggregate graph terminal state through the LanesReader boundary."""
    lanes = lanes_reader.list_lanes()
    lane_by_id = {
        str(lane.get("feature_id")): lane
        for lane in lanes
        if isinstance(lane, dict) and lane.get("feature_id")
    }
    graph_lane_ids = _graph_lane_ids(graph_id, lanes, lanes_reader)
    lineage_lane_ids = _lineage_lane_ids(graph_id, graph_lane_ids, lanes_reader)
    lane_statuses: list[dict[str, Any]] = []
    blocked_objects: list[dict[str, Any]] = []

    for lane_id in lineage_lane_ids:
        lane = lane_by_id.get(lane_id)
        if lane is None:
            lane_statuses.append(
                {
                    "feature_id": lane_id,
                    "raw_status": "unprojected",
                    "normalized_status": "waiting_dependency",
                    "terminal": False,
                }
            )
            continue
        normalized = normalize_lane_state(lane)
        lane_status: dict[str, Any] = {
            "feature_id": lane_id,
            "raw_status": normalized.raw_status,
            "normalized_status": normalized.normalized_status,
            "terminal": normalized.is_terminal,
        }
        if lane.get("review_decision"):
            lane_status["review_decision"] = str(lane["review_decision"])
        if lane.get("review_verdict_id"):
            lane_status["review_verdict_id"] = str(lane["review_verdict_id"])
        lane_statuses.append(lane_status)
        blocked = lanes_reader.blocked_object_for_lane(lane)
        if blocked is not None and (
            normalized.raw_status == "blocked_for_input" or not normalized.is_terminal
        ):
            blocked_objects.append(blocked)

    present_lineage_lanes = [
        lane_by_id[lane_id] for lane_id in lineage_lane_ids if lane_id in lane_by_id
    ]
    final_action_holds = [
        hold
        for lane_id in lineage_lane_ids
        if (lane := lane_by_id.get(lane_id)) is not None
        if (hold := lanes_reader.final_action_hold_for_lane(lane)) is not None
    ]
    verdict_lineage = _build_verdict_lineage(
        lineage_lane_ids,
        lane_by_id,
        verdict_store=verdict_store,
    )
    status, reason = _aggregate_status(
        lane_statuses,
        blocked_objects,
        final_action_holds,
        verdict_lineage,
    )
    aggregation = RunTerminalAggregation(
        aggregation_id=_new_id("runagg"),
        run_id=graph_id,
        resolution_id=_resolution_id_for_graph(
            graph_id,
            present_lineage_lanes,
            lanes_reader=lanes_reader,
        ),
        graph_id=graph_id,
        status=status,
        terminal=status is not RunTerminalStatus.RUNNING,
        reason=reason,
        lane_counts=summarize_lane_states(present_lineage_lanes),
        lane_statuses=lane_statuses,
        open_lineages=lanes_reader.open_lineages(lane_by_id),
        blocked_objects=blocked_objects,
        final_action_holds=final_action_holds,
        verdict_lineage=verdict_lineage,
        created_at=_utc_now(),
    )
    if store is not None:
        return store.save_aggregation(aggregation)
    root = getattr(lanes_reader, "xmuse_root", None)
    if isinstance(root, Path):
        return SelfEvolutionStore(root / "self_evolution").save_aggregation(aggregation)
    return aggregation


def build_evidence_bundle(
    *,
    aggregation: RunTerminalAggregation,
    store: SelfEvolutionStore,
    lanes_path: Path | None = None,
    xmuse_root: Path | None = None,
    blueprint_path: Path | None = None,
    selection_policy_id: str = _DEFAULT_SELECTION_POLICY_ID,
    selection_policy_version: str = _DEFAULT_SELECTION_POLICY_VERSION,
) -> StructuredEvidenceBundle:
    """Build and persist the structured evidence bundle for an aggregation."""
    root = xmuse_root or _xmuse_root_from_store(store)
    resolved_lanes_path = lanes_path or root / "feature_lanes.json"
    resolved_blueprint_path = blueprint_path or root / "blueprint.md"
    lanes = _read_lanes(resolved_lanes_path)
    relevant_lanes = _relevant_lanes_for_aggregation(lanes, aggregation)
    gate_report_refs = _gate_report_refs(relevant_lanes, root)
    primary_refs = [
        _relative_ref(resolved_lanes_path, root),
        f"lane_graphs/{aggregation.graph_id}.json",
        _relative_ref(resolved_blueprint_path, root),
    ]
    signal_refs = [
        _lane_counts_ref(aggregation),
        *_lane_signal_refs(relevant_lanes, aggregation),
        *_gate_report_signal_refs(gate_report_refs),
        *_gate_report_resolution_signal_refs(gate_report_refs, root),
        *_gate_report_diagnostic_signal_refs(gate_report_refs, root),
        *_gate_report_result_signal_refs(gate_report_refs, root),
    ]
    bundle = StructuredEvidenceBundle(
        bundle_id=_new_id("evbundle"),
        source_run_id=aggregation.run_id,
        source_resolution_id=aggregation.resolution_id,
        selection_policy_id=selection_policy_id,
        selection_policy_version=selection_policy_version,
        summary=_evidence_summary(aggregation, signal_refs, root),
        run_terminal_status=aggregation.status,
        verdict_refs=[
            str(lane["review_verdict_id"])
            for lane in relevant_lanes
            if lane.get("review_verdict_id")
        ],
        gate_report_refs=gate_report_refs,
        lineage_refs=[
            f"lane:{lane['source_lane_id']}->{lane['feature_id']}"
            for lane in relevant_lanes
            if lane.get("source_lane_id") and lane.get("feature_id")
        ],
        artifact_refs=primary_refs,
        signal_refs=signal_refs,
        primary_refs=primary_refs,
        created_at=_utc_now(),
    )
    return store.save_evidence_bundle(bundle)


def _lineage_lane_ids(
    graph_id: str,
    graph_lane_ids: list[str],
    lanes_reader: Any,
) -> list[str]:
    ordered = list(lanes_reader.lineage_lane_ids(graph_id))
    seen = set(ordered)
    for lane_id in graph_lane_ids:
        if lane_id not in seen:
            ordered.append(lane_id)
            seen.add(lane_id)
    return ordered


def _graph_lane_ids(
    graph_id: str,
    lanes: list[dict[str, Any]],
    lanes_reader: Any,
) -> list[str]:
    if hasattr(lanes_reader, "graph_lane_ids"):
        return list(lanes_reader.graph_lane_ids(graph_id, lanes=lanes))
    return [
        str(lane["feature_id"])
        for lane in lanes
        if lane.get("graph_id") == graph_id and lane.get("feature_id")
    ]


def _resolution_id_for_graph(
    graph_id: str,
    lanes: list[dict[str, Any]],
    *,
    lanes_reader: Any | None = None,
) -> str:
    if lanes_reader is not None and hasattr(lanes_reader, "graph_resolution_id"):
        resolution_id = lanes_reader.graph_resolution_id(graph_id)
        if isinstance(resolution_id, str) and resolution_id:
            return resolution_id
    for lane in lanes:
        resolution_id = lane.get("resolution_id")
        if isinstance(resolution_id, str) and resolution_id:
            return resolution_id
    return graph_id.removesuffix("-graph-v1")


def _build_verdict_lineage(
    lineage_lane_ids: list[str],
    lane_by_id: dict[str, dict[str, Any]],
    *,
    verdict_store: VerdictStore | None = None,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for lane_id in lineage_lane_ids:
        lane = lane_by_id.get(lane_id)
        if lane is None:
            continue
        if verdict_store is not None:
            for verdict in verdict_store.list_verdicts_for_lane(lane_id):
                result.append(
                    {
                        "lane_id": lane_id,
                        "verdict_id": verdict.id,
                        "decision": verdict.decision.value,
                        "summary": verdict.summary,
                        "source": "verdict_store",
                    }
                )
        elif lane.get("review_verdict_id"):
            entry: dict[str, Any] = {
                "lane_id": lane_id,
                "verdict_id": str(lane["review_verdict_id"]),
                "source": "lane_metadata",
            }
            if lane.get("review_decision"):
                entry["decision"] = str(lane["review_decision"])
            if lane.get("review_summary"):
                entry["summary"] = evidence_text.compact_signal_text(
                    str(lane["review_summary"]), 160
                )
            result.append(entry)
    return result


def _aggregate_status(
    lane_statuses: list[dict[str, Any]],
    blocked_objects: list[dict[str, Any]],
    final_action_holds: list[dict[str, Any]],
    verdict_lineage: list[dict[str, Any]],
) -> tuple[RunTerminalStatus, str]:
    if blocked_objects:
        return RunTerminalStatus.BLOCKED_FOR_INPUT, "one or more lanes request clarification"
    if not lane_statuses:
        return RunTerminalStatus.RUNNING, "no graph lanes have been projected yet"
    if any(not bool(item["terminal"]) for item in lane_statuses):
        if final_action_holds:
            return (
                RunTerminalStatus.RUNNING,
                "one or more lanes are awaiting final-action approval",
            )
        return RunTerminalStatus.RUNNING, "at least one graph lineage lane is not terminal"
    if all(item["normalized_status"] == "merged" for item in lane_statuses):
        return RunTerminalStatus.MERGED, "all graph lineage lanes merged"
    if _has_unmerged_terminal_lineage(lane_statuses, verdict_lineage):
        return RunTerminalStatus.RUNNING, "graph lineage merge coordination pending"
    return RunTerminalStatus.TERMINATED, "at least one graph lineage terminalized without merge"


def _has_unmerged_terminal_lineage(
    lane_statuses: list[dict[str, Any]],
    verdict_lineage: list[dict[str, Any]],
) -> bool:
    merged_lane_ids = {
        str(entry.get("lane_id"))
        for entry in verdict_lineage
        if str(entry.get("decision", "")).lower() == "merge"
    }
    closed_lane_ids = merged_lane_ids | {
        str(entry.get("lane_id"))
        for entry in verdict_lineage
        if str(entry.get("decision", "")).lower() == "terminate"
    }
    for status in lane_statuses:
        lane_id = str(status.get("feature_id") or "")
        if not lane_id or lane_id in closed_lane_ids:
            continue
        if (
            bool(status.get("terminal"))
            and status.get("normalized_status") != "merged"
            and str(status.get("review_decision", "")).lower()
            in {"rework", "patch-forward", "patch_forward"}
        ):
            return True
    return False


def _xmuse_root_from_store(store: SelfEvolutionStore) -> Path:
    return store.path_for("aggregations").parent.parent


def _read_lanes(lanes_path: Path) -> list[dict[str, Any]]:
    if not lanes_path.exists():
        return []
    try:
        data = json.loads(lanes_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    lanes = data.get("lanes", []) if isinstance(data, dict) else []
    return [lane for lane in lanes if isinstance(lane, dict)]


def _relevant_lanes_for_aggregation(
    lanes: list[dict[str, Any]],
    aggregation: RunTerminalAggregation,
) -> list[dict[str, Any]]:
    lineage_lane_ids = {
        str(item["feature_id"])
        for item in aggregation.lane_statuses
        if isinstance(item.get("feature_id"), str)
    }
    return [
        lane
        for lane in lanes
        if lane.get("graph_id") == aggregation.graph_id
        or lane.get("feature_id") in lineage_lane_ids
    ]


def _gate_report_refs(lanes: list[dict[str, Any]], root: Path) -> list[str]:
    refs: list[str] = []
    for lane in lanes:
        lane_id = lane.get("feature_id")
        if not lane_id:
            continue
        report_path = root / "logs" / "gates" / str(lane_id) / "report.json"
        if report_path.exists():
            refs.append(_relative_ref(report_path, root))
    return refs


def _is_generated_signal_ref(signal: str) -> bool:
    return gate_report_signals.is_generated_signal_ref(signal)


def _relative_ref(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        try:
            return path.relative_to(root.parent).as_posix()
        except ValueError:
            return path.as_posix()


def _lane_counts_ref(aggregation: RunTerminalAggregation) -> str:
    return f"lane_counts:{json.dumps(aggregation.lane_counts, sort_keys=True)}"


def _evidence_summary(
    aggregation: RunTerminalAggregation,
    signal_refs: list[str],
    root: Path,
) -> str:
    lane_counts = _lane_counts_summary(_lane_counts_ref(aggregation))
    if lane_counts.startswith("lane_counts "):
        lane_counts = lane_counts.removeprefix("lane_counts ")
    summary = (
        f"Run {aggregation.run_id} terminal status is {aggregation.status.value}. "
        f"Reason: {aggregation.reason}. Lane counts: {lane_counts}."
    )
    if signal_refs:
        summary = f"{summary} Evidence signals: {_signal_summary(signal_refs, root)}."
    return summary


def _lane_signal_refs(
    lanes: list[dict[str, Any]],
    aggregation: RunTerminalAggregation,
) -> list[str]:
    status_by_id = {
        str(item.get("feature_id")): item
        for item in aggregation.lane_statuses
        if isinstance(item.get("feature_id"), str)
    }
    refs: list[str] = []
    for lane in lanes:
        lane_id = lane.get("feature_id")
        if not isinstance(lane_id, str) or not lane_id:
            continue
        status = status_by_id.get(lane_id, {})
        payload: dict[str, Any] = {
            "feature_id": lane_id,
            "raw_status": status.get("raw_status", lane.get("status")),
            "normalized_status": status.get("normalized_status"),
            "terminal": bool(status.get("terminal")),
        }
        for key in (
            "failure_reason",
            "manual_recovery",
            "review_decision",
            "review_fallback",
            "review_fallback_reason",
            "gate_passed",
            "retry_count",
            "patch_lane_id",
        ):
            if key in lane:
                payload[key] = lane[key]
        review_findings = review_text.review_finding_summaries(lane.get("review_summary"))
        if review_findings:
            payload["review_findings"] = review_findings
        review_scope_refs = review_text.review_scope_refs(lane.get("review_summary"))
        if review_scope_refs:
            payload["review_scope_refs"] = review_scope_refs
        review_risks = review_text.review_risk_summaries(lane.get("review_summary"))
        if review_risks:
            payload["review_risks"] = review_risks
        review_recovery_reason = review_text.review_recovery_reason(lane)
        if review_recovery_reason:
            payload["review_recovery_reason"] = review_recovery_reason
        if (
            payload.get("normalized_status") == "merged"
            or payload.get("review_decision") == "merge"
        ):
            review_confirmations = review_text.review_confirmation_summaries(
                lane.get("review_summary")
            )
            if review_confirmations:
                payload["review_confirmations"] = review_confirmations
        if payload["terminal"] or payload.get("review_decision") or payload.get("failure_reason"):
            refs.append(
                f"lane_signal:{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"
            )
    return refs


def _signal_summary(signal_refs: list[str], root: Path) -> str:
    signal_text: list[str] = []
    ordered_refs = signal_order.ordered_signal_summary_refs(signal_refs)
    max_signal_text = (
        6
        if any(signal.startswith("gate_report_diagnostic:") for signal in ordered_refs)
        else 5
    )
    for signal in ordered_refs:
        if signal.startswith("lane_signal:"):
            signal_text.append(_lane_signal_summary(signal))
        elif signal.startswith("lane_counts:"):
            signal_text.append(_lane_counts_summary(signal))
        elif signal.startswith("gate_report:"):
            signal_text.append(_gate_report_summary(signal.removeprefix("gate_report:"), root))
        elif signal.startswith("gate_report_resolution:"):
            try:
                payload = json.loads(signal.removeprefix("gate_report_resolution:"))
            except json.JSONDecodeError:
                signal_text.append(signal)
                continue
            signal_text.append(gate_report_signals.gate_report_resolution_summary(payload))
        elif signal.startswith("gate_report_diagnostic:"):
            try:
                payload = json.loads(signal.removeprefix("gate_report_diagnostic:"))
            except json.JSONDecodeError:
                signal_text.append(signal)
                continue
            signal_text.append(gate_report_signals.gate_report_diagnostic_summary(payload))
        elif signal.startswith("gate_report_result:"):
            try:
                payload = json.loads(signal.removeprefix("gate_report_result:"))
            except json.JSONDecodeError:
                signal_text.append(signal)
                continue
            command = gate_report_signals.gate_report_command_summary(payload)
            outcome = str(payload.get("outcome") or "unknown")
            stdout_summary = str(payload.get("stdout_summary") or "").strip()
            result = f"gate_command={command} -> {outcome}"
            if stdout_summary:
                result = f"{result} ({stdout_summary})"
            signal_text.append(evidence_text.compact_confirmation_text(result, 160))
        else:
            signal_text.append(signal)
        if len(signal_text) >= max_signal_text:
            break
    return "; ".join(signal_text) if signal_text else "none"


def _lane_signal_summary(signal: str) -> str:
    try:
        payload = json.loads(signal.removeprefix("lane_signal:"))
    except json.JSONDecodeError:
        return signal
    parts = [
        f"lane {payload.get('feature_id', 'unknown')}",
        f"status={payload.get('normalized_status', payload.get('raw_status'))}",
    ]
    if payload.get("review_decision"):
        parts.append(f"review={payload['review_decision']}")
    if payload.get("review_fallback"):
        parts.append(f"review_source={payload['review_fallback']}")
        parts.append(f"review_fallback={payload['review_fallback']}")
    if payload.get("review_fallback_reason"):
        parts.append(
            "fallback_reason="
            f"{evidence_text.compact_signal_text(str(payload['review_fallback_reason']), 80)}"
        )
    if payload.get("review_recovery_reason"):
        parts.append(
            "recovery_reason="
            f"{evidence_text.compact_signal_text(str(payload['review_recovery_reason']), 80)}"
        )
    review_scope_refs = payload.get("review_scope_refs")
    if isinstance(review_scope_refs, list) and review_scope_refs:
        reviewed = ",".join(str(ref) for ref in review_scope_refs[:2])
        parts.append(f"reviewed={evidence_text.compact_signal_text(reviewed, 140)}")
    if "gate_passed" in payload:
        parts.append(f"gate={'passed' if payload['gate_passed'] else 'failed'}")
    if payload.get("retry_count") is not None:
        parts.append(f"retries={payload['retry_count']}")
    if payload.get("manual_recovery"):
        parts.append(
            "recovery="
            f"{evidence_text.compact_signal_text(str(payload['manual_recovery']), 100)}"
        )
    if payload.get("failure_reason"):
        parts.append(f"failure={payload['failure_reason']}")
    review_findings = payload.get("review_findings")
    if isinstance(review_findings, list) and review_findings:
        parts.append(
            f"finding={evidence_text.compact_signal_text(str(review_findings[0]), 120)}"
        )
    review_risks = payload.get("review_risks")
    if isinstance(review_risks, list) and review_risks:
        parts.append(
            f"risk={evidence_text.compact_risk_text(str(review_risks[0]), 120)}"
        )
    signal_text = " ".join(parts)
    review_confirmations = payload.get("review_confirmations")
    if isinstance(review_confirmations, list) and review_confirmations:
        confirmations = [
            "confirmation="
            f"{evidence_text.compact_confirmation_text(str(confirmation), 120)}"
            for confirmation in review_confirmations[:2]
        ]
        signal_text = f"{signal_text} {'; '.join(confirmations)}"
    return signal_text


def _gate_report_signal_refs(gate_report_refs: list[str]) -> list[str]:
    return [f"gate_report:{ref}" for ref in gate_report_refs if ref]


def _gate_report_resolution_signal_refs(gate_report_refs: list[str], root: Path) -> list[str]:
    refs: list[str] = []
    for report_ref in gate_report_refs:
        payload = _gate_report_resolution_payload(report_ref, root)
        if payload:
            refs.append(
                "gate_report_resolution:"
                f"{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"
            )
    return refs


def _gate_report_resolution_payload(report_ref: str, root: Path) -> dict[str, Any] | None:
    report = _read_gate_report(report_ref, root)
    if report is None:
        return None
    resolution_reasons = report.get("resolution_reasons")
    if not isinstance(resolution_reasons, dict):
        return None
    profile_reasons: list[dict[str, Any]] = []
    for profile_id in sorted(resolution_reasons):
        raw_reasons = resolution_reasons.get(profile_id)
        if not isinstance(profile_id, str) or not isinstance(raw_reasons, list):
            continue
        reasons = [
            evidence_text.compact_signal_text(str(reason), 80)
            for reason in raw_reasons
            if isinstance(reason, str) and reason.strip()
        ][:3]
        if reasons:
            profile_reasons.append({"profile_id": profile_id, "reasons": reasons})
        if len(profile_reasons) >= 3:
            break
    if not profile_reasons:
        return None
    return {"report_ref": report_ref, "profile_reasons": profile_reasons}


def _gate_report_diagnostic_signal_refs(gate_report_refs: list[str], root: Path) -> list[str]:
    refs: list[str] = []
    for report_ref in gate_report_refs:
        payload = _gate_report_diagnostic_payload(report_ref, root)
        if payload:
            refs.append(
                "gate_report_diagnostic:"
                f"{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"
            )
    return refs


def _gate_report_diagnostic_payload(report_ref: str, root: Path) -> dict[str, Any] | None:
    report = _read_gate_report(report_ref, root)
    if report is None:
        return None
    warnings = gate_report_signals.compact_report_messages(report.get("warnings"))
    nonblocking_failures = gate_report_signals.compact_report_messages(
        report.get("nonblocking_failures")
    )
    if not warnings and not nonblocking_failures:
        return None
    payload: dict[str, Any] = {"report_ref": report_ref}
    if warnings:
        payload["warnings"] = warnings
    if nonblocking_failures:
        payload["nonblocking_failures"] = nonblocking_failures
    return payload


def _gate_report_summary(report_ref: str, root: Path) -> str:
    parts = [f"gate_report={report_ref}"]
    report = _read_gate_report(report_ref, root)
    if report is None:
        return parts[0]
    outcome = gate_report_signals.gate_report_outcome(report)
    if outcome:
        parts.append(f"status={outcome}")
    blocking_passed = report.get("blocking_passed")
    if isinstance(blocking_passed, bool):
        parts.append(f"blocking={'passed' if blocking_passed else 'failed'}")
    profile_ids = report.get("profile_ids")
    if isinstance(profile_ids, list):
        profiles = [str(profile_id) for profile_id in profile_ids if isinstance(profile_id, str)]
        if profiles:
            parts.append(f"profiles={','.join(profiles[:3])}")
    return evidence_text.compact_signal_text(" ".join(parts), 180)


def _gate_report_result_signal_refs(gate_report_refs: list[str], root: Path) -> list[str]:
    refs: list[str] = []
    for report_ref in gate_report_refs:
        for payload in _gate_report_result_payloads(report_ref, root)[:2]:
            refs.append(
                "gate_report_result:"
                f"{json.dumps(payload, sort_keys=True, separators=(',', ':'))}"
            )
    return refs


def _gate_report_result_payloads(report_ref: str, root: Path) -> list[dict[str, Any]]:
    report = _read_gate_report(report_ref, root)
    if report is None:
        return []
    command_results = report.get("command_results")
    legacy_commands = report.get("commands")
    if not isinstance(command_results, list) and not isinstance(legacy_commands, list):
        return []
    payloads: list[dict[str, Any]] = []
    for result in command_results if isinstance(command_results, list) else []:
        if not isinstance(result, dict) or not isinstance(result.get("returncode"), int):
            continue
        payload: dict[str, Any] = {
            "report_ref": report_ref,
            "command_id": str(result.get("command_id") or "command"),
            "profile_id": str(result.get("profile_id") or "unknown"),
            "returncode": result["returncode"],
            "outcome": "passed" if result["returncode"] == 0 else "failed",
        }
        argv = result.get("argv")
        if isinstance(argv, list) and argv:
            payload["argv"] = [str(part) for part in argv]
        stdout_summary = _gate_report_stdout_summary(result.get("stdout_path"), root)
        if stdout_summary:
            payload["stdout_summary"] = stdout_summary
        payloads.append(payload)
    if not payloads and isinstance(legacy_commands, list):
        report_outcome = gate_report_signals.gate_report_outcome(report)
        for index, command_entry in enumerate(legacy_commands, start=1):
            payload = gate_report_signals.legacy_gate_command_payload(
                report_ref=report_ref,
                command_entry=command_entry,
                index=index,
                report_outcome=report_outcome,
            )
            if payload:
                payloads.append(payload)
    payloads.sort(
        key=lambda item: (
            item.get("outcome") == "passed",
            str(item.get("profile_id", "")),
            str(item.get("command_id", "")),
        )
    )
    return payloads


def _gate_report_stdout_summary(stdout_path: Any, root: Path) -> str | None:
    if not isinstance(stdout_path, str) or not stdout_path:
        return None
    path = _resolve_xmuse_ref(stdout_path, root)
    if not path.exists() or not path.is_file():
        return None
    try:
        stdout = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for raw_line in reversed(stdout[-65536:].splitlines()):
        line = evidence_text.compact_signal_text(raw_line.strip("= "), 160)
        lowered = line.lower()
        if not line:
            continue
        if (
            "all checks passed" in lowered
            or re.search(r"\b\d+\s+passed\b", lowered)
            or re.search(r"\b\d+\s+failed\b", lowered)
            or re.search(r"\b\d+\s+errors?\b", lowered)
        ):
            return line
    return None


def _read_gate_report(report_ref: str, root: Path) -> dict[str, Any] | None:
    path = _resolve_xmuse_ref(report_ref, root)
    if not path.exists():
        return None
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return report if isinstance(report, dict) else None


def _resolve_xmuse_ref(ref: str, root: Path) -> Path:
    path = Path(ref)
    return path if path.is_absolute() else root / path


def _lane_counts_summary(signal: str) -> str:
    return gate_report_signals.lane_counts_summary(signal)
