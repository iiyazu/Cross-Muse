from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from xmuse_core.chat.execution_cards import ChatExecutionCardEmitter
from xmuse_core.platform.event_bus import _read_json, _utc_timestamp, _write_json
from xmuse_core.platform.projection.allowlist import stamp_mutation_audit
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.platform.takeover_action_refs import (
    _current_writer_lease_id,
    _decision_evidence_refs,
    _decision_id,
    _ensure_action,
    _first_blueprint_ref,
    _lane_context_hash,
    _require_text,
    _requires_controlled_terminal_update,
    _should_persist_without_transition,
    _snapshot_lanes,
    _snapshot_projection_revision,
    _takeover_bundle_hash,
    _takeover_dedupe_key,
    _takeover_event_id,
    _takeover_reason,
    _takeover_started_summary,
    _validate_decision_evidence,
    _validate_resolution_applicable,
)
from xmuse_core.structuring.models import (
    ReviewGodTakeoverAction,
    ReviewGodTakeoverDecision,
)

_STARTED_EVENT = "run.takeover_started"
_RESOLVED_EVENT = "run.takeover_resolved"
_ABANDONED_EVENT = "lane.abandoned"
_AUDIT_FILE = "audit_events.json"
_CARD_INTENT_FILE = "read_models/execution_card_intents.json"
_TAKEOVER_ACTION_HANDLERS: dict[ReviewGodTakeoverAction, str] = {
    ReviewGodTakeoverAction.REPAIR_AND_MERGE: "repair_and_merge",
    ReviewGodTakeoverAction.REQUEUE_WITH_CONTEXT: "requeue_with_context",
    ReviewGodTakeoverAction.ABANDON_LANE: "abandon_lane",
    ReviewGodTakeoverAction.SELF_CORRECTION_THEN_ABANDON: "self_correction_then_abandon",
    ReviewGodTakeoverAction.ESCALATE_TO_HUMAN_OR_OUTER_GOD: "escalate_to_human_or_outer_god",
}


def apply_takeover_decision(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None = None,
    guard: dict[str, Any] | None = None,
) -> dict[str, str]:
    handler_name = _TAKEOVER_ACTION_HANDLERS[decision.action]
    handler = globals()[handler_name]
    return handler(
        state_machine=state_machine,
        xmuse_root=xmuse_root,
        event_bus=event_bus,
        decision=decision,
        audit=audit,
        created_at=created_at,
        guard=guard,
    )


def record_takeover_started(
    *,
    lane: dict[str, Any],
    xmuse_root: Path,
    event_bus: Any,
    takeover_reason: str,
    audit: dict[str, str],
    created_at: str | None = None,
) -> dict[str, str]:
    payload = _takeover_payload(
        lane=lane,
        audit=audit,
        takeover_reason=takeover_reason,
        decision=None,
        event_type=_STARTED_EVENT,
        created_at=created_at,
    )
    event = _upsert_audit_event(event_bus=event_bus, payload=payload)
    emitter = ChatExecutionCardEmitter(xmuse_root)
    intent = emitter.emit_run_takeover(
        conversation_id=payload["conversation_id"],
        planning_run_id=payload["planning_run_id"],
        lane_id=payload["lane_id"],
        takeover_reason=takeover_reason,
        created_at=payload["created_at"],
        summary=payload["summary"],
        payload=payload,
        dedupe_suffix=payload["dedupe_key"],
    )
    return {
        "event_id": str(event["event_id"]),
        "audit_event_ref": f"{_AUDIT_FILE}#{event['event_id']}",
        "chat_card_ref": f"{_CARD_INTENT_FILE}#{intent.intent_id}",
    }


