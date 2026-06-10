from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import asdict
from hashlib import sha256
from pathlib import Path

import pytest

from xmuse_core.platform.event_bus import EventBus
from xmuse_core.platform.lane_context import build_lane_context_bundle
from xmuse_core.platform.lane_takeover import build_lane_takeover_bundle
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.platform.takeover_actions import (
    abandon_lane,
    apply_takeover_decision,
    escalate_to_human_or_outer_god,
    normalize_takeover_guard,
    record_takeover_started,
    repair_and_merge,
    requeue_with_context,
    self_correction_then_abandon,
)
from xmuse_core.structuring.models import ReviewGodTakeoverDecision


def test_takeover_actions_delegates_ref_helpers_to_extracted_module() -> None:
    assert importlib.util.find_spec("xmuse_core.platform.takeover_action_refs") is not None
    refs = importlib.import_module("xmuse_core.platform.takeover_action_refs")
    import xmuse_core.platform.takeover_actions as actions

    assert actions._decision_evidence_refs is refs._decision_evidence_refs
    assert actions._takeover_bundle_hash is refs._takeover_bundle_hash


def _write_lane(tmp_path: Path, *, status: str = "exec_failed") -> tuple[LaneStateMachine, dict]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    lane = {
        "feature_id": "lane-takeover",
        "status": status,
        "prompt": "Fix the failed takeover lane.",
        "conversation_id": "conv-takeover",
        "graph_id": "graph-takeover",
        "graph_set_id": "graph-set-takeover",
        "feature_plan_id": "plan-takeover",
        "feature_plan_feature_id": "feature-takeover",
        "planning_run_id": "plan-run-takeover",
        "blueprint_refs": ["docs/spec.md"],
        "risk_level": "high",
        "takeover_attempt_id": "takeover-attempt-1",
        "lease_id": "lease-1",
        "lease_owner": "runner-1",
        "lease_expires_at": "2026-06-01T12:34:56Z",
        "evidence_bundle_id": "evbundle_123",
        "evidence_bundle_hash": "evidence-bundle-hash",
        "max_attempts_by_reason": {
            "execution_infra_failure": 2,
            "prompt_scope_mismatch": 1,
            "review_self_correction": 1,
            "ambiguous_review_failure": 1,
            "merge_failed": 2,
            "retry_count_exhausted": 1,
        },
        "takeover_attempt_cap": 3,
        "takeover_cooldown_seconds": 90,
        "terminal_escalation_policy": "escalate_to_human_or_outer_god",
    }
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 7, "lanes": [lane]}),
        encoding="utf-8",
    )
    (tmp_path / "feature_lanes.json.writer_lease.json").write_text(
        json.dumps({"lease_id": lane["lease_id"]}),
        encoding="utf-8",
    )
    _write_evidence_files(tmp_path)
    return LaneStateMachine(
        lanes_path,
        history_path=tmp_path / "state_history.json",
    ), lane


def _write_evidence_files(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "logs" / "takeover" / "lane-takeover" / "context.json",
        {"lane_id": "lane-takeover", "kind": "takeover_context"},
    )
    patch_path = tmp_path / "logs" / "diffs" / "lane-takeover.patch"
    patch_path.parent.mkdir(parents=True, exist_ok=True)
    patch_path.write_text("diff --git a/file b/file\n", encoding="utf-8")
    _write_json(
        tmp_path / "logs" / "gates" / "lane-takeover" / "report.json",
        {"lane_id": "lane-takeover", "passed": True, "blocking_passed": True},
    )
    _write_json(
        tmp_path / "xmuse" / "reviews" / "lane-takeover" / "verdict.json",
        {"lane_id": "lane-takeover", "decision": "merge"},
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _base_decision(
    *,
    action: str,
    audit_event_ref: str,
    chat_card_ref: str,
) -> ReviewGodTakeoverDecision:
    payload = {
        "lane_id": "lane-takeover",
        "action": action,
        "summary": "Review GOD resolved the takeover.",
        "evidence": {
            "takeover_context_ref": "logs/takeover/lane-takeover/context.json",
            "change_ref": "logs/diffs/lane-takeover.patch",
            "verification_ref": "logs/gates/lane-takeover/report.json",
            "review_verdict_ref": "xmuse/reviews/lane-takeover/verdict.json",
            "audit_event_ref": audit_event_ref,
            "chat_card_ref": chat_card_ref,
        },
    }
    if action in {"abandon_lane", "self_correction_then_abandon"}:
        payload.update(
            {
                "abandon_reason": "Wrong subsystem",
                "impact": "The lane should not be released.",
                "replacement_required": True,
                "feature_gap_implications": "Coverage remains open until a replacement lane lands.",
            }
        )
    if action == "self_correction_then_abandon":
        payload.update(
            {
                "review_self_correction": True,
                "original_review_issue": "The prior review blamed tests instead of scope.",
                "corrected_review_issue": "The lane targets the wrong subsystem.",
            }
        )
    return ReviewGodTakeoverDecision.model_validate(payload)


def _audit_entries(tmp_path: Path) -> list[dict]:
    return json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))["events"]


