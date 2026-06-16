from __future__ import annotations

import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.feature_graph_claim_coordinator import (
    claim_next_ready_feature_graph_worker,
)
from xmuse_core.platform.feature_graph_worker_evidence_coordinator import (
    submit_feature_graph_worker_evidence,
)
from xmuse_core.platform.local_execution_candidate import (
    build_local_execution_candidate_lineage,
    build_validated_execution_candidate_boundary,
)
from xmuse_core.platform.run_health import build_process_inventory
from xmuse_core.platform.runner_recovery_proof import build_runner_recovery_proof
from xmuse_core.platform.runner_session import build_runner_session_lineage
from xmuse_core.platform.runner_supervisor import RunnerSupervisorConfig, runner_status
from xmuse_core.structuring.blueprint_execution.lane_recovery_artifacts import (
    lane_recovery_artifact_path,
)
from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphSet,
    FeaturePlan,
    FeaturePlanFeature,
    LaneGraph,
    LaneNode,
)
from xmuse_core.structuring.projection import project_feature_graph_set_ready_lanes

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "platform_runner.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("xmuse_platform_runner", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


platform_runner = _load_module()


class _FakeStateMachine:
    def __init__(self, lanes=None):
        self._lanes = lanes or []

    def get_lanes(self, status: str | None = None):
        if status is None:
            return list(self._lanes)
        return [lane for lane in self._lanes if lane.get("status") == status]

    def get_lane(self, lane_id: str):
        for lane in self._lanes:
            if lane.get("feature_id") == lane_id:
                return dict(lane)
        raise KeyError(lane_id)

    def update_metadata(self, lane_id: str, metadata: dict):
        for lane in self._lanes:
            if lane.get("feature_id") == lane_id:
                lane.update(metadata)
                return dict(lane)
        raise KeyError(lane_id)


class _FakeFeatureGraphStatus:
    graph_set_id = "graph-a-graph-set"
    feature_graph_id = "graph-a-feature-a"
    status_id = "fgs:graph-a:feature-a:reviewing"
    status = "reviewing"
    blueprint_proof_level = "contract_proof"
    active_lane_ids: list[str] = []
    completed_lane_ids = ["lane-local-1"]
    source_event_lineage: list[dict] = []


class _FakeFeatureGraphStatusStore:
    def get(self, *, graph_set_id: str, feature_graph_id: str):
        if (
            graph_set_id == _FakeFeatureGraphStatus.graph_set_id
            and feature_graph_id == _FakeFeatureGraphStatus.feature_graph_id
        ):
            return _FakeFeatureGraphStatus()
        raise KeyError(f"{graph_set_id}:{feature_graph_id}")


class _FakeRunningFeatureGraphStatus:
    graph_set_id = "graph-a-graph-set"
    feature_graph_id = "graph-a-feature-a"
    status_id = "fgs:graph-a:feature-a:running"
    status = "running"
    blueprint_proof_level = "contract_proof"
    active_lane_ids = ["lane-local-1"]
    completed_lane_ids: list[str] = []
    source_event_lineage: list[dict] = []


class _FakeRunningFeatureGraphStatusStore:
    def get(self, *, graph_set_id: str, feature_graph_id: str):
        if (
            graph_set_id == _FakeRunningFeatureGraphStatus.graph_set_id
            and feature_graph_id == _FakeRunningFeatureGraphStatus.feature_graph_id
        ):
            return _FakeRunningFeatureGraphStatus()
        raise KeyError(f"{graph_set_id}:{feature_graph_id}")


def test_runner_recovery_proof_without_block_remains_manual_gap(tmp_path: Path) -> None:
    artifact = build_runner_recovery_proof(
        run_id="run-no-block",
        runner_id="runner-test",
        lanes=[
            {
                "feature_id": "lane-ready",
                "status": "pending",
                "graph_id": "graph-a",
            }
        ],
        candidate_lanes=[
            {
                "feature_id": "lane-ready",
                "status": "pending",
                "graph_id": "graph-a",
            }
        ],
        runner_status={
            "health": {
                "recovery": {
                    "source_authority": "lane_recovery_artifact",
                    "proof_level": "contract_proof",
                    "counts": {
                        "blocked": 0,
                        "non_retry_decision": 0,
                        "invalid_artifact": 0,
                        "retry_allowed": 0,
                    },
                    "blocked_lanes": [],
                    "invalid_artifacts": [],
                }
            }
        },
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
    )

    assert artifact["status"] == "manual_gap"
    assert artifact["proof_level"] == "manual_gap"
    assert "no_durable_recovery_block_observed" in artifact["manual_gaps"]
    assert "overnight_safe_recovery" in artifact["forbidden_claims"]
    assert "end_to_end_execution_review_closure" in artifact["forbidden_claims"]
    assert "worker_output_is_review_truth" in artifact["forbidden_claims"]
    assert "ready_to_merge" in artifact["forbidden_claims"]
    assert "pr_merged" in artifact["forbidden_claims"]


@pytest.mark.asyncio
async def test_runner_does_not_require_final_action_approval_by_default(
    monkeypatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(
            self,
            *,
            lanes_path: Path,
            xmuse_root: Path,
            mcp_port: int,
            require_final_action_approval: bool,
            god_runtime: str | None = None,
            runner_id: str | None = None,
            memoryos_client=None,
            review_god_session_layer=None,
        ) -> None:
            captured["lanes_path"] = lanes_path
            captured["xmuse_root"] = xmuse_root
            captured["mcp_port"] = mcp_port
            captured["require_final_action_approval"] = require_final_action_approval
            captured["god_runtime"] = god_runtime
            captured["runner_id"] = runner_id
            captured["memoryos_client"] = memoryos_client
            captured["review_god_session_layer"] = review_god_session_layer
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
    )

    assert captured["require_final_action_approval"] is False
    assert captured["god_runtime"] is None
    assert captured["memoryos_client"] is None
    assert captured["review_god_session_layer"] is None


@pytest.mark.asyncio
async def test_runner_can_require_final_action_approval(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(
            self,
            *,
            lanes_path: Path,
            xmuse_root: Path,
            mcp_port: int,
            require_final_action_approval: bool,
            god_runtime: str | None = None,
            runner_id: str | None = None,
            memoryos_client=None,
            review_god_session_layer=None,
        ) -> None:
            captured["require_final_action_approval"] = require_final_action_approval
            captured["god_runtime"] = god_runtime
            captured["runner_id"] = runner_id
            captured["memoryos_client"] = memoryos_client
            captured["review_god_session_layer"] = review_god_session_layer
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        require_final_action_approval=True,
        god_runtime="codex",
    )

    assert captured["require_final_action_approval"] is True
    assert captured["god_runtime"] == "codex"
    assert captured["memoryos_client"] is None
    assert captured["review_god_session_layer"] is None


