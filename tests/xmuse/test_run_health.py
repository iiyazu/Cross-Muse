from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from xmuse_core.platform import run_health
from xmuse_core.providers.models import ProviderId, ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.providers.selection_record import (
    ProviderSelectionRecord,
    ProviderSelectionRecordStore,
)


def test_summarize_run_health_groups_operational_states() -> None:
    lanes = [
        {"feature_id": "live-1", "status": "dispatched"},
        {"feature_id": "retry-1", "status": "gated", "retry_count": 1},
        {
            "feature_id": "infra-1",
            "status": "exec_failed",
            "failure_reason": "execution_infra_unavailable",
        },
        {"feature_id": "blocked-1", "status": "awaiting_final_action"},
        {"feature_id": "terminal-1", "status": "merged", "branch": "b", "worktree": "."},
        {"feature_id": "unsafe-1", "status": "merged"},
        {"feature_id": "terminal-retry-history", "status": "failed", "retry_count": 2},
    ]

    summary = run_health.summarize_run_health(lanes)

    assert summary["counts"]["live"] == 2
    assert summary["counts"]["retrying"] == 1
    assert summary["counts"]["infra_failed"] == 1
    assert summary["counts"]["blocked"] == 1
    assert summary["counts"]["terminal"] == 4
    assert summary["counts"]["unsafe_to_release_dependents"] == 1
    assert summary["groups"]["unsafe_to_release_dependents"] == ["unsafe-1"]
    assert "terminal-retry-history" not in summary["groups"]["retrying"]


def test_summarize_run_health_flags_stale_active_lanes() -> None:
    lanes = [
        {
            "feature_id": "stale-1",
            "status": "dispatched",
            "dispatched_at": 100.0,
        },
        {
            "feature_id": "fresh-1",
            "status": "gated",
            "review_started_at": 950.0,
        },
    ]

    summary = run_health.summarize_run_health(
        lanes,
        now=1000.0,
        stale_after_s=300.0,
    )

    assert summary["groups"]["stale"] == ["stale-1"]
    assert summary["groups"]["live"] == ["fresh-1"]


def test_summarize_run_health_uses_worker_lease_pid_liveness() -> None:
    lanes = [
        {
            "feature_id": "live",
            "status": "dispatched",
            "worker_pid": 123,
            "dispatched_at": 100.0,
        },
        {
            "feature_id": "stale",
            "status": "dispatched",
            "worker_pid": 456,
            "dispatched_at": 100.0,
        },
    ]

    summary = run_health.summarize_run_health(
        lanes,
        now=1000.0,
        stale_after_s=300.0,
        live_pids={123},
    )

    assert summary["groups"]["live"] == ["live"]
    assert summary["groups"]["stale"] == ["stale"]


def test_summarize_run_health_does_not_treat_finished_worker_pid_as_active_lease() -> None:
    lanes = [
        {
            "feature_id": "under-review",
            "status": "gated",
            "worker_pid": 456,
            "review_started_at": 950.0,
        },
    ]

    summary = run_health.summarize_run_health(
        lanes,
        now=1000.0,
        stale_after_s=300.0,
        live_pids=set(),
    )

    assert summary["groups"]["live"] == ["under-review"]
    assert summary["groups"]["stale"] == []


def test_summarize_run_health_treats_live_review_worker_pid_as_fresh() -> None:
    lanes = [
        {
            "feature_id": "under-review",
            "status": "gated",
            "worker_pid": 456,
            "review_started_at": 100.0,
        },
    ]

    summary = run_health.summarize_run_health(
        lanes,
        now=1000.0,
        stale_after_s=300.0,
        live_pids={456},
    )

    assert summary["groups"]["live"] == ["under-review"]
    assert summary["groups"]["stale"] == []


def test_summarize_run_health_uses_normalized_terminal_semantics() -> None:
    lanes = [
        {"feature_id": "aborted-history", "status": "aborted", "retry_count": 1},
        {
            "feature_id": "review-infra-retry",
            "status": "gate_failed",
            "failure_reason": "review_infra_unavailable",
            "review_retry_count": 1,
        },
        {"feature_id": "gate-terminal", "status": "gate_failed", "retry_count": 1},
    ]

    summary = run_health.summarize_run_health(lanes)

    assert "aborted-history" in summary["groups"]["terminal"]
    assert "aborted-history" not in summary["groups"]["retrying"]
    assert "review-infra-retry" not in summary["groups"]["terminal"]
    assert "review-infra-retry" in summary["groups"]["retrying"]
    assert "gate-terminal" in summary["groups"]["terminal"]
    assert "gate-terminal" not in summary["groups"]["retrying"]