def _execution_intents(tmp_path: Path) -> list[dict]:
    path = tmp_path / "read_models" / "execution_card_intents.json"
    return json.loads(path.read_text(encoding="utf-8"))["intents"]


def _stable_hash(payload: object) -> str:
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def _takeover_guard(
    state_machine: LaneStateMachine,
    *,
    xmuse_root: Path,
    lane_id: str = "lane-takeover",
) -> dict[str, object]:
    lane = state_machine.get_lane(lane_id)
    snapshot = state_machine._read()
    lanes = snapshot["lanes"]
    lane_context_hash = _stable_hash(
        build_lane_context_bundle(
            lane,
            xmuse_root=xmuse_root,
            all_lanes=lanes,
        )["context_contract"]
    )
    evidence_bundle_hash = _stable_hash(
        asdict(
            build_lane_takeover_bundle(
                lane,
                xmuse_root=xmuse_root,
                all_lanes=lanes,
            )
        )
    )
    return normalize_takeover_guard(
        {
            "lane_status": lane["status"],
            "projection_revision": snapshot["projection_revision"],
            "lease_id": lane["lease_id"],
            "lane_context_hash": lane_context_hash,
            "evidence_bundle_hash": evidence_bundle_hash,
        }
    )


def test_requeue_with_context_records_audit_refs_and_replay_safe_takeover_intent(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-1",
        "reason": "retry after richer context bundle",
        "request_id": "req-takeover-1",
    }

    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="execution_infra_failure",
        audit=audit,
        created_at="2026-05-31T12:00:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    first = requeue_with_context(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T12:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    second = requeue_with_context(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T12:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )

    updated = sm.get_lane("lane-takeover")

    assert updated["status"] == "reworking"
    assert updated["takeover_decision_id"] == first["decision_id"] == second["decision_id"]
    assert (
        updated["takeover_resolved_card_ref"]
        == first["chat_card_ref"]
        == second["chat_card_ref"]
    )
    assert updated["takeover_evidence_refs"] == [
        "logs/takeover/lane-takeover/context.json",
        "logs/diffs/lane-takeover.patch",
        "logs/gates/lane-takeover/report.json",
        "xmuse/reviews/lane-takeover/verdict.json",
        started["audit_event_ref"],
        started["chat_card_ref"],
        first["audit_event_ref"],
    ]
    assert updated["rework_context"] == "Review GOD resolved the takeover."

    audit_events = _audit_entries(tmp_path)
    assert [event["event_type"] for event in audit_events] == [
        "run.takeover_started",
        "run.takeover_resolved",
    ]
    resolved_payload = audit_events[1]["metadata"]
    assert resolved_payload["decision"] == "requeue_with_context"
    assert resolved_payload["chat_card_ref"] == first["chat_card_ref"]
    assert resolved_payload["evidence_refs"][-1] == started["chat_card_ref"]
    assert resolved_payload["request_id"] == "req-takeover-1"

    intents = _execution_intents(tmp_path)
    assert len(intents) == 2
    assert intents[0]["card_type"] == "run_takeover"
    assert intents[0]["payload"]["event_type"] == "run.takeover_started"
    assert intents[0]["payload"]["takeover_reason"] == "execution_infra_failure"
    assert intents[1]["payload"]["event_type"] == "run.takeover_resolved"
    assert intents[1]["payload"]["decision"] == "requeue_with_context"
    assert intents[1]["takeover_active"] is False