@pytest.mark.asyncio
async def test_runner_refuses_duplicate_active_writer_lease(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            raise AssertionError("runner should reject before constructing orchestrator")

    lease_path = platform_runner._writer_lease_path(tmp_path / "feature_lanes.json")
    lease_path.write_text(
        json.dumps(
            {
                "runner_id": "runner-other",
                "lease_id": "lease-other",
                "heartbeat_at": 100.0,
                "expires_at": 160.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(platform_runner.time, "time", lambda: 120.0)
    monkeypatch.setattr(platform_runner.os, "getpid", lambda: 4242)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    with pytest.raises(RuntimeError, match="active writer lease"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=0,
            max_concurrent=1,
        )


def test_acquire_writer_lease_reclaims_stale_lease(tmp_path: Path, monkeypatch) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    lease_path = platform_runner._writer_lease_path(lanes_path)
    lease_path.write_text(
        json.dumps(
            {
                "runner_id": "runner-stale",
                "lease_id": "lease-stale",
                "heartbeat_at": 10.0,
                "expires_at": 20.0,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(platform_runner.time, "time", lambda: 30.0)

    lease = platform_runner._acquire_writer_lease(
        lanes_path,
        runner_id="runner-fresh",
    )

    assert lease["runner_id"] == "runner-fresh"
    assert lease["reclaimed_from_runner_id"] == "runner-stale"
    persisted = json.loads(lease_path.read_text(encoding="utf-8"))
    assert persisted["runner_id"] == "runner-fresh"
    assert persisted["reclaimed_from_runner_id"] == "runner-stale"


@pytest.mark.asyncio
async def test_writer_lease_heartbeat_renews_until_stopped(
    monkeypatch,
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    renewals: list[tuple[str, str]] = []

    def fake_renew(lanes, *, lease_id: str, runner_id: str, **kwargs):
        assert lanes == lanes_path
        renewals.append((lease_id, runner_id))
        return {"lease_id": lease_id, "runner_id": runner_id}

    monkeypatch.setattr(platform_runner, "_renew_writer_lease", fake_renew)
    stop = asyncio.Event()
    lost = asyncio.Event()

    task = asyncio.create_task(
        platform_runner._writer_lease_heartbeat_loop(
            lanes_path,
            lease_id="lease-1",
            runner_id="runner-1",
            stop=stop,
            lost=lost,
            interval_s=0.001,
        )
    )
    await asyncio.sleep(0.01)
    stop.set()
    await task

    assert renewals
    assert set(renewals) == {("lease-1", "runner-1")}
    assert not lost.is_set()


@pytest.mark.asyncio
async def test_writer_lease_heartbeat_marks_lost_when_renewal_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    monkeypatch.setattr(
        platform_runner,
        "_renew_writer_lease",
        lambda *args, **kwargs: None,
    )
    stop = asyncio.Event()
    lost = asyncio.Event()

    await platform_runner._writer_lease_heartbeat_loop(
        lanes_path,
        lease_id="lease-1",
        runner_id="runner-1",
        stop=stop,
        lost=lost,
        interval_s=0.001,
    )

    assert lost.is_set()
    assert stop.is_set()


@pytest.mark.asyncio
async def test_runner_releases_writer_lease_when_startup_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class UnsupportedLauncher:
        supports_persistent_sessions = False

    import xmuse_core.agents.launchers as launchers_module

    lease_path = platform_runner._writer_lease_path(tmp_path / "feature_lanes.json")
    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": UnsupportedLauncher()},
    )
    monkeypatch.setattr(platform_runner.time, "time", lambda: 100.0)
    monkeypatch.setattr(platform_runner.os, "getpid", lambda: 4242)

    with pytest.raises(RuntimeError, match="requires a launcher"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=0,
            max_concurrent=1,
            persistent_review_god_enabled=True,
        )

    assert not lease_path.exists()


@pytest.mark.asyncio
async def test_runner_rejects_persistent_review_god_without_capable_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class UnsupportedLauncher:
        supports_persistent_sessions = False

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
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
            persistent_review_god_enabled=True,
        )


@pytest.mark.asyncio
async def test_runner_can_explicitly_enable_persistent_review_god_with_capable_launcher(
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
            captured["review_god_session_layer"] = kwargs["review_god_session_layer"]
            self._sm = _FakeStateMachine()

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
        persistent_review_god_enabled=True,
    )

    assert captured["review_god_session_layer"] is not None


@pytest.mark.asyncio
async def test_runner_enables_persistent_review_god_with_default_codex_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured["review_god_session_layer"] = kwargs["review_god_session_layer"]
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        persistent_review_god_enabled=True,
    )

    assert captured["review_god_session_layer"] is not None


@pytest.mark.asyncio
async def test_runner_enables_peer_chat_with_default_codex_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            captured["ticked"] = True

    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "native")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    assert captured["scheduler_kwargs"]["scheduler_id"] == "platform-runner"
    assert captured["scheduler_kwargs"]["god_layer"] is not None
    assert captured["scheduler_kwargs"]["degraded_fallback_enabled"] is False
    assert captured["scheduler_kwargs"]["response_wait_s"] >= 180
    assert captured["scheduler_kwargs"]["claim_ttl_s"] >= (
        captured["scheduler_kwargs"]["response_wait_s"]
    )


@pytest.mark.asyncio
async def test_runner_uses_ray_peer_god_layer_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    import xmuse_core.agents.ray_session_layer as ray_session_layer_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    async def fake_prewarm(self) -> None:
        captured["prewarmed"] = type(self).__name__

    monkeypatch.delenv("XMUSE_PEER_GOD_BACKEND", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(ray_session_layer_module.RayGodSessionLayer, "prewarm", fake_prewarm)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    assert type(captured["scheduler_kwargs"]["god_layer"]).__name__ == "RayGodSessionLayer"
    assert captured["prewarmed"] == "RayGodSessionLayer"


@pytest.mark.asyncio
async def test_runner_builds_dispatch_bridge_with_peer_god_layer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    class FakeDispatchBridge:
        def __init__(self, **kwargs) -> None:
            captured["dispatch_bridge_kwargs"] = kwargs

    import xmuse_core.chat.dispatch_bridge as dispatch_bridge_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "native")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(dispatch_bridge_module, "ChatDispatchBridge", FakeDispatchBridge)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    assert captured["dispatch_bridge_kwargs"]["bridge_id"] == "platform-runner-dispatch"
    assert (
        captured["dispatch_bridge_kwargs"]["god_layer"]
        is captured["scheduler_kwargs"]["god_layer"]
    )
    assert captured["dispatch_bridge_kwargs"]["response_wait_s"] >= 180


@pytest.mark.asyncio
async def test_dispatch_bridge_tick_scans_chat_conversations(tmp_path: Path) -> None:
    from xmuse_core.chat.store import ChatStore

    root = tmp_path / "xmuse"
    root.mkdir()
    chat = ChatStore(root / "chat.db")
    first = chat.create_conversation("first")
    second = chat.create_conversation("second")

    class FakeDispatchBridge:
        def __init__(self) -> None:
            self.ticked: list[str] = []

        async def tick_once(self, *, conversation_id: str) -> None:
            self.ticked.append(conversation_id)

    bridge = FakeDispatchBridge()

    await platform_runner._tick_chat_dispatch_bridge(bridge, xmuse_root=root)

    assert bridge.ticked == [first.id, second.id]


@pytest.mark.asyncio
async def test_runner_prewarm_ray_peer_god_layer_by_default(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    async def fake_prewarm(self) -> None:
        captured["prewarmed"] = type(self).__name__

    import xmuse_core.agents.ray_session_layer as ray_session_layer_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.delenv("XMUSE_PEER_GOD_BACKEND", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(ray_session_layer_module.RayGodSessionLayer, "prewarm", fake_prewarm)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    assert captured["prewarmed"] == "RayGodSessionLayer"


@pytest.mark.asyncio
async def test_runner_can_force_native_peer_god_layer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    class FakePeerScheduler:
        def __init__(self, **kwargs) -> None:
            captured["scheduler_kwargs"] = kwargs

        async def tick_once(self) -> None:
            return None

    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "native")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )

    assert type(captured["scheduler_kwargs"]["god_layer"]).__name__ == "GodSessionLayer"




@pytest.mark.asyncio
async def test_runner_can_enable_persistent_execute_god_with_capable_launcher(
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
            self._sm = _FakeStateMachine()

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


def test_health_once_reports_native_persistent_runtime_without_ray(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(
            runner_pids=[11],
            mcp_pids=[12],
            services={"persistent_god_shim": [21]},
        ),
    )

    summary = platform_runner.health_once(lanes_path, live_pids={11, 12, 21})

    assert summary["processes"]["counts_by_service"]["persistent_god_shim"] == 1
    assert "ray" not in summary["processes"]["counts_by_service"]
    assert summary["warnings"] == []


@pytest.mark.asyncio
async def test_runner_ticks_blueprint_automation_without_blocking_dispatch(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {
        "dispatches": [],
        "planning_worker_ids": [],
    }

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._feature_graph_status_store = _FakeFeatureGraphStatusStore()
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-1",
                        "lane_local_id": "lane-local-1",
                        "conversation_id": "conv-a",
                        "graph_id": "graph-a-feature-a",
                        "graph_set_id": "graph-a-graph-set",
                        "status": "pending",
                        "priority": 1,
                        "allowed_files": ["src/xmuse_core/example.py"],
                        "required_checks": ["uv run pytest tests/xmuse/test_example.py -q"],
                    }
                ]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            captured["dispatches"].append(lane_id)
            self._sm._lanes[0]["status"] = "dispatched"

    class FakeBlueprintAutomationService:
        def __init__(self, *, base_dir: Path, **kwargs) -> None:
            captured["planning_base_dir"] = base_dir

        def tick(self, *, worker_id: str):
            captured["planning_worker_ids"].append(worker_id)
            return None

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        platform_runner,
        "BlueprintAutomationService",
        FakeBlueprintAutomationService,
        raising=False,
    )
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=1,
    )

    assert captured["planning_base_dir"] == tmp_path / "xmuse"
    assert captured["planning_worker_ids"] == ["platform-runner"]
    assert captured["dispatches"] == ["lane-1"]
    candidate = json.loads(
        (
            tmp_path
            / "xmuse"
            / "work"
            / "local_execution_candidates"
            / "graph-a.lane-1.json"
        ).read_text(encoding="utf-8")
    )
    assert candidate["schema_version"] == "xmuse.local_execution_candidate.v1"
    assert candidate["status"] == "candidate_only"
    assert candidate["proof_level"] == "local_runtime_proof"
    assert candidate["source_authority"] == "local_execution_candidate_capture"
    assert candidate["producer"] == "platform_runner_dispatch"
    assert candidate["conversation_id"] == "conv-a"
    assert candidate["lane_id"] == "lane-1"
    assert candidate["lane_local_id"] == "lane-local-1"
    assert candidate["runner_session_id"].startswith("runner-session-")
    assert candidate["runner_session_ref"].startswith("work/runner_sessions/")
    assert candidate["graph_id"] == "graph-a"
    assert candidate["graph_status_source_authority"] == "feature_graph_status_store"
    assert candidate["graph_status_lineage"]["status_id"] == "fgs:graph-a:feature-a:reviewing"
    assert candidate["source_refs"] == [
        "lane:lane-1",
        "lane_local:lane-local-1",
        "graph:graph-a",
        "graph_set:graph-a-graph-set",
        "feature_graph:graph-a-feature-a",
        "feature_graph_status:fgs:graph-a:feature-a:reviewing",
    ]
    assert candidate["changed_file_refs"] == ["src/xmuse_core/example.py"]
    assert candidate["verification_refs"] == [
        "uv run pytest tests/xmuse/test_example.py -q"
    ]
    assert "worker_output_is_review_truth" in candidate["forbidden_claims"]
    assert "review_truth_not_proven" in candidate["manual_gaps"]
    session_path = tmp_path / "xmuse" / candidate["runner_session_ref"]
    runner_session = json.loads(session_path.read_text(encoding="utf-8"))
    assert runner_session["schema_version"] == "xmuse.runner_session.v1"
    assert runner_session["session_id"] == candidate["runner_session_id"]
    assert runner_session["run_id"] == candidate["run_id"]
    assert runner_session["runner_id"] == candidate["worker_id"]
    assert runner_session["status"] == "session_completed"
    assert runner_session["proof_level"] == "local_runtime_proof"
    assert runner_session["candidate_artifact_refs"] == [
        "work/local_execution_candidates/graph-a.lane-1.json"
    ]
    assert runner_session["worker_evidence_bundle_refs"] == []
    assert runner_session["worker_evidence_bundle_count"] == 0
    assert "runner_session_is_review_truth" in runner_session["forbidden_claims"]


@pytest.mark.asyncio
async def test_runner_submits_graph_native_worker_evidence_before_candidate_capture(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            xmuse_root = kwargs["xmuse_root"]
            self._feature_graph_status_store = FeatureGraphStatusStore(
                xmuse_root / "feature_graph_statuses.json"
            )
            self._feature_graph_artifact_store = FeatureGraphArtifactStore(
                xmuse_root / "feature_graph_artifacts.json"
            )
            self._feature_graph_status_store.upsert(
                FeatureGraphExecutionStatusRecord(
                    status_id="fgs:graph-a:feature-a:ready",
                    conversation_id="conv-a",
                    planning_run_id="planning-run-a",
                    graph_set_id="graph-a-graph-set",
                    graph_set_version=1,
                    feature_plan_id="feature-plan-a",
                    feature_plan_version=1,
                    feature_id="feature-a",
                    feature_graph_id="graph-a-feature-a",
                    blueprint_proof_level="contract_proof",
                    status=FeatureGraphExecutionStatus.READY,
                    ready_lane_ids=["lane-local-1"],
                    projection_lane_ids=["lane-1"],
                    updated_at="2026-06-03T03:00:00Z",
                )
            )
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-1",
                        "lane_local_id": "lane-local-1",
                        "conversation_id": "conv-a",
                        "graph_id": "graph-a-feature-a",
                        "graph_set_id": "graph-a-graph-set",
                        "status": "pending",
                        "priority": 1,
                        "prompt": "Implement the graph-native worker handoff.",
                        "acceptance_criteria": [
                            "Worker evidence reaches graph-native review intake."
                        ],
                        "blueprint_refs": ["blueprint:bp-graph-native:v1"],
                        "allowed_files": ["src/xmuse_core/example.py"],
                        "required_checks": [
                            "uv run pytest tests/xmuse/test_example.py -q"
                        ],
                        "provider_session_binding_id": (
                            "provider_session_binding:psb-worker-a:v1"
                        ),
                    }
                ]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            self._sm.update_metadata(lane_id, {"status": "dispatched"})

        def claim_next_ready_feature_graph_worker(self, **kwargs):
            return claim_next_ready_feature_graph_worker(
                store=self._feature_graph_status_store,
                **kwargs,
            )

        def submit_feature_graph_worker_evidence(self, **kwargs):
            return submit_feature_graph_worker_evidence(
                store=self._feature_graph_status_store,
                artifact_store=self._feature_graph_artifact_store,
                **kwargs,
            )

    class FakeBlueprintAutomationService:
        def __init__(self, *, base_dir: Path, **kwargs) -> None:
            return None

        def tick(self, *, worker_id: str):
            return None

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        platform_runner,
        "BlueprintAutomationService",
        FakeBlueprintAutomationService,
        raising=False,
    )
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=1,
    )

    status_store = FeatureGraphStatusStore(
        tmp_path / "xmuse" / "feature_graph_statuses.json"
    )
    status = status_store.get(
        graph_set_id="graph-a-graph-set",
        feature_graph_id="graph-a-feature-a",
    )
    assert status.status is FeatureGraphExecutionStatus.REVIEWING
    assert status.active_lane_ids == []
    assert status.completed_lane_ids == ["lane-local-1"]
    assert status.active_worker_session_id.startswith("runner-session-")
    assert (
        status.active_provider_session_binding_ref
        == "provider_session_binding:psb-worker-a:v1"
    )

    artifact_store = FeatureGraphArtifactStore(
        tmp_path / "xmuse" / "feature_graph_artifacts.json"
    )
    bundles = artifact_store.list_evidence_bundles()
    assert len(bundles) == 1
    assert bundles[0].worker_session_id == status.active_worker_session_id
    assert bundles[0].provider_session_binding_ref == (
        "provider_session_binding:psb-worker-a:v1"
    )
    assert bundles[0].lane_graph_summary.completed_lane_ids == ["lane-local-1"]
    assert bundles[0].verification.commands_run == [
        "uv run pytest tests/xmuse/test_example.py -q"
    ]

    candidate = json.loads(
        (
            tmp_path
            / "xmuse"
            / "work"
            / "local_execution_candidates"
            / "graph-a.lane-1.json"
        ).read_text(encoding="utf-8")
    )
    assert candidate["status"] == "candidate_only"
    assert candidate["proof_level"] == "local_runtime_proof"
    assert candidate["graph_status_lineage"]["status"] == "reviewing"
    assert (
        f"feature_evidence_bundle:{bundles[0].bundle_id}:v1"
        in candidate["source_refs"]
    )
    assert "review_truth_not_proven" in candidate["manual_gaps"]
    assert "worker_output_is_review_truth" in candidate["forbidden_claims"]

    session_path = tmp_path / "xmuse" / candidate["runner_session_ref"]
    runner_session = json.loads(session_path.read_text(encoding="utf-8"))
    assert runner_session["status"] == "session_completed"
    assert runner_session["proof_level"] == "local_runtime_proof"
    assert runner_session["candidate_artifact_refs"] == [
        "work/local_execution_candidates/graph-a.lane-1.json"
    ]
    assert runner_session["worker_evidence_bundle_refs"] == [
        f"feature_evidence_bundle:{bundles[0].bundle_id}:v1"
    ]
    assert runner_session["worker_evidence_bundle_count"] == 1
    assert "runner_session_is_review_truth" in runner_session["forbidden_claims"]
    candidate_lineage = build_local_execution_candidate_lineage(
        artifact=candidate,
        artifact_ref="work/local_execution_candidates/graph-a.lane-1.json",
    )
    runner_session_lineage = build_runner_session_lineage(
        artifact=runner_session,
        artifact_ref=candidate["runner_session_ref"],
        session_id=candidate["runner_session_id"],
        run_id=candidate["run_id"],
        runner_id=candidate["worker_id"],
        candidate_artifact_ref="work/local_execution_candidates/graph-a.lane-1.json",
        graph_id="graph-a",
    )
    boundary = build_validated_execution_candidate_boundary(
        candidate_lineage=candidate_lineage,
        runner_session_lineage=runner_session_lineage,
        graph_id="graph-a",
        lane_id="lane-1",
    )
    assert boundary["status"] == "validated"
    assert "worker_output_is_review_truth" in boundary["forbidden_claims"]