def test_summarize_run_health_includes_review_rework_alignment_summary() -> None:
    lanes = [
        {
            "feature_id": "active-real-rework",
            "status": "reworking",
            "retry_count": 1,
            "review_fallback_reason": "reproduced_finding",
            "review_summary": "Blocking: still fails.",
        },
        {
            "feature_id": "active-parser-artifact",
            "status": "reworking",
            "review_retry_count": 1,
            "review_summary": "Review decision: no blocking findings",
            "review_fallback_reason": "unknown_review_text",
        },
        {
            "feature_id": "historical-terminal-retry",
            "status": "failed",
            "retry_count": 3,
        },
        {
            "feature_id": "pending-unrelated",
            "status": "pending",
        },
    ]

    summary = run_health.summarize_run_health(lanes)

    alignment = summary["review_rework_alignment"]
    assert alignment["counts_by_category"]["semantic_rework"] == 1
    assert alignment["counts_by_category"]["approved_review"] == 1
    assert alignment["counts_by_category"]["unknown"] == 1
    assert alignment["counts_by_category"]["not_review_related"] == 1
    assert alignment["current_active_retry_or_rework"] == [
        "active-real-rework",
        "active-parser-artifact",
    ]
    assert alignment["historical_terminal_retry_metadata"] == [
        "historical-terminal-retry"
    ]
    assert [sample["lane_id"] for sample in alignment["operator_attention_samples"]] == [
        "active-real-rework",
        "active-parser-artifact",
    ]
    assert alignment["operator_attention_samples"][1]["reason_category"] == (
        "approved_review"
    )


def test_summarize_run_health_includes_model_policy_selection_summary() -> None:
    lanes = [
        {
            "feature_id": "tiered-lane",
            "status": "dispatched",
            "model_policy_enabled": True,
            "model_selection_records": [
                {
                    "peer_type": "review",
                    "lane_risk": "high",
                    "task_type": "review",
                    "model_tier": "frontier_high_reasoning",
                    "selected_model": "gpt-5.4",
                    "selection_reason": "keep high-risk review on the frontier tier",
                },
                {
                    "peer_type": "worker",
                    "lane_risk": "low",
                    "task_type": "bounded_code_writing",
                    "model_tier": "low_cost",
                    "selected_model": "gpt-5.4-mini",
                    "selection_reason": "keep bounded coding on the low-cost tier",
                },
            ],
        },
        {
            "feature_id": "legacy-lane",
            "status": "pending",
        },
    ]

    summary = run_health.summarize_run_health(lanes)

    assert summary["model_policy_summary"] == {
        "lanes_with_model_policy": 1,
        "lanes_with_selection_records": 1,
        "counts_by_model_tier": {
            "frontier_high_reasoning": 1,
            "low_cost": 1,
        },
        "counts_by_lane_risk": {
            "high": 1,
            "low": 1,
        },
        "counts_by_task_type": {
            "review": 1,
            "bounded_code_writing": 1,
        },
        "counts_by_selected_model": {
            "gpt-5.4": 1,
            "gpt-5.4-mini": 1,
        },
        "counts_by_selection_reason": {
            "keep high-risk review on the frontier tier": 1,
            "keep bounded coding on the low-cost tier": 1,
        },
        "by_model_tier": {
            "frontier_high_reasoning": {
                "selection_count": 1,
                "lane_count": 1,
                "total_cost_usd": 0.0,
                "rework_lane_count": 0,
                "review_rejection_lane_count": 0,
                "rework_rate": 0.0,
                "review_rejection_rate": 0.0,
            },
            "low_cost": {
                "selection_count": 1,
                "lane_count": 1,
                "total_cost_usd": 0.0,
                "rework_lane_count": 0,
                "review_rejection_lane_count": 0,
                "rework_rate": 0.0,
                "review_rejection_rate": 0.0,
            },
        },
    }


