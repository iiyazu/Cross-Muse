from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.registry import AgentRuntime
from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.execution import merger as execution_merger
from xmuse_core.platform.execution.executor import run_execution_god
from xmuse_core.platform.messages import ExecuteRequest, ExecuteResponse, ReviewRequest
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.adapters.fake import (
    FakeProviderHealthState,
    build_fake_provider_health_snapshot,
)
from xmuse_core.providers.models import TaskCapability
from xmuse_core.providers.registry import build_default_provider_registry
from xmuse_core.providers.selection_record import ProviderSelectionRecordStore
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.self_evolution.recovery import RecoveryConfig, RecoveryManager
from xmuse_core.structuring.models import (
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
)
from xmuse_core.structuring.projection import project_feature_graph_set_ready_lanes
from xmuse_core.structuring.ready_set import build_graph_ready_set

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "platform_runner.py"


def _load_platform_runner():
    spec = importlib.util.spec_from_file_location("xmuse_platform_runner", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


platform_runner = _load_platform_runner()


class CapturingTransport:
    def __init__(self, response: ExecuteResponse | None = None) -> None:
        self.execute_requests: list[ExecuteRequest] = []
        self.response = response or ExecuteResponse(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
        )

    async def send_execute(self, req: ExecuteRequest) -> ExecuteResponse:
        self.execute_requests.append(req)
        return self.response

    async def send_review(self, req: ReviewRequest):
        raise AssertionError("review transport should not be used")


class FakePersistentExecuteSessionLayer:
    def __init__(
        self,
        *,
        message: StdoutMessage | None = None,
        receive_delay_s: float = 0,
        ensure_error: Exception | None = None,
        send_error: Exception | None = None,
        receive_error: Exception | None = None,
    ) -> None:
        self.message = message
        self.receive_delay_s = receive_delay_s
        self.ensure_error = ensure_error
        self.send_error = send_error
        self.receive_error = receive_error
        self.ensure_calls: list[dict[str, Any]] = []
        self.aborted: list[str] = []

    async def ensure_conversation_session(self, **kwargs: Any) -> GodSessionRecord:
        self.ensure_calls.append(kwargs)
        if self.ensure_error is not None:
            raise self.ensure_error
        return GodSessionRecord(
            god_session_id="god-execute-1",
            role=str(kwargs["role"]),
            agent_name=kwargs["agent"].name,
            runtime=kwargs["agent"].runtime.value,
            session_address="@execute",
            session_inbox_id="inbox-execute",
            conversation_id=str(kwargs["conversation_id"]),
            participant_id=str(kwargs["participant_id"]),
        )

    async def send_message(
        self,
        god_session_id: str,
        message_type: str,
        prompt: str,
        context: str,
        request_id: str | None = None,
    ) -> None:
        del god_session_id, message_type, prompt, context, request_id
        if self.send_error is not None:
            raise self.send_error

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None:
        del god_session_id
        if self.receive_delay_s:
            await asyncio.sleep(self.receive_delay_s)
        if self.receive_error is not None:
            raise self.receive_error
        return self.message

    async def abort_session(self, god_session_id: str) -> None:
        self.aborted.append(god_session_id)

    def persistent_model_for_runtime(self, runtime) -> str:
        del runtime
        return "gpt-5.5"


class FakePersistentReviewSessionLayer:
    def __init__(
        self,
        *,
        message: StdoutMessage | None = None,
        receive_delay_s: float = 0,
        ensure_error: Exception | None = None,
        send_error: Exception | None = None,
        receive_error: Exception | None = None,
    ) -> None:
        self.message = message
        self.receive_delay_s = receive_delay_s
        self.ensure_error = ensure_error
        self.send_error = send_error
        self.receive_error = receive_error
        self.ensure_calls: list[dict[str, Any]] = []
        self.aborted: list[str] = []

    async def ensure_conversation_session(self, **kwargs: Any) -> GodSessionRecord:
        self.ensure_calls.append(kwargs)
        if self.ensure_error is not None:
            raise self.ensure_error
        return GodSessionRecord(
            god_session_id="god-review-1",
            role=str(kwargs["role"]),
            agent_name=kwargs["agent"].name,
            runtime=kwargs["agent"].runtime.value,
            session_address="@review",
            session_inbox_id="inbox-review",
            conversation_id=str(kwargs["conversation_id"]),
            participant_id=str(kwargs["participant_id"]),
        )

    async def send_message(
        self,
        god_session_id: str,
        message_type: str,
        prompt: str,
        context: str,
        request_id: str | None = None,
    ) -> None:
        del god_session_id, message_type, prompt, context, request_id
        if self.send_error is not None:
            raise self.send_error

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None:
        del god_session_id
        if self.receive_delay_s:
            await asyncio.sleep(self.receive_delay_s)
        if self.receive_error is not None:
            raise self.receive_error
        return self.message

    async def abort_session(self, god_session_id: str) -> None:
        self.aborted.append(god_session_id)

    def persistent_model_for_runtime(self, runtime) -> str:
        del runtime
        return "gpt-5.5"


def _write_orchestrator_support_files(tmp_path: Path) -> None:
    (tmp_path / "error_knowledge.json").write_text(
        json.dumps({"entries": []}),
        encoding="utf-8",
    )
    prompts_dir = tmp_path / "xmuse" / "god_prompts"
    prompts_dir.mkdir(parents=True)
    (prompts_dir / "execution_god.md").write_text("exec", encoding="utf-8")
    (prompts_dir / "review_god.md").write_text("review", encoding="utf-8")


def _state_machine(tmp_path: Path, lanes: list[dict[str, Any]]) -> LaneStateMachine:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    return LaneStateMachine(lanes_path)


def _low_risk_actor_lane(
    *,
    tmp_path: Path,
    lane_id: str,
    feature_group: str,
) -> dict[str, Any]:
    return {
        "feature_id": lane_id,
        "status": "pending",
        "prompt": f"Implement {feature_group} lane.",
        "worktree": str(tmp_path),
        "risk": "low",
        "task_type": "bounded_code_writing",
        "bounded_context": True,
        "well_specified": True,
        "feature_group": feature_group,
    }


async def _run_actor_lane(
    tmp_path: Path,
    sm: LaneStateMachine,
    *,
    lane_id: str,
    layer: FakePersistentExecuteSessionLayer,
    fallback_response: ExecuteResponse | None = None,
) -> CapturingTransport:
    transport = CapturingTransport(response=fallback_response)
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)
    await run_execution_god(
        lane_id=lane_id,
        god=GodConfig(
            name="execution-god",
            runtime="codex",
            timeout_s=60,
            skill_prompt_path="xmuse/god_prompts/execution_god.md",
        ),
        prompt="Implement the bounded actor lane.",
        worktree=tmp_path / "lane-worktree",
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=lambda _lane_id: asyncio.sleep(0),
        persistent_execute_enabled=True,
        persistent_session_layer=layer,
        xmuse_root=tmp_path,
    )
    return transport


