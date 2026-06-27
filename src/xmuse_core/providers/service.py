from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from xmuse_core.agents.protocol import AgentOutput
from xmuse_core.providers.adapters.base import (
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationResult,
)
from xmuse_core.providers.adapters.codex import CodexProviderAdapter
from xmuse_core.providers.adapters.opencode import OpenCodeProviderAdapter
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.health import ProviderHealthSnapshot
from xmuse_core.providers.models import ProviderId, RiskTier, TaskCapability
from xmuse_core.providers.policy import ProviderPolicyService, is_low_risk_bounded_task
from xmuse_core.providers.registry import ProviderRegistry, build_default_provider_registry
from xmuse_core.providers.selection_record import (
    ProviderSelectionRecord,
    ProviderSelectionRecordStore,
)
from xmuse_core.structuring.feature_review_contracts import ProviderSessionBindingRecord

if TYPE_CHECKING:
    from xmuse_core.platform.agent_spawner import SpawnResult

DEFAULT_EXECUTION_PROVIDER_PROFILE_REF = "codex.default"
DEFAULT_REVIEW_PROVIDER_PROFILE_REF = "codex.review"
PromptDeliveryMode = Literal["stdin", "argv"]


class RunnerProviderService:
    def __init__(
        self,
        *,
        mcp_port: int = 8100,
        registry: ProviderRegistry | None = None,
        policy_service: ProviderPolicyService | None = None,
        selection_record_store: ProviderSelectionRecordStore | None = None,
        execution_provider_profile_ref: str = DEFAULT_EXECUTION_PROVIDER_PROFILE_REF,
        review_provider_profile_ref: str = DEFAULT_REVIEW_PROVIDER_PROFILE_REF,
        health_by_profile: Mapping[str, ProviderHealthSnapshot] | None = None,
    ) -> None:
        self._mcp_port = mcp_port
        self._registry = registry or build_default_provider_registry()
        self._policy_service = policy_service or ProviderPolicyService(
            registry=self._registry
        )
        self._selection_record_store = selection_record_store
        self._execution_provider_profile_ref = execution_provider_profile_ref
        self._review_provider_profile_ref = review_provider_profile_ref
        self._health_by_profile = dict(health_by_profile or {})
        self._pending_selection_records: dict[str, ProviderSelectionRecord] = {}

    def build_execution_invocation(
        self,
        *,
        lane_id: str,
        prompt: str,
        workspace: Path,
        timeout_seconds: int,
        provider_profile_ref: str | None = None,
        lane: Mapping[str, Any] | None = None,
        risk_tier: RiskTier = RiskTier.MEDIUM,
    ) -> ProviderInvocation:
        if provider_profile_ref is None and lane is not None and is_low_risk_bounded_task(lane):
            decision = self._policy_service.select_worker(
                lane=lane,
                health_by_profile=self._health_by_profile or None,
            )
            return self._build_invocation_for_decision(
                lane_id=lane_id,
                prompt=prompt,
                workspace=workspace,
                timeout_seconds=timeout_seconds,
                request_suffix="execute",
                decision=decision,
            )
        return self._build_invocation(
            lane_id=lane_id,
            prompt=prompt,
            workspace=workspace,
            timeout_seconds=timeout_seconds,
            provider_profile_ref=provider_profile_ref or self._execution_provider_profile_ref,
            task_type=TaskCapability.LANE_COORDINATION,
            risk_tier=risk_tier,
            request_suffix="execute",
        )

    def build_review_invocation(
        self,
        *,
        lane_id: str,
        prompt: str,
        workspace: Path,
        timeout_seconds: int,
        provider_profile_ref: str | None = None,
        lane: Mapping[str, Any] | None = None,
        risk_tier: RiskTier = RiskTier.HIGH,
    ) -> ProviderInvocation:
        if provider_profile_ref is None:
            decision = self._policy_service.select_review(lane=lane)
            return self._build_invocation_for_decision(
                lane_id=lane_id,
                prompt=prompt,
                workspace=workspace,
                timeout_seconds=timeout_seconds,
                request_suffix="review",
                decision=decision,
            )
        return self._build_invocation(
            lane_id=lane_id,
            prompt=prompt,
            workspace=workspace,
            timeout_seconds=timeout_seconds,
            provider_profile_ref=provider_profile_ref or self._review_provider_profile_ref,
            task_type=TaskCapability.REVIEW,
            risk_tier=risk_tier,
            request_suffix="review",
        )

    def runtime_for_invocation(self, invocation: ProviderInvocation) -> str:
        if invocation.provider_id is ProviderId.A2A:
            return "a2a"
        if invocation.provider_id is ProviderId.CODEX:
            return "codex"
        if invocation.provider_id is ProviderId.OPENCODE:
            return "opencode"
        raise ValueError(
            f"unsupported provider runtime for {invocation.provider_profile_ref!r}"
        )

    def supports_explicit_session_resume(self, invocation: ProviderInvocation) -> bool:
        profile = self._registry.get(invocation.provider_profile_ref)
        if invocation.provider_id is ProviderId.CODEX:
            return profile.supports_persistent_sessions
        return False

    def supports_persistent_execute(self, invocation: ProviderInvocation) -> bool:
        profile = self._registry.get(invocation.provider_profile_ref)
        return profile.supports_persistent_sessions

    def model_for_invocation(
        self,
        invocation: ProviderInvocation,
        *,
        model_override: str | None = None,
    ) -> str:
        if model_override and model_override.strip():
            return model_override.strip()
        profile = self._registry.get(invocation.provider_profile_ref)
        return profile.model_id

    def prompt_delivery_for_invocation(
        self,
        invocation: ProviderInvocation,
    ) -> PromptDeliveryMode:
        if invocation.provider_id is ProviderId.OPENCODE:
            return "argv"
        return "stdin"

    def build_command(
        self,
        invocation: ProviderInvocation,
        *,
        model_override: str | None = None,
        provider_session_binding: ProviderSessionBindingRecord | None = None,
    ) -> list[str]:
        if invocation.provider_id is ProviderId.CODEX:
            return self._codex_adapter(
                invocation.provider_profile_ref,
                model_override=model_override,
            ).build_command_for_invocation(
                invocation,
                provider_session_binding=provider_session_binding,
            )
        if provider_session_binding is not None:
            raise ValueError(
                "provider session binding is only supported for Codex exec commands"
            )
        if invocation.provider_id is ProviderId.OPENCODE:
            return self._opencode_adapter(invocation.provider_profile_ref).build_command(
                invocation
            )
        raise ValueError(
            f"unsupported provider command for {invocation.provider_profile_ref!r}"
        )

    def build_env(
        self,
        invocation: ProviderInvocation,
        *,
        lane_id: str,
        base_env: Mapping[str, str],
    ) -> dict[str, str]:
        runtime_env = dict(base_env)
        if invocation.provider_id is ProviderId.CODEX:
            runtime_env["XMUSE_FEATURE_ID"] = lane_id
            return runtime_env
        if invocation.provider_id is ProviderId.OPENCODE:
            return self._opencode_adapter(invocation.provider_profile_ref).build_env(
                runtime_env
            )
        raise ValueError(
            f"unsupported provider environment for {invocation.provider_profile_ref!r}"
        )

    def build_result_from_spawn_result(
        self,
        invocation: ProviderInvocation,
        result: SpawnResult,
    ) -> ProviderInvocationResult:
        artifacts = {}
        if result.stdout_log_path:
            artifacts["stdout_ref"] = result.stdout_log_path
        if result.stderr_log_path:
            artifacts["stderr_ref"] = result.stderr_log_path
        if result.stdout:
            artifacts["stdout"] = result.stdout
        if invocation.provider_id is ProviderId.CODEX:
            output = AgentOutput(
                status=(
                    "timeout"
                    if result.timed_out
                    else "success"
                    if result.exit_code == 0
                    else "error"
                ),
                artifacts=artifacts,
                error_code=(
                    None
                    if result.timed_out or result.exit_code == 0
                    else f"codex_exit_{result.exit_code}"
                ),
                error_message=result.stderr or None,
            )
            return self._codex_adapter(invocation.provider_profile_ref).build_result_from_output(
                invocation,
                output,
            )

        status = (
            WorkerResultStatus.FAILED
            if result.timed_out or result.exit_code != 0
            else WorkerResultStatus.COMPLETED
        )
        failure_kind = None
        if result.timed_out:
            failure_kind = ProviderFailureKind.TIMEOUT
        elif result.exit_code != 0:
            failure_kind = ProviderFailureKind.NON_ZERO_EXIT
        return ProviderInvocationResult(
            request_id=invocation.request_id,
            provider_id=invocation.provider_id,
            profile_id=invocation.profile_id,
            status=status,
            stdout_ref=result.stdout_log_path,
            stderr_ref=result.stderr_log_path,
            evidence_refs=[],
            failure_kind=failure_kind,
        )

    def record_execution_selection(
        self,
        *,
        lane_id: str,
        invocation: ProviderInvocation,
        used_override: bool,
    ) -> None:
        self._record_selection(
            lane_id=lane_id,
            invocation=invocation,
            peer_type="coordinator",
            selection_reason=(
                "Route execution through the configured provider profile."
                if used_override
                else "Route execution through the default provider profile."
            ),
        )

    def record_review_selection(
        self,
        *,
        lane_id: str,
        invocation: ProviderInvocation,
        used_override: bool,
    ) -> None:
        self._record_selection(
            lane_id=lane_id,
            invocation=invocation,
            peer_type="review",
            selection_reason=(
                "Route review through the configured provider profile."
                if used_override
                else "Route review through the default review provider profile."
            ),
        )

    def _build_invocation(
        self,
        *,
        lane_id: str,
        prompt: str,
        workspace: Path,
        timeout_seconds: int,
        provider_profile_ref: str,
        task_type: TaskCapability,
        risk_tier: RiskTier,
        request_suffix: str,
    ) -> ProviderInvocation:
        profile = self._registry.get(provider_profile_ref)
        if task_type not in profile.task_capabilities:
            raise ValueError(
                f"{provider_profile_ref} does not support task capability {task_type.value}"
            )
        return ProviderInvocation(
            request_id=f"{lane_id}:{request_suffix}",
            provider_id=profile.provider_id,
            profile_id=profile.profile_id,
            task_type=task_type,
            risk_tier=risk_tier,
            prompt=prompt,
            workspace=workspace,
            timeout_seconds=timeout_seconds,
        )

    def _build_invocation_for_decision(
        self,
        *,
        lane_id: str,
        prompt: str,
        workspace: Path,
        timeout_seconds: int,
        request_suffix: str,
        decision,
    ) -> ProviderInvocation:
        invocation = self._build_invocation(
            lane_id=lane_id,
            prompt=prompt,
            workspace=workspace,
            timeout_seconds=timeout_seconds,
            provider_profile_ref=decision.provider_profile_ref,
            task_type=decision.task_type,
            risk_tier=decision.lane_risk,
            request_suffix=request_suffix,
        )
        self._pending_selection_records[invocation.request_id] = decision.to_selection_record(
            lane_id=lane_id,
            selected_at=datetime.now(UTC),
        )
        return invocation

    def _record_selection(
        self,
        *,
        lane_id: str,
        invocation: ProviderInvocation,
        peer_type: str,
        selection_reason: str,
    ) -> None:
        if self._selection_record_store is None:
            return
        selected_record = self._pending_selection_records.pop(
            invocation.request_id,
            None,
        )
        if selected_record is not None:
            self._selection_record_store.append(selected_record)
            return
        self._selection_record_store.append(
            ProviderSelectionRecord(
                lane_id=lane_id,
                selected_at=datetime.now(UTC),
                provider_id=invocation.provider_id,
                profile_id=invocation.profile_id,
                task_type=invocation.task_type,
                lane_risk=invocation.risk_tier,
                selection_reason=selection_reason,
                peer_type=peer_type,
                source_authority="runner_provider_service",
            )
        )

    def _codex_adapter(
        self,
        provider_profile_ref: str,
        *,
        model_override: str | None = None,
    ) -> CodexProviderAdapter:
        profile = self._registry.get(provider_profile_ref)
        return CodexProviderAdapter(
            mcp_port=self._mcp_port,
            model=model_override or profile.model_id,
            profile_id=profile.profile_id,
        )

    def _opencode_adapter(self, provider_profile_ref: str) -> OpenCodeProviderAdapter:
        return OpenCodeProviderAdapter(self._registry.get(provider_profile_ref))