def test_summarize_run_health_tracks_model_policy_cost_and_failure_rates_by_tier() -> None:
    lanes = [
        {
            "feature_id": "escalated-lane",
            "status": "reworking",
            "retry_count": 2,
            "review_summary": "Review decision: no blocking findings",
            "model_policy_enabled": True,
            "model_selection_records": [
                {
                    "peer_type": "review",
                    "lane_risk": "high",
                    "task_type": "review",
                    "model_tier": "frontier_high_reasoning",
                    "selected_model": "gpt-5.4",
                    "selection_reason": "Escalate review to the frontier tier",
                    "estimated_cost_usd": 0.9,
                },
                {
                    "peer_type": "coordinator",
                    "lane_risk": "high",
                    "task_type": "lane_coordination",
                    "model_tier": "frontier_high_reasoning",
                    "selected_model": "gpt-5.4",
                    "selection_reason": "Escalate coordination to the frontier tier",
                    "estimated_cost_usd": 0.3,
                },
                {
                    "peer_type": "worker",
                    "lane_risk": "high",
                    "task_type": "bounded_code_writing",
                    "model_tier": "mid_tier",
                    "selected_model": "gpt-5.4",
                    "selection_reason": "Escalate worker to the mid tier",
                    "estimated_cost_usd": 0.4,
                },
            ],
        },
        {
            "feature_id": "low-risk-lane",
            "status": "reviewed",
            "review_decision": "merge",
            "model_policy_enabled": True,
            "model_selection_records": [
                {
                    "peer_type": "coordinator",
                    "lane_risk": "low",
                    "task_type": "lane_coordination",
                    "model_tier": "low_cost",
                    "selected_model": "gpt-5.4-mini",
                    "selection_reason": "Keep low-risk coordination on the low-cost tier",
                    "estimated_cost_usd": 0.05,
                },
                {
                    "peer_type": "worker",
                    "lane_risk": "low",
                    "task_type": "bounded_code_writing",
                    "model_tier": "low_cost",
                    "selected_model": "gpt-5.4-mini",
                    "selection_reason": "Keep low-risk coding on the low-cost tier",
                    "estimated_cost_usd": 0.1,
                },
            ],
        },
        {
            "feature_id": "review-reject-lane",
            "status": "reworking",
            "review_decision": "rework",
            "model_policy_enabled": True,
            "model_selection_records": [
                {
                    "peer_type": "review",
                    "lane_risk": "high",
                    "task_type": "review",
                    "model_tier": "frontier_high_reasoning",
                    "selected_model": "gpt-5.4",
                    "selection_reason": "Keep high-risk review on the frontier tier",
                    "estimated_cost_usd": 0.6,
                }
            ],
        },
    ]

    summary = run_health.summarize_run_health(lanes)

    assert summary["model_policy_summary"]["by_model_tier"] == {
        "frontier_high_reasoning": {
            "selection_count": 3,
            "lane_count": 2,
            "total_cost_usd": 1.8,
            "rework_lane_count": 2,
            "review_rejection_lane_count": 1,
            "rework_rate": 1.0,
            "review_rejection_rate": 0.5,
        },
        "mid_tier": {
            "selection_count": 1,
            "lane_count": 1,
            "total_cost_usd": 0.4,
            "rework_lane_count": 1,
            "review_rejection_lane_count": 0,
            "rework_rate": 1.0,
            "review_rejection_rate": 0.0,
        },
        "low_cost": {
            "selection_count": 2,
            "lane_count": 1,
            "total_cost_usd": 0.15,
            "rework_lane_count": 0,
            "review_rejection_lane_count": 0,
            "rework_rate": 0.0,
            "review_rejection_rate": 0.0,
        },
    }


def test_summarize_run_health_counts_resolved_review_rejections_from_history_by_tier(
    ) -> None:
    lanes = [
        {
            "feature_id": "history-backed-review-rework",
            "status": "reviewed",
            "review_decision": "merge",
            "review_summary": "Ready to merge after the rework.",
            "review_history": [
                {
                    "decision": "rework",
                    "summary": "Fix the failing edge-case assertion.",
                    "fallback": "structured",
                    "fallback_reason": "review_verdict",
                    "verdict_id": "verdict-rework-1",
                },
                {
                    "decision": "merge",
                    "summary": "Ready to merge after the rework.",
                    "fallback": "structured",
                    "fallback_reason": "review_verdict",
                    "verdict_id": "verdict-merge-2",
                },
            ],
            "model_policy_enabled": True,
            "model_selection_records": [
                {
                    "peer_type": "review",
                    "lane_risk": "high",
                    "task_type": "review",
                    "model_tier": "frontier_high_reasoning",
                    "selected_model": "gpt-5.4",
                    "selection_reason": "Escalate review after rejection history",
                    "estimated_cost_usd": 0.7,
                },
                {
                    "peer_type": "worker",
                    "lane_risk": "low",
                    "task_type": "bounded_code_writing",
                    "model_tier": "low_cost",
                    "selected_model": "gpt-5.4-mini",
                    "selection_reason": "Keep bounded rework coding on low-cost tier",
                    "estimated_cost_usd": 0.2,
                },
            ],
        }
    ]

    summary = run_health.summarize_run_health(lanes)

    assert summary["model_policy_summary"]["by_model_tier"] == {
        "frontier_high_reasoning": {
            "selection_count": 1,
            "lane_count": 1,
            "total_cost_usd": 0.7,
            "rework_lane_count": 1,
            "review_rejection_lane_count": 1,
            "rework_rate": 1.0,
            "review_rejection_rate": 1.0,
        },
        "low_cost": {
            "selection_count": 1,
            "lane_count": 1,
            "total_cost_usd": 0.2,
            "rework_lane_count": 1,
            "review_rejection_lane_count": 1,
            "rework_rate": 1.0,
            "review_rejection_rate": 1.0,
        },
    }