def test_runner_candidate_capture_fail_closes_before_worker_evidence_reviewing(
    tmp_path: Path,
) -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self._feature_graph_status_store = _FakeRunningFeatureGraphStatusStore()

    lane = {
        "feature_id": "lane-1",
        "lane_local_id": "lane-local-1",
        "conversation_id": "conv-a",
        "graph_id": "graph-a-feature-a",
        "graph_set_id": "graph-a-graph-set",
        "status": "dispatched",
        "allowed_files": ["src/xmuse_core/example.py"],
        "required_checks": ["uv run pytest tests/xmuse/test_example.py -q"],
    }

    capture = platform_runner._capture_local_execution_candidate_if_requested(
        output_dir=tmp_path / "xmuse" / "work" / "local_execution_candidates",
        run_id="local-execution-runner",
        runner_id="platform-runner",
        runner_session_id="runner-session-running",
        runner_session_ref="work/runner_sessions/runner-session-running.json",
        xmuse_root=tmp_path / "xmuse",
        orch=FakeOrchestrator(),
        lane=lane,
        graph_id=None,
        resolution_id=None,
    )

    assert capture is not None
    candidate = capture["artifact"]
    assert candidate["status"] == "manual_gap"
    assert candidate["proof_level"] == "manual_gap"
    assert candidate["producer"] == "platform_runner_dispatch"
    assert candidate["graph_status_lineage"]["status"] == "running"
    assert "graph_native_worker_evidence_not_submitted" in candidate["manual_gaps"]
    assert "local_execution_candidate_not_reviewable" in candidate["manual_gaps"]
    assert "graph_status_lineage_missing" not in candidate["manual_gaps"]
    assert "worker_output_is_review_truth" in candidate["forbidden_claims"]


@pytest.mark.asyncio
async def test_runner_session_does_not_count_manual_gap_candidate_as_runtime_proof(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._feature_graph_status_store = _FakeRunningFeatureGraphStatusStore()
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-1",
                        "lane_local_id": "lane-local-1",
                        "conversation_id": "conv-a",
                        "graph_id": "graph-a-feature-a",
                        "graph_set_id": "graph-a-graph-set",
                        "status": "pending",
                        "priority": 1,
                        "allowed_files": ["src/xmuse_core/example.py"],
                        "required_checks": [
                            "uv run pytest tests/xmuse/test_example.py -q"
                        ],
                    }
                ]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            self._sm._lanes[0]["status"] = "dispatched"

    class FakeBlueprintAutomationService:
        def __init__(self, *, base_dir: Path, **kwargs) -> None:
            return None

        def tick(self, *, worker_id: str):
            return None

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        platform_runner,
        "BlueprintAutomationService",
        FakeBlueprintAutomationService,
        raising=False,
    )
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=1,
    )

    candidate = json.loads(
        (
            tmp_path
            / "xmuse"
            / "work"
            / "local_execution_candidates"
            / "graph-a.lane-1.json"
        ).read_text(encoding="utf-8")
    )
    assert candidate["status"] == "manual_gap"
    assert candidate["proof_level"] == "manual_gap"
    assert "graph_native_worker_evidence_not_submitted" in candidate["manual_gaps"]

    session_paths = list((tmp_path / "xmuse" / "work" / "runner_sessions").glob("*.json"))
    assert len(session_paths) == 1
    runner_session = json.loads(session_paths[0].read_text(encoding="utf-8"))
    assert runner_session["schema_version"] == "xmuse.runner_session.v1"
    assert runner_session["status"] == "session_completed"
    assert runner_session["proof_level"] == "manual_gap"
    assert runner_session["candidate_artifact_refs"] == []
    assert runner_session["candidate_lane_ids"] == []
    assert "runner_session_candidate_refs_missing" in runner_session["manual_gaps"]
    assert "runner_session_is_review_truth" in runner_session["forbidden_claims"]


@pytest.mark.asyncio
async def test_runner_session_marks_dispatch_task_failure_manual_gap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-fails",
                        "status": "pending",
                        "priority": 1,
                        "graph_id": "graph-a",
                    }
                ]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            raise RuntimeError(f"dispatch failed for {lane_id}")

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=1,
    )

    session_paths = list((tmp_path / "xmuse" / "work" / "runner_sessions").glob("*.json"))
    assert len(session_paths) == 1
    runner_session = json.loads(session_paths[0].read_text(encoding="utf-8"))
    assert runner_session["schema_version"] == "xmuse.runner_session.v1"
    assert runner_session["status"] == "session_failed"
    assert runner_session["proof_level"] == "manual_gap"
    assert runner_session["candidate_artifact_refs"] == []
    assert runner_session["candidate_lane_ids"] == []
    assert runner_session["failure"] == (
        "dispatch task failure: lane-fails: RuntimeError: "
        "dispatch failed for lane-fails"
    )
    assert "runner_session_not_completed" in runner_session["manual_gaps"]
    assert "runner_session_is_review_truth" in runner_session["forbidden_claims"]


@pytest.mark.asyncio
async def test_runner_session_marks_candidate_capture_failure_manual_gap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-capture-fails",
                        "status": "pending",
                        "priority": 1,
                        "graph_id": "graph-a",
                    }
                ]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            self._sm._lanes[0]["status"] = "dispatched"

    async def _fast_sleep(_: float) -> None:
        return None

    def _capture_fails(**kwargs):
        raise OSError("candidate output directory unavailable")

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(
        platform_runner,
        "_capture_local_execution_candidate_if_requested",
        _capture_fails,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=1,
    )

    session_paths = list((tmp_path / "xmuse" / "work" / "runner_sessions").glob("*.json"))
    assert len(session_paths) == 1
    runner_session = json.loads(session_paths[0].read_text(encoding="utf-8"))
    assert runner_session["schema_version"] == "xmuse.runner_session.v1"
    assert runner_session["status"] == "session_failed"
    assert runner_session["proof_level"] == "manual_gap"
    assert runner_session["candidate_artifact_refs"] == []
    assert runner_session["candidate_lane_ids"] == []
    assert runner_session["failure"] == (
        "local execution candidate capture failure: lane-capture-fails: "
        "OSError: candidate output directory unavailable"
    )
    assert "runner_session_not_completed" in runner_session["manual_gaps"]
    assert "runner_session_is_review_truth" in runner_session["forbidden_claims"]


