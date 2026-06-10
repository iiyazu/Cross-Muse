from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, TypedDict

ReviewReworkReasonCategory = Literal[
    "semantic_rework",
    "review_rejection",
    "approved_review",
    "review_infra",
    "execution_infra",
    "gate_failure",
    "merge_conflict",
    "prompt_subsystem_mismatch",
    "unknown",
    "not_review_related",
]


class ReviewReworkSummary(TypedDict):
    lane_id: str
    status: str
    reason_category: ReviewReworkReasonCategory
    retry_count: int
    review_retry_count: int
    fallback_reason: str | None
    primary_evidence_refs: list[str]


_REVIEW_REWORK_STATUSES = {
    "reviewed",
    "reworking",
    "rejected",
    "gate_failed",
    "exec_failed",
    "failed",
    "terminated",
    "awaiting_final_action",
    "merge_failed",
    "merged",
    "done",
    "completed",
}
_POSITIVE_FALLBACK_REASONS = {
    "approval_marker",
    "explicit_merge_decision",
    "explicit_merge_verdict",
    "persistent_result",
    "positive_no_blocking",
    "positive_no_findings",
    "positive_none",
    "review_verdict",
    "update_lane_status",
    "verdict_merge",
}
_REWORK_FALLBACK_REASONS = {
    "blocking_finding",
    "findings_section",
    "incomplete_validation",
    "missing_coverage",
    "missing_tests",
    "must_fix",
    "negative_marker",
    "reproduced_finding",
    "severity_finding",
    "unresolved_finding",
    "unknown_review_text",
}
_REVIEW_REJECTION_FALLBACK_REASONS = {
    "explicit_rejection",
    "needs_rework",
    "verdict_rework",
    "verdict_terminate",
}
_REVIEW_INFRA_FAILURE_REASONS = {
    "review_infra_unavailable",
    "review_spawn_failed",
    "review_non_zero_exit",
    "review_no_verdict",
    "review_timeout",
}
_EXECUTION_INFRA_FAILURE_REASONS = {
    "execution_infra_unavailable",
    "execution_circuit_open",
    "non_zero_exit",
    "timeout",
}


def classify_review_rework_lanes(
    lanes: list[dict[str, Any]],
    *,
    xmuse_root: Path | None = None,
) -> list[ReviewReworkSummary]:
    return [
        classify_review_rework_lane(lane, xmuse_root=xmuse_root)
        for lane in lanes
        if isinstance(lane, dict)
    ]


def classify_review_rework_lane(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None = None,
) -> ReviewReworkSummary:
    lane_id = _lane_id(lane)
    status = str(lane.get("status") or "unknown")
    fallback_reason, fallback_ref = _fallback_reason(lane)
    review_text_evidence = _review_text_evidence(lane, xmuse_root=xmuse_root)
    if fallback_reason is None and review_text_evidence is not None:
        _decision, fallback_reason, _refs = review_text_evidence
    category, evidence_refs = _classify_lane(
        lane,
        status=status,
        fallback_reason=fallback_reason,
        fallback_ref=fallback_ref,
        review_text_evidence=review_text_evidence,
        xmuse_root=xmuse_root,
    )
    return {
        "lane_id": lane_id,
        "status": status,
        "reason_category": category,
        "retry_count": _int_or_zero(lane.get("retry_count")),
        "review_retry_count": _int_or_zero(lane.get("review_retry_count")),
        "fallback_reason": fallback_reason,
        "primary_evidence_refs": evidence_refs,
    }


