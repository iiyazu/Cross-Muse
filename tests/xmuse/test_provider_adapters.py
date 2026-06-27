from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from xmuse_core.providers.adapters.base import (
    ProviderAdapter,
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationResult,
)
from xmuse_core.providers.adapters.fake import (
    FakeAdapterOutcome,
    FakeCliWorkerHarness,
    FakeProviderAdapter,
    FakeProviderHealthState,
    build_fake_provider_health_snapshot,
)
from xmuse_core.providers.goal_contract import (
    WorkerGoalContract,
    WorkerGoalResult,
    WorkerResultStatus,
)
from xmuse_core.providers.health import ProviderHealthSnapshot
from xmuse_core.providers.models import (
    AdapterKind,
    CostTier,
    PersistentCapability,
    ProviderId,
    ProviderProfile,
    ProviderProfileId,
    RiskTier,
    TaskCapability,
)


def _build_profile() -> ProviderProfile:
    return ProviderProfile(
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.WORKER,
        adapter_kind=AdapterKind.CODEX_CLI,
        model_id="gpt-5.4-mini",
        supports_mcp=True,
        persistent_capability=PersistentCapability.SUPPORTED,
        cost_tier=CostTier.LOW,
        risk_tier=RiskTier.LOW,
        task_capabilities=[TaskCapability.BOUNDED_CODE_WRITING],
    )


def _build_goal_contract() -> WorkerGoalContract:
    return WorkerGoalContract(
        request_id="req-123",
        lane_id="lane-123",
        provider_id=ProviderId.CODEX,
        provider_profile_id=ProviderProfileId.WORKER,
        goal="Implement adapter contracts",
        acceptance_criteria=["Define shared provider adapter runtime contracts."],
        blueprint_refs=["docs/superpowers/specs/provider-platform.md"],
    )


def _build_worker_result() -> WorkerGoalResult:
    return WorkerGoalResult(
        request_id="req-123",
        provider_id=ProviderId.CODEX,
        provider_profile_id=ProviderProfileId.WORKER,
        status=WorkerResultStatus.COMPLETED,
        changed_files=["src/xmuse_core/providers/adapters/base.py"],
        tests_run=["uv run pytest tests/xmuse/test_provider_adapters.py -q"],
        evidence_refs=["artifacts/provider-adapters.md"],
        confidence=0.92,
        touched_areas=["src/xmuse_core/providers"],
        summary="Defined shared adapter contracts.",
    )


def _build_invocation(
    tmp_path,
    *,
    profile: ProviderProfile | None = None,
    task_type: TaskCapability = TaskCapability.BOUNDED_CODE_WRITING,
) -> ProviderInvocation:
    selected_profile = profile or _build_profile()
    return ProviderInvocation(
        request_id="req-123",
        provider_id=selected_profile.provider_id,
        profile_id=selected_profile.profile_id,
        task_type=task_type,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane contract.",
        workspace=tmp_path,
        timeout_seconds=120,
        goal_contract=_build_goal_contract(),
    )


def test_provider_invocation_exposes_profile_ref_and_binds_goal_contract(tmp_path) -> None:
    invocation = ProviderInvocation(
        request_id="req-123",
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.WORKER,
        task_type=TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier=RiskTier.LOW,
        prompt="Implement the lane contract.",
        workspace=tmp_path,
        timeout_seconds=120,
        goal_contract=_build_goal_contract(),
    )

    assert invocation.provider_profile_ref == "codex.worker"
    assert invocation.workspace == tmp_path
    assert invocation.goal_contract is not None

    with pytest.raises(ValidationError, match="goal_contract provider/profile"):
        ProviderInvocation(
            request_id="req-123",
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            risk_tier=RiskTier.LOW,
            prompt="Implement the lane contract.",
            workspace=tmp_path,
            timeout_seconds=120,
            goal_contract=_build_goal_contract(),
        )


def test_provider_invocation_result_requires_failure_kind_for_failed_status() -> None:
    worker_result = _build_worker_result()

    result = ProviderInvocationResult(
        request_id="req-123",
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.WORKER,
        status=WorkerResultStatus.COMPLETED,
        stdout_ref="artifacts/stdout.log",
        stderr_ref="artifacts/stderr.log",
        worker_result=worker_result,
        changed_files=["src/xmuse_core/providers/adapters/base.py"],
        tests_run=["uv run pytest tests/xmuse/test_provider_adapters.py -q"],
        evidence_refs=["artifacts/provider-adapters.md"],
    )

    assert result.provider_profile_ref == "codex.worker"
    assert result.failure_kind is None
    assert result.worker_result is worker_result
    assert result.diagnostic_payload == {}

    with pytest.raises(ValidationError, match="failure_kind must be provided"):
        ProviderInvocationResult(
            request_id="req-123",
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            status=WorkerResultStatus.FAILED,
        )