@pytest.mark.asyncio
async def test_runner_shutdown_continues_when_session_finish_capture_fails(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeLoop:
        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return 0.0

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine([])

    captured: dict[str, object] = {"finish_attempted": False}

    def _finish_fails(**kwargs):
        captured["finish_attempted"] = True
        raise ValueError("runner session start artifact is invalid JSON")

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(
        platform_runner,
        "capture_runner_session_finished",
        _finish_fails,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
    )

    assert captured["finish_attempted"] is True
    assert not platform_runner._writer_lease_path(
        tmp_path / "feature_lanes.json"
    ).exists()


@pytest.mark.asyncio
async def test_runner_loop_blocks_refactor_required_and_status_reports_recovery(
    monkeypatch,
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "xmuse"
    lanes_path = xmuse_root / "feature_lanes.json"
    lanes_path.parent.mkdir(parents=True)
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-refactor",
                        "status": "reworking",
                        "priority": 5,
                        "graph_id": "graph-a",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    _write_recovery_artifact(
        xmuse_root,
        graph_id="graph-a",
        lane_id="lane-refactor",
        decision="refactor_required",
        retry_allowed=False,
    )
    captured: dict[str, object] = {"dispatches": []}
    orchestrator_holder: dict[str, object] = {}

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._root = kwargs["xmuse_root"]
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-refactor",
                        "status": "reworking",
                        "priority": 5,
                        "graph_id": "graph-a",
                    }
                ]
            )
            orchestrator_holder["orch"] = self

        async def reconcile_status_changes(
            self, *, dispatch_reworking: bool = True
        ) -> None:
            captured["reconcile_dispatch_reworking"] = dispatch_reworking

        async def dispatch_lane(self, lane_id: str) -> None:
            captured["dispatches"].append(lane_id)

    class FakeBlueprintAutomationService:
        def __init__(self, *, base_dir: Path, **kwargs) -> None:
            captured["planning_base_dir"] = base_dir

        def tick(self, *, worker_id: str):
            captured["planning_worker_id"] = worker_id
            return None

    async def _instant_idle_wait(awaitable, *, timeout: float):
        awaitable.close()
        raise TimeoutError

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        platform_runner,
        "BlueprintAutomationService",
        FakeBlueprintAutomationService,
        raising=False,
    )
    monkeypatch.setattr(
        platform_runner,
        "_writer_lease_heartbeat_loop",
        lambda *args, **kwargs: asyncio.Event().wait(),
    )
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "wait_for", _instant_idle_wait)

    await platform_runner.run(
        lanes_path=lanes_path,
        xmuse_root=xmuse_root,
        mcp_port=8100,
        max_hours=1,
        max_concurrent=1,
        runner_recovery_proof_output=xmuse_root / "reports" / "runner-recovery.json",
    )

    assert captured["planning_base_dir"] == xmuse_root
    assert captured["planning_worker_id"] == "platform-runner"
    assert captured["dispatches"] == []
    blocked_lane = orchestrator_holder["orch"]._sm.get_lanes()[0]
    assert blocked_lane["dispatch_blocked_by_recovery"] is True
    assert blocked_lane["recovery_dispatch_block_reason"] == "refactor_required"
    assert blocked_lane["recovery_source_authority"] == "lane_recovery_artifact"
    assert blocked_lane["recovery_decision"]["retry_allowed"] is False
    assert "dispatch_attempt_id" not in blocked_lane

    status = runner_status(
        RunnerSupervisorConfig(
            repo_root=tmp_path,
            pid_file=xmuse_root / "runner.pid.json",
            lanes_path=lanes_path,
        ),
        runner_pids=[1234],
        mcp_pids=[],
        live_pids={1234},
    )
    recovery = status["health"]["recovery"]
    assert recovery["source_authority"] == "lane_recovery_artifact"
    assert recovery["proof_level"] == "contract_proof"
    assert recovery["counts"] == {
        "blocked": 1,
        "non_retry_decision": 1,
        "invalid_artifact": 0,
        "retry_allowed": 0,
    }
    assert recovery["blocked_lanes"][0]["lane_id"] == "lane-refactor"
    assert recovery["blocked_lanes"][0]["decision"] == "refactor_required"
    assert "live_runner_recovery_enforcement_not_proven" in recovery["manual_gaps"]
    assert "ready_to_merge" in recovery["forbidden_claims"]

    proof_artifact = json.loads(
        (xmuse_root / "reports" / "runner-recovery.json").read_text(encoding="utf-8")
    )
    assert proof_artifact["schema_version"] == "xmuse.local_runner_recovery_proof.v1"
    assert proof_artifact["status"] == "ok"
    assert proof_artifact["proof_level"] == "local_runtime_proof"
    assert proof_artifact["source_authority"] == (
        "platform_runner_candidate_selection"
        "+shared_runner_health_model"
        "+lane_recovery_artifact"
    )
    assert proof_artifact["candidate_selection"][
        "excluded_recovery_blocked_lane_ids"
    ] == ["lane-refactor"]
    assert proof_artifact["runner_supervisor"]["recovery"]["blocked_lanes"][0][
        "decision"
    ] == "refactor_required"
    assert "review_truth_not_proven" in proof_artifact["manual_gaps"]
    assert "overnight_safe_recovery" in proof_artifact["forbidden_claims"]
    assert "ready_to_merge" in proof_artifact["forbidden_claims"]


@pytest.mark.asyncio
async def test_runner_dispatches_actor_session_groups_under_one_writer_lease(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {
        "dispatches": [],
        "feature_groups": [],
        "lease_ids": [],
    }

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-session-a",
                        "status": "pending",
                        "priority": 2,
                        "feature_group": "actor/session-a",
                    },
                    {
                        "feature_id": "lane-session-b",
                        "status": "pending",
                        "priority": 1,
                        "feature_group": "actor/session-b",
                    },
                ]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            lane = next(
                item for item in self._sm._lanes if item["feature_id"] == lane_id
            )
            lease = json.loads(
                platform_runner._writer_lease_path(
                    tmp_path / "feature_lanes.json"
                ).read_text(encoding="utf-8")
            )
            captured["dispatches"].append(lane_id)
            captured["feature_groups"].append(lane["feature_group"])
            captured["lease_ids"].append(lease["lease_id"])
            lane["status"] = "dispatched"

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=2,
    )

    assert captured["dispatches"] == ["lane-session-a", "lane-session-b"]
    assert captured["feature_groups"] == ["actor/session-a", "actor/session-b"]
    assert len(set(captured["lease_ids"])) == 1
    assert not platform_runner._writer_lease_path(
        tmp_path / "feature_lanes.json"
    ).exists()


@pytest.mark.asyncio
async def test_runner_schedules_ready_lanes_before_slow_reconcile(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {
        "dispatches": [],
        "reconcile_dispatch_reworking": [],
    }
    original_sleep = asyncio.sleep

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [
                    {"feature_id": "lane-rework", "status": "reworking", "priority": 3},
                    {"feature_id": "lane-pending-a", "status": "pending", "priority": 2},
                    {"feature_id": "lane-pending-b", "status": "pending", "priority": 1},
                ]
            )

        async def reconcile_status_changes(self, *, dispatch_reworking: bool = True) -> None:
            captured["reconcile_dispatch_reworking"].append(dispatch_reworking)
            await original_sleep(0)
            assert captured["dispatches"] == [
                "lane-rework",
                "lane-pending-a",
                "lane-pending-b",
            ]

        async def dispatch_lane(self, lane_id: str) -> None:
            captured["dispatches"].append(lane_id)
            for lane in self._sm._lanes:
                if lane["feature_id"] == lane_id:
                    lane["status"] = "dispatched"
            await original_sleep(0.01)

    async def _fast_sleep(_: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=64,
    )

    assert captured["dispatches"] == [
        "lane-rework",
        "lane-pending-a",
        "lane-pending-b",
    ]
    assert captured["reconcile_dispatch_reworking"] == [False]


@pytest.mark.asyncio
async def test_runner_dispatches_new_ready_lanes_while_reconcile_is_blocked(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {
        "dispatches": [],
        "reconcile_calls": 0,
    }
    original_sleep = asyncio.sleep
    reconcile_cancelled = asyncio.Event()
    never_release = asyncio.Event()

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [{"feature_id": "lane-1", "status": "pending", "priority": 1}]
            )

        async def reconcile_status_changes(self, *, dispatch_reworking: bool = True) -> None:
            captured["reconcile_calls"] += 1
            try:
                await never_release.wait()
            except asyncio.CancelledError:
                reconcile_cancelled.set()
                raise

        async def dispatch_lane(self, lane_id: str) -> None:
            captured["dispatches"].append(lane_id)
            for lane in self._sm._lanes:
                if lane["feature_id"] == lane_id:
                    lane["status"] = "dispatched"
            await original_sleep(0)

    sleep_calls = 0
    fake_orch_holder: dict[str, FakeOrchestrator] = {}

    class CapturingOrchestrator(FakeOrchestrator):
        def __init__(self, **kwargs) -> None:
            super().__init__(**kwargs)
            fake_orch_holder["orch"] = self

    async def _fast_sleep(_: float) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 1:
            fake_orch_holder["orch"]._sm._lanes.append(
                {"feature_id": "lane-2", "status": "pending", "priority": 1}
            )
        await original_sleep(0)

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", CapturingOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=1,
        max_concurrent=64,
    )

    assert captured["dispatches"] == ["lane-1", "lane-2"]
    assert captured["reconcile_calls"] == 1
    assert reconcile_cancelled.is_set()


@pytest.mark.asyncio
async def test_runner_stops_before_dispatch_when_writer_lease_renewal_is_lost(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {
        "dispatches": [],
        "reconcile_calls": 0,
    }

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "priority": 1,
                    }
                ]
            )

        async def reconcile_status_changes(self) -> None:
            captured["reconcile_calls"] += 1

        async def dispatch_lane(self, lane_id: str) -> None:
            captured["dispatches"].append(lane_id)
            self._sm._lanes[0]["status"] = "dispatched"

    async def _fast_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", _fast_sleep)
    monkeypatch.setattr(
        platform_runner,
        "_renew_writer_lease",
        lambda *args, **kwargs: None,
    )

    with pytest.raises(RuntimeError, match="writer lease"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=1,
            max_concurrent=1,
        )

    assert captured["reconcile_calls"] == 0
    assert captured["dispatches"] == []


