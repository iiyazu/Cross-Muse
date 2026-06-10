from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.memory_refs import serialize_memory_refs
from xmuse_core.platform.review_rework import classify_review_rework_lane

_REDACTED_LOG_KEYS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)


def build_lane_context_bundle(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]] | None = None,
    max_review_summary_chars: int = 4000,
    max_spawn_refs: int = 6,
) -> dict[str, Any]:
    lane_id = str(lane.get("feature_id", "unknown"))
    feature_id = str(lane.get("feature_plan_feature_id") or lane_id)
    safe_lane_id = _safe_lane_id(lane_id)
    gate_report_path = xmuse_root / "logs" / "gates" / safe_lane_id / "report.json"
    gate_report_ref = _existing_relative_ref(
        xmuse_root,
        gate_report_path,
    )
    recent_spawn_refs = _recent_spawn_refs(
        lane_id,
        xmuse_root=xmuse_root,
        max_refs=max_spawn_refs,
    )
    recent_spawn_paths = _recent_spawn_paths(
        lane_id,
        xmuse_root=xmuse_root,
        max_refs=max_spawn_refs,
    )
    gate_summary = _gate_report_summary(
        gate_report_path,
    )
    review_rework_summary = classify_review_rework_lane(lane, xmuse_root=xmuse_root)
    context_category = _context_failure_category(review_rework_summary)
    review_rework_alignment: dict[str, Any] = {
        **review_rework_summary,
        "context_category": context_category,
    }
    primary_evidence_refs = [
        str(ref) for ref in review_rework_alignment.get("primary_evidence_refs", [])
    ]
    compact_primary_evidence_refs = _compact_primary_evidence_refs(primary_evidence_refs)
    recent_spawn_excerpt = _recent_spawn_excerpt(
        lane_id,
        xmuse_root=xmuse_root,
        max_chars=3000,
    )
    dependency_states = _dependency_states(lane, all_lanes=all_lanes)
    gate_refs = _gate_refs(
        lane,
        lane_id=lane_id,
        gate_report_ref=gate_report_ref,
        gate_report_path=gate_report_path,
        xmuse_root=xmuse_root,
    )
    worker_refs = _worker_refs(recent_spawn_refs)
    blueprint_refs = _compact_text_items(lane.get("blueprint_refs"))
    acceptance_criteria = _compact_text_items(lane.get("acceptance_criteria"))
    memory_refs = serialize_memory_refs(lane.get("memory_refs"))
    bundle: dict[str, Any] = {
        "lane_id": lane_id,
        "lane_context_ref": _lane_context_ref(lane_id),
        "feature_id": feature_id,
        "graph_id": lane.get("graph_id"),
        "status": lane.get("status"),
        "retry_count": _int_or_zero(lane.get("retry_count")),
        "review_retry_count": _int_or_zero(lane.get("review_retry_count")),
        "failure_reason": lane.get("failure_reason"),
        "merge_failure_reason": lane.get("merge_failure_reason"),
        "merge_failure_detail": _compact_text(
            lane.get("merge_failure_detail"),
            max_chars=max_review_summary_chars,
        ),
        "review_decision": lane.get("review_decision"),
        "review_summary": _compact_text(
            lane.get("review_summary"),
            max_chars=max_review_summary_chars,
        ),
        "review_history": _compact_review_history(lane.get("review_history")),
        "gate_passed": lane.get("gate_passed"),
        "gate_report_ref": gate_report_ref,
        "gate_report_path": str(gate_report_path) if gate_report_path.exists() else None,
        "gate_report_summary": gate_summary,
        "branch": lane.get("branch"),
        "worktree": lane.get("worktree"),
        "source_plan": lane.get("source_plan"),
        "depends_on": lane.get("depends_on", []),
        "dependency_states": dependency_states,
        "blueprint_refs": blueprint_refs,
        "acceptance_criteria": acceptance_criteria,
        "memory_refs": memory_refs,
        "review_rework_alignment": review_rework_alignment,
        "primary_evidence_refs": primary_evidence_refs,
        "compact_primary_evidence_refs": compact_primary_evidence_refs,
        "gate_refs": gate_refs,
        "worker_refs": worker_refs,
        "recent_agent_spawn_refs": recent_spawn_refs,
        "recent_agent_spawn_paths": recent_spawn_paths,
        "recent_agent_spawn_excerpt": recent_spawn_excerpt,
        "generated_at": _utc_now(),
    }
    bundle["context_contract"] = _context_contract(
        bundle,
        failure_category=context_category,
    )
    bundle["operator_summary"] = _operator_summary(bundle)
    bundle["retry_context"] = retry_context_for_prompt(bundle)
    return bundle