def requeue_with_context(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None = None,
    guard: dict[str, Any] | None = None,
) -> dict[str, str]:
    _ensure_action(decision, ReviewGodTakeoverAction.REQUEUE_WITH_CONTEXT)
    return _apply_takeover_resolution(
        state_machine=state_machine,
        xmuse_root=xmuse_root,
        event_bus=event_bus,
        decision=decision,
        audit=audit,
        created_at=created_at,
        target_status="reworking",
        extra_metadata={
            "reason": decision.summary,
            "rework_context": decision.summary,
            "takeover_retry_override": True,
        },
        guard=guard,
    )


def abandon_lane(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None = None,
    guard: dict[str, Any] | None = None,
) -> dict[str, str]:
    _ensure_action(decision, ReviewGodTakeoverAction.ABANDON_LANE)
    return _abandon_with_resolution(
        state_machine=state_machine,
        xmuse_root=xmuse_root,
        event_bus=event_bus,
        decision=decision,
        audit=audit,
        created_at=created_at,
        guard=guard,
    )


def self_correction_then_abandon(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None = None,
    guard: dict[str, Any] | None = None,
) -> dict[str, str]:
    _ensure_action(decision, ReviewGodTakeoverAction.SELF_CORRECTION_THEN_ABANDON)
    return _abandon_with_resolution(
        state_machine=state_machine,
        xmuse_root=xmuse_root,
        event_bus=event_bus,
        decision=decision,
        audit=audit,
        created_at=created_at,
        guard=guard,
    )


def _abandon_with_resolution(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None,
    guard: dict[str, Any] | None,
) -> dict[str, str]:
    result = _apply_takeover_resolution(
        state_machine=state_machine,
        xmuse_root=xmuse_root,
        event_bus=event_bus,
        decision=decision,
        audit=audit,
        created_at=created_at,
        target_status="failed",
        extra_metadata=_abandon_metadata(decision),
        guard=guard,
    )
    lane = state_machine.get_lane(decision.lane_id)
    payload = _takeover_payload(
        lane=lane,
        audit=audit,
        takeover_reason=_takeover_reason(lane),
        decision=decision,
        event_type=_ABANDONED_EVENT,
        created_at=created_at,
        resolved_audit_event_ref=result["audit_event_ref"],
    )
    abandoned_event = _upsert_audit_event(event_bus=event_bus, payload=payload)
    abandoned_audit_ref = f"{_AUDIT_FILE}#{abandoned_event['event_id']}"
    abandoned_card_ref = _emit_resolution_card(
        xmuse_root=xmuse_root,
        payload=payload,
        decision_id=result["decision_id"],
        evidence_refs=_decision_evidence_refs(
            decision,
            resolved_audit_event_ref=result["audit_event_ref"],
        ),
        status="abandoned",
        title="Run takeover abandoned",
    )
    _merge_audit_event_metadata(
        event_bus=event_bus,
        event_ref=abandoned_audit_ref,
        metadata={"chat_card_ref": abandoned_card_ref},
    )
    state_machine.update_metadata(
        decision.lane_id,
        stamp_mutation_audit(
            {
                "takeover_abandoned_event_ref": abandoned_audit_ref,
                "takeover_abandoned_card_ref": abandoned_card_ref,
            },
            audit=audit,
            tool_name="takeover_actions",
        ),
        guard=_build_takeover_mutation_guard(
            guard=_current_takeover_guard(
                state_machine=state_machine,
                xmuse_root=xmuse_root,
                lane_id=decision.lane_id,
            ),
            state_machine=state_machine,
            xmuse_root=xmuse_root,
        ),
    )
    result["abandoned_audit_event_ref"] = abandoned_audit_ref
    result["abandoned_chat_card_ref"] = abandoned_card_ref
    return result


def escalate_to_human_or_outer_god(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None = None,
    guard: dict[str, Any] | None = None,
) -> dict[str, str]:
    _ensure_action(decision, ReviewGodTakeoverAction.ESCALATE_TO_HUMAN_OR_OUTER_GOD)
    return _apply_takeover_resolution(
        state_machine=state_machine,
        xmuse_root=xmuse_root,
        event_bus=event_bus,
        decision=decision,
        audit=audit,
        created_at=created_at,
        target_status=None,
        extra_metadata={
            "reason": decision.summary,
        },
        guard=guard,
    )


