from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from xmuse_core.providers.adapters.base import (
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationResult,
)
from xmuse_core.providers.goal_contract import (
    WorkerGoalResult,
    WorkerResultStatus,
    validate_worker_goal_result,
)
from xmuse_core.providers.health import ProviderHealthFailureKind, ProviderHealthSnapshot
from xmuse_core.providers.models import ProviderProfile


class FakeProviderHealthState(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    AUTH_ERROR = "auth_error"
    CONFIG_ERROR = "config_error"
    TIMEOUT = "timeout"
    MODEL_UNAVAILABLE = "model_unavailable"


class FakeAdapterOutcome(StrEnum):
    SUCCESS = "success"
    UNAVAILABLE = ProviderFailureKind.UNAVAILABLE.value
    AUTH_ERROR = ProviderFailureKind.AUTH_ERROR.value
    CONFIG_ERROR = ProviderFailureKind.CONFIG_ERROR.value
    TIMEOUT = ProviderFailureKind.TIMEOUT.value
    NON_ZERO_EXIT = ProviderFailureKind.NON_ZERO_EXIT.value
    UNSUPPORTED_CAPABILITY = ProviderFailureKind.UNSUPPORTED_CAPABILITY.value
    MODEL_UNAVAILABLE = ProviderFailureKind.MODEL_UNAVAILABLE.value
    CONTRACT_VIOLATION = ProviderFailureKind.CONTRACT_VIOLATION.value
    STALE_REQUEST = ProviderFailureKind.STALE_REQUEST.value


_DEFAULT_DIAGNOSTIC_SUMMARIES = {
    FakeProviderHealthState.READY: "ready",
    FakeProviderHealthState.UNAVAILABLE: "provider unavailable",
    FakeProviderHealthState.AUTH_ERROR: "provider authentication failed",
    FakeProviderHealthState.CONFIG_ERROR: "provider configuration is missing or invalid",
    FakeProviderHealthState.TIMEOUT: "provider health check timed out",
    FakeProviderHealthState.MODEL_UNAVAILABLE: "provider model unavailable",
}

_HEALTH_STATE_FLAGS = {
    FakeProviderHealthState.READY: (True, True, True, True),
    FakeProviderHealthState.UNAVAILABLE: (False, True, True, True),
    FakeProviderHealthState.AUTH_ERROR: (False, True, False, True),
    FakeProviderHealthState.CONFIG_ERROR: (False, False, False, False),
    FakeProviderHealthState.TIMEOUT: (False, True, True, True),
    FakeProviderHealthState.MODEL_UNAVAILABLE: (False, True, True, False),
}

_HEALTH_STATE_FAILURE_KINDS = {
    FakeProviderHealthState.READY: None,
    FakeProviderHealthState.UNAVAILABLE: ProviderHealthFailureKind.UNAVAILABLE,
    FakeProviderHealthState.AUTH_ERROR: ProviderHealthFailureKind.AUTH_ERROR,
    FakeProviderHealthState.CONFIG_ERROR: ProviderHealthFailureKind.CONFIG_ERROR,
    FakeProviderHealthState.TIMEOUT: ProviderHealthFailureKind.TIMEOUT,
    FakeProviderHealthState.MODEL_UNAVAILABLE: ProviderHealthFailureKind.MODEL_UNAVAILABLE,
}

_OUTCOME_TO_FAILURE_KIND = {
    FakeAdapterOutcome.UNAVAILABLE: ProviderFailureKind.UNAVAILABLE,
    FakeAdapterOutcome.AUTH_ERROR: ProviderFailureKind.AUTH_ERROR,
    FakeAdapterOutcome.CONFIG_ERROR: ProviderFailureKind.CONFIG_ERROR,
    FakeAdapterOutcome.TIMEOUT: ProviderFailureKind.TIMEOUT,
    FakeAdapterOutcome.NON_ZERO_EXIT: ProviderFailureKind.NON_ZERO_EXIT,
    FakeAdapterOutcome.UNSUPPORTED_CAPABILITY: ProviderFailureKind.UNSUPPORTED_CAPABILITY,
    FakeAdapterOutcome.MODEL_UNAVAILABLE: ProviderFailureKind.MODEL_UNAVAILABLE,
    FakeAdapterOutcome.CONTRACT_VIOLATION: ProviderFailureKind.CONTRACT_VIOLATION,
    FakeAdapterOutcome.STALE_REQUEST: ProviderFailureKind.STALE_REQUEST,
}

_OUTCOME_TO_HEALTH_STATE = {
    FakeAdapterOutcome.SUCCESS: FakeProviderHealthState.READY,
    FakeAdapterOutcome.UNAVAILABLE: FakeProviderHealthState.UNAVAILABLE,
    FakeAdapterOutcome.AUTH_ERROR: FakeProviderHealthState.AUTH_ERROR,
    FakeAdapterOutcome.CONFIG_ERROR: FakeProviderHealthState.CONFIG_ERROR,
    FakeAdapterOutcome.TIMEOUT: FakeProviderHealthState.TIMEOUT,
    FakeAdapterOutcome.NON_ZERO_EXIT: FakeProviderHealthState.READY,
    FakeAdapterOutcome.UNSUPPORTED_CAPABILITY: FakeProviderHealthState.READY,
    FakeAdapterOutcome.MODEL_UNAVAILABLE: FakeProviderHealthState.MODEL_UNAVAILABLE,
    FakeAdapterOutcome.CONTRACT_VIOLATION: FakeProviderHealthState.READY,
    FakeAdapterOutcome.STALE_REQUEST: FakeProviderHealthState.READY,
}


def build_fake_provider_health_snapshot(
    profile: ProviderProfile,
    *,
    state: FakeProviderHealthState = FakeProviderHealthState.READY,
    checked_at: datetime | None = None,
    diagnostic_summary: str | None = None,
) -> ProviderHealthSnapshot:
    is_available, is_configured, auth_ok, model_available = _HEALTH_STATE_FLAGS[state]
    return ProviderHealthSnapshot(
        provider_id=profile.provider_id,
        profile_id=profile.profile_id,
        checked_at=checked_at or datetime.now(UTC),
        is_available=is_available,
        is_configured=is_configured,
        auth_ok=auth_ok,
        model_available=model_available,
        failure_kind=_HEALTH_STATE_FAILURE_KINDS[state],
        diagnostic_summary=diagnostic_summary or _DEFAULT_DIAGNOSTIC_SUMMARIES[state],
    )


class FakeProviderAdapter:
    def __init__(
        self,
        profile: ProviderProfile,
        *,
        outcome: FakeAdapterOutcome = FakeAdapterOutcome.SUCCESS,
        health_state: FakeProviderHealthState | None = None,
        diagnostic_summary: str | None = None,
        checked_at: datetime | None = None,
        worker_result: WorkerGoalResult | None = None,
        changed_files: list[str] | tuple[str, ...] = (),
        tests_run: list[str] | tuple[str, ...] = (),
        evidence_refs: list[str] | tuple[str, ...] = (),
        stdout_ref: str | None = None,
        stderr_ref: str | None = None,
    ) -> None:
        self.profile = profile
        self._outcome = outcome
        self._worker_result = worker_result
        self._changed_files = list(changed_files)
        self._tests_run = list(tests_run)
        self._evidence_refs = list(evidence_refs)
        self._stdout_ref = stdout_ref
        self._stderr_ref = stderr_ref
        self._health_snapshot = build_fake_provider_health_snapshot(
            profile,
            state=health_state or _OUTCOME_TO_HEALTH_STATE[outcome],
            checked_at=checked_at,
            diagnostic_summary=diagnostic_summary,
        )

    def invoke(self, invocation: ProviderInvocation) -> ProviderInvocationResult:
        if (
            invocation.provider_id is not self.profile.provider_id
            or invocation.profile_id is not self.profile.profile_id
        ):
            return self._build_failure_result(
                invocation,
                ProviderFailureKind.CONTRACT_VIOLATION,
            )

        if invocation.task_type not in self.profile.task_capabilities:
            return self._build_failure_result(
                invocation,
                ProviderFailureKind.UNSUPPORTED_CAPABILITY,
            )

        if self._outcome is FakeAdapterOutcome.SUCCESS:
            return self._build_result(invocation, status=WorkerResultStatus.COMPLETED)

        if self._outcome is FakeAdapterOutcome.UNSUPPORTED_CAPABILITY:
            return self._build_failure_result(
                invocation,
                ProviderFailureKind.UNSUPPORTED_CAPABILITY,
            )

        return self._build_failure_result(
            invocation,
            _OUTCOME_TO_FAILURE_KIND[self._outcome],
        )

    def check_health(self) -> ProviderHealthSnapshot:
        return self._health_snapshot

    def _build_failure_result(
        self,
        invocation: ProviderInvocation,
        failure_kind: ProviderFailureKind,
    ) -> ProviderInvocationResult:
        return self._build_result(
            invocation,
            status=WorkerResultStatus.FAILED,
            failure_kind=failure_kind,
        )

    def _build_result(
        self,
        invocation: ProviderInvocation,
        *,
        status: WorkerResultStatus,
        failure_kind: ProviderFailureKind | None = None,
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=status,
            stdout_ref=self._stdout_ref,
            stderr_ref=self._stderr_ref,
            worker_result=self._worker_result,
            changed_files=self._changed_files,
            tests_run=self._tests_run,
            evidence_refs=self._evidence_refs,
            failure_kind=failure_kind,
        )


class FakeCliWorkerHarness:
    def __init__(
        self,
        profile: ProviderProfile,
        *,
        worker_result_payload: WorkerGoalResult | dict[str, Any] | None = None,
        outcome: FakeAdapterOutcome = FakeAdapterOutcome.SUCCESS,
        stdout_ref: str | None = None,
        stderr_ref: str | None = None,
    ) -> None:
        self.profile = profile
        self._worker_result_payload = worker_result_payload
        self._outcome = outcome
        self._stdout_ref = stdout_ref
        self._stderr_ref = stderr_ref

    def invoke(self, invocation: ProviderInvocation) -> ProviderInvocationResult:
        if (
            invocation.provider_id is not self.profile.provider_id
            or invocation.profile_id is not self.profile.profile_id
        ):
            return self._failure(invocation, ProviderFailureKind.CONTRACT_VIOLATION)

        if invocation.task_type not in self.profile.task_capabilities:
            return self._failure(invocation, ProviderFailureKind.UNSUPPORTED_CAPABILITY)

        if self._outcome is not FakeAdapterOutcome.SUCCESS:
            return self._failure(invocation, _OUTCOME_TO_FAILURE_KIND[self._outcome])

        if self._worker_result_payload is None:
            return ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=self.profile.provider_id,
                profile_id=self.profile.profile_id,
                status=WorkerResultStatus.COMPLETED,
                stdout_ref=self._stdout_ref,
                stderr_ref=self._stderr_ref,
            )

        try:
            worker_result = (
                self._worker_result_payload
                if isinstance(self._worker_result_payload, WorkerGoalResult)
                else WorkerGoalResult.model_validate(self._worker_result_payload)
            )
            if invocation.goal_contract is not None:
                worker_result = validate_worker_goal_result(
                    worker_result,
                    contract=invocation.goal_contract,
                )
        except ValueError as exc:
            failure_kind = (
                ProviderFailureKind.STALE_REQUEST
                if "stale request id" in str(exc)
                else ProviderFailureKind.CONTRACT_VIOLATION
            )
            return self._failure(invocation, failure_kind)

        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=worker_result.status,
            stdout_ref=self._stdout_ref,
            stderr_ref=self._stderr_ref,
            worker_result=worker_result,
            changed_files=worker_result.changed_files,
            tests_run=worker_result.tests_run,
            evidence_refs=worker_result.evidence_refs,
            failure_kind=(
                ProviderFailureKind.NON_ZERO_EXIT
                if worker_result.status is WorkerResultStatus.FAILED
                else None
            ),
        )

    def _failure(
        self,
        invocation: ProviderInvocation,
        failure_kind: ProviderFailureKind,
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=WorkerResultStatus.FAILED,
            stdout_ref=self._stdout_ref,
            stderr_ref=self._stderr_ref,
            failure_kind=failure_kind,
        )


__all__ = [
    "FakeAdapterOutcome",
    "FakeCliWorkerHarness",
    "FakeProviderAdapter",
    "FakeProviderHealthState",
    "build_fake_provider_health_snapshot",
]