async def _run_review_lane(
    tmp_path: Path,
    sm: LaneStateMachine,
    *,
    lane_id: str,
    layer: FakePersistentReviewSessionLayer,
) -> PlatformOrchestrator:
    _write_orchestrator_support_files(tmp_path)
    orch = PlatformOrchestrator(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path,
        mcp_port=9999,
        review_god_session_layer=layer,
        require_final_action_approval=True,
    )

    async def should_not_review_transport(req):
        del req
        raise AssertionError("native review fallback should not be used")

    with patch.object(orch._transport, "send_review", new=should_not_review_transport):
        await orch._run_review_god(lane_id)
    return orch


def test_actor_session_groups_align_with_graph_set_ready_set(tmp_path: Path) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    graph_set = FeatureGraphSet(
        id="graph-set-ray-scheduling",
        feature_plan=FeaturePlan(
            id="plan-ray-scheduling",
            conversation_id="conv-ray",
            resolution_id="res-ray",
            version=1,
            features=[
                FeaturePlanFeature(
                    feature_id="feature-a",
                    title="Feature A",
                    goal="Schedule actor session A.",
                    acceptance_criteria=["Actor session A root lane is ready."],
                    graph_id="graph-a",
                ),
                FeaturePlanFeature(
                    feature_id="feature-b",
                    title="Feature B",
                    goal="Schedule actor session B.",
                    acceptance_criteria=["Actor session B root lane is ready."],
                    graph_id="graph-b",
                ),
            ],
        ),
        graphs=[
            LaneGraph(
                id="graph-a",
                conversation_id="conv-ray",
                resolution_id="res-ray",
                version=1,
                lanes=[
                    LaneNode(
                        feature_id="root-a",
                        prompt="Dispatch actor session A root lane.",
                        feature_group="actor/session-a",
                    ),
                    LaneNode(
                        feature_id="followup-a",
                        prompt="Dispatch actor session A dependent lane.",
                        depends_on=["root-a"],
                        feature_group="actor/session-a",
                    ),
                ],
            ),
            LaneGraph(
                id="graph-b",
                conversation_id="conv-ray",
                resolution_id="res-ray",
                version=1,
                lanes=[
                    LaneNode(
                        feature_id="root-b",
                        prompt="Dispatch actor session B root lane.",
                        feature_group="actor/session-b",
                    )
                ],
            ),
        ],
    )

    projected = project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids=set(),
    )
    ready = build_graph_ready_set(
        json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"],
        graph_id=None,
        resolution_id="res-ray",
    )

    assert [lane["lane_local_id"] for lane in projected] == ["root-a", "root-b"]
    assert [lane["feature_id"] for lane in ready] == [
        lane["feature_id"] for lane in projected
    ]
    assert {lane["feature_group"] for lane in ready} == {
        "actor/session-a",
        "actor/session-b",
    }
    assert all(lane["graph_set_id"] == "graph-set-ray-scheduling" for lane in ready)