def test_summarize_run_health_wires_provider_selection_fallback_from_read_model(
    tmp_path: Path,
) -> None:
    lanes = [
        {
            "feature_id": "worker-fallback",
            "status": "reviewed",
            "provider_profile_ref": "codex.worker",
        },
        {
            "feature_id": "worker-healthy",
            "status": "reviewed",
            "provider_profile_ref": "opencode.deepseek_flash_worker",
        },
    ]
    store = ProviderSelectionRecordStore.from_xmuse_root(tmp_path)
    store.append(
        ProviderSelectionRecord(
            lane_id="worker-fallback",
            selected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Fallback to codex when OpenCode is unavailable.",
            peer_type="worker",
            fallback_cause="unavailable",
            health_failure_kind="unavailable",
            source_authority="provider_policy",
        )
    )
    store.append(
        ProviderSelectionRecord(
            lane_id="worker-healthy",
            selected_at=datetime(2026, 6, 1, 12, 1, tzinfo=UTC),
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Prefer the healthy low-cost worker profile.",
            peer_type="worker",
            source_authority="provider_policy",
        )
    )

    summary = run_health.summarize_run_health(lanes, xmuse_root=tmp_path)

    assert summary["groups"]["degraded_fallback"] == ["worker-fallback"]
    assert summary["counts"]["degraded_fallback"] == 1
    assert summary["provider_selection"] == {
        "counts_by_selected_profile": {
            "codex.worker": 1,
            "opencode.deepseek_flash_worker": 1,
        },
        "counts_by_task_type": {
            "bounded_code_writing": 2,
        },
        "fallback_causes": {
            "unavailable": ["worker-fallback"],
        },
        "fallback_lanes": [
            {
                "lane_id": "worker-fallback",
                "selected_profile_ref": "codex.worker",
                "task_type": "bounded_code_writing",
                "fallback_cause": "unavailable",
                "health_failure_kind": "unavailable",
                "source_authority": "provider_policy",
            }
        ],
    }


def test_summarize_run_health_uses_latest_provider_selection_per_lane(
    tmp_path: Path,
) -> None:
    lanes = [
        {
            "feature_id": "worker-recovered",
            "status": "reviewed",
            "provider_profile_ref": "opencode.deepseek_flash_worker",
        }
    ]
    store = ProviderSelectionRecordStore.from_xmuse_root(tmp_path)
    store.append(
        ProviderSelectionRecord(
            lane_id="worker-recovered",
            selected_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Fallback to codex when OpenCode is unavailable.",
            peer_type="worker",
            fallback_cause="unavailable",
            health_failure_kind="unavailable",
            source_authority="provider_policy",
        )
    )
    store.append(
        ProviderSelectionRecord(
            lane_id="worker-recovered",
            selected_at=datetime(2026, 6, 1, 12, 5, tzinfo=UTC),
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Recover to the preferred healthy low-cost worker profile.",
            peer_type="worker",
            source_authority="provider_policy",
        )
    )

    summary = run_health.summarize_run_health(lanes, xmuse_root=tmp_path)

    assert summary["groups"]["degraded_fallback"] == []
    assert summary["counts"]["degraded_fallback"] == 0
    assert summary["provider_selection"] == {
        "counts_by_selected_profile": {
            "opencode.deepseek_flash_worker": 1,
        },
        "counts_by_task_type": {
            "bounded_code_writing": 1,
        },
        "fallback_causes": {},
        "fallback_lanes": [],
    }


