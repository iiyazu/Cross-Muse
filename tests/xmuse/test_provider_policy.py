from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest

from xmuse_core.chat.protocol_v2 import GodSpeechAct
from xmuse_core.platform.read_contracts import build_provider_selection_records
from xmuse_core.providers.adapters.base import ProviderFailureKind
from xmuse_core.providers.adapters.fake import (
    FakeProviderHealthState,
    build_fake_provider_health_snapshot,
)
from xmuse_core.providers.models import (
    ProviderId,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)
from xmuse_core.providers.policy import ProviderPolicyService
from xmuse_core.providers.registry import build_default_provider_registry
from xmuse_core.providers.selection_record import (
    ProviderSelectionRecord,
    ProviderSelectionRecordStore,
)


def _record(
    *,
    lane_id: str,
    provider_id: ProviderId,
    profile_id: ProviderProfileId,
    task_type: TaskCapability,
    lane_risk: RiskTier,
    selection_reason: str,
    peer_type: str,
    selected_at: datetime,
    fallback_cause: str | None = None,
) -> ProviderSelectionRecord:
    return ProviderSelectionRecord(
        lane_id=lane_id,
        provider_id=provider_id,
        profile_id=profile_id,
        task_type=task_type,
        lane_risk=lane_risk,
        selection_reason=selection_reason,
        peer_type=peer_type,
        selected_at=selected_at,
        fallback_cause=fallback_cause,
    )


def test_provider_selection_records_write_runtime_read_model_and_are_queryable(
    tmp_path,
) -> None:
    store = ProviderSelectionRecordStore.from_xmuse_root(tmp_path)
    store.append(
        _record(
            lane_id="lane-1",
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Prefer the healthy low-cost worker profile.",
            peer_type="worker",
            selected_at=datetime(2026, 5, 31, 12, 0, tzinfo=UTC),
        )
    )
    store.append(
        _record(
            lane_id="lane-1",
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Fallback to the codex worker profile.",
            peer_type="worker",
            selected_at=datetime(2026, 5, 31, 12, 1, tzinfo=UTC),
            fallback_cause="provider_unavailable",
        )
    )
    store.append(
        _record(
            lane_id="lane-2",
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.REVIEW,
            task_type=TaskCapability.REVIEW,
            lane_risk=RiskTier.HIGH,
            selection_reason="Keep high-risk review on codex.",
            peer_type="review",
            selected_at=datetime(2026, 5, 31, 12, 2, tzinfo=UTC),
        )
    )

    payload = build_provider_selection_records(
        xmuse_root=tmp_path,
        lane_id="lane-1",
        limit=2,
    )

    assert payload["kind"] == "provider_selection_records"
    assert payload["read_only"] is True
    assert payload["source_authority"] == "provider_selection_records_read_model"
    assert isinstance(payload["generated_at"], str)
    assert payload["generated_at"].endswith("Z")
    assert payload["filters"] == {
        "lane_id": "lane-1",
        "provider_profile_ref": None,
        "task_type": None,
        "limit": 2,
    }
    assert payload["counts"] == {
        "records": 2,
        "lanes": 1,
        "provider_profiles": 2,
        "task_types": 1,
    }
    assert payload["records"] == [
        {
            "lane_id": "lane-1",
            "selected_at": "2026-05-31T12:01:00Z",
            "generated_at": "2026-05-31T12:01:00Z",
            "provider_id": "codex",
            "profile_id": "worker",
            "provider_profile_ref": "codex.worker",
            "selected_profile_ref": "codex.worker",
            "task_type": "bounded_code_writing",
            "task_capability": "bounded_code_writing",
            "lane_risk": "low",
            "risk_tier": "low",
            "selection_reason": "Fallback to the codex worker profile.",
            "peer_type": "worker",
            "fallback_cause": "provider_unavailable",
            "health_failure_kind": "provider_unavailable",
            "source_authority": "provider_selection_record_store",
        },
        {
            "lane_id": "lane-1",
            "selected_at": "2026-05-31T12:00:00Z",
            "generated_at": "2026-05-31T12:00:00Z",
            "provider_id": "opencode",
            "profile_id": "deepseek_flash_worker",
            "provider_profile_ref": "opencode.deepseek_flash_worker",
            "selected_profile_ref": "opencode.deepseek_flash_worker",
            "task_type": "bounded_code_writing",
            "task_capability": "bounded_code_writing",
            "lane_risk": "low",
            "risk_tier": "low",
            "selection_reason": "Prefer the healthy low-cost worker profile.",
            "peer_type": "worker",
            "fallback_cause": None,
            "health_failure_kind": None,
            "source_authority": "provider_selection_record_store",
        },
    ]


