import asyncio
import importlib.util
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.platform.agent_spawner import GodConfig
from xmuse_core.platform.execution.executor import (
    _persistent_execute_request_degraded_reason,
    run_execution_god,
)
from xmuse_core.platform.messages import ExecuteRequest, ExecuteResponse, ReviewRequest
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.self_evolution.recovery import RecoveryConfig, RecoveryManager

PROJECT = Path(__file__).resolve().parents[2]
PLATFORM_RUNNER_PATH = PROJECT / "xmuse" / "platform_runner.py"


def _load_platform_runner():
    spec = importlib.util.spec_from_file_location(
        "xmuse_platform_runner_for_execute_tests",
        PLATFORM_RUNNER_PATH,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


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


@dataclass
class SentPersistentMessage:
    god_session_id: str
    message_type: str
    prompt: str
    context: str
    request_id: str | None = None


class FakePersistentExecuteSessionLayer:
    def __init__(
        self,
        *,
        message: StdoutMessage | None = None,
        receive_delay_s: float = 0,
        ensure_error: Exception | None = None,
        send_error: Exception | None = None,
        receive_error: Exception | None = None,
        echo_request_id: bool = True,
    ) -> None:
        self.message = message
        self.receive_delay_s = receive_delay_s
        self.ensure_error = ensure_error
        self.send_error = send_error
        self.receive_error = receive_error
        self.echo_request_id = echo_request_id
        self.ensure_calls: list[dict[str, Any]] = []
        self.sent_messages: list[SentPersistentMessage] = []
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
        if self.send_error is not None:
            raise self.send_error
        self.sent_messages.append(
            SentPersistentMessage(
                god_session_id=god_session_id,
                message_type=message_type,
                prompt=prompt,
                context=context,
                request_id=request_id,
            )
        )

    async def receive_message(self, god_session_id: str) -> StdoutMessage | None:
        if self.receive_delay_s:
            await asyncio.sleep(self.receive_delay_s)
        if self.receive_error is not None:
            raise self.receive_error
        if (
            self.echo_request_id
            and self.message is not None
            and self.message.request_id is None
            and self.sent_messages
        ):
            return replace(self.message, request_id=str(self.sent_messages[-1].request_id))
        return self.message

    async def abort_session(self, god_session_id: str) -> None:
        self.aborted.append(god_session_id)

    def persistent_model_for_runtime(self, runtime) -> str:
        return "gpt-5.5"


def _god() -> GodConfig:
    return GodConfig(
        name="execution-god",
        runtime="codex",
        timeout_s=60,
        skill_prompt_path="xmuse/god_prompts/execution_god.md",
    )


def _state_machine(tmp_path: Path, lanes: list[dict[str, Any]]) -> LaneStateMachine:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": lanes}), encoding="utf-8")
    return LaneStateMachine(lanes_path)


async def _run(
    tmp_path: Path,
    sm: LaneStateMachine,
    *,
    lane_id: str = "lane-a",
    layer: FakePersistentExecuteSessionLayer | None,
    receive_timeout_s: float = 1,
    fallback_response: ExecuteResponse | None = None,
) -> CapturingTransport:
    transport = CapturingTransport(response=fallback_response)
    recovery = RecoveryManager(RecoveryConfig(max_attempts=1), async_sleep=asyncio.sleep)
    await run_execution_god(
        lane_id=lane_id,
        god=_god(),
        prompt="Implement lane.",
        worktree=tmp_path / "lane-worktree",
        sm=sm,
        recovery=recovery,
        transport=transport,
        observer=lambda _event: None,
        on_executed=lambda _lane_id: asyncio.sleep(0),
        persistent_execute_enabled=True,
        persistent_session_layer=layer,
        xmuse_root=tmp_path,
        receive_timeout_s=receive_timeout_s,
    )
    return transport


@pytest.mark.asyncio
async def test_persistent_execute_routes_through_conversation_feature_session(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
                "feature_title": "Feature Alpha",
                "feature_goal": "Route execute work through a persistent GOD.",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            artifacts={
                "execute_result": {
                    "exit_code": 0,
                }
            },
        )
    )

    await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["execute_peer_id"] == "execute-peer-1"
    assert lane["execute_peer_request_id"] in layer.sent_messages[0].prompt
    assert lane["execute_peer_routing_mode"] == "preferred"
    assert lane["execute_peer_delivery_mode"] == "configured_peer"
    assert lane["execute_delivery_mode"] == "persistent"
    assert lane["persistent_execute_degraded"] is False
    assert lane["persistent_execute_identity"] == "conv-1:execute-peer-1"
    assert lane["execute_request_id"] in layer.sent_messages[0].prompt
    assert layer.ensure_calls[0]["conversation_id"] == "conv-1"
    assert layer.ensure_calls[0]["participant_id"] == "execute-peer-1"
    assert layer.ensure_calls[0]["role"] == "execute"
    assert str(layer.ensure_calls[0]["worktree"]) == str(tmp_path)
    assert layer.ensure_calls[0]["model"] == "gpt-5.4"
    assert str(layer.ensure_calls[0]["prompt_fingerprint"]).startswith("sha256:")
    assert layer.ensure_calls[0]["feature_scope_id"] == "feature-alpha"
    assert layer.sent_messages[0].message_type == "execute"
    assert layer.sent_messages[0].request_id == lane["execute_request_id"]
    assert "Delegate bounded implementation to a temporary_child_worker" not in (
        layer.sent_messages[0].prompt
    )
    assert "Title source: lane_metadata.feature_title" in layer.sent_messages[0].context


