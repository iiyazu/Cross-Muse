from __future__ import annotations

import json
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from xmuse_core.platform.lane_context import build_lane_context_bundle
from xmuse_core.platform.review_rework import classify_review_rework_lane
from xmuse_core.platform.run_health import summarize_run_health
from xmuse_core.structuring.models import ReviewGodTakeoverContextContract

_REDACTED_LOG_KEYS = (
    "api_key",
    "authorization",
    "bearer",
    "password",
    "secret",
    "token",
)
_EVIDENCE_REQUIREMENTS = [
    "takeover_context_bundle",
    "repair_diff_or_invalid_abandon_rationale",
    "focused_tests_or_gate_report",
    "review_verdict",
    "audit_event",
    "chat_takeover_or_terminal_card",
]


@dataclass(frozen=True)
class LaneTakeoverBundle:
    lane_id: str
    prompt: str | None
    acceptance_criteria: list[str]
    lane_metadata: dict[str, Any]
    feature_refs: list[str]
    blueprint_refs: list[str]
    gate_report_refs: list[dict[str, Any]]
    review_summary: str | None
    review_history: list[dict[str, Any]]
    worker_diff_refs: list[str]
    worker_logs: list[dict[str, Any]]
    worktree_ref: dict[str, Any]
    retry_metadata: dict[str, Any]
    dependency_status: dict[str, Any]
    context_contract: dict[str, Any]
    run_health_summary: dict[str, Any]
    evidence_requirements: list[str]

    def as_prompt_context(self) -> str:
        lines = [
            "## Failed Lane Takeover Context",
            "",
            f"- Lane ID: {self.lane_id}",
            f"- Status: {self.lane_metadata.get('status') or 'unknown'}",
        ]
        if self.prompt:
            lines.extend(["", "### Prompt", "", self.prompt])
        if self.acceptance_criteria:
            lines.extend(["", "### Acceptance Criteria"])
            lines.extend(f"- {item}" for item in self.acceptance_criteria)
        if self.feature_refs:
            lines.extend(["", "### Feature Refs"])
            lines.extend(f"- {item}" for item in self.feature_refs)
        if self.blueprint_refs:
            lines.extend(["", "### Blueprint Refs"])
            lines.extend(f"- {item}" for item in self.blueprint_refs)
        if self.review_summary:
            lines.extend(["", "### Review Summary", "", self.review_summary])
        if self.review_history:
            lines.extend(["", "### Review History"])
            for item in self.review_history:
                decision = item.get("decision") or "unknown"
                summary = item.get("summary") or ""
                recorded_at = item.get("recorded_at")
                suffix = f" ({recorded_at})" if recorded_at else ""
                lines.append(f"- {decision}{suffix}: {summary}")
        lines.extend(["", "### Retry Metadata"])
        lines.append(f"- Retry count: {self.retry_metadata.get('retry_count', 0)}")
        lines.append(
            f"- Review retry count: {self.retry_metadata.get('review_retry_count', 0)}"
        )
        if self.retry_metadata.get("failure_reason"):
            lines.append(f"- Failure reason: {self.retry_metadata['failure_reason']}")
        if self.retry_metadata.get("review_decision"):
            lines.append(f"- Review decision: {self.retry_metadata['review_decision']}")
        alignment = self.retry_metadata.get("review_rework_alignment")
        if isinstance(alignment, dict):
            lines.append(
                f"- Review/rework category: {alignment.get('reason_category') or 'unknown'}"
            )
        lines.extend(["", "### Worktree"])
        lines.append(f"- Branch: {self.worktree_ref.get('branch') or 'missing'}")
        lines.append(f"- Worktree: {self.worktree_ref.get('worktree') or 'missing'}")
        if self.worker_diff_refs:
            lines.extend(["", "### Worker Diff Refs"])
            lines.extend(f"- {item}" for item in self.worker_diff_refs)
        if self.gate_report_refs:
            lines.extend(["", "### Gate Reports"])
            for ref in self.gate_report_refs:
                lines.append(f"- {ref['ref']} exists={ref['exists']}")
                if ref.get("summary"):
                    lines.append(str(ref["summary"]))
        lines.extend(["", "### Dependency Status"])
        for item in self.dependency_status.get("depends_on", []):
            lines.append(f"- dependency {item['lane_id']}: {item['status']}")
        for item in self.dependency_status.get("dependents", []):
            lines.append(f"- dependent {item['lane_id']}: {item['status']}")
        if self.context_contract:
            lines.extend(["", "### Guard Context"])
            attempt = self.context_contract.get("attempt", {})
            if isinstance(attempt, dict):
                lines.append(
                    f"- takeover_attempt_id: {attempt.get('takeover_attempt_id') or 'missing'}"
                )
            lease = self.context_contract.get("lease", {})
            if isinstance(lease, dict):
                lines.append(f"- lease_id: {lease.get('lease_id') or 'missing'}")
                lines.append(f"- lease_owner: {lease.get('lease_owner') or 'missing'}")
            projection = self.context_contract.get("projection", {})
            if isinstance(projection, dict):
                lines.append(
                    "- projection_revision: "
                    + str(projection.get("projection_revision", "missing"))
                )
            evidence = self.context_contract.get("evidence", {})
            if isinstance(evidence, dict):
                if evidence.get("evidence_bundle_id"):
                    lines.append(f"- evidence_bundle_id: {evidence['evidence_bundle_id']}")
                if evidence.get("evidence_bundle_hash"):
                    lines.append(
                        f"- evidence_bundle_hash: {evidence['evidence_bundle_hash']}"
                    )
                lines.append(
                    f"- lane_context_hash: {evidence.get('lane_context_hash') or 'missing'}"
                )
            guard_status = self.context_contract.get("guard_status", {})
            if isinstance(guard_status, dict):
                lines.append(
                    f"- mutation_ready: {guard_status.get('mutation_ready', False)}"
                )
                escalation_action = guard_status.get("escalation_action")
                if escalation_action:
                    lines.append(f"- escalation_action: {escalation_action}")
                missing_fields = guard_status.get("missing_required_fields")
                if isinstance(missing_fields, list) and missing_fields:
                    lines.append("- missing_required_fields: " + ", ".join(missing_fields))
        lines.extend(["", "### Run Health Summary"])
        for key, value in self.run_health_summary.get("counts", {}).items():
            lines.append(f"- {key}: {value}")
        for key, value in self.run_health_summary.get("takeover_counts_by_reason", {}).items():
            lines.append(f"- takeover_reason {key}: {value}")
        needed_lane_ids = self.run_health_summary.get("takeover_needed_lane_ids", [])
        if needed_lane_ids:
            lines.append("- takeover_needed_lanes: " + ", ".join(needed_lane_ids))
        lines.extend(["", "### Evidence Requirements"])
        lines.extend(f"- {item}" for item in self.evidence_requirements)
        if self.worker_logs:
            lines.extend(["", "### Worker Logs"])
            for log in self.worker_logs:
                lines.append(f"#### {log['ref']}")
                lines.append(str(log.get("excerpt") or ""))
        return "\n".join(lines)