def repair_and_merge(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None = None,
    guard: dict[str, Any] | None = None,
) -> dict[str, str]:
    _ensure_action(decision, ReviewGodTakeoverAction.REPAIR_AND_MERGE)
    return _apply_takeover_resolution(
        state_machine=state_machine,
        xmuse_root=xmuse_root,
        event_bus=event_bus,
        decision=decision,
        audit=audit,
        created_at=created_at,
        target_status="merged",
        extra_metadata={
            "reason": decision.summary,
            "outer_god_takeover": True,
        },
        guard=guard,
    )


def _apply_takeover_resolution(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    event_bus: Any,
    decision: ReviewGodTakeoverDecision,
    audit: dict[str, str],
    created_at: str | None,
    target_status: str | None,
    extra_metadata: dict[str, Any],
    guard: dict[str, Any] | None,
) -> dict[str, str]:
    lane = state_machine.get_lane(decision.lane_id)
    current_status = str(lane.get("status") or "")
    _validate_decision_evidence(decision, lane=lane, xmuse_root=xmuse_root)
    decision_id = _decision_id(decision, audit=audit)
    existing_decision_id = str(lane.get("takeover_decision_id") or "")
    if existing_decision_id == decision_id:
        existing_ref = str(lane.get("takeover_resolved_event_ref") or "")
        existing_card_ref = str(lane.get("takeover_resolved_card_ref") or "")
        return {
            "decision_id": decision_id,
            "audit_event_ref": existing_ref,
            "chat_card_ref": existing_card_ref,
        }
    resolved_at = created_at or _utc_timestamp()
    normalized_guard = _require_takeover_guard(
        guard=guard,
        lane=lane,
        state_machine=state_machine,
        xmuse_root=xmuse_root,
    )
    policy_metadata = _validate_takeover_action_policy(
        lane=lane,
        action=decision.action,
        created_at=resolved_at,
    )
    _validate_resolution_applicable(current_status=current_status, target_status=target_status)

    payload = _takeover_payload(
        lane=lane,
        audit=audit,
        takeover_reason=_takeover_reason(lane),
        decision=decision,
        event_type=_RESOLVED_EVENT,
        created_at=resolved_at,
    )
    event = _upsert_audit_event(event_bus=event_bus, payload=payload)
    audit_event_ref = f"{_AUDIT_FILE}#{event['event_id']}"
    evidence_refs = _decision_evidence_refs(decision, resolved_audit_event_ref=audit_event_ref)
    card_ref = _emit_resolution_card(
        xmuse_root=xmuse_root,
        payload=payload,
        decision_id=decision_id,
        evidence_refs=evidence_refs,
    )
    _merge_audit_event_metadata(
        event_bus=event_bus,
        event_ref=audit_event_ref,
        metadata={"chat_card_ref": card_ref, "takeover_resolved_card_ref": card_ref},
    )
    metadata = stamp_mutation_audit(
        {
            "takeover_action": decision.action.value,
            "takeover_decision_id": decision_id,
            "takeover_evidence_ref": decision.evidence.takeover_context_ref,
            "takeover_evidence_refs": evidence_refs,
            "takeover_started_event_ref": decision.evidence.audit_event_ref,
            "takeover_resolved_event_ref": audit_event_ref,
            "takeover_resolved_card_ref": card_ref,
            "review_summary": decision.summary,
            **policy_metadata,
            **extra_metadata,
            **_abandon_metadata(decision),
            **_self_correction_metadata(decision),
        },
        audit=audit,
        tool_name="takeover_actions",
    )
    mutation_guard = _build_takeover_mutation_guard(
        guard=normalized_guard,
        state_machine=state_machine,
        xmuse_root=xmuse_root,
    )
    try:
        if _requires_controlled_terminal_update(
            current_status=current_status,
            target_status=target_status,
        ):
            state_machine.controlled_terminal_update(
                decision.lane_id,
                target_status,
                metadata=metadata,
                guard=mutation_guard,
            )
        elif _should_persist_without_transition(
            current_status=current_status,
            target_status=target_status,
        ):
            state_machine.update_metadata(
                decision.lane_id,
                metadata,
                guard=mutation_guard,
            )
        else:
            state_machine.transition(
                decision.lane_id,
                target_status,
                metadata=metadata,
                guard=mutation_guard,
            )
    except Exception:
        if not _takeover_resolution_committed(
            state_machine=state_machine,
            lane_id=decision.lane_id,
            decision_id=decision_id,
            audit_event_ref=audit_event_ref,
            chat_card_ref=card_ref,
        ):
            _discard_resolution_artifacts(
                event_bus=event_bus,
                xmuse_root=xmuse_root,
                audit_event_ref=audit_event_ref,
                chat_card_ref=card_ref,
            )
        raise
    return {
        "decision_id": decision_id,
        "audit_event_ref": audit_event_ref,
        "chat_card_ref": card_ref,
    }