@pytest.mark.asyncio
async def test_actor_session_groups_share_provider_budget_backpressure(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    _low_risk_actor_lane(
                        tmp_path=tmp_path,
                        lane_id="lane-session-a",
                        feature_group="actor/session-a",
                    ),
                    _low_risk_actor_lane(
                        tmp_path=tmp_path,
                        lane_id="lane-session-b",
                        feature_group="actor/session-b",
                    ),
                ]
            }
        ),
        encoding="utf-8",
    )
    _write_orchestrator_support_files(tmp_path)
    registry = build_default_provider_registry()
    selection_store = ProviderSelectionRecordStore.from_xmuse_root(tmp_path)
    provider_service = RunnerProviderService(
        selection_record_store=selection_store,
        health_by_profile={
            "opencode.deepseek_flash_worker": build_fake_provider_health_snapshot(
                registry.get("opencode.deepseek_flash_worker"),
                state=FakeProviderHealthState.READY,
            )
        },
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        provider_service=provider_service,
    )
    invocations: list[tuple[str, Any]] = []
    shared_health_states = iter(
        (
            FakeProviderHealthState.READY,
            FakeProviderHealthState.TIMEOUT,
        )
    )

    async def fake_send_execute(req):
        invocations.append((req.lane_id, req.provider_invocation))
        return ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="failed",
            timed_out=False,
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        for lane_id in ("lane-session-a", "lane-session-b"):
            health_state = next(shared_health_states)
            provider_service._health_by_profile["opencode.deepseek_flash_worker"] = (
                build_fake_provider_health_snapshot(
                    registry.get("opencode.deepseek_flash_worker"),
                    state=health_state,
                    diagnostic_summary=(
                        "shared actor provider budget available"
                        if health_state is FakeProviderHealthState.READY
                        else "shared actor provider budget exhausted"
                    ),
                )
            )
            await orch.dispatch_lane(lane_id)

    assert [lane_id for lane_id, _ in invocations] == [
        "lane-session-a",
        "lane-session-b",
    ]
    assert [invocation.provider_profile_ref for _, invocation in invocations] == [
        "opencode.deepseek_flash_worker",
        "codex.worker",
    ]
    assert all(
        invocation.task_type is TaskCapability.BOUNDED_CODE_WRITING
        for _, invocation in invocations
    )
    assert orch._sm.get_lane("lane-session-a")["provider_profile_ref"] == (
        "opencode.deepseek_flash_worker"
    )
    assert orch._sm.get_lane("lane-session-b")["provider_profile_ref"] == "codex.worker"

    session_a_records = selection_store.list_records(lane_id="lane-session-a")
    session_b_records = selection_store.list_records(lane_id="lane-session-b")
    assert len(session_a_records) == 1
    assert len(session_b_records) == 1
    assert session_a_records[0].provider_profile_ref == "opencode.deepseek_flash_worker"
    assert session_a_records[0].fallback_cause is None
    assert session_b_records[0].provider_profile_ref == "codex.worker"
    assert session_b_records[0].fallback_cause == "timeout"
    assert session_b_records[0].health_failure_kind == "timeout"
    assert "low-cost worker profile" in session_a_records[0].selection_reason
    assert "Fallback to the codex worker profile" in session_b_records[0].selection_reason