def _classify_lane(
    lane: dict[str, Any],
    *,
    status: str,
    fallback_reason: str | None,
    fallback_ref: str | None,
    review_text_evidence: tuple[str, str, list[str]] | None,
    xmuse_root: Path | None,
) -> tuple[ReviewReworkReasonCategory, list[str]]:
    merge_conflict_refs = _merge_conflict_evidence(lane)
    if status not in _REVIEW_REWORK_STATUSES and not merge_conflict_refs:
        return "not_review_related", ["lane.status"]

    if merge_conflict_refs:
        return "merge_conflict", merge_conflict_refs

    prompt_mismatch_refs = _prompt_subsystem_mismatch_evidence(lane)
    if prompt_mismatch_refs:
        return "prompt_subsystem_mismatch", prompt_mismatch_refs

    if review_text_evidence is not None and review_text_evidence[0] == "reviewed":
        return "approved_review", review_text_evidence[2]

    if fallback_reason in _POSITIVE_FALLBACK_REASONS:
        return "approved_review", [fallback_ref or "lane.review_fallback_reason"]

    failure_reason = _str_or_none(lane.get("failure_reason"))
    review_infra_reason = _str_or_none(lane.get("review_infra_reason"))
    if failure_reason in _REVIEW_INFRA_FAILURE_REASONS:
        refs = ["lane.failure_reason"]
        if review_infra_reason:
            refs.append("lane.review_infra_reason")
        return "review_infra", refs
    if failure_reason in _EXECUTION_INFRA_FAILURE_REASONS:
        return "execution_infra", ["lane.failure_reason"]
    if status == "exec_failed":
        return "execution_infra", ["lane.status"]

    if failure_reason == "gate_failed":
        return "gate_failure", ["lane.failure_reason"]
    gate_ref_evidence = _gate_failure_evidence(lane, xmuse_root=xmuse_root)
    if status == "gate_failed" and gate_ref_evidence:
        return "gate_failure", gate_ref_evidence

    if fallback_reason in _REWORK_FALLBACK_REASONS:
        if fallback_ref is not None:
            refs = [fallback_ref]
        elif review_text_evidence is not None:
            refs = list(review_text_evidence[2])
        else:
            refs = ["lane.review_fallback_reason"]
        if _str_or_none(lane.get("review_summary")) and "lane.review_summary" not in refs:
            refs.append("lane.review_summary")
        elif review_text_evidence is not None:
            refs.extend(ref for ref in review_text_evidence[2] if ref not in refs)
        return "semantic_rework", refs

    if fallback_reason in _REVIEW_REJECTION_FALLBACK_REASONS:
        refs = _fallback_refs_with_summary(
            fallback_ref=fallback_ref,
            review_text_evidence=review_text_evidence,
            lane=lane,
        )
        return "review_rejection", refs

    if str(lane.get("review_decision") or "").lower() == "merge":
        if _review_decision_is_memory_only(lane):
            return "unknown", _unknown_evidence_refs(lane)
        return "approved_review", ["lane.review_decision"]
    if status == "reviewed":
        return "approved_review", ["lane.status"]
    if str(lane.get("review_decision") or "").lower() in {"rework", "reject", "rejected"}:
        return "review_rejection", ["lane.review_decision"]

    return "unknown", _unknown_evidence_refs(lane)