def _require_takeover_guard(
    *,
    guard: dict[str, Any] | None,
    lane: dict[str, Any],
    state_machine: LaneStateMachine,
    xmuse_root: Path,
) -> dict[str, Any]:
    normalized_guard = normalize_takeover_guard(guard)
    validate_takeover_guard(
        guard=normalized_guard,
        lane=lane,
        all_lanes=state_machine.get_lanes(),
        lanes_path=state_machine._path,
        xmuse_root=xmuse_root,
        projection_revision=state_machine.current_projection_revision(),
    )
    return normalized_guard


def _validate_takeover_action_policy(
    *,
    lane: dict[str, Any],
    action: ReviewGodTakeoverAction,
    created_at: str,
) -> dict[str, Any]:
    lane_id = _require_text(lane.get("feature_id"), "lane_id")
    takeover_attempt_id = _required_lane_text(lane, "takeover_attempt_id")
    _required_lane_text(lane, "lease_owner")
    _required_lane_text(lane, "lease_expires_at")
    _required_lane_text(lane, "evidence_bundle_id")
    _required_lane_text(lane, "graph_set_id")
    _required_lane_text(lane, "feature_plan_id")
    max_attempts_by_reason = _required_attempt_policy(lane)
    takeover_attempt_cap = _required_lane_non_negative_int(lane, "takeover_attempt_cap")
    cooldown_seconds = _required_cooldown_seconds(lane)
    _required_lane_text(lane, "terminal_escalation_policy")
    current_attempt_count = _lane_non_negative_int(
        lane.get("takeover_action_attempt_count"),
        default=0,
    )
    if current_attempt_count >= takeover_attempt_cap:
        raise ValueError(
            f"takeover_attempt_cap exceeded for {lane_id}: "
            f"{current_attempt_count}/{takeover_attempt_cap}"
        )

    takeover_reason = _takeover_reason(lane)
    reason_counts = _lane_attempt_counts(lane.get("takeover_reason_attempt_counts"))
    reason_limit = max_attempts_by_reason.get(takeover_reason)
    current_reason_count = reason_counts.get(takeover_reason, 0)
    if reason_limit is not None and current_reason_count >= reason_limit:
        raise ValueError(
            f"max_attempts_by_reason exceeded for {lane_id}: "
            f"{takeover_reason}={current_reason_count}/{reason_limit}"
        )

    current_time = _parse_utc_timestamp(created_at)
    cooldown_deadline = _cooldown_deadline(
        lane=lane,
        created_at=current_time,
        cooldown_seconds=cooldown_seconds,
    )
    if cooldown_deadline is not None and current_time < cooldown_deadline:
        raise ValueError(
            f"takeover cooldown active for {lane_id} until "
            f"{_format_utc_timestamp(cooldown_deadline)}"
        )

    next_reason_counts = dict(reason_counts)
    next_reason_counts[takeover_reason] = current_reason_count + 1
    next_cooldown_deadline = current_time + timedelta(seconds=cooldown_seconds)
    return {
        "takeover_attempt_id": takeover_attempt_id,
        "takeover_last_action": action.value,
        "takeover_last_action_reason": takeover_reason,
        "takeover_last_action_at": _format_utc_timestamp(current_time),
        "takeover_cooldown_until": _format_utc_timestamp(next_cooldown_deadline),
        "takeover_action_attempt_count": current_attempt_count + 1,
        "takeover_reason_attempt_counts": next_reason_counts,
    }