@pytest.mark.asyncio
async def test_runner_does_not_dispatch_more_lanes_after_heartbeat_loss(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {
        "dispatches": [],
    }
    original_sleep = asyncio.sleep

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [
                    {"feature_id": "lane-1", "status": "pending", "priority": 2},
                    {"feature_id": "lane-2", "status": "pending", "priority": 1},
                ]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            captured["dispatches"].append(lane_id)
            await original_sleep(0.01)
            for lane in self._sm._lanes:
                if lane["feature_id"] == lane_id:
                    lane["status"] = "dispatched"

    async def fake_heartbeat(*args, stop, lost, **kwargs) -> None:
        await original_sleep(0)
        lost.set()
        stop.set()

    async def fast_sleep(_: float) -> None:
        await original_sleep(0)

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(platform_runner, "_writer_lease_heartbeat_loop", fake_heartbeat)

    with pytest.raises(RuntimeError, match="writer lease lost"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=1,
            max_concurrent=1,
        )

    assert captured["dispatches"] == ["lane-1"]


@pytest.mark.asyncio
async def test_runner_cancels_in_flight_dispatch_when_lease_lost(
    monkeypatch,
    tmp_path: Path,
) -> None:
    original_sleep = asyncio.sleep
    dispatch_started = asyncio.Event()
    dispatch_cancelled = asyncio.Event()
    never_release = asyncio.Event()

    class FakeLoop:
        def __init__(self) -> None:
            self._times = iter((0.0, 0.0, 0.0, 3601.0))

        def add_signal_handler(self, *args, **kwargs) -> None:
            return None

        def time(self) -> float:
            return next(self._times)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine(
                [{"feature_id": "lane-1", "status": "pending", "priority": 1}]
            )

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            dispatch_started.set()
            try:
                await never_release.wait()
            except asyncio.CancelledError:
                dispatch_cancelled.set()
                raise

    async def fake_heartbeat(*args, stop, lost, **kwargs) -> None:
        await dispatch_started.wait()
        lost.set()
        stop.set()

    async def fast_sleep(_: float) -> None:
        await dispatch_started.wait()
        await original_sleep(0)

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner.asyncio, "get_running_loop", lambda: FakeLoop())
    monkeypatch.setattr(platform_runner.asyncio, "sleep", fast_sleep)
    monkeypatch.setattr(platform_runner, "_writer_lease_heartbeat_loop", fake_heartbeat)

    with pytest.raises(RuntimeError, match="writer lease lost"):
        await platform_runner.run(
            lanes_path=tmp_path / "feature_lanes.json",
            xmuse_root=tmp_path / "xmuse",
            mcp_port=8100,
            max_hours=1,
            max_concurrent=1,
        )

    assert dispatch_started.is_set()
    assert dispatch_cancelled.is_set()


@pytest.mark.asyncio
async def test_runner_disables_peer_chat_when_no_persistent_launcher(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class UnsupportedLauncher:
        supports_persistent_sessions = False

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    def fail_scheduler(*args, **kwargs):
        raise AssertionError("peer scheduler should not be constructed")

    import xmuse_core.agents.launchers as launchers_module
    import xmuse_core.chat.peer_scheduler as peer_scheduler_module

    monkeypatch.setattr(
        launchers_module,
        "build_default_launchers",
        lambda *, mcp_port: {"shim": UnsupportedLauncher()},
    )
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", fail_scheduler)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
    )


def test_runner_parser_rejects_non_codex_god_runtime() -> None:
    with pytest.raises(SystemExit):
        platform_runner.main_arg_parser().parse_args(["--god-runtime", "claude"])


def test_runner_parser_defaults_chat_driver_model_to_codex_model() -> None:
    args = platform_runner.main_arg_parser().parse_args([])

    assert args.chat_driver_model == "gpt-5.4"


def test_platform_runner_rejects_peer_chat_with_chat_driver() -> None:
    parser = platform_runner.main_arg_parser()
    args = parser.parse_args(["--peer-chat", "--chat-driver"])

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_platform_runner_rejects_default_review_peer_without_persistent_review() -> None:
    parser = platform_runner.main_arg_parser()
    args = parser.parse_args(["--default-review-peer-routing"])

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_platform_runner_rejects_review_timeout_without_persistent_review() -> None:
    parser = platform_runner.main_arg_parser()
    args = parser.parse_args(["--persistent-review-timeout-s", "1800"])

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_platform_runner_rejects_non_positive_review_timeout() -> None:
    parser = platform_runner.main_arg_parser()
    args = parser.parse_args([
        "--persistent-review-god",
        "--persistent-review-timeout-s",
        "0",
    ])

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


@pytest.mark.parametrize("timeout", ["nan", "inf"])
def test_platform_runner_rejects_non_finite_review_timeout(timeout: str) -> None:
    parser = platform_runner.main_arg_parser()
    args = parser.parse_args([
        "--persistent-review-god",
        "--persistent-review-timeout-s",
        timeout,
    ])

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_runner_parser_supports_health_once() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--health-once", "--health-check-http", "--stale-after-s", "120"]
    )

    assert args.health_once is True
    assert args.health_check_http is True
    assert args.stale_after_s == 120


def test_runner_parser_resolves_lanes_from_xmuse_root(tmp_path: Path) -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--xmuse-root", str(tmp_path / "runtime")]
    )
    xmuse_root, lanes_path = platform_runner._runtime_paths_from_args(args)

    assert xmuse_root == (tmp_path / "runtime").resolve()
    assert lanes_path == xmuse_root / "feature_lanes.json"


def test_runner_parser_explicit_lanes_override_xmuse_root(tmp_path: Path) -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--xmuse-root",
            str(tmp_path / "runtime"),
            "--lanes",
            str(tmp_path / "projection.json"),
        ]
    )
    xmuse_root, lanes_path = platform_runner._runtime_paths_from_args(args)

    assert xmuse_root == (tmp_path / "runtime").resolve()
    assert lanes_path == tmp_path / "projection.json"


def test_runner_parser_defaults_health_stale_threshold_to_1800() -> None:
    args = platform_runner.main_arg_parser().parse_args(["--health-once"])

    assert args.stale_after_s == 1800.0


def test_runner_parser_supports_persistent_review_god_flag() -> None:
    args = platform_runner.main_arg_parser().parse_args(["--persistent-review-god"])

    assert args.persistent_review_god is True


def test_runner_parser_supports_persistent_review_timeout() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--persistent-review-god", "--persistent-review-timeout-s", "1800"]
    )

    platform_runner.validate_args(args)
    assert args.persistent_review_timeout_s == 1800


def test_runner_parser_supports_default_review_peer_routing_flag() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--default-review-peer-routing"]
    )

    assert args.default_review_peer_routing is True


def test_runner_parser_supports_provider_profile_refs() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--execution-provider-profile-ref",
            "codex.default",
            "--review-provider-profile-ref",
            "codex.review",
        ]
    )

    assert args.execution_provider_profile_ref == "codex.default"
    assert args.review_provider_profile_ref == "codex.review"


@pytest.mark.asyncio
async def test_runner_wires_default_review_peer_routing(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        persistent_review_god_enabled=True,
        persistent_review_timeout_s=1800,
        default_review_peer_routing_enabled=True,
    )

    assert captured["review_god_session_layer"] is not None
    assert captured["persistent_review_receive_timeout_s"] == 1800
    assert captured["default_review_peer_routing_enabled"] is True


@pytest.mark.asyncio
async def test_runner_wires_provider_profile_ref_overrides(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        execution_provider_profile_ref="codex.default",
        review_provider_profile_ref="codex.review",
    )

    assert captured["execution_provider_profile_ref"] == "codex.default"
    assert captured["review_provider_profile_ref"] == "codex.review"


def test_has_persistent_session_launcher_requires_explicit_capability() -> None:
    class OneShotLauncher:
        pass

    class FakeCapabilityLauncher:
        supports_persistent_sessions = True

    class PersistentLauncher:
        supports_persistent_sessions = True

        def build_persistent_command(self, role: str, worktree: Path) -> list[str]:
            return ["persistent-agent", role, str(worktree)]

    assert platform_runner._has_persistent_session_launcher({"codex": OneShotLauncher()}) is False
    assert (
        platform_runner._has_persistent_session_launcher(
            {"codex": FakeCapabilityLauncher()}
        )
        is False
    )
    assert (
        platform_runner._has_persistent_session_launcher(
            {"codex": OneShotLauncher(), "shim": PersistentLauncher()}
        )
        is True
    )


def test_health_once_reads_projection_and_uses_live_pid_evidence(tmp_path: Path) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "live-worker",
                        "status": "dispatched",
                        "worker_pid": 123,
                        "dispatched_at": 100.0,
                    },
                    {
                        "feature_id": "dead-worker",
                        "status": "dispatched",
                        "worker_pid": 456,
                        "dispatched_at": 100.0,
                    },
                    {
                        "feature_id": "infra-failed",
                        "status": "exec_failed",
                        "failure_reason": "execution_infra_unavailable",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    summary = platform_runner.health_once(
        lanes_path,
        now=1000.0,
        stale_after_s=300.0,
        live_pids={123},
    )

    assert summary["groups"]["live"] == ["live-worker"]
    assert summary["groups"]["stale"] == ["dead-worker"]
    assert summary["groups"]["infra_failed"] == ["infra-failed"]


def test_health_once_uses_shared_read_model_process_semantics(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[11, 12], mcp_pids=[]),
    )

    summary = platform_runner.health_once(lanes_path, live_pids={11, 12})

    assert summary["processes"]["runner_count"] == 2
    assert summary["processes"]["mcp_count"] == 0
    assert [warning["code"] for warning in summary["warnings"]] == [
        "duplicate_runner_processes",
        "missing_mcp_process",
    ]


def test_health_once_exposes_runtime_operations_contract(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    (tmp_path / "chat.db").write_text("", encoding="utf-8")
    (tmp_path / "god_sessions.json").write_text("{}", encoding="utf-8")
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.setenv("XMUSE_RAY_GOD_TRANSPORT", "app-server")
    monkeypatch.setenv("XMUSE_RAY_GOD_MCP", "1")
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(
            runner_pids=[11],
            mcp_pids=[12],
            services={"chat_api": [13], "codex_app_server": [21], "raylet": [31]},
        ),
    )
    monkeypatch.setattr(platform_runner, "_http_status", lambda url: 200)

    summary = platform_runner.health_once(
        lanes_path,
        xmuse_root=tmp_path,
        mcp_port=8101,
        chat_api_url="http://127.0.0.1:8201",
        check_http=True,
        live_pids={11, 12, 13, 21, 31},
    )

    operations = summary["operations"]
    assert operations["ports"] == {
        "mcp": {"port": 8101, "url": "http://127.0.0.1:8101/mcp"},
        "mcp_chat": {"port": 8101, "url": "http://127.0.0.1:8101/mcp/chat"},
        "chat_api": {"port": 8201, "url": "http://127.0.0.1:8201"},
    }
    assert operations["readiness"]["chat_api"]["status"] == "ready"
    assert operations["readiness"]["mcp"]["status"] == "ready"
    assert operations["readiness"]["runner"]["status"] == "ready"
    assert operations["readiness"]["ray_god_layer"] == {
        "status": "configured",
        "backend": "ray",
        "transport": "app-server",
        "mcp_enabled": True,
    }
    assert operations["readiness"]["codex_app_server"]["status"] == "observed"
    assert operations["durable_state"]["chat_db"]["exists"] is True
    assert operations["durable_state"]["god_sessions"]["exists"] is True
    assert operations["scheduler_progress"]["status"] == "no_traces"
    assert operations["chat_dispatch_bridge"] == {
        "status": "no_entries",
        "total": 0,
        "queued": 0,
        "processing": 0,
        "dispatched": 0,
        "failed": 0,
        "latest": None,
    }
    assert operations["cleanup"]["status"] == "clean"


