import asyncio
import json
from pathlib import Path

import pytest

from xmuse_core.agents.provider_session_binding_store import ProviderSessionBindingStore
from xmuse_core.platform.agent_spawner import GodConfig, SpawnResult
from xmuse_core.platform.execution.executor import run_execution_god
from xmuse_core.platform.execution.transport import SubprocessTransport
from xmuse_core.platform.messages import (
    EXECUTE_DELIVERY_MODE_ONE_SHOT_FALLBACK,
    EXECUTE_DELIVERY_MODE_PERSISTENT,
    EXECUTE_PARENT_GOD_ROLE,
    EXECUTE_PEER_DEGRADED_REASON_FIELD,
    EXECUTE_PEER_DELIVERY_MODE_CONFIGURED,
    EXECUTE_PEER_DELIVERY_MODE_FIELD,
    EXECUTE_PEER_DELIVERY_MODE_ONE_SHOT_FALLBACK,
    EXECUTE_PEER_ID_FIELD,
    EXECUTE_PEER_REQUEST_ID_FIELD,
    EXECUTE_PEER_RESULT_ARTIFACT_FIELD,
    EXECUTE_PEER_ROUTING_MODE_FIELD,
    EXECUTE_PEER_ROUTING_MODE_PREFERRED,
    EXECUTE_WORKER_KIND_TEMPORARY_CHILD,
    PERSISTENT_EXECUTE_DEGRADED_REASONS,
    ExecuteRequest,
    ExecuteResponse,
    ReviewRequest,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.adapters.base import (
    ProviderFailureKind,
    ProviderInvocation,
    ProviderInvocationResult,
)
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderId, ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.self_evolution.recovery import RecoveryConfig, RecoveryManager
from xmuse_core.structuring.models import (
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
)


class CapturingTransport:
    def __init__(self, response: ExecuteResponse | None = None) -> None:
        self.execute_requests: list[ExecuteRequest] = []
        self.response = response

    async def send_execute(self, req: ExecuteRequest) -> ExecuteResponse:
        self.execute_requests.append(req)
        return self.response or ExecuteResponse(exit_code=0, stdout="", stderr="", timed_out=False)

    async def send_review(self, req: ReviewRequest):
        raise AssertionError("review transport should not be used")


class CapturingSpawner:
    def __init__(self) -> None:
        self.spawn_requests: list[dict[str, object]] = []

    async def spawn(self, **kwargs) -> SpawnResult:
        self.spawn_requests.append(kwargs)
        return SpawnResult(exit_code=0, stdout="", stderr="")


class CapturingBindingWriter:
    def __init__(self) -> None:
        self.bindings: list[ProviderSessionBindingRecord] = []

    def upsert_active(
        self,
        binding: ProviderSessionBindingRecord,
    ) -> ProviderSessionBindingRecord:
        self.bindings.append(binding)
        return binding


class FailingBindingWriter:
    def upsert_active(
        self,
        binding: ProviderSessionBindingRecord,
    ) -> ProviderSessionBindingRecord:
        raise ValueError("provider session binding replay conflict: psb-demo")


class FailingMarkFailedBindingWriter:
    def mark_failed(
        self,
        binding_id: str,
        *,
        status: ProviderSessionBindingStatus,
        reason: str,
        failed_at: str | None = None,
    ) -> ProviderSessionBindingRecord:
        raise OSError("provider session binding store unavailable")


@pytest.mark.asyncio
async def test_execution_request_identifies_temporary_child_worker(tmp_path: Path) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "status": "dispatched",
                        "prompt": "Implement lane.",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    transport = CapturingTransport()
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)

    await run_execution_god(
        lane_id="lane-a",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
        ),
        prompt="Prompt",
        worktree=tmp_path,
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=lambda _lane_id: asyncio.sleep(0),
    )

    req = transport.execute_requests[0]
    assert req.parent_god_role == "execute"
    assert req.worker_kind == "temporary_child_worker"
    assert sm.get_lane("lane-a")["worker_kind"] == "temporary_child_worker"
    assert sm.get_lane("lane-a")["parent_god"] == "execution-god"


