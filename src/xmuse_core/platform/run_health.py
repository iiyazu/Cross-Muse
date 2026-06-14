from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from xmuse_core.platform.coordinator_incidents import summarize_coordinator_incidents
from xmuse_core.platform.review_rework import classify_review_rework_lanes
from xmuse_core.platform.run_processes import (
    build_process_inventory,
    discover_xmuse_processes,
    discover_xmuse_runtime_processes,
    list_live_pids,
)
from xmuse_core.platform.run_processes import (
    process_warnings as _process_warnings,
)
from xmuse_core.platform.state_normalizer import normalize_lane_state

__all__ = [
    "build_process_inventory",
    "build_run_health_model",
    "build_run_health_model_from_lanes",
    "build_run_health_scope",
    "discover_xmuse_processes",
    "discover_xmuse_runtime_processes",
    "list_live_pids",
    "summarize_run_health",
]

ACTIVE_STATUSES = {"dispatched", "gated", "executed", "reviewed", "reworking"}
REVIEW_REWORK_CATEGORIES = (
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
)
INFRA_FAILURE_REASONS = {
    "execution_infra_unavailable",
    "execution_circuit_open",
    "review_infra_unavailable",
    "review_spawn_failed",
    "review_non_zero_exit",
    "timeout",
}
REQUIRED_PEER_FAILURE_REASONS = {
    "required_review_peer_unavailable",
    "review_peer_delivery_failed",
}
PEER_DEGRADED_OR_FALLBACK_MODES = {
    "configured_peer_degraded",
    "one_shot_fallback",
    "auto_persistent_fallback",
    "required_peer_failed",
}
DEFAULT_STALE_AFTER_S = 1800.0


def summarize_run_health(
    lanes: list[dict[str, Any]],
    *,
    now: float | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    live_pids: set[int] | None = None,
    xmuse_root: Path | None = None,
    review_rework_sample_limit: int = 5,
) -> dict[str, Any]:
    current_time = time.time() if now is None else now
    groups = {
        "live": [],
        "stale": [],
        "retrying": [],
        "blocked": [],
        "infra_failed": [],
        "terminal": [],
        "unsafe_to_release_dependents": [],
        "takeover_context_needed": [],
        "degraded_fallback": [],
    }
    lane_dicts = [lane for lane in lanes if isinstance(lane, dict)]

    for lane in lane_dicts:
        lane_id = str(lane.get("feature_id") or lane.get("id") or "unknown")
        status = str(lane.get("status") or "unknown")
        normalized = normalize_lane_state(lane)
        if status in ACTIVE_STATUSES:
            if _is_stale(
                lane,
                status=status,
                now=current_time,
                stale_after_s=stale_after_s,
                live_pids=live_pids,
            ):
                groups["stale"].append(lane_id)
            else:
                groups["live"].append(lane_id)
        if not normalized.is_terminal and _is_retrying(lane):
            groups["retrying"].append(lane_id)
        if _is_blocked(lane):
            groups["blocked"].append(lane_id)
        if str(lane.get("failure_reason") or "") in INFRA_FAILURE_REASONS:
            groups["infra_failed"].append(lane_id)
        if normalized.is_terminal:
            groups["terminal"].append(lane_id)
        if _unsafe_to_release_dependents(lane):
            groups["unsafe_to_release_dependents"].append(lane_id)

    review_rework_alignment = summarize_review_rework_alignment(
        lane_dicts,
        xmuse_root=xmuse_root,
        sample_limit=review_rework_sample_limit,
    )
    takeover_context = summarize_takeover_context_needs(
        lane_dicts,
        stale_lane_ids=set(groups["stale"]),
        xmuse_root=xmuse_root,
    )
    groups["takeover_context_needed"] = [
        item["lane_id"] for item in takeover_context["needed_lanes"]
    ]
    peer_delivery = summarize_peer_delivery_visibility(lane_dicts)
    provider_selection = summarize_provider_selection_visibility(
        lane_dicts,
        xmuse_root=xmuse_root,
    )
    recovery = summarize_lane_recovery_blocks(
        lane_dicts,
        xmuse_root=xmuse_root,
    )
    groups["degraded_fallback"] = _dedupe_lane_ids(
        [
            item["lane_id"] for item in peer_delivery["degraded_or_fallback_lanes"]
        ]
        + [item["lane_id"] for item in provider_selection["fallback_lanes"]]
    )

    return {
        "counts": {name: len(items) for name, items in groups.items()},
        "groups": groups,
        "review_rework_alignment": review_rework_alignment,
        "takeover_context": takeover_context,
        "peer_delivery": peer_delivery,
        "provider_selection": provider_selection,
        "recovery": recovery,
        "model_policy_summary": summarize_model_policy_selection(lane_dicts),
    }