@pytest.mark.asyncio
async def test_ray_session_layer_executes_actor_lane_before_native_fallback(
    tmp_path: Path,
) -> None:
    from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

    class _FakeRayActor:
        def __init__(self) -> None:
            self.info = {"alive": False}
            self.sent: list[tuple[str, dict[str, object]]] = []
            self.shutdown_called = False
            self.received = [
                StdoutMessage(
                    type="result",
                    request_id="execute-peer-actor-session-a-lane-actor-session-a",
                    artifacts={"execute_result": {"exit_code": 0}},
                )
            ]

        async def ensure_alive(self) -> bool:
            self.info["alive"] = True
            return True

        async def get_info(self) -> dict[str, object]:
            return self.info

        async def send_typed(self, msg_type: str, **payload: object) -> None:
            self.sent.append((msg_type, payload))

        async def receive(self):
            if self.received:
                return self.received.pop(0)
            return None

        async def shutdown(self) -> None:
            self.shutdown_called = True
            self.info["alive"] = False

    actors: list[_FakeRayActor] = []

    def actor_factory(**_kwargs):
        actor = _FakeRayActor()
        actors.append(actor)
        return actor

    class Launcher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["fake-cli", role, str(worktree)]

        def persistent_model(self) -> str:
            return "gpt-5.4"

    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-actor-session-a",
                "status": "dispatched",
                "prompt": "Implement actor session A lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-ray",
                "execute_peer_id": "actor-session-a",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: Launcher()},
        actor_factory=actor_factory,
    )

    transport = await _run_actor_lane(
        tmp_path,
        sm,
        lane_id="lane-actor-session-a",
        layer=layer,
    )

    lane = sm.get_lane("lane-actor-session-a")
    assert lane["status"] == "executed"
    assert lane["execute_delivery_mode"] == "persistent"
    assert lane["execute_peer_delivery_mode"] == "configured_peer"
    assert lane["persistent_execute_degraded"] is False
    assert len(actors) == 1
    assert transport.execute_requests == []
    assert actors[0].sent[0][0] == "execute"


@pytest.mark.asyncio
async def test_runner_uses_ray_execution_session_layer_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self._sm = type(
                "_EmptyStateMachine",
                (),
                {"get_lanes": lambda self, status=None: []},
            )()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module

    async def fake_prewarm(self) -> None:
        captured["prewarmed"] = type(self).__name__

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.delenv("XMUSE_EXECUTE_GOD_BACKEND", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        ray_session_layer_module.RayGodSessionLayer,
        "prewarm",
        fake_prewarm,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        persistent_execute_god_enabled=True,
    )

    assert captured["persistent_execute_enabled"] is True
    assert (
        type(captured["persistent_execute_session_layer"]).__name__
        == "RayGodSessionLayer"
    )
    assert captured["prewarmed"] == "RayGodSessionLayer"