def test_execute_request_carries_lane_request_and_feature_context_refs(
    tmp_path: Path,
) -> None:
    god = GodConfig(
        name="execution-god",
        runtime="codex",
        timeout_s=60,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )

    req = ExecuteRequest(
        lane_id="lane-01",
        lane_request_id="exec-req-01",
        feature_scope_id="persistent-execute-god-child-worker-orchestration",
        feature_context_refs=[
            "docs/superpowers/specs/2026-05-30-xmuse-persistent-execute-god-child-worker-preview.md",
            "xmuse/lane_graphs/xmuse-persistent-execute-god-child-worker-graph-set-v1.json",
        ],
        prompt="Implement lane.",
        worktree=tmp_path,
        capabilities=["code"],
        god_config=god,
        mcp_url=None,
        env_overrides={},
    )

    assert req.lane_request_id == "exec-req-01"
    assert (
        req.feature_scope_id
        == "persistent-execute-god-child-worker-orchestration"
    )
    assert req.feature_context_refs == [
        "docs/superpowers/specs/2026-05-30-xmuse-persistent-execute-god-child-worker-preview.md",
        "xmuse/lane_graphs/xmuse-persistent-execute-god-child-worker-graph-set-v1.json",
    ]


@pytest.mark.asyncio
async def test_execution_request_carries_explicit_provider_session_binding(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "status": "dispatched",
                        "prompt": "Implement lane.",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    transport = CapturingTransport()
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)
    invocation = _provider_invocation(tmp_path)
    binding = _provider_session_binding(worktree=str(tmp_path))

    await run_execution_god(
        lane_id="lane-a",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
        ),
        prompt="Prompt",
        worktree=tmp_path,
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=lambda _lane_id: asyncio.sleep(0),
        provider_invocation=invocation,
        provider_session_binding=binding,
    )

    req = transport.execute_requests[0]
    assert req.provider_invocation == invocation
    assert req.provider_session_binding == binding


@pytest.mark.asyncio
async def test_subprocess_transport_passes_provider_session_binding_to_spawner(
    tmp_path: Path,
) -> None:
    spawner = CapturingSpawner()
    transport = SubprocessTransport(spawner)
    invocation = _provider_invocation(tmp_path)
    binding = _provider_session_binding(worktree=str(tmp_path))

    response = await transport.send_execute(
        ExecuteRequest(
            lane_id="lane-a",
            prompt="Prompt",
            worktree=tmp_path,
            capabilities=["code"],
            god_config=GodConfig(
                name="execution-god",
                runtime="codex",
                timeout_s=60,
                skill_prompt_path="xmuse/god_prompts/execution_god.md",
            ),
            mcp_url=None,
            env_overrides={},
            provider_invocation=invocation,
            provider_session_binding=binding,
        )
    )

    assert response.exit_code == 0
    assert spawner.spawn_requests[0]["provider_invocation"] == invocation
    assert spawner.spawn_requests[0]["provider_session_binding"] == binding


@pytest.mark.asyncio
async def test_run_execution_god_upserts_provider_session_binding_from_successful_result(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "status": "dispatched",
                        "prompt": "Implement lane.",
                        "worktree": str(tmp_path),
                        "conversation_id": "conv-1",
                        "graph_id": "graph-feature-a",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    invocation = _provider_invocation(tmp_path)
    provider_result = _provider_result(invocation)
    transport = CapturingTransport(
        ExecuteResponse(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            provider_result=provider_result,
        )
    )
    writer = CapturingBindingWriter()
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)

    await run_execution_god(
        lane_id="lane-a",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
            model="gpt-5.4",
        ),
        prompt="Prompt",
        worktree=tmp_path,
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=lambda _lane_id: asyncio.sleep(0),
        provider_invocation=invocation,
        provider_session_binding_writer=writer,
        provider_session_binding_god_session_id="god-worker-demo",
        provider_session_binding_role="feature_worker",
        provider_session_binding_conversation_id="conv-1",
        provider_session_binding_feature_graph_id="graph-feature-a",
        provider_session_binding_prompt_fingerprint="sha256:prompt-demo",
    )

    assert len(writer.bindings) == 1
    binding = writer.bindings[0]
    assert binding.god_session_id == "god-worker-demo"
    assert binding.provider == "codex"
    assert binding.provider_session_id == provider_result.provider_session_id
    assert binding.feature_graph_id == "graph-feature-a"
    assert binding.conversation_id == "conv-1"
    assert binding.model == "gpt-5.4"
    assert binding.prompt_fingerprint == "sha256:prompt-demo"