def summarize_lane_recovery_blocks(
    lanes: list[dict[str, Any]],
    *,
    xmuse_root: Path | None = None,
    sample_limit: int = 5,
) -> dict[str, Any]:
    """Project durable lane recovery blocks without making recovery decisions."""
    from xmuse_core.structuring.blueprint_execution.lane_recovery_artifacts import (
        LaneRecoveryArtifactError,
        lane_recovery_artifact_path,
        load_lane_recovery_decision,
    )

    forbidden_claims = [
        "overnight_safe_recovery",
        "end_to_end_execution_review_closure",
        "ready_to_merge",
        "pr_merged",
    ]
    if xmuse_root is None:
        return {
            "source_authority": "lane_recovery_artifact",
            "proof_level": "manual_gap",
            "counts": _empty_recovery_counts(),
            "blocked_lanes": [],
            "invalid_artifacts": [],
            "manual_gaps": ["lane_recovery_artifact_scan_unavailable"],
            "forbidden_claims": forbidden_claims,
        }

    counts = _empty_recovery_counts()
    blocked_lanes: list[dict[str, Any]] = []
    invalid_artifacts: list[dict[str, Any]] = []
    for lane in lanes:
        lane_id = _optional_text(lane.get("feature_id")) or _optional_text(
            lane.get("id")
        )
        graph_id = _optional_text(lane.get("graph_id"))
        if lane_id is None or graph_id is None:
            continue
        try:
            decision = load_lane_recovery_decision(
                xmuse_root,
                graph_id=graph_id,
                lane_id=lane_id,
            )
        except (LaneRecoveryArtifactError, ValueError) as exc:
            counts["invalid_artifact"] += 1
            item = {
                "lane_id": lane_id,
                "graph_id": graph_id,
                "status": str(lane.get("status") or "unknown"),
                "reason": "invalid_recovery_artifact",
                "error": str(exc),
                "source_authority": "lane_recovery_artifact",
                "artifact_ref": str(
                    lane_recovery_artifact_path(
                        xmuse_root,
                        graph_id=graph_id,
                        lane_id=lane_id,
                    )
                ),
            }
            invalid_artifacts.append(item)
            blocked_lanes.append(
                item
                | {
                    "retry_allowed": False,
                    "decision": "invalid_recovery_artifact",
                    "next_action": (
                        "repair or regenerate the lane recovery artifact before retrying"
                    ),
                }
            )
            continue
        if decision is None:
            continue
        if decision.retry_allowed:
            counts["retry_allowed"] += 1
            continue
        counts["non_retry_decision"] += 1
        blocked_lanes.append(
            {
                "lane_id": lane_id,
                "graph_id": graph_id,
                "status": str(lane.get("status") or "unknown"),
                "decision": decision.decision.value,
                "retry_allowed": False,
                "failure_class": decision.failure_class,
                "attempt": decision.attempt,
                "reason": decision.decision.value,
                "next_action": decision.next_action,
                "source_refs": list(decision.source_refs),
                "source_authority": "lane_recovery_artifact",
                "artifact_ref": str(
                    lane_recovery_artifact_path(
                        xmuse_root,
                        graph_id=graph_id,
                        lane_id=lane_id,
                    )
                ),
            }
        )

    counts["blocked"] = counts["non_retry_decision"] + counts["invalid_artifact"]
    return {
        "source_authority": "lane_recovery_artifact",
        "proof_level": "contract_proof",
        "counts": counts,
        "blocked_lanes": blocked_lanes[:sample_limit],
        "invalid_artifacts": invalid_artifacts[:sample_limit],
        "sample_limit": sample_limit,
        "manual_gaps": ["live_runner_recovery_enforcement_not_proven"],
        "forbidden_claims": forbidden_claims,
    }


def _empty_recovery_counts() -> dict[str, int]:
    return {
        "blocked": 0,
        "non_retry_decision": 0,
        "invalid_artifact": 0,
        "retry_allowed": 0,
    }