def test_provider_invocation_result_rejects_worker_result_mismatches() -> None:
    with pytest.raises(ValidationError, match="worker_result status must match"):
        ProviderInvocationResult(
            request_id="req-123",
            provider_id=ProviderId.CODEX,
            profile_id=ProviderProfileId.WORKER,
            status=WorkerResultStatus.FAILED,
            worker_result=_build_worker_result(),
            failure_kind=ProviderFailureKind.NON_ZERO_EXIT,
        )


def test_provider_health_snapshot_tracks_availability_and_bounds_diagnostics() -> None:
    snapshot = ProviderHealthSnapshot(
        provider_id=ProviderId.OPENCODE,
        profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
        checked_at=datetime(2026, 5, 31, tzinfo=UTC),
        is_available=False,
        is_configured=True,
        auth_ok=False,
        model_available=False,
        diagnostic_summary="Missing DEEPSEEK_API_KEY for opencode worker profile.",
    )

    assert snapshot.provider_profile_ref == "opencode.deepseek_flash_worker"
    assert snapshot.is_available is False

    with pytest.raises(ValidationError, match="diagnostic_summary"):
        ProviderHealthSnapshot(
            provider_id=ProviderId.OPENCODE,
            profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
            checked_at=datetime(2026, 5, 31, tzinfo=UTC),
            is_available=False,
            is_configured=False,
            auth_ok=False,
            model_available=False,
            diagnostic_summary="x" * 513,
        )


def test_provider_failure_kind_covers_required_categories() -> None:
    assert {item.value for item in ProviderFailureKind} == {
        "unavailable",
        "auth_error",
        "config_error",
        "timeout",
        "transport_crash",
        "non_zero_exit",
        "unsupported_capability",
        "model_unavailable",
        "contract_violation",
        "stale_request",
    }


def test_provider_adapter_protocol_requires_profile_invoke_and_health() -> None:
    profile = _build_profile()
    snapshot = ProviderHealthSnapshot(
        provider_id=profile.provider_id,
        profile_id=profile.profile_id,
        checked_at=datetime(2026, 5, 31, tzinfo=UTC),
        is_available=True,
        is_configured=True,
        auth_ok=True,
        model_available=True,
        diagnostic_summary="ready",
    )
    result = ProviderInvocationResult(
        request_id="req-123",
        provider_id=profile.provider_id,
        profile_id=profile.profile_id,
        status=WorkerResultStatus.COMPLETED,
        worker_result=_build_worker_result(),
        changed_files=["src/xmuse_core/providers/adapters/base.py"],
        tests_run=["uv run pytest tests/xmuse/test_provider_adapters.py -q"],
        evidence_refs=["artifacts/provider-adapters.md"],
    )

    class DummyAdapter:
        def __init__(self, profile: ProviderProfile) -> None:
            self.profile = profile

        def invoke(self, invocation: ProviderInvocation) -> ProviderInvocationResult:
            assert invocation.provider_profile_ref == self.profile.ref
            return result

        def check_health(self) -> ProviderHealthSnapshot:
            return snapshot

    adapter = DummyAdapter(profile)

    assert isinstance(adapter, ProviderAdapter)
    assert adapter.invoke(
        ProviderInvocation(
            request_id="req-123",
            provider_id=profile.provider_id,
            profile_id=profile.profile_id,
            task_type=TaskCapability.BOUNDED_CODE_WRITING,
            risk_tier=RiskTier.LOW,
            prompt="Implement the lane contract.",
            workspace=".",
            timeout_seconds=120,
        )
    ) == result
    assert adapter.check_health() == snapshot


@pytest.mark.parametrize(
    ("state", "is_available", "is_configured", "auth_ok", "model_available"),
    [
        (FakeProviderHealthState.READY, True, True, True, True),
        (FakeProviderHealthState.UNAVAILABLE, False, True, True, True),
        (FakeProviderHealthState.AUTH_ERROR, False, True, False, True),
        (FakeProviderHealthState.CONFIG_ERROR, False, False, False, False),
        (FakeProviderHealthState.TIMEOUT, False, True, True, True),
        (FakeProviderHealthState.MODEL_UNAVAILABLE, False, True, True, False),
    ],
)
def test_fake_provider_health_fixture_maps_common_provider_states(
    state: FakeProviderHealthState,
    is_available: bool,
    is_configured: bool,
    auth_ok: bool,
    model_available: bool,
) -> None:
    profile = _build_profile()

    snapshot = build_fake_provider_health_snapshot(
        profile,
        state=state,
        checked_at=datetime(2026, 5, 31, tzinfo=UTC),
    )

    assert snapshot.provider_profile_ref == profile.ref
    assert snapshot.is_available is is_available
    assert snapshot.is_configured is is_configured
    assert snapshot.auth_ok is auth_ok
    assert snapshot.model_available is model_available
    assert snapshot.diagnostic_summary is not None


