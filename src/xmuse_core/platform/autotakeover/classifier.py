from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from xmuse_core.platform.review_rework import (
    ReviewReworkReasonCategory,
    classify_review_rework_lane,
)
from xmuse_core.platform.state_machine import MAX_RETRIES

TakeoverCandidateReason = Literal[
    "merge_failed",
    "rework_failed",
    "review_failed",
    "retry_exhausted",
    "gate_failed",
    "prompt_subsystem_mismatch",
]


class TakeoverCandidateSummary(TypedDict):
    lane_id: str
    status: str
    is_takeover_candidate: bool
    takeover_reason: TakeoverCandidateReason | None
    legacy_reason_category: ReviewReworkReasonCategory | None
    retry_count: int
    review_retry_count: int
    primary_evidence_refs: list[str]


_CURRENT_REASON_ALIASES: dict[str, TakeoverCandidateReason] = {
    "merge_failed": "merge_failed",
    "rework_failed": "rework_failed",
    "review_failed": "review_failed",
    "retry_exhausted": "retry_exhausted",
    "retry_count_exhausted": "retry_exhausted",
    "prompt_subsystem_mismatch": "prompt_subsystem_mismatch",
    "prompt_mismatch": "prompt_subsystem_mismatch",
}

_LEGACY_REASON_MAP: dict[
    ReviewReworkReasonCategory,
    TakeoverCandidateReason,
] = {
    "merge_conflict": "merge_failed",
    "semantic_rework": "rework_failed",
    "review_rejection": "rework_failed",
    "review_infra": "review_failed",
    "execution_infra": "retry_exhausted",
    "gate_failure": "gate_failed",
    "prompt_subsystem_mismatch": "prompt_subsystem_mismatch",
}


def classify_takeover_candidates(
    lanes: list[dict[str, Any]],
    *,
    xmuse_root: Path | None = None,
) -> list[TakeoverCandidateSummary]:
    return [
        classify_takeover_candidate(lane, xmuse_root=xmuse_root)
        for lane in lanes
        if isinstance(lane, dict)
    ]


def classify_takeover_candidate(
    lane: dict[str, Any],
    *,
    xmuse_root: Path | None = None,
) -> TakeoverCandidateSummary:
    lane_id = _lane_id(lane)
    status = str(lane.get("status") or "unknown")
    retry_count = _int_or_zero(lane.get("retry_count"))
    review_retry_count = _int_or_zero(lane.get("review_retry_count"))
    legacy_summary = classify_review_rework_lane(lane, xmuse_root=xmuse_root)
    legacy_reason = legacy_summary["reason_category"]

    explicit_reason = _explicit_current_reason(lane, legacy_reason=legacy_reason)
    if explicit_reason is not None:
        return _summary(
            lane_id=lane_id,
            status=status,
            reason=explicit_reason,
            legacy_reason_category=(
                legacy_reason
                if _current_reason_comes_from_legacy(
                    explicit_reason,
                    lane,
                    legacy_reason,
                )
                else None
            ),
            retry_count=retry_count,
            review_retry_count=review_retry_count,
            primary_evidence_refs=_explicit_reason_refs(
                lane,
                explicit_reason=explicit_reason,
                legacy_summary=legacy_summary,
            ),
        )

    if _is_retry_exhausted(lane):
        refs = _dedupe(
            [
                *(
                    ["lane.retry_count"]
                    if retry_count >= MAX_RETRIES
                    else ["lane.review_retry_count"]
                ),
                *legacy_summary["primary_evidence_refs"],
            ]
        )
        return _summary(
            lane_id=lane_id,
            status=status,
            reason="retry_exhausted",
            legacy_reason_category=(
                legacy_reason if legacy_reason in _LEGACY_REASON_MAP else None
            ),
            retry_count=retry_count,
            review_retry_count=review_retry_count,
            primary_evidence_refs=refs,
        )

    mapped_reason = _LEGACY_REASON_MAP.get(legacy_reason)
    if mapped_reason is not None:
        return _summary(
            lane_id=lane_id,
            status=status,
            reason=mapped_reason,
            legacy_reason_category=legacy_reason,
            retry_count=retry_count,
            review_retry_count=review_retry_count,
            primary_evidence_refs=list(legacy_summary["primary_evidence_refs"]),
        )

    return {
        "lane_id": lane_id,
        "status": status,
        "is_takeover_candidate": False,
        "takeover_reason": None,
        "legacy_reason_category": None,
        "retry_count": retry_count,
        "review_retry_count": review_retry_count,
        "primary_evidence_refs": [],
    }