def test_provider_selection_records_ignore_invalid_lines_and_do_not_mutate_projection(
    tmp_path,
) -> None:
    feature_lanes_path = tmp_path / "feature_lanes.json"
    feature_lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "Implement selection audit wiring.",
                        "model_selection_records": [{"selected_model": "gpt-5.4-mini"}],
                        "provider_health": {"diagnostic_summary": "secret"},
                        "stderr_ref": "logs/provider.err",
                    }
                ]
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    original_projection = feature_lanes_path.read_text(encoding="utf-8")

    store = ProviderSelectionRecordStore.from_xmuse_root(tmp_path)
    store.append(
        _record(
            lane_id="lane-1",
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            lane_risk=RiskTier.LOW,
            selection_reason="Keep the record bounded in the runtime read model.",
            peer_type="worker",
            selected_at=datetime(2026, 5, 31, 12, 3, tzinfo=UTC),
        )
    )
    records_path = tmp_path / "read_models" / "provider_selection_records.jsonl"
    with records_path.open("a", encoding="utf-8") as handle:
        handle.write("not-json\n")
        handle.write('{"lane_id":"broken"}\n')

    payload = build_provider_selection_records(xmuse_root=tmp_path)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["counts"]["records"] == 1
    assert payload["records"][0]["provider_profile_ref"] == "codex.worker"
    assert payload["records"][0]["selected_profile_ref"] == "codex.worker"
    assert payload["records"][0]["source_authority"] == "provider_selection_record_store"
    assert feature_lanes_path.read_text(encoding="utf-8") == original_projection
    for forbidden in (
        "stderr_ref",
        "provider_health",
        "diagnostic_summary",
        "selected_model",
    ):
        assert forbidden not in serialized


def test_provider_policy_selects_codex_god_review_and_mid_tier_coordinator() -> None:
    service = ProviderPolicyService(registry=build_default_provider_registry())

    god = service.select_god(task_type=TaskCapability.PLANNING)
    review = service.select_review()
    coordinator = service.select_coordinator(
        lane={
            "risk": "medium",
            "task_type": "lane_coordination",
        }
    )

    assert god.provider_profile_ref == "codex.god"
    assert god.task_type is TaskCapability.PLANNING
    assert "codex GOD profile" in god.selection_reason

    assert review.provider_profile_ref == "codex.review"
    assert review.task_type is TaskCapability.REVIEW
    assert "codex review profile" in review.selection_reason

    assert coordinator.provider_profile_ref == "codex.god"
    assert coordinator.task_type is TaskCapability.LANE_COORDINATION
    assert coordinator.lane_risk is RiskTier.MEDIUM
    assert "mid-tier codex coordinator profile" in coordinator.selection_reason


def test_provider_registry_reserves_gpt55_for_explicit_final_quality_profile() -> None:
    registry = build_default_provider_registry()

    default_profile = registry.get("codex.default")
    final_quality_profile = registry.get("codex.final_quality")

    assert default_profile.model_id == "gpt-5.4"
    assert final_quality_profile.model_id == "gpt-5.5"
    assert final_quality_profile.task_capabilities == (
        TaskCapability.MERGE_FINAL_REVIEW,
    )


def test_provider_policy_routes_merge_final_review_to_final_quality_profile() -> None:
    service = ProviderPolicyService(registry=build_default_provider_registry())

    final_quality = service.select_god(task_type=TaskCapability.MERGE_FINAL_REVIEW)
    planning = service.select_god(task_type=TaskCapability.PLANNING)

    assert final_quality.provider_profile_ref == "codex.final_quality"
    assert final_quality.selected_model == "gpt-5.5"
    assert "final-quality codex profile" in final_quality.selection_reason

    assert planning.provider_profile_ref == "codex.god"
    assert planning.selected_model == "gpt-5.4"


