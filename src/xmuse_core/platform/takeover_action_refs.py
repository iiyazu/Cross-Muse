from __future__ import annotations

import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path
from typing import Any

from xmuse_core.platform.event_bus import _read_json
from xmuse_core.platform.lane_context import build_lane_context_bundle
from xmuse_core.platform.lane_takeover import build_lane_takeover_bundle
from xmuse_core.structuring.models import (
    ReviewGodTakeoverAction,
    ReviewGodTakeoverDecision,
)

_STARTED_EVENT = "run.takeover_started"
_AUDIT_FILE = "audit_events.json"
_CARD_INTENT_FILE = "read_models/execution_card_intents.json"


def _decision_evidence_refs(
    decision: ReviewGodTakeoverDecision | None,
    *,
    resolved_audit_event_ref: str | None = None,
) -> list[str]:
    if decision is None:
        return []
    refs = [
        decision.evidence.takeover_context_ref,
        decision.evidence.change_ref,
        decision.evidence.verification_ref,
        decision.evidence.review_verdict_ref,
        decision.evidence.audit_event_ref,
        decision.evidence.chat_card_ref,
    ]
    if resolved_audit_event_ref:
        refs.append(resolved_audit_event_ref)
    return _dedupe_preserving_order(refs)


def _takeover_reason(lane: dict[str, Any]) -> str:
    return str(lane.get("failure_reason") or lane.get("takeover_reason") or "takeover_needed")


def _takeover_started_summary(lane: dict[str, Any]) -> str:
    lane_id = _require_text(lane.get("feature_id"), "lane_id")
    return f"Review GOD takeover started for {lane_id}."


def _takeover_event_id(
    *,
    event_type: str,
    lane_id: str,
    request_id: str,
    action: str,
) -> str:
    digest = sha256(f"{event_type}:{lane_id}:{request_id}:{action}".encode()).hexdigest()
    return f"evt-{digest[:12]}"


def _takeover_dedupe_key(
    *,
    planning_run_id: str,
    lane_id: str,
    request_id: str,
    event_type: str,
    action: str,
) -> str:
    return ":".join(
        [planning_run_id, lane_id, request_id, event_type, action]
    )