def _required_lane_text(lane: dict[str, Any], field_name: str) -> str:
    value = lane.get(field_name)
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"takeover action requires lane.{field_name}")


def _required_lane_non_negative_int(lane: dict[str, Any], field_name: str) -> int:
    value = lane.get(field_name)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"takeover action requires lane.{field_name}")
    return value


def _required_cooldown_seconds(lane: dict[str, Any]) -> int:
    value = lane.get("takeover_cooldown_seconds")
    if value is None:
        value = lane.get("cooldown_seconds")
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("takeover action requires lane.takeover_cooldown_seconds")
    return value


def _required_attempt_policy(lane: dict[str, Any]) -> dict[str, int]:
    value = lane.get("max_attempts_by_reason")
    if not isinstance(value, dict) or not value:
        raise ValueError("takeover action requires lane.max_attempts_by_reason")
    cleaned: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("takeover action requires lane.max_attempts_by_reason")
        if not isinstance(item, int) or isinstance(item, bool) or item < 0:
            raise ValueError("takeover action requires lane.max_attempts_by_reason")
        cleaned[key.strip()] = item
    return cleaned


def _lane_attempt_counts(value: Any) -> dict[str, int]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("takeover_reason_attempt_counts must be a mapping")
    cleaned: dict[str, int] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key.strip():
            raise ValueError("takeover_reason_attempt_counts must use non-empty keys")
        cleaned[key.strip()] = _lane_non_negative_int(item)
    return cleaned


def _lane_non_negative_int(value: Any, *, default: int | None = None) -> int:
    if value is None and default is not None:
        return default
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("takeover attempt counters must be non-negative integers")
    return value


def _current_takeover_guard(
    *,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
    lane_id: str,
) -> dict[str, Any]:
    lane = state_machine.get_lane(lane_id)
    all_lanes = state_machine.get_lanes()
    return normalize_takeover_guard(
        {
            "lane_status": str(lane.get("status") or ""),
            "projection_revision": state_machine.current_projection_revision(),
            "lease_id": _current_writer_lease_id(state_machine._path)
            or _required_lane_text(lane, "lease_id"),
            "lane_context_hash": _lane_context_hash(
                lane,
                xmuse_root=xmuse_root,
                all_lanes=all_lanes,
            ),
            "evidence_bundle_hash": _takeover_bundle_hash(
                lane,
                xmuse_root=xmuse_root,
                all_lanes=all_lanes,
            ),
        }
    )


def _cooldown_deadline(
    *,
    lane: dict[str, Any],
    created_at: datetime,
    cooldown_seconds: int,
) -> datetime | None:
    explicit_deadline = lane.get("takeover_cooldown_until")
    if isinstance(explicit_deadline, str) and explicit_deadline.strip():
        return _parse_utc_timestamp(explicit_deadline)
    last_action_at = lane.get("takeover_last_action_at")
    if isinstance(last_action_at, str) and last_action_at.strip():
        return _parse_utc_timestamp(last_action_at) + timedelta(seconds=cooldown_seconds)
    del created_at
    return None