def test_summarize_run_health_exposes_takeover_context_needs() -> None:
    lanes = [
        {
            "feature_id": "stale-worker",
            "status": "dispatched",
            "dispatched_at": 100.0,
        },
        {
            "feature_id": "review-rejection",
            "status": "reworking",
            "review_retry_count": 1,
            "review_fallback_reason": "verdict_rework",
            "review_summary": "Verdict: rework",
        },
        {
            "feature_id": "semantic-rework",
            "status": "reworking",
            "retry_count": 1,
            "review_fallback_reason": "reproduced_finding",
        },
        {
            "feature_id": "gate-failure-retry",
            "status": "gate_failed",
            "failure_reason": "gate_failed",
            "retry_count": 1,
        },
        {
            "feature_id": "review-infra-retry",
            "status": "gate_failed",
            "failure_reason": "review_infra_unavailable",
            "review_retry_count": 1,
        },
        {
            "feature_id": "review-no-verdict",
            "status": "gate_failed",
            "failure_reason": "review_no_verdict",
        },
        {
            "feature_id": "terminal-exec-failure",
            "status": "exec_failed",
            "failure_reason": "execution_infra_unavailable",
        },
        {
            "feature_id": "terminal-failed",
            "status": "failed",
            "failure_reason": "worker_stopped_without_result",
        },
        {
            "feature_id": "merge-conflict",
            "status": "reworking",
            "retry_count": 1,
            "merge_failure_reason": "merge_conflict_or_failed",
            "merge_failure_detail": "CONFLICT (content): src/example.py",
        },
        {
            "feature_id": "prompt-mismatch",
            "status": "reworking",
            "review_retry_count": 1,
            "review_summary": "Findings: approach targets the wrong subsystem",
            "review_fallback_reason": "verdict_terminate",
        },
        {
            "feature_id": "fresh-worker",
            "status": "dispatched",
            "dispatched_at": 950.0,
        },
    ]

    summary = run_health.summarize_run_health(
        lanes,
        now=1000.0,
        stale_after_s=300.0,
    )

    assert summary["groups"]["takeover_context_needed"] == [
        "stale-worker",
        "review-rejection",
        "semantic-rework",
        "gate-failure-retry",
        "review-infra-retry",
        "review-no-verdict",
        "terminal-exec-failure",
        "terminal-failed",
        "merge-conflict",
        "prompt-mismatch",
    ]
    assert summary["counts"]["takeover_context_needed"] == 10
    takeover_context = summary["takeover_context"]
    assert takeover_context["counts_by_reason"] == {
        "stale_worker": 1,
        "review_rejection": 1,
        "semantic_rework": 1,
        "gate_failure": 1,
        "review_infra_retry": 1,
        "review_infra_failure": 1,
        "execution_infra_failure": 1,
        "terminal_failure": 1,
        "merge_conflict": 1,
        "prompt_subsystem_mismatch": 1,
    }
    assert takeover_context["needed_lanes"] == [
        {
            "lane_id": "stale-worker",
            "status": "dispatched",
            "reason": "stale_worker",
            "review_rework_category": "not_review_related",
            "lane_context_ref": "logs/lane_context/stale-worker/latest.json",
        },
        {
            "lane_id": "review-rejection",
            "status": "reworking",
            "reason": "review_rejection",
            "review_rework_category": "review_rejection",
            "lane_context_ref": "logs/lane_context/review-rejection/latest.json",
        },
        {
            "lane_id": "semantic-rework",
            "status": "reworking",
            "reason": "semantic_rework",
            "review_rework_category": "semantic_rework",
            "lane_context_ref": "logs/lane_context/semantic-rework/latest.json",
        },
        {
            "lane_id": "gate-failure-retry",
            "status": "gate_failed",
            "reason": "gate_failure",
            "review_rework_category": "gate_failure",
            "lane_context_ref": "logs/lane_context/gate-failure-retry/latest.json",
        },
        {
            "lane_id": "review-infra-retry",
            "status": "gate_failed",
            "reason": "review_infra_retry",
            "review_rework_category": "review_infra",
            "lane_context_ref": "logs/lane_context/review-infra-retry/latest.json",
        },
        {
            "lane_id": "review-no-verdict",
            "status": "gate_failed",
            "reason": "review_infra_failure",
            "review_rework_category": "review_infra",
            "lane_context_ref": "logs/lane_context/review-no-verdict/latest.json",
        },
        {
            "lane_id": "terminal-exec-failure",
            "status": "exec_failed",
            "reason": "execution_infra_failure",
            "review_rework_category": "execution_infra",
            "lane_context_ref": "logs/lane_context/terminal-exec-failure/latest.json",
        },
        {
            "lane_id": "terminal-failed",
            "status": "failed",
            "reason": "terminal_failure",
            "review_rework_category": "unknown",
            "lane_context_ref": "logs/lane_context/terminal-failed/latest.json",
        },
        {
            "lane_id": "merge-conflict",
            "status": "reworking",
            "reason": "merge_conflict",
            "review_rework_category": "merge_conflict",
            "lane_context_ref": "logs/lane_context/merge-conflict/latest.json",
        },
        {
            "lane_id": "prompt-mismatch",
            "status": "reworking",
            "reason": "prompt_subsystem_mismatch",
            "review_rework_category": "prompt_subsystem_mismatch",
            "lane_context_ref": "logs/lane_context/prompt-mismatch/latest.json",
        },
    ]
    assert "review-infra-retry" not in summary["groups"]["terminal"]
    assert "terminal-exec-failure" in summary["groups"]["terminal"]