def summarize_review_rework_alignment(
    lanes: list[dict[str, Any]],
    *,
    xmuse_root: Path | None = None,
    sample_limit: int = 5,
) -> dict[str, Any]:
    """Summarize review/rework classifier output for compact health surfaces."""
    lane_dicts = [lane for lane in lanes if isinstance(lane, dict)]
    summaries = classify_review_rework_lanes(lane_dicts, xmuse_root=xmuse_root)
    lanes_by_id = {_lane_id(lane): lane for lane in lane_dicts}
    counts_by_category = {category: 0 for category in REVIEW_REWORK_CATEGORIES}
    for summary in summaries:
        category = summary["reason_category"]
        counts_by_category[category] = counts_by_category.get(category, 0) + 1

    active_retry_or_rework = [
        summary["lane_id"]
        for summary in summaries
        if _is_current_retry_or_rework(lanes_by_id.get(summary["lane_id"]))
    ]
    active_retry_or_rework_set = set(active_retry_or_rework)
    terminal_retry_metadata = [
        summary["lane_id"]
        for summary in summaries
        if _is_historical_terminal_retry_metadata(lanes_by_id.get(summary["lane_id"]))
    ]
    attention_samples = [
        summary
        for summary in summaries
        if summary["lane_id"] in active_retry_or_rework_set
        and summary["reason_category"] != "not_review_related"
    ][:sample_limit]
    return {
        "counts_by_category": counts_by_category,
        "current_active_retry_or_rework": active_retry_or_rework,
        "historical_terminal_retry_metadata": terminal_retry_metadata,
        "operator_attention_samples": attention_samples,
        "sample_limit": sample_limit,
    }


def summarize_takeover_context_needs(
    lanes: list[dict[str, Any]],
    *,
    stale_lane_ids: set[str],
    xmuse_root: Path | None = None,
) -> dict[str, Any]:
    """Identify lanes whose next operator action needs takeover context."""
    lane_dicts = [lane for lane in lanes if isinstance(lane, dict)]
    summaries = classify_review_rework_lanes(lane_dicts, xmuse_root=xmuse_root)
    summaries_by_id = {summary["lane_id"]: summary for summary in summaries}
    needed_lanes: list[dict[str, str]] = []
    counts_by_reason: dict[str, int] = {}

    for lane in lane_dicts:
        lane_id = _lane_id(lane)
        summary = summaries_by_id.get(lane_id)
        category = (
            summary["reason_category"]
            if summary is not None
            else "not_review_related"
        )
        category = _takeover_category_override(lane, category)
        reason = _takeover_context_reason(
            lane,
            lane_id=lane_id,
            stale_lane_ids=stale_lane_ids,
            review_rework_category=category,
        )
        if reason is None:
            continue
        counts_by_reason[reason] = counts_by_reason.get(reason, 0) + 1
        needed_lanes.append(
            {
                "lane_id": lane_id,
                "status": str(lane.get("status") or "unknown"),
                "reason": reason,
                "review_rework_category": category,
                "lane_context_ref": _lane_context_ref(lane, lane_id=lane_id),
            }
        )

    return {
        "counts_by_reason": counts_by_reason,
        "needed_lanes": needed_lanes,
    }


