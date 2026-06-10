from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from xmuse_core.agents.protocol import AgentOutput, StdoutMessage
from xmuse_core.providers.adapters.base import ProviderInvocation, ProviderInvocationResult
from xmuse_core.providers.adapters.codex import CodexProviderAdapter
from xmuse_core.providers.goal_contract import WorkerGoalContract
from xmuse_core.providers.models import ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.providers.registry import (
    DEFAULT_CODEX_GOD_MODEL_ID,
    normalize_codex_model_id,
)


@dataclass
class CodexLauncher:
    mcp_port: int = 8100
    model: str = DEFAULT_CODEX_GOD_MODEL_ID
    profile_id: ProviderProfileId = ProviderProfileId.DEFAULT
    supports_persistent_sessions: bool = field(init=False)
    _provider_adapter: CodexProviderAdapter = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.model = normalize_codex_model_id(
            self.model,
            profile_id=self.profile_id,
            allow_final_quality=self.profile_id is ProviderProfileId.FINAL_QUALITY,
        )
        self._provider_adapter = CodexProviderAdapter(
            mcp_port=self.mcp_port,
            model=self.model,
            profile_id=self.profile_id,
        )
        self.model = self._provider_adapter.profile.model_id
        self.supports_persistent_sessions = (
            self._provider_adapter.profile.supports_persistent_sessions
        )

    @property
    def provider_adapter(self) -> CodexProviderAdapter:
        return self._provider_adapter

    @property
    def provider_profile_ref(self) -> str:
        return self._provider_adapter.profile.ref

    def build_provider_invocation(
        self,
        *,
        request_id: str,
        prompt: str,
        worktree: Path,
        timeout_seconds: int,
        task_type: TaskCapability = TaskCapability.BOUNDED_CODE_WRITING,
        risk_tier: RiskTier = RiskTier.LOW,
        goal_contract: WorkerGoalContract | None = None,
    ) -> ProviderInvocation:
        return self._provider_adapter.build_invocation(
            request_id=request_id,
            task_type=task_type,
            risk_tier=risk_tier,
            prompt=prompt,
            workspace=worktree,
            timeout_seconds=timeout_seconds,
            goal_contract=goal_contract,
        )

    def build_provider_result_from_output(
        self,
        invocation: ProviderInvocation,
        output: AgentOutput,
    ) -> ProviderInvocationResult:
        return self._provider_adapter.build_result_from_output(invocation, output)

    def build_provider_result_from_message(
        self,
        invocation: ProviderInvocation,
        msg: StdoutMessage,
    ) -> ProviderInvocationResult | None:
        return self._provider_adapter.build_result_from_message(invocation, msg)

    def build_command(self, feature_id: str, worktree: Path) -> list[str]:
        return self._provider_adapter.build_command(worktree)

    def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
        return self._provider_adapter.build_persistent_command(role, worktree)

    def format_prompt(self, task: str, context: str) -> str:
        if context:
            return f"{context}\n\n---\n\n{task}"
        return task

    def build_env(self, feature_id: str) -> dict[str, str]:
        return self._provider_adapter.build_env(feature_id)

    def parse_output(self, msg: StdoutMessage) -> AgentOutput | None:
        if msg.type == "result":
            return AgentOutput.from_result(msg)
        if msg.type == "error":
            return AgentOutput.from_error(msg)
        return None