def test_summarize_run_health_exposes_peer_delivery_degraded_visibility() -> None:
    lanes = [
        {
            "feature_id": "configured-success",
            "status": "reviewed",
            "review_peer_id": "peer-reviewer",
            "peer_request_id": "req-configured",
            "peer_routing_mode": "required",
            "peer_delivery_mode": "configured_peer",
        },
        {
            "feature_id": "configured-fallback",
            "status": "reviewed",
            "review_peer_id": "peer-reviewer",
            "peer_request_id": "req-fallback",
            "peer_routing_mode": "preferred",
            "peer_delivery_mode": "one_shot_fallback",
            "peer_degraded_reason": "receive_timeout",
        },
        {
            "feature_id": "required-failed",
            "status": "gate_failed",
            "failure_reason": "required_review_peer_unavailable",
            "review_peer_id": "peer-required",
            "peer_request_id": "req-required",
            "peer_routing_mode": "required",
            "peer_delivery_mode": "required_peer_failed",
            "peer_degraded_reason": "review_peer_role_mismatch",
        },
        {
            "feature_id": "persistent-degraded",
            "status": "reviewed",
            "review_delivery_mode": "one_shot_fallback",
            "persistent_review_degraded": True,
            "persistent_review_degraded_reason": "send_failed",
            "review_request_id": "review-req",
        },
        {
            "feature_id": "default-peer-success",
            "status": "reviewed",
            "peer_routing_mode": "preferred",
            "peer_delivery_mode": "configured_peer",
            "review_peer_defaulted": True,
        },
    ]

    summary = run_health.summarize_run_health(lanes)

    assert summary["groups"]["degraded_fallback"] == [
        "configured-fallback",
        "required-failed",
        "persistent-degraded",
    ]
    assert summary["counts"]["degraded_fallback"] == 3
    peer_delivery = summary["peer_delivery"]
    assert peer_delivery["counts_by_delivery_mode"] == {
        "configured_peer": 2,
        "one_shot_fallback": 1,
        "required_peer_failed": 1,
    }
    assert peer_delivery["configured_peer_lanes"] == [
        {
            "lane_id": "configured-success",
            "status": "reviewed",
            "peer_routing_mode": "required",
            "peer_delivery_mode": "configured_peer",
            "review_peer_id": "peer-reviewer",
            "peer_request_id": "req-configured",
            "peer_degraded_reason": None,
            "review_peer_defaulted": False,
        },
        {
            "lane_id": "default-peer-success",
            "status": "reviewed",
            "peer_routing_mode": "preferred",
            "peer_delivery_mode": "configured_peer",
            "review_peer_id": None,
            "peer_request_id": None,
            "peer_degraded_reason": None,
            "review_peer_defaulted": True,
        },
    ]
    assert peer_delivery["required_peer_failures"] == [
        {
            "lane_id": "required-failed",
            "status": "gate_failed",
            "failure_reason": "required_review_peer_unavailable",
            "review_peer_id": "peer-required",
            "peer_request_id": "req-required",
            "peer_degraded_reason": "review_peer_role_mismatch",
        }
    ]
    assert peer_delivery["persistent_review_degraded_reasons"] == {
        "send_failed": ["persistent-degraded"]
    }
    assert peer_delivery["default_review_peer_routing"] == [
        {
            "lane_id": "default-peer-success",
            "status": "reviewed",
            "peer_delivery_mode": "configured_peer",
            "peer_routing_mode": "preferred",
            "peer_degraded_reason": None,
        }
    ]
    assert [item["lane_id"] for item in peer_delivery["degraded_or_fallback_lanes"]] == [
        "configured-fallback",
        "required-failed",
        "persistent-degraded",
    ]


def test_summarize_run_health_does_not_request_takeover_for_merged_history_noise() -> None:
    summary = run_health.summarize_run_health(
        [
            {
                "feature_id": "merged-with-old-review-noise",
                "status": "merged",
                "failure_reason": "review_infra_unavailable",
                "review_summary": "Blocking: stale issue from an earlier attempt.",
                "review_decision": "merge",
            }
        ],
        now=1000.0,
        stale_after_s=300.0,
    )

    assert summary["groups"]["takeover_context_needed"] == []
    assert summary["counts"]["takeover_context_needed"] == 0
    assert summary["takeover_context"]["needed_lanes"] == []


def test_summarize_run_health_bounds_review_rework_operator_attention_samples() -> None:
    lanes = [
        {
            "feature_id": f"rework-{index}",
            "status": "reworking",
            "retry_count": 1,
            "review_fallback_reason": "reproduced_finding",
        }
        for index in range(7)
    ]

    summary = run_health.summarize_run_health(lanes)

    samples = summary["review_rework_alignment"]["operator_attention_samples"]
    assert [sample["lane_id"] for sample in samples] == [
        "rework-0",
        "rework-1",
        "rework-2",
        "rework-3",
        "rework-4",
    ]
    assert summary["review_rework_alignment"]["sample_limit"] == 5