def test_health_once_reports_missing_chat_dispatch_bridge_db(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[11], mcp_pids=[], services={}),
    )

    summary = platform_runner.health_once(
        lanes_path,
        xmuse_root=tmp_path,
        live_pids={11},
    )

    assert summary["operations"]["chat_dispatch_bridge"] == {
        "status": "missing_chat_db",
        "total": 0,
        "queued": 0,
        "processing": 0,
        "dispatched": 0,
        "failed": 0,
        "latest": None,
    }


def test_health_once_exposes_chat_dispatch_bridge_progress(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    conversation = ChatStore(tmp_path / "chat.db").create_conversation("V14 bridge health")
    queue = ChatDispatchQueueStore(tmp_path / "chat.db")
    dispatched = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation.id,
        proposal_id="proposal-v14-dispatched",
        resolution_id="resolution-v14-dispatched",
        collaboration_run_id="collab-v14",
        artifact_ref="artifact:lane_graph",
    )
    queued = queue.enqueue_agent_auto_dispatch(
        conversation_id=conversation.id,
        proposal_id="proposal-v14-queued",
        resolution_id="resolution-v14-queued",
        collaboration_run_id="collab-v14",
        artifact_ref="artifact:lane_graph",
    )
    queue.claim_next_auto_dispatch(
        conversation_id=conversation.id,
        claimed_by="platform-runner-dispatch",
    )
    queue.mark_dispatched(
        dispatched.entry_id,
        provider_run_ref="provider:execute:part-execute",
        dispatch_evidence="mcp_writeback:inbox-v14-dispatch",
    )
    assert queued.status == "queued"
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[11], mcp_pids=[], services={}),
    )

    summary = platform_runner.health_once(
        lanes_path,
        xmuse_root=tmp_path,
        live_pids={11},
    )

    bridge = summary["operations"]["chat_dispatch_bridge"]
    assert bridge["status"] == "observed"
    assert bridge["total"] == 2
    assert bridge["queued"] == 1
    assert bridge["processing"] == 0
    assert bridge["dispatched"] == 1
    assert bridge["failed"] == 0
    assert bridge["latest"] == {
        "entry_id": dispatched.entry_id,
        "conversation_id": conversation.id,
        "status": "dispatched",
        "source": "agent",
        "target": "execute",
        "auto_execute": True,
        "proposal_id": "proposal-v14-dispatched",
        "resolution_id": "resolution-v14-dispatched",
        "collaboration_run_id": "collab-v14",
        "artifact_ref": "artifact:lane_graph",
        "dispatch_evidence": "mcp_writeback:inbox-v14-dispatch",
    }


def test_health_once_marks_runtime_operations_degraded_and_cleanup_dirty(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "native")
    monkeypatch.setenv("XMUSE_RAY_GOD_MCP", "0")
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(
            runner_pids=[],
            mcp_pids=[],
            services={
                "codex_app_server": [21],
                "raylet": [31],
                "gcs_server": [32],
                "ray_worker": [33],
            },
        ),
    )
    monkeypatch.setattr(platform_runner, "_http_status", lambda url: None)

    summary = platform_runner.health_once(
        lanes_path,
        xmuse_root=tmp_path,
        mcp_port=8101,
        check_http=True,
        live_pids={21, 31, 32, 33},
    )

    operations = summary["operations"]
    assert operations["readiness"]["chat_api"]["status"] == "unreachable"
    assert operations["readiness"]["mcp"]["status"] == "unreachable"
    assert operations["readiness"]["runner"]["status"] == "missing"
    assert operations["readiness"]["ray_god_layer"]["status"] == "degraded"
    assert operations["readiness"]["codex_app_server"]["status"] == "orphaned"
    assert operations["cleanup"]["status"] == "dirty"
    assert [item["code"] for item in operations["cleanup"]["leftovers"]] == [
        "leftover_codex_app_server",
        "leftover_raylet",
        "leftover_gcs_server",
        "leftover_ray_worker",
    ]


def test_health_once_handles_missing_lane_projection(tmp_path: Path, monkeypatch) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )

    summary = platform_runner.health_once(
        lanes_path,
        xmuse_root=tmp_path,
        live_pids=set(),
    )

    assert summary["counts"]["live"] == 0
    assert summary["operations"]["durable_state"]["chat_db"]["exists"] is False


def test_health_once_includes_review_rework_alignment_summary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "semantic-rework",
                        "status": "reworking",
                        "retry_count": 1,
                        "review_fallback_reason": "reproduced_finding",
                    },
                    {
                        "feature_id": "historical-terminal-retry",
                        "status": "failed",
                        "retry_count": 2,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )

    summary = platform_runner.health_once(lanes_path, live_pids=set())

    alignment = summary["review_rework_alignment"]
    assert alignment["counts_by_category"]["semantic_rework"] == 1
    assert alignment["current_active_retry_or_rework"] == ["semantic-rework"]
    assert alignment["historical_terminal_retry_metadata"] == [
        "historical-terminal-retry"
    ]


def test_health_once_exposes_takeover_context_reason_breakdown(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    gate_report = tmp_path / "logs" / "gates" / "gate-failure" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(
        json.dumps({"passed": False, "blocking_passed": False}),
        encoding="utf-8",
    )
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "stale-worker",
                        "status": "dispatched",
                        "worker_pid": 123,
                        "dispatched_at": 100.0,
                    },
                    {
                        "feature_id": "gate-failure",
                        "status": "gate_failed",
                        "gate_report_ref": "logs/gates/gate-failure/report.json",
                    },
                    {
                        "feature_id": "review-infra-failed",
                        "status": "failed",
                        "failure_reason": "review_no_verdict",
                    },
                    {
                        "feature_id": "merge-conflict",
                        "status": "failed",
                        "merge_failure_reason": "merge_conflict_or_failed",
                        "merge_failure_detail": "CONFLICT (content): src/example.py",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )

    summary = platform_runner.health_once(
        lanes_path,
        now=1000.0,
        stale_after_s=300.0,
        live_pids=set(),
    )

    assert summary["groups"]["takeover_context_needed"] == [
        "stale-worker",
        "gate-failure",
        "review-infra-failed",
        "merge-conflict",
    ]
    assert summary["takeover_context"]["counts_by_reason"] == {
        "stale_worker": 1,
        "gate_failure": 1,
        "review_infra_failure": 1,
        "merge_conflict": 1,
    }
    assert summary["takeover_context"]["needed_lanes"] == [
        {
            "lane_id": "stale-worker",
            "status": "dispatched",
            "reason": "stale_worker",
            "review_rework_category": "not_review_related",
            "lane_context_ref": "logs/lane_context/stale-worker/latest.json",
        },
        {
            "lane_id": "gate-failure",
            "status": "gate_failed",
            "reason": "gate_failure",
            "review_rework_category": "gate_failure",
            "lane_context_ref": "logs/lane_context/gate-failure/latest.json",
        },
        {
            "lane_id": "review-infra-failed",
            "status": "failed",
            "reason": "review_infra_failure",
            "review_rework_category": "review_infra",
            "lane_context_ref": "logs/lane_context/review-infra-failed/latest.json",
        },
        {
            "lane_id": "merge-conflict",
            "status": "failed",
            "reason": "merge_conflict",
            "review_rework_category": "merge_conflict",
            "lane_context_ref": "logs/lane_context/merge-conflict/latest.json",
        },
    ]


def test_health_once_exposes_peer_delivery_visibility_read_only(
    tmp_path: Path,
    monkeypatch,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    original_payload = {
        "lanes": [
            {
                "feature_id": "configured-fallback",
                "status": "reviewed",
                "review_peer_id": "peer-reviewer",
                "peer_request_id": "req-fallback",
                "peer_routing_mode": "preferred",
                "peer_delivery_mode": "one_shot_fallback",
                "peer_degraded_reason": "receive_timeout",
            },
            {
                "feature_id": "required-failed",
                "status": "gate_failed",
                "failure_reason": "review_peer_delivery_failed",
                "review_peer_id": "peer-required",
                "peer_request_id": "req-required",
                "peer_routing_mode": "required",
                "peer_delivery_mode": "required_peer_failed",
                "peer_degraded_reason": "review_peer_no_verdict",
            },
            {
                "feature_id": "default-peer-success",
                "status": "reviewed",
                "peer_routing_mode": "preferred",
                "peer_delivery_mode": "configured_peer",
                "review_peer_defaulted": True,
            },
        ]
    }
    lanes_path.write_text(json.dumps(original_payload, indent=2), encoding="utf-8")
    monkeypatch.setattr(
        platform_runner,
        "discover_xmuse_runtime_processes",
        lambda: build_process_inventory(runner_pids=[], mcp_pids=[]),
    )

    summary = platform_runner.health_once(lanes_path, live_pids=set())

    assert summary["groups"]["degraded_fallback"] == [
        "configured-fallback",
        "required-failed",
    ]
    assert summary["peer_delivery"]["required_peer_failures"][0]["lane_id"] == (
        "required-failed"
    )
    assert summary["peer_delivery"]["default_review_peer_routing"] == [
        {
            "lane_id": "default-peer-success",
            "status": "reviewed",
            "peer_delivery_mode": "configured_peer",
            "peer_routing_mode": "preferred",
            "peer_degraded_reason": None,
        }
    ]
    assert json.loads(lanes_path.read_text(encoding="utf-8")) == original_payload


@pytest.mark.asyncio
async def test_runner_can_wire_memoryos_client(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    class FakeMemoryOSClient:
        def __init__(self, *, base_url: str) -> None:
            self.base_url = base_url

    class FakeOrchestrator:
        def __init__(
            self,
            *,
            lanes_path: Path,
            xmuse_root: Path,
            mcp_port: int,
            require_final_action_approval: bool,
            god_runtime: str | None = None,
            runner_id: str | None = None,
            memoryos_client=None,
            review_god_session_layer=None,
        ) -> None:
            captured["runner_id"] = runner_id
            captured["memoryos_client"] = memoryos_client
            captured["review_god_session_layer"] = review_god_session_layer
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(platform_runner, "MemoryOSClient", FakeMemoryOSClient)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        memoryos_url="http://memoryos.test",
    )

    memoryos_client = captured["memoryos_client"]
    assert isinstance(memoryos_client, FakeMemoryOSClient)
    assert memoryos_client.base_url == "http://memoryos.test"
    assert captured["review_god_session_layer"] is None


@pytest.mark.asyncio
async def test_runner_shutdown_closes_runtime_god_layers(monkeypatch, tmp_path: Path) -> None:
    closed: list[str] = []

    class FakeRayLayer:
        def __init__(self, *, name: str) -> None:
            self.name = name

        async def prewarm(self) -> None:
            return None

        async def shutdown(self) -> None:
            closed.append(self.name)

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        platform_runner,
        "_build_review_god_layer",
        lambda **kwargs: FakeRayLayer(name="review"),
    )
    monkeypatch.setattr(
        platform_runner,
        "_build_execution_god_layer",
        lambda **kwargs: FakeRayLayer(name="execution"),
    )
    monkeypatch.setattr(
        platform_runner,
        "_build_peer_god_layer",
        lambda **kwargs: FakeRayLayer(name="peer"),
    )
    monkeypatch.setattr(
        platform_runner,
        "_has_persistent_session_launcher",
        lambda launchers: True,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        persistent_review_god_enabled=True,
        persistent_execute_god_enabled=True,
        peer_chat_enabled=True,
    )

    assert closed == ["review", "execution", "peer"]


