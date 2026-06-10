from __future__ import annotations

from pathlib import Path

from xmuse_core.agents.provider_session_binding_store import ProviderSessionBindingStore
from xmuse_core.platform.execution.provider_session_binding import (
    plan_execution_runtime_session_route,
    plan_review_runtime_session_route,
    resolve_execution_provider_session_binding,
    resolve_review_provider_session_binding,
)
from xmuse_core.providers.adapters.base import ProviderInvocation
from xmuse_core.providers.models import ProviderId, ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    ProviderSessionBindingDegradationEvidence,
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)


def test_resolve_execution_provider_session_binding_requires_explicit_god_session_id(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    store.upsert_active(_binding(worktree=str(tmp_path)))

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={"feature_id": "lane-a", "graph_id": "graph-feature-a"},
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert resolved is None


def test_resolve_execution_provider_session_binding_returns_compatible_codex_binding(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path)))

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert resolved == binding


def test_plan_execution_runtime_session_route_prefers_explicit_resume_for_compatible_binding(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path)))

    route = plan_execution_runtime_session_route(
        store=store,
        provider_adapter=RunnerProviderService(),
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert route.primary_path == "explicit_provider_resume"
    assert route.provider_session_binding == binding


def test_plan_execution_runtime_session_route_disables_persistent_for_opencode(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    store.upsert_active(
        _binding(
            provider="opencode",
            provider_session_id="opencode-session-11111111",
            model="deepseek-v4-flash",
            worktree=str(tmp_path),
        ).model_copy(update={"god_session_id": "god-opencode-demo"})
    )

    route = plan_execution_runtime_session_route(
        store=store,
        provider_adapter=RunnerProviderService(),
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-opencode-demo",
        },
        invocation=ProviderInvocation(
            request_id="lane-a:execute",
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            risk_tier=RiskTier.LOW,
            prompt="Prompt",
            workspace=tmp_path,
            timeout_seconds=60,
        ),
        model="deepseek-v4-flash",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert route.primary_path == "persistent_execute_or_fallback"
    assert route.provider_session_binding is None
    assert route.allows_persistent_execute is False
    assert (
        route.persistent_execute_unsupported_reason
        == "provider_persistent_execute_unsupported"
    )


def test_resolve_execution_provider_session_binding_ignores_projection_mark_failed_degradation(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path)))

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
            "provider_session_binding_degraded": True,
            "provider_session_binding_degraded_reason": "mark_failed_failed",
            "provider_session_binding_id": binding.binding_id,
        },
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert resolved == binding


def test_resolve_execution_provider_session_binding_ignores_projection_upsert_failed_degradation(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path)))

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
            "provider_session_binding_degraded": True,
            "provider_session_binding_degraded_reason": "upsert_failed",
            "provider_session_binding_id": binding.binding_id,
        },
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert resolved == binding


def test_resolve_execution_provider_session_binding_quarantines_graph_native_degradation(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path)))
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _running_status(
            provider_session_binding_degradations=[
                ProviderSessionBindingDegradationEvidence(
                    binding_id=binding.binding_id,
                    reason="upsert_failed",
                    evidence_refs=[binding.binding_id, "runtime:execution_god:lane-a"],
                    failure="provider store write failed",
                )
            ]
        )
    )

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_set_id": "graph-set-1",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
        feature_graph_status_store=status_store,
    )

    assert resolved is None


def test_resolve_execution_provider_session_binding_ignores_stale_projection_degradation(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path)))
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_running_status())

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_set_id": "graph-set-1",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
            "provider_session_binding_degraded": True,
            "provider_session_binding_degraded_reason": "upsert_failed",
            "provider_session_binding_id": binding.binding_id,
        },
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
        feature_graph_status_store=status_store,
    )

    assert resolved == binding