def build_lane_takeover_bundle(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]] | None = None,
    max_log_excerpt_chars: int = 3000,
) -> LaneTakeoverBundle:
    lane_id = _lane_id(lane)
    lane_dicts = [item for item in all_lanes or [lane] if isinstance(item, dict)]
    acceptance_criteria = _compact_text_items(lane.get("acceptance_criteria"))
    lane_metadata = _lane_metadata(lane, lane_id=lane_id)
    feature_refs = _feature_refs(lane, lane_id=lane_id)
    blueprint_refs = _compact_text_items(lane.get("blueprint_refs"))
    gate_report_refs = _gate_report_refs(lane, lane_id=lane_id, xmuse_root=xmuse_root)
    review_history = _review_history(lane.get("review_history"))
    worker_diff_refs = _worker_diff_refs(lane)
    retry_metadata = {
        "retry_count": _int_or_zero(lane.get("retry_count")),
        "review_retry_count": _int_or_zero(lane.get("review_retry_count")),
        "failure_reason": lane.get("failure_reason"),
        "review_decision": lane.get("review_decision"),
        "review_rework_alignment": classify_review_rework_lane(
            lane,
            xmuse_root=xmuse_root,
        ),
    }
    dependency_status = _dependency_status(lane, all_lanes=all_lanes)
    context_contract = _context_contract(
        lane,
        lane_id=lane_id,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
        gate_report_refs=gate_report_refs,
        review_history=review_history,
        worker_diff_refs=worker_diff_refs,
    )
    return LaneTakeoverBundle(
        lane_id=lane_id,
        prompt=_optional_str(lane.get("prompt")),
        acceptance_criteria=acceptance_criteria,
        lane_metadata=lane_metadata,
        feature_refs=feature_refs,
        blueprint_refs=blueprint_refs,
        gate_report_refs=gate_report_refs,
        review_summary=_optional_str(lane.get("review_summary")),
        review_history=review_history,
        worker_diff_refs=worker_diff_refs,
        worker_logs=_worker_logs(
            lane_id,
            xmuse_root=xmuse_root,
            max_log_excerpt_chars=max_log_excerpt_chars,
        ),
        worktree_ref={
            "branch": _optional_str(lane.get("branch")),
            "worktree": _optional_str(lane.get("worktree")),
        },
        retry_metadata=retry_metadata,
        dependency_status=dependency_status,
        context_contract=context_contract,
        run_health_summary=_run_health_summary(lane_dicts, xmuse_root=xmuse_root),
        evidence_requirements=list(_EVIDENCE_REQUIREMENTS),
    )