def test_candidate_lanes_filters_to_target_graph_and_includes_reworking() -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self._sm = _FakeStateMachine(
                [
                    {"feature_id": "lane-1", "status": "pending", "graph_id": "graph-a"},
                    {"feature_id": "lane-2", "status": "reworking", "graph_id": "graph-a"},
                    {"feature_id": "lane-3", "status": "pending", "graph_id": "graph-b"},
                    {"feature_id": "lane-4", "status": "exec_failed", "graph_id": "graph-a"},
                ]
            )

    lanes = platform_runner._candidate_lanes(
        FakeOrchestrator(),
        xmuse_root=Path("/tmp/no-recovery-artifacts"),
        graph_id="graph-a",
        resolution_id=None,
    )

    assert [lane["feature_id"] for lane in lanes] == ["lane-1", "lane-2"]


def test_candidate_lanes_waits_for_unmerged_dependencies() -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self._sm = _FakeStateMachine(
                [
                    {"feature_id": "lane-1", "status": "pending"},
                    {
                        "feature_id": "lane-2",
                        "status": "pending",
                        "depends_on": ["lane-1"],
                    },
                    {
                        "feature_id": "lane-3",
                        "status": "pending",
                        "depends_on": ["lane-done", "lane-merged", "lane-completed"],
                    },
                    {"feature_id": "lane-done", "status": "done"},
                    {"feature_id": "lane-merged", "status": "merged"},
                    {"feature_id": "lane-completed", "status": "completed"},
                ]
            )

    lanes = platform_runner._candidate_lanes(
        FakeOrchestrator(),
        xmuse_root=Path("/tmp/no-recovery-artifacts"),
        graph_id=None,
        resolution_id=None,
    )

    assert [lane["feature_id"] for lane in lanes] == ["lane-1", "lane-3"]


def test_candidate_lanes_excludes_non_retry_recovery_decision(tmp_path: Path) -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self._root = tmp_path
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-refactor",
                        "status": "reworking",
                        "graph_id": "graph-a",
                    },
                    {
                        "feature_id": "lane-retry",
                        "status": "reworking",
                        "graph_id": "graph-a",
                    },
                ]
            )

    _write_recovery_artifact(
        tmp_path,
        graph_id="graph-a",
        lane_id="lane-refactor",
        decision="refactor_required",
        retry_allowed=False,
    )
    _write_recovery_artifact(
        tmp_path,
        graph_id="graph-a",
        lane_id="lane-retry",
        decision="retry",
        retry_allowed=True,
    )
    orch = FakeOrchestrator()

    lanes = platform_runner._candidate_lanes(
        orch,
        xmuse_root=tmp_path,
        graph_id="graph-a",
        resolution_id=None,
    )

    assert [lane["feature_id"] for lane in lanes] == ["lane-retry"]
    assert lanes[0]["ready_set_parity"] == {
        "matches": False,
        "runner_source": "legacy_projection",
        "ready_set_source": "graph_native",
        "graph_id": "graph-a",
        "resolution_id": None,
        "legacy_candidate_lane_ids": ["lane-retry"],
        "ready_set_lane_ids": ["lane-refactor", "lane-retry"],
        "legacy_only_lane_ids": [],
        "ready_set_only_lane_ids": ["lane-refactor"],
    }
    blocked = orch._sm.get_lanes()[0]
    assert blocked["dispatch_blocked_by_recovery"] is True
    assert blocked["recovery_dispatch_block_reason"] == "refactor_required"
    assert blocked["recovery_source_authority"] == "lane_recovery_artifact"
    assert blocked["recovery_decision"]["retry_allowed"] is False
    assert "live_runner_recovery_enforcement_not_proven" in blocked["manual_gaps"]
    assert "ready_to_merge" in blocked["forbidden_claims"]
    assert "dispatch_attempt_id" not in blocked


def test_candidate_lanes_uses_explicit_recovery_root_without_orchestrator_private_root(
    tmp_path: Path,
) -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-refactor",
                        "status": "reworking",
                        "graph_id": "graph-a",
                    }
                ]
            )

    _write_recovery_artifact(
        tmp_path,
        graph_id="graph-a",
        lane_id="lane-refactor",
        decision="refactor_required",
        retry_allowed=False,
    )
    orch = FakeOrchestrator()

    lanes = platform_runner._candidate_lanes(
        orch,
        xmuse_root=tmp_path,
        graph_id="graph-a",
        resolution_id=None,
    )

    assert lanes == []
    blocked = orch._sm.get_lanes()[0]
    assert blocked["dispatch_blocked_by_recovery"] is True
    assert blocked["recovery_dispatch_block_reason"] == "refactor_required"
    assert blocked["recovery_source_authority"] == "lane_recovery_artifact"
    assert "live_runner_recovery_enforcement_not_proven" in blocked["manual_gaps"]


def test_candidate_lanes_excludes_invalid_recovery_artifact(tmp_path: Path) -> None:
    class FakeOrchestrator:
        def __init__(self) -> None:
            self._root = tmp_path
            self._sm = _FakeStateMachine(
                [
                    {
                        "feature_id": "lane-invalid-recovery",
                        "status": "reworking",
                        "graph_id": "graph-a",
                    }
                ]
            )

    recovery_path = lane_recovery_artifact_path(
        tmp_path,
        graph_id="graph-a",
        lane_id="lane-invalid-recovery",
    )
    recovery_path.parent.mkdir(parents=True, exist_ok=True)
    recovery_path.write_text(
        json.dumps({"schema_version": "xmuse.god_room_lane_recovery.v1"}) + "\n",
        encoding="utf-8",
    )
    orch = FakeOrchestrator()

    lanes = platform_runner._candidate_lanes(
        orch,
        xmuse_root=tmp_path,
        graph_id="graph-a",
        resolution_id=None,
    )

    assert lanes == []
    blocked = orch._sm.get_lanes()[0]
    assert blocked["dispatch_blocked_by_recovery"] is True
    assert blocked["recovery_dispatch_block_reason"] == "invalid_recovery_artifact"
    assert blocked["recovery_source_authority"] == "lane_recovery_artifact"
    assert "lane_recovery_artifact_invalid" in blocked["manual_gaps"]
    assert "ready_to_merge" in blocked["forbidden_claims"]
    assert "dispatch_attempt_id" not in blocked


def test_candidate_lanes_matches_graph_native_ready_set_parity(
    tmp_path: Path,
) -> None:
    lanes_path = tmp_path / "feature_lanes.json"
    graph_set = FeatureGraphSet(
        id="graph-set-b4",
        feature_plan=FeaturePlan(
            id="plan-b4",
            conversation_id="conv-1",
            resolution_id="res-1",
            version=7,
            features=[
                FeaturePlanFeature(
                    feature_id="schema",
                    title="Schema",
                    goal="Add graph-set schema.",
                    acceptance_criteria=["Schema validates."],
                    graph_id="graph-schema",
                ),
                FeaturePlanFeature(
                    feature_id="projection",
                    title="Projection",
                    goal="Project ready lanes.",
                    acceptance_criteria=["Projection is safe."],
                    dependencies=["schema"],
                    graph_id="graph-projection",
                ),
            ],
        ),
        graphs=[
            LaneGraph(
                id="graph-schema",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[LaneNode(feature_id="schema-root", prompt="Implement schema.")],
            ),
            LaneGraph(
                id="graph-projection",
                conversation_id="conv-1",
                resolution_id="res-1",
                version=7,
                lanes=[
                    LaneNode(
                        feature_id="projection-root",
                        prompt="Implement projection.",
                    ),
                    LaneNode(
                        feature_id="projection-dependent",
                        prompt="Wire dependents.",
                        depends_on=["projection-root"],
                    ),
                ],
            ),
        ],
    )

    initial_projected = project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )
    assert [lane["lane_local_id"] for lane in initial_projected] == ["projection-root"]

    class FakeOrchestrator:
        def __init__(self) -> None:
            self._sm = _FakeStateMachine(
                json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
            )

    initial_lanes = platform_runner._candidate_lanes(
        FakeOrchestrator(),
        xmuse_root=tmp_path,
        graph_id="graph-projection",
        resolution_id="res-1",
    )

    assert [lane["feature_id"] for lane in initial_projected] == [
        lane["feature_id"] for lane in initial_lanes
    ]
    assert initial_lanes[0]["ready_set_parity"] == {
        "matches": True,
        "runner_source": "legacy_projection",
        "ready_set_source": "graph_native",
        "graph_id": "graph-projection",
        "resolution_id": "res-1",
        "legacy_candidate_lane_ids": [initial_projected[0]["feature_id"]],
        "ready_set_lane_ids": [initial_projected[0]["feature_id"]],
        "legacy_only_lane_ids": [],
        "ready_set_only_lane_ids": [],
    }

    projected_doc = json.loads(lanes_path.read_text(encoding="utf-8"))
    projected_doc["lanes"][0]["status"] = "merged"
    lanes_path.write_text(json.dumps(projected_doc) + "\n", encoding="utf-8")

    dependent_projected = project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids={"schema"},
    )
    assert [lane["lane_local_id"] for lane in dependent_projected] == [
        "projection-dependent"
    ]

    dependent_lanes = platform_runner._candidate_lanes(
        FakeOrchestrator(),
        xmuse_root=tmp_path,
        graph_id="graph-projection",
        resolution_id="res-1",
    )

    assert [lane["feature_id"] for lane in dependent_projected] == [
        lane["feature_id"] for lane in dependent_lanes
    ]
    assert dependent_lanes[0]["ready_set_parity"] == {
        "matches": True,
        "runner_source": "legacy_projection",
        "ready_set_source": "graph_native",
        "graph_id": "graph-projection",
        "resolution_id": "res-1",
        "legacy_candidate_lane_ids": [dependent_projected[0]["feature_id"]],
        "ready_set_lane_ids": [dependent_projected[0]["feature_id"]],
        "legacy_only_lane_ids": [],
        "ready_set_only_lane_ids": [],
    }