def write_lane_context_bundle(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]] | None = None,
) -> Path:
    bundle = build_lane_context_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    lane_id = str(bundle["lane_id"])
    path = xmuse_root / "logs" / "lane_context" / _safe_lane_id(lane_id) / "latest.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(bundle, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def load_lane_context_bundle(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    max_bytes: int = 64_000,
) -> dict[str, Any] | None:
    """Load a persisted lane context bundle without touching raw log files."""
    for ref in _lane_context_refs(lane):
        payload = _read_json_ref(ref, xmuse_root=xmuse_root, max_bytes=max_bytes)
        if isinstance(payload, dict):
            return payload
    return None


def load_retry_context_for_prompt(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    max_bytes: int = 64_000,
) -> str | None:
    """Return prompt-ready retry context from a persisted lane context bundle."""
    bundle = load_lane_context_bundle(
        lane,
        xmuse_root=xmuse_root,
        max_bytes=max_bytes,
    )
    if bundle is None:
        return None
    retry_context = bundle.get("retry_context")
    if isinstance(retry_context, str) and retry_context.strip():
        return retry_context
    return retry_context_for_prompt(bundle)


def should_include_retry_context(lane: dict[str, Any]) -> bool:
    return (
        _int_or_zero(lane.get("retry_count")) > 0
        or _int_or_zero(lane.get("review_retry_count")) > 0
        or lane.get("status") == "reworking"
        or lane.get("review_decision") == "rework"
        or bool(lane.get("failure_reason"))
        or lane.get("gate_passed") is not None
        or bool(lane.get("review_summary"))
    )