def _lane_metadata(lane: dict[str, Any], *, lane_id: str) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "status": lane.get("status"),
        "graph_id": lane.get("graph_id"),
        "conversation_id": lane.get("conversation_id"),
        "feature_plan_id": lane.get("feature_plan_id"),
        "feature_plan_feature_id": lane.get("feature_plan_feature_id"),
        "blueprint_refs": _compact_text_items(lane.get("blueprint_refs")),
    }


def _feature_refs(lane: dict[str, Any], *, lane_id: str) -> list[str]:
    refs = [
        f"conversation:{value}"
        for value in [_optional_str(lane.get("conversation_id"))]
        if value
    ]
    graph_id = _optional_str(lane.get("graph_id"))
    if graph_id:
        refs.append(f"graph:{graph_id}")
    feature_plan_id = _optional_str(lane.get("feature_plan_id"))
    if feature_plan_id:
        refs.append(f"feature_plan:{feature_plan_id}")
    feature_id = _optional_str(lane.get("feature_plan_feature_id"))
    if feature_id:
        refs.append(f"feature:{feature_id}")
    refs.append(f"lane:{lane_id}")
    return refs


def _gate_report_refs(
    lane: dict[str, Any],
    *,
    lane_id: str,
    xmuse_root: Path,
) -> list[dict[str, Any]]:
    refs = _compact_text_items(lane.get("gate_report_refs"))
    explicit_ref = _optional_str(lane.get("gate_report_ref"))
    if explicit_ref:
        refs.append(explicit_ref)
    refs.append(f"logs/gates/{lane_id}/report.json")
    refs.append(f"logs/gates/{_safe_lane_id(lane_id)}/report.json")

    gate_refs: list[dict[str, Any]] = []
    for ref in _dedupe(refs):
        path = Path(ref)
        if not path.is_absolute():
            path = xmuse_root / ref
        exists = path.exists()
        gate_refs.append(
            {
                "ref": ref,
                "path": str(path),
                "exists": exists,
                "summary": _gate_report_summary(path) if exists else None,
            }
        )
    return gate_refs


def _gate_report_summary(path: Path, *, max_commands: int = 6) -> str | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    lines = [
        f"- passed: {payload.get('passed')}",
        f"- blocking_passed: {payload.get('blocking_passed')}",
    ]
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