def test_build_run_health_model_reports_lane_groups_and_process_counts(
    tmp_path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "live-worker",
                        "status": "dispatched",
                        "worker_pid": 123,
                        "dispatched_at": 100.0,
                    },
                    {
                        "feature_id": "dead-worker",
                        "status": "dispatched",
                        "worker_pid": 456,
                        "dispatched_at": 100.0,
                    },
                    {"feature_id": "retry", "status": "gated", "retry_count": 1},
                    {"feature_id": "blocked", "status": "awaiting_final_action"},
                    {
                        "feature_id": "infra",
                        "status": "exec_failed",
                        "failure_reason": "execution_infra_unavailable",
                    },
                    {
                        "feature_id": "terminal-retry-history",
                        "status": "failed",
                        "retry_count": 5,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    model = run_health.build_run_health_model(
        lanes_path,
        now=1000.0,
        stale_after_s=300.0,
        live_pids={123, 2001, 2002},
        runner_pids=[2001, 2002],
        mcp_pids=[],
    )

    assert model["groups"]["live"] == ["live-worker", "retry"]
    assert model["groups"]["stale"] == ["dead-worker"]
    assert model["groups"]["retrying"] == ["retry"]
    assert model["groups"]["blocked"] == ["blocked"]
    assert model["groups"]["infra_failed"] == ["infra"]
    assert model["groups"]["terminal"] == ["infra", "terminal-retry-history"]
    assert model["processes"]["runner_count"] == 2
    assert model["processes"]["mcp_count"] == 0
    assert [warning["code"] for warning in model["warnings"]] == [
        "duplicate_runner_processes",
        "missing_mcp_process",
    ]


def test_build_run_health_model_reads_review_rework_evidence_without_writing_projection(
    tmp_path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "context-approved-rework",
                "status": "reworking",
                "review_decision": "rework",
                "lane_context_ref": (
                    "logs/lane_context/context-approved-rework/latest.json"
                ),
            }
        ]
    }
    context_path = (
        tmp_path / "logs" / "lane_context" / "context-approved-rework" / "latest.json"
    )
    context_path.parent.mkdir(parents=True)
    context_path.write_text(
        json.dumps({"review_summary": "Review decision: no blocking findings"}),
        encoding="utf-8",
    )
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")

    model = run_health.build_run_health_model(
        lanes_path,
        xmuse_root=tmp_path,
        runner_pids=[],
        mcp_pids=[],
    )

    assert model["review_rework_alignment"]["counts_by_category"]["approved_review"] == 1
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


def test_discover_xmuse_processes_dedupes_uv_wrapper_and_python_child(tmp_path) -> None:
    proc_root = tmp_path / "proc"
    uv_runner = proc_root / "101"
    py_runner = proc_root / "102"
    uv_mcp = proc_root / "201"
    py_mcp = proc_root / "202"
    for path, ppid, cmdline in [
        (uv_runner, 1, b"uv\0run\0python\0xmuse/platform_runner.py\0--max-hours\08\0"),
        (py_runner, 101, b"python3\0xmuse/platform_runner.py\0--max-hours\08\0"),
        (uv_mcp, 1, b"uv\0run\0python\0xmuse/mcp_server.py\0"),
        (py_mcp, 201, b"python3\0xmuse/mcp_server.py\0"),
    ]:
        path.mkdir(parents=True)
        path.joinpath("cmdline").write_bytes(cmdline)
        path.joinpath("status").write_text(f"Name:\ttest\nPPid:\t{ppid}\n")

    runner_pids, mcp_pids = run_health.discover_xmuse_processes(proc_root)

    assert runner_pids == [102]
    assert mcp_pids == [202]