def retry_context_for_prompt(bundle_or_lane: dict[str, Any]) -> str:
    lane_id = str(bundle_or_lane.get("lane_id") or bundle_or_lane.get("feature_id") or "")
    alignment = _alignment_for_prompt(bundle_or_lane)
    lines = [
        "## Prior Attempt Context",
        "",
        f"- Lane ID: {lane_id}",
        f"- Previous status: {bundle_or_lane.get('status') or 'unknown'}",
        f"- Retry count: {_int_or_zero(bundle_or_lane.get('retry_count'))}",
        f"- Review retry count: {_int_or_zero(bundle_or_lane.get('review_retry_count'))}",
    ]
    if bundle_or_lane.get("failure_reason"):
        lines.append(f"- Failure reason: {bundle_or_lane['failure_reason']}")
    if bundle_or_lane.get("merge_failure_reason"):
        lines.append(f"- Merge failure reason: {bundle_or_lane['merge_failure_reason']}")
    if (
        bundle_or_lane.get("review_decision")
        and alignment.get("reason_category") != "approved_review"
    ):
        lines.append(f"- Review decision: {bundle_or_lane['review_decision']}")
    if bundle_or_lane.get("review_summary"):
        lines.append(f"- Review summary: {bundle_or_lane['review_summary']}")
    history = bundle_or_lane.get("review_history")
    if isinstance(history, list) and history:
        lines.extend(["", "### Recent Review History", ""])
        for item in history[-4:]:
            if not isinstance(item, dict):
                continue
            decision = item.get("decision", "unknown")
            summary = _compact_text(item.get("summary"), max_chars=900)
            if summary:
                lines.append(f"- {decision}: {summary}")

    contract = bundle_or_lane.get("context_contract")
    if isinstance(contract, dict):
        lines.extend(["", "### Context Contract", ""])
        lines.append(f"- Failure category: {contract.get('failure_category') or 'unknown'}")
        lines.append(f"- Feature ID: {contract.get('feature_id') or 'unknown'}")
        lines.append(f"- Graph ID: {contract.get('graph_id') or 'unknown'}")
        refs = contract.get("primary_evidence_refs")
        if isinstance(refs, list) and refs:
            lines.append("- Primary evidence refs: " + ", ".join(str(ref) for ref in refs[:6]))
        dependency_states = contract.get("dependency_states")
        if isinstance(dependency_states, dict):
            for item in dependency_states.get("depends_on", []):
                if isinstance(item, dict):
                    lines.append(
                        f"- dependency {item.get('lane_id')}: "
                        f"{item.get('status') or 'unknown'}"
                    )
            for item in dependency_states.get("dependents", []):
                if isinstance(item, dict):
                    lines.append(
                        f"- dependent {item.get('lane_id')}: "
                        f"{item.get('status') or 'unknown'}"
                    )

    lines.extend(_context_bundle_ref_section(bundle_or_lane))
    lines.extend(_alignment_sections(bundle_or_lane, alignment=alignment))
    if bundle_or_lane.get("merge_failure_detail"):
        lines.extend(["", "### Merge Failure", ""])
        lines.append(str(bundle_or_lane["merge_failure_detail"]))

    blueprint_refs = bundle_or_lane.get("blueprint_refs")
    if isinstance(blueprint_refs, list) and blueprint_refs:
        lines.extend(["", "### Blueprint References", ""])
        for ref in blueprint_refs[:6]:
            lines.append(f"- {ref}")
    acceptance_criteria = bundle_or_lane.get("acceptance_criteria")
    if isinstance(acceptance_criteria, list) and acceptance_criteria:
        lines.extend(["", "### Acceptance Criteria", ""])
        for criterion in acceptance_criteria[:12]:
            lines.append(f"- {criterion}")

    branch = bundle_or_lane.get("branch") or "missing"
    worktree = bundle_or_lane.get("worktree") or "missing"
    lines.append(f"- Branch/worktree evidence: branch={branch} worktree={worktree}")
    if alignment.get("reason_category") != "approved_review":
        lines.append("- Required continuation: address prior review/failure before unrelated work.")
    return "\n".join(lines)


def _alignment_for_prompt(bundle_or_lane: dict[str, Any]) -> Mapping[str, Any]:
    alignment = bundle_or_lane.get("review_rework_alignment")
    if isinstance(alignment, dict):
        return alignment
    return classify_review_rework_lane(bundle_or_lane)


def _context_failure_category(alignment: Mapping[str, Any]) -> str:
    category = str(alignment.get("reason_category") or "unknown")
    return {
        "execution_infra": "execution_infra_failure",
        "review_infra": "review_infra_failure",
    }.get(category, category)


def _context_contract(
    bundle: dict[str, Any],
    *,
    failure_category: str,
) -> dict[str, Any]:
    return {
        "schema_version": "lane-context-contract/v1",
        "lane_id": bundle.get("lane_id"),
        "feature_id": bundle.get("feature_id"),
        "graph_id": bundle.get("graph_id"),
        "status": bundle.get("status"),
        "failure_category": failure_category,
        "expected_fix": _expected_fix(bundle),
        "primary_evidence_refs": bundle.get("primary_evidence_refs", []),
        "blueprint_refs": bundle.get("blueprint_refs", []),
        "acceptance_criteria": bundle.get("acceptance_criteria", []),
        "memory_refs": bundle.get("memory_refs", []),
        "dependency_states": bundle.get("dependency_states", {}),
        "gate_refs": bundle.get("gate_refs", []),
        "worker_refs": bundle.get("worker_refs", []),
        "compact_primary_evidence_refs": bundle.get("compact_primary_evidence_refs", []),
        "review_history_refs": _review_history_refs(bundle.get("review_history")),
    }


