from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.providers.adapters.base import ProviderInvocation, ProviderInvocationResult
from xmuse_core.structuring.feature_review_contracts import ProviderSessionBindingRecord

EXECUTE_PARENT_GOD_ROLE = "execute"
EXECUTE_WORKER_KIND_TEMPORARY_CHILD = "temporary_child_worker"
EXECUTE_DELIVERY_MODE_PERSISTENT = "persistent"
EXECUTE_DELIVERY_MODE_ONE_SHOT_FALLBACK = "one_shot_fallback"
EXECUTE_PEER_ID_FIELD = "execute_peer_id"
EXECUTE_PEER_REQUEST_ID_FIELD = "execute_peer_request_id"
EXECUTE_PEER_ROUTING_MODE_FIELD = "execute_peer_routing_mode"
EXECUTE_PEER_DELIVERY_MODE_FIELD = "execute_peer_delivery_mode"
EXECUTE_PEER_DEGRADED_REASON_FIELD = "execute_peer_degraded_reason"
EXECUTE_PEER_RESULT_ARTIFACT_FIELD = "execute_result"
EXECUTE_PEER_ROUTING_MODE_PREFERRED = "preferred"
EXECUTE_PEER_DELIVERY_MODE_CONFIGURED = "configured_peer"
EXECUTE_PEER_DELIVERY_MODE_ONE_SHOT_FALLBACK = "one_shot_fallback"
PERSISTENT_EXECUTE_DEGRADED_REASONS = frozenset(
    {
        "session_layer_unavailable",
        "missing_conversation_id",
        "missing_feature_identity",
        "ensure_failed",
        "worktree_mismatch",
        "send_failed",
        "receive_failed",
        "receive_timeout",
        "receive_error",
        "no_result_message",
        "request_id_missing",
        "request_id_mismatch",
    }
)

FeatureContextRef = str | dict[str, object]


@dataclass(frozen=True)
class ExecuteRequest:
    lane_id: str
    prompt: str
    worktree: Path
    capabilities: list[str]
    god_config: GodConfig
    mcp_url: str | None
    env_overrides: dict[str, str]
    parent_god_role: str = EXECUTE_PARENT_GOD_ROLE
    worker_kind: str = EXECUTE_WORKER_KIND_TEMPORARY_CHILD
    lane_request_id: str | None = None
    feature_scope_id: str | None = None
    feature_context_refs: list[FeatureContextRef] = field(default_factory=list)
    provider_invocation: ProviderInvocation | None = None
    provider_session_binding: ProviderSessionBindingRecord | None = None


@dataclass(frozen=True)
class ExecuteResponse:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool
    transport_error: str | None = None
    process_pid: int | None = None
    memoryos_session_id: str | None = None
    memoryos_context_attached: bool = False
    memoryos_ingested: bool = False
    memoryos_degraded_reason: str | None = None
    provider_result: ProviderInvocationResult | None = None


@dataclass(frozen=True)
class ReviewRequest:
    lane_id: str
    prompt: str
    worktree: Path
    evidence_refs: list[str]
    god_config: GodConfig
    mcp_url: str | None
    provider_invocation: ProviderInvocation | None = None
    provider_session_binding: ProviderSessionBindingRecord | None = None


@dataclass(frozen=True)
class ReviewVerdict:
    passed: bool
    verdict: str
    feedback: str
    raw_output: str
    exit_code: int = 0
    timed_out: bool = False
    transport_error: str | None = None
    provider_result: ProviderInvocationResult | None = None

    @property
    def stdout(self) -> str:
        return self.raw_output

    @property
    def stderr(self) -> str:
        return self.feedback


class Transport(Protocol):
    async def send_execute(self, req: ExecuteRequest) -> ExecuteResponse: ...

    async def send_review(self, req: ReviewRequest) -> ReviewVerdict: ...