def test_discover_xmuse_runtime_processes_classifies_runtime_helpers_and_workers(
    tmp_path: Path,
) -> None:
    proc_root = tmp_path / "proc"
    entries = [
        (101, 1, b"uv\0run\0python\0xmuse/platform_runner.py\0--max-hours\08\0"),
        (102, 101, b"python3\0xmuse/platform_runner.py\0--max-hours\08\0"),
        (201, 1, b"python3\0xmuse/mcp_server.py\0"),
        (301, 1, b"python3\0xmuse/dashboard_api.py\0"),
        (302, 1, b"python3\0xmuse/chat_api.py\0"),
        (401, 1, b"python3\0xmuse/master_loop.py\0"),
        (402, 1, b"python3\0xmuse_main.py\0"),
        (403, 1, b"bash\0xmuse/overnight_runner.sh\0"),
        (501, 1, b"bash\0xmuse/scheduler_monitor.sh\0"),
        (502, 1, b"bash\0xmuse/start_scheduler_monitor.sh\0"),
        (503, 1, b"bash\0xmuse/god_launcher.sh\0"),
        (601, 1, b"python3\0xmuse/master_review_runner.py\0"),
        (602, 1, b"python3\0xmuse/integrated_test_runner.py\0--loop\0xmuse\0"),
        (603, 1, b"python3\0xmuse/master_merge_runner.py\0--loop\0xmuse\0--execute\0"),
        (701, 1, b"python3\0src/xmuse_core/agents/codex_persistent.py\0"),
        (702, 701, b"python3\0-m\0xmuse_core.agents.codex_persistent\0"),
        (801, 1, b"codex\0exec\0--yolo\0prompt\0"),
        (802, 1, b"opencode\0run\0--model\0deepseek-v4\0"),
    ]
    for pid, ppid, cmdline in entries:
        path = proc_root / str(pid)
        path.mkdir(parents=True)
        path.joinpath("cmdline").write_bytes(cmdline)
        path.joinpath("status").write_text(f"Name:\ttest\nPPid:\t{ppid}\n")

    inventory = run_health.discover_xmuse_runtime_processes(proc_root)

    assert inventory["runner_pids"] == [102]
    assert inventory["mcp_pids"] == [201]
    assert inventory["counts_by_service"] == {
        "runner": 1,
        "mcp": 1,
        "dashboard_api": 1,
        "chat_api": 1,
        "master_loop_runner": 1,
        "xmuse_main_runner": 1,
        "overnight_runner": 1,
        "scheduler_monitor": 1,
        "start_scheduler_monitor": 1,
        "god_launcher": 1,
        "master_review_runner": 1,
        "integrated_test_runner": 1,
        "master_merge_runner": 1,
        "persistent_god_shim": 1,
        "codex_worker": 1,
        "opencode_worker": 1,
    }
    assert [item["service"] for item in inventory["services"]] == [
        "runner",
        "mcp",
        "dashboard_api",
        "chat_api",
        "master_loop_runner",
        "xmuse_main_runner",
        "overnight_runner",
        "scheduler_monitor",
        "start_scheduler_monitor",
        "god_launcher",
        "master_review_runner",
        "integrated_test_runner",
        "master_merge_runner",
        "persistent_god_shim",
        "codex_worker",
        "opencode_worker",
    ]
    assert inventory["warnings"] == []
    assert inventory["evidence"] == {"hard": [], "degraded": []}


def test_build_run_health_model_exposes_compact_process_inventory_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    inventory = run_health.build_process_inventory(
        runner_pids=[11, 12],
        mcp_pids=[],
        services={"scheduler_monitor": [21, 22]},
    )
    monkeypatch.setattr(
        run_health,
        "discover_xmuse_runtime_processes",
        lambda proc_root=Path("/proc"): inventory,
    )

    model = run_health.build_run_health_model(lanes_path)

    assert model["processes"]["services"] == inventory["services"]
    assert model["processes"]["counts_by_service"] == inventory["counts_by_service"]
    assert model["processes"]["evidence"] == inventory["evidence"]
    assert [warning["code"] for warning in model["warnings"]] == [
        "duplicate_runner_processes",
        "missing_mcp_process",
        "duplicate_scheduler_monitor_processes",
    ]


def test_process_inventory_allows_persistent_god_shim_pool() -> None:
    inventory = run_health.build_process_inventory(
        runner_pids=[11],
        mcp_pids=[21],
        services={"persistent_god_shim": [101, 102, 103]},
    )

    assert inventory["counts_by_service"]["persistent_god_shim"] == 3
    assert inventory["evidence"] == {"hard": [], "degraded": []}
    assert [warning["code"] for warning in inventory["warnings"]] == []
    assert [
        service
        for service in inventory["services"]
        if service["service"] == "persistent_god_shim"
    ] == [
        {
            "service": "persistent_god_shim",
            "label": "codex_persistent",
            "category": "session_shim",
            "writer_capable": True,
            "count": 3,
            "pids": [101, 102, 103],
            "state": "multiple",
        }
    ]


def test_build_run_health_model_from_lanes_preserves_requested_scope() -> None:
    model = run_health.build_run_health_model_from_lanes(
        [{"feature_id": "lane-a", "status": "pending"}],
        process_inventory=run_health.build_process_inventory(
            runner_pids=[101],
            mcp_pids=[201],
        ),
        scope=run_health.build_run_health_scope(
            conversation_id="conv-a",
            workspace_id="conv-a",
        ),
    )

    assert model["scope"] == {
        "kind": "conversation",
        "conversation_id": "conv-a",
        "workspace_id": "conv-a",
    }