@pytest.mark.asyncio
async def test_runner_uses_ray_review_session_layer_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self._sm = type(
                "_EmptyStateMachine",
                (),
                {"get_lanes": lambda self, status=None: []},
            )()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module

    async def fake_prewarm(self) -> None:
        captured["prewarmed"] = type(self).__name__

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.delenv("XMUSE_REVIEW_GOD_BACKEND", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        ray_session_layer_module.RayGodSessionLayer,
        "prewarm",
        fake_prewarm,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        persistent_review_god_enabled=True,
    )

    assert type(captured["review_god_session_layer"]).__name__ == "RayGodSessionLayer"
    assert captured["prewarmed"] == "RayGodSessionLayer"


@pytest.mark.asyncio
async def test_runner_rejects_native_review_fallback_when_ray_unavailable_without_degraded_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self._sm = type(
                "_EmptyStateMachine",
                (),
                {"get_lanes": lambda self, status=None: []},
            )()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setenv("XMUSE_REVIEW_GOD_BACKEND", "ray")
    monkeypatch.setattr(
        ray_session_layer_module,
        "RayGodSessionLayer",
        type(
            "BrokenRayLayer",
            (),
            {
                "__init__": lambda self, *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("ray unavailable")
                )
            },
        ),
    )

    with pytest.raises(RuntimeError, match="native fallback is disabled"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=0,
            max_concurrent=1,
            persistent_review_god_enabled=True,
        )