def test_fake_provider_adapter_returns_successful_invocation_and_ready_health(
    tmp_path,
) -> None:
    profile = _build_profile()
    adapter = FakeProviderAdapter(
        profile,
        changed_files=["src/xmuse_core/providers/adapters/fake.py"],
        tests_run=["uv run pytest tests/xmuse/test_provider_adapters.py -q"],
        evidence_refs=["artifacts/fake-provider-adapter.md"],
    )

    result = adapter.invoke(_build_invocation(tmp_path, profile=profile))

    assert result.provider_profile_ref == profile.ref
    assert result.status is WorkerResultStatus.COMPLETED
    assert result.failure_kind is None
    assert result.changed_files == ["src/xmuse_core/providers/adapters/fake.py"]
    assert adapter.check_health().is_available is True


@pytest.mark.parametrize(
    ("outcome", "failure_kind", "health_state"),
    [
        (
            FakeAdapterOutcome.UNAVAILABLE,
            ProviderFailureKind.UNAVAILABLE,
            FakeProviderHealthState.UNAVAILABLE,
        ),
        (
            FakeAdapterOutcome.AUTH_ERROR,
            ProviderFailureKind.AUTH_ERROR,
            FakeProviderHealthState.AUTH_ERROR,
        ),
        (
            FakeAdapterOutcome.CONFIG_ERROR,
            ProviderFailureKind.CONFIG_ERROR,
            FakeProviderHealthState.CONFIG_ERROR,
        ),
        (
            FakeAdapterOutcome.TIMEOUT,
            ProviderFailureKind.TIMEOUT,
            FakeProviderHealthState.TIMEOUT,
        ),
        (
            FakeAdapterOutcome.NON_ZERO_EXIT,
            ProviderFailureKind.NON_ZERO_EXIT,
            FakeProviderHealthState.READY,
        ),
        (
            FakeAdapterOutcome.MODEL_UNAVAILABLE,
            ProviderFailureKind.MODEL_UNAVAILABLE,
            FakeProviderHealthState.MODEL_UNAVAILABLE,
        ),
        (
            FakeAdapterOutcome.CONTRACT_VIOLATION,
            ProviderFailureKind.CONTRACT_VIOLATION,
            FakeProviderHealthState.READY,
        ),
        (
            FakeAdapterOutcome.STALE_REQUEST,
            ProviderFailureKind.STALE_REQUEST,
            FakeProviderHealthState.READY,
        ),
    ],
)
def test_fake_provider_adapter_simulates_required_failure_outcomes(
    tmp_path,
    outcome: FakeAdapterOutcome,
    failure_kind: ProviderFailureKind,
    health_state: FakeProviderHealthState,
) -> None:
    profile = _build_profile()
    adapter = FakeProviderAdapter(profile, outcome=outcome)

    result = adapter.invoke(_build_invocation(tmp_path, profile=profile))
    snapshot = adapter.check_health()
    expected_snapshot = build_fake_provider_health_snapshot(
        profile,
        state=health_state,
        checked_at=snapshot.checked_at,
    )

    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is failure_kind
    assert snapshot == expected_snapshot


def test_fake_provider_adapter_reports_unsupported_capability_from_profile(
    tmp_path,
) -> None:
    profile = _build_profile()
    adapter = FakeProviderAdapter(profile)

    result = adapter.invoke(
        _build_invocation(
            tmp_path,
            profile=profile,
            task_type=TaskCapability.REVIEW,
        )
    )

    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.UNSUPPORTED_CAPABILITY


def test_fake_cli_worker_harness_validates_structured_worker_output(tmp_path) -> None:
    profile = _build_profile()
    worker_result = _build_worker_result().model_dump(mode="python") | {
        "evidence": [
            {
                "kind": "changed_file",
                "ref": "src/xmuse_core/providers/adapters/base.py",
                "summary": "Provider adapter contract changed.",
            }
        ],
        "verification": [
            {
                "command": "uv run pytest tests/xmuse/test_provider_adapters.py -q",
                "status": "passed",
                "exit_code": 0,
            }
        ],
    }
    harness = FakeCliWorkerHarness(profile, worker_result_payload=worker_result)

    result = harness.invoke(_build_invocation(tmp_path, profile=profile))

    assert result.status is WorkerResultStatus.COMPLETED
    assert result.worker_result is not None
    assert result.worker_result.evidence[0].kind.value == "changed_file"
    assert result.worker_result.verification[0].status.value == "passed"
    assert result.failure_kind is None


def test_fake_cli_worker_harness_maps_contract_violations_to_failure_kind(
    tmp_path,
) -> None:
    profile = _build_profile()
    worker_result = _build_worker_result().model_dump(mode="python") | {
        "request_id": "stale-req",
    }
    harness = FakeCliWorkerHarness(profile, worker_result_payload=worker_result)

    result = harness.invoke(_build_invocation(tmp_path, profile=profile))

    assert result.status is WorkerResultStatus.FAILED
    assert result.failure_kind is ProviderFailureKind.STALE_REQUEST
    assert result.worker_result is None