@pytest.mark.asyncio
async def test_persistent_execute_does_not_route_non_preferred_execute_peer(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "execute_peer_routing_mode": "required",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            artifacts={"execute_result": {"exit_code": 0}},
        )
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["execute_peer_id"] == "execute-peer-1"
    assert lane["execute_peer_routing_mode"] == "required"
    assert layer.ensure_calls == []
    assert layer.sent_messages == []
    assert len(transport.execute_requests) == 1
    assert "execute_peer_delivery_mode" not in lane
    assert "persistent_execute_identity" not in lane


@pytest.mark.asyncio
async def test_persistent_execute_accepts_codex_persistent_result_artifacts(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
                "feature_title": "Feature Alpha",
                "feature_goal": "Route execute work through a persistent GOD.",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            artifacts={
                "returncode": 0,
                "stdout": "child worker completed",
                "stderr": "",
                "message_type": "execute",
            },
        )
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["execute_delivery_mode"] == "persistent"
    assert lane["persistent_execute_degraded"] is False
    assert "persistent_execute_degraded_reason" not in lane
    assert transport.execute_requests == []


@pytest.mark.asyncio
async def test_persistent_execute_maps_codex_persistent_error_returncode(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
                "feature_title": "Feature Alpha",
                "feature_goal": "Route execute work through a persistent GOD.",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="error",
            artifacts={
                "returncode": 2,
                "stdout": "",
                "stderr": "child worker failed",
                "message_type": "execute",
            },
        )
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "non_zero_exit"
    assert lane["execute_delivery_mode"] == "persistent"
    assert lane["persistent_execute_degraded"] is False
    assert "persistent_execute_degraded_reason" not in lane
    assert transport.execute_requests == []