def _merge_conflict_evidence(lane: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    reason = _str_or_none(lane.get("merge_failure_reason"))
    detail = _str_or_none(lane.get("merge_failure_detail"))
    if reason and ("conflict" in reason.lower() or reason == "merge_conflict_or_failed"):
        refs.append("lane.merge_failure_reason")
    if detail and _text_mentions_merge_conflict(detail):
        refs.append("lane.merge_failure_detail")
    return refs


def _text_mentions_merge_conflict(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in (
            "merge conflict",
            "conflict (",
            "unmerged paths",
            "automatic merge failed",
        )
    )


def _prompt_subsystem_mismatch_evidence(lane: dict[str, Any]) -> list[str]:
    for key in ("prompt_subsystem_mismatch", "prompt_mismatch_reason"):
        value = _str_or_none(lane.get(key))
        if value:
            return [f"lane.{key}"]
    failure_reason = _str_or_none(lane.get("failure_reason"))
    if failure_reason in {"prompt_subsystem_mismatch", "prompt_mismatch"}:
        return ["lane.failure_reason"]
    summary = _str_or_none(lane.get("review_summary"))
    if summary and _text_mentions_prompt_subsystem_mismatch(summary):
        return ["lane.review_summary"]
    history = lane.get("review_history")
    if isinstance(history, list):
        for item in reversed(history[-4:]):
            if not isinstance(item, dict):
                continue
            history_summary = _str_or_none(item.get("summary"))
            if history_summary and _text_mentions_prompt_subsystem_mismatch(
                history_summary
            ):
                return ["lane.review_history[-1].summary"]
    return []


def _text_mentions_prompt_subsystem_mismatch(value: str) -> bool:
    lowered = value.lower()
    return any(
        marker in lowered
        for marker in (
            "wrong subsystem",
            "different subsystem",
            "incorrect subsystem",
            "prompt/subsystem mismatch",
            "prompt subsystem mismatch",
            "targets the wrong",
            "targeted the wrong",
            "out of scope",
        )
    )


def _fallback_refs_with_summary(
    *,
    fallback_ref: str | None,
    review_text_evidence: tuple[str, str, list[str]] | None,
    lane: dict[str, Any],
) -> list[str]:
    refs: list[str] = []
    if fallback_ref is not None:
        refs.append(fallback_ref)
    elif review_text_evidence is not None:
        refs.extend(review_text_evidence[2])
    else:
        refs.append("lane.review_fallback_reason")
    if _str_or_none(lane.get("review_summary")) and "lane.review_summary" not in refs:
        refs.append("lane.review_summary")
    return _dedupe(refs)


def _review_text_evidence(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None,
) -> tuple[str, str, list[str]] | None:
    from xmuse_core.platform.execution.review import infer_review_fallback

    summary = _str_or_none(lane.get("review_summary"))
    if summary:
        decision, _summary, reason = infer_review_fallback(summary)
        if (
            decision == "reviewed"
            or reason in _REWORK_FALLBACK_REASONS
            or reason in _REVIEW_REJECTION_FALLBACK_REASONS
        ):
            return decision, reason, ["lane.review_summary"]
    history = lane.get("review_history")
    if isinstance(history, list):
        for item in reversed(history[-4:]):
            if not isinstance(item, dict):
                continue
            fallback_reason = _str_or_none(item.get("fallback_reason"))
            if fallback_reason in _POSITIVE_FALLBACK_REASONS:
                return "reviewed", fallback_reason, [
                    "lane.review_history[-1].fallback_reason"
                ]
            history_summary = _str_or_none(item.get("summary"))
            if history_summary:
                decision, _summary, reason = infer_review_fallback(history_summary)
                if (
                    decision == "reviewed"
                    or reason in _REWORK_FALLBACK_REASONS
                    or reason in _REVIEW_REJECTION_FALLBACK_REASONS
                ):
                    return decision, reason, ["lane.review_history[-1].summary"]
    return _lane_context_review_evidence(lane, xmuse_root=xmuse_root)


def _lane_context_review_evidence(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None,
) -> tuple[str, str, list[str]] | None:
    from xmuse_core.platform.execution.review import infer_review_fallback

    if xmuse_root is None:
        return None
    for context_ref in _lane_context_refs(lane):
        payload = _read_bounded_json_ref(context_ref, xmuse_root=xmuse_root)
        if not isinstance(payload, dict):
            continue
        for key in ("review_summary", "retry_context"):
            text = _str_or_none(payload.get(key))
            if text is None:
                continue
            decision, _summary, reason = infer_review_fallback(text)
            if (
                decision == "reviewed"
                or reason in _REWORK_FALLBACK_REASONS
                or reason in _REVIEW_REJECTION_FALLBACK_REASONS
            ):
                return decision, reason, ["lane.lane_context_ref", context_ref]
    return None


def _lane_context_refs(lane: dict[str, Any]) -> list[str]:
    refs: list[str] = []
    for key in ("lane_context_ref", "lane_context_path"):
        value = _str_or_none(lane.get(key))
        if value:
            refs.append(value)
    lane_id = _lane_id(lane)
    if lane_id != "unknown":
        refs.append(f"logs/lane_context/{_safe_ref_segment(lane_id)}/latest.json")
    return _dedupe(refs)


def _gate_failure_evidence(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None,
) -> list[str]:
    gate_ref = _str_or_none(lane.get("gate_report_ref"))
    evidence_refs: list[str] = []
    if gate_ref:
        evidence_refs.append("lane.gate_report_ref")
        if _gate_report_failed(gate_ref, xmuse_root=xmuse_root):
            evidence_refs.append(gate_ref)
            return evidence_refs
    if lane.get("gate_passed") is False:
        evidence_refs.append("lane.gate_passed")
    return evidence_refs


def _gate_report_failed(gate_ref: str, *, xmuse_root: Path | None) -> bool:
    if xmuse_root is None:
        return False
    payload = _read_bounded_json_ref(gate_ref, xmuse_root=xmuse_root)
    if not isinstance(payload, dict):
        return False
    return payload.get("passed") is False or payload.get("blocking_passed") is False


def _fallback_reason(lane: dict[str, Any]) -> tuple[str | None, str | None]:
    direct = _str_or_none(lane.get("review_fallback_reason"))
    if direct is not None:
        return direct, "lane.review_fallback_reason"
    history = lane.get("review_history")
    if isinstance(history, list):
        for item in reversed(history[-4:]):
            if isinstance(item, dict):
                value = _str_or_none(item.get("fallback_reason"))
                if value is not None:
                    return value, "lane.review_history[-1].fallback_reason"
    return None, None


def _unknown_evidence_refs(lane: dict[str, Any]) -> list[str]:
    refs = ["lane.status"]
    for key in (
        "failure_reason",
        "review_decision",
        "review_summary",
        "review_fallback_reason",
    ):
        if lane.get(key) is not None:
            refs.append(f"lane.{key}")
    return refs


def _review_decision_is_memory_only(lane: dict[str, Any]) -> bool:
    if not lane.get("memory_refs"):
        return False
    if _str_or_none(lane.get("review_summary")) is not None:
        return False
    if _str_or_none(lane.get("review_verdict_id")) is not None:
        return False
    if _str_or_none(lane.get("review_task_id")) is not None:
        return False
    history = lane.get("review_history")
    if isinstance(history, list):
        for item in reversed(history[-4:]):
            if not isinstance(item, dict):
                continue
            if (
                _str_or_none(item.get("summary")) is not None
                or _str_or_none(item.get("fallback_reason")) is not None
            ):
                return False
    return True


def _lane_id(lane: dict[str, Any]) -> str:
    return str(lane.get("feature_id") or lane.get("lane_id") or lane.get("id") or "unknown")


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_or_zero(value: Any) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _read_bounded_json_ref(
    ref: str,
    *,
    xmuse_root: Path,
    max_bytes: int = 64_000,
) -> Any:
    path = xmuse_root / ref
    try:
        resolved_root = xmuse_root.resolve()
        resolved_path = path.resolve()
        resolved_path.relative_to(resolved_root)
        if resolved_path.stat().st_size > max_bytes:
            return None
        return json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return None


def _safe_ref_segment(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value)


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result