def _write_recovery_artifact(
    base_dir: Path,
    *,
    graph_id: str,
    lane_id: str,
    decision: str,
    retry_allowed: bool,
) -> None:
    recovery_path = lane_recovery_artifact_path(
        base_dir,
        graph_id=graph_id,
        lane_id=lane_id,
    )
    recovery_path.parent.mkdir(parents=True, exist_ok=True)
    recovery_path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.god_room_lane_recovery.v1",
                "decision": {
                    "lane_id": lane_id,
                    "decision": decision,
                    "retry_allowed": retry_allowed,
                    "failure_class": "demo_grade_boundary",
                    "attempt": 2,
                    "next_action": (
                        "refactor or replace the failing lane boundary before retrying"
                    ),
                    "source_refs": ["pytest:runner-recovery-gate"],
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_repair_stale_dispatched_lanes_marks_dead_worker_exec_failed(
    monkeypatch,
    tmp_path: Path,
) -> None:
    class FakeStateMachine:
        def __init__(self) -> None:
            self._lanes = [
                {
                    "feature_id": "dead-worker",
                    "status": "dispatched",
                    "worker_pid": 123,
                    "dispatched_at": 100.0,
                    "graph_id": "graph-a",
                    "retry_count": 2,
                },
                {
                    "feature_id": "live-worker",
                    "status": "dispatched",
                    "worker_pid": 456,
                    "dispatched_at": 100.0,
                },
                {
                    "feature_id": "owned-finishing-worker",
                    "status": "dispatched",
                    "worker_pid": 789,
                    "dispatched_at": 100.0,
                },
                {
                    "feature_id": "lease-changed-before-write",
                    "status": "dispatched",
                    "worker_pid": 999,
                    "dispatched_at": 100.0,
                    "graph_id": "graph-a",
                },
                {
                    "feature_id": "dispatch-no-pid",
                    "status": "dispatched",
                    "dispatched_at": 100.0,
                    "graph_id": "graph-a",
                },
                {
                    "feature_id": "no-lease",
                    "status": "dispatched",
                    "dispatched_at": 100.0,
                },
            ]
            self.transitions: list[tuple[str, str, dict]] = []

        def get_lanes(self, status: str | None = None):
            if status is None:
                return list(self._lanes)
            return [lane for lane in self._lanes if lane.get("status") == status]

        def transition(self, lane_id: str, target_status: str, *, metadata: dict):
            return self.transition_if_metadata(
                lane_id,
                target_status,
                expected_metadata={"status": "dispatched"},
                metadata=metadata,
            )

        def transition_if_metadata(
            self,
            lane_id: str,
            target_status: str,
            *,
            expected_metadata: dict,
            metadata: dict,
        ):
            if lane_id == "lease-changed-before-write":
                for lane in self._lanes:
                    if lane["feature_id"] == lane_id:
                        lane["worker_pid"] = 1000
                        break
            self.transitions.append((lane_id, target_status, metadata))
            for lane in self._lanes:
                if lane["feature_id"] == lane_id:
                    if any(
                        lane.get(key) != expected
                        for key, expected in expected_metadata.items()
                    ):
                        self.transitions.pop()
                        return None
                    lane.update(metadata)
                    lane["status"] = target_status
                    return lane
            raise KeyError(lane_id)

        def update_metadata(self, lane_id: str, metadata: dict):
            for lane in self._lanes:
                if lane["feature_id"] == lane_id:
                    lane.update(metadata)
                    return lane
            raise KeyError(lane_id)

    class FakeOrchestrator:
        def __init__(self) -> None:
            self._sm = FakeStateMachine()

    orch = FakeOrchestrator()
    monkeypatch.setattr(platform_runner, "_live_pids", lambda: {456})

    platform_runner._repair_stale_dispatched_lanes(
        orch,
        xmuse_root=tmp_path,
        now=1000.0,
        stale_after_s=300.0,
        owned_lane_ids={"owned-finishing-worker"},
    )

    assert orch._sm.transitions == [
        (
            "dead-worker",
            "exec_failed",
            {
                "failure_reason": "stale_worker_lost",
                "stale_worker_pid": 123,
                "stale_repaired_at": 1000.0,
            },
        ),
        (
            "dispatch-no-pid",
            "exec_failed",
            {
                "failure_reason": "dispatch_no_worker_pid",
                "stale_worker_pid_missing": True,
                "stale_repaired_at": 1000.0,
            },
        ),
    ]
    assert orch._sm.get_lanes()[1]["status"] == "dispatched"
    assert orch._sm.get_lanes()[2]["status"] == "dispatched"
    assert orch._sm.get_lanes()[3]["status"] == "dispatched"
    assert orch._sm.get_lanes()[3]["worker_pid"] == 1000
    assert orch._sm.get_lanes()[4]["status"] == "exec_failed"
    assert orch._sm.get_lanes()[5]["status"] == "dispatched"
    repaired = orch._sm.get_lanes()[0]
    assert repaired["recovery_artifact_status"] == "written"
    assert repaired["recovery_artifact_source_authority"] == (
        "platform_runner_stale_repair"
    )
    assert repaired["recovery_artifact_ref"] == (
        "lane_graphs/graph-a.dead-worker.recovery.json"
    )
    recovery_artifact = json.loads(
        lane_recovery_artifact_path(
            tmp_path,
            graph_id="graph-a",
            lane_id="dead-worker",
        ).read_text(encoding="utf-8")
    )
    assert recovery_artifact["source_authority"] == "platform_runner_stale_repair"
    assert recovery_artifact["decision"] == {
        "attempt": 3,
        "decision": "suspended",
        "failure_class": "stale_worker_lost",
        "lane_id": "dead-worker",
        "next_action": (
            "inspect stale worker loss and record recovery or refactor evidence "
            "before retrying this lane"
        ),
        "retry_allowed": False,
        "source_refs": [
            "lane:dead-worker",
            "graph:graph-a",
            "stale_worker_pid:123",
            "platform_runner_stale_repair:1000.0",
        ],
        "suspend_reason": "stale_worker_lost",
    }
    assert not lane_recovery_artifact_path(
        tmp_path,
        graph_id="graph-a",
        lane_id="lease-changed-before-write",
    ).exists()
    pidless_repair = orch._sm.get_lanes()[4]
    assert pidless_repair["recovery_artifact_status"] == "written"
    pidless_artifact = json.loads(
        lane_recovery_artifact_path(
            tmp_path,
            graph_id="graph-a",
            lane_id="dispatch-no-pid",
        ).read_text(encoding="utf-8")
    )
    assert pidless_artifact["decision"]["failure_class"] == "dispatch_no_worker_pid"
    assert pidless_artifact["decision"]["retry_allowed"] is False
    assert pidless_artifact["decision"]["source_refs"] == [
        "lane:dispatch-no-pid",
        "graph:graph-a",
        "worker_pid:missing",
        "platform_runner_stale_repair:1000.0",
    ]

    repaired["status"] = "reworking"
    pidless_repair["status"] = "reworking"
    assert (
        platform_runner._candidate_lanes(
            orch,
            xmuse_root=tmp_path,
            graph_id="graph-a",
            resolution_id=None,
        )
        == []
    )
    assert repaired["dispatch_blocked_by_recovery"] is True
    assert repaired["recovery_dispatch_block_reason"] == "suspended"
    assert pidless_repair["dispatch_blocked_by_recovery"] is True
    assert pidless_repair["recovery_dispatch_block_reason"] == "suspended"


def test_coordinator_control_service_records_lifecycle_event(tmp_path: Path) -> None:
    service = platform_runner.CoordinatorControlService(
        xmuse_root=tmp_path,
        runner_id="runner-1",
        now=lambda: 123.0,
    )

    service.record_lifecycle(
        "started",
        details={"lanes_path": "xmuse/feature_lanes.json"},
    )

    records = [
        json.loads(line)
        for line in (tmp_path / "coordinator_incidents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records == [
        {
            "kind": "lifecycle",
            "component": "platform_runner",
            "operation": "started",
            "runner_id": "runner-1",
            "created_at": 123.0,
            "details": {"lanes_path": "xmuse/feature_lanes.json"},
        }
    ]


def test_coordinator_control_service_dead_letters_blueprint_failure(
    tmp_path: Path,
) -> None:
    service = platform_runner.CoordinatorControlService(
        xmuse_root=tmp_path,
        runner_id="runner-1",
        now=lambda: 456.0,
    )

    class FailingBlueprintService:
        def tick(self, *, worker_id: str):
            raise RuntimeError(f"boom from {worker_id}")

    assert service.drive_blueprint_automation(
        FailingBlueprintService(),
        worker_id="platform-runner",
    ) is None

    records = [
        json.loads(line)
        for line in (tmp_path / "coordinator_incidents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records == [
        {
            "kind": "dead_letter",
            "component": "blueprint_automation",
            "operation": "tick",
            "runner_id": "runner-1",
            "created_at": 456.0,
            "error_type": "RuntimeError",
            "error": "boom from platform-runner",
            "details": {"worker_id": "platform-runner"},
        }
    ]


def test_coordinator_control_service_degrades_optional_chat_failure(
    tmp_path: Path,
) -> None:
    service = platform_runner.CoordinatorControlService(
        xmuse_root=tmp_path,
        runner_id="runner-1",
        now=lambda: 789.0,
    )

    class FailingChatDriver:
        def tick(self):
            raise ValueError("chat unavailable")

    assert service.drive_chat(FailingChatDriver()) == []

    records = [
        json.loads(line)
        for line in (tmp_path / "coordinator_incidents.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert records == [
        {
            "kind": "degraded",
            "component": "chat_driver",
            "operation": "tick",
            "runner_id": "runner-1",
            "created_at": 789.0,
            "error_type": "ValueError",
            "error": "chat unavailable",
            "details": {},
        }
    ]