def _context_bundle_ref_section(bundle_or_lane: dict[str, Any]) -> list[str]:
    lines = ["", "### Context Bundle References", ""]
    lane_id = str(bundle_or_lane.get("lane_id") or bundle_or_lane.get("feature_id") or "")
    bundle_ref = str(bundle_or_lane.get("lane_context_ref") or _lane_context_ref(lane_id))
    lines.append(f"- Lane context bundle: {bundle_ref}")
    lines.append("- Context contract: lane_context.context_contract")

    primary_refs = _string_refs(bundle_or_lane.get("primary_evidence_refs"))
    if not primary_refs:
        alignment = bundle_or_lane.get("review_rework_alignment")
        if isinstance(alignment, dict):
            primary_refs = _string_refs(alignment.get("primary_evidence_refs"))
    if primary_refs:
        lines.append("- Primary evidence refs: " + ", ".join(primary_refs[:6]))

    compact_refs = bundle_or_lane.get("compact_primary_evidence_refs")
    if isinstance(compact_refs, list) and compact_refs:
        lines.append(
            "- Compact primary evidence refs: "
            + ", ".join(_format_compact_ref(ref) for ref in compact_refs[:6])
        )

    history_refs = []
    contract = bundle_or_lane.get("context_contract")
    if isinstance(contract, dict):
        history_refs = _string_refs(contract.get("review_history_refs"))
    if not history_refs:
        history_refs = _review_history_refs(bundle_or_lane.get("review_history"))
    if history_refs:
        lines.append("- Review history refs: " + ", ".join(history_refs[:6]))

    gate_refs = _ref_values(bundle_or_lane.get("gate_refs"))
    if not gate_refs:
        gate_report_ref = bundle_or_lane.get("gate_report_ref")
        if isinstance(gate_report_ref, str) and gate_report_ref.strip():
            gate_refs = [gate_report_ref.strip()]
    if gate_refs:
        lines.append(f"- Gate report: {gate_refs[0]}")
        lines.append("- Gate refs: " + ", ".join(gate_refs[:6]))

    worker_refs = _ref_values(bundle_or_lane.get("worker_refs"))
    if not worker_refs:
        worker_refs = _string_refs(bundle_or_lane.get("recent_agent_spawn_refs"))
    if worker_refs:
        lines.append("- Worker refs: " + ", ".join(worker_refs[:6]))

    blueprint_refs = _string_refs(bundle_or_lane.get("blueprint_refs"))
    if blueprint_refs:
        lines.append("- Blueprint refs: " + ", ".join(blueprint_refs[:6]))
    memory_ref_uris = _memory_ref_uris(bundle_or_lane.get("memory_refs"))
    if memory_ref_uris:
        lines.append("- Memory refs: " + ", ".join(memory_ref_uris[:6]))
    memory_ref_evidence_refs = _memory_ref_evidence_refs(bundle_or_lane.get("memory_refs"))
    if memory_ref_evidence_refs:
        lines.append(
            "- Memory ref evidence refs: " + ", ".join(memory_ref_evidence_refs[:6])
        )
    return lines


def _format_compact_ref(value: Any) -> str:
    if isinstance(value, dict):
        ref = str(value.get("ref") or "unknown")
        kind = str(value.get("kind") or "evidence_ref")
        return f"{kind}:{ref}"
    return str(value)