@pytest.mark.asyncio
async def test_run_execution_god_records_provider_binding_upsert_failure_without_failing_lane(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "status": "dispatched",
                        "prompt": "Implement lane.",
                        "worktree": str(tmp_path),
                        "conversation_id": "conv-1",
                        "graph_id": "graph-feature-a",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    invocation = _provider_invocation(tmp_path)
    transport = CapturingTransport(
        ExecuteResponse(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            provider_result=_provider_result(invocation),
        )
    )
    executed_lane_ids: list[str] = []
    degradations: list[tuple[str, str, str | None]] = []
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)

    async def on_executed(lane_id: str) -> None:
        executed_lane_ids.append(lane_id)

    await run_execution_god(
        lane_id="lane-a",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
            model="gpt-5.4",
        ),
        prompt="Prompt",
        worktree=tmp_path,
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=on_executed,
        provider_invocation=invocation,
        provider_session_binding_writer=FailingBindingWriter(),
        provider_session_binding_god_session_id="god-worker-demo",
        provider_session_binding_role="feature_worker",
        provider_session_binding_conversation_id="conv-1",
        provider_session_binding_feature_graph_id="graph-feature-a",
        provider_session_binding_prompt_fingerprint="sha256:prompt-demo",
        record_provider_session_binding_degradation=(
            lambda binding_id, reason, failure: degradations.append(
                (binding_id, reason, failure)
            )
        ),
    )

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert executed_lane_ids == ["lane-a"]
    assert lane["provider_session_binding_degraded"] is True
    assert lane["provider_session_binding_degraded_reason"] == "upsert_failed"
    assert (
        lane["provider_session_binding_failure"]
        == "provider session binding replay conflict: psb-demo"
    )
    assert degradations == [
        (
            lane["provider_session_binding_id"],
            "upsert_failed",
            "provider session binding replay conflict: psb-demo",
        )
    ]


@pytest.mark.asyncio
async def test_run_execution_god_marks_resume_binding_stale_on_stale_provider_failure(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "status": "dispatched",
                        "prompt": "Implement lane.",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    invocation = _provider_invocation(tmp_path)
    binding_store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = binding_store.upsert_active(_provider_session_binding(worktree=str(tmp_path)))
    transport = CapturingTransport(
        ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="resume failed",
            timed_out=False,
            provider_result=ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=invocation.provider_id,
                profile_id=invocation.profile_id,
                status=WorkerResultStatus.FAILED,
                failure_kind=ProviderFailureKind.STALE_REQUEST,
                evidence_refs=[],
            ),
        )
    )
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)
    degradations: list[tuple[str, str, str | None]] = []

    await run_execution_god(
        lane_id="lane-a",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
            model="gpt-5.4",
        ),
        prompt="Prompt",
        worktree=tmp_path,
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=lambda _lane_id: asyncio.sleep(0),
        provider_invocation=invocation,
        provider_session_binding=binding,
        provider_session_binding_writer=binding_store,
    )

    stale = binding_store.get(binding.binding_id)
    assert stale.status is ProviderSessionBindingStatus.STALE
    assert stale.failure_reason == "stale_request"
    with pytest.raises(KeyError, match="active provider session binding not found"):
        binding_store.find_active(
            god_session_id="god-worker-demo",
            provider="codex",
            kind="exec",
        )