def summarize_peer_delivery_visibility(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize peer routing and degraded/fallback review delivery metadata."""
    counts_by_delivery_mode: dict[str, int] = {}
    configured_peer_lanes: list[dict[str, Any]] = []
    required_peer_failures: list[dict[str, Any]] = []
    persistent_review_degraded_reasons: dict[str, list[str]] = {}
    default_review_peer_routing: list[dict[str, Any]] = []
    degraded_or_fallback_lanes: list[dict[str, Any]] = []

    for lane in lanes:
        lane_id = _lane_id(lane)
        status = str(lane.get("status") or "unknown")
        peer_delivery_mode = _optional_text(lane.get("peer_delivery_mode"))
        if peer_delivery_mode is not None:
            counts_by_delivery_mode[peer_delivery_mode] = (
                counts_by_delivery_mode.get(peer_delivery_mode, 0) + 1
            )
        if _is_configured_peer_lane(lane, peer_delivery_mode):
            configured_peer_lanes.append(_configured_peer_item(lane, lane_id, status))
        if _is_required_peer_failure(lane, peer_delivery_mode):
            required_peer_failures.append(
                {
                    "lane_id": lane_id,
                    "status": status,
                    "failure_reason": _optional_text(lane.get("failure_reason")),
                    "review_peer_id": _optional_text(lane.get("review_peer_id")),
                    "peer_request_id": _optional_text(lane.get("peer_request_id")),
                    "peer_degraded_reason": _optional_text(
                        lane.get("peer_degraded_reason")
                    ),
                }
            )
        if lane.get("persistent_review_degraded") is True:
            reason = (
                _optional_text(lane.get("persistent_review_degraded_reason"))
                or "unknown"
            )
            persistent_review_degraded_reasons.setdefault(reason, []).append(lane_id)
        if lane.get("review_peer_defaulted") is True:
            default_review_peer_routing.append(
                {
                    "lane_id": lane_id,
                    "status": status,
                    "peer_delivery_mode": peer_delivery_mode,
                    "peer_routing_mode": _optional_text(lane.get("peer_routing_mode")),
                    "peer_degraded_reason": _optional_text(
                        lane.get("peer_degraded_reason")
                    ),
                }
            )
        if _is_degraded_or_fallback_lane(lane, peer_delivery_mode):
            degraded_or_fallback_lanes.append(
                {
                    "lane_id": lane_id,
                    "status": status,
                    "peer_delivery_mode": peer_delivery_mode,
                    "review_delivery_mode": _optional_text(
                        lane.get("review_delivery_mode")
                    ),
                    "peer_routing_mode": _optional_text(lane.get("peer_routing_mode")),
                    "review_peer_id": _optional_text(lane.get("review_peer_id")),
                    "peer_request_id": _optional_text(lane.get("peer_request_id")),
                    "failure_reason": _optional_text(lane.get("failure_reason")),
                    "peer_degraded_reason": _optional_text(
                        lane.get("peer_degraded_reason")
                    ),
                    "persistent_review_degraded_reason": _optional_text(
                        lane.get("persistent_review_degraded_reason")
                    ),
                    "review_peer_defaulted": lane.get("review_peer_defaulted") is True,
                }
            )

    return {
        "counts_by_delivery_mode": counts_by_delivery_mode,
        "configured_peer_lanes": configured_peer_lanes,
        "required_peer_failures": required_peer_failures,
        "persistent_review_degraded_reasons": persistent_review_degraded_reasons,
        "default_review_peer_routing": default_review_peer_routing,
        "degraded_or_fallback_lanes": degraded_or_fallback_lanes,
    }


def summarize_provider_selection_visibility(
    lanes: list[dict[str, Any]],
    *,
    xmuse_root: Path | None = None,
) -> dict[str, Any]:
    """Summarize provider selection and provider fallback from runtime read models."""
    empty = {
        "counts_by_selected_profile": {},
        "counts_by_task_type": {},
        "fallback_causes": {},
        "fallback_lanes": [],
    }
    if xmuse_root is None:
        return empty

    lane_ids = {
        lane_id
        for lane in lanes
        if (lane_id := _lane_id(lane)) != "unknown"
    }
    if not lane_ids:
        return empty

    from xmuse_core.providers.selection_record import ProviderSelectionRecordStore

    records = ProviderSelectionRecordStore.from_xmuse_root(xmuse_root).list_records()
    if not records:
        return empty

    latest_records_by_lane: dict[str, Any] = {}
    for record in records:
        if record.lane_id not in lane_ids or record.lane_id in latest_records_by_lane:
            continue
        latest_records_by_lane[record.lane_id] = record

    counts_by_selected_profile: dict[str, int] = {}
    counts_by_task_type: dict[str, int] = {}
    fallback_causes: dict[str, list[str]] = {}
    fallback_lanes: list[dict[str, Any]] = []

    for record in latest_records_by_lane.values():
        selected_profile_ref = record.provider_profile_ref
        counts_by_selected_profile[selected_profile_ref] = (
            counts_by_selected_profile.get(selected_profile_ref, 0) + 1
        )
        task_type = record.task_type.value
        counts_by_task_type[task_type] = counts_by_task_type.get(task_type, 0) + 1

        fallback_cause = _optional_text(record.fallback_cause)
        if fallback_cause is None:
            continue
        lane_ids_for_cause = fallback_causes.setdefault(fallback_cause, [])
        if record.lane_id not in lane_ids_for_cause:
            lane_ids_for_cause.append(record.lane_id)
        fallback_lanes.append(
            {
                "lane_id": record.lane_id,
                "selected_profile_ref": selected_profile_ref,
                "task_type": task_type,
                "fallback_cause": fallback_cause,
                "health_failure_kind": (
                    _optional_text(record.health_failure_kind) or fallback_cause
                ),
                "source_authority": record.source_authority,
            }
        )

    return {
        "counts_by_selected_profile": counts_by_selected_profile,
        "counts_by_task_type": counts_by_task_type,
        "fallback_causes": fallback_causes,
        "fallback_lanes": fallback_lanes,
    }


def summarize_model_policy_selection(lanes: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize additive model-policy selection records without mutating lanes."""
    counts_by_model_tier: dict[str, int] = {}
    counts_by_lane_risk: dict[str, int] = {}
    counts_by_task_type: dict[str, int] = {}
    counts_by_selected_model: dict[str, int] = {}
    counts_by_selection_reason: dict[str, int] = {}
    by_model_tier: dict[str, dict[str, Any]] = {}
    lanes_with_model_policy = 0
    lanes_with_selection_records = 0
    review_rework_summaries = {
        summary["lane_id"]: summary for summary in classify_review_rework_lanes(lanes)
    }

    for lane in lanes:
        if lane.get("model_policy_enabled") is True:
            lanes_with_model_policy += 1
        records = lane.get("model_selection_records")
        if not isinstance(records, list):
            continue
        valid_records = [record for record in records if isinstance(record, dict)]
        if not valid_records:
            continue
        lanes_with_selection_records += 1
        lane_id = _lane_id(lane)
        lane_summary = review_rework_summaries.get(lane_id)
        is_rework_lane = _lane_has_rework_history(
            lane,
            lane_summary=lane_summary,
        )
        is_review_rejection_lane = _lane_has_review_rejection_history(
            lane,
            lane_summary=lane_summary,
        )
        lane_cost_share = _lane_level_model_cost_usd(lane, record_count=len(valid_records))
        tiers_seen_for_lane: set[str] = set()
        for record in valid_records:
            model_tier = _normalized_text(record.get("model_tier"))
            if model_tier is None:
                continue
            _increment_summary_count(
                counts_by_model_tier,
                model_tier,
            )
            _increment_summary_count(
                counts_by_lane_risk,
                record.get("lane_risk"),
            )
            _increment_summary_count(
                counts_by_task_type,
                record.get("task_type"),
            )
            _increment_summary_count(
                counts_by_selected_model,
                record.get("selected_model"),
            )
            _increment_summary_count(
                counts_by_selection_reason,
                record.get("selection_reason"),
            )
            tier_entry = by_model_tier.setdefault(
                model_tier,
                _empty_model_tier_summary(),
            )
            tier_entry["selection_count"] += 1
            tier_entry["total_cost_usd"] += _record_cost_usd(
                record,
                lane_cost_share=lane_cost_share,
            )
            if model_tier in tiers_seen_for_lane:
                continue
            tiers_seen_for_lane.add(model_tier)
            tier_entry["lane_count"] += 1
            if is_rework_lane:
                tier_entry["rework_lane_count"] += 1
            if is_review_rejection_lane:
                tier_entry["review_rejection_lane_count"] += 1

    finalized_by_model_tier: dict[str, dict[str, Any]] = {}
    for model_tier, tier_entry in by_model_tier.items():
        lane_count = int(tier_entry["lane_count"])
        rework_lane_count = int(tier_entry["rework_lane_count"])
        review_rejection_lane_count = int(tier_entry["review_rejection_lane_count"])
        finalized_by_model_tier[model_tier] = {
            "selection_count": int(tier_entry["selection_count"]),
            "lane_count": lane_count,
            "total_cost_usd": _round_metric(float(tier_entry["total_cost_usd"])),
            "rework_lane_count": rework_lane_count,
            "review_rejection_lane_count": review_rejection_lane_count,
            "rework_rate": _round_metric(
                rework_lane_count / lane_count if lane_count else 0.0
            ),
            "review_rejection_rate": _round_metric(
                review_rejection_lane_count / lane_count if lane_count else 0.0
            ),
        }

    return {
        "lanes_with_model_policy": lanes_with_model_policy,
        "lanes_with_selection_records": lanes_with_selection_records,
        "counts_by_model_tier": counts_by_model_tier,
        "counts_by_lane_risk": counts_by_lane_risk,
        "counts_by_task_type": counts_by_task_type,
        "counts_by_selected_model": counts_by_selected_model,
        "counts_by_selection_reason": counts_by_selection_reason,
        "by_model_tier": finalized_by_model_tier,
    }


def _increment_summary_count(counts: dict[str, int], value: Any) -> None:
    if not isinstance(value, str):
        return
    normalized = value.strip()
    if not normalized:
        return
    counts[normalized] = counts.get(normalized, 0) + 1


def _dedupe_lane_ids(lane_ids: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for lane_id in lane_ids:
        normalized = lane_id.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def _empty_model_tier_summary() -> dict[str, float | int]:
    return {
        "selection_count": 0,
        "lane_count": 0,
        "total_cost_usd": 0.0,
        "rework_lane_count": 0,
        "review_rejection_lane_count": 0,
    }


def _lane_level_model_cost_usd(lane: dict[str, Any], *, record_count: int) -> float:
    for key in ("model_cost_usd", "estimated_cost_usd", "cost_usd"):
        value = _coerce_cost(lane.get(key))
        if value is not None:
            return value / record_count if record_count > 0 else 0.0
    return 0.0


def _record_cost_usd(record: dict[str, Any], *, lane_cost_share: float) -> float:
    for key in ("estimated_cost_usd", "model_cost_usd", "cost_usd"):
        value = _coerce_cost(record.get(key))
        if value is not None:
            return value
    return lane_cost_share


def _coerce_cost(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    return None


def _normalized_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _round_metric(value: float) -> float:
    return round(value, 6)


def build_run_health_model(
    lanes_path: Path,
    *,
    now: float | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    live_pids: set[int] | None = None,
    runner_pids: list[int] | None = None,
    mcp_pids: list[int] | None = None,
    process_inventory: dict[str, Any] | None = None,
    xmuse_root: Path | None = None,
) -> dict[str, Any]:
    """Build a read-only operational health model from lanes and process evidence."""
    if lanes_path.exists():
        payload = json.loads(lanes_path.read_text(encoding="utf-8"))
    else:
        payload = {"lanes": []}
    lanes = payload.get("lanes")
    if not isinstance(lanes, list):
        raise ValueError(f"lanes file does not contain a lane list: {lanes_path}")

    return build_run_health_model_from_lanes(
        [lane for lane in lanes if isinstance(lane, dict)],
        now=now,
        stale_after_s=stale_after_s,
        live_pids=live_pids,
        runner_pids=runner_pids,
        mcp_pids=mcp_pids,
        process_inventory=process_inventory,
        xmuse_root=lanes_path.parent if xmuse_root is None else xmuse_root,
    )


def build_run_health_scope(
    *,
    conversation_id: str | None = None,
    workspace_id: str | None = None,
) -> dict[str, Any]:
    scoped_conversation_id = conversation_id or workspace_id
    scoped_workspace_id = workspace_id or scoped_conversation_id
    return {
        "kind": "conversation" if scoped_conversation_id is not None else "global",
        "conversation_id": scoped_conversation_id,
        "workspace_id": scoped_workspace_id,
    }


def build_run_health_model_from_lanes(
    lanes: list[dict[str, Any]],
    *,
    now: float | None = None,
    stale_after_s: float = DEFAULT_STALE_AFTER_S,
    live_pids: set[int] | None = None,
    runner_pids: list[int] | None = None,
    mcp_pids: list[int] | None = None,
    process_inventory: dict[str, Any] | None = None,
    xmuse_root: Path | None = None,
    scope: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a run-health read model from an already selected lane set."""

    current_live_pids = live_pids if live_pids is not None else list_live_pids()
    inventory = process_inventory
    if inventory is None:
        discovered_inventory: dict[str, Any] | None = None
        if runner_pids is None or mcp_pids is None:
            discovered_inventory = discover_xmuse_runtime_processes()
        extra_services = (
            {
                item["service"]: item["pids"]
                for item in discovered_inventory.get("services", [])
                if isinstance(item, dict)
                and item.get("service") not in {"runner", "mcp"}
                and isinstance(item.get("pids"), list)
            }
            if discovered_inventory is not None
            else None
        )
        inventory = build_process_inventory(
            runner_pids=(
                discovered_inventory["runner_pids"]
                if runner_pids is None and discovered_inventory is not None
                else runner_pids
            ),
            mcp_pids=(
                discovered_inventory["mcp_pids"]
                if mcp_pids is None and discovered_inventory is not None
                else mcp_pids
            ),
            services=extra_services,
        )
    if runner_pids is None:
        runner_pids = list(inventory["runner_pids"])
    if mcp_pids is None:
        mcp_pids = list(inventory["mcp_pids"])

    summary = summarize_run_health(
        [lane for lane in lanes if isinstance(lane, dict)],
        now=now,
        stale_after_s=stale_after_s,
        live_pids=current_live_pids,
        xmuse_root=xmuse_root,
    )
    processes = {
        "runner_count": len(runner_pids),
        "mcp_count": len(mcp_pids),
        "runner_pids": sorted(runner_pids),
        "mcp_pids": sorted(mcp_pids),
        "services": inventory["services"],
        "counts_by_service": inventory["counts_by_service"],
        "evidence": inventory["evidence"],
    }
    return {
        **summary,
        "scope": _normalize_run_health_scope(scope),
        "coordinator": summarize_coordinator_incidents(
            xmuse_root=xmuse_root,
            active_runner_ids={f"runner-{pid}" for pid in runner_pids},
        ),
        "processes": processes,
        "warnings": _process_warnings(
            runner_count=processes["runner_count"],
            mcp_count=processes["mcp_count"],
            process_inventory=inventory,
        ),
    }


def _normalize_run_health_scope(scope: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(scope, dict):
        return build_run_health_scope()
    return build_run_health_scope(
        conversation_id=_optional_text(scope.get("conversation_id")),
        workspace_id=_optional_text(scope.get("workspace_id")),
    )


def _is_retrying(lane: dict[str, Any]) -> bool:
    return _positive_int(lane.get("retry_count")) or _positive_int(
        lane.get("review_retry_count")
    )


def _is_blocked(lane: dict[str, Any]) -> bool:
    return lane.get("status") == "awaiting_final_action" or lane.get(
        "failure_reason"
    ) == "merge_context_missing"


def _unsafe_to_release_dependents(lane: dict[str, Any]) -> bool:
    status = lane.get("status")
    if status not in {"merged", "done", "completed"}:
        return False
    if lane.get("integration_mode") == "noop":
        return False
    return not lane.get("branch") or not lane.get("worktree")


def _is_stale(
    lane: dict[str, Any],
    *,
    status: str,
    now: float,
    stale_after_s: float,
    live_pids: set[int] | None,
) -> bool:
    worker_pid = lane.get("worker_pid")
    if (
        isinstance(worker_pid, int)
        and not isinstance(worker_pid, bool)
        and live_pids is not None
    ):
        if worker_pid in live_pids:
            return False
        if status == "dispatched":
            return True
    timestamp = _active_timestamp(lane)
    if timestamp is None:
        return False
    return now - timestamp > stale_after_s


def _active_timestamp(lane: dict[str, Any]) -> float | None:
    for key in ("review_started_at", "dispatched_at", "executed_at"):
        value = lane.get(key)
        if isinstance(value, int | float) and not isinstance(value, bool):
            return float(value)
    return None


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _optional_text(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    text = str(value).strip()
    return text or None


def _lane_id(lane: dict[str, Any]) -> str:
    return str(lane.get("feature_id") or lane.get("id") or "unknown")


def _lane_context_ref(lane: dict[str, Any], *, lane_id: str) -> str:
    explicit = _optional_text(lane.get("lane_context_ref")) or _optional_text(
        lane.get("lane_context_path")
    )
    if explicit is not None:
        return explicit
    safe_lane_id = "".join(
        char if char.isalnum() or char in {"-", "_", "."} else "-"
        for char in lane_id
    )
    return f"logs/lane_context/{safe_lane_id}/latest.json"


def _is_configured_peer_lane(
    lane: dict[str, Any],
    peer_delivery_mode: str | None,
) -> bool:
    return peer_delivery_mode == "configured_peer"


def _configured_peer_item(
    lane: dict[str, Any],
    lane_id: str,
    status: str,
) -> dict[str, Any]:
    return {
        "lane_id": lane_id,
        "status": status,
        "peer_routing_mode": _optional_text(lane.get("peer_routing_mode")),
        "peer_delivery_mode": _optional_text(lane.get("peer_delivery_mode")),
        "review_peer_id": _optional_text(lane.get("review_peer_id")),
        "peer_request_id": _optional_text(lane.get("peer_request_id")),
        "peer_degraded_reason": _optional_text(lane.get("peer_degraded_reason")),
        "review_peer_defaulted": lane.get("review_peer_defaulted") is True,
    }


def _is_required_peer_failure(
    lane: dict[str, Any],
    peer_delivery_mode: str | None,
) -> bool:
    return peer_delivery_mode == "required_peer_failed" or (
        _optional_text(lane.get("failure_reason")) in REQUIRED_PEER_FAILURE_REASONS
    )


def _is_degraded_or_fallback_lane(
    lane: dict[str, Any],
    peer_delivery_mode: str | None,
) -> bool:
    if peer_delivery_mode in PEER_DEGRADED_OR_FALLBACK_MODES:
        return True
    if lane.get("persistent_review_degraded") is True:
        return True
    return _optional_text(lane.get("failure_reason")) in REQUIRED_PEER_FAILURE_REASONS


def _is_current_retry_or_rework(lane: dict[str, Any] | None) -> bool:
    if lane is None:
        return False
    normalized = normalize_lane_state(lane)
    if normalized.is_terminal:
        return False
    return lane.get("status") == "reworking" or _is_retrying(lane)


def _is_historical_terminal_retry_metadata(lane: dict[str, Any] | None) -> bool:
    if lane is None:
        return False
    return normalize_lane_state(lane).is_terminal and _is_retrying(lane)


def _lane_has_rework_history(
    lane: dict[str, Any],
    *,
    lane_summary: dict[str, Any] | None,
) -> bool:
    if _is_current_retry_or_rework(lane) or _is_historical_terminal_retry_metadata(lane):
        return True
    if (
        lane_summary is not None
        and lane_summary["reason_category"]
        in {
            "semantic_rework",
            "review_rejection",
            "prompt_subsystem_mismatch",
            "gate_failure",
            "merge_conflict",
        }
    ):
        return True
    return _review_history_contains_decision(lane, "rework")


def _lane_has_review_rejection_history(
    lane: dict[str, Any],
    *,
    lane_summary: dict[str, Any] | None,
) -> bool:
    if (
        lane_summary is not None
        and lane_summary["reason_category"] == "review_rejection"
    ):
        return True
    return _review_history_contains_decision(lane, "rework")


def _review_history_contains_decision(lane: dict[str, Any], decision: str) -> bool:
    history = lane.get("review_history")
    if not isinstance(history, list):
        return False
    expected = decision.strip().lower()
    if not expected:
        return False
    for item in history:
        if not isinstance(item, dict):
            continue
        value = _optional_text(item.get("decision"))
        if value is not None and value.lower() == expected:
            return True
    return False


def _takeover_context_reason(
    lane: dict[str, Any],
    *,
    lane_id: str,
    stale_lane_ids: set[str],
    review_rework_category: str,
) -> str | None:
    if lane_id in stale_lane_ids:
        return "stale_worker"

    normalized = normalize_lane_state(lane)
    is_retry_or_rework = _is_current_retry_or_rework(lane)
    if is_retry_or_rework:
        if review_rework_category == "review_rejection":
            return "review_rejection"
        if review_rework_category == "semantic_rework":
            return "semantic_rework"
        if review_rework_category == "review_infra":
            return "review_infra_retry"
        if review_rework_category == "execution_infra":
            return "execution_infra_retry"
        if review_rework_category == "gate_failure":
            return "gate_failure_retry"
        if review_rework_category == "merge_conflict":
            return "merge_conflict"
        if review_rework_category == "prompt_subsystem_mismatch":
            return "prompt_subsystem_mismatch"
        if review_rework_category == "approved_review":
            return "approved_review_retry"
        return "unknown_retry_or_rework"

    if not normalized.is_terminal:
        return None
    if normalized.normalized_status == "merged":
        return None
    if review_rework_category == "review_infra":
        return "review_infra_failure"
    if review_rework_category == "execution_infra":
        return "execution_infra_failure"
    if review_rework_category == "gate_failure":
        return "gate_failure"
    if review_rework_category == "review_rejection":
        return "review_rejection"
    if review_rework_category == "semantic_rework":
        return "semantic_rework"
    if review_rework_category == "merge_conflict":
        return "merge_conflict"
    if review_rework_category == "prompt_subsystem_mismatch":
        return "prompt_subsystem_mismatch"
    if lane.get("failure_reason") or normalized.normalized_status in {
        "exec_failed",
        "gate_failed",
        "terminated",
    }:
        return "terminal_failure"
    return None


def _takeover_category_override(lane: dict[str, Any], category: str) -> str:
    merge_reason = _optional_text(lane.get("merge_failure_reason"))
    merge_detail = _optional_text(lane.get("merge_failure_detail"))
    if merge_reason and "conflict" in merge_reason.lower():
        return "merge_conflict"
    if merge_detail and "conflict" in merge_detail.lower():
        return "merge_conflict"

    failure_reason = _optional_text(lane.get("failure_reason"))
    if failure_reason in {
        "review_infra_unavailable",
        "review_spawn_failed",
        "review_non_zero_exit",
        "review_no_verdict",
        "review_timeout",
    }:
        return "review_infra"
    if failure_reason in {
        "execution_infra_unavailable",
        "execution_circuit_open",
        "non_zero_exit",
        "timeout",
    }:
        return "execution_infra"
    if failure_reason == "gate_failed" or lane.get("gate_passed") is False:
        return "gate_failure"
    if failure_reason in {"prompt_subsystem_mismatch", "prompt_mismatch"}:
        return "prompt_subsystem_mismatch"
    return category