def _worker_logs(
    lane_id: str,
    *,
    xmuse_root: Path,
    max_log_excerpt_chars: int,
) -> list[dict[str, Any]]:
    spawn_dir = xmuse_root / "logs" / "agent_spawns" / _safe_lane_id(lane_id)
    if not spawn_dir.exists():
        return []
    logs: list[dict[str, Any]] = []
    for path in sorted(spawn_dir.iterdir()):
        if not path.is_file() or not path.name.endswith((".stdout.log", ".stderr.log")):
            continue
        original, excerpt = _tail_text(path, max_chars=max_log_excerpt_chars)
        ref = str(path.relative_to(xmuse_root))
        logs.append(
            {
                "ref": ref,
                "path": str(path),
                "excerpt": excerpt,
                "truncated": original != excerpt,
            }
        )
    return logs


def _worker_diff_refs(lane: dict[str, Any]) -> list[str]:
    refs = _compact_text_items(lane.get("worker_diff_refs"))
    refs.extend(_compact_text_items(lane.get("diff_refs")))
    explicit_ref = _optional_str(lane.get("diff_ref"))
    if explicit_ref:
        refs.append(explicit_ref)
    patch_ref = _optional_str(lane.get("patch_ref"))
    if patch_ref:
        refs.append(patch_ref)
    return _dedupe(refs)


def _tail_text(path: Path, *, max_chars: int) -> tuple[str, str]:
    try:
        with path.open("rb") as handle:
            handle.seek(0, 2)
            size = handle.tell()
            handle.seek(max(0, size - max_chars * 4))
            original = handle.read(max_chars * 4).decode("utf-8", errors="replace").strip()
    except OSError:
        return "", ""
    redacted = _redact_log_text(original)
    if len(redacted) <= max_chars:
        return original, redacted
    return original, "...<truncated>\n" + redacted[-max_chars:].lstrip()


def _redact_log_text(value: str) -> str:
    lines: list[str] = []
    for line in value.splitlines():
        lowered = line.lower()
        if any(key in lowered for key in _REDACTED_LOG_KEYS):
            lines.append("[redacted sensitive log line]")
        else:
            lines.append(line)
    return "\n".join(lines)