def test_provider_policy_prefers_healthy_low_cost_worker_for_bounded_low_risk_tasks() -> None:
    registry = build_default_provider_registry()
    service = ProviderPolicyService(registry=registry)
    worker_health = build_fake_provider_health_snapshot(
        registry.get("opencode.deepseek_flash_worker"),
        state=FakeProviderHealthState.READY,
        checked_at=datetime(2026, 5, 31, 12, 5, tzinfo=UTC),
    )

    decision = service.select_worker(
        lane={
            "risk": "low",
            "task_type": "mechanical_cleanup",
            "bounded_context": True,
            "well_specified": True,
            "changed_files": ["README.md"],
        },
        health_by_profile={
            worker_health.provider_profile_ref: worker_health,
        },
    )

    assert decision.provider_profile_ref == "opencode.deepseek_flash_worker"
    assert decision.lane_risk is RiskTier.LOW
    assert decision.fallback_cause is None
    assert "healthy low-cost worker profile" in decision.selection_reason
    record = decision.to_selection_record(
        lane_id="lane-worker-1",
        selected_at=datetime(2026, 5, 31, 12, 6, tzinfo=UTC),
    )
    assert record.provider_profile_ref == "opencode.deepseek_flash_worker"
    assert record.fallback_cause is None


def test_provider_policy_prefers_healthy_low_cost_worker_for_bounded_code_writing() -> None:
    registry = build_default_provider_registry()
    service = ProviderPolicyService(registry=registry)
    worker_health = build_fake_provider_health_snapshot(
        registry.get("opencode.deepseek_flash_worker"),
        state=FakeProviderHealthState.READY,
        checked_at=datetime(2026, 5, 31, 12, 6, tzinfo=UTC),
    )

    decision = service.select_worker(
        lane={
            "risk": "low",
            "task_type": "bounded_code_writing",
            "bounded_context": True,
            "well_specified": True,
        },
        health_by_profile={
            worker_health.provider_profile_ref: worker_health,
        },
    )

    assert decision.provider_profile_ref == "opencode.deepseek_flash_worker"
    assert decision.lane_risk is RiskTier.LOW
    assert decision.fallback_cause is None
    assert "healthy low-cost worker profile" in decision.selection_reason


def test_provider_policy_selects_healthy_opencode_for_bounded_deliberation_only() -> None:
    registry = build_default_provider_registry()
    service = ProviderPolicyService(registry=registry)
    worker_health = build_fake_provider_health_snapshot(
        registry.get("opencode.deepseek_flash_worker"),
        state=FakeProviderHealthState.READY,
        checked_at=datetime(2026, 6, 10, 9, 0, tzinfo=UTC),
    )

    decision = service.select_bounded_deliberation(
        lane={
            "risk": "low",
            "task_type": "bounded_deliberation",
            "bounded_context": True,
            "well_specified": True,
        },
        health_by_profile={worker_health.provider_profile_ref: worker_health},
    )

    assert decision.provider_profile_ref == "opencode.deepseek_flash_worker"
    assert decision.task_type is TaskCapability.BOUNDED_DELIBERATION
    assert decision.peer_type == "deliberation"
    assert decision.state_write_allowed is False
    assert decision.allowed_speech_acts == (
        GodSpeechAct.PROPOSE.value,
        GodSpeechAct.ASK.value,
        GodSpeechAct.CHALLENGE.value,
    )
    for forbidden in (
        GodSpeechAct.OBJECT,
        GodSpeechAct.VOTE,
        GodSpeechAct.DECIDE,
        GodSpeechAct.EVIDENCE,
        GodSpeechAct.HANDOFF,
        GodSpeechAct.RETRACT,
    ):
        assert forbidden.value not in decision.allowed_speech_acts