def test_resolve_execution_provider_session_binding_ignores_incompatible_binding(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    store.upsert_active(_binding(worktree=str(tmp_path), model="gpt-5.2-codex"))

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=_provider_invocation(tmp_path),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert resolved is None


def test_resolve_execution_provider_session_binding_ignores_non_codex_invocation(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    store.upsert_active(_binding(worktree=str(tmp_path)))

    resolved = resolve_execution_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=ProviderInvocation(
            request_id="lane-a:execute",
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            risk_tier=RiskTier.LOW,
            prompt="Prompt",
            workspace=tmp_path,
            timeout_seconds=60,
        ),
        model="deepseek-v4-flash",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert resolved is None


def test_resolve_review_provider_session_binding_returns_compatible_codex_binding(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path), session_kind="review"))

    resolved = resolve_review_provider_session_binding(
        store=store,
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=_provider_invocation(tmp_path, task_type=TaskCapability.REVIEW),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert resolved == binding


def test_plan_review_runtime_session_route_skips_stale_binding(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = store.upsert_active(_binding(worktree=str(tmp_path), session_kind="review"))
    store.mark_failed(
        binding.binding_id,
        status=ProviderSessionBindingStatus.STALE,
        reason="review_stale_request",
    )

    route = plan_review_runtime_session_route(
        store=store,
        provider_adapter=RunnerProviderService(),
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=_provider_invocation(tmp_path, task_type=TaskCapability.REVIEW),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert route.primary_path == "persistent_review_or_fallback"
    assert route.provider_session_binding is None


def test_plan_review_runtime_session_route_ignores_incompatible_binding(
    tmp_path: Path,
) -> None:
    store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    store.upsert_active(
        _binding(
            worktree=str(tmp_path),
            session_kind="review",
            model="gpt-5.2-codex",
        )
    )

    route = plan_review_runtime_session_route(
        store=store,
        provider_adapter=RunnerProviderService(),
        lane={
            "feature_id": "lane-a",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
        invocation=_provider_invocation(tmp_path, task_type=TaskCapability.REVIEW),
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
    )

    assert route.primary_path == "persistent_review_or_fallback"
    assert route.provider_session_binding is None


def _provider_invocation(
    tmp_path: Path,
    *,
    task_type: TaskCapability = TaskCapability.LANE_COORDINATION,
) -> ProviderInvocation:
    return ProviderInvocation(
        request_id="lane-a:execute",
        provider_id=ProviderId.CODEX,
        profile_id=(
            ProviderProfileId.REVIEW
            if task_type is TaskCapability.REVIEW
            else ProviderProfileId.DEFAULT
        ),
        task_type=task_type,
        risk_tier=RiskTier.MEDIUM,
        prompt="Prompt",
        workspace=tmp_path,
        timeout_seconds=60,
    )


def _binding(
    *,
    worktree: str,
    session_kind: str = "exec",
    provider: str = "codex",
    provider_session_id: str = "codex-session-11111111-2222-3333-4444-555555555555",
    model: str = "gpt-5.4",
) -> ProviderSessionBindingRecord:
    return ProviderSessionBindingRecord(
        binding_id="psb-codex-demo",
        god_session_id="god-worker-demo",
        provider=provider,
        provider_session_id=provider_session_id,
        session_kind=session_kind,
        status=ProviderSessionBindingStatus.ACTIVE,
        conversation_id="conv-xmuse-hardening",
        feature_graph_id="graph-feature-a",
        role="reviewer" if session_kind == "review" else "feature_worker",
        cwd="/repo",
        worktree=worktree,
        model=model,
        prompt_fingerprint="sha256:prompt-demo",
        created_at="2026-06-03T02:10:00Z",
        last_used_at="2026-06-03T02:11:00Z",
        last_verified_at="2026-06-03T02:11:30Z",
        resume_command_template="codex exec resume {provider_session_id}",
    )


def _running_status(
    *,
    provider_session_binding_degradations: list[
        ProviderSessionBindingDegradationEvidence
    ] | None = None,
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id="fgs-running",
        conversation_id="conv-xmuse-hardening",
        planning_run_id="planning-1",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_plan_id="feature-plan-1",
        feature_plan_version=1,
        feature_id="feature-a",
        feature_graph_id="graph-feature-a",
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["lane-a"],
        active_worker_session_id="god-worker-demo",
        active_provider_session_binding_ref="psb-codex-demo",
        completed_lane_ids=[],
        blocked_lane_ids=[],
        projection_lane_ids=["lane:conv-xmuse-hardening:graph-feature-a:lane-a"],
        feature_lanes_projection_ref="feature_lanes.json#projection_revision=7",
        provider_session_binding_degradations=(
            provider_session_binding_degradations or []
        ),
        updated_at="2026-06-03T03:10:00Z",
    )