def _dependency_status(
    lane: dict[str, Any],
    *,
    all_lanes: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    lane_id = _lane_id(lane)
    lanes_by_id = {
        _lane_id(item): item
        for item in all_lanes or [lane]
        if isinstance(item, dict) and _lane_id(item) != "unknown"
    }
    dependencies = []
    for dependency_id in _compact_text_items(lane.get("depends_on")):
        dependency = lanes_by_id.get(dependency_id)
        dependencies.append(
            {
                "lane_id": dependency_id,
                "status": _optional_str(dependency.get("status")) if dependency else "missing",
                "found": dependency is not None,
            }
        )
    dependents = []
    for item in all_lanes or []:
        if not isinstance(item, dict):
            continue
        if lane_id in _compact_text_items(item.get("depends_on")):
            dependents.append(
                {
                    "lane_id": _lane_id(item),
                    "status": _optional_str(item.get("status")) or "unknown",
                }
            )
    return {"depends_on": dependencies, "dependents": dependents}


def _review_history(value: Any, *, max_items: int = 8) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    history: list[dict[str, Any]] = []
    for item in value[-max_items:]:
        if not isinstance(item, dict):
            continue
        summary = _compact_text(item.get("summary"), max_chars=500)
        entry = {
            "decision": _optional_str(item.get("decision")) or "unknown",
            "summary": summary or "",
        }
        recorded_at = _optional_str(item.get("recorded_at"))
        if recorded_at:
            entry["recorded_at"] = recorded_at
        history.append(entry)
    return history


def _context_contract(
    lane: dict[str, Any],
    *,
    lane_id: str,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]] | None,
    gate_report_refs: list[dict[str, Any]],
    review_history: list[dict[str, Any]],
    worker_diff_refs: list[str],
) -> dict[str, Any]:
    lane_context_bundle = build_lane_context_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    payload = {
        "schema_version": "takeover-context-contract/v1",
        "lane_id": lane_id,
        "attempt": {
            "takeover_attempt_id": _takeover_attempt_id(lane, lane_id=lane_id),
            "retry_count": _int_or_zero(lane.get("retry_count")),
            "review_retry_count": _int_or_zero(lane.get("review_retry_count")),
        },
        "lease": {
            "lease_id": _lease_id(lane, xmuse_root=xmuse_root),
            "lease_owner": _lease_owner(lane, xmuse_root=xmuse_root),
            "lease_expires_at": _lease_expires_at(lane, xmuse_root=xmuse_root),
        },
        "projection": {
            "projection_revision": _projection_revision(lane),
            "projection_source": _projection_source(lane),
        },
        "lane": {
            "lane_id": lane_id,
            "lane_status": _optional_str(lane.get("status")) or "unknown",
            "graph_id": _optional_str(lane.get("graph_id")),
            "conversation_id": _optional_str(lane.get("conversation_id")),
        },
        "evidence": {
            "takeover_context_ref": _takeover_context_ref(lane_id, lane=lane),
            "lane_context_ref": _lane_context_ref(lane_context_bundle, lane_id=lane_id),
            "lane_context_hash": _stable_payload_hash(
                lane_context_bundle.get("context_contract", {})
            ),
            "evidence_bundle_id": _optional_str(lane.get("evidence_bundle_id")),
            "evidence_bundle_hash": _optional_str(lane.get("evidence_bundle_hash")),
            "gate_report_refs": [
                str(ref["ref"])
                for ref in gate_report_refs
                if isinstance(ref, dict) and ref.get("ref")
            ],
            "review_history_refs": [
                f"lane.review_history[{index}]"
                for index, _item in enumerate(review_history)
            ],
            "worker_diff_refs": worker_diff_refs,
        },
        "graph_set": {
            "graph_set_id": _optional_str(lane.get("graph_set_id")),
            "graph_id": _optional_str(lane.get("graph_id")),
        },
        "feature_plan": {
            "feature_plan_id": _optional_str(lane.get("feature_plan_id")),
            "plan_feature_id": _plan_feature_id(lane),
        },
        "max_attempt": {
            "max_attempts_by_reason": _max_attempts_by_reason(lane),
            "takeover_attempt_cap": _optional_non_negative_int(
                lane.get("takeover_attempt_cap")
            ),
            "cooldown_seconds": _optional_non_negative_int(
                lane.get("takeover_cooldown_seconds") or lane.get("cooldown_seconds")
            ),
            "terminal_escalation_policy": _optional_str(
                lane.get("terminal_escalation_policy")
            ),
        },
    }
    missing_required_fields = _missing_required_context_fields(payload)
    try:
        contract = ReviewGodTakeoverContextContract.model_validate(payload)
    except ValidationError:
        contract_payload = payload
    else:
        contract_payload = contract.model_dump(mode="json")
    contract_payload["guard_status"] = {
        "mutation_ready": not missing_required_fields,
        "escalation_action": (
            None if not missing_required_fields else "escalate_to_human_or_outer_god"
        ),
        "missing_required_fields": missing_required_fields,
    }
    return contract_payload


def _run_health_summary(
    lanes: list[dict[str, Any]],
    *,
    xmuse_root: Path,
) -> dict[str, Any]:
    summary = summarize_run_health(lanes, live_pids=set(), xmuse_root=xmuse_root)
    takeover_context = summary.get("takeover_context", {})
    return {
        "counts": dict(summary.get("counts", {})),
        "takeover_counts_by_reason": dict(takeover_context.get("counts_by_reason", {})),
        "takeover_needed_lane_ids": [
            str(item.get("lane_id"))
            for item in takeover_context.get("needed_lanes", [])
            if isinstance(item, dict) and item.get("lane_id")
        ],
    }