def test_apply_takeover_decision_requires_guard_for_lane_state_mutations(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-guard-required",
        "reason": "guarded takeover mutations only",
        "request_id": "req-takeover-guard-required",
    }

    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="execution_infra_failure",
        audit=audit,
        created_at="2026-05-31T12:05:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    with pytest.raises(ValueError, match="requires guard"):
        apply_takeover_decision(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T12:05:01Z",
        )

    assert sm.get_lane("lane-takeover")["status"] == "exec_failed"
    assert [event["event_type"] for event in _audit_entries(tmp_path)] == [
        "run.takeover_started",
    ]


def test_apply_takeover_decision_rejects_stale_takeover_lease_guard(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-guard-lease",
        "reason": "guarded takeover requires the active takeover lease",
        "request_id": "req-takeover-guard-lease",
    }

    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="execution_infra_failure",
        audit=audit,
        created_at="2026-05-31T12:06:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )
    stale_guard = _takeover_guard(sm, xmuse_root=tmp_path)
    stale_guard["lease_id"] = "lease-stale"

    with pytest.raises(ValueError, match="guard.lease_id mismatch"):
        apply_takeover_decision(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T12:06:01Z",
            guard=stale_guard,
        )

    assert sm.get_lane("lane-takeover")["status"] == "exec_failed"
    assert [event["event_type"] for event in _audit_entries(tmp_path)] == [
        "run.takeover_started",
    ]


def test_requeue_with_context_rejects_active_takeover_cooldown(tmp_path: Path) -> None:
    sm, lane = _write_lane(tmp_path)
    sm.update_metadata(
        "lane-takeover",
        {
            "failure_reason": "merge_failed",
            "takeover_last_action_at": "2026-05-31T12:00:30Z",
        },
    )
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-cooldown",
        "reason": "cooldown must block rapid takeover retries",
        "request_id": "req-takeover-cooldown",
    }

    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T12:00:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    with pytest.raises(ValueError, match="cooldown"):
        requeue_with_context(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T12:01:00Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )

    lane_after = sm.get_lane("lane-takeover")
    assert lane_after["status"] == "exec_failed"
    assert "takeover_resolved_event_ref" not in lane_after
    assert [event["event_type"] for event in _audit_entries(tmp_path)] == [
        "run.takeover_started",
    ]