@pytest.mark.asyncio
async def test_runner_can_use_native_review_fallback_in_explicit_degraded_local_mode(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self._sm = type(
                "_EmptyStateMachine",
                (),
                {"get_lanes": lambda self, status=None: []},
            )()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.agents.ray_session_layer as ray_session_layer_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setenv("XMUSE_REVIEW_GOD_BACKEND", "ray")
    monkeypatch.setenv("XMUSE_DEGRADED_LOCAL_GOD_MODE", "1")
    monkeypatch.setattr(
        ray_session_layer_module,
        "RayGodSessionLayer",
        type(
            "BrokenRayLayer",
            (),
            {
                "__init__": lambda self, *args, **kwargs: (_ for _ in ()).throw(
                    RuntimeError("ray unavailable")
                )
            },
        ),
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        persistent_review_god_enabled=True,
    )

    assert type(captured["review_god_session_layer"]).__name__ == "GodSessionLayer"


@pytest.mark.asyncio
async def test_ray_session_layer_reviews_lane_before_native_fallback(
    tmp_path: Path,
) -> None:
    from xmuse_core.agents.ray_session_layer import RayGodSessionLayer

    class _FakeRayActor:
        def __init__(self) -> None:
            self.info = {"alive": False}
            self.sent: list[tuple[str, dict[str, object]]] = []
            self.shutdown_called = False

        async def ensure_alive(self) -> bool:
            self.info["alive"] = True
            return True

        async def get_info(self) -> dict[str, object]:
            return self.info

        async def send_typed(self, msg_type: str, **payload: object) -> None:
            self.sent.append((msg_type, payload))

        async def receive(self):
            request_id = self.sent[-1][1]["request_id"]
            return StdoutMessage(
                type="result",
                request_id=str(request_id),
                artifacts={
                    "review_verdict": {
                        "decision": "merge",
                        "summary": "No findings.",
                    }
                },
            )

        async def shutdown(self) -> None:
            self.shutdown_called = True
            self.info["alive"] = False

    actors: list[_FakeRayActor] = []

    def actor_factory(**_kwargs):
        actor = _FakeRayActor()
        actors.append(actor)
        return actor

    class Launcher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["fake-cli", role, str(worktree)]

        def persistent_model(self) -> str:
            return "gpt-5.4"

    lanes = [
        {
            "feature_id": "lane-review-a",
            "status": "gated",
            "prompt": "Review the lane.",
            "worktree": str(tmp_path / "lane-worktree"),
            "conversation_id": "conv-ray",
            "feature_plan_feature_id": "feature-alpha",
            "gate_passed": True,
        }
    ]
    sm = _state_machine(tmp_path, lanes)
    layer = RayGodSessionLayer(
        registry_path=tmp_path / "god_sessions.json",
        db_path=tmp_path / "chat.db",
        launchers={AgentRuntime.CODEX: Launcher()},
        actor_factory=actor_factory,
    )

    orch = await _run_review_lane(
        tmp_path,
        sm,
        lane_id="lane-review-a",
        layer=layer,
    )

    lane = orch._sm.get_lane("lane-review-a")
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_delivery_mode"] == "persistent"
    assert lane["persistent_review_degraded"] is False
    assert "persistent_review_identity" in lane
    assert len(actors) == 1
    assert actors[0].sent[0][0] == "review"


@pytest.mark.asyncio
async def test_actor_crash_falls_back_to_native_execution_without_losing_writer_lease(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-actor-session-a",
                "status": "dispatched",
                "prompt": "Implement actor session A lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-ray",
                "execute_peer_id": "actor-session-a",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    lanes_path = tmp_path / "feature_lanes.json"
    writer_lease = platform_runner._acquire_writer_lease(
        lanes_path,
        runner_id="runner-ray-fallback",
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            artifacts={"execute_result": {"exit_code": 0}},
        ),
        receive_error=RuntimeError("actor crashed"),
    )

    transport = await _run_actor_lane(
        tmp_path,
        sm,
        lane_id="lane-actor-session-a",
        layer=layer,
    )

    lane = sm.get_lane("lane-actor-session-a")
    assert lane["status"] == "executed"
    assert lane["execute_delivery_mode"] == "one_shot_fallback"
    assert lane["execute_peer_delivery_mode"] == "one_shot_fallback"
    assert lane["persistent_execute_degraded"] is True
    assert lane["persistent_execute_degraded_reason"] == "receive_failed"
    assert layer.aborted == ["god-execute-1"]
    assert len(transport.execute_requests) == 1
    assert transport.execute_requests[0].lane_id == "lane-actor-session-a"
    assert transport.execute_requests[0].worker_kind == "temporary_child_worker"

    persisted_lease = json.loads(
        platform_runner._writer_lease_path(lanes_path).read_text(encoding="utf-8")
    )
    assert persisted_lease["lease_id"] == writer_lease["lease_id"]
    assert persisted_lease["runner_id"] == "runner-ray-fallback"


def test_actor_crash_releases_merge_lock_without_dropping_writer_lease(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    monkeypatch.setattr(platform_runner.time, "time", lambda: 100.0)
    writer_lease = platform_runner._acquire_writer_lease(
        lanes_path,
        runner_id="runner-ray-fallback",
    )
    repo = tmp_path / "repo"
    repo.mkdir()
    metadata_path = execution_merger._merge_lock_metadata_path(
        repo,
        target_branch="main",
    )

    with pytest.raises(RuntimeError, match="actor crashed"):
        with execution_merger._merge_lock(
            repo,
            target_branch="main",
            owner_id="actor/session-a",
            now=100.0,
        ):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            assert metadata["owner_id"] == "actor/session-a"
            raise RuntimeError("actor crashed")

    persisted_lease = json.loads(
        platform_runner._writer_lease_path(lanes_path).read_text(encoding="utf-8")
    )
    assert persisted_lease["lease_id"] == writer_lease["lease_id"]
    assert persisted_lease["runner_id"] == "runner-ray-fallback"
    assert platform_runner._lease_is_active(persisted_lease, now=110.0)
    assert not metadata_path.exists()