def _lane_id(lane: dict[str, Any]) -> str:
    return str(lane.get("feature_id") or lane.get("id") or "unknown")


def _takeover_attempt_id(lane: dict[str, Any], *, lane_id: str) -> str:
    return _optional_str(lane.get("takeover_attempt_id")) or f"takeover-{lane_id}"


def _takeover_context_ref(lane_id: str, *, lane: dict[str, Any]) -> str:
    return (
        _optional_str(lane.get("takeover_context_ref"))
        or f"logs/takeover/{_safe_lane_id(lane_id)}/context.json"
    )


def _lane_context_ref(bundle: dict[str, Any], *, lane_id: str) -> str:
    value = bundle.get("lane_context_ref")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return f"logs/lane_context/{_safe_lane_id(lane_id)}/latest.json"


def _projection_revision(lane: dict[str, Any]) -> int:
    value = lane.get("projection_revision")
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else 0


def _projection_source(lane: dict[str, Any]) -> str | None:
    return _optional_str(lane.get("projection_source")) or "feature_lanes.json"


def _missing_required_context_fields(payload: dict[str, Any]) -> list[str]:
    required_paths = (
        "lease.lease_expires_at",
        "lease.lease_id",
        "lease.lease_owner",
        "evidence.evidence_bundle_hash",
        "evidence.evidence_bundle_id",
        "feature_plan.feature_plan_id",
        "feature_plan.plan_feature_id",
        "graph_set.graph_set_id",
        "max_attempt.max_attempts_by_reason",
        "max_attempt.cooldown_seconds",
        "max_attempt.takeover_attempt_cap",
        "max_attempt.terminal_escalation_policy",
    )
    missing: list[str] = []
    for path in required_paths:
        value = _nested_value(payload, path)
        if _is_missing_guard_value(value):
            missing.append(path)
    return missing


def _nested_value(payload: dict[str, Any], path: str) -> Any:
    current: Any = payload
    for part in path.split("."):
        if not isinstance(current, dict):
            return None
        current = current.get(part)
    return current


def _is_missing_guard_value(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, dict):
        return not value
    return False


def _writer_lease_payload(xmuse_root: Path) -> dict[str, Any]:
    path = xmuse_root / "feature_lanes.json.writer_lease.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _lease_id(lane: dict[str, Any], *, xmuse_root: Path) -> str | None:
    return _optional_str(lane.get("lease_id")) or _optional_str(
        _writer_lease_payload(xmuse_root).get("lease_id")
    )


def _lease_owner(lane: dict[str, Any], *, xmuse_root: Path) -> str | None:
    return (
        _optional_str(lane.get("lease_owner"))
        or _optional_str(lane.get("runner_id"))
        or _optional_str(_writer_lease_payload(xmuse_root).get("runner_id"))
    )


def _lease_expires_at(lane: dict[str, Any], *, xmuse_root: Path) -> str | int | float | None:
    lane_value = lane.get("lease_expires_at")
    if lane_value is not None:
        return lane_value
    lease_payload = _writer_lease_payload(xmuse_root)
    value = lease_payload.get("expires_at")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value
    return _optional_str(value)


def _plan_feature_id(lane: dict[str, Any]) -> str | None:
    return _optional_str(lane.get("plan_feature_id")) or _optional_str(
        lane.get("feature_plan_feature_id")
    )


def _max_attempts_by_reason(lane: dict[str, Any]) -> dict[str, int]:
    value = lane.get("max_attempts_by_reason")
    if not isinstance(value, dict):
        return {}
    result: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if isinstance(item, int) and not isinstance(item, bool) and item >= 0:
            result[key.strip()] = item
    return result


def _optional_non_negative_int(value: Any) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


def _optional_str(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


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


def _compact_text(value: Any, *, max_chars: int) -> str | None:
    text = str(value).strip()
    if not text:
        return None
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 14].rstrip() + "...<truncated>"


def _safe_lane_id(value: str) -> str:
    return "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in value
    )


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


def _stable_payload_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