@pytest.mark.asyncio
async def test_run_execution_god_records_provider_binding_mark_failed_failure(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "status": "dispatched",
                        "prompt": "Implement lane.",
                        "worktree": str(tmp_path),
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    sm = LaneStateMachine(lanes_path)
    invocation = _provider_invocation(tmp_path)
    binding = _provider_session_binding(worktree=str(tmp_path))
    transport = CapturingTransport(
        ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="resume failed",
            timed_out=False,
            provider_result=ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=invocation.provider_id,
                profile_id=invocation.profile_id,
                status=WorkerResultStatus.FAILED,
                failure_kind=ProviderFailureKind.STALE_REQUEST,
                evidence_refs=[],
            ),
        )
    )
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)
    degradations: list[tuple[str, str, str | None]] = []

    await run_execution_god(
        lane_id="lane-a",
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
            model="gpt-5.4",
        ),
        prompt="Prompt",
        worktree=tmp_path,
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=lambda _lane_id: asyncio.sleep(0),
        provider_invocation=invocation,
        provider_session_binding=binding,
        provider_session_binding_writer=FailingMarkFailedBindingWriter(),
        record_provider_session_binding_degradation=(
            lambda binding_id, reason, failure: degradations.append(
                (binding_id, reason, failure)
            )
        ),
    )

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "stale_request"
    assert lane["provider_session_binding_degraded"] is True
    assert lane["provider_session_binding_degraded_reason"] == "mark_failed_failed"
    assert lane["provider_session_binding_id"] == binding.binding_id
    assert lane["provider_session_binding_failure"] == "provider session binding store unavailable"
    assert degradations == [
        (
            binding.binding_id,
            "mark_failed_failed",
            "provider session binding store unavailable",
        )
    ]


def test_persistent_execute_metadata_vocabulary_is_explicit() -> None:
    assert EXECUTE_PARENT_GOD_ROLE == "execute"
    assert EXECUTE_WORKER_KIND_TEMPORARY_CHILD == "temporary_child_worker"
    assert EXECUTE_DELIVERY_MODE_PERSISTENT == "persistent"
    assert EXECUTE_DELIVERY_MODE_ONE_SHOT_FALLBACK == "one_shot_fallback"
    assert EXECUTE_PEER_ID_FIELD == "execute_peer_id"
    assert EXECUTE_PEER_REQUEST_ID_FIELD == "execute_peer_request_id"
    assert EXECUTE_PEER_ROUTING_MODE_FIELD == "execute_peer_routing_mode"
    assert EXECUTE_PEER_DELIVERY_MODE_FIELD == "execute_peer_delivery_mode"
    assert EXECUTE_PEER_DEGRADED_REASON_FIELD == "execute_peer_degraded_reason"
    assert EXECUTE_PEER_RESULT_ARTIFACT_FIELD == "execute_result"
    assert EXECUTE_PEER_ROUTING_MODE_PREFERRED == "preferred"
    assert EXECUTE_PEER_DELIVERY_MODE_CONFIGURED == "configured_peer"
    assert (
        EXECUTE_PEER_DELIVERY_MODE_ONE_SHOT_FALLBACK
        == "one_shot_fallback"
    )
    assert {
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
    } <= PERSISTENT_EXECUTE_DEGRADED_REASONS


def _provider_invocation(tmp_path: Path) -> ProviderInvocation:
    return ProviderInvocation(
        request_id="lane-a:execute",
        provider_id=ProviderId.CODEX,
        profile_id=ProviderProfileId.DEFAULT,
        task_type=TaskCapability.LANE_COORDINATION,
        risk_tier=RiskTier.MEDIUM,
        prompt="Prompt",
        workspace=tmp_path,
        timeout_seconds=60,
    )


def _provider_session_binding(*, worktree: str) -> ProviderSessionBindingRecord:
    return ProviderSessionBindingRecord(
        binding_id="psb-codex-demo",
        god_session_id="god-worker-demo",
        provider="codex",
        provider_session_id="codex-session-11111111-2222-3333-4444-555555555555",
        session_kind="exec",
        status=ProviderSessionBindingStatus.ACTIVE,
        conversation_id="conv-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
        role="feature_worker",
        cwd="/repo",
        worktree=worktree,
        model="gpt-5.4",
        prompt_fingerprint="sha256:prompt-demo",
        created_at="2026-06-03T02:10:00Z",
        last_used_at="2026-06-03T02:11:00Z",
        last_verified_at="2026-06-03T02:11:30Z",
        resume_command_template="codex exec resume {provider_session_id}",
    )


def _provider_result(invocation: ProviderInvocation) -> ProviderInvocationResult:
    return ProviderInvocationResult(
        request_id=invocation.request_id,
        provider_id=invocation.provider_id,
        profile_id=invocation.profile_id,
        status=WorkerResultStatus.COMPLETED,
        provider_session_id="codex-session-11111111-2222-3333-4444-555555555555",
        evidence_refs=[],
    )