def test_takeover_actions_enforce_bounded_attempt_caps_for_mutation_and_escalation(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path)
    sm.update_metadata(
        "lane-takeover",
        {
            "failure_reason": "merge_failed",
            "takeover_action_attempt_count": 3,
            "takeover_reason_attempt_counts": {"merge_failed": 2},
        },
    )
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-attempt-cap",
        "reason": "bounded takeover attempts only",
        "request_id": "req-takeover-attempt-cap",
    }

    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T12:10:00Z",
    )
    requeue_decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )
    escalate_decision = _base_decision(
        action="escalate_to_human_or_outer_god",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    with pytest.raises(ValueError, match="takeover_attempt_cap"):
        requeue_with_context(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=requeue_decision,
            audit=audit,
            created_at="2026-05-31T12:10:01Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )

    sm.update_metadata("lane-takeover", {"takeover_action_attempt_count": 1})

    with pytest.raises(ValueError, match="max_attempts_by_reason"):
        escalate_to_human_or_outer_god(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=escalate_decision,
            audit=audit,
            created_at="2026-05-31T12:10:02Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )

    lane_after = sm.get_lane("lane-takeover")
    assert lane_after["status"] == "exec_failed"
    assert lane_after["takeover_action_attempt_count"] == 1
    assert [event["event_type"] for event in _audit_entries(tmp_path)] == [
        "run.takeover_started",
    ]


def test_abandon_and_self_correction_record_feature_gap_and_abandonment_audit(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-2",
        "reason": "lane invalidated by takeover review",
        "request_id": "req-takeover-2",
    }

    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="prompt_scope_mismatch",
        audit=audit,
        created_at="2026-05-31T12:00:00Z",
    )
    abandon_decision = _base_decision(
        action="abandon_lane",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    abandoned = abandon_lane(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=abandon_decision,
        audit=audit,
        created_at="2026-05-31T12:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    after_abandon = sm.get_lane("lane-takeover")

    assert after_abandon["status"] == "failed"
    assert after_abandon["replacement_required"] is True
    assert after_abandon["feature_gap_implications"] == (
        "Coverage remains open until a replacement lane lands."
    )
    assert after_abandon["takeover_decision_id"] == abandoned["decision_id"]
    assert after_abandon["takeover_abandoned_card_ref"] == abandoned["abandoned_chat_card_ref"]

    self_sm, self_lane = _write_lane(tmp_path / "self-correction")
    self_bus = EventBus(audit_log_path=(tmp_path / "self-correction" / "audit_events.json"))
    self_started = record_takeover_started(
        lane=self_lane,
        xmuse_root=tmp_path / "self-correction",
        event_bus=self_bus,
        takeover_reason="review_self_correction",
        audit=audit,
        created_at="2026-05-31T13:00:00Z",
    )
    correction_decision = _base_decision(
        action="self_correction_then_abandon",
        audit_event_ref=self_started["audit_event_ref"],
        chat_card_ref=self_started["chat_card_ref"],
    )

    corrected = self_correction_then_abandon(
        state_machine=self_sm,
        xmuse_root=tmp_path / "self-correction",
        event_bus=self_bus,
        decision=correction_decision,
        audit=audit,
        created_at="2026-05-31T13:00:01Z",
        guard=_takeover_guard(self_sm, xmuse_root=tmp_path / "self-correction"),
    )
    after_correction = self_sm.get_lane("lane-takeover")

    assert after_correction["status"] == "failed"
    assert after_correction["review_self_correction"] is True
    assert after_correction["original_review_issue"] == (
        "The prior review blamed tests instead of scope."
    )
    assert after_correction["corrected_review_issue"] == "The lane targets the wrong subsystem."
    assert after_correction["takeover_decision_id"] == corrected["decision_id"]

    abandon_events = _audit_entries(tmp_path)
    assert [event["event_type"] for event in abandon_events] == [
        "run.takeover_started",
        "run.takeover_resolved",
        "lane.abandoned",
    ]
    assert abandon_events[2]["metadata"]["replacement_required"] is True
    assert "Coverage remains open" in abandon_events[2]["metadata"]["feature_gap_implications"]

    correction_events = _audit_entries(tmp_path / "self-correction")
    assert correction_events[2]["metadata"]["review_self_correction"] is True
    assert correction_events[2]["metadata"]["original_review_issue"] == (
        "The prior review blamed tests instead of scope."
    )


def test_escalation_audit_is_idempotent_and_keeps_started_ref(tmp_path: Path) -> None:
    sm, lane = _write_lane(tmp_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-3",
        "reason": "escalate repeated takeover ambiguity",
        "request_id": "req-takeover-3",
    }

    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="ambiguous_review_failure",
        audit=audit,
        created_at="2026-05-31T12:00:00Z",
    )
    decision = _base_decision(
        action="escalate_to_human_or_outer_god",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    first = escalate_to_human_or_outer_god(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T12:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    second = escalate_to_human_or_outer_god(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T12:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )

    lane_after = sm.get_lane("lane-takeover")

    assert lane_after["status"] == "exec_failed"
    assert lane_after["takeover_decision_id"] == first["decision_id"] == second["decision_id"]
    assert lane_after["takeover_action"] == "escalate_to_human_or_outer_god"

    audit_events = _audit_entries(tmp_path)
    assert [event["event_type"] for event in audit_events] == [
        "run.takeover_started",
        "run.takeover_resolved",
    ]
    resolved = audit_events[1]["metadata"]
    assert resolved["decision"] == "escalate_to_human_or_outer_god"
    assert resolved["evidence_refs"][4] == started["audit_event_ref"]


def test_requeue_from_failed_lane_preserves_terminal_status_and_records_audit_refs(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path, status="failed")
    sm.update_metadata("lane-takeover", {"failure_reason": "merge_failed", "retry_count": 2})
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-4",
        "reason": "requeue failed lane with richer takeover context",
        "request_id": "req-takeover-4",
    }

    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T14:00:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    first = requeue_with_context(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T14:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    second = requeue_with_context(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T14:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )

    updated = sm.get_lane("lane-takeover")

    assert updated["status"] == "reworking"
    assert updated["retry_count"] == 3
    assert updated["takeover_retry_override"] is True
    assert "failure_reason" not in updated
    assert updated["takeover_decision_id"] == first["decision_id"] == second["decision_id"]
    assert updated["takeover_started_event_ref"] == started["audit_event_ref"]
    assert updated["takeover_resolved_event_ref"] == first["audit_event_ref"]
    assert (
        updated["takeover_resolved_card_ref"]
        == first["chat_card_ref"]
        == second["chat_card_ref"]
    )
    assert updated["takeover_evidence_refs"] == [
        "logs/takeover/lane-takeover/context.json",
        "logs/diffs/lane-takeover.patch",
        "logs/gates/lane-takeover/report.json",
        "xmuse/reviews/lane-takeover/verdict.json",
        started["audit_event_ref"],
        started["chat_card_ref"],
        first["audit_event_ref"],
    ]
    assert updated["rework_context"] == "Review GOD resolved the takeover."

    audit_events = _audit_entries(tmp_path)
    assert [event["event_type"] for event in audit_events] == [
        "run.takeover_started",
        "run.takeover_resolved",
    ]
    assert audit_events[1]["metadata"]["takeover_reason"] == "merge_failed"
    assert audit_events[1]["metadata"]["chat_card_ref"] == first["chat_card_ref"]

    intents = _execution_intents(tmp_path)
    assert len(intents) == 2
    assert intents[0]["payload"]["takeover_reason"] == "merge_failed"
    assert intents[1]["payload"]["decision"] == "requeue_with_context"
    assert intents[1]["takeover_active"] is False


@pytest.mark.parametrize("status", ["exec_failed", "gate_failed"])
def test_requeue_from_failed_execution_lane_can_override_retry_exhaustion(
    tmp_path: Path,
    status: str,
) -> None:
    sm, lane = _write_lane(tmp_path, status=status)
    sm.update_metadata(
        "lane-takeover",
        {"failure_reason": "execution_infra_unavailable", "retry_count": 2},
    )
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-exhausted",
        "reason": "takeover requeue after retry exhaustion",
        "request_id": "req-takeover-exhausted",
    }
    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="retry_count_exhausted",
        audit=audit,
        created_at="2026-05-31T14:30:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    result = requeue_with_context(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T14:30:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    updated = sm.get_lane("lane-takeover")

    assert updated["status"] == "reworking"
    assert updated["retry_count"] == 3
    assert updated["takeover_retry_override"] is True
    assert updated["takeover_resolved_event_ref"] == result["audit_event_ref"]
    assert _audit_entries(tmp_path)[1]["event_type"] == "run.takeover_resolved"


def test_takeover_action_entrypoints_reject_mismatched_decision_action(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-mismatch",
        "reason": "mismatched action should be rejected",
        "request_id": "req-takeover-mismatch",
    }
    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T17:00:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    with pytest.raises(ValueError, match="takeover_action_mismatch"):
        abandon_lane(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T17:00:01Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )

    assert sm.get_lane("lane-takeover")["status"] == "exec_failed"


def test_repair_and_merge_requires_verified_evidence_and_marks_failed_lane_merged(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path, status="failed")
    sm.update_metadata(
        "lane-takeover",
        {"failure_reason": "merge_failed", "gate_passed": False},
    )
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-repair",
        "reason": "repair failed lane and merge with verified evidence",
        "request_id": "req-takeover-repair",
    }
    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T18:00:00Z",
    )
    decision = _base_decision(
        action="repair_and_merge",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    result = apply_takeover_decision(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T18:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    updated = sm.get_lane("lane-takeover")

    assert updated["status"] == "merged"
    assert updated["takeover_action"] == "repair_and_merge"
    assert updated["outer_god_takeover"] is True
    assert updated["takeover_decision_id"] == result["decision_id"]
    assert updated["gate_passed"] is True
    assert updated["takeover_started_event_ref"] == started["audit_event_ref"]
    assert updated["takeover_resolved_event_ref"] == result["audit_event_ref"]
    assert updated["takeover_resolved_card_ref"] == result["chat_card_ref"]
    assert updated["takeover_evidence_refs"] == [
        "logs/takeover/lane-takeover/context.json",
        "logs/diffs/lane-takeover.patch",
        "logs/gates/lane-takeover/report.json",
        "xmuse/reviews/lane-takeover/verdict.json",
        started["audit_event_ref"],
        started["chat_card_ref"],
        result["audit_event_ref"],
    ]
    assert updated["last_mutation_audit"] == {
        "actor": "review-god/session-repair",
        "reason": "repair failed lane and merge with verified evidence",
        "request_id": "req-takeover-repair",
        "tool": "takeover_actions",
    }
    assert "failure_reason" not in updated
    history = json.loads((tmp_path / "state_history.json").read_text(encoding="utf-8"))
    assert history["snapshots"][-1]["metadata"]["from_status"] == "failed"
    assert history["snapshots"][-1]["state_key"] == "merged"
    assert _audit_entries(tmp_path)[1]["metadata"]["evidence_refs"][-1] == started["chat_card_ref"]
    intents = _execution_intents(tmp_path)
    assert len(intents) == 2
    assert intents[1]["payload"]["decision"] == "repair_and_merge"
    assert intents[1]["status"] == "resolved"


def test_repair_and_merge_keeps_resolved_artifacts_after_post_commit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sm, _lane = _write_lane(tmp_path, status="failed")
    sm.update_metadata(
        "lane-takeover",
        {"failure_reason": "merge_failed", "gate_passed": False},
    )
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-repair",
        "reason": "repair failed lane and merge with verified evidence",
        "request_id": "req-takeover-repair-post-commit-failure",
    }
    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T18:00:00Z",
    )
    decision = _base_decision(
        action="repair_and_merge",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    def raise_after_projection_commit(**_kwargs) -> None:
        raise RuntimeError("history write failed after commit")

    monkeypatch.setattr(sm, "_append_state_history", raise_after_projection_commit)

    with pytest.raises(RuntimeError, match="history write failed after commit"):
        apply_takeover_decision(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T18:00:01Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )

    updated = sm.get_lane("lane-takeover")
    assert updated["status"] == "merged"
    assert updated["takeover_decision_id"]
    assert updated["takeover_resolved_event_ref"]
    assert updated["takeover_resolved_card_ref"]
    assert [event["event_type"] for event in _audit_entries(tmp_path)] == [
        "run.takeover_started",
        "run.takeover_resolved",
    ]
    intents = _execution_intents(tmp_path)
    assert len(intents) == 2
    assert intents[1]["payload"]["event_type"] == "run.takeover_resolved"

    replay = apply_takeover_decision(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T18:00:02Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    assert replay["audit_event_ref"] == updated["takeover_resolved_event_ref"]
    assert replay["chat_card_ref"] == updated["takeover_resolved_card_ref"]


def test_repair_and_merge_rejects_missing_verified_evidence(tmp_path: Path) -> None:
    sm, lane = _write_lane(tmp_path, status="failed")
    (tmp_path / "logs" / "gates" / "lane-takeover" / "report.json").unlink()
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-repair",
        "reason": "repair failed lane and merge with verified evidence",
        "request_id": "req-takeover-repair-missing",
    }
    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T18:30:00Z",
    )
    decision = _base_decision(
        action="repair_and_merge",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    with pytest.raises(ValueError, match="missing takeover evidence"):
        repair_and_merge(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T18:30:01Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )


def test_repair_and_merge_rejects_gate_evidence_for_other_feature_id(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path, status="failed")
    _write_json(
        tmp_path / "logs" / "gates" / "lane-takeover" / "report.json",
        {"feature_id": "other-lane", "passed": True, "blocking_passed": True},
    )
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-repair",
        "reason": "repair failed lane with mismatched gate evidence",
        "request_id": "req-takeover-repair-mismatch",
    }
    started = record_takeover_started(
        lane=lane,
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T18:45:00Z",
    )
    decision = _base_decision(
        action="repair_and_merge",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    with pytest.raises(ValueError, match="verification_ref"):
        repair_and_merge(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T18:45:01Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )


def test_abandon_from_failed_lane_records_feature_gap_and_abandonment_audit(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path, status="failed")
    sm.update_metadata("lane-takeover", {"failure_reason": "merge_failed"})
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-5",
        "reason": "abandon invalid failed lane",
        "request_id": "req-takeover-5",
    }

    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T15:00:00Z",
    )
    decision = _base_decision(
        action="abandon_lane",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    result = abandon_lane(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T15:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    updated = sm.get_lane("lane-takeover")

    assert updated["status"] == "failed"
    assert updated["takeover_decision_id"] == result["decision_id"]
    assert updated["takeover_resolved_event_ref"] == result["audit_event_ref"]
    assert updated["replacement_required"] is True
    assert updated["feature_gap_implications"] == (
        "Coverage remains open until a replacement lane lands."
    )

    audit_events = _audit_entries(tmp_path)
    assert [event["event_type"] for event in audit_events] == [
        "run.takeover_started",
        "run.takeover_resolved",
        "lane.abandoned",
    ]
    assert audit_events[2]["metadata"]["replacement_required"] is True
    assert audit_events[2]["metadata"]["evidence_refs"][-1] == result["audit_event_ref"]
    assert result["abandoned_audit_event_ref"] == (
        f"audit_events.json#{audit_events[2]['event_id']}"
    )
    assert result["abandoned_chat_card_ref"] == updated["takeover_abandoned_card_ref"]
    assert audit_events[2]["metadata"]["chat_card_ref"] == result["abandoned_chat_card_ref"]


def test_self_correction_abandon_from_failed_lane_records_review_correction_audit(
    tmp_path: Path,
) -> None:
    sm, lane = _write_lane(tmp_path, status="failed")
    sm.update_metadata("lane-takeover", {"failure_reason": "merge_failed"})
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-6",
        "reason": "correct prior takeover review before abandoning lane",
        "request_id": "req-takeover-6",
    }

    started = record_takeover_started(
        lane=sm.get_lane("lane-takeover"),
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T16:00:00Z",
    )
    decision = _base_decision(
        action="self_correction_then_abandon",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    result = self_correction_then_abandon(
        state_machine=sm,
        xmuse_root=tmp_path,
        event_bus=bus,
        decision=decision,
        audit=audit,
        created_at="2026-05-31T16:00:01Z",
        guard=_takeover_guard(sm, xmuse_root=tmp_path),
    )
    updated = sm.get_lane("lane-takeover")

    assert updated["status"] == "failed"
    assert updated["takeover_decision_id"] == result["decision_id"]
    assert updated["review_self_correction"] is True
    assert updated["original_review_issue"] == (
        "The prior review blamed tests instead of scope."
    )
    assert updated["corrected_review_issue"] == "The lane targets the wrong subsystem."

    audit_events = _audit_entries(tmp_path)
    assert [event["event_type"] for event in audit_events] == [
        "run.takeover_started",
        "run.takeover_resolved",
        "lane.abandoned",
    ]
    assert audit_events[2]["metadata"]["review_self_correction"] is True
    assert audit_events[2]["metadata"]["original_review_issue"] == (
        "The prior review blamed tests instead of scope."
    )


def test_takeover_decision_rejects_started_refs_for_other_lane(tmp_path: Path) -> None:
    sm, lane = _write_lane(tmp_path)
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")
    audit = {
        "actor": "review-god/session-mismatch",
        "reason": "reject mismatched started evidence",
        "request_id": "req-takeover-started-mismatch",
    }
    started = record_takeover_started(
        lane={**lane, "feature_id": "other-lane"},
        xmuse_root=tmp_path,
        event_bus=bus,
        takeover_reason="merge_failed",
        audit=audit,
        created_at="2026-05-31T19:00:00Z",
    )
    decision = _base_decision(
        action="requeue_with_context",
        audit_event_ref=started["audit_event_ref"],
        chat_card_ref=started["chat_card_ref"],
    )

    with pytest.raises(ValueError, match="audit_event_ref"):
        apply_takeover_decision(
            state_machine=sm,
            xmuse_root=tmp_path,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at="2026-05-31T19:00:01Z",
            guard=_takeover_guard(sm, xmuse_root=tmp_path),
        )