@pytest.mark.asyncio
async def test_persistent_execute_missing_identity_records_degraded_and_falls_back(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "execute_peer_id": "execute-peer-1",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(type="result", artifacts={"execute_result": {"exit_code": 0}})
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["execute_delivery_mode"] == "one_shot_fallback"
    assert lane["execute_peer_delivery_mode"] == "one_shot_fallback"
    assert lane["execute_peer_degraded_reason"] == "missing_conversation_id"
    assert lane["persistent_execute_degraded"] is True
    assert lane["persistent_execute_degraded_reason"] == "missing_conversation_id"
    assert len(transport.execute_requests) == 1
    assert layer.ensure_calls == []


@pytest.mark.asyncio
async def test_persistent_execute_send_failure_records_reason_and_falls_back(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(type="result", artifacts={"execute_result": {"exit_code": 0}}),
        send_error=RuntimeError("send failed"),
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["persistent_execute_degraded_reason"] == "send_failed"
    assert len(transport.execute_requests) == 1


@pytest.mark.asyncio
async def test_persistent_execute_receive_timeout_records_reason_and_falls_back(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(type="result", artifacts={"execute_result": {"exit_code": 0}}),
        receive_delay_s=0.1,
    )

    transport = await _run(tmp_path, sm, layer=layer, receive_timeout_s=0.01)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["persistent_execute_degraded_reason"] == "receive_timeout"
    assert layer.aborted == ["god-execute-1"]
    assert len(transport.execute_requests) == 1


@pytest.mark.asyncio
async def test_persistent_execute_missing_request_id_records_reason_and_falls_back(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            artifacts={"execute_result": {"exit_code": 0}},
        ),
        echo_request_id=False,
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["execute_delivery_mode"] == "one_shot_fallback"
    assert lane["persistent_execute_degraded_reason"] == "request_id_missing"
    assert lane["persistent_execute_degraded_source"] == "coordinator_session_delivery"
    assert layer.aborted == ["god-execute-1"]
    assert len(transport.execute_requests) == 1


@pytest.mark.asyncio
async def test_persistent_execute_missing_top_level_request_id_ignores_stale_success_payload(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            artifacts={
                "execute_result": {
                    "exit_code": 0,
                    "execute_peer_request_id": "execute-peer-execute-peer-1-lane-a",
                }
            },
        ),
        echo_request_id=False,
    )

    transport = await _run(
        tmp_path,
        sm,
        layer=layer,
        fallback_response=ExecuteResponse(
            exit_code=2,
            stdout="",
            stderr="focused pytest failed",
            timed_out=False,
        ),
    )

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "non_zero_exit"
    assert lane["execute_delivery_mode"] == "one_shot_fallback"
    assert lane["persistent_execute_degraded"] is True
    assert lane["persistent_execute_degraded_reason"] == "request_id_missing"
    assert lane["persistent_execute_degraded_source"] == "coordinator_session_delivery"
    assert lane["execute_failure_source"] == "worker_test_gate"
    assert layer.aborted == ["god-execute-1"]
    assert len(transport.execute_requests) == 1


@pytest.mark.asyncio
async def test_persistent_execute_mismatched_request_id_records_reason_and_falls_back(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="wrong",
            artifacts={"execute_result": {"exit_code": 0}},
        )
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert lane["execute_delivery_mode"] == "one_shot_fallback"
    assert lane["persistent_execute_degraded_reason"] == "request_id_mismatch"
    assert lane["persistent_execute_degraded_source"] == "coordinator_session_delivery"
    assert layer.aborted == ["god-execute-1"]
    assert len(transport.execute_requests) == 1


@pytest.mark.asyncio
async def test_persistent_execute_mismatched_top_level_request_id_ignores_stale_success_payload(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            request_id="execute-peer-execute-peer-1-stale-lane",
            artifacts={
                "execute_result": {
                    "exit_code": 0,
                    "execute_peer_request_id": "execute-peer-execute-peer-1-lane-a",
                }
            },
        )
    )

    transport = await _run(
        tmp_path,
        sm,
        layer=layer,
        fallback_response=ExecuteResponse(
            exit_code=2,
            stdout="",
            stderr="focused pytest failed",
            timed_out=False,
        ),
    )

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "non_zero_exit"
    assert lane["execute_delivery_mode"] == "one_shot_fallback"
    assert lane["persistent_execute_degraded"] is True
    assert lane["persistent_execute_degraded_reason"] == "request_id_mismatch"
    assert lane["persistent_execute_degraded_source"] == "coordinator_session_delivery"
    assert lane["execute_failure_source"] == "worker_test_gate"
    assert layer.aborted == ["god-execute-1"]
    assert len(transport.execute_requests) == 1


@pytest.mark.asyncio
async def test_persistent_execute_same_identity_is_single_flight(tmp_path: Path) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane A.",
                "worktree": str(tmp_path / "lane-a-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            },
            {
                "feature_id": "lane-b",
                "status": "dispatched",
                "prompt": "Implement lane B.",
                "worktree": str(tmp_path / "lane-b-worktree"),
                "conversation_id": "conv-1",
                "execute_peer_id": "execute-peer-1",
                "feature_plan_feature_id": "feature-alpha",
            },
        ],
    )
    in_flight = 0
    max_in_flight = 0

    class BlockingLayer(FakePersistentExecuteSessionLayer):
        async def send_message(
            self,
            god_session_id: str,
            message_type: str,
            prompt: str,
            context: str,
            request_id: str | None = None,
        ) -> None:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.02)
            await super().send_message(
                god_session_id,
                message_type,
                prompt,
                context,
                request_id=request_id,
            )
            in_flight -= 1

    layer = BlockingLayer(
        message=StdoutMessage(type="result", artifacts={"execute_result": {"exit_code": 0}})
    )

    await asyncio.gather(
        _run(tmp_path, sm, lane_id="lane-a", layer=layer),
        _run(tmp_path, sm, lane_id="lane-b", layer=layer),
    )

    assert max_in_flight == 1
    assert sm.get_lane("lane-a")["status"] == "executed"
    assert sm.get_lane("lane-b")["status"] == "executed"
    assert (
        sm.get_lane("lane-a")["persistent_execute_identity"]
        == sm.get_lane("lane-b")["persistent_execute_identity"]
    )