def _summary(
    *,
    lane_id: str,
    status: str,
    reason: TakeoverCandidateReason,
    legacy_reason_category: ReviewReworkReasonCategory | None,
    retry_count: int,
    review_retry_count: int,
    primary_evidence_refs: list[str],
) -> TakeoverCandidateSummary:
    return {
        "lane_id": lane_id,
        "status": status,
        "is_takeover_candidate": True,
        "takeover_reason": reason,
        "legacy_reason_category": legacy_reason_category,
        "retry_count": retry_count,
        "review_retry_count": review_retry_count,
        "primary_evidence_refs": _dedupe(primary_evidence_refs),
    }


def _explicit_current_reason(
    lane: dict[str, Any],
    *,
    legacy_reason: ReviewReworkReasonCategory,
) -> TakeoverCandidateReason | None:
    failure_reason = _str_or_none(lane.get("failure_reason"))
    if failure_reason in _CURRENT_REASON_ALIASES:
        return _CURRENT_REASON_ALIASES[failure_reason]

    merge_failure_reason = _str_or_none(lane.get("merge_failure_reason"))
    if merge_failure_reason == "merge_failed":
        return "merge_failed"

    prompt_mismatch = _str_or_none(lane.get("prompt_subsystem_mismatch"))
    if prompt_mismatch is not None:
        return "prompt_subsystem_mismatch"

    prompt_mismatch_reason = _str_or_none(lane.get("prompt_mismatch_reason"))
    if prompt_mismatch_reason is not None:
        return "prompt_subsystem_mismatch"

    status = str(lane.get("status") or "unknown")
    if status == "gate_failed" and legacy_reason == "gate_failure":
        return "gate_failed"

    return None


def _current_reason_comes_from_legacy(
    explicit_reason: TakeoverCandidateReason,
    lane: dict[str, Any],
    legacy_reason: ReviewReworkReasonCategory,
) -> bool:
    if explicit_reason != "gate_failed":
        return False
    return (
        _str_or_none(lane.get("failure_reason")) is None
        and legacy_reason == "gate_failure"
    )


def _explicit_reason_refs(
    lane: dict[str, Any],
    *,
    explicit_reason: TakeoverCandidateReason,
    legacy_summary: dict[str, Any],
) -> list[str]:
    if explicit_reason == "merge_failed":
        if _str_or_none(lane.get("failure_reason")) == "merge_failed":
            return ["lane.failure_reason"]
        refs = []
        if _str_or_none(lane.get("merge_failure_reason")) is not None:
            refs.append("lane.merge_failure_reason")
        if _str_or_none(lane.get("merge_failure_detail")) is not None:
            refs.append("lane.merge_failure_detail")
        return refs or list(legacy_summary["primary_evidence_refs"])

    if explicit_reason == "gate_failed":
        if _str_or_none(lane.get("failure_reason")) == "gate_failed":
            return ["lane.failure_reason"]
        return list(legacy_summary["primary_evidence_refs"])

    if explicit_reason == "prompt_subsystem_mismatch":
        if _str_or_none(lane.get("failure_reason")) in {
            "prompt_subsystem_mismatch",
            "prompt_mismatch",
        }:
            return ["lane.failure_reason"]
        if _str_or_none(lane.get("prompt_subsystem_mismatch")) is not None:
            return ["lane.prompt_subsystem_mismatch"]
        if _str_or_none(lane.get("prompt_mismatch_reason")) is not None:
            return ["lane.prompt_mismatch_reason"]
        return list(legacy_summary["primary_evidence_refs"])

    return ["lane.failure_reason"]


def _is_retry_exhausted(lane: dict[str, Any]) -> bool:
    retry_count = _int_or_zero(lane.get("retry_count"))
    review_retry_count = _int_or_zero(lane.get("review_retry_count"))
    return retry_count >= MAX_RETRIES or review_retry_count >= MAX_RETRIES


def _lane_id(lane: dict[str, Any]) -> str:
    return str(lane.get("feature_id") or lane.get("lane_id") or lane.get("id") or "unknown")


def _str_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


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