def test_provider_policy_falls_back_when_opencode_deliberation_is_unavailable() -> None:
    registry = build_default_provider_registry()
    service = ProviderPolicyService(registry=registry)
    worker_health = build_fake_provider_health_snapshot(
        registry.get("opencode.deepseek_flash_worker"),
        state=FakeProviderHealthState.AUTH_ERROR,
        checked_at=datetime(2026, 6, 10, 9, 1, tzinfo=UTC),
    )

    decision = service.select_bounded_deliberation(
        lane={
            "risk": "low",
            "task_type": "bounded_deliberation",
            "bounded_context": True,
            "well_specified": True,
        },
        health_by_profile={worker_health.provider_profile_ref: worker_health},
    )

    assert decision.provider_profile_ref == "codex.god"
    assert decision.task_type is TaskCapability.BOUNDED_DELIBERATION
    assert decision.peer_type == "deliberation"
    assert decision.state_write_allowed is False
    assert decision.fallback_cause == ProviderFailureKind.AUTH_ERROR.value
    assert decision.health_failure_kind == ProviderFailureKind.AUTH_ERROR.value


@pytest.mark.parametrize(
    ("health_state", "expected_profile_ref", "expected_fallback_cause"),
    [
        (FakeProviderHealthState.READY, "opencode.deepseek_flash_worker", None),
        (
            FakeProviderHealthState.UNAVAILABLE,
            "codex.worker",
            ProviderFailureKind.UNAVAILABLE.value,
        ),
        (
            FakeProviderHealthState.AUTH_ERROR,
            "codex.worker",
            ProviderFailureKind.AUTH_ERROR.value,
        ),
        (
            FakeProviderHealthState.CONFIG_ERROR,
            "codex.worker",
            ProviderFailureKind.CONFIG_ERROR.value,
        ),
        (
            FakeProviderHealthState.TIMEOUT,
            "codex.worker",
            ProviderFailureKind.TIMEOUT.value,
        ),
        (
            FakeProviderHealthState.MODEL_UNAVAILABLE,
            "codex.worker",
            ProviderFailureKind.MODEL_UNAVAILABLE.value,
        ),
        (None, "codex.worker", ProviderFailureKind.UNAVAILABLE.value),
    ],
)
def test_provider_policy_records_provider_fallback_cause_from_health_state(
    health_state: FakeProviderHealthState | None,
    expected_profile_ref: str,
    expected_fallback_cause: str | None,
) -> None:
    registry = build_default_provider_registry()
    service = ProviderPolicyService(registry=registry)
    worker_health = (
        build_fake_provider_health_snapshot(
            registry.get("opencode.deepseek_flash_worker"),
            state=health_state,
            checked_at=datetime(2026, 5, 31, 12, 7, tzinfo=UTC),
        )
        if health_state is not None
        else None
    )

    decision = service.select_worker(
        lane={
            "risk": "low",
            "task_type": "mechanical_cleanup",
            "bounded_context": True,
            "well_specified": True,
        },
        health_by_profile=(
            {
                worker_health.provider_profile_ref: worker_health,
            }
            if worker_health is not None
            else None
        ),
    )

    assert decision.provider_profile_ref == expected_profile_ref
    assert decision.fallback_cause == expected_fallback_cause
    assert decision.health_failure_kind == expected_fallback_cause
    if expected_fallback_cause is None:
        assert "healthy low-cost worker profile" in decision.selection_reason
    else:
        assert "fallback" in decision.selection_reason.lower()

    record = decision.to_selection_record(
        lane_id="lane-worker-health-1",
        selected_at=datetime(2026, 5, 31, 12, 8, tzinfo=UTC),
    )
    assert record.source_authority == "provider_policy"
    assert record.health_failure_kind == expected_fallback_cause


def test_provider_policy_escalates_repeated_ambiguous_high_risk_worker_lanes() -> None:
    service = ProviderPolicyService(registry=build_default_provider_registry())

    decision = service.select_worker(
        lane={
            "status": "reworking",
            "retry_count": 2,
            "review_summary": "Review decision: no blocking findings",
            "changed_files": [
                "src/xmuse_core/platform/orchestrator.py",
                "src/xmuse_core/providers/policy.py",
            ],
        }
    )

    assert decision.provider_profile_ref == "codex.god"
    assert decision.lane_risk is RiskTier.HIGH
    assert decision.escalation_level == "high"
    assert decision.escalation_reasons == (
        "repeated failure",
        "ambiguous review",
        "high-risk files",
        "cross-module blast radius",
    )
    assert "Escalated bounded code writing" in decision.selection_reason