def _ref_values(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if isinstance(item, dict):
            ref = item.get("ref")
            if isinstance(ref, str) and ref.strip():
                refs.append(ref.strip())
        elif isinstance(item, str) and item.strip():
            refs.append(item.strip())
    return refs


def _string_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _memory_ref_uris(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        uri = item.get("uri")
        if isinstance(uri, str) and uri.strip():
            refs.append(uri.strip())
    return refs


def _memory_ref_evidence_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        evidence_refs = item.get("primary_evidence_refs")
        if not isinstance(evidence_refs, list):
            continue
        for ref in evidence_refs:
            cleaned = str(ref).strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            refs.append(cleaned)
    return refs


def _compact_primary_evidence_refs(refs: list[str]) -> list[dict[str, str]]:
    return [{"ref": ref, "kind": _primary_evidence_ref_kind(ref)} for ref in refs[:8]]


def _primary_evidence_ref_kind(ref: str) -> str:
    if ref.startswith("lane.review_history"):
        return "review_history"
    if ref.startswith("lane."):
        return "lane_metadata"
    if ref.startswith("logs/gates/"):
        return "gate_report"
    if ref.startswith("logs/agent_spawns/"):
        return "worker_artifact"
    if ref.startswith("logs/lane_context/"):
        return "lane_context"
    return "evidence_ref"


def _expected_fix(bundle: dict[str, Any]) -> str | None:
    for key in ("review_summary", "failure_reason", "merge_failure_reason"):
        text = _compact_text(bundle.get(key), max_chars=700)
        if text:
            return text
    return None


def _review_history_refs(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    refs: list[str] = []
    for index, item in enumerate(value[-4:], start=max(0, len(value) - 4)):
        if isinstance(item, dict) and (item.get("summary") or item.get("fallback_reason")):
            refs.append(f"lane.review_history[{index}]")
    return refs


def _dependency_states(
    lane: dict[str, Any],
    *,
    all_lanes: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    lanes = [item for item in all_lanes or [] if isinstance(item, dict)]
    lanes_by_id = {_lane_id(item): item for item in lanes}
    lane_id = _lane_id(lane)
    depends_on = []
    raw_depends_on = lane.get("depends_on")
    if isinstance(raw_depends_on, list):
        for dep_id_value in raw_depends_on:
            dep_id = str(dep_id_value)
            dep_lane = lanes_by_id.get(dep_id)
            depends_on.append(
                {
                    "lane_id": dep_id,
                    "status": str(dep_lane.get("status") or "unknown")
                    if dep_lane is not None
                    else "missing",
                    "found": dep_lane is not None,
                }
            )
    dependents = []
    for candidate in lanes:
        candidate_id = _lane_id(candidate)
        if candidate_id == lane_id:
            continue
        candidate_depends_on = candidate.get("depends_on")
        if not isinstance(candidate_depends_on, list) or lane_id not in {
            str(item) for item in candidate_depends_on
        }:
            continue
        dependents.append(
            {
                "lane_id": candidate_id,
                "status": str(candidate.get("status") or "unknown"),
            }
        )
    return {
        "depends_on": depends_on,
        "dependents": dependents,
    }


def _gate_refs(
    lane: dict[str, Any],
    *,
    lane_id: str,
    gate_report_ref: str | None,
    gate_report_path: Path,
    xmuse_root: Path,
) -> list[dict[str, Any]]:
    refs = _compact_text_items(lane.get("gate_report_refs"))
    explicit_ref = _compact_text(lane.get("gate_report_ref"), max_chars=500)
    if explicit_ref:
        refs.append(explicit_ref)
    if gate_report_ref:
        refs.append(gate_report_ref)
    else:
        refs.append(f"logs/gates/{_safe_lane_id(lane_id)}/report.json")

    result: list[dict[str, Any]] = []
    for ref in _dedupe(refs):
        path = Path(ref)
        if not path.is_absolute():
            path = xmuse_root / ref
        if ref == f"logs/gates/{_safe_lane_id(lane_id)}/report.json":
            exists = gate_report_path.exists()
        else:
            exists = path.exists()
        if exists:
            result.append({"ref": ref, "exists": True})
    return result


def _worker_refs(refs: list[str]) -> list[dict[str, str]]:
    return [{"ref": ref, "kind": _worker_ref_kind(ref)} for ref in refs]


def _worker_ref_kind(ref: str) -> str:
    if ref.endswith(".result.json"):
        return "spawn_result"
    return "spawn_log"


def _alignment_sections(
    bundle_or_lane: dict[str, Any],
    *,
    alignment: Mapping[str, Any],
) -> list[str]:
    category = str(alignment.get("reason_category") or "unknown")
    lines = ["", "### Infra Failure", ""]
    failure_reason = bundle_or_lane.get("failure_reason")
    if failure_reason:
        if category == "review_infra" or str(failure_reason).startswith("review_"):
            lines.append(f"- Review infra: {failure_reason}")
        elif category == "execution_infra":
            lines.append(f"- Execution infra: {failure_reason}")
        elif category == "gate_failure":
            lines.append(f"- Gate failure: {failure_reason}")
        else:
            lines.append(f"- Failure reason: {failure_reason}")
    elif category in {"review_infra", "execution_infra", "gate_failure"}:
        lines.append(f"- Category indicates {category}.")
    else:
        lines.append("- None recorded.")

    lines.extend(["", "### Parser/Fallback Classification", ""])
    lines.append(f"- Category: {category}")
    fallback_reason = alignment.get("fallback_reason")
    if fallback_reason:
        lines.append(f"- Fallback reason: {fallback_reason}")
    refs = alignment.get("primary_evidence_refs")
    if isinstance(refs, list) and refs:
        lines.append("- Evidence refs: " + ", ".join(str(ref) for ref in refs[:6]))

    lines.extend(["", "### Real Semantic Findings", ""])
    review_summary = bundle_or_lane.get("review_summary")
    if category == "semantic_rework" and review_summary:
        lines.append(f"- {review_summary}")
    elif category == "semantic_rework":
        lines.append("- Review/rework alignment indicates semantic rework.")
    elif category == "approved_review":
        lines.append("- None identified by review/rework alignment.")
    else:
        lines.append(f"- Semantic finding section not applicable for {category}.")

    lines.extend(["", "### Resolved Prior Findings", ""])
    if category == "approved_review":
        lines.append("- Prior review evidence indicates approval/no blocking findings.")
    else:
        resolved = _resolved_history_items(bundle_or_lane.get("review_history"))
        if resolved:
            lines.extend(f"- {item}" for item in resolved)
        else:
            lines.append("- Resolved prior finding refs are unavailable.")
    return lines


def _resolved_history_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    resolved: list[str] = []
    for item in value[-4:]:
        if not isinstance(item, dict):
            continue
        decision = str(item.get("decision") or "").lower()
        summary = _compact_text(item.get("summary"), max_chars=500)
        fallback_reason = str(item.get("fallback_reason") or "")
        if decision in {"merge", "reviewed", "approved"} or fallback_reason.startswith(
            "positive_"
        ):
            resolved.append(summary or f"Review history marked {decision or fallback_reason}.")
    return resolved[:4]


def _recent_spawn_refs(lane_id: str, *, xmuse_root: Path, max_refs: int) -> list[str]:
    return [str(path.relative_to(xmuse_root)) for path in _recent_spawn_files(
        lane_id,
        xmuse_root=xmuse_root,
        max_refs=max_refs,
    )]


def _recent_spawn_paths(lane_id: str, *, xmuse_root: Path, max_refs: int) -> list[str]:
    return [str(path) for path in _recent_spawn_files(
        lane_id,
        xmuse_root=xmuse_root,
        max_refs=max_refs,
    )]


def _recent_spawn_files(lane_id: str, *, xmuse_root: Path, max_refs: int) -> list[Path]:
    spawn_dir = xmuse_root / "logs" / "agent_spawns" / _safe_lane_id(lane_id)
    if not spawn_dir.exists():
        return []
    files = sorted(path for path in spawn_dir.iterdir() if path.is_file())
    return files[-max_refs:]


def _existing_relative_ref(root: Path, path: Path) -> str | None:
    if not path.exists():
        return None
    return str(path.relative_to(root))


def _gate_report_summary(path: Path, *, max_commands: int = 6) -> str | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    lines = [
        f"- passed: {payload.get('passed')}",
        f"- blocking_passed: {payload.get('blocking_passed')}",
    ]
    warnings = payload.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("- warnings: " + "; ".join(str(item) for item in warnings[:3]))
    command_results = payload.get("command_results")
    if isinstance(command_results, list) and command_results:
        lines.append("- commands:")
        for result in command_results[:max_commands]:
            if not isinstance(result, dict):
                continue
            argv = result.get("argv")
            command = " ".join(str(part) for part in argv) if isinstance(argv, list) else ""
            lines.append(
                "  - "
                + f"{result.get('command_id', 'command')} "
                + f"blocking={result.get('blocking')} "
                + f"returncode={result.get('returncode')} "
                + f"cmd={command}"
            )
    return "\n".join(lines)


def _recent_spawn_excerpt(
    lane_id: str,
    *,
    xmuse_root: Path,
    max_chars: int,
) -> str | None:
    spawn_dir = xmuse_root / "logs" / "agent_spawns" / _safe_lane_id(lane_id)
    if not spawn_dir.exists():
        return None
    candidates = sorted(
        path
        for path in spawn_dir.iterdir()
        if path.is_file() and path.name.endswith((".stdout.log", ".stderr.log"))
    )
    if not candidates:
        return None
    parts: list[str] = []
    remaining = max_chars
    for path in reversed(candidates[-4:]):
        if remaining <= 0:
            break
        text = _tail_text(path, max_chars=min(remaining, 1200))
        if not text:
            continue
        rel = path.relative_to(xmuse_root)
        block = f"#### {rel}\n\n{text}"
        parts.append(block)
        remaining -= len(block)
    if not parts:
        return None
    return "\n\n".join(reversed(parts))


def _lane_context_refs(lane: dict[str, Any]) -> list[str]:
    lane_id = _lane_id(lane)
    refs = _compact_text_items(lane.get("lane_context_ref"), max_items=1)
    refs.extend(_compact_text_items(lane.get("lane_context_path"), max_items=1))
    if lane_id != "unknown":
        refs.append(_lane_context_ref(lane_id))
    return _dedupe(refs)


def _read_json_ref(ref: str, *, xmuse_root: Path, max_bytes: int) -> Any:
    path = Path(ref)
    if not path.is_absolute():
        path = xmuse_root / path
    try:
        root = xmuse_root.resolve()
        resolved = path.resolve()
        resolved.relative_to(root)
        if resolved.stat().st_size > max_bytes:
            return None
        return json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _tail_text(path: Path, *, max_chars: int) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_chars * 4))
            text = handle.read(max_chars * 4).decode("utf-8", errors="replace")
    except OSError:
        return ""
    text = _redact_log_text(text.strip())
    if len(text) <= max_chars:
        return text
    return "...<truncated>\n" + text[-max_chars:].lstrip()


def _redact_log_text(value: str) -> str:
    lines = []
    for line in value.splitlines():
        lowered = line.lower()
        if any(key in lowered for key in _REDACTED_LOG_KEYS):
            lines.append("[redacted sensitive log line]")
        else:
            lines.append(line)
    return "\n".join(lines)


def _operator_summary(bundle: dict[str, Any]) -> str:
    parts = [
        f"lane={bundle.get('lane_id')}",
        f"status={bundle.get('status')}",
        f"retry={bundle.get('retry_count')}",
    ]
    if bundle.get("review_decision"):
        parts.append(f"review={bundle['review_decision']}")
    if bundle.get("failure_reason"):
        parts.append(f"failure={bundle['failure_reason']}")
    if not bundle.get("branch") or not bundle.get("worktree"):
        parts.append("merge_context=missing")
    return "; ".join(parts)


def _compact_review_history(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    history: list[dict[str, Any]] = []
    for item in value[-8:]:
        if not isinstance(item, dict):
            continue
        summary = _compact_text(item.get("summary"), max_chars=1200)
        history.append(
            {
                "decision": item.get("decision"),
                "summary": summary,
                "fallback": item.get("fallback"),
                "fallback_reason": item.get("fallback_reason"),
                "recorded_at": item.get("recorded_at"),
            }
        )
    return history


def _compact_text_items(
    value: Any,
    *,
    max_items: int = 12,
    max_chars: int = 500,
) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        compacted = _compact_text(value, max_chars=max_chars)
        return [compacted] if compacted else []
    if not isinstance(value, list):
        return []
    items: list[str] = []
    for item in value[:max_items]:
        compacted = _compact_text(item, max_chars=max_chars)
        if compacted:
            items.append(compacted)
    return items


def _lane_id(lane: dict[str, Any]) -> str:
    return str(lane.get("feature_id") or lane.get("lane_id") or lane.get("id") or "unknown")


def _safe_lane_id(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in value
    )


def _lane_context_ref(lane_id: str) -> str:
    return f"logs/lane_context/{_safe_lane_id(lane_id)}/latest.json"


def _compact_text(value: Any, *, max_chars: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