@pytest.mark.asyncio
async def test_persistent_execute_enabled_does_not_route_without_execute_peer_id(
    tmp_path: Path,
) -> None:
    sm = _state_machine(
        tmp_path,
        [
            {
                "feature_id": "lane-a",
                "status": "dispatched",
                "prompt": "Implement lane.",
                "worktree": str(tmp_path / "lane-worktree"),
                "conversation_id": "conv-1",
                "feature_plan_feature_id": "feature-alpha",
            }
        ],
    )
    layer = FakePersistentExecuteSessionLayer(
        message=StdoutMessage(
            type="result",
            artifacts={"execute_result": {"exit_code": 0}},
        )
    )

    transport = await _run(tmp_path, sm, layer=layer)

    lane = sm.get_lane("lane-a")
    assert lane["status"] == "executed"
    assert layer.ensure_calls == []
    assert len(transport.execute_requests) == 1
    assert "execute_peer_id" not in lane
    assert "execute_peer_request_id" not in lane
    assert "execute_peer_delivery_mode" not in lane
    assert "persistent_execute_identity" not in lane


@pytest.mark.parametrize(
    ("message", "expected_reason"),
    [
        (StdoutMessage(type="result"), "request_id_missing"),
        (StdoutMessage(type="result", request_id="other"), "request_id_mismatch"),
        (StdoutMessage(type="result", request_id="execute-peer-1"), None),
    ],
)
def test_persistent_execute_result_request_id_contract_rejects_uncorrelated_results(
    message: StdoutMessage,
    expected_reason: str | None,
) -> None:
    assert (
        _persistent_execute_request_degraded_reason(
            message,
            expected_request_id="execute-peer-1",
        )
        == expected_reason
    )


@pytest.mark.asyncio
async def test_orchestrator_wires_persistent_execute_session_layer_when_enabled(
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
                        "worktree": str(tmp_path / "lane-worktree"),
                        "conversation_id": "conv-1",
                        "feature_plan_feature_id": "feature-alpha",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text(
        "exec",
        encoding="utf-8",
    )
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text(
        "review",
        encoding="utf-8",
    )
    layer = object()
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        persistent_execute_enabled=True,
        persistent_execute_session_layer=layer,
    )

    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        new_callable=AsyncMock,
    ) as run_execution:
        await orch._run_execution_god("lane-a")

    assert run_execution.await_args.kwargs["persistent_execute_enabled"] is True
    assert run_execution.await_args.kwargs["persistent_session_layer"] is layer
    assert run_execution.await_args.kwargs["xmuse_root"] == tmp_path


def test_platform_runner_parser_supports_persistent_execute_god_flag() -> None:
    platform_runner = _load_platform_runner()

    args = platform_runner.main_arg_parser().parse_args(["--persistent-execute-god"])

    assert args.persistent_execute_god is True


@pytest.mark.asyncio
async def test_runner_can_explicitly_enable_persistent_execute_god_with_capable_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    platform_runner = _load_platform_runner()
    captured: dict[str, Any] = {}

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    class FakeStateMachine:
        def get_lanes(self, status: str | None = None) -> list[dict[str, Any]]:
            return []

    class FakeOrchestrator:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            self._sm = FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    import xmuse_core.agents.launchers as launchers_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": PersistentLauncher()},
    )
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        persistent_execute_god_enabled=True,
    )

    assert captured["persistent_execute_enabled"] is True
    assert captured["persistent_execute_session_layer"] is not None
    assert captured["review_god_session_layer"] is None


@pytest.mark.asyncio
async def test_runner_rejects_persistent_execute_god_without_capable_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    platform_runner = _load_platform_runner()

    class UnsupportedLauncher:
        supports_persistent_sessions = False

    class FakeOrchestrator:
        def __init__(self, **kwargs: Any) -> None:
            raise AssertionError("runner should reject before constructing orchestrator")

    import xmuse_core.agents.launchers as launchers_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": UnsupportedLauncher()},
    )
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    with pytest.raises(RuntimeError, match="requires a launcher"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=0,
            max_concurrent=1,
            persistent_execute_god_enabled=True,
        )
