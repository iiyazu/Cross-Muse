from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Protocol

from xmuse_core.integrations.a2a_provider_client import (
    A2AProviderClient,
    A2AProviderTaskRequest,
)
from xmuse_core.integrations.a2a_sdk_boundary import NormalizedA2ATaskResult
from xmuse_core.providers.adapters.base import (
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationResult,
)
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.health import ProviderHealthSnapshot
from xmuse_core.providers.models import AdapterKind, ProviderId, ProviderProfile


class A2ATaskClient(Protocol):
    def invoke_task(
        self,
        request: A2AProviderTaskRequest,
    ) -> Awaitable[NormalizedA2ATaskResult]: ...


class A2AProviderAdapter:
    """Expose a remote A2A agent through the existing provider adapter contract.

    This adapter deliberately returns only `ProviderInvocationResult`. It does
    not write chat.db, approve reviews, dispatch work, or promote A2A task state
    into xmuse authority.
    """

    def __init__(
        self,
        profile: ProviderProfile,
        *,
        endpoint_url: str,
        api_key: str | None = None,
        client: A2ATaskClient | None = None,
        checked_at_factory: Callable[[], datetime] | None = None,
    ) -> None:
        if profile.provider_id is not ProviderId.A2A:
            raise ValueError("A2AProviderAdapter requires an a2a profile")
        if profile.adapter_kind is not AdapterKind.A2A_REMOTE:
            raise ValueError("A2AProviderAdapter requires an a2a_remote profile")
        self.profile = profile
        self._endpoint_url = _clean_text(endpoint_url, "endpoint_url")
        self._api_key = _clean_optional_text(api_key, "api_key")
        self._client = client or A2AProviderClient(
            self._endpoint_url,
            api_key=self._api_key,
        )
        self._checked_at_factory = checked_at_factory or (lambda: datetime.now(UTC))

    def invoke(self, invocation: ProviderInvocation) -> ProviderInvocationResult:
        if (
            invocation.provider_id is not self.profile.provider_id
            or invocation.profile_id is not self.profile.profile_id
        ):
            return self._failure_result(
                invocation,
                failure_kind=ProviderFailureKind.CONTRACT_VIOLATION,
                evidence_refs=["a2a_adapter:profile_mismatch"],
            )
        if invocation.task_type not in self.profile.task_capabilities:
            return self._failure_result(
                invocation,
                failure_kind=ProviderFailureKind.UNSUPPORTED_CAPABILITY,
                evidence_refs=["a2a_adapter:unsupported_capability"],
            )

        request = self._build_task_request(invocation)
        try:
            result = _run_awaitable(self._client.invoke_task(request))
        except Exception as exc:  # noqa: BLE001 - adapter must fail closed.
            return self._failure_result(
                invocation,
                failure_kind=ProviderFailureKind.TRANSPORT_CRASH,
                evidence_refs=[
                    f"a2a_task:{invocation.request_id}",
                    f"a2a_adapter_exception:{exc.__class__.__name__}",
                ],
            )

        status = _worker_status(result)
        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            status=status,
            evidence_refs=_evidence_refs(result),
            failure_kind=_failure_kind(result, status),
        )

    def check_health(self) -> ProviderHealthSnapshot:
        return ProviderHealthSnapshot(
            provider_id=self.profile.provider_id,
            profile_id=self.profile.profile_id,
            checked_at=self._checked_at_factory(),
            is_available=True,
            is_configured=True,
            auth_ok=True,
            model_available=True,
            diagnostic_summary="A2A adapter configured; live remote health not probed.",
        )

    def _build_task_request(
        self,
        invocation: ProviderInvocation,
    ) -> A2AProviderTaskRequest:
        context_id = invocation.request_id
        metadata: dict[str, object] = {
            "xmuse_provider_profile_ref": invocation.provider_profile_ref,
            "xmuse_task_type": invocation.task_type.value,
            "xmuse_risk_tier": invocation.risk_tier.value,
            "xmuse_workspace": str(invocation.workspace),
        }
        if invocation.goal_contract is not None:
            context_id = invocation.goal_contract.lane_id
            metadata["xmuse_goal_contract"] = {
                "lane_id": invocation.goal_contract.lane_id,
                "acceptance_criteria": list(
                    invocation.goal_contract.acceptance_criteria
                ),
                "blueprint_refs": list(invocation.goal_contract.blueprint_refs),
            }
        return A2AProviderTaskRequest(
            task_id=invocation.request_id,
            context_id=context_id,
            sender_agent_id=f"xmuse:{self.profile.ref}",
            content=invocation.prompt,
            metadata=metadata,
        )

    def _failure_result(
        self,
        invocation: ProviderInvocation,
        *,
        failure_kind: ProviderFailureKind,
        evidence_refs: list[str],
    ) -> ProviderInvocationResult:
        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=invocation.provider_id,
            profile_id=invocation.profile_id,
            status=WorkerResultStatus.FAILED,
            evidence_refs=evidence_refs,
            failure_kind=failure_kind,
        )


def _run_awaitable(
    awaitable: Awaitable[NormalizedA2ATaskResult],
) -> NormalizedA2ATaskResult:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    with ThreadPoolExecutor(max_workers=1) as executor:
        return executor.submit(lambda: asyncio.run(awaitable)).result()


def _worker_status(result: NormalizedA2ATaskResult) -> WorkerResultStatus:
    if result.disposition == "completed":
        return WorkerResultStatus.COMPLETED
    if result.disposition == "blocked":
        return WorkerResultStatus.BLOCKED
    return WorkerResultStatus.FAILED


def _failure_kind(
    result: NormalizedA2ATaskResult,
    status: WorkerResultStatus,
) -> ProviderFailureKind | None:
    if status is not WorkerResultStatus.FAILED:
        return None
    if "transport_error" in result.metadata:
        return ProviderFailureKind.UNAVAILABLE
    return ProviderFailureKind.CONTRACT_VIOLATION


def _evidence_refs(result: NormalizedA2ATaskResult) -> list[str]:
    refs = list(result.source_refs)
    refs.append(f"a2a_state:{result.state}")
    refs.append(f"a2a_disposition:{result.disposition}")
    if result.jsonrpc_id is not None:
        refs.append(f"a2a_jsonrpc:{result.jsonrpc_id}")
    return refs


def _clean_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must be non-empty")
    return cleaned


def _clean_optional_text(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    return _clean_text(value, field_name)