def _decision_id(decision: ReviewGodTakeoverDecision, *, audit: dict[str, str]) -> str:
    digest = sha256(
        json.dumps(
            {
                "lane_id": decision.lane_id,
                "action": decision.action.value,
                "request_id": audit["request_id"],
                "audit_event_ref": decision.evidence.audit_event_ref,
                "chat_card_ref": decision.evidence.chat_card_ref,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"takeover-{digest[:12]}"


def _ensure_action(
    decision: ReviewGodTakeoverDecision,
    expected: ReviewGodTakeoverAction,
) -> None:
    if decision.action is not expected:
        raise ValueError(
            f"takeover_action_mismatch: expected {expected.value}, "
            f"got {decision.action.value}"
        )


def _validate_decision_evidence(
    decision: ReviewGodTakeoverDecision,
    *,
    lane: dict[str, Any],
    xmuse_root: Path,
) -> None:
    lane_id = _require_text(lane.get("feature_id"), "lane_id")
    planning_run_id = _require_text(
        lane.get("planning_run_id") or lane.get("source_run_id") or lane.get("graph_id"),
        "planning_run_id",
    )
    refs = [
        decision.evidence.takeover_context_ref,
        decision.evidence.change_ref,
        decision.evidence.verification_ref,
        decision.evidence.review_verdict_ref,
        decision.evidence.audit_event_ref,
        decision.evidence.chat_card_ref,
    ]
    missing = [ref for ref in refs if not _evidence_ref_exists(ref, xmuse_root=xmuse_root)]
    if missing:
        raise ValueError(f"missing takeover evidence: {', '.join(missing)}")
    _validate_started_evidence(
        decision=decision,
        lane_id=lane_id,
        planning_run_id=planning_run_id,
        xmuse_root=xmuse_root,
    )

    if decision.action is ReviewGodTakeoverAction.REPAIR_AND_MERGE:
        gate = _read_json_ref(decision.evidence.verification_ref, xmuse_root=xmuse_root)
        gate_lane_id = gate.get("lane_id") or gate.get("feature_id")
        if gate_lane_id != lane_id:
            raise ValueError("takeover evidence lane mismatch: verification_ref")
        if gate.get("passed") is not True or gate.get("blocking_passed") is False:
            raise ValueError("repair_and_merge requires passing verification evidence")
        verdict = _read_json_ref(decision.evidence.review_verdict_ref, xmuse_root=xmuse_root)
        if verdict.get("lane_id") not in {None, lane_id}:
            raise ValueError("takeover evidence lane mismatch: review_verdict_ref")
        if str(verdict.get("decision") or verdict.get("verdict") or "").lower() not in {
            "merge",
            "approved",
            "approve",
        }:
            raise ValueError("repair_and_merge requires merge review verdict evidence")


def _validate_resolution_applicable(
    *,
    current_status: str,
    target_status: str | None,
) -> None:
    if target_status is None:
        return
    if current_status == "failed":
        if target_status in {"failed", "reworking", "merged"}:
            return
        raise ValueError(
            f"takeover resolution cannot move failed lane to {target_status}"
        )
    allowed = {
        "exec_failed": {"failed", "reworking"},
        "gate_failed": {"failed", "reworking", "gated"},
        "rejected": {"failed", "reworking"},
        "reviewed": {"failed", "merged", "awaiting_final_action", "reworking"},
    }
    if target_status not in allowed.get(current_status, set()):
        raise ValueError(
            f"takeover resolution cannot move {current_status} lane to {target_status}"
        )


def _validate_started_evidence(
    *,
    decision: ReviewGodTakeoverDecision,
    lane_id: str,
    planning_run_id: str,
    xmuse_root: Path,
) -> None:
    audit_event = _read_json_ref(decision.evidence.audit_event_ref, xmuse_root=xmuse_root)
    audit_metadata = audit_event.get("metadata")
    if not isinstance(audit_metadata, dict):
        audit_metadata = audit_event
    if audit_event.get("event_type") != _STARTED_EVENT:
        raise ValueError("takeover evidence mismatch: audit_event_ref event_type")
    if audit_metadata.get("lane_id") != lane_id:
        raise ValueError("takeover evidence lane mismatch: audit_event_ref")
    if audit_metadata.get("planning_run_id") != planning_run_id:
        raise ValueError("takeover evidence planning run mismatch: audit_event_ref")
    request_id = audit_metadata.get("request_id")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("takeover evidence missing request_id: audit_event_ref")

    card = _read_json_ref(decision.evidence.chat_card_ref, xmuse_root=xmuse_root)
    payload = card.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    if card.get("card_type") != "run_takeover":
        raise ValueError("takeover evidence mismatch: chat_card_ref card_type")
    if card.get("planning_run_id") != planning_run_id:
        raise ValueError("takeover evidence planning run mismatch: chat_card_ref")
    if payload.get("event_type") != _STARTED_EVENT:
        raise ValueError("takeover evidence mismatch: chat_card_ref event_type")
    if payload.get("lane_id") != lane_id:
        raise ValueError("takeover evidence lane mismatch: chat_card_ref")
    if payload.get("request_id") != request_id:
        raise ValueError("takeover evidence request mismatch: chat_card_ref")


def _evidence_ref_exists(ref: str, *, xmuse_root: Path) -> bool:
    path_text, _, fragment = ref.partition("#")
    path = xmuse_root / path_text
    if not path.exists():
        return False
    if not fragment:
        return True
    return _read_json_ref(ref, xmuse_root=xmuse_root) != {}


def _read_json_ref(ref: str, *, xmuse_root: Path) -> dict[str, Any]:
    path_text, _, fragment = ref.partition("#")
    payload = _read_json(xmuse_root / path_text, {})
    if not fragment:
        return payload
    if path_text == _AUDIT_FILE:
        return _find_ref_item(payload, "events", "event_id", fragment)
    if path_text == _CARD_INTENT_FILE:
        return _find_ref_item(payload, "intents", "intent_id", fragment)
    if isinstance(payload.get("id"), str) and payload.get("id") == fragment:
        return payload
    for collection_name in ("review_verdicts", "verdicts", "items", "events", "intents"):
        item = _find_ref_item(payload, collection_name, "id", fragment)
        if item:
            return item
    return {}


def _find_ref_item(
    payload: dict[str, Any],
    collection_name: str,
    id_key: str,
    ref_id: str,
) -> dict[str, Any]:
    values = payload.get(collection_name)
    if not isinstance(values, list):
        return {}
    for value in values:
        if isinstance(value, dict) and value.get(id_key) == ref_id:
            return value
    return {}


def _requires_controlled_terminal_update(
    *,
    current_status: str,
    target_status: str | None,
) -> bool:
    return current_status == "failed" and target_status in {"reworking", "merged"}


def _should_persist_without_transition(
    *,
    current_status: str,
    target_status: str | None,
) -> bool:
    return target_status is None or current_status == "failed"


def _first_blueprint_ref(lane: dict[str, Any]) -> str | None:
    refs = lane.get("blueprint_refs")
    if isinstance(refs, list):
        for ref in refs:
            if isinstance(ref, str) and ref.strip():
                return ref.strip()
    ref = lane.get("blueprint_ref")
    if isinstance(ref, str) and ref.strip():
        return ref.strip()
    return None


def _require_text(value: Any, field_name: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    raise ValueError(f"{field_name} is required")


def _dedupe_preserving_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _current_writer_lease_id(lanes_path: Path) -> str | None:
    lease_path = lanes_path.with_name(f"{lanes_path.name}.writer_lease.json")
    if not lease_path.exists():
        return None
    try:
        payload = json.loads(lease_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    lease_id = payload.get("lease_id")
    if isinstance(lease_id, str) and lease_id.strip():
        return lease_id.strip()
    return None


def _lane_context_hash(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]],
) -> str:
    bundle = build_lane_context_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    return _stable_payload_hash(bundle["context_contract"])


def _takeover_bundle_hash(
    lane: dict[str, Any],
    *,
    xmuse_root: Path,
    all_lanes: list[dict[str, Any]],
) -> str:
    bundle = build_lane_takeover_bundle(
        lane,
        xmuse_root=xmuse_root,
        all_lanes=all_lanes,
    )
    return _stable_payload_hash(asdict(bundle))


def _stable_payload_hash(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _snapshot_lanes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = snapshot.get("lanes")
    if not isinstance(lanes, list):
        raise ValueError("feature_lanes.json lanes must be a list")
    return [lane for lane in lanes if isinstance(lane, dict)]


def _snapshot_projection_revision(snapshot: dict[str, Any]) -> int:
    revision = snapshot.get("projection_revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool):
        return 0
    return revision