def _parse_utc_timestamp(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _format_utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_takeover_guard(guard: Any) -> dict[str, Any]:
    tool_name = "apply_takeover_decision"
    if not isinstance(guard, dict):
        raise ValueError(f"{tool_name} requires guard.lane_status")

    lane_status = guard.get("lane_status")
    if not isinstance(lane_status, str) or not lane_status.strip():
        raise ValueError(f"{tool_name} guard.lane_status is required")

    projection_revision = guard.get("projection_revision")
    if not isinstance(projection_revision, int) or isinstance(projection_revision, bool):
        raise ValueError(f"{tool_name} guard.projection_revision must be a non-negative integer")
    if projection_revision < 0:
        raise ValueError(f"{tool_name} guard.projection_revision must be a non-negative integer")

    lease_id = guard.get("lease_id")
    if not isinstance(lease_id, str) or not lease_id.strip():
        raise ValueError(f"{tool_name} guard.lease_id is required")

    lane_context_hash = guard.get("lane_context_hash")
    if not isinstance(lane_context_hash, str) or not lane_context_hash.strip():
        raise ValueError(f"{tool_name} guard.lane_context_hash is required")

    evidence_bundle_hash = guard.get("evidence_bundle_hash")
    if not isinstance(evidence_bundle_hash, str) or not evidence_bundle_hash.strip():
        raise ValueError(f"{tool_name} guard.evidence_bundle_hash is required")

    return {
        "lane_status": lane_status.strip(),
        "projection_revision": projection_revision,
        "lease_id": lease_id.strip(),
        "lane_context_hash": lane_context_hash.strip(),
        "evidence_bundle_hash": evidence_bundle_hash.strip(),
    }


def _takeover_resolution_committed(
    *,
    state_machine: LaneStateMachine,
    lane_id: str,
    decision_id: str,
    audit_event_ref: str,
    chat_card_ref: str,
) -> bool:
    try:
        lane = state_machine.get_lane(lane_id)
    except Exception:
        return False
    return (
        lane.get("takeover_decision_id") == decision_id
        and lane.get("takeover_resolved_event_ref") == audit_event_ref
        and lane.get("takeover_resolved_card_ref") == chat_card_ref
    )


def validate_takeover_guard(
    *,
    guard: dict[str, Any],
    lane: dict[str, Any],
    all_lanes: list[dict[str, Any]],
    lanes_path: Path,
    xmuse_root: Path,
    projection_revision: int,
) -> None:
    tool_name = "apply_takeover_decision"
    actual_status = str(lane.get("status") or "")
    if actual_status != guard["lane_status"]:
        raise ValueError(
            f"{tool_name} guard.lane_status mismatch: expected {actual_status}"
        )
    if projection_revision != guard["projection_revision"]:
        raise ValueError(
            f"{tool_name} guard.projection_revision mismatch: expected {projection_revision}"
        )

    current_lease_id = _current_writer_lease_id(lanes_path)
    if current_lease_id != guard["lease_id"]:
        expected = current_lease_id or "missing"
        raise ValueError(f"{tool_name} guard.lease_id mismatch: expected {expected}")

    lane_context_hash = _lane_context_hash(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    if lane_context_hash != guard["lane_context_hash"]:
        raise ValueError(
            f"{tool_name} guard.lane_context_hash mismatch: expected {lane_context_hash}"
        )

    evidence_bundle_hash = _takeover_bundle_hash(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    if evidence_bundle_hash != guard["evidence_bundle_hash"]:
        raise ValueError(
            f"{tool_name} guard.evidence_bundle_hash mismatch: expected {evidence_bundle_hash}"
        )


def _build_takeover_mutation_guard(
    *,
    guard: dict[str, Any] | None,
    state_machine: LaneStateMachine,
    xmuse_root: Path,
):
    if guard is None:
        return None

    def validate(lane: dict[str, Any], data: dict[str, Any]) -> None:
        validate_takeover_guard(
            guard=guard,
            lane=lane,
            all_lanes=_snapshot_lanes(data),
            lanes_path=state_machine._path,
            xmuse_root=xmuse_root,
            projection_revision=_snapshot_projection_revision(data),
        )

    return validate


def _takeover_payload(
    *,
    lane: dict[str, Any],
    audit: dict[str, str],
    takeover_reason: str,
    decision: ReviewGodTakeoverDecision | None,
    event_type: str,
    created_at: str | None,
    resolved_audit_event_ref: str | None = None,
) -> dict[str, Any]:
    planning_run_id = _require_text(
        lane.get("planning_run_id") or lane.get("source_run_id") or lane.get("graph_id"),
        "planning_run_id",
    )
    conversation_id = _require_text(lane.get("conversation_id"), "conversation_id")
    blueprint_ref = _first_blueprint_ref(lane)
    payload: dict[str, Any] = {
        "event_id": _takeover_event_id(
            event_type=event_type,
            lane_id=_require_text(lane.get("feature_id"), "lane_id"),
            request_id=audit["request_id"],
            action=decision.action.value if decision is not None else "started",
        ),
        "dedupe_key": _takeover_dedupe_key(
            planning_run_id=planning_run_id,
            lane_id=_require_text(lane.get("feature_id"), "lane_id"),
            request_id=audit["request_id"],
            event_type=event_type,
            action=decision.action.value if decision is not None else "started",
        ),
        "planning_run_id": planning_run_id,
        "conversation_id": conversation_id,
        "blueprint_ref": blueprint_ref,
        "actor_session_id": audit["actor"],
        "request_id": audit["request_id"],
        "decision": decision.action.value if decision is not None else "takeover_started",
        "evidence_refs": (
            _decision_evidence_refs(
                decision,
                resolved_audit_event_ref=resolved_audit_event_ref,
            )
            if decision is not None
            else []
        ),
        "risk_level": lane.get("risk_level"),
        "degraded_reason": lane.get("degraded_reason"),
        "lane_id": _require_text(lane.get("feature_id"), "lane_id"),
        "takeover_reason": takeover_reason,
        "event_type": event_type,
        "created_at": created_at or _utc_timestamp(),
        "summary": decision.summary if decision is not None else _takeover_started_summary(lane),
    }
    payload.update(_abandon_metadata(decision))
    payload.update(_self_correction_metadata(decision))
    return payload


def _upsert_audit_event(*, event_bus: Any, payload: dict[str, Any]) -> dict[str, Any]:
    path = getattr(event_bus, "_audit_log_path", None)
    if path is None:
        raise ValueError("event_bus must be configured with an audit_log_path")
    audit_path = Path(path)
    data = _read_json(audit_path, {"events": []})
    events = data.setdefault("events", [])
    for event in events:
        if not isinstance(event, dict):
            continue
        metadata = event.get("metadata")
        if (
            isinstance(metadata, dict)
            and metadata.get("dedupe_key") == payload["dedupe_key"]
            and event.get("event_type") == payload["event_type"]
        ):
            return event
    event = {
        "event_id": payload["event_id"],
        "event_type": payload["event_type"],
        "timestamp": payload["created_at"],
        "metadata": dict(payload),
    }
    events.append(event)
    _write_json(audit_path, data)
    return event


def _emit_resolution_card(
    *,
    xmuse_root: Path,
    payload: dict[str, Any],
    decision_id: str,
    evidence_refs: list[str],
    status: str = "resolved",
    title: str = "Run takeover resolved",
) -> str:
    emitter = ChatExecutionCardEmitter(xmuse_root)
    intent = emitter.emit_run_takeover(
        conversation_id=payload["conversation_id"],
        planning_run_id=payload["planning_run_id"],
        lane_id=payload["lane_id"],
        takeover_reason=payload["takeover_reason"],
        created_at=payload["created_at"],
        summary=payload["summary"],
        payload={
            **payload,
            "decision_id": decision_id,
            "evidence_refs": evidence_refs,
        },
        status=status,
        title=title,
        dedupe_suffix=payload["dedupe_key"],
        takeover_active=False,
    )
    return f"{_CARD_INTENT_FILE}#{intent.intent_id}"


def _merge_audit_event_metadata(
    *,
    event_bus: Any,
    event_ref: str,
    metadata: dict[str, Any],
) -> None:
    path = getattr(event_bus, "_audit_log_path", None)
    if path is None:
        raise ValueError("event_bus must be configured with an audit_log_path")
    path_text, _, event_id = event_ref.partition("#")
    if path_text != _AUDIT_FILE or not event_id:
        raise ValueError(f"invalid audit event ref: {event_ref}")
    audit_path = Path(path)
    data = _read_json(audit_path, {"events": []})
    events = data.get("events")
    if not isinstance(events, list):
        raise ValueError("audit event log must contain events list")
    for event in events:
        if not isinstance(event, dict) or event.get("event_id") != event_id:
            continue
        existing = event.setdefault("metadata", {})
        if not isinstance(existing, dict):
            raise ValueError(f"audit event metadata must be an object: {event_ref}")
        existing.update(metadata)
        _write_json(audit_path, data)
        return
    raise ValueError(f"audit event not found: {event_ref}")


def _discard_resolution_artifacts(
    *,
    event_bus: Any,
    xmuse_root: Path,
    audit_event_ref: str,
    chat_card_ref: str,
) -> None:
    _discard_audit_event(event_bus=event_bus, event_ref=audit_event_ref)
    _discard_execution_card_intent(xmuse_root=xmuse_root, card_ref=chat_card_ref)


def _discard_audit_event(*, event_bus: Any, event_ref: str) -> None:
    path = getattr(event_bus, "_audit_log_path", None)
    if path is None:
        return
    path_text, _, event_id = event_ref.partition("#")
    if path_text != _AUDIT_FILE or not event_id:
        return
    audit_path = Path(path)
    data = _read_json(audit_path, {"events": []})
    events = data.get("events")
    if not isinstance(events, list):
        return
    remaining = [
        event
        for event in events
        if not isinstance(event, dict) or event.get("event_id") != event_id
    ]
    if len(remaining) == len(events):
        return
    data["events"] = remaining
    _write_json(audit_path, data)


def _discard_execution_card_intent(*, xmuse_root: Path, card_ref: str) -> None:
    path_text, _, intent_id = card_ref.partition("#")
    if path_text != _CARD_INTENT_FILE or not intent_id:
        return
    intents_path = xmuse_root / _CARD_INTENT_FILE
    data = _read_json(intents_path, {"intents": []})
    intents = data.get("intents")
    if not isinstance(intents, list):
        return
    remaining = [
        intent
        for intent in intents
        if not isinstance(intent, dict) or intent.get("intent_id") != intent_id
    ]
    if len(remaining) == len(intents):
        return
    data["intents"] = remaining
    _write_json(intents_path, data)


def _abandon_metadata(decision: ReviewGodTakeoverDecision | None) -> dict[str, Any]:
    if decision is None or decision.action.value not in {
        "abandon_lane",
        "self_correction_then_abandon",
    }:
        return {}
    return {
        "abandon_reason": decision.abandon_reason,
        "impact": decision.impact,
        "replacement_required": decision.replacement_required,
        "feature_gap_implications": decision.feature_gap_implications,
    }


def _self_correction_metadata(decision: ReviewGodTakeoverDecision | None) -> dict[str, Any]:
    if decision is None or decision.action.value != "self_correction_then_abandon":
        return {}
    return {
        "review_self_correction": decision.review_self_correction,
        "original_review_issue": decision.original_review_issue,
        "corrected_review_issue": decision.corrected_review_issue,
    }
