import asyncio
import json
import subprocess
import time
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.agents.provider_session_binding_store import ProviderSessionBindingStore
from xmuse_core.chat.acceptance_spine import AcceptanceSpineStatus, AcceptanceSpineStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.peer_service import PeerChatService
from xmuse_core.chat.store import ChatStore
from xmuse_core.gates.models import GateReport
from xmuse_core.integrations.a2a_provider_client import A2AProviderTaskRequest
from xmuse_core.integrations.a2a_sdk_boundary import NormalizedA2ATaskResult
from xmuse_core.platform.agent_spawner import SpawnResult
from xmuse_core.platform.execution.a2a_review_verdicts import (
    build_a2a_platform_review_verdict_envelope,
)
from xmuse_core.platform.execution.review import infer_review_fallback
from xmuse_core.platform.messages import ExecuteRequest, ExecuteResponse, ReviewVerdict
from xmuse_core.platform.orchestrator import PlatformOrchestrator
from xmuse_core.platform.state_validation import StateValidationError
from xmuse_core.providers.adapters.base import ProviderFailureKind, ProviderInvocationResult
from xmuse_core.providers.adapters.fake import (
    FakeProviderHealthState,
    build_fake_provider_health_snapshot,
)
from xmuse_core.providers.goal_contract import WorkerResultStatus
from xmuse_core.providers.models import ProviderId, RiskTier, TaskCapability
from xmuse_core.providers.registry import build_default_provider_registry
from xmuse_core.providers.selection_record import ProviderSelectionRecordStore
from xmuse_core.providers.service import RunnerProviderService
from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    FeatureEvidenceBundle,
    FeatureGraphExecutionStatus,
    FeatureGraphExecutionStatusRecord,
    FeatureGraphPatchForwardGateResult,
    FeatureGraphPatchForwardPlan,
    FeatureGraphReviewCoordinatorAction,
    FeatureGraphTakeoverPlan,
    FeatureReviewVerdict,
    ProviderSessionBindingRecord,
    ProviderSessionBindingStatus,
    ReworkPacket,
)
from xmuse_core.structuring.verdict_store import ClarificationStore

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts/artifacts")


@pytest.fixture
def setup(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "pending", "prompt": "fix bug",
         "worktree": str(tmp_path)},
    ]}))
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    gates_dir = tmp_path / "logs" / "gates" / "lane-1"
    gates_dir.mkdir(parents=True)
    (gates_dir / "report.json").write_text(json.dumps({"passed": True}))
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    return tmp_path, lanes_path


@pytest.mark.asyncio
async def test_dispatch_lane_transitions_to_dispatched(setup):
    tmp_path, lanes_path = setup
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    mock_result = SpawnResult(exit_code=0, stdout="", stderr="")
    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=mock_result):
        with patch.object(orch, "_run_gate", new_callable=AsyncMock,
                          return_value=True):
            await orch.dispatch_lane("lane-1")
            await asyncio.sleep(0.1)

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] in ("dispatched", "executed", "gated", "gate_failed")


@pytest.mark.asyncio
async def test_dispatch_lane_records_cas_metadata(setup):
    tmp_path, lanes_path = setup
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock) as run_exec:
        await orch.dispatch_lane("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "dispatched"
    assert lane["dispatch_status_guard"] == "pending"
    assert lane["dispatch_projection_revision"] == 1
    assert lane["branch"] == "lane-1"
    assert lane["base_head_sha"] == "unknown"
    assert lane["runner_id"] == orch._runner_id
    assert isinstance(lane["dispatch_attempt_id"], str)
    assert lane["dispatch_attempt_id"].startswith("dispatch-lane-1-")
    run_exec.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_dispatch_lane_skips_when_graph_native_ready_membership_excludes_lane(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "fix bug",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            ready_lane_ids=["lane-other"],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock) as run_exec:
        await orch.dispatch_lane("lane-1")

    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "pending"
    run_exec.assert_not_awaited()


@pytest.mark.asyncio
async def test_dispatch_lane_allows_graph_native_ready_membership_for_matching_lane(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "fix bug",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            ready_lane_ids=["lane-1"],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock) as run_exec:
        await orch.dispatch_lane("lane-1")

    assert orch._sm.get_lane("lane-1")["status"] == "dispatched"
    run_exec.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_dispatch_lane_allows_graph_native_running_membership_for_matching_lane(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "fix bug",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-running",
            status=FeatureGraphExecutionStatus.RUNNING,
            ready_lane_ids=[],
            active_lane_ids=["lane-1"],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock) as run_exec:
        await orch.dispatch_lane("lane-1")

    assert orch._sm.get_lane("lane-1")["status"] == "dispatched"
    run_exec.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_dispatch_lane_allows_graph_native_reworking_for_matching_lane(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "reworking",
                        "prompt": "repair and retry",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reworking",
            status=FeatureGraphExecutionStatus.REWORKING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock) as run_exec:
        await orch.dispatch_lane("lane-1")

    assert orch._sm.get_lane("lane-1")["status"] == "dispatched"
    run_exec.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_dispatch_lane_allows_graph_native_reworking_with_stale_pending_projection(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "repair and retry",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reworking",
            status=FeatureGraphExecutionStatus.REWORKING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock) as run_exec:
        await orch.dispatch_lane("lane-1")

    assert orch._sm.get_lane("lane-1")["status"] == "dispatched"
    run_exec.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_dispatch_lane_initializes_missing_isolated_worktree(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-no-worktree", "status": "pending", "prompt": "fix bug"},
    ]}))
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "god_prompts").mkdir(parents=True)
    (tmp_path / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "god_prompts" / "review_god.md").write_text("review")
    isolated_worktree = tmp_path / "lane-no-worktree"
    spawn_worktrees: list[Path] = []

    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fake_spawn(*, god_config, lane_id, prompt, worktree):
        spawn_worktrees.append(worktree)
        return SpawnResult(exit_code=-1, stdout="", stderr="stop before gate")

    with patch("xmuse_core.platform.orchestrator.WORKTREE_BASE", tmp_path):
        with patch("xmuse_core.platform.orchestrator._git_output", return_value="base-sha"):
            with patch.object(orch, "_create_or_reuse_worktree") as create_worktree:
                create_worktree.side_effect = lambda *, worktree, branch: worktree.mkdir()
                with patch.object(orch._spawner, "spawn", side_effect=fake_spawn):
                    await orch.dispatch_lane("lane-no-worktree")

    lane = orch._sm.get_lane("lane-no-worktree")
    assert lane["worktree"] == str(isolated_worktree)
    assert lane["branch"] == "lane-no-worktree"
    assert lane["base_head_sha"] == "base-sha"
    assert spawn_worktrees == [isolated_worktree]
    create_worktree.assert_called_once_with(
        worktree=isolated_worktree,
        branch="lane-no-worktree",
    )


def test_create_or_reuse_worktree_uses_source_repo_root_when_state_root_is_not_repo(
    tmp_path,
):
    source_repo = tmp_path / "source-repo"
    source_repo.mkdir()
    subprocess.run(["git", "init"], cwd=source_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "xmuse@example.invalid"],
        cwd=source_repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "xmuse"],
        cwd=source_repo,
        check=True,
    )
    (source_repo / "README.md").write_text("source\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=source_repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "initial"],
        cwd=source_repo,
        check=True,
        capture_output=True,
    )
    state_root = tmp_path / "runtime-state"
    state_root.mkdir()
    lanes_path = state_root / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}), encoding="utf-8")
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=state_root,
        mcp_port=9999,
    )
    orch._repo_root = source_repo
    lane_worktree = tmp_path / "lane-worktree"

    orch._create_or_reuse_worktree(worktree=lane_worktree, branch="lane-source-root")

    assert lane_worktree.exists()
    assert (
        subprocess.run(
            ["git", "-C", str(lane_worktree), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        == "true"
    )


@pytest.mark.asyncio
async def test_dispatch_lane_creates_missing_projected_worktree_path(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    projected_worktree = tmp_path / "projected-lane-worktree"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-projected-worktree",
            "status": "pending",
            "prompt": "fix bug",
            "worktree": str(projected_worktree),
        },
    ]}))
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "god_prompts").mkdir(parents=True)
    (tmp_path / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "god_prompts" / "review_god.md").write_text("review")
    spawn_worktrees: list[Path] = []

    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fake_spawn(*, god_config, lane_id, prompt, worktree):
        spawn_worktrees.append(worktree)
        return SpawnResult(exit_code=-1, stdout="", stderr="stop before gate")

    with patch("xmuse_core.platform.orchestrator._git_output", return_value="base-sha"):
        with patch.object(orch, "_create_or_reuse_worktree") as create_worktree:
            create_worktree.side_effect = lambda *, worktree, branch: worktree.mkdir()
            with patch.object(orch._spawner, "spawn", side_effect=fake_spawn):
                await orch.dispatch_lane("lane-projected-worktree")

    lane = orch._sm.get_lane("lane-projected-worktree")
    assert lane["worktree"] == str(projected_worktree)
    assert lane["branch"] == "lane-projected-worktree"
    assert lane["base_head_sha"] == "unknown"
    assert spawn_worktrees == [projected_worktree]
    create_worktree.assert_called_once_with(
        worktree=projected_worktree,
        branch="lane-projected-worktree",
    )


@pytest.mark.asyncio
async def test_dispatch_lane_recreates_empty_projected_worktree_path(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    projected_worktree = tmp_path / "empty-projected-lane-worktree"
    projected_worktree.mkdir()
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-empty-projected-worktree",
            "status": "pending",
            "prompt": "fix bug",
            "worktree": str(projected_worktree),
        },
    ]}))
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "god_prompts").mkdir(parents=True)
    (tmp_path / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "god_prompts" / "review_god.md").write_text("review")
    spawn_worktrees: list[Path] = []

    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fake_spawn(*, god_config, lane_id, prompt, worktree):
        spawn_worktrees.append(worktree)
        return SpawnResult(exit_code=-1, stdout="", stderr="stop before gate")

    with patch("xmuse_core.platform.orchestrator._git_output", return_value="base-sha"):
        with patch.object(orch, "_create_or_reuse_worktree") as create_worktree:
            create_worktree.side_effect = lambda *, worktree, branch: worktree.mkdir()
            with patch.object(orch._spawner, "spawn", side_effect=fake_spawn):
                await orch.dispatch_lane("lane-empty-projected-worktree")

    lane = orch._sm.get_lane("lane-empty-projected-worktree")
    assert lane["worktree"] == str(projected_worktree)
    assert lane["branch"] == "lane-empty-projected-worktree"
    assert lane["base_head_sha"] == "unknown"
    assert spawn_worktrees == [projected_worktree]
    create_worktree.assert_called_once_with(
        worktree=projected_worktree,
        branch="lane-empty-projected-worktree",
    )


@pytest.mark.asyncio
async def test_dispatch_lane_records_branch_for_existing_non_git_worktree(setup):
    tmp_path, lanes_path = setup
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fake_spawn(*, god_config, lane_id, prompt, worktree):
        return SpawnResult(exit_code=1, stdout="", stderr="stop before gate")

    with patch("xmuse_core.platform.orchestrator._git_output") as git_output:
        with patch.object(orch, "_create_or_reuse_worktree") as create_worktree:
            with patch.object(orch._spawner, "spawn", side_effect=fake_spawn):
                await orch.dispatch_lane("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["worktree"] == str(tmp_path)
    assert lane["branch"] == "lane-1"
    assert lane["base_head_sha"] == "unknown"
    git_output.assert_not_called()
    create_worktree.assert_not_called()


@pytest.mark.asyncio
async def test_dispatch_lane_attaches_existing_detached_git_worktree_to_lane_branch(
    tmp_path,
):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "xmuse@example.invalid"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "xmuse"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "base"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        ["git", "checkout", "--detach", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-existing-detached",
            "status": "pending",
            "prompt": "fix bug",
            "worktree": str(repo),
        },
    ]}))
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fake_spawn(*, god_config, lane_id, prompt, worktree):
        return SpawnResult(exit_code=1, stdout="", stderr="stop before gate")

    with patch.object(orch, "_create_or_reuse_worktree") as create_worktree:
        with patch.object(orch._spawner, "spawn", side_effect=fake_spawn):
            await orch.dispatch_lane("lane-existing-detached")

    lane = orch._sm.get_lane("lane-existing-detached")
    assert lane["worktree"] == str(repo)
    assert lane["branch"] == "lane-existing-detached"
    assert lane["base_head_sha"] == base_head
    current_branch = subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert current_branch == "lane-existing-detached"
    create_worktree.assert_not_called()


@pytest.mark.asyncio
async def test_execution_god_timeout_marks_exec_failed(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "dispatched", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    timeout_result = SpawnResult(exit_code=-1, stdout="", stderr="timeout",
                                 timed_out=True)
    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=timeout_result):
        await orch._run_execution_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "exec_failed"


@pytest.mark.asyncio
async def test_execution_transport_receives_provider_invocation(setup):
    tmp_path, lanes_path = setup
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    captured: dict[str, object] = {}

    async def fake_send_execute(req):
        captured["provider_invocation"] = req.provider_invocation
        return ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="failed",
            timed_out=False,
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        await orch.dispatch_lane("lane-1")

    invocation = captured["provider_invocation"]
    assert invocation is not None
    assert invocation.task_type is TaskCapability.LANE_COORDINATION
    assert invocation.provider_profile_ref == "codex.default"
    lane = orch._sm.get_lane("lane-1")
    assert lane["provider_profile_ref"] == "codex.default"


@pytest.mark.asyncio
async def test_execution_god_tolerates_child_writeback_already_gated(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "run package boundary proof",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    async def fake_send_execute(req):
        orch._sm.transition(
            "lane-1",
            "executed",
            metadata={
                "tests_run": ["uv run pytest tests/xmuse/test_package_boundaries.py -q"],
                "changed_files": [],
            },
        )
        orch._sm.transition("lane-1", "gated", metadata={"gate_passed": True})
        return ExecuteResponse(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            provider_result=ProviderInvocationResult(
                request_id=req.provider_invocation.request_id,
                provider_id=req.provider_invocation.provider_id,
                profile_id=req.provider_invocation.profile_id,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=[],
            ),
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        with patch.object(orch, "_on_lane_executed", new_callable=AsyncMock) as on_executed:
            await orch._run_execution_god("lane-1")

    on_executed.assert_not_called()
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gated"
    assert lane["gate_passed"] is True
    assert lane["parent_god_role"] == "execute"
    assert lane["worker_kind"] == "temporary_child_worker"


@pytest.mark.asyncio
async def test_execution_transport_prefers_ready_low_cost_worker_and_records_selection(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-worker-ready",
                        "status": "pending",
                        "prompt": "Implement the bounded lane.",
                        "worktree": str(tmp_path),
                        "risk": "low",
                        "task_type": "bounded_code_writing",
                        "bounded_context": True,
                        "well_specified": True,
                    }
                ]
            }
        )
    )
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    registry = build_default_provider_registry()
    provider_service = RunnerProviderService(
        selection_record_store=ProviderSelectionRecordStore.from_xmuse_root(tmp_path),
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
    captured: dict[str, object] = {}

    async def fake_send_execute(req):
        captured["provider_invocation"] = req.provider_invocation
        return ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="failed",
            timed_out=False,
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        await orch.dispatch_lane("lane-worker-ready")

    invocation = captured["provider_invocation"]
    assert invocation is not None
    assert invocation.task_type is TaskCapability.BOUNDED_CODE_WRITING
    assert invocation.provider_profile_ref == "opencode.deepseek_flash_worker"
    lane = orch._sm.get_lane("lane-worker-ready")
    assert lane["provider_profile_ref"] == "opencode.deepseek_flash_worker"
    records = ProviderSelectionRecordStore.from_xmuse_root(tmp_path).list_records(
        lane_id="lane-worker-ready"
    )
    assert len(records) == 1
    assert records[0].provider_profile_ref == "opencode.deepseek_flash_worker"
    assert records[0].task_type is TaskCapability.BOUNDED_CODE_WRITING
    assert records[0].lane_risk is RiskTier.LOW
    assert records[0].fallback_cause is None
    assert records[0].health_failure_kind is None
    assert records[0].source_authority == "provider_policy"


@pytest.mark.asyncio
async def test_execution_transport_falls_back_to_codex_worker_when_low_cost_worker_unavailable(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-worker-fallback",
                        "status": "pending",
                        "prompt": "Implement the bounded lane.",
                        "worktree": str(tmp_path),
                        "risk": "low",
                        "task_type": "bounded_code_writing",
                        "bounded_context": True,
                        "well_specified": True,
                    }
                ]
            }
        )
    )
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    registry = build_default_provider_registry()
    provider_service = RunnerProviderService(
        selection_record_store=ProviderSelectionRecordStore.from_xmuse_root(tmp_path),
        health_by_profile={
            "opencode.deepseek_flash_worker": build_fake_provider_health_snapshot(
                registry.get("opencode.deepseek_flash_worker"),
                state=FakeProviderHealthState.UNAVAILABLE,
            )
        },
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        provider_service=provider_service,
    )
    captured: dict[str, object] = {}

    async def fake_send_execute(req):
        captured["provider_invocation"] = req.provider_invocation
        return ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="failed",
            timed_out=False,
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        await orch.dispatch_lane("lane-worker-fallback")

    invocation = captured["provider_invocation"]
    assert invocation is not None
    assert invocation.task_type is TaskCapability.BOUNDED_CODE_WRITING
    assert invocation.provider_profile_ref == "codex.worker"
    lane = orch._sm.get_lane("lane-worker-fallback")
    assert lane["provider_profile_ref"] == "codex.worker"
    records = ProviderSelectionRecordStore.from_xmuse_root(tmp_path).list_records(
        lane_id="lane-worker-fallback"
    )
    assert len(records) == 1
    assert records[0].provider_profile_ref == "codex.worker"
    assert records[0].task_type is TaskCapability.BOUNDED_CODE_WRITING
    assert records[0].lane_risk is RiskTier.LOW
    assert records[0].fallback_cause == "unavailable"
    assert records[0].health_failure_kind == "unavailable"
    assert records[0].source_authority == "provider_policy"


@pytest.mark.asyncio
async def test_on_lane_reviewed_transitions_to_merged(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "reviewed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.on_lane_reviewed("lane-1")
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "merged"


@pytest.mark.asyncio
async def test_on_lane_reviewed_clears_advisory_stale_merge_metadata(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    async def merge_with_stale_metadata(lane_id: str, _worktree: Path) -> bool:
        orch._sm.update_metadata(
            lane_id,
            {
                "stale_against_current_target_head": True,
                "current_target_head": "current-head",
                "stale_base_head_sha": "old-base",
            },
        )
        return True

    with patch.object(orch, "_auto_merge", side_effect=merge_with_stale_metadata):
        await orch.on_lane_reviewed("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "merged"
    assert lane.get("stale_against_current_target_head") is None
    assert lane.get("current_target_head") is None
    assert lane.get("stale_base_head_sha") is None


@pytest.mark.asyncio
async def test_on_lane_reviewed_preserves_merge_context_failure(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "reviewed", "prompt": "fix"},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    await orch.on_lane_reviewed("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "failed"
    assert lane["failure_reason"] == "merge_context_missing"
    assert "branch" in lane["merge_failure_detail"]


@pytest.mark.asyncio
async def test_on_lane_reviewed_reworks_merge_conflict_with_context(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "branch": "lane-1",
            "worktree": str(tmp_path / "lane-1"),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fail_with_conflict(lane_id: str, worktree: Path) -> bool:
        orch._sm.update_metadata(
            lane_id,
            {
                "merge_failure_reason": "merge_conflict_or_failed",
                "merge_failure_reworkable": True,
                "merge_failure_detail": "CONFLICT (content): file.py",
            },
        )
        return False

    with patch.object(orch, "_auto_merge", side_effect=fail_with_conflict):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch.on_lane_reviewed("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["retry_count"] == 1
    assert lane["merge_failure_reason"] == "merge_conflict_or_failed"
    assert "CONFLICT" in lane["merge_failure_detail"]
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_on_lane_reviewed_does_not_rework_non_reworkable_merge_failure(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "branch": "lane-1",
            "worktree": str(tmp_path / "lane-1"),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fail_without_conflict(lane_id: str, worktree: Path) -> bool:
        orch._sm.update_metadata(
            lane_id,
            {
                "merge_failure_reason": "merge_failed",
                "merge_failure_reworkable": False,
                "merge_failure_detail": "fatal: refusing to merge unrelated histories",
            },
        )
        return False

    with patch.object(orch, "_auto_merge", side_effect=fail_without_conflict):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch.on_lane_reviewed("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "failed"
    assert lane["failure_reason"] == "merge_failed"
    assert lane["merge_failure_reworkable"] is False
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_execution_god_writes_lane_context_bundle(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reworking",
            "prompt": "fix",
            "retry_count": 1,
            "review_decision": "rework",
            "review_summary": "Fix the failed assertion.",
            "worktree": str(tmp_path),
            "branch": "lane-1",
            "depends_on": ["base-lane"],
        },
        {
            "feature_id": "base-lane",
            "status": "merged",
            "prompt": "base",
            "worktree": str(tmp_path),
        },
        {
            "feature_id": "dependent-lane",
            "status": "pending",
            "prompt": "dependent",
            "worktree": str(tmp_path),
            "depends_on": ["lane-1"],
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        new_callable=AsyncMock,
    ) as run_execution:
        await orch._run_execution_god("lane-1")

    bundle_path = tmp_path / "logs" / "lane_context" / "lane-1" / "latest.json"
    assert bundle_path.exists()
    payload = json.loads(bundle_path.read_text())
    assert payload["lane_id"] == "lane-1"
    assert "Fix the failed assertion." in payload["retry_context"]
    assert payload["dependency_states"] == {
        "depends_on": [
            {"lane_id": "base-lane", "status": "merged", "found": True},
        ],
        "dependents": [
            {"lane_id": "dependent-lane", "status": "pending"},
        ],
    }
    run_execution.assert_awaited_once()
    prompt = run_execution.await_args.kwargs["prompt"]
    assert "## Prior Attempt Context" in prompt
    assert "- dependency base-lane: merged" in prompt
    assert "- dependent dependent-lane: pending" in prompt


@pytest.mark.asyncio
async def test_run_execution_god_passes_compatible_provider_session_binding(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
    ]}))
    binding_store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = binding_store.upsert_active(
        _provider_session_binding(worktree=str(tmp_path))
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        new_callable=AsyncMock,
    ) as run_execution:
        await orch._run_execution_god("lane-1")

    assert run_execution.await_args.kwargs["provider_session_binding"] == binding


@pytest.mark.asyncio
async def test_run_execution_god_prefers_provider_binding_resume_over_persistent_session(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "conversation_id": "conv-1",
            "graph_id": "graph-feature-a",
            "feature_plan_feature_id": "feature-alpha",
            "provider_session_binding_god_session_id": "god-worker-demo",
            "execute_peer_id": "execute-peer-1",
        },
    ]}))
    binding_store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = binding_store.upsert_active(_provider_session_binding(worktree=str(tmp_path)))

    class _RecordingPersistentLayer:
        def __init__(self) -> None:
            self.ensure_calls: list[dict[str, object]] = []
            self.send_calls: list[dict[str, object]] = []

        async def ensure_conversation_session(self, **_kwargs):
            self.ensure_calls.append(dict(_kwargs))
            return GodSessionRecord(
                god_session_id="god-execute-1",
                role="execute",
                agent_name="execution-god",
                runtime="codex",
                session_address="@execute",
                session_inbox_id="inbox-execute",
                conversation_id="conv-1",
                participant_id="execute-peer-1",
            )

        async def send_message(
            self,
            god_session_id,
            message_type,
            prompt,
            context,
            request_id=None,
        ):
            self.send_calls.append(
                {
                    "god_session_id": god_session_id,
                    "message_type": message_type,
                    "prompt": prompt,
                    "context": context,
                    "request_id": request_id,
                }
            )

        async def receive_message(self, *_args, **_kwargs):
            return StdoutMessage(
                type="result",
                artifacts={
                    "execute_result": {
                        "exit_code": 0,
                    }
                },
            )

        async def abort_session(self, *_args, **_kwargs):
            return None

    layer = _RecordingPersistentLayer()

    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        persistent_execute_enabled=True,
        persistent_execute_session_layer=layer,
        provider_session_binding_store=binding_store,
    )

    sent_requests: list[ExecuteRequest] = []

    async def fake_send_execute(req):
        sent_requests.append(req)
        assert req.provider_invocation is not None
        assert req.provider_session_binding == binding
        return ExecuteResponse(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            provider_result=ProviderInvocationResult(
                request_id=req.provider_invocation.request_id,
                provider_id=req.provider_invocation.provider_id,
                profile_id=req.provider_invocation.profile_id,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=[],
            ),
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        with patch.object(orch, "_on_lane_executed", new_callable=AsyncMock) as on_executed:
            await orch._run_execution_god("lane-1")

    on_executed.assert_awaited_once_with("lane-1")
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "executed"
    assert sent_requests != []
    assert layer.ensure_calls == []
    assert layer.send_calls == []
    assert lane.get("persistent_execute_identity") is None


@pytest.mark.asyncio
async def test_run_execution_god_passes_provider_session_binding_writer_context(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "conversation_id": "conv-1",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        new_callable=AsyncMock,
    ) as run_execution:
        await orch._run_execution_god("lane-1")

    kwargs = run_execution.await_args.kwargs
    assert kwargs["provider_session_binding_writer"] is orch._provider_session_binding_store
    assert kwargs["provider_session_binding_god_session_id"] == "god-worker-demo"
    assert kwargs["provider_session_binding_role"] == "feature_worker"
    assert kwargs["provider_session_binding_conversation_id"] == "conv-1"
    assert kwargs["provider_session_binding_feature_graph_id"] == "graph-feature-a"
    assert isinstance(kwargs["provider_session_binding_prompt_fingerprint"], str)


@pytest.mark.asyncio
async def test_run_execution_god_disables_persistent_route_for_provider_without_persistent_execute(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-worker-ready",
            "status": "dispatched",
            "prompt": "Implement the bounded lane.",
            "worktree": str(tmp_path),
            "conversation_id": "conv-1",
            "graph_id": "graph-feature-a",
            "feature_plan_feature_id": "feature-alpha",
            "execute_peer_id": "execute-peer-1",
            "risk": "low",
            "task_type": "bounded_code_writing",
            "bounded_context": True,
            "well_specified": True,
        },
    ]}))
    (tmp_path / "error_knowledge.json").write_text(json.dumps({"entries": []}))
    (tmp_path / "xmuse" / "god_prompts").mkdir(parents=True)
    (tmp_path / "xmuse" / "god_prompts" / "execution_god.md").write_text("exec")
    (tmp_path / "xmuse" / "god_prompts" / "review_god.md").write_text("review")
    registry = build_default_provider_registry()
    provider_service = RunnerProviderService(
        selection_record_store=ProviderSelectionRecordStore.from_xmuse_root(tmp_path),
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
        persistent_execute_enabled=True,
        persistent_execute_session_layer=object(),
    )

    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        new_callable=AsyncMock,
    ) as run_execution:
        await orch._run_execution_god("lane-worker-ready")

    kwargs = run_execution.await_args.kwargs
    assert kwargs["provider_invocation"] is not None
    assert kwargs["provider_invocation"].provider_id is ProviderId.OPENCODE
    assert kwargs["provider_session_binding"] is None
    assert kwargs["persistent_execute_enabled"] is False
    assert kwargs["persistent_session_layer"] is None


@pytest.mark.asyncio
async def test_run_execution_god_records_provider_binding_degradation_in_graph_status(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_set_id": "graph-set-1",
            "graph_id": "graph-feature-a",
        },
    ]}))
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-running",
            status=FeatureGraphExecutionStatus.RUNNING,
            ready_lane_ids=[],
            active_lane_ids=["lane-1"],
            updated_at="2026-06-03T03:00:00Z",
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    async def fake_run_execution(**_kwargs):
        _kwargs["record_provider_session_binding_degradation"](
            binding_id="provider_session_binding:psb-worker-a:v1",
            reason="upsert_failed",
            failure="provider store write failed",
        )

    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        side_effect=fake_run_execution,
    ):
        await orch._run_execution_god("lane-1")

    status = status_store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )
    assert len(status.provider_session_binding_degradations) == 1
    degradation = status.provider_session_binding_degradations[0]
    assert degradation.binding_id == "provider_session_binding:psb-worker-a:v1"
    assert degradation.reason == "upsert_failed"
    assert degradation.failure == "provider store write failed"
    assert degradation.evidence_refs == [
        "runtime:execution_god:lane=lane-1",
        "provider_session_binding:psb-worker-a:v1",
    ]
    events = status_store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )
    assert [event.event_type for event in events] == [
        "feature_graph_status.provider_session_binding_degraded"
    ]


@pytest.mark.asyncio
async def test_run_execution_god_does_not_replay_projection_degradation_bridge_by_default(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_set_id": "graph-set-1",
            "graph_id": "graph-feature-a",
        },
    ]}))
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-running",
            status=FeatureGraphExecutionStatus.RUNNING,
            ready_lane_ids=[],
            active_lane_ids=["lane-1"],
            updated_at="2026-06-03T03:00:00Z",
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    async def fake_run_execution(**_kwargs):
        orch._sm.update_metadata(
            "lane-1",
            {
                "provider_session_binding_degraded": True,
                "provider_session_binding_degraded_reason": "upsert_failed",
                "provider_session_binding_id": "provider_session_binding:psb-worker-a:v1",
                "provider_session_binding_failure": "projection failure detail",
            },
        )

    with patch(
        "xmuse_core.platform.orchestrator.execution_executor.run_execution_god",
        side_effect=fake_run_execution,
    ):
        await orch._run_execution_god("lane-1")

    status = status_store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    )
    assert status.provider_session_binding_degradations == []
    assert status_store.list_events(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ) == []


def test_reconcile_provider_binding_degradation_scans_lanes_into_graph_status(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "executed",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "provider_session_binding_degraded": True,
                        "provider_session_binding_degraded_reason": "upsert_failed",
                        "provider_session_binding_id": (
                            "provider_session_binding:psb-worker-a:v1"
                        ),
                        "provider_session_binding_failure": "provider store write failed",
                    }
                ]
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-running",
            status=FeatureGraphExecutionStatus.RUNNING,
            ready_lane_ids=[],
            active_lane_ids=["lane-1"],
            updated_at="2026-06-03T03:00:00Z",
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    outcomes = orch.reconcile_feature_graph_provider_binding_degradations(
        updated_at="2026-06-03T03:12:00Z",
        compatibility_bridge_enabled=True,
    )

    assert len(outcomes) == 1
    assert outcomes[0].evidence.reason == "upsert_failed"
    assert status_store.get(
        graph_set_id="graph-set-1",
        feature_graph_id="graph-feature-a",
    ).provider_session_binding_degradations == [outcomes[0].evidence]
    assert lanes_path.read_text(encoding="utf-8") == before_projection


@pytest.mark.asyncio
async def test_run_execution_god_upserts_provider_session_binding_store(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "conversation_id": "conv-1",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    async def fake_send_execute(req):
        assert req.provider_invocation is not None
        return ExecuteResponse(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            provider_result=ProviderInvocationResult(
                request_id=req.provider_invocation.request_id,
                provider_id=req.provider_invocation.provider_id,
                profile_id=req.provider_invocation.profile_id,
                status=WorkerResultStatus.COMPLETED,
                provider_session_id=(
                    "codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
                ),
                evidence_refs=[],
            ),
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        with patch.object(orch, "_on_lane_executed", new_callable=AsyncMock):
            await orch._run_execution_god("lane-1")

    binding = orch._provider_session_binding_store.find_active(
        god_session_id="god-worker-demo",
        provider="codex",
        kind="exec",
    )
    assert binding.provider_session_id == (
        "codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    )
    assert binding.conversation_id == "conv-1"
    assert binding.feature_graph_id == "graph-feature-a"
    assert binding.model == "gpt-5.4"
    assert binding.prompt_fingerprint is not None


@pytest.mark.asyncio
async def test_run_execution_god_tags_existing_binding_when_writeback_fails_after_successful_resume(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "conversation_id": "conv-1",
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
    ]}))
    binding_store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = binding_store.upsert_active(_provider_session_binding(worktree=str(tmp_path)))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        provider_session_binding_store=binding_store,
    )

    async def fake_send_execute(req):
        assert req.provider_invocation is not None
        assert req.provider_session_binding == binding
        return ExecuteResponse(
            exit_code=0,
            stdout="",
            stderr="",
            timed_out=False,
            provider_result=ProviderInvocationResult(
                request_id=req.provider_invocation.request_id,
                provider_id=req.provider_invocation.provider_id,
                profile_id=req.provider_invocation.profile_id,
                status=WorkerResultStatus.COMPLETED,
                provider_session_id=(
                    "codex-session-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
                ),
                evidence_refs=[],
            ),
        )

    with patch.object(
        binding_store,
        "upsert_active",
        side_effect=RuntimeError("provider store write failed"),
    ):
        with patch.object(orch._transport, "send_execute", new=fake_send_execute):
            with patch.object(orch, "_on_lane_executed", new_callable=AsyncMock) as on_executed:
                await orch._run_execution_god("lane-1")

    on_executed.assert_awaited_once_with("lane-1")
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "executed"
    assert lane["provider_session_binding_degraded"] is True
    assert lane["provider_session_binding_degraded_reason"] == "upsert_failed"
    assert lane["provider_session_binding_id"] == binding.binding_id
    assert lane["provider_session_binding_failure"] == "provider store write failed"
    assert binding_store.find_active(
        god_session_id="god-worker-demo",
        provider="codex",
        kind="exec",
    ) == binding


@pytest.mark.asyncio
async def test_run_execution_god_marks_compatible_binding_stale_on_provider_resume_failure(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "conversation_id": "conv-1",
            "graph_id": "graph-feature-a",
            "feature_plan_feature_id": "feature-alpha",
            "provider_session_binding_god_session_id": "god-worker-demo",
            "execute_peer_id": "execute-peer-1",
        },
    ]}))
    binding_store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding_store.upsert_active(_provider_session_binding(worktree=str(tmp_path)))

    class _RecordingPersistentLayer:
        def __init__(self) -> None:
            self.ensure_calls: list[dict[str, object]] = []

        async def ensure_conversation_session(self, **_kwargs):
            self.ensure_calls.append(dict(_kwargs))
            return GodSessionRecord(
                god_session_id="god-execute-1",
                role="execute",
                agent_name="execution-god",
                runtime="codex",
                session_address="@execute",
                session_inbox_id="inbox-execute",
                conversation_id="conv-1",
                participant_id="execute-peer-1",
            )

        async def send_message(self, *_args, **_kwargs):
            return None

        async def receive_message(self, *_args, **_kwargs):
            return StdoutMessage(
                type="result",
                artifacts={
                    "execute_result": {
                        "exit_code": 0,
                    }
                },
            )

        async def abort_session(self, *_args, **_kwargs):
            return None

    layer = _RecordingPersistentLayer()

    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        provider_session_binding_store=binding_store,
        persistent_execute_enabled=True,
        persistent_execute_session_layer=layer,
    )

    async def fake_send_execute(req):
        assert req.provider_invocation is not None
        assert req.provider_session_binding is not None
        return ExecuteResponse(
            exit_code=1,
            stdout="",
            stderr="stale resume",
            timed_out=False,
            provider_result=ProviderInvocationResult(
                request_id=req.provider_invocation.request_id,
                provider_id=req.provider_invocation.provider_id,
                profile_id=req.provider_invocation.profile_id,
                status=WorkerResultStatus.FAILED,
                failure_kind=ProviderFailureKind.STALE_REQUEST,
                evidence_refs=[],
            ),
        )

    with patch.object(orch._transport, "send_execute", new=fake_send_execute):
        with patch.object(orch, "_on_lane_executed", new_callable=AsyncMock) as on_executed:
            await orch._run_execution_god("lane-1")

    on_executed.assert_not_awaited()
    stale = binding_store.get("psb-codex-demo")
    assert stale.status is ProviderSessionBindingStatus.STALE
    assert stale.failure_reason == "stale_request"
    assert layer.ensure_calls == []
    with pytest.raises(KeyError, match="active provider session binding not found"):
        binding_store.find_active(
            god_session_id="god-worker-demo",
            provider="codex",
            kind="exec",
        )
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "stale_request"


def test_claim_next_ready_feature_graph_worker_claims_status_store_not_projection(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "status": "pending",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_feature_graph_status())
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.claim_next_ready_feature_graph_worker(
            graph_set_id="graph-set-1",
            worker_session_id="god-session-feature-worker-a",
            provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
            updated_at="2026-06-03T03:10:00Z",
        )

    assert outcome is not None
    assert outcome.plan.source_status_id == "fgs-ready"
    assert outcome.status.status is FeatureGraphExecutionStatus.RUNNING
    assert outcome.status.active_lane_ids == ["lane-a"]
    assert outcome.status.active_worker_session_id == "god-session-feature-worker-a"
    assert (
        outcome.status.active_provider_session_binding_ref
        == "provider_session_binding:psb-worker-a:v1"
    )
    assert status_store.list_ready(graph_set_id="graph-set-1") == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_claim_next_ready_feature_graph_worker_does_not_scan_projection_degradation_bridge(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-a",
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "status": "pending",
                        "provider_session_binding_degraded": True,
                        "provider_session_binding_degraded_reason": "upsert_failed",
                        "provider_session_binding_id": (
                            "provider_session_binding:psb-worker-a:v1"
                        ),
                        "provider_session_binding_failure": "provider store write failed",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_feature_graph_status())
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
    )

    outcome = orch.claim_next_ready_feature_graph_worker(
        graph_set_id="graph-set-1",
        worker_session_id="god-session-feature-worker-a",
        provider_session_binding_ref="provider_session_binding:psb-worker-a:v1",
        updated_at="2026-06-03T03:10:00Z",
    )

    assert outcome is not None
    assert outcome.status.status is FeatureGraphExecutionStatus.RUNNING
    assert outcome.status.provider_session_binding_degradations == []
    assert [
        event.event_type
        for event in status_store.list_events(
            graph_set_id="graph-set-1",
            feature_graph_id="graph-feature-a",
        )
    ] == [
        "feature_graph_status.transitioned",
    ]
    assert lanes_path.read_text(encoding="utf-8") == before_projection


def test_claim_next_ready_feature_graph_worker_returns_none_without_lane_dispatch(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}) + "\n", encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-running",
            status=FeatureGraphExecutionStatus.RUNNING,
            ready_lane_ids=[],
            active_lane_ids=["lane-a"],
            updated_at="2026-06-03T03:00:00Z",
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.claim_next_ready_feature_graph_worker(
            worker_session_id="god-session-feature-worker-a",
            provider_session_binding_ref=None,
            updated_at="2026-06-03T03:10:00Z",
        )

    assert outcome is None
    assert status_store.list_events(graph_set_id="graph-set-1") == []
    dispatch.assert_not_awaited()


def test_submit_feature_graph_worker_evidence_moves_running_graph_to_reviewing(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 42,
                "lanes": [
                    {
                        "feature_id": "binding-schema",
                        "graph_set_id": "gs-xmuse-hardening",
                        "graph_id": "graph-provider-session-binding",
                        "status": "dispatched",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_running_feature_graph_status_from_bundle(bundle))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_worker_evidence(
            evidence_bundle=bundle,
            evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
            updated_at="2026-06-03T02:17:00Z",
        )

    assert outcome.plan.source_status_id == "fgs-running-from-bundle"
    assert outcome.status.status is FeatureGraphExecutionStatus.REVIEWING
    assert outcome.status.active_lane_ids == []
    assert outcome.status.completed_lane_ids == ["binding-schema"]
    assert outcome.status.active_worker_session_id == "god-worker-demo"
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening")[0].to_status is (
        FeatureGraphExecutionStatus.REVIEWING
    )
    assert artifact_store.get_evidence_bundle(bundle.bundle_id) == bundle
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_worker_evidence_rejects_unclaimed_worker(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}) + "\n", encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(
        _running_feature_graph_status_from_bundle(bundle).model_copy(
            update={"active_worker_session_id": "god-worker-other"}
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="active_worker_session_id"):
            orch.submit_feature_graph_worker_evidence(
                evidence_bundle=bundle,
                evidence_bundle_ref="feature_evidence_bundle:fevb_demo:v1",
                updated_at="2026-06-03T02:17:00Z",
            )

    assert status_store.get(
        graph_set_id="gs-xmuse-hardening",
        feature_graph_id="graph-provider-session-binding",
    ).status is FeatureGraphExecutionStatus.RUNNING
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening") == []
    assert artifact_store.list_evidence_bundles() == []
    dispatch.assert_not_awaited()


def test_submit_feature_graph_review_verdict_merge_writes_graph_status_not_projection(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    verdict = _feature_review_verdict()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_review_verdict(
            evidence_bundle=bundle,
            verdict=verdict,
            updated_at="2026-06-03T02:18:00Z",
        )

    assert outcome.status is not None
    assert outcome.status.status is FeatureGraphExecutionStatus.MERGED
    assert outcome.plan.coordinator_action is FeatureGraphReviewCoordinatorAction.TRANSITION_STATUS
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening")[0].to_status is (
        FeatureGraphExecutionStatus.MERGED
    )
    assert artifact_store.get_review_verdict(verdict.verdict_id) == verdict
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_review_verdict_rework_writes_reworking_status(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}) + "\n", encoding="utf-8")
    bundle = _feature_evidence_bundle()
    verdict = _rework_feature_review_verdict()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    outcome = orch.submit_feature_graph_review_verdict(
        evidence_bundle=bundle,
        verdict=verdict,
        updated_at="2026-06-03T02:18:00Z",
    )

    assert outcome.status is not None
    assert outcome.status.status is FeatureGraphExecutionStatus.REWORKING
    assert outcome.plan.target_status is FeatureGraphExecutionStatus.REWORKING
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening")[0].to_status is (
        FeatureGraphExecutionStatus.REWORKING
    )
    assert artifact_store.get_review_verdict(verdict.verdict_id) == verdict
    rework_packets = artifact_store.list_rework_packets_for_evidence_bundle(bundle.bundle_id)
    assert len(rework_packets) == 1
    assert rework_packets[0].rework_id == (
        "rework:fverdict_rework_demo:fevb_demo:20260603T021800z"
    )
    assert rework_packets[0].source_verdict_id == verdict.verdict_id
    assert rework_packets[0].target_worker_session_id == bundle.worker_session_id
    assert (
        rework_packets[0].target_provider_session_binding_ref
        == bundle.provider_session_binding_ref
    )
    assert rework_packets[0].max_remaining_attempts == 1


def test_submit_feature_graph_review_verdict_rework_accounts_for_prior_packets(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(json.dumps({"lanes": []}) + "\n", encoding="utf-8")
    bundle = _feature_evidence_bundle()
    verdict = _rework_feature_review_verdict()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    historical = _artifact_payload("feature_graph_rework_packet.v1.json")
    artifact_store.save_rework_packet(
        ReworkPacket.model_validate(
            {
                **historical,
                "rework_id": "rework:fverdict_rework_demo:fevb_demo:20260603T021500z",
                "max_remaining_attempts": 1,
            }
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    outcome = orch.submit_feature_graph_review_verdict(
        evidence_bundle=bundle,
        verdict=verdict,
        updated_at="2026-06-03T02:18:00Z",
    )

    assert outcome.rework_packet is not None
    assert outcome.rework_packet.max_remaining_attempts == 0
    assert artifact_store.get_rework_packet(
        "rework:fverdict_rework_demo:fevb_demo:20260603T021800z"
    ).max_remaining_attempts == 0


def test_submit_feature_graph_review_verdict_patch_forward_does_not_write_status(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    verdict = _patch_forward_feature_review_verdict()
    reviewing = _reviewing_feature_graph_status_from_bundle(bundle)
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(reviewing)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_review_verdict(
            evidence_bundle=bundle,
            verdict=verdict,
            updated_at="2026-06-03T02:18:00Z",
        )

    assert outcome.status is None
    assert (
        outcome.plan.coordinator_action
        is FeatureGraphReviewCoordinatorAction.PATCH_FORWARD_GATE
    )
    assert outcome.plan.target_status_record is None
    assert outcome.patch_forward_plan is not None
    assert outcome.patch_forward_plan.plan_id == (
        "fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021800z"
    )
    assert outcome.patch_forward_plan.allowed_file_refs == [
        "src/xmuse_core/agents/provider_session_binding.py"
    ]
    assert artifact_store.get_patch_forward_plan(
        "fgpf:fverdict_patch_forward_demo:fevb_demo:20260603T021800z"
    ) == outcome.patch_forward_plan
    assert artifact_store.get_review_verdict(verdict.verdict_id) == verdict
    assert status_store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    ) == reviewing
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening") == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_gate_result_saves_valid_result(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()
    result = _patch_forward_gate_result()
    artifact_store.save_patch_forward_plan(plan)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_patch_forward_gate_result(
            plan_id=plan.plan_id,
            result=result,
        )

    assert outcome.plan == plan
    assert outcome.result == result
    assert outcome.advance_to_merge_guard is True
    assert outcome.merge_guard_handoff is not None
    assert outcome.merge_guard_handoff.gate_result_id == result.result_id
    assert outcome.merge_guard_handoff.merge_guard_input_refs == [
        "feature_graph_patch_forward_gate_result:"
        "fgpfr:fverdict_patch_forward_demo:fevb_demo:20260603T021900z:v1",
        "diffs/patch-forward/provider-session-binding.diff",
        "logs/gates/provider-binding-patch-forward.json",
    ]
    assert artifact_store.get_patch_forward_gate_result(result.result_id) == result
    assert artifact_store.list_patch_forward_gate_results_for_plan(plan.plan_id) == [result]
    assert artifact_store.list_patch_forward_merge_guard_handoffs_for_gate_result(
        result.result_id
    ) == [outcome.merge_guard_handoff]
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_gate_result_saves_failed_evidence(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()
    failed_result = _patch_forward_gate_result().model_copy(
        update={
            "result_id": "fgpfr:fverdict_patch_forward_demo:fevb_demo:failed",
            "passed": False,
            "failure_reasons": ["focused provider binding gate failed"],
        }
    )
    artifact_store.save_patch_forward_plan(plan)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_patch_forward_gate_result(
            plan_id=plan.plan_id,
            result=failed_result,
        )

    assert outcome.plan == plan
    assert outcome.result == failed_result
    assert outcome.advance_to_merge_guard is False
    assert outcome.merge_guard_handoff is None
    assert artifact_store.get_patch_forward_gate_result(failed_result.result_id) == failed_result
    assert artifact_store.list_patch_forward_gate_results_for_plan(plan.plan_id) == [
        failed_result
    ]
    assert artifact_store.list_patch_forward_merge_guard_handoffs() == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_gate_result_rejects_passed_out_of_scope_result(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()
    invalid_result = _patch_forward_gate_result().model_copy(
        update={"changed_file_refs": ["src/xmuse_core/agents/other.py"]}
    )
    artifact_store.save_patch_forward_plan(plan)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="changed files"):
            orch.submit_feature_graph_patch_forward_gate_result(
                plan_id=plan.plan_id,
                result=invalid_result,
            )

    assert artifact_store.list_patch_forward_gate_results() == []
    assert artifact_store.list_patch_forward_merge_guard_handoffs() == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_gate_result_rejects_identity_mismatch(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()
    mismatched_result = _patch_forward_gate_result().model_copy(
        update={"feature_graph_id": "other-feature-graph"}
    )
    artifact_store.save_patch_forward_plan(plan)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="feature_graph_id must match plan"):
            orch.submit_feature_graph_patch_forward_gate_result(
                plan_id=plan.plan_id,
                result=mismatched_result,
            )

    assert artifact_store.list_patch_forward_gate_results() == []
    assert artifact_store.list_patch_forward_merge_guard_handoffs() == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_merge_guard_decision_saves_passed_result(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    plan = _patch_forward_plan()
    bundle = _feature_evidence_bundle()
    artifact_store.save_patch_forward_plan(plan)
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
        feature_graph_status_store=status_store,
    )
    gate_outcome = orch.submit_feature_graph_patch_forward_gate_result(
        plan_id=plan.plan_id,
        result=_patch_forward_gate_result(),
    )
    assert gate_outcome.merge_guard_handoff is not None

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_patch_forward_merge_guard_decision(
            handoff_id=gate_outcome.merge_guard_handoff.handoff_id,
            merge_guard_ref="logs/merge_guard/provider-binding-patch-forward.json",
            merge_guard_evidence_refs=[
                "feature_graph_patch_forward_merge_guard_handoff:"
                "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:"
                "20260603T021900z:v1",
                "logs/merge_guard/provider-binding-patch-forward.json",
            ],
            passed=True,
            failure_reasons=None,
            checked_at="2026-06-03T02:22:00Z",
        )

    assert outcome.handoff == gate_outcome.merge_guard_handoff
    assert outcome.decision.passed is True
    assert outcome.eligible_for_status_transition is True
    assert artifact_store.get_patch_forward_merge_guard_decision(
        outcome.decision.decision_id
    ) == outcome.decision
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_merge_guard_decision_saves_failed_result(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()
    artifact_store.save_patch_forward_plan(plan)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )
    gate_outcome = orch.submit_feature_graph_patch_forward_gate_result(
        plan_id=plan.plan_id,
        result=_patch_forward_gate_result(),
    )
    assert gate_outcome.merge_guard_handoff is not None

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_patch_forward_merge_guard_decision(
            handoff_id=gate_outcome.merge_guard_handoff.handoff_id,
            merge_guard_ref="logs/merge_guard/provider-binding-patch-forward-failed.json",
            merge_guard_evidence_refs=[
                "logs/merge_guard/provider-binding-patch-forward-failed.json"
            ],
            passed=False,
            failure_reasons=["target branch changed before merge guard"],
            checked_at="2026-06-03T02:23:00Z",
        )

    assert outcome.decision.passed is False
    assert outcome.eligible_for_status_transition is False
    assert outcome.decision.failure_reasons == ["target branch changed before merge guard"]
    assert artifact_store.list_patch_forward_merge_guard_decisions_for_handoff(
        gate_outcome.merge_guard_handoff.handoff_id
    ) == [outcome.decision]
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_merge_guard_decision_rejects_stale_review_context(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    plan = _patch_forward_plan()
    bundle = _feature_evidence_bundle()
    artifact_store.save_patch_forward_plan(plan)
    status_store.upsert(
        _reviewing_feature_graph_status_from_bundle(bundle).model_copy(
            update={
                "status_id": "fgstatus_blocked_patch_forward_demo",
                "status": FeatureGraphExecutionStatus.BLOCKED,
            }
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
        feature_graph_status_store=status_store,
    )
    gate_outcome = orch.submit_feature_graph_patch_forward_gate_result(
        plan_id=plan.plan_id,
        result=_patch_forward_gate_result(),
    )
    assert gate_outcome.merge_guard_handoff is not None

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="requires reviewing status"):
            orch.submit_feature_graph_patch_forward_merge_guard_decision(
                handoff_id=gate_outcome.merge_guard_handoff.handoff_id,
                merge_guard_ref="logs/merge_guard/provider-binding-patch-forward.json",
                merge_guard_evidence_refs=[
                    "feature_graph_patch_forward_merge_guard_handoff:"
                    "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:"
                    "20260603T021900z:v1",
                    "logs/merge_guard/provider-binding-patch-forward.json",
                ],
                passed=True,
                failure_reasons=None,
                checked_at="2026-06-03T02:22:00Z",
            )

    assert artifact_store.list_patch_forward_merge_guard_decisions() == []
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening") == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_merge_guard_decision_replay_is_duplicate_safe(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    plan = _patch_forward_plan()
    bundle = _feature_evidence_bundle()
    artifact_store.save_patch_forward_plan(plan)
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
        feature_graph_status_store=status_store,
    )
    gate_outcome = orch.submit_feature_graph_patch_forward_gate_result(
        plan_id=plan.plan_id,
        result=_patch_forward_gate_result(),
    )
    assert gate_outcome.merge_guard_handoff is not None

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        first = orch.submit_feature_graph_patch_forward_merge_guard_decision(
            handoff_id=gate_outcome.merge_guard_handoff.handoff_id,
            merge_guard_ref="logs/merge_guard/provider-binding-patch-forward.json",
            merge_guard_evidence_refs=[
                "feature_graph_patch_forward_merge_guard_handoff:"
                "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:"
                "20260603T021900z:v1",
                "logs/merge_guard/provider-binding-patch-forward.json",
            ],
            passed=True,
            failure_reasons=None,
            checked_at="2026-06-03T02:22:00Z",
        )
        replay = orch.submit_feature_graph_patch_forward_merge_guard_decision(
            handoff_id=gate_outcome.merge_guard_handoff.handoff_id,
            merge_guard_ref="logs/merge_guard/provider-binding-patch-forward.json",
            merge_guard_evidence_refs=[
                "feature_graph_patch_forward_merge_guard_handoff:"
                "fgpfmgh:fgpfr:fverdict_patch_forward_demo:fevb_demo:"
                "20260603T021900z:v1",
                "logs/merge_guard/provider-binding-patch-forward.json",
            ],
            passed=True,
            failure_reasons=None,
            checked_at="2026-06-03T02:22:00Z",
        )

    assert replay.decision == first.decision
    assert artifact_store.list_patch_forward_merge_guard_decisions_for_handoff(
        gate_outcome.merge_guard_handoff.handoff_id
    ) == [first.decision]
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening") == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_patch_forward_merge_guard_decision_rejects_invalid_failure(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = _patch_forward_plan()
    artifact_store.save_patch_forward_plan(plan)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )
    gate_outcome = orch.submit_feature_graph_patch_forward_gate_result(
        plan_id=plan.plan_id,
        result=_patch_forward_gate_result(),
    )
    assert gate_outcome.merge_guard_handoff is not None

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="failed patch-forward merge guard"):
            orch.submit_feature_graph_patch_forward_merge_guard_decision(
                handoff_id=gate_outcome.merge_guard_handoff.handoff_id,
                merge_guard_ref="logs/merge_guard/provider-binding-patch-forward.json",
                merge_guard_evidence_refs=[
                    "logs/merge_guard/provider-binding-patch-forward.json"
                ],
                passed=False,
                failure_reasons=[],
                checked_at="2026-06-03T02:24:00Z",
            )

    assert artifact_store.list_patch_forward_merge_guard_decisions() == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_apply_feature_graph_patch_forward_merge_guard_decision_status_writes_merged_status(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _reviewing_feature_graph_status_from_bundle(_feature_evidence_bundle())
    )
    plan = _patch_forward_plan()
    artifact_store.save_patch_forward_plan(plan)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
        feature_graph_status_store=status_store,
    )
    gate_outcome = orch.submit_feature_graph_patch_forward_gate_result(
        plan_id=plan.plan_id,
        result=_patch_forward_gate_result(),
    )
    assert gate_outcome.merge_guard_handoff is not None
    decision_outcome = orch.submit_feature_graph_patch_forward_merge_guard_decision(
        handoff_id=gate_outcome.merge_guard_handoff.handoff_id,
        merge_guard_ref="logs/merge_guard/provider-binding-patch-forward.json",
        merge_guard_evidence_refs=[
            "logs/merge_guard/provider-binding-patch-forward.json"
        ],
        passed=True,
        failure_reasons=None,
        checked_at="2026-06-03T02:22:00Z",
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.apply_feature_graph_patch_forward_merge_guard_decision_status(
            decision_id=decision_outcome.decision.decision_id,
            updated_at="2026-06-03T02:25:00Z",
        )

    assert outcome.decision == decision_outcome.decision
    assert outcome.status.status is FeatureGraphExecutionStatus.MERGED
    assert status_store.get(
        graph_set_id=outcome.status.graph_set_id,
        feature_graph_id=outcome.status.feature_graph_id,
    ) == outcome.status
    assert len(status_store.list_events(graph_set_id=outcome.status.graph_set_id)) == 1
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_review_verdict_blocked_writes_plan_and_status(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    verdict = _blocked_feature_review_verdict()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_review_verdict(
            evidence_bundle=bundle,
            verdict=verdict,
            updated_at="2026-06-03T02:18:00Z",
        )

    assert outcome.status is not None
    assert outcome.status.status is FeatureGraphExecutionStatus.BLOCKED
    assert outcome.blocked_review_plan is not None
    assert outcome.blocked_review_plan.plan_id == (
        "fgblocked:fverdict_blocked_demo:fevb_demo:20260603T021800z"
    )
    assert outcome.blocked_review_plan.missing_inputs == [
        "Codex CLI resume smoke evidence"
    ]
    assert outcome.blocked_review_plan.blocked_reason == (
        "Need Codex CLI resume smoke evidence."
    )
    assert outcome.blocked_review_plan.blocked_owner == "coordinator"
    assert artifact_store.get_blocked_review_plan(
        "fgblocked:fverdict_blocked_demo:fevb_demo:20260603T021800z"
    ) == outcome.blocked_review_plan
    assert artifact_store.get_review_verdict(verdict.verdict_id) == verdict
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening")[0].to_status is (
        FeatureGraphExecutionStatus.BLOCKED
    )
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_review_verdict_takeover_writes_plan_without_status(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    verdict = _takeover_feature_review_verdict()
    reviewing = _reviewing_feature_graph_status_from_bundle(bundle)
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    status_store.upsert(reviewing)
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_review_verdict(
            evidence_bundle=bundle,
            verdict=verdict,
            updated_at="2026-06-03T02:18:00Z",
        )

    assert outcome.status is None
    assert (
        outcome.plan.coordinator_action
        is FeatureGraphReviewCoordinatorAction.TAKEOVER_REQUIRED
    )
    assert outcome.plan.target_status_record is None
    assert outcome.takeover_plan is not None
    assert outcome.takeover_plan.plan_id == (
        "fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T021800z"
    )
    assert outcome.takeover_plan.failed_worker_session_id == bundle.worker_session_id
    assert (
        outcome.takeover_plan.failed_provider_session_binding_ref
        == bundle.provider_session_binding_ref
    )
    assert artifact_store.get_takeover_plan(
        "fgtakeover:fverdict_takeover_demo:fevb_demo:20260603T021800z"
    ) == outcome.takeover_plan
    assert artifact_store.get_review_verdict(verdict.verdict_id) == verdict
    assert status_store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    ) == reviewing
    assert status_store.list_events(graph_set_id="gs-xmuse-hardening") == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_decision_saves_approved_result(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_takeover_decision(
            plan_id=plan.plan_id,
            approved=True,
            takeover_worker_session_id="god-takeover-worker-demo",
            takeover_provider_session_binding_ref=(
                "provider_session_binding:psb_takeover_demo:v1"
            ),
            gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
            failure_reasons=None,
            checked_at="2026-06-03T02:23:00Z",
        )

    assert outcome.plan == plan
    assert outcome.decision.approved is True
    assert outcome.eligible_for_takeover is True
    assert outcome.takeover_handoff is not None
    assert outcome.takeover_handoff.decision_id == outcome.decision.decision_id
    assert outcome.takeover_handoff.takeover_worker_session_id == (
        "god-takeover-worker-demo"
    )
    assert artifact_store.get_takeover_decision(
        outcome.decision.decision_id
    ) == outcome.decision
    assert artifact_store.list_takeover_handoffs_for_decision(
        outcome.decision.decision_id
    ) == [outcome.takeover_handoff]
    assert status_store.list_events(graph_set_id=bundle.graph_set_id) == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_decision_rejects_stale_review_context(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _reviewing_feature_graph_status_from_bundle(bundle).model_copy(
            update={
                "status_id": "fgstatus_blocked_takeover_demo",
                "status": FeatureGraphExecutionStatus.BLOCKED,
            }
        )
    )
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="requires reviewing status"):
            orch.submit_feature_graph_takeover_decision(
                plan_id=plan.plan_id,
                approved=True,
                takeover_worker_session_id="god-takeover-worker-demo",
                takeover_provider_session_binding_ref=(
                    "provider_session_binding:psb_takeover_demo:v1"
                ),
                gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
                failure_reasons=None,
                checked_at="2026-06-03T02:23:00Z",
            )

    assert artifact_store.list_takeover_decisions() == []
    assert artifact_store.list_takeover_handoffs() == []
    assert status_store.list_events(graph_set_id=bundle.graph_set_id) == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_decision_rejects_review_context_identity_mismatch(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _reviewing_feature_graph_status_from_bundle(bundle).model_copy(
            update={"feature_id": "other-feature"}
        )
    )
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="current status feature_id must match takeover plan"):
            orch.submit_feature_graph_takeover_decision(
                plan_id=plan.plan_id,
                approved=True,
                takeover_worker_session_id="god-takeover-worker-demo",
                takeover_provider_session_binding_ref=(
                    "provider_session_binding:psb_takeover_demo:v1"
                ),
                gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
                failure_reasons=None,
                checked_at="2026-06-03T02:23:00Z",
            )

    assert artifact_store.list_takeover_decisions() == []
    assert artifact_store.list_takeover_handoffs() == []
    assert status_store.list_events(graph_set_id=bundle.graph_set_id) == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_decision_replay_is_duplicate_safe(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        first = orch.submit_feature_graph_takeover_decision(
            plan_id=plan.plan_id,
            approved=True,
            takeover_worker_session_id="god-takeover-worker-demo",
            takeover_provider_session_binding_ref=(
                "provider_session_binding:psb_takeover_demo:v1"
            ),
            gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
            failure_reasons=None,
            checked_at="2026-06-03T02:23:00Z",
        )
        replay = orch.submit_feature_graph_takeover_decision(
            plan_id=plan.plan_id,
            approved=True,
            takeover_worker_session_id="god-takeover-worker-demo",
            takeover_provider_session_binding_ref=(
                "provider_session_binding:psb_takeover_demo:v1"
            ),
            gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
            failure_reasons=None,
            checked_at="2026-06-03T02:23:00Z",
        )

    assert replay.decision == first.decision
    assert replay.takeover_handoff == first.takeover_handoff
    assert artifact_store.list_takeover_decisions_for_plan(plan.plan_id) == [first.decision]
    assert artifact_store.list_takeover_handoffs_for_decision(
        first.decision.decision_id
    ) == [first.takeover_handoff]
    assert status_store.list_events(graph_set_id=bundle.graph_set_id) == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_decision_saves_rejected_result(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_takeover_decision(
            plan_id=plan.plan_id,
            approved=False,
            takeover_worker_session_id=None,
            takeover_provider_session_binding_ref=None,
            gate_refs=["logs/takeover/provider-binding-takeover-rejected.json"],
            failure_reasons=["takeover worker lease unavailable"],
            checked_at="2026-06-03T02:24:00Z",
        )

    assert outcome.decision.approved is False
    assert outcome.eligible_for_takeover is False
    assert outcome.takeover_handoff is None
    assert outcome.decision.failure_reasons == ["takeover worker lease unavailable"]
    assert artifact_store.list_takeover_decisions_for_plan(plan.plan_id) == [
        outcome.decision
    ]
    assert artifact_store.list_takeover_handoffs() == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_decision_rejects_invalid_failure(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_artifact_store=artifact_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with pytest.raises(ValueError, match="rejected takeover decisions"):
            orch.submit_feature_graph_takeover_decision(
                plan_id=plan.plan_id,
                approved=False,
                takeover_worker_session_id=None,
                takeover_provider_session_binding_ref=None,
                gate_refs=["logs/takeover/provider-binding-takeover-rejected.json"],
                failure_reasons=[],
                checked_at="2026-06-03T02:24:00Z",
            )

    assert artifact_store.list_takeover_decisions() == []
    assert artifact_store.list_takeover_handoffs() == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_outcome_saves_completed_result(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_takeover_outcome(
            handoff_id=decision_outcome.takeover_handoff.handoff_id,
            changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
            evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
            verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
            output_summary="Recovered provider binding command planning.",
            completed=True,
            failure_reasons=None,
            created_at="2026-06-03T02:29:00Z",
        )

    assert outcome.handoff == decision_outcome.takeover_handoff
    assert outcome.outcome.completed is True
    assert outcome.eligible_for_followup_review is True
    assert outcome.review_handoff is not None
    assert outcome.review_handoff.outcome_id == outcome.outcome.outcome_id
    assert artifact_store.get_takeover_outcome(
        outcome.outcome.outcome_id
    ) == outcome.outcome
    assert artifact_store.list_takeover_outcomes_for_handoff(
        decision_outcome.takeover_handoff.handoff_id
    ) == [outcome.outcome]
    assert artifact_store.list_takeover_review_handoffs_for_outcome(
        outcome.outcome.outcome_id
    ) == [outcome.review_handoff]
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_outcome_rejects_stale_review_context(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    status_store.transition(
        _reviewing_feature_graph_status_from_bundle(bundle).model_copy(
            update={
                "status_id": "fgstatus_blocked_takeover_outcome_demo",
                "status": FeatureGraphExecutionStatus.BLOCKED,
                "updated_at": "2026-06-03T02:28:30Z",
            }
        ),
        expected_status=FeatureGraphExecutionStatus.REVIEWING,
    )

    with pytest.raises(ValueError, match="takeover outcome requires reviewing status"):
        orch.submit_feature_graph_takeover_outcome(
            handoff_id=decision_outcome.takeover_handoff.handoff_id,
            changed_file_refs=[],
            evidence_refs=[],
            verification_refs=[],
            output_summary="Takeover worker could not acquire a worktree lease.",
            completed=False,
            failure_reasons=["takeover worktree lease unavailable"],
            created_at="2026-06-03T02:30:00Z",
        )

    assert artifact_store.list_takeover_outcomes() == []
    assert artifact_store.list_takeover_review_handoffs() == []


def test_submit_feature_graph_takeover_outcome_recovers_review_handoff_after_outcome_write(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None

    with patch.object(
        artifact_store,
        "save_takeover_review_handoff",
        side_effect=RuntimeError("persist review handoff later"),
    ):
        with pytest.raises(RuntimeError, match="persist review handoff later"):
            orch.submit_feature_graph_takeover_outcome(
                handoff_id=decision_outcome.takeover_handoff.handoff_id,
                changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
                evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
                verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
                output_summary="Recovered provider binding command planning.",
                completed=True,
                failure_reasons=None,
                created_at="2026-06-03T02:29:00Z",
            )

    saved_outcomes = artifact_store.list_takeover_outcomes_for_handoff(
        decision_outcome.takeover_handoff.handoff_id
    )
    assert len(saved_outcomes) == 1
    assert artifact_store.list_takeover_review_handoffs() == []

    recovered = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:31:00Z",
    )

    assert recovered.outcome == saved_outcomes[0]
    assert recovered.review_handoff is not None
    assert recovered.review_handoff.outcome_id == saved_outcomes[0].outcome_id
    assert artifact_store.list_takeover_outcomes_for_handoff(
        decision_outcome.takeover_handoff.handoff_id
    ) == [saved_outcomes[0]]
    assert artifact_store.list_takeover_review_handoffs_for_outcome(
        saved_outcomes[0].outcome_id
    ) == [recovered.review_handoff]


def test_submit_feature_graph_takeover_followup_review_verdict_saves_verdict(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(
        FeatureEvidenceBundle.model_validate(_artifact_payload("feature_evidence_bundle.v1.json"))
    )
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    verdict = FeatureReviewVerdict.model_validate(
        _artifact_payload("feature_review_verdict.v1.json")
    ).model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_merge",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_takeover_followup_review_verdict(
            review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
            verdict=verdict,
        )

    assert outcome.handoff == takeover_outcome.review_handoff
    assert outcome.verdict.verdict_id == "fverdict_takeover_followup_merge"
    assert artifact_store.get_review_verdict(outcome.verdict.verdict_id) == outcome.verdict
    assert artifact_store.list_review_verdicts_for_evidence_bundle("fevb_demo") == [
        outcome.verdict
    ]
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_submit_feature_graph_takeover_followup_review_verdict_rejects_stale_review_context(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(bundle)
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    status_store.transition(
        _reviewing_feature_graph_status_from_bundle(bundle).model_copy(
            update={
                "status_id": "fgstatus_blocked_takeover_followup_demo",
                "status": FeatureGraphExecutionStatus.BLOCKED,
                "updated_at": "2026-06-03T02:30:30Z",
            }
        ),
        expected_status=FeatureGraphExecutionStatus.REVIEWING,
    )
    verdict = FeatureReviewVerdict.model_validate(
        _artifact_payload("feature_review_verdict.v1.json")
    ).model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_merge",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )

    with pytest.raises(
        ValueError,
        match="takeover follow-up review verdict requires reviewing status",
    ):
        orch.submit_feature_graph_takeover_followup_review_verdict(
            review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
            verdict=verdict,
        )

    assert artifact_store.list_review_verdicts() == []


def test_apply_feature_graph_takeover_followup_review_verdict_merges_status(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(bundle)
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    verdict = _feature_review_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_merge",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )
    saved = orch.submit_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
        verdict=verdict,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        applied = orch.apply_feature_graph_takeover_followup_review_verdict(
            review_handoff_id=saved.handoff.review_handoff_id,
            verdict_id=saved.verdict.verdict_id,
            updated_at="2026-06-03T02:31:00Z",
        )

    assert applied.handoff == takeover_outcome.review_handoff
    assert applied.application.verdict_id == saved.verdict.verdict_id
    assert applied.application.applied_status is not None
    assert applied.review_outcome.status is not None
    assert applied.review_outcome.status.status is FeatureGraphExecutionStatus.MERGED
    assert status_store.list_events(graph_set_id=bundle.graph_set_id)[0].to_status is (
        FeatureGraphExecutionStatus.MERGED
    )
    assert artifact_store.list_takeover_followup_review_applications_for_handoff(
        saved.handoff.review_handoff_id
    ) == [applied.application]

    replayed = orch.apply_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=saved.handoff.review_handoff_id,
        verdict_id=saved.verdict.verdict_id,
        updated_at="2026-06-03T02:31:00Z",
    )

    assert replayed.application == applied.application
    assert replayed.review_outcome.status == applied.review_outcome.status
    assert len(status_store.list_events(graph_set_id=bundle.graph_set_id)) == 1
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_apply_feature_graph_takeover_followup_recovers_application_after_status_write(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(bundle)
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    verdict = _feature_review_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_merge",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )
    saved = orch.submit_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
        verdict=verdict,
    )
    direct_review = orch.submit_feature_graph_review_verdict(
        evidence_bundle=bundle,
        verdict=saved.verdict,
        updated_at="2026-06-03T02:31:00Z",
    )
    assert direct_review.status is not None
    assert direct_review.status.status is FeatureGraphExecutionStatus.MERGED
    assert artifact_store.list_takeover_followup_review_applications_for_handoff(
        saved.handoff.review_handoff_id
    ) == []

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        recovered = orch.apply_feature_graph_takeover_followup_review_verdict(
            review_handoff_id=saved.handoff.review_handoff_id,
            verdict_id=saved.verdict.verdict_id,
            updated_at="2026-06-03T02:31:30Z",
        )

    assert recovered.application.applied_status == direct_review.status
    assert recovered.application.review_plan.target_status_record == direct_review.status
    assert recovered.review_outcome.status == direct_review.status
    assert artifact_store.list_takeover_followup_review_applications_for_handoff(
        saved.handoff.review_handoff_id
    ) == [recovered.application]
    assert len(status_store.list_events(graph_set_id=bundle.graph_set_id)) == 1
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_apply_feature_graph_takeover_followup_recovers_rework_application_after_status_write(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(bundle)
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    verdict = _rework_feature_review_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_rework",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )
    saved = orch.submit_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
        verdict=verdict,
    )
    direct_review = orch.submit_feature_graph_review_verdict(
        evidence_bundle=bundle,
        verdict=saved.verdict,
        updated_at="2026-06-03T02:32:00Z",
    )
    assert direct_review.status is not None
    assert direct_review.status.status is FeatureGraphExecutionStatus.REWORKING
    assert direct_review.rework_packet is not None
    assert artifact_store.list_takeover_followup_review_applications_for_handoff(
        saved.handoff.review_handoff_id
    ) == []

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        recovered = orch.apply_feature_graph_takeover_followup_review_verdict(
            review_handoff_id=saved.handoff.review_handoff_id,
            verdict_id=saved.verdict.verdict_id,
            updated_at="2026-06-03T02:32:30Z",
        )

    assert recovered.application.applied_status == direct_review.status
    assert recovered.application.rework_id == direct_review.rework_packet.rework_id
    assert recovered.review_outcome.rework_packet == direct_review.rework_packet
    assert len(status_store.list_events(graph_set_id=bundle.graph_set_id)) == 1
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_apply_feature_graph_takeover_followup_recovers_blocked_application_after_status_write(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(bundle)
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/providers/adapters/codex.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Takeover output still needs provider resume evidence.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    verdict = _blocked_feature_review_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_blocked",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )
    saved = orch.submit_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
        verdict=verdict,
    )
    direct_review = orch.submit_feature_graph_review_verdict(
        evidence_bundle=bundle,
        verdict=saved.verdict,
        updated_at="2026-06-03T02:33:00Z",
    )
    assert direct_review.status is not None
    assert direct_review.status.status is FeatureGraphExecutionStatus.BLOCKED
    assert direct_review.blocked_review_plan is not None
    assert artifact_store.list_takeover_followup_review_applications_for_handoff(
        saved.handoff.review_handoff_id
    ) == []

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        recovered = orch.apply_feature_graph_takeover_followup_review_verdict(
            review_handoff_id=saved.handoff.review_handoff_id,
            verdict_id=saved.verdict.verdict_id,
            updated_at="2026-06-03T02:33:30Z",
        )

    assert recovered.application.applied_status == direct_review.status
    assert (
        recovered.application.blocked_review_plan_id
        == direct_review.blocked_review_plan.plan_id
    )
    assert recovered.review_outcome.blocked_review_plan == direct_review.blocked_review_plan
    assert recovered.review_outcome.blocked_review_plan.missing_inputs == [
        "Codex CLI resume smoke evidence"
    ]
    assert len(status_store.list_events(graph_set_id=bundle.graph_set_id)) == 1
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_apply_feature_graph_takeover_followup_patch_forward_keeps_reviewing_status(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    reviewing = _reviewing_feature_graph_status_from_bundle(bundle)
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(reviewing)
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(bundle)
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/agents/provider_session_binding.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    verdict = _patch_forward_feature_review_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_patch_forward",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )
    saved = orch.submit_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
        verdict=verdict,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        applied = orch.apply_feature_graph_takeover_followup_review_verdict(
            review_handoff_id=saved.handoff.review_handoff_id,
            verdict_id=saved.verdict.verdict_id,
            updated_at="2026-06-03T02:31:00Z",
        )

    assert applied.review_outcome.status is None
    assert applied.review_outcome.patch_forward_plan is not None
    assert applied.application.patch_forward_plan_id == (
        applied.review_outcome.patch_forward_plan.plan_id
    )
    assert applied.review_outcome.patch_forward_plan.plan_id == (
        "fgpf:fverdict_takeover_followup_patch_forward:fevb_demo:20260603T023100z"
    )
    assert status_store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    ) == reviewing
    assert status_store.list_events(graph_set_id=bundle.graph_set_id) == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


def test_apply_feature_graph_takeover_followup_patch_forward_recovers_application_after_plan_write(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    bundle = _feature_evidence_bundle()
    reviewing = _reviewing_feature_graph_status_from_bundle(bundle)
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(reviewing)
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    artifact_store.save_evidence_bundle(bundle)
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None
    takeover_outcome = orch.submit_feature_graph_takeover_outcome(
        handoff_id=decision_outcome.takeover_handoff.handoff_id,
        changed_file_refs=["src/xmuse_core/agents/provider_session_binding.py"],
        evidence_refs=["feature_evidence_bundle:fevb_takeover_provider_binding:v1"],
        verification_refs=["logs/takeover/provider-binding-focused-gates.json"],
        output_summary="Recovered provider binding command planning.",
        completed=True,
        failure_reasons=None,
        created_at="2026-06-03T02:29:00Z",
    )
    assert takeover_outcome.review_handoff is not None
    verdict = _patch_forward_feature_review_verdict().model_copy(
        update={
            "verdict_id": "fverdict_takeover_followup_patch_forward",
            "evidence_refs": list(takeover_outcome.review_handoff.reviewer_input_refs),
        }
    )
    saved = orch.submit_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=takeover_outcome.review_handoff.review_handoff_id,
        verdict=verdict,
    )

    with patch.object(
        artifact_store,
        "save_takeover_followup_review_application",
        side_effect=RuntimeError("persist followup application later"),
    ):
        with pytest.raises(RuntimeError, match="persist followup application later"):
            orch.apply_feature_graph_takeover_followup_review_verdict(
                review_handoff_id=saved.handoff.review_handoff_id,
                verdict_id=saved.verdict.verdict_id,
                updated_at="2026-06-03T02:31:00Z",
            )

    saved_patch_forward_plans = artifact_store.list_patch_forward_plans_for_evidence_bundle(
        bundle.bundle_id
    )
    assert len(saved_patch_forward_plans) == 1
    assert artifact_store.list_takeover_followup_review_applications_for_handoff(
        saved.handoff.review_handoff_id
    ) == []

    recovered = orch.apply_feature_graph_takeover_followup_review_verdict(
        review_handoff_id=saved.handoff.review_handoff_id,
        verdict_id=saved.verdict.verdict_id,
        updated_at="2026-06-03T02:31:30Z",
    )

    assert recovered.application.patch_forward_plan_id == saved_patch_forward_plans[0].plan_id
    assert recovered.review_outcome.patch_forward_plan == saved_patch_forward_plans[0]
    assert artifact_store.list_patch_forward_plans_for_evidence_bundle(bundle.bundle_id) == [
        saved_patch_forward_plans[0]
    ]
    assert artifact_store.list_takeover_followup_review_applications_for_handoff(
        saved.handoff.review_handoff_id
    ) == [recovered.application]
    assert status_store.get(
        graph_set_id=bundle.graph_set_id,
        feature_graph_id=bundle.feature_graph_id,
    ) == reviewing


def test_submit_feature_graph_takeover_outcome_saves_failed_result(tmp_path):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 42, "lanes": [{"feature_id": "binding-schema"}]})
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    bundle = _feature_evidence_bundle()
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(_reviewing_feature_graph_status_from_bundle(bundle))
    artifact_store = FeatureGraphArtifactStore(tmp_path / "feature_graph_artifacts.json")
    plan = artifact_store.save_takeover_plan(
        FeatureGraphTakeoverPlan.model_validate(
            _artifact_payload("feature_graph_takeover_plan.v1.json")
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        feature_graph_status_store=status_store,
        feature_graph_artifact_store=artifact_store,
    )
    decision_outcome = orch.submit_feature_graph_takeover_decision(
        plan_id=plan.plan_id,
        approved=True,
        takeover_worker_session_id="god-takeover-worker-demo",
        takeover_provider_session_binding_ref="provider_session_binding:psb_takeover_demo:v1",
        gate_refs=["logs/takeover/provider-binding-takeover-gate.json"],
        failure_reasons=None,
        checked_at="2026-06-03T02:23:00Z",
    )
    assert decision_outcome.takeover_handoff is not None

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        outcome = orch.submit_feature_graph_takeover_outcome(
            handoff_id=decision_outcome.takeover_handoff.handoff_id,
            changed_file_refs=[],
            evidence_refs=[],
            verification_refs=[],
            output_summary="Takeover worker could not acquire a worktree lease.",
            completed=False,
            failure_reasons=["takeover worktree lease unavailable"],
            created_at="2026-06-03T02:30:00Z",
        )

    assert outcome.outcome.completed is False
    assert outcome.eligible_for_followup_review is False
    assert outcome.review_handoff is None
    assert outcome.outcome.failure_reasons == ["takeover worktree lease unavailable"]
    assert artifact_store.list_takeover_outcomes_for_handoff(
        decision_outcome.takeover_handoff.handoff_id
    ) == [outcome.outcome]
    assert artifact_store.list_takeover_review_handoffs() == []
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    dispatch.assert_not_awaited()


@pytest.mark.asyncio
async def test_mcp_status_change_callback(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    result = orch._tools.call("update_lane_status", {
        "lane_id": "lane-1",
        "status": "reviewed",
        "audit": {
            "actor": "review_god",
            "reason": "accept review verdict",
            "request_id": "req-orch-review-1",
        },
        "guard": {"current_status": "gated"},
    })
    assert result["status"] == "reviewed"


def _provider_session_binding(
    *,
    worktree: str,
    session_kind: str = "exec",
    role: str = "feature_worker",
) -> ProviderSessionBindingRecord:
    return ProviderSessionBindingRecord(
        binding_id="psb-codex-demo",
        god_session_id="god-worker-demo",
        provider="codex",
        provider_session_id="codex-session-11111111-2222-3333-4444-555555555555",
        session_kind=session_kind,
        status=ProviderSessionBindingStatus.ACTIVE,
        conversation_id="conv-xmuse-hardening",
        feature_graph_id="graph-feature-a",
        role=role,
        cwd="/repo",
        worktree=worktree,
        model="gpt-5.4",
        prompt_fingerprint=None,
        created_at="2026-06-03T02:10:00Z",
        last_used_at="2026-06-03T02:11:00Z",
        last_verified_at="2026-06-03T02:11:30Z",
        resume_command_template="codex exec resume {provider_session_id}",
    )


def _feature_graph_status(
    *,
    status_id: str = "fgs-ready",
    status: FeatureGraphExecutionStatus = FeatureGraphExecutionStatus.READY,
    ready_lane_ids: list[str] | None = None,
    active_lane_ids: list[str] | None = None,
    updated_at: str = "2026-06-03T03:00:00Z",
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id=status_id,
        conversation_id="conv-1",
        planning_run_id="planning-1",
        graph_set_id="graph-set-1",
        graph_set_version=1,
        feature_plan_id="feature-plan-1",
        feature_plan_version=1,
        feature_id="feature-a",
        feature_graph_id="graph-feature-a",
        status=status,
        ready_lane_ids=ready_lane_ids if ready_lane_ids is not None else ["lane-a"],
        active_lane_ids=active_lane_ids or [],
        completed_lane_ids=[],
        blocked_lane_ids=[],
        projection_lane_ids=["lane:conv-1:graph-feature-a:lane-a"],
        feature_lanes_projection_ref="feature_lanes.json#projection_revision=7",
        updated_at=updated_at,
    )


def _artifact_payload(name: str) -> dict:
    payload = json.loads((CONTRACT_ROOT / name).read_text(encoding="utf-8"))
    assert payload["schema_version"] == "xmuse.artifact.v1"
    assert isinstance(payload["payload"], dict)
    return payload["payload"]


def _feature_evidence_bundle() -> FeatureEvidenceBundle:
    return FeatureEvidenceBundle.model_validate(
        _artifact_payload("feature_evidence_bundle.v1.json")
    )


def _feature_review_verdict() -> FeatureReviewVerdict:
    return FeatureReviewVerdict.model_validate(
        _artifact_payload("feature_review_verdict.v1.json")
    )


def _rework_feature_review_verdict() -> FeatureReviewVerdict:
    merge = _feature_review_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_rework_demo",
            "decision": "rework",
            "summary": "Focused verification is missing for stale binding recovery.",
            "blocking_findings": [
                {
                    "finding_id": "finding-stale-binding",
                    "severity": "blocking",
                    "summary": "Missing stale binding recovery coverage.",
                    "evidence_refs": ["logs/gates/provider-binding.json"],
                }
            ],
        }
    )


def _patch_forward_feature_review_verdict() -> FeatureReviewVerdict:
    merge = _feature_review_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_patch_forward_demo",
            "decision": "patch_forward",
            "summary": "A one-line import fix can be patched by reviewer under gate.",
            "patch_forward_gate": {
                "risk": "low",
                "reason_not_rework": "The fix is a one-line import in an existing touched file.",
                "allowed_file_refs": ["src/xmuse_core/agents/provider_session_binding.py"],
                "max_files_changed": 1,
                "max_lines_changed": 5,
                "focused_gates_to_rerun": [
                    "uv run pytest -q tests/xmuse/test_provider_session_binding.py"
                ],
                "disallow_new_dependencies": True,
                "disallow_public_contract_changes": True,
            },
        }
    )


def _patch_forward_plan() -> FeatureGraphPatchForwardPlan:
    return FeatureGraphPatchForwardPlan.model_validate(
        _artifact_payload("feature_graph_patch_forward_plan.v1.json")
    )


def _patch_forward_gate_result() -> FeatureGraphPatchForwardGateResult:
    return FeatureGraphPatchForwardGateResult.model_validate(
        _artifact_payload("feature_graph_patch_forward_gate_result.v1.json")
    )


def _blocked_feature_review_verdict() -> FeatureReviewVerdict:
    merge = _feature_review_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_blocked_demo",
            "decision": "blocked",
            "summary": "Cannot review without provider CLI resume behavior evidence.",
            "blocked_missing_inputs": ["Codex CLI resume smoke evidence"],
            "blocked_reason": "Need Codex CLI resume smoke evidence.",
            "blocked_owner": "coordinator",
        }
    )


def _takeover_feature_review_verdict() -> FeatureReviewVerdict:
    merge = _feature_review_verdict().model_dump(mode="json")
    return FeatureReviewVerdict.model_validate(
        {
            **merge,
            "verdict_id": "fverdict_takeover_demo",
            "decision": "takeover",
            "summary": "Worker session is not recoverable.",
            "takeover_reason": "Provider session binding is stale and worker context is lost.",
            "takeover_triggers": ["worker_unrecoverable", "context_lost"],
        }
    )


def _running_feature_graph_status_from_bundle(
    bundle: FeatureEvidenceBundle,
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id="fgs-running-from-bundle",
        conversation_id=bundle.conversation_id,
        planning_run_id=bundle.planning_run_id,
        graph_set_id=bundle.graph_set_id,
        graph_set_version=bundle.graph_set_version,
        feature_plan_id=bundle.feature_plan_id,
        feature_plan_version=bundle.feature_plan_version,
        feature_id=bundle.feature_id,
        feature_graph_id=bundle.feature_graph_id,
        status=FeatureGraphExecutionStatus.RUNNING,
        ready_lane_ids=[],
        active_lane_ids=["binding-schema"],
        active_worker_session_id=bundle.worker_session_id,
        active_provider_session_binding_ref=bundle.provider_session_binding_ref,
        completed_lane_ids=[],
        blocked_lane_ids=[],
        projection_lane_ids=[
            "lane:conv-xmuse-hardening:graph-provider-session-binding:binding-schema"
        ],
        feature_lanes_projection_ref="feature_lanes.json#projection_revision=42",
        updated_at="2026-06-03T02:16:00Z",
    )


def _reviewing_feature_graph_status_from_bundle(
    bundle: FeatureEvidenceBundle,
) -> FeatureGraphExecutionStatusRecord:
    return FeatureGraphExecutionStatusRecord(
        status_id="fgs-reviewing-from-bundle",
        conversation_id=bundle.conversation_id,
        planning_run_id=bundle.planning_run_id,
        graph_set_id=bundle.graph_set_id,
        graph_set_version=bundle.graph_set_version,
        feature_plan_id=bundle.feature_plan_id,
        feature_plan_version=bundle.feature_plan_version,
        feature_id=bundle.feature_id,
        feature_graph_id=bundle.feature_graph_id,
        status=FeatureGraphExecutionStatus.REVIEWING,
        ready_lane_ids=[],
        active_lane_ids=[],
        active_worker_session_id=bundle.worker_session_id,
        active_provider_session_binding_ref=bundle.provider_session_binding_ref,
        completed_lane_ids=["binding-schema"],
        blocked_lane_ids=[],
        projection_lane_ids=[
            "lane:conv-xmuse-hardening:graph-provider-session-binding:binding-schema"
        ],
        feature_lanes_projection_ref="feature_lanes.json#projection_revision=42",
        updated_at="2026-06-03T02:17:00Z",
    )


def test_orchestrator_default_mcp_port_matches_server(setup):
    tmp_path, lanes_path = setup
    orch = PlatformOrchestrator(lanes_path=lanes_path, xmuse_root=tmp_path)

    assert orch._spawner._mcp_port == 8100


def test_orchestrator_wires_memoryos_client_into_spawner(setup):
    tmp_path, lanes_path = setup
    memoryos_client = object()
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        memoryos_client=memoryos_client,
    )

    assert orch._spawner._memoryos_client is memoryos_client


@pytest.mark.asyncio
async def test_execution_result_memoryos_metadata_is_written_to_lane(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "dispatched", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    result = SpawnResult(
        exit_code=0,
        stdout="ok",
        stderr="",
        memoryos_session_id="ses_lane_1",
        memoryos_context_attached=True,
        memoryos_ingested=True,
    )
    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock, return_value=result):
        with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=False):
            await orch._run_execution_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["memoryos_session_id"] == "ses_lane_1"
    assert lane["memoryos_context_attached"] is True
    assert lane["memoryos_ingested"] is True


def test_orchestrator_records_worker_lease_on_process_start(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "dispatched", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(lanes_path=lanes_path, xmuse_root=tmp_path)

    orch._record_worker_lease(
        "lane-1",
        4321,
        ["codex", "exec"],
        tmp_path,
    )

    lane = orch._sm.get_lane("lane-1")
    assert lane["worker_pid"] == 4321
    assert isinstance(lane["worker_started_at"], float)
    assert isinstance(lane["worker_heartbeat_at"], float)
    assert "worker_command" not in lane
    assert lane["worker_worktree"] == str(tmp_path)


@pytest.mark.asyncio
async def test_dispatch_clears_stale_worker_lease_before_new_attempt(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reworking",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "worker_pid": 123,
            "worker_started_at": 100.0,
            "worker_heartbeat_at": 100.0,
            "worker_command": ["old", "cmd"],
            "worker_worktree": "/old/worktree",
        },
    ]}))
    orch = PlatformOrchestrator(lanes_path=lanes_path, xmuse_root=tmp_path)

    async def assert_lease_cleared_before_spawn(_lane_id: str) -> None:
        lane = orch._sm.get_lane("lane-1")
        assert lane["status"] == "dispatched"
        assert lane["worker_pid"] is None
        assert lane["worker_started_at"] is None
        assert lane["worker_heartbeat_at"] is None
        assert "worker_command" not in lane
        assert lane["worker_worktree"] == str(tmp_path)

    with patch.object(
        orch,
        "_run_execution_god",
        new_callable=AsyncMock,
        side_effect=assert_lease_cleared_before_spawn,
    ):
        await orch.dispatch_lane("lane-1")


def test_orchestrator_defaults_to_codex_runtime(setup, monkeypatch):
    tmp_path, lanes_path = setup
    monkeypatch.delenv("XMUSE_GOD_RUNTIME", raising=False)
    orch = PlatformOrchestrator(lanes_path=lanes_path, xmuse_root=tmp_path)

    assert orch._execution_god.runtime == "codex"
    assert orch._review_god.runtime == "codex"


def test_orchestrator_rejects_non_codex_runtime_arg(setup, monkeypatch):
    tmp_path, lanes_path = setup
    monkeypatch.setenv("XMUSE_GOD_RUNTIME", "codex")
    with pytest.raises(ValueError, match="codex-only"):
        PlatformOrchestrator(
            lanes_path=lanes_path, xmuse_root=tmp_path, god_runtime="claude",
        )


def test_orchestrator_ignores_non_codex_runtime_env(setup, monkeypatch):
    tmp_path, lanes_path = setup
    monkeypatch.setenv("XMUSE_GOD_RUNTIME", "claude")
    orch = PlatformOrchestrator(lanes_path=lanes_path, xmuse_root=tmp_path)

    assert orch._runtime_mode == "codex"
    assert orch._execution_god.runtime == "codex"
    assert orch._review_god.runtime == "codex"


def test_orchestrator_rejects_unknown_runtime(setup, monkeypatch):
    tmp_path, lanes_path = setup
    monkeypatch.delenv("XMUSE_GOD_RUNTIME", raising=False)
    with pytest.raises(ValueError):
        PlatformOrchestrator(
            lanes_path=lanes_path, xmuse_root=tmp_path, god_runtime="grok",
        )


def test_orchestrator_rejects_mixed_runtime_arg(setup, monkeypatch):
    tmp_path, lanes_path = setup
    monkeypatch.delenv("XMUSE_GOD_RUNTIME", raising=False)
    with pytest.raises(ValueError, match="codex-only"):
        PlatformOrchestrator(
            lanes_path=lanes_path, xmuse_root=tmp_path, god_runtime="mixed",
        )


def test_orchestrator_review_god_stays_codex_even_if_lane_metadata_says_claude(
    setup, monkeypatch
):
    tmp_path, lanes_path = setup
    monkeypatch.delenv("XMUSE_GOD_RUNTIME", raising=False)
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-claude", "status": "gated", "prompt": "x",
         "worktree": str(tmp_path), "god_runtime": "claude"},
    ]}))
    orch = PlatformOrchestrator(lanes_path=lanes_path, xmuse_root=tmp_path)

    assert orch._god_picker.pick_review("lane-claude").runtime == "codex"


@pytest.mark.asyncio
async def test_review_god_does_not_retransition_already_gated_lane(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    review_result = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"


@pytest.mark.asyncio
async def test_review_transport_receives_provider_invocation(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    captured: dict[str, object] = {}

    async def fake_send_review(req):
        captured["provider_invocation"] = req.provider_invocation
        return ReviewVerdict(
            passed=False,
            verdict="",
            feedback="review failed",
            raw_output="",
            exit_code=1,
        )

    with patch.object(orch._transport, "send_review", new=fake_send_review):
        await orch._run_review_god("lane-1")

    invocation = captured["provider_invocation"]
    assert invocation is not None
    assert invocation.task_type is TaskCapability.REVIEW
    assert invocation.provider_profile_ref == "codex.review"


@pytest.mark.asyncio
async def test_a2a_review_runtime_structured_verdict_marks_reviewed_without_stdout(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-a2a-review",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_runtime": "a2a",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    captured: dict[str, object] = {}

    async def fake_send_review(req):
        captured["provider_invocation"] = req.provider_invocation
        invocation = req.provider_invocation
        return ReviewVerdict(
            passed=True,
            verdict="raw",
            feedback="",
            raw_output="",
            exit_code=0,
            provider_result=ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=invocation.provider_id,
                profile_id=invocation.profile_id,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=["a2a_task:lane-a2a-review:review"],
                diagnostic_payload={
                    "a2a_content": "Verdict: merge",
                    "a2a_metadata": {
                        "xmuse_platform_review_verdict": (
                            build_a2a_platform_review_verdict_envelope(
                                lane_id="lane-a2a-review",
                                decision="merge",
                                summary="A2A structured review allows merge.",
                                evidence_refs=[
                                    "a2a_task:lane-a2a-review:review",
                                    "review:structured-envelope",
                                ],
                            )
                        )
                    },
                },
            ),
        )

    with patch.object(orch._transport, "send_review", new=fake_send_review), patch.object(
        orch,
        "on_lane_reviewed",
        new_callable=AsyncMock,
    ) as reviewed:
        await orch._run_review_god("lane-a2a-review")

    invocation = captured["provider_invocation"]
    assert invocation is not None
    assert invocation.provider_id is ProviderId.A2A
    assert invocation.provider_profile_ref == "a2a.remote"
    lane = orch._sm.get_lane("lane-a2a-review")
    assert lane["status"] == "reviewed"
    assert lane["review_decision"] == "merge"
    assert lane["review_fallback"] == "a2a_provider_result"
    assert lane["review_fallback_reason"] == "structured_a2a_platform_review_verdict"
    assert lane["review_delivery_mode"] == "a2a_provider_result"
    assert lane["review_evidence_refs"] == [
        "a2a_task:lane-a2a-review:review",
        "review:structured-envelope",
    ]
    assert lane["review_verdict_id"]
    reviewed.assert_awaited_once_with("lane-a2a-review")


@pytest.mark.asyncio
async def test_a2a_review_runtime_uses_adapter_result_contract_for_review_god(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-a2a-contract-path",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_runtime": "a2a",
        },
    ]}))

    class ContractAwareA2AClient:
        def __init__(self) -> None:
            self.requests: list[A2AProviderTaskRequest] = []

        async def invoke_task(
            self,
            request: A2AProviderTaskRequest,
        ) -> NormalizedA2ATaskResult:
            self.requests.append(request)
            expected = request.metadata["xmuse_expected_result"]
            assert isinstance(expected, dict)
            envelope_contract = expected["envelope"]
            assert isinstance(envelope_contract, dict)
            lane_id = envelope_contract["lane_id"]
            assert lane_id == "lane-a2a-contract-path"
            assert envelope_contract["authority"] == "review_plane/lane_state"
            assert envelope_contract["a2a_is_authority"] is False
            return NormalizedA2ATaskResult(
                task_id=request.task_id,
                context_id=request.context_id,
                state="TASK_STATE_COMPLETED",
                disposition="completed",
                terminal=True,
                content="Verdict: merge",
                metadata={
                    "xmuse_platform_review_verdict": (
                        build_a2a_platform_review_verdict_envelope(
                            lane_id=str(lane_id),
                            decision="merge",
                            summary="A2A contract path returns structured review.",
                            evidence_refs=[
                                f"a2a_task:{request.task_id}",
                                f"a2a_context:{request.context_id}",
                            ],
                        )
                    )
                },
                source_refs=(
                    f"a2a_task:{request.task_id}",
                    f"a2a_context:{request.context_id}",
                ),
                sdk_task={
                    "id": request.task_id,
                    "contextId": request.context_id,
                    "status": {"state": "TASK_STATE_COMPLETED"},
                },
                jsonrpc_id=request.task_id,
            )

    client = ContractAwareA2AClient()
    provider_service = RunnerProviderService(
        a2a_provider_endpoint_url="https://remote.example/a2a",
        a2a_task_client=client,
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        provider_service=provider_service,
    )

    with patch.object(orch, "on_lane_reviewed", new_callable=AsyncMock) as reviewed:
        await orch._run_review_god("lane-a2a-contract-path")

    assert len(client.requests) == 1
    request = client.requests[0]
    assert request.task_id == "lane-a2a-contract-path:review"
    assert request.context_id == "lane-a2a-contract-path"
    lane = orch._sm.get_lane("lane-a2a-contract-path")
    assert lane["status"] == "reviewed"
    assert lane["review_decision"] == "merge"
    assert lane["review_fallback"] == "a2a_provider_result"
    assert lane["review_fallback_reason"] == "structured_a2a_platform_review_verdict"
    assert lane["review_delivery_mode"] == "a2a_provider_result"
    assert lane["review_evidence_refs"] == [
        "a2a_task:lane-a2a-contract-path:review",
        "a2a_context:lane-a2a-contract-path",
    ]
    reviewed.assert_awaited_once_with("lane-a2a-contract-path")


@pytest.mark.asyncio
async def test_a2a_review_runtime_verdict_does_not_override_transport_failure(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-a2a-review-nonzero",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_runtime": "a2a",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    async def fake_send_review(req):
        invocation = req.provider_invocation
        return ReviewVerdict(
            passed=False,
            verdict="raw",
            feedback="provider failed",
            raw_output="",
            exit_code=2,
            provider_result=ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=invocation.provider_id,
                profile_id=invocation.profile_id,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=["a2a_task:lane-a2a-review-nonzero:review"],
                diagnostic_payload={
                    "a2a_metadata": {
                        "xmuse_platform_review_verdict": (
                            build_a2a_platform_review_verdict_envelope(
                                lane_id="lane-a2a-review-nonzero",
                                decision="merge",
                                summary="This must not override transport failure.",
                                evidence_refs=[
                                    "a2a_task:lane-a2a-review-nonzero:review",
                                ],
                            )
                        )
                    },
                },
            ),
        )

    with patch.object(orch._transport, "send_review", new=fake_send_review), patch.object(
        orch,
        "on_lane_reviewed",
        new_callable=AsyncMock,
    ) as reviewed:
        await orch._run_review_god("lane-a2a-review-nonzero")

    lane = orch._sm.get_lane("lane-a2a-review-nonzero")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_non_zero_exit"
    reviewed.assert_not_awaited()


@pytest.mark.asyncio
async def test_a2a_review_runtime_rejects_content_only_verdict(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-a2a-content-only-review",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_runtime": "a2a",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    async def fake_send_review(req):
        invocation = req.provider_invocation
        return ReviewVerdict(
            passed=True,
            verdict="raw",
            feedback="",
            raw_output="",
            exit_code=0,
            provider_result=ProviderInvocationResult(
                request_id=invocation.request_id,
                provider_id=invocation.provider_id,
                profile_id=invocation.profile_id,
                status=WorkerResultStatus.COMPLETED,
                evidence_refs=["a2a_task:lane-a2a-content-only-review:review"],
                diagnostic_payload={
                    "a2a_content": "Verdict: merge\nNo findings.",
                    "a2a_metadata": {},
                },
            ),
        )

    with patch.object(orch._transport, "send_review", new=fake_send_review), patch.object(
        orch,
        "on_lane_reviewed",
        new_callable=AsyncMock,
    ) as reviewed:
        await orch._run_review_god("lane-a2a-content-only-review")

    lane = orch._sm.get_lane("lane-a2a-content-only-review")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"
    reviewed.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_review_god_prefers_provider_binding_resume_over_persistent_session(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
    ]}))
    binding_store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = binding_store.upsert_active(
        _provider_session_binding(
            worktree=str(tmp_path),
            session_kind="review",
            role="reviewer",
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        review_god_session_layer=object(),
        provider_session_binding_store=binding_store,
    )
    captured: dict[str, object] = {}

    async def fake_send_review(req):
        captured["provider_session_binding"] = req.provider_session_binding
        return ReviewVerdict(
            passed=False,
            verdict="",
            feedback="review failed",
            raw_output="",
            exit_code=1,
        )

    with patch.object(
        orch._transport,
        "send_review",
        new=fake_send_review,
    ), patch(
        "xmuse_core.platform.execution.review_god._try_persistent_review",
        new_callable=AsyncMock,
        side_effect=AssertionError("persistent review should not be used"),
    ) as persistent_review:
        await orch._run_review_god("lane-1")

    assert captured["provider_session_binding"] == binding
    assert persistent_review.await_count == 0
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_non_zero_exit"


@pytest.mark.asyncio
async def test_run_review_god_reroutes_provider_resume_failure_to_persistent_review(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-feature-a",
            "provider_session_binding_god_session_id": "god-worker-demo",
        },
    ]}))
    binding_store = ProviderSessionBindingStore(tmp_path / "provider_session_bindings.json")
    binding = binding_store.upsert_active(
        _provider_session_binding(
            worktree=str(tmp_path),
            session_kind="review",
            role="reviewer",
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        review_god_session_layer=object(),
        provider_session_binding_store=binding_store,
    )
    captured: dict[str, object] = {}

    async def fake_send_review(req):
        captured["provider_session_binding"] = req.provider_session_binding
        return ReviewVerdict(
            passed=False,
            verdict="",
            feedback="stale review resume",
            raw_output="",
            exit_code=1,
            provider_result=ProviderInvocationResult(
                request_id=req.provider_invocation.request_id,
                provider_id=req.provider_invocation.provider_id,
                profile_id=req.provider_invocation.profile_id,
                status=WorkerResultStatus.FAILED,
                failure_kind=ProviderFailureKind.STALE_REQUEST,
                evidence_refs=[],
            ),
        )

    with patch.object(orch._transport, "send_review", new=fake_send_review), patch(
        "xmuse_core.platform.execution.review_god._try_persistent_review",
        new_callable=AsyncMock,
        return_value=True,
    ) as persistent_review:
        await orch._run_review_god("lane-1")

    assert captured["provider_session_binding"] == binding
    assert persistent_review.await_count == 1
    assert (
        binding_store.get(binding.binding_id).status
        is ProviderSessionBindingStatus.STALE
    )


@pytest.mark.asyncio
async def test_mcp_reviewed_status_triggers_auto_merge(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        result = orch._tools.call("update_lane_status", {
            "lane_id": "lane-1",
            "status": "reviewed",
            "audit": {
                "actor": "review_god",
                "reason": "accept review verdict",
                "request_id": "req-orch-review-2",
            },
            "guard": {"current_status": "gated"},
        })
        await asyncio.sleep(0.1)

    assert result["status"] == "reviewed"
    assert orch._sm.get_lane("lane-1")["status"] == "merged"


@pytest.mark.asyncio
async def test_reconcile_external_reviewed_status_triggers_auto_merge(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "reviewed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.reconcile_status_changes()

    assert orch._sm.get_lane("lane-1")["status"] == "merged"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_reviewed_skips_when_graph_native_disallows_review(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "reviewed",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-merged",
            status=FeatureGraphExecutionStatus.MERGED,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "on_lane_reviewed", new_callable=AsyncMock) as reviewed:
        await orch.reconcile_status_changes()

    reviewed.assert_not_awaited()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "reviewed"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_reviewed_merges_when_graph_native_allows_review(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "reviewed",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reviewing",
            status=FeatureGraphExecutionStatus.REVIEWING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.reconcile_status_changes()

    assert orch._sm.get_lane("lane-1")["status"] == "merged"


@pytest.mark.asyncio
async def test_reconcile_external_executed_status_runs_gate_and_review(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "executed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=True) as gate:
        with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
            await orch.reconcile_status_changes()

    assert orch._sm.get_lane("lane-1")["status"] == "gated"
    gate.assert_awaited_once_with("lane-1")
    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_reconcile_graph_backed_executed_skips_when_graph_native_disallows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "executed",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reviewing",
            status=FeatureGraphExecutionStatus.REVIEWING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_on_lane_executed", new_callable=AsyncMock) as executed:
        await orch.reconcile_status_changes()

    executed.assert_not_awaited()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "executed"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_executed_runs_when_graph_native_allows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "executed",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-running",
            status=FeatureGraphExecutionStatus.RUNNING,
            ready_lane_ids=[],
            active_lane_ids=["lane-1"],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=True) as gate:
        with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
            await orch.reconcile_status_changes()

    assert orch._sm.get_lane("lane-1")["status"] == "gated"
    gate.assert_awaited_once_with("lane-1")
    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_mcp_executed_status_triggers_gate_and_review(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "dispatched", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=True) as gate:
        with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
            result = orch._tools.call("update_lane_status", {
                "lane_id": "lane-1",
                "status": "executed",
                "audit": {
                    "actor": "execute_god",
                    "reason": "worker finished focused lane task",
                    "request_id": "req-orch-exec-1",
                },
                "guard": {"current_status": "dispatched"},
            })
            await asyncio.sleep(0.1)

    assert result["status"] == "executed"
    assert orch._sm.get_lane("lane-1")["status"] == "gated"
    gate.assert_awaited_once_with("lane-1")
    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_mcp_reworking_status_redispatches_without_direct_merge_bypass(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "exec_failed",
            "prompt": "repair and retry",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with patch.object(orch, "_auto_merge", new_callable=AsyncMock) as auto_merge:
            result = orch._tools.call("update_lane_status", {
                "lane_id": "lane-1",
                "status": "reworking",
                "audit": {
                    "actor": "review_god",
                    "reason": "takeover repair should retry through platform",
                    "request_id": "req-orch-takeover-1",
                },
                "guard": {"current_status": "exec_failed"},
            })
            await asyncio.sleep(0.1)

    assert result["status"] == "reworking"
    assert orch._sm.get_lane("lane-1")["status"] == "reworking"
    dispatch.assert_awaited_once_with("lane-1")
    auto_merge.assert_not_awaited()


@pytest.mark.asyncio
async def test_concurrent_executed_handlers_do_not_double_transition(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "executed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_gate", new_callable=AsyncMock,
                      return_value=True) as gate:
        with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
            await asyncio.gather(
                orch._on_lane_executed("lane-1"),
                orch._on_lane_executed("lane-1"),
            )

    assert orch._sm.get_lane("lane-1")["status"] == "gated"
    assert gate.await_count >= 1
    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_concurrent_reworking_dispatch_claims_lane_once(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reworking",
            "prompt": "repair and retry",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_execution_god", new_callable=AsyncMock) as run_exec:
        with patch.object(
            orch,
            "_record_lane_memory_event",
            new_callable=AsyncMock,
        ) as record_memory:
            await asyncio.gather(
                orch.dispatch_lane("lane-1"),
                orch.dispatch_lane("lane-1"),
            )

    assert orch._sm.get_lane("lane-1")["status"] == "dispatched"
    run_exec.assert_awaited_once_with("lane-1")
    record_memory.assert_awaited_once()


@pytest.mark.asyncio
async def test_reconcile_external_reworking_status_redispatches_without_direct_merge(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reworking",
            "prompt": "repair and retry",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        with patch.object(orch, "_auto_merge", new_callable=AsyncMock) as auto_merge:
            await orch.reconcile_status_changes()

    dispatch.assert_awaited_once_with("lane-1")
    auto_merge.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_graph_backed_reworking_skips_when_graph_native_disallows_dispatch(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "reworking",
                        "prompt": "repair and retry",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reviewing",
            status=FeatureGraphExecutionStatus.REVIEWING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        await orch.reconcile_status_changes()

    dispatch.assert_not_called()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "reworking"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_reworking_redispatches_when_graph_native_allows_dispatch(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "reworking",
                        "prompt": "repair and retry",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reworking",
            status=FeatureGraphExecutionStatus.REWORKING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        await orch.reconcile_status_changes()

    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_reconcile_graph_backed_reworking_redispatches_with_stale_pending_projection(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "pending",
                        "prompt": "repair and retry",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reworking",
            status=FeatureGraphExecutionStatus.REWORKING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        await orch.reconcile_status_changes()

    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_reconcile_graph_backed_rejected_skips_when_graph_native_disallows_review(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "rejected",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reworking",
            status=FeatureGraphExecutionStatus.REWORKING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "on_lane_rejected", new_callable=AsyncMock) as rejected:
        await orch.reconcile_status_changes()

    rejected.assert_not_awaited()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "rejected"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_rejected_reworks_when_graph_native_allows_review(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "rejected",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reviewing",
            status=FeatureGraphExecutionStatus.REVIEWING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
        await orch.reconcile_status_changes()

    dispatch.assert_awaited_once_with("lane-1")
    assert orch._sm.get_lane("lane-1")["status"] == "reworking"


@pytest.mark.asyncio
async def test_reconcile_recovers_gated_lane_without_review_start(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_reconcile_graph_backed_gated_skips_when_review_authority_disallows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "gated",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "gate_passed": True,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-ready",
            status=FeatureGraphExecutionStatus.READY,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_not_awaited()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "gated"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_gated_recovers_when_review_authority_allows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "gated",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "gate_passed": True,
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reviewing",
            status=FeatureGraphExecutionStatus.REVIEWING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_reconcile_recovers_gated_lane_from_previous_runner(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "review_started_at": 100.0,
            "review_runner_id": "runner-old",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        runner_id="runner-new",
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_reconcile_does_not_restart_current_runner_review(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "review_started_at": time.time(),
            "review_runner_id": "runner-current",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        runner_id="runner-current",
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_not_awaited()


@pytest.mark.asyncio
async def test_reconcile_runs_executed_lane_gate_review_batch_concurrently(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "executed", "prompt": "fix", "worktree": str(tmp_path)},
        {"feature_id": "lane-2", "status": "executed", "prompt": "fix", "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    both_started = asyncio.Event()
    started: list[str] = []

    async def handler(lane_id: str) -> None:
        started.append(lane_id)
        if len(started) == 2:
            both_started.set()
        await both_started.wait()

    with patch.object(orch, "_on_lane_executed", side_effect=handler) as gate_review:
        await asyncio.wait_for(orch.reconcile_status_changes(), timeout=1.0)

    assert set(started) == {"lane-1", "lane-2"}
    assert gate_review.await_count == 2


@pytest.mark.asyncio
async def test_reconcile_runs_entire_ready_gate_review_batch_by_default(
    setup,
    monkeypatch,
):
    tmp_path, lanes_path = setup
    monkeypatch.delenv("XMUSE_RECONCILE_GATE_REVIEW_CONCURRENCY", raising=False)
    lane_count = 24
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": f"lane-{idx}",
            "status": "executed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        }
        for idx in range(lane_count)
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    all_started = asyncio.Event()
    started: set[str] = set()

    async def handler(lane_id: str) -> None:
        started.add(lane_id)
        if len(started) == lane_count:
            all_started.set()
        await all_started.wait()

    with patch.object(orch, "_on_lane_executed", side_effect=handler) as gate_review:
        await asyncio.wait_for(orch.reconcile_status_changes(), timeout=1.0)

    assert len(started) == lane_count
    assert gate_review.await_count == lane_count


@pytest.mark.asyncio
async def test_reconcile_honors_explicit_gate_review_concurrency_limit(
    setup,
    monkeypatch,
):
    tmp_path, lanes_path = setup
    monkeypatch.setenv("XMUSE_RECONCILE_GATE_REVIEW_CONCURRENCY", "2")
    lane_count = 5
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": f"lane-{idx}",
            "status": "executed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        }
        for idx in range(lane_count)
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    active = 0
    max_active = 0

    async def handler(_lane_id: str) -> None:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        active -= 1

    with patch.object(orch, "_on_lane_executed", side_effect=handler) as gate_review:
        await orch.reconcile_status_changes()

    assert gate_review.await_count == lane_count
    assert max_active <= 2


@pytest.mark.asyncio
async def test_reconcile_invalid_gate_review_concurrency_uses_safe_cap(
    setup,
    monkeypatch,
):
    tmp_path, lanes_path = setup
    monkeypatch.setenv("XMUSE_RECONCILE_GATE_REVIEW_CONCURRENCY", "not-a-number")
    lane_count = 24
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": f"lane-{idx}",
            "status": "executed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        }
        for idx in range(lane_count)
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    first_wave_started = asyncio.Event()
    release_first_wave = asyncio.Event()
    started: set[str] = set()
    first_wave: set[str] = set()

    async def handler(lane_id: str) -> None:
        started.add(lane_id)
        if not first_wave_started.is_set():
            first_wave.add(lane_id)
            if len(first_wave) == 16:
                first_wave_started.set()
            await first_wave_started.wait()
            await release_first_wave.wait()

    with patch.object(orch, "_on_lane_executed", side_effect=handler) as gate_review:
        task = asyncio.create_task(orch.reconcile_status_changes())
        await asyncio.wait_for(first_wave_started.wait(), timeout=1.0)
        assert len(started) == 16
        release_first_wave.set()
        await asyncio.wait_for(task, timeout=1.0)

    assert gate_review.await_count == lane_count
    assert len(started) == lane_count


@pytest.mark.asyncio
async def test_gate_failure_marks_lane_gate_failed_and_skips_review(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "executed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=False):
        with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
            await orch._on_lane_executed("lane-1")

    assert orch._sm.get_lane("lane-1")["status"] == "gate_failed"
    review.assert_not_called()


@pytest.mark.asyncio
async def test_on_lane_executed_attaches_chat_acceptance_spine_execution_evidence(
    tmp_path: Path,
) -> None:
    db = tmp_path / "chat.db"
    service = PeerChatService(db)
    created = service.create_conversation(title="Lane execution acceptance spine")
    conversation_id = created["conversation"]["id"]
    intake = service.post_human_message(
        conversation_id=conversation_id,
        author="Human operator",
        content="Run this approved lane through the platform worker.",
        client_request_id="lane-exec-spine-intake",
    )
    proposal = ChatStore(db).create_proposal(
        conversation_id=conversation_id,
        author="architect",
        proposal_type="lane_graph",
        content='{"summary":"execute proposal","lanes":[]}',
        references=[f"intake_message:{intake.message.id}"],
    )
    resolution = ChatStore(db).approve_proposal(
        proposal.id,
        approved_by=["human"],
        approval_mode="manual",
        goal_summary="Approve lane execution.",
        content={"type": "lane_graph", "lanes": []},
    )
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conversation_id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id="collab-lane-exec",
        artifact_ref="artifact:lane_graph",
    )
    ChatDispatchQueueStore(db).claim_next_auto_dispatch(
        conversation_id=conversation_id,
        claimed_by="dispatch-bridge-test",
    )
    ChatDispatchQueueStore(db).mark_dispatched(
        dispatch.entry_id,
        provider_run_ref="peer_ack:execute:participant-1",
        dispatch_evidence="mcp_writeback:dispatch-1",
    )
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-accepted-exec",
                        "status": "executed",
                        "prompt": "Implement the approved lane.",
                        "worktree": str(tmp_path),
                        "resolution_id": resolution.id,
                        "graph_id": f"{resolution.id}-graph-v1",
                        "dispatch_attempt_id": "dispatch-lane-accepted-exec-abc123",
                        "provider_session_binding_id": "binding-lane-accepted-exec",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=False):
        await orch._on_lane_executed("lane-accepted-exec")

    lane = orch._sm.get_lane("lane-accepted-exec")
    spine = AcceptanceSpineStore(db).get_by_intake_message(intake.message.id)
    assert lane["status"] == "gate_failed"
    assert spine.status is AcceptanceSpineStatus.EXECUTED
    assert spine.execution_evidence_refs == [
        "peer_ack:execute:participant-1",
        "mcp_writeback:dispatch-1",
        "feature_lanes.json#lane=lane-accepted-exec:status=executed",
        f"lane_graph:{resolution.id}-graph-v1",
        "dispatch_attempt:dispatch-lane-accepted-exec-abc123",
        "provider_session_binding:binding-lane-accepted-exec",
    ]


@pytest.mark.asyncio
async def test_gate_failure_transition_is_rejected_without_failure_reason(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "executed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with pytest.raises(StateValidationError, match="failure_reason"):
        orch._sm.transition("lane-1", "gate_failed")

    assert orch._sm.get_lane("lane-1")["status"] == "executed"


@pytest.mark.asyncio
async def test_run_gate_uses_plural_gate_profiles(setup):
    tmp_path, lanes_path = setup
    (tmp_path / "gate_profiles.json").write_text(json.dumps({
        "schema_version": 1,
        "defaults": {
            "full_gate_profile": "strict-product",
            "full_gate_interval": 20,
            "unknown_diff_policy": "strict-product",
            "unclassified_test_policy": "fail",
        },
        "command_catalog": {
            "noop": {
                "argv": ["true"],
                "cwd": ".",
                "timeout_s": 0,
                "allow_extra_args": False,
            }
        },
        "profiles": {
            "strict-product": {
                "description": "strict",
                "blocking": True,
                "env": {},
                "commands": [{"command": "noop", "args": []}],
                "diff_selectors": ["src/memoryos_lite/**"],
                "test_files": ["tests/xmuse/test_platform_orchestrator.py"],
                "test_nodeids": [],
                "test_markers": [],
                "mixed_test_files": [],
            },
            "xmuse-core": {
                "description": "xmuse",
                "blocking": True,
                "env": {},
                "commands": [{"command": "noop", "args": []}],
                "diff_selectors": ["src/xmuse_core/**"],
                "test_files": ["tests/xmuse/test_platform_orchestrator.py"],
                "test_nodeids": [],
                "test_markers": [],
                "mixed_test_files": [],
            },
        },
    }))
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "executed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_profiles": ["xmuse-core"],
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def fake_run(plan):
        assert plan.profiles == ["xmuse-core"]
        assert plan.warnings == [
            "explicit gate_profiles selected; full dirty-worktree "
            "coverage is recorded but not used to reject this lane"
        ]
        return GateReport(
            feature_id=plan.feature_id,
            passed=True,
            blocking_passed=True,
            nonblocking_failures=[],
            profile_ids=plan.profiles,
            resolution_reasons=plan.resolution_reasons,
            command_results=[],
            artifact_dir=tmp_path / "logs" / "gates" / "lane-1",
            warnings=[],
        )

    with patch(
        "xmuse_core.platform.execution.gate.get_changed_paths",
        return_value=[
            "src/xmuse_core/platform/orchestrator.py",
            "src/memoryos_lite/config.py",
        ],
    ):
        with patch("xmuse_core.gates.runner.GateRunner.run", side_effect=fake_run):
            assert await orch._run_gate("lane-1") is True


@pytest.mark.asyncio
async def test_run_gate_fails_closed_when_gate_profiles_missing(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "executed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    assert await orch._run_gate("lane-1") is False

    report_path = tmp_path / "logs" / "gates" / "lane-1" / "report.json"
    assert report_path.exists()
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is False
    assert report["blocking_passed"] is False
    assert report["profile_ids"] == []
    assert report["command_results"] == []
    assert report["resolution_reasons"] == {
        "gate_profiles": ["gate_profiles_missing"],
    }
    assert report["worktree"] == str(tmp_path)


@pytest.mark.asyncio
async def test_run_gate_uses_worktree_gate_profiles_when_runtime_root_missing(setup):
    tmp_path, lanes_path = setup
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "xmuse").mkdir()
    (repo / "gate_profiles.json").write_text("runtime config must not be used")
    (repo / "xmuse" / "gate_profiles.json").write_text(json.dumps({
        "schema_version": 1,
        "defaults": {
            "full_gate_profile": "strict-product",
            "full_gate_interval": 20,
            "unknown_diff_policy": "strict-product",
            "unclassified_test_policy": "fail",
        },
        "command_catalog": {
            "noop": {
                "argv": ["true"],
                "cwd": ".",
                "timeout_s": 0,
                "allow_extra_args": False,
            }
        },
        "profiles": {
            "strict-product": {
                "description": "strict",
                "blocking": True,
                "env": {},
                "commands": [{"command": "noop", "args": []}],
                "diff_selectors": ["**"],
                "test_files": ["tests/xmuse/test_platform_orchestrator.py"],
                "test_nodeids": [],
                "test_markers": [],
                "mixed_test_files": [],
            },
            "historical": {
                "description": "historical",
                "blocking": False,
                "env": {},
                "commands": [],
                "diff_selectors": [],
                "test_files": ["tests/test_agent.py"],
                "test_nodeids": [],
                "test_markers": [],
                "mixed_test_files": [],
            },
        },
    }))
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "executed",
            "prompt": "fix",
            "worktree": str(repo),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    assert await orch._run_gate("lane-1") is True

    report_path = tmp_path / "logs" / "gates" / "lane-1" / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["passed"] is True
    assert report["blocking_passed"] is True
    assert report["profile_ids"] == ["strict-product"]
    assert report["resolution_reasons"] == {
        "strict-product": ["unknown_diff_policy"],
    }
    assert report["gate_profiles_source"] == {
        "source": "lane_worktree_fallback",
        "selected_path": str(repo / "xmuse" / "gate_profiles.json"),
        "xmuse_root_path": str(tmp_path / "gate_profiles.json"),
        "lane_worktree_path": str(repo / "xmuse" / "gate_profiles.json"),
    }
    assert report["warnings"] == [
        "gate_profiles.json missing in XMUSE_ROOT; "
        "using lane worktree xmuse/gate_profiles.json"
    ]


@pytest.mark.asyncio
async def test_reconcile_recovers_review_timeout_by_rerunning_review(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_timeout",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gated"
    assert lane["review_retry_count"] == 1
    assert lane["review_recovered_from"] == "review_timeout"
    assert "failure_reason" not in lane
    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_reconcile_graph_backed_gate_failed_skips_retry_when_graph_native_disallows_review(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "gate_failed",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "gate_passed": True,
                        "failure_reason": "review_timeout",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reworking",
            status=FeatureGraphExecutionStatus.REWORKING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_not_called()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "gate_failed"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_gate_failed_retries_when_graph_native_allows_review(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "gate_failed",
                        "prompt": "fix",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                        "gate_passed": True,
                        "failure_reason": "review_timeout",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reviewing",
            status=FeatureGraphExecutionStatus.REVIEWING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_awaited_once_with("lane-1")
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gated"
    assert lane["review_retry_count"] == 1
    assert lane["review_recovered_from"] == "review_timeout"


@pytest.mark.asyncio
async def test_reconcile_recovers_review_no_verdict_by_rerunning_review(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_no_verdict",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gated"
    assert lane["review_retry_count"] == 1
    assert lane["review_recovered_from"] == "review_no_verdict"
    assert "failure_reason" not in lane
    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_non_zero_exit_marks_gate_failed(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    review_result = SpawnResult(exit_code=1, stdout="", stderr="boom")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_non_zero_exit"


@pytest.mark.asyncio
async def test_review_god_non_zero_exit_honors_committed_rework_status(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def review_updates_status_then_crashes(*, god_config, lane_id, prompt, worktree):
        orch._sm.transition(
            lane_id,
            "rejected",
            metadata={
                "review_decision": "rework",
                "review_summary": "MCP committed rework verdict.",
            },
        )
        return SpawnResult(exit_code=1, stdout="", stderr="transport closed")

    with patch.object(orch._spawner, "spawn", side_effect=review_updates_status_then_crashes):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_summary"] == "MCP committed rework verdict."
    assert "failure_reason" not in lane
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_transient_exit_honors_committed_rework_without_retry(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    orch._recovery.config = orch._recovery.config.__class__(
        max_attempts=2,
        initial_delay_s=0,
        max_delay_s=0,
    )
    spawn_calls = 0

    async def review_updates_status_then_hits_502(*, god_config, lane_id, prompt, worktree):
        nonlocal spawn_calls
        spawn_calls += 1
        orch._sm.transition(
            lane_id,
            "rejected",
            metadata={
                "review_decision": "rework",
                "review_summary": "MCP committed rework before provider failure.",
            },
        )
        return SpawnResult(
            exit_code=1,
            stdout="",
            stderr="ERROR: unexpected status 502 Bad Gateway",
        )

    with patch.object(orch._spawner, "spawn", side_effect=review_updates_status_then_hits_502):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert spawn_calls == 1
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_summary"] == "MCP committed rework before provider failure."
    assert "failure_reason" not in lane
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_timeout_honors_committed_rework_status(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    async def review_updates_status_then_times_out(*, god_config, lane_id, prompt, worktree):
        orch._sm.transition(
            lane_id,
            "rejected",
            metadata={
                "review_decision": "rework",
                "review_summary": "MCP committed rework before timeout.",
            },
        )
        return SpawnResult(exit_code=-1, stdout="", stderr="timeout", timed_out=True)

    with patch.object(orch._spawner, "spawn", side_effect=review_updates_status_then_times_out):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_summary"] == "MCP committed rework before timeout."
    assert "failure_reason" not in lane
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_empty_stdout_honors_committed_reviewed_status(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )

    async def review_updates_status_then_emits_no_stdout(*, god_config, lane_id, prompt, worktree):
        orch._sm.transition(
            lane_id,
            "reviewed",
            metadata={
                "review_decision": "merge",
                "review_summary": "MCP committed merge before empty stdout.",
            },
        )
        return SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(
        orch._spawner,
        "spawn",
        side_effect=review_updates_status_then_emits_no_stdout,
    ):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_decision"] == "merge"
    assert lane["review_summary"] == "MCP committed merge before empty stdout."
    assert "failure_reason" not in lane


@pytest.mark.asyncio
async def test_review_god_non_zero_exit_honors_committed_reviewed_status(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )

    async def review_updates_status_then_crashes(*, god_config, lane_id, prompt, worktree):
        orch._sm.transition(
            lane_id,
            "reviewed",
            metadata={
                "review_decision": "merge",
                "review_summary": "MCP committed merge verdict.",
            },
        )
        return SpawnResult(exit_code=1, stdout="", stderr="transport closed")

    with patch.object(orch._spawner, "spawn", side_effect=review_updates_status_then_crashes):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_decision"] == "merge"
    assert lane["review_summary"] == "MCP committed merge verdict."
    assert "failure_reason" not in lane


@pytest.mark.asyncio
async def test_review_god_usage_limit_marks_infra_unavailable_with_backoff(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=1,
        stdout="",
        stderr="ERROR: You've hit your usage limit. Try again later.",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_infra_unavailable"
    assert lane["review_infra_reason"] == "usage_limit"
    assert lane["review_retry_after_at"] > lane["review_started_at"]


@pytest.mark.asyncio
async def test_reconcile_waits_for_review_infra_backoff(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_infra_unavailable",
            "review_retry_after_at": 9999999999,
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    assert orch._sm.get_lane("lane-1")["status"] == "gate_failed"
    review.assert_not_called()


@pytest.mark.asyncio
async def test_reconcile_recovers_review_infra_failure_after_backoff(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_infra_unavailable",
            "review_retry_after_at": 1,
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gated"
    assert lane["review_retry_count"] == 1
    assert lane["review_recovered_from"] == "review_infra_unavailable"
    assert "failure_reason" not in lane
    review.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_approves_when_mcp_status_missing(setup):
    tmp_path, lanes_path = setup
    gate_report = tmp_path / "logs" / "gates" / "lane-1" / "report.json"
    gate_report.parent.mkdir(parents=True, exist_ok=True)
    gate_report.write_text("{}", encoding="utf-8")
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "prompt_ref": "logs/lane_prompts/lane-1.md"},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )
    review_result = SpawnResult(exit_code=0, stdout="No findings. Approved.", stderr="")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_fallback"] == "stdout"
    assert lane["review_fallback_reason"] in {
        "approval_marker",
        "positive_no_findings",
    }
    assert lane["review_decision"] == "merge"
    assert lane["review_evidence_refs"] == [
        "feature_lanes.json#lane=lane-1",
        f"review_plane.json#task={lane['review_task_id']}",
        "logs/lane_prompts/lane-1.md",
        "logs/gates/lane-1/report.json",
    ]
    review_plane = json.loads((tmp_path / "review_plane.json").read_text())
    verdict = review_plane["review_verdicts"][0]
    assert verdict["evidence_refs"] == lane["review_evidence_refs"]
    final_actions = json.loads((tmp_path / "final_actions.json").read_text())
    assert final_actions["holds"][0]["verdict_id"] == lane["review_verdict_id"]


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_approves_none_findings_with_negated_blocking_issue(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout=(
            "**Findings**\n\n"
            "None. I did not find a blocking issue in the current lane state."
        ),
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_fallback"] == "stdout"
    assert lane["review_fallback_reason"] == "positive_none"
    assert lane["review_decision"] == "merge"


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_approves_common_empty_findings_prose(
    setup,
):
    tmp_path, lanes_path = setup
    for stdout in (
        "**Findings**\n\nNone. I did not find any issues.",
        "**Findings**\n\nNo issues were found.",
    ):
        lanes_path.write_text(json.dumps({"lanes": [
            {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
             "worktree": str(tmp_path)},
        ]}))
        orch = PlatformOrchestrator(
            lanes_path=lanes_path,
            xmuse_root=tmp_path,
            mcp_port=9999,
            require_final_action_approval=True,
        )
        review_result = SpawnResult(exit_code=0, stdout=stdout, stderr="")

        with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                          return_value=review_result):
            await orch._run_review_god("lane-1")

        lane = orch._sm.get_lane("lane-1")
        assert lane["status"] == "awaiting_final_action"
        assert lane["review_fallback"] == "stdout"
        assert lane["review_decision"] == "merge"


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_blocking_findings(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(exit_code=0, stdout="**Findings**\n1. High: bug", stderr="")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_fallback"] == "stdout"
    assert lane["review_fallback_reason"] == "severity_finding"
    assert lane["review_decision"] == "rework"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_findings_even_with_approved_word(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n1. High: approved review can still stall",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_markdown_heading_findings(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="## Findings\n- Missing coverage. No findings in tests.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] in {"findings_section", "missing_coverage"}
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_no_findings_prefix_inside_findings(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="## Findings\n- No findings in tests; missing coverage.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] in {"findings_section", "missing_coverage"}
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_no_issues_prefix_inside_findings(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n\nNo issues were found in tests; missing coverage remains.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] in {
        "findings_section",
        "unresolved_finding",
    }
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_global_no_issues_prefix_with_issue(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="No issues were found in tests; missing coverage remains.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "unresolved_finding"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_common_rejection_prose(setup):
    tmp_path, lanes_path = setup
    cases = (
        ("I would not merge this yet; tests are absent.", "explicit_rejection"),
        ("This is not ready to merge; validation is incomplete.", "explicit_rejection"),
        ("Needs rework before merge.", "needs_rework"),
        ("The change is not acceptable for merge.", "explicit_rejection"),
    )
    for stdout, expected_reason in cases:
        lanes_path.write_text(json.dumps({"lanes": [
            {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
             "worktree": str(tmp_path)},
        ]}))
        orch = PlatformOrchestrator(
            lanes_path=lanes_path,
            xmuse_root=tmp_path,
            mcp_port=9999,
        )
        review_result = SpawnResult(exit_code=0, stdout=stdout, stderr="")

        with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                          return_value=review_result):
            with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
                await orch._run_review_god("lane-1")

        lane = orch._sm.get_lane("lane-1")
        assert lane["status"] == "reworking"
        assert lane["review_decision"] == "rework"
        assert lane["review_fallback_reason"] == expected_reason
        dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_reproduced_findings(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout=(
            "No findings claimed by the fallback summary, but the rework "
            "finding still reproduces in the live code."
        ),
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "reproduced_finding"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_explicit_not_approved(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n- Missing coverage; not approved.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "explicit_rejection"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_cannot_approve(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Cannot approve: missing tests.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "explicit_rejection"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_do_not_merge(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Do not merge: missing tests.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "explicit_rejection"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_reject_marker(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Reject: missing tests.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "explicit_rejection"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_findings_section_despite_no_findings(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n- Missing coverage. No findings in tests.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] in {"findings_section", "missing_coverage"}
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_empty_stdout_marks_review_no_verdict(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path), "gate_passed": True},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(exit_code=0, stdout="", stderr="")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_no_verdict"


@pytest.mark.asyncio
async def test_dispatch_lane_waits_for_execution_lifecycle(setup):
    tmp_path, lanes_path = setup
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    gate = asyncio.Event()

    async def wait_for_gate(_: str) -> None:
        await gate.wait()

    with patch.object(orch, "_run_execution_god", side_effect=wait_for_gate):
        task = asyncio.create_task(orch.dispatch_lane("lane-1"))
        await asyncio.sleep(0)

        assert not task.done()
        gate.set()
        await task


@pytest.mark.asyncio
async def test_reviewed_lane_enters_final_action_hold_when_enabled(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "reviewed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )

    await orch.reconcile_status_changes()

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "awaiting_final_action"
    assert lane["final_action_hold_id"]
    holds = orch._final_action_store.list_actions()
    assert len(holds) == 1
    assert holds[0].action == "merge"


@pytest.mark.asyncio
async def test_reviewed_lane_without_branch_fails_merge_guard(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "reviewed", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )

    await orch.on_lane_reviewed("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "failed"
    assert lane["failure_reason"] == "merge_context_missing"


@pytest.mark.asyncio
async def test_reconcile_status_changes_projects_newly_ready_dependents_for_merged_lane(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "conversation_id": "conv-1",
            "resolution_id": "res-1",
            "graph_id": "graph-1",
            "graph_version": 1,
        },
    ]}))
    graph_dir = tmp_path / "lane_graphs"
    graph_dir.mkdir(parents=True)
    (graph_dir / "graph-1.json").write_text(json.dumps({
        "id": "graph-1",
        "conversation_id": "conv-1",
        "resolution_id": "res-1",
        "version": 1,
        "status": "planned",
        "lanes": [
            {
                "feature_id": "lane-1",
                "prompt": "build chat",
                "priority": 90,
                "depends_on": [],
            },
            {
                "feature_id": "lane-2",
                "prompt": "build dashboard",
                "priority": 60,
                "depends_on": ["lane-1"],
            },
        ],
    }))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    await orch.reconcile_status_changes()
    await orch.reconcile_status_changes()

    lanes = json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"]
    assert [lane["feature_id"] for lane in lanes] == ["lane-1", "lane-2"]
    assert lanes[1]["status"] == "pending"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_merged_skips_reprojection_when_graph_native_disallows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "merged",
                        "prompt": "build chat",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reviewing",
            status=FeatureGraphExecutionStatus.REVIEWING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch(
        "xmuse_core.platform.orchestrator.reproject_dependents_if_needed",
        new_callable=AsyncMock,
    ) as reproject:
        await orch.reconcile_status_changes()

    reproject.assert_not_awaited()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "merged"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_merged_reprojects_when_graph_native_allows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "merged",
                        "prompt": "build chat",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-merged",
            status=FeatureGraphExecutionStatus.MERGED,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch(
        "xmuse_core.platform.orchestrator.reproject_dependents_if_needed",
        new_callable=AsyncMock,
    ) as reproject:
        await orch.reconcile_status_changes()

    reproject.assert_awaited_once_with(
        "lane-1",
        sm=orch._sm,
        graph_store=orch._graph_store,
    )


@pytest.mark.asyncio
async def test_reconcile_reprojects_merged_dependents(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch(
        "xmuse_core.platform.orchestrator.reproject_dependents_if_needed",
        new_callable=AsyncMock,
    ) as reproject:
        await orch.reconcile_status_changes()

    reproject.assert_awaited_once_with(
        "lane-1",
        sm=orch._sm,
        graph_store=orch._graph_store,
    )


@pytest.mark.asyncio
async def test_reconcile_graph_backed_failed_skips_reprojection_when_graph_native_disallows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "failed",
                        "prompt": "build chat",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    before_projection = lanes_path.read_text(encoding="utf-8")
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-reworking",
            status=FeatureGraphExecutionStatus.REWORKING,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch(
        "xmuse_core.platform.orchestrator.reproject_dependents_if_needed",
        new_callable=AsyncMock,
    ) as reproject:
        await orch.reconcile_status_changes()

    reproject.assert_not_awaited()
    assert lanes_path.read_text(encoding="utf-8") == before_projection
    assert orch._sm.get_lane("lane-1")["status"] == "failed"


@pytest.mark.asyncio
async def test_reconcile_graph_backed_failed_reprojects_when_graph_native_allows(
    tmp_path,
):
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps(
            {
                "projection_revision": 7,
                "lanes": [
                    {
                        "feature_id": "lane-1",
                        "status": "failed",
                        "prompt": "build chat",
                        "worktree": str(tmp_path),
                        "graph_set_id": "graph-set-1",
                        "graph_id": "graph-feature-a",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    status_store = FeatureGraphStatusStore(tmp_path / "feature_graph_statuses.json")
    status_store.upsert(
        _feature_graph_status(
            status_id="fgs-failed",
            status=FeatureGraphExecutionStatus.FAILED,
            ready_lane_ids=[],
            active_lane_ids=[],
        )
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        feature_graph_status_store=status_store,
    )

    with patch(
        "xmuse_core.platform.orchestrator.reproject_dependents_if_needed",
        new_callable=AsyncMock,
    ) as reproject:
        await orch.reconcile_status_changes()

    reproject.assert_awaited_once_with(
        "lane-1",
        sm=orch._sm,
        graph_store=orch._graph_store,
    )


# ---------------------------------------------------------------------------
# clarification_recovery: stdout fallback unknown-text safety (evbundle_0a8afa9f)
# Finding: High — stdout fallback defaulted unknown review text to merge.
# Fix: unknown/unclassifiable stdout now rejects with "unknown_review_text".
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_ambiguous_prose(setup):
    """Ambiguous review prose with no positive/negative signals must reject."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    # Ambiguous text: no approval marker, no rejection marker, no findings section.
    review_result = SpawnResult(
        exit_code=0,
        stdout="The implementation looks reasonable.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    # on_lane_rejected transitions to reworking and re-dispatches (retry_count < 2)
    assert lane["status"] == "reworking"
    assert lane["review_fallback"] == "stdout"
    assert lane["review_fallback_reason"] == "unknown_review_text"
    assert lane["review_decision"] == "rework"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_generic_reviewed_prose(setup):
    """'I reviewed the changes' with no verdict signals must reject, not merge."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="I reviewed the changes.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_fallback_reason"] == "unknown_review_text"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_implementation_complete_prose(setup):
    """'Implementation complete.' with no verdict signals must reject, not merge."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Implementation complete.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch:
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_fallback_reason"] == "unknown_review_text"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_still_approves_explicit_approval_marker(setup):
    """Explicit 'approved' marker must still resolve to merge after the fix."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Approved. No findings.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_decision"] == "merge"
    assert lane["review_fallback_reason"] == "approval_marker"


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_approves_parseable_findings_verdict(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
        require_final_action_approval=True,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Findings: none\nVerdict: merge",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "awaiting_final_action"
    assert lane["review_decision"] == "merge"
    assert lane["review_fallback_reason"] == "verdict_merge"


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_parseable_rework_verdict(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Findings:\n- Missing scheduler gate coverage.\nVerdict: rework",
        stderr="",
    )

    with (
        patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                     return_value=review_result),
        patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch,
    ):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "verdict_rework"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_review_god_stdout_fallback_rejects_parseable_terminate_verdict(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path,
        xmuse_root=tmp_path,
        mcp_port=9999,
    )
    review_result = SpawnResult(
        exit_code=0,
        stdout="Findings: approach targets the wrong subsystem\nVerdict: terminate",
        stderr="",
    )

    with (
        patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                     return_value=review_result),
        patch.object(orch, "dispatch_lane", new_callable=AsyncMock) as dispatch,
    ):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"
    assert lane["review_fallback_reason"] == "verdict_terminate"
    dispatch.assert_awaited_once_with("lane-1")


@pytest.mark.asyncio
async def test_infer_review_fallback_unknown_text_returns_rejected_tuple(setup):
    """Unit-level: infer_review_fallback returns rejected for unclassifiable text."""
    ambiguous_cases = [
        "The implementation looks reasonable.",
        "I reviewed the changes.",
        "The code has been examined.",
        "Changes look okay to me.",
        "Implementation complete.",
        "Looks good overall.",
    ]
    for text in ambiguous_cases:
        decision, _summary, reason = infer_review_fallback(text)
        assert decision == "rejected", (
            f"Expected 'rejected' for ambiguous text {text!r}, got {decision!r}"
        )
        assert reason == "unknown_review_text", (
            f"Expected 'unknown_review_text' for {text!r}, got {reason!r}"
        )


@pytest.mark.asyncio
async def test_infer_review_fallback_accepts_no_blocking_findings_context_sentence(setup):
    """Unit-level: review stdout can approve a no-blocking-findings sentence."""
    decision, _summary, reason = infer_review_fallback(
        "No blocking findings in the lane diff I reviewed."
    )

    assert decision == "reviewed"
    assert reason == "positive_no_blocking"


@pytest.mark.asyncio
async def test_infer_review_fallback_accepts_no_blocking_findings_current_diff(setup):
    """Unit-level: review stdout can approve a clean current-diff finding."""
    decision, _summary, reason = infer_review_fallback(
        "**Findings**\n\n"
        "No blocking findings in the current diff.\n\n"
        "The lane only adds focused chat-first E2E coverage.\n\n"
        "**Verification**\n\n"
        "`uv run pytest tests/xmuse/test_peer_chat_end_to_end.py -q` -> "
        "`3 passed`."
    )

    assert decision == "reviewed"
    assert reason == "positive_no_blocking"


@pytest.mark.asyncio
async def test_infer_review_fallback_accepts_review_decision_no_blocking_findings(setup):
    """Unit-level: review stdout can approve an explicit review-decision line."""
    decision, _summary, reason = infer_review_fallback(
        "Review decision: no blocking findings."
    )

    assert decision == "reviewed"
    assert reason == "positive_no_blocking"


@pytest.mark.asyncio
async def test_infer_review_fallback_accepts_empty_findings_section_with_explanation(setup):
    """Unit-level: an empty findings section can include explanatory prose."""
    decision, _summary, reason = infer_review_fallback(
        "**Findings**\n\n"
        "No blocking findings.\n\n"
        "The implementation matches the lane acceptance criteria I could verify.\n\n"
        "Review decision: pass."
    )

    assert decision == "reviewed"
    assert reason == "positive_no_blocking"


@pytest.mark.asyncio
async def test_infer_review_fallback_accepts_inline_findings_none_with_explanation(setup):
    """Unit-level: review prompt format `Findings: none` is a merge signal."""
    decision, _summary, reason = infer_review_fallback(
        "Findings: none.\n\n"
        "I reviewed the current diff directly instead.\n\n"
        "Verified:\n"
        "- `uv run pytest tests/xmuse/test_gate_profiles.py -q` -> `30 passed`\n"
        "- `uv run ruff check tests/xmuse/test_gate_profiles.py` -> passed"
    )

    assert decision == "reviewed"
    assert reason == "positive_none"


@pytest.mark.asyncio
async def test_infer_review_fallback_rejects_severity_after_inline_findings_none(setup):
    """Unit-level: `Findings: none` must not mask later blocking findings."""
    decision, _summary, reason = infer_review_fallback(
        "Findings: none.\n\n"
        "Important: gate profile missing required test."
    )

    assert decision == "rejected"
    assert reason == "severity_finding"


@pytest.mark.asyncio
async def test_infer_review_fallback_accepts_resolved_prior_blocking_issue(setup):
    """Unit-level: resolved prior blocking issues are not new blocking findings."""
    decision, _summary, reason = infer_review_fallback(
        "**Findings**\n\n"
        "None. The prior blocking issue is resolved: the docs file is now "
        "known to git as an added file.\n\n"
        "**Review Decision**\n\n"
        "Pass.\n\n"
        "**Verification**\n\n"
        "- `git ls-files --error-unmatch docs/superpowers/plans/example.md` "
        "-> exit 0"
    )

    assert decision == "reviewed"
    assert reason == "positive_none"


@pytest.mark.asyncio
async def test_infer_review_fallback_rejects_important_finding_after_positive_sentence(setup):
    """Unit-level: a scoped positive sentence must not mask later findings."""
    decision, _summary, reason = infer_review_fallback(
        "No blocking findings in the lane diff I reviewed.\n"
        "Important: gate profile missing required test."
    )

    assert decision == "rejected"
    assert reason == "severity_finding"


@pytest.mark.asyncio
async def test_infer_review_fallback_rejects_important_finding_after_empty_findings_marker(setup):
    """Unit-level: empty findings prose must not mask a later severity finding."""
    decision, _summary, reason = infer_review_fallback(
        "**Findings**\n\n"
        "No blocking findings.\n\n"
        "Important: gate profile missing required test."
    )

    assert decision == "rejected"
    assert reason == "severity_finding"


# ---------------------------------------------------------------------------
# Review plane integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_review_god_opens_review_task_and_stamps_lane(setup):
    """_run_review_god opens a ReviewTask and stamps review_task_id on the lane."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    review_result = SpawnResult(exit_code=0, stdout="Approved. No findings.", stderr="")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert "review_task_id" in lane
    task_id = lane["review_task_id"]
    assert task_id.startswith("rtask_")

    # The task must be persisted in the review plane store.
    task = orch._review_plane.store.get_task(task_id)
    assert task.lane_id == "lane-1"


@pytest.mark.asyncio
async def test_on_lane_reviewed_ingests_verdict_through_review_plane(setup):
    """on_lane_reviewed persists the verdict through ReviewPlaneController."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_decision": "merge",
            "review_summary": "No findings.",
            "review_verdict_id": "verdict-lane-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Open a task first so ingest_verdict has a task to link to.
    task = orch._review_plane.open_review_task("lane-1")
    orch._sm.update_metadata("lane-1", {"review_task_id": task.task_id})

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.on_lane_reviewed("lane-1")

    # Verdict must be persisted in the review plane store.
    verdict = orch._review_plane.store.get_verdict("verdict-lane-1")
    assert verdict.lane_id == "lane-1"
    assert verdict.decision.value == "merge"
    assert verdict.task_id == task.task_id


@pytest.mark.asyncio
async def test_verdict_lineage_for_lane_returns_chain_after_merge(setup):
    """verdict_lineage_for_lane returns the task→verdict chain after a merge."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_decision": "merge",
            "review_summary": "No findings.",
            "review_verdict_id": "verdict-lineage-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    task = orch._review_plane.open_review_task("lane-1")
    orch._sm.update_metadata("lane-1", {"review_task_id": task.task_id})

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.on_lane_reviewed("lane-1")

    lineage = orch.verdict_lineage_for_lane("lane-1")

    assert len(lineage) == 1
    assert lineage[0]["task"]["task_id"] == task.task_id
    assert lineage[0]["verdict"] is not None
    assert lineage[0]["verdict"]["id"] == "verdict-lineage-1"


@pytest.mark.asyncio
async def test_has_verdict_lineage_is_true_after_merge(setup):
    """has_verdict_lineage returns True after a lane is merged through the review plane."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_decision": "merge",
            "review_summary": "No findings.",
            "review_verdict_id": "verdict-has-lineage-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    task = orch._review_plane.open_review_task("lane-1")
    orch._sm.update_metadata("lane-1", {"review_task_id": task.task_id})

    assert orch.has_verdict_lineage("lane-1") is False

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.on_lane_reviewed("lane-1")

    assert orch.has_verdict_lineage("lane-1") is True


def test_has_verdict_lineage_is_false_for_unknown_lane(setup):
    """has_verdict_lineage returns False for a lane with no review plane record."""
    tmp_path, lanes_path = setup
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    assert orch.has_verdict_lineage("lane-unknown") is False


@pytest.mark.asyncio
async def test_run_review_god_captures_gate_report_ref_in_task(setup):
    """_run_review_god captures the gate report ref in the ReviewTask when available."""
    tmp_path, lanes_path = setup
    # The setup fixture already creates logs/gates/lane-1/report.json.
    lanes_path.write_text(json.dumps({"lanes": [
        {"feature_id": "lane-1", "status": "gated", "prompt": "fix",
         "worktree": str(tmp_path)},
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    review_result = SpawnResult(exit_code=0, stdout="Approved. No findings.", stderr="")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    task_id = lane.get("review_task_id")
    assert task_id is not None

    task = orch._review_plane.store.get_task(task_id)
    assert task.gate_report_ref is not None
    assert "lane-1" in task.gate_report_ref
    assert "report.json" in task.gate_report_ref


@pytest.mark.asyncio
async def test_review_plane_error_does_not_break_execution_path(setup):
    """A review plane failure must not prevent the lane from transitioning normally."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_decision": "merge",
            "review_summary": "No findings.",
            "review_verdict_id": "verdict-error-1",
            # Deliberately omit review_task_id so ingest_verdict raises KeyError.
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        # Should not raise even though there is no review_task_id.
        await orch.on_lane_reviewed("lane-1")

    assert orch._sm.get_lane("lane-1")["status"] == "merged"


@pytest.mark.asyncio
async def test_rework_verdict_creates_review_task_and_verdict_lineage(setup):
    """A rework verdict via _run_review_god is persisted in the review plane."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Simulate review GOD returning a rework verdict via stdout fallback.
    review_result = SpawnResult(
        exit_code=0,
        stdout="**Findings**\n1. High: core behavior is incorrect.",
        stderr="",
    )

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=review_result):
        with patch.object(orch, "dispatch_lane", new_callable=AsyncMock):
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reworking"
    assert lane["review_decision"] == "rework"

    # The review task must have been opened and stamped on the lane.
    task_id = lane.get("review_task_id")
    assert task_id is not None
    task = orch._review_plane.store.get_task(task_id)
    assert task.lane_id == "lane-1"


# ---------------------------------------------------------------------------
# Run-level terminal aggregation (review_plane track, evbundle_648180f3cce14c129fad244774d94f80)
# Spec: blueprint-anchored self-evolution, "Run Terminal Aggregation" section.
# Hard Rule #10: run terminalization must be computed through an explicit
# aggregation contract rather than guessed from individual lane states.
# ---------------------------------------------------------------------------


def test_aggregate_run_terminal_status_merged_when_all_lanes_merged(setup):
    """All lanes merged → run status is 'merged'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
        {
            "feature_id": "lane-2",
            "status": "merged",
            "prompt": "build dashboard",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    assert result.graph_id == "graph-1"
    assert result.status == "merged"
    assert result.open_lane_lineages == []
    assert result.failed_lineages == []
    assert result.open_final_action_holds == []


def test_aggregate_run_terminal_status_in_progress_when_lane_pending(setup):
    """A pending lane keeps the run in 'in_progress'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
        {
            "feature_id": "lane-2",
            "status": "pending",
            "prompt": "build dashboard",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    assert result.status == "in_progress"
    assert "lane-2" in result.open_lane_lineages
    assert result.failed_lineages == []


def test_aggregate_run_terminal_status_terminated_when_lane_failed(setup):
    """A failed lane with all others merged → run status is 'terminated'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
        {
            "feature_id": "lane-2",
            "status": "failed",
            "prompt": "build dashboard",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    assert result.status == "terminated"
    assert "lane-2" in result.failed_lineages
    assert result.open_lane_lineages == []


def test_aggregate_run_terminal_status_terminated_for_exec_failed(setup):
    """exec_failed lane with all others merged → run status is 'terminated'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
        {
            "feature_id": "lane-2",
            "status": "exec_failed",
            "prompt": "build dashboard",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    assert result.status == "terminated"
    assert "lane-2" in result.failed_lineages


def test_aggregate_run_terminal_status_blocked_for_input_when_hold_pending(setup):
    """All lanes merged but a pending final-action hold → 'blocked_for_input'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "awaiting_final_action",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    # Create a pending hold for lane-1.
    orch._final_action_store.create_hold(
        lane_id="lane-1",
        verdict_id="verdict-1",
        action="merge",
        target_status="reviewed",
        summary="awaiting approval",
    )
    # Manually move lane-1 to a closed state so the only blocker is the hold.
    # We simulate: lane is in awaiting_final_action (open), so in_progress first.
    # To test blocked_for_input we need all lineages closed but hold pending.
    # Patch the lane to a non-open status that is also not in _CLOSED_OK/_CLOSED_FAIL.
    # The spec says blocked_for_input = all lineages closed + open hold.
    # awaiting_final_action is in _OPEN, so the run is in_progress.
    # We test the pure blocked_for_input path by using a lane with no open lineages.
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))

    result = orch.aggregate_run_terminal_status("graph-1")

    assert result.status == "blocked_for_input"
    assert len(result.open_final_action_holds) == 1


def test_aggregate_run_terminal_status_includes_patch_forward_descendants(setup):
    """Patch-forward descendants are included in the lineage closure."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "failure_reason": "patch_forward_requested",
        },
        {
            "feature_id": "lane-1-patch-forward",
            "status": "pending",
            "prompt": "patch forward",
            "worktree": str(tmp_path),
            "source_lane_id": "lane-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    # The patch-forward descendant is still pending → in_progress.
    assert result.status == "in_progress"
    assert "lane-1-patch-forward" in result.open_lane_lineages


def test_aggregate_run_terminal_status_patch_forward_merged_closes_lineage(setup):
    """When the patch-forward descendant merges, the lineage is fully closed."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "failure_reason": "patch_forward_requested",
        },
        {
            "feature_id": "lane-1-patch-forward",
            "status": "merged",
            "prompt": "patch forward",
            "worktree": str(tmp_path),
            "source_lane_id": "lane-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    # lane-1 is failed (terminated lineage), patch-forward is merged (closed ok).
    # All lineages closed, at least one via fail → terminated.
    assert result.status == "terminated"
    assert "lane-1" in result.failed_lineages
    assert result.open_lane_lineages == []


def test_aggregate_run_terminal_status_empty_graph_returns_merged(setup):
    """A graph with no lanes is considered merged (vacuously complete)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": []}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-empty")

    assert result.status == "merged"
    assert result.open_lane_lineages == []
    assert result.failed_lineages == []


def test_aggregate_run_terminal_status_basis_records_aggregation_inputs(setup):
    """The basis field records the key aggregation inputs for audit."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    assert "graph_id=graph-1" in result.basis
    assert "total_lane_lineages=1" in result.basis
    assert "open=0" in result.basis
    assert "failed=0" in result.basis


def test_aggregate_run_terminal_status_ignores_lanes_from_other_graphs(setup):
    """Lanes from a different graph_id do not affect the aggregation."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
        {
            "feature_id": "lane-other",
            "status": "pending",
            "prompt": "other graph work",
            "worktree": str(tmp_path),
            "graph_id": "graph-2",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    # graph-2's pending lane must not affect graph-1's aggregation.
    assert result.status == "merged"
    assert "lane-other" not in result.open_lane_lineages


def test_aggregate_run_terminal_status_in_progress_for_dispatched_lane(setup):
    """A dispatched lane keeps the run in 'in_progress'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    result = orch.aggregate_run_terminal_status("graph-1")

    assert result.status == "in_progress"
    assert "lane-1" in result.open_lane_lineages


# ---------------------------------------------------------------------------
# StructuredEvidenceBundle assembly
# (review_plane track, self-evolution-review_plane-res_e0fefabbce6c449799c942bfca91061a-graph-v1)
# Spec: blueprint-anchored self-evolution, "Evidence Model" section.
# Testing Expectations #1-2: terminal run outcome can produce a structured
# evidence bundle; bundles expose curated summaries plus full primary refs
# under a versioned selection policy.
# ---------------------------------------------------------------------------


def test_assemble_evidence_bundle_from_merged_run(setup):
    """A merged run produces an evidence bundle with run_terminal_status 'merged'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "resolution_id": "res-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle("graph-1")

    assert bundle.source_run_id == "graph-1"
    assert bundle.run_terminal_status == "merged"
    assert bundle.source_resolution_id == "res-1"
    assert bundle.bundle_id.startswith("evbundle_")
    assert bundle.created_at


def test_assemble_evidence_bundle_from_terminated_run(setup):
    """A terminated run produces a bundle with run_terminal_status 'terminated'."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
        {
            "feature_id": "lane-2",
            "status": "failed",
            "prompt": "build dashboard",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "failure_reason": "non_zero_exit",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle("graph-1")

    assert bundle.run_terminal_status == "terminated"
    assert bundle.source_run_id == "graph-1"


def test_assemble_evidence_bundle_uses_authoritative_lane_graph(setup):
    """Bundle assembly uses LaneGraph lanes even when lane graph_id metadata is stale."""
    tmp_path, lanes_path = setup
    graph_id = "graph-authoritative"
    (tmp_path / "lane_graphs").mkdir()
    (tmp_path / "lane_graphs" / f"{graph_id}.json").write_text(json.dumps({
        "id": graph_id,
        "conversation_id": "conv-1",
        "resolution_id": "res-authoritative",
        "version": 1,
        "lanes": [{"feature_id": "lane-stale", "prompt": "fix stale metadata"}],
    }))
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-stale",
            "status": "failed",
            "prompt": "fix stale metadata",
            "worktree": str(tmp_path),
            "failure_reason": "non_zero_exit",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle(graph_id)

    assert bundle.run_terminal_status == "terminated"
    assert bundle.source_resolution_id == "res-authoritative"
    assert any("lane-stale" in ref for ref in bundle.signal_refs)


def test_assemble_evidence_bundle_uses_orchestrator_clarification_store(setup):
    """Open clarifications block bundle status through the production wrapper path."""
    tmp_path, lanes_path = setup
    graph_id = "graph-clarification"
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-clarify",
            "status": "merged",
            "prompt": "needs external input",
            "worktree": str(tmp_path),
            "graph_id": graph_id,
        },
    ]}))
    ClarificationStore(tmp_path / "clarifications.json").open_clarification(
        clarification_id="clar-1",
        lane_id="lane-clarify",
        graph_id=graph_id,
        question="which deployment target?",
        created_at="2026-05-30T00:00:00Z",
    )
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle(graph_id)

    assert bundle.run_terminal_status == "blocked_for_input"
    assert any(
        ref.get("type") == "clarification" and ref.get("id") == "clar-1"
        for ref in bundle.primary_refs
    )


def test_evidence_bundle_includes_negative_signal_refs_for_failed_lanes(setup):
    """Evidence bundle records negative signal refs for every failed lane."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "failure_reason": "merge_failed",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle("graph-1")

    assert any("lane-1" in ref for ref in bundle.signal_refs)
    assert any("merge_failed" in ref for ref in bundle.signal_refs)
    # primary_refs must include the negative signal entry
    neg_primaries = [r for r in bundle.primary_refs if r.get("type") == "negative_signal"]
    assert len(neg_primaries) == 1
    assert neg_primaries[0]["lane_id"] == "lane-1"
    assert neg_primaries[0]["failure_reason"] == "merge_failed"


def test_evidence_bundle_includes_verdict_refs_and_primary_refs(setup):
    """Evidence bundle includes verdict refs and full primary refs for each verdict."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "review_decision": "merge",
            "review_summary": "No findings.",
            "review_verdict_id": "verdict-ev-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Open a task and ingest a verdict so the lineage exists.
    task = orch._review_plane.open_review_task("lane-1")
    orch._sm.update_metadata("lane-1", {"review_task_id": task.task_id})
    from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict
    verdict = ReviewVerdict(
        id="verdict-ev-1",
        lane_id="lane-1",
        decision=ReviewDecision.MERGE,
        summary="No findings.",
        task_id=task.task_id,
    )
    orch._review_plane.store.save_verdict(verdict)
    # Update task to verdict_emitted state.
    task.verdict_id = "verdict-ev-1"
    from xmuse_core.structuring.models import ReviewTaskStatus
    task.status = ReviewTaskStatus.VERDICT_EMITTED
    orch._review_plane.store.save_task(task)

    bundle = orch.assemble_evidence_bundle("graph-1")

    assert "verdict-ev-1" in bundle.verdict_refs
    verdict_primaries = [r for r in bundle.primary_refs if r.get("type") == "review_verdict"]
    assert len(verdict_primaries) == 1
    assert verdict_primaries[0]["id"] == "verdict-ev-1"
    assert verdict_primaries[0]["decision"] == "merge"


def test_evidence_bundle_includes_gate_report_refs(setup):
    """Evidence bundle includes gate report refs from review tasks."""
    tmp_path, lanes_path = setup
    # setup fixture already creates logs/gates/lane-1/report.json
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Open a task with a gate_report_ref.
    task = orch._review_plane.open_review_task(
        "lane-1", gate_report_ref="logs/gates/lane-1/report.json"
    )
    orch._sm.update_metadata("lane-1", {"review_task_id": task.task_id})

    bundle = orch.assemble_evidence_bundle("graph-1")

    assert "logs/gates/lane-1/report.json" in bundle.gate_report_refs
    task_primaries = [r for r in bundle.primary_refs if r.get("type") == "review_task"]
    assert any(r.get("gate_report_ref") == "logs/gates/lane-1/report.json" for r in task_primaries)


def test_evidence_bundle_includes_lineage_refs_for_patch_forward(setup):
    """Evidence bundle includes lineage refs for patch-forward descendants."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "build chat",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "failure_reason": "patch_forward_requested",
        },
        {
            "feature_id": "lane-1-patch",
            "status": "merged",
            "prompt": "patch forward",
            "worktree": str(tmp_path),
            "source_lane_id": "lane-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle("graph-1")

    assert any("lane-1-patch" in ref for ref in bundle.lineage_refs)
    lineage_primaries = [r for r in bundle.primary_refs if r.get("type") == "lane_lineage"]
    assert any(r.get("lane_id") == "lane-1-patch" for r in lineage_primaries)


def test_evidence_bundle_selection_policy_is_versioned(setup):
    """Evidence bundle records selection_policy_id and selection_policy_version."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle(
        "graph-1",
        selection_policy_id="review-plane-v1",
        selection_policy_version="2",
    )

    assert bundle.selection_policy_id == "review-plane-v1"
    assert bundle.selection_policy_version == "2"


def test_evidence_bundle_is_persisted_in_evidence_store(setup):
    """Evidence bundle is persisted in the evidence store when provided."""
    from xmuse_core.structuring.verdict_store import EvidenceBundleStore

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    store = EvidenceBundleStore(tmp_path / "evidence_bundles.json")

    bundle = orch.assemble_evidence_bundle("graph-1", evidence_store=store)

    # Bundle must be retrievable from the store.
    retrieved = store.get(bundle.bundle_id)
    assert retrieved.bundle_id == bundle.bundle_id
    assert retrieved.source_run_id == "graph-1"
    assert retrieved.run_terminal_status == "merged"


def test_evidence_bundle_summary_contains_key_aggregation_facts(setup):
    """Evidence bundle summary includes run id, status, and lane counts."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-summary",
        },
        {
            "feature_id": "lane-2",
            "status": "failed",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-summary",
            "failure_reason": "exec_failed",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle("graph-summary")

    assert "graph-summary" in bundle.summary
    assert "terminated" in bundle.summary
    assert "Failed: 1" in bundle.summary


def test_evidence_bundle_primary_refs_cover_all_cited_items(setup):
    """Every item referenced in verdict_refs / gate_report_refs / signal_refs
    must also appear in primary_refs (evidence curation contract)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "failure_reason": "merge_failed",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Open a task with a gate report ref.
    task = orch._review_plane.open_review_task(
        "lane-1", gate_report_ref="logs/gates/lane-1/report.json"
    )
    orch._sm.update_metadata("lane-1", {"review_task_id": task.task_id})

    bundle = orch.assemble_evidence_bundle("graph-1")

    primary_types = {r.get("type") for r in bundle.primary_refs}
    # Gate report ref → review_task primary ref must exist.
    if bundle.gate_report_refs:
        assert "review_task" in primary_types
    # Negative signal → negative_signal primary ref must exist.
    if bundle.signal_refs:
        assert "negative_signal" in primary_types


# ---------------------------------------------------------------------------
# Merge guards (evbundle_6259476d67dd414a8be293d1025ccb8c)
# Finding: graph lineage terminated without proper merge, leaving sibling
# lineages stranded and run-level terminal status ambiguous.
# Guards: check_lineage_merge_completeness, assert_termination_safe,
#         record_incomplete_termination.
# ---------------------------------------------------------------------------


def test_check_lineage_merge_completeness_all_merged(setup):
    """All lanes merged → report is complete with no open or unmerged lineages."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
        },
        {
            "feature_id": "lane-2",
            "status": "merged",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    report = orch._review_plane.check_lineage_merge_completeness("graph-mg")

    assert report.is_complete is True
    assert set(report.merged_lineages) == {"lane-1", "lane-2"}
    assert report.terminated_without_merge == []
    assert report.open_lineages == []


def test_check_lineage_merge_completeness_open_lane(setup):
    """A pending lane is classified as open, making the report incomplete."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
        },
        {
            "feature_id": "lane-2",
            "status": "pending",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    report = orch._review_plane.check_lineage_merge_completeness("graph-mg")

    assert report.is_complete is False
    assert "lane-1" in report.merged_lineages
    assert "lane-2" in report.open_lineages
    assert report.terminated_without_merge == []


def test_check_lineage_merge_completeness_failed_without_merge_verdict(setup):
    """A failed lane with no merge verdict is classified as terminated_without_merge."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
        },
        {
            "feature_id": "lane-2",
            "status": "failed",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
            "failure_reason": "exec_failed",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    report = orch._review_plane.check_lineage_merge_completeness("graph-mg")

    assert report.is_complete is False
    assert "lane-1" in report.merged_lineages
    assert "lane-2" in report.terminated_without_merge
    assert report.open_lineages == []


def test_check_lineage_merge_completeness_failed_with_merge_verdict_counts_as_merged(setup):
    """A failed lane that has a finalized MERGE verdict is classified as merged."""
    from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
            "failure_reason": "patch_forward_requested",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Persist a MERGE verdict for lane-1 directly in the store.
    verdict = ReviewVerdict(
        id="verdict-mg-1",
        lane_id="lane-1",
        decision=ReviewDecision.MERGE,
        summary="Merged via patch-forward.",
        status="finalized",
    )
    orch._review_plane.store.save_verdict(verdict)

    report = orch._review_plane.check_lineage_merge_completeness("graph-mg")

    assert "lane-1" in report.merged_lineages
    assert report.terminated_without_merge == []
    assert report.is_complete is True


def test_check_lineage_merge_completeness_includes_source_lane_descendants(setup):
    """Descendants linked via source_lane_id are included in the completeness check."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-mg",
            "failure_reason": "patch_forward_requested",
        },
        {
            "feature_id": "lane-1-patch",
            "status": "pending",
            "prompt": "patch",
            "worktree": str(tmp_path),
            "source_lane_id": "lane-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    report = orch._review_plane.check_lineage_merge_completeness("graph-mg")

    # lane-1 is failed without merge verdict → terminated_without_merge.
    # lane-1-patch is pending → open.
    assert "lane-1" in report.terminated_without_merge
    assert "lane-1-patch" in report.open_lineages
    assert report.is_complete is False


def test_assert_termination_safe_passes_when_all_siblings_merged(setup):
    """assert_termination_safe does not raise when all sibling lineages are merged."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
        },
        {
            "feature_id": "lane-2",
            "status": "gated",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # lane-2 is the lane being terminated; lane-1 is merged → safe.
    # Should not raise.
    orch._review_plane.assert_termination_safe("lane-2", "graph-ts")


def test_assert_termination_safe_raises_when_sibling_is_open(setup):
    """assert_termination_safe raises IncompleteLineageTerminationError when a
    sibling lineage is still open (in-flight)."""
    from xmuse_core.platform.review_plane import IncompleteLineageTerminationError

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
        },
        {
            "feature_id": "lane-2",
            "status": "gated",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Terminating lane-2 while lane-1 is still open must be blocked.
    with pytest.raises(IncompleteLineageTerminationError) as exc_info:
        orch._review_plane.assert_termination_safe("lane-2", "graph-ts")

    err = exc_info.value
    assert err.lane_id == "lane-2"
    assert err.graph_id == "graph-ts"
    assert "lane-1" in err.open_lineages
    assert err.unmerged_lineages == []


def test_assert_termination_safe_raises_when_sibling_terminated_without_merge(setup):
    """assert_termination_safe raises when a sibling already terminated without merge."""
    from xmuse_core.platform.review_plane import IncompleteLineageTerminationError

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
            "failure_reason": "exec_failed",
        },
        {
            "feature_id": "lane-2",
            "status": "gated",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # lane-1 terminated without merge; terminating lane-2 must be blocked.
    with pytest.raises(IncompleteLineageTerminationError) as exc_info:
        orch._review_plane.assert_termination_safe("lane-2", "graph-ts")

    err = exc_info.value
    assert "lane-1" in err.unmerged_lineages


def test_assert_termination_safe_excludes_terminating_lane_from_sibling_check(setup):
    """The lane being terminated is excluded from the sibling open/unmerged checks."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
        },
        {
            "feature_id": "lane-2",
            "status": "gated",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-ts",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # lane-2 is in-flight but it is the lane being terminated — must not block itself.
    # lane-1 is merged → no open siblings → safe.
    orch._review_plane.assert_termination_safe("lane-2", "graph-ts")


def test_ingest_verdict_terminate_blocked_by_open_sibling(setup):
    """ingest_verdict raises IncompleteLineageTerminationError for TERMINATE when
    a sibling lineage is still open (evbundle_6259476d67dd414a8be293d1025ccb8c)."""
    from xmuse_core.platform.review_plane import IncompleteLineageTerminationError
    from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-iv",
        },
        {
            "feature_id": "lane-2",
            "status": "gated",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-iv",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Open a review task for lane-2.
    task = orch._review_plane.open_review_task("lane-2")

    terminate_verdict = ReviewVerdict(
        id="verdict-term-1",
        lane_id="lane-2",
        decision=ReviewDecision.TERMINATE,
        summary="Terminating lane-2.",
    )

    # lane-1 is still open → TERMINATE must be blocked.
    with pytest.raises(IncompleteLineageTerminationError):
        orch._review_plane.ingest_verdict(task.task_id, terminate_verdict)


def test_ingest_verdict_terminate_allowed_when_all_siblings_merged(setup):
    """ingest_verdict allows TERMINATE when all sibling lineages are merged."""
    from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "merged",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-iv",
        },
        {
            "feature_id": "lane-2",
            "status": "gated",
            "prompt": "fix2",
            "worktree": str(tmp_path),
            "graph_id": "graph-iv",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    task = orch._review_plane.open_review_task("lane-2")

    terminate_verdict = ReviewVerdict(
        id="verdict-term-2",
        lane_id="lane-2",
        decision=ReviewDecision.TERMINATE,
        summary="Terminating lane-2 safely.",
    )

    # lane-1 is merged → TERMINATE is safe.
    result = orch._review_plane.ingest_verdict(task.task_id, terminate_verdict)
    assert result is not None


def test_record_incomplete_termination_persists_verdict(setup):
    """record_incomplete_termination writes a synthetic TERMINATE verdict with
    status='incomplete_termination' for the failed lane."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-rit",
            "failure_reason": "exec_failed",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    verdict = orch._review_plane.record_incomplete_termination(
        "lane-1", "graph-rit", reason="exec_failed"
    )

    assert verdict.lane_id == "lane-1"
    assert verdict.status == "incomplete_termination"
    assert verdict.terminate_reason == "exec_failed"
    assert "evbundle_6259476d67dd414a8be293d1025ccb8c" in verdict.summary

    # Must be retrievable from the store.
    stored = orch._review_plane.store.get_verdict(verdict.id)
    assert stored.id == verdict.id
    assert stored.status == "incomplete_termination"


def test_record_incomplete_termination_is_idempotent(setup):
    """Calling record_incomplete_termination twice returns the same verdict."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-rit",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    v1 = orch._review_plane.record_incomplete_termination("lane-1", "graph-rit")
    v2 = orch._review_plane.record_incomplete_termination("lane-1", "graph-rit")

    assert v1.id == v2.id


def test_evidence_bundle_records_incomplete_termination_for_failed_lane(setup):
    """assemble_evidence_bundle calls record_incomplete_termination for failed lanes
    that never received a merge verdict, adding an incomplete_termination primary ref."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-rit",
            "failure_reason": "exec_failed",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    bundle = orch.assemble_evidence_bundle("graph-rit")

    # An incomplete_termination primary ref must be present.
    incomplete_primaries = [
        r for r in bundle.primary_refs if r.get("type") == "incomplete_termination"
    ]
    assert len(incomplete_primaries) == 1
    assert incomplete_primaries[0]["lane_id"] == "lane-1"
    assert incomplete_primaries[0]["evidence_bundle_ref"] == (
        "evbundle_6259476d67dd414a8be293d1025ccb8c"
    )

    # The incomplete_termination signal ref must also appear in signal_refs.
    assert any("incomplete_termination" in ref for ref in bundle.signal_refs)


def test_evidence_bundle_does_not_duplicate_incomplete_termination_on_second_call(setup):
    """Calling assemble_evidence_bundle twice does not create duplicate
    incomplete_termination verdicts (idempotency via record_incomplete_termination)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "graph_id": "graph-rit",
            "failure_reason": "exec_failed",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    orch.assemble_evidence_bundle("graph-rit")
    bundle2 = orch.assemble_evidence_bundle("graph-rit")

    incomplete_primaries = [
        r for r in bundle2.primary_refs if r.get("type") == "incomplete_termination"
    ]
    # Exactly one incomplete_termination entry — no duplicates.
    assert len(incomplete_primaries) == 1


# ---------------------------------------------------------------------------
# Error recovery mechanisms (evbundle_6ef398723414454ba7212973e08e05f5)
# Tests: retry logic, circuit breaker state transitions, graceful degradation,
#        state preservation under failure.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_exec_failed_lane_retries_up_to_max_retries(setup):
    """A lane in exec_failed can be retried up to MAX_RETRIES times via reworking.
    After MAX_RETRIES the state machine rejects further rework transitions."""
    from xmuse_core.platform.state_machine import MAX_RETRIES, InvalidTransitionError

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "exec_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Exhaust all retries
    for _ in range(MAX_RETRIES):
        orch._sm.transition("lane-1", "reworking")
        orch._sm.transition("lane-1", "dispatched")
        orch._sm.transition("lane-1", "exec_failed")

    # One more rework attempt must be rejected
    with pytest.raises(InvalidTransitionError):
        orch._sm.transition("lane-1", "reworking")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "exec_failed"
    assert lane["retry_count"] == MAX_RETRIES


@pytest.mark.asyncio
async def test_gate_failed_lane_retries_up_to_max_retries(setup):
    """A lane in gate_failed can be retried up to MAX_RETRIES times.
    After MAX_RETRIES the state machine rejects further rework transitions."""
    from xmuse_core.platform.state_machine import MAX_RETRIES, InvalidTransitionError

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    for _ in range(MAX_RETRIES):
        orch._sm.transition("lane-1", "reworking")
        orch._sm.transition("lane-1", "dispatched")
        orch._sm.transition("lane-1", "executed")
        orch._sm.transition(
            "lane-1",
            "gate_failed",
            metadata={"failure_reason": "gate_failed"},
        )

    with pytest.raises(InvalidTransitionError):
        orch._sm.transition("lane-1", "reworking")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["retry_count"] == MAX_RETRIES


@pytest.mark.asyncio
async def test_retry_count_increments_on_each_rework_transition(setup):
    """retry_count increments by 1 on each reworking transition."""
    from xmuse_core.platform.state_machine import MAX_RETRIES

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "exec_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    for expected_count in range(1, MAX_RETRIES + 1):
        orch._sm.transition("lane-1", "reworking")
        lane = orch._sm.get_lane("lane-1")
        assert lane["retry_count"] == expected_count
        orch._sm.transition("lane-1", "dispatched")
        orch._sm.transition("lane-1", "exec_failed")


@pytest.mark.asyncio
async def test_review_retry_count_increments_on_reconcile_recovery(setup):
    """review_retry_count increments each time reconcile recovers a review failure."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_timeout",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock):
        await orch.reconcile_status_changes()

    lane = orch._sm.get_lane("lane-1")
    assert lane["review_retry_count"] == 1
    assert lane["review_recovered_from"] == "review_timeout"
    assert "failure_reason" not in lane


@pytest.mark.asyncio
async def test_review_retry_stops_after_max_review_retries(setup):
    """reconcile does not retry review when review_retry_count >= 2."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_timeout",
            "review_retry_count": 2,  # already at limit
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_not_called()
    assert orch._sm.get_lane("lane-1")["status"] == "gate_failed"


@pytest.mark.asyncio
async def test_execution_god_non_zero_exit_marks_exec_failed_preserves_prompt(setup):
    """A non-zero exit from the execution god marks exec_failed and preserves
    the original lane prompt (no data corruption)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "build the feature",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    fail_result = SpawnResult(exit_code=1, stdout="", stderr="error")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=fail_result):
        await orch._run_execution_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "non_zero_exit"
    # Prompt must be preserved
    assert lane["prompt"] == "build the feature"


@pytest.mark.asyncio
async def test_execution_god_timeout_preserves_lane_metadata(setup):
    """A timed-out execution god marks exec_failed and preserves all existing
    lane metadata (no data loss)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix bug",
            "worktree": str(tmp_path),
            "graph_id": "graph-1",
            "resolution_id": "res-1",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    timeout_result = SpawnResult(exit_code=-1, stdout="", stderr="timeout", timed_out=True)

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=timeout_result):
        await orch._run_execution_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "exec_failed"
    assert lane["failure_reason"] == "timeout"
    # Metadata from before the failure must be intact
    assert lane["graph_id"] == "graph-1"
    assert lane["resolution_id"] == "res-1"
    assert lane["prompt"] == "fix bug"


@pytest.mark.asyncio
async def test_review_infra_unavailable_circuit_breaker_respects_backoff(setup):
    """When review_infra_unavailable is set with a future retry_after_at,
    reconcile does not retry (circuit breaker open)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_infra_unavailable",
            "review_retry_after_at": 9999999999,  # far future
            "review_retry_count": 0,
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_not_called()
    assert orch._sm.get_lane("lane-1")["status"] == "gate_failed"


@pytest.mark.asyncio
async def test_review_infra_unavailable_circuit_breaker_closes_after_backoff(setup):
    """When review_retry_after_at is in the past, reconcile retries (circuit breaker closed)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_infra_unavailable",
            "review_retry_after_at": 1,  # past
            "review_retry_count": 0,
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_awaited_once_with("lane-1")
    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gated"
    assert lane["review_retry_count"] == 1
    assert lane["review_recovered_from"] == "review_infra_unavailable"


@pytest.mark.asyncio
async def test_review_infra_unavailable_circuit_breaker_stops_at_40_retries(setup):
    """review_infra_unavailable retries stop at 40 (circuit breaker max)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gate_failed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
            "failure_reason": "review_infra_unavailable",
            "review_retry_after_at": 1,  # past
            "review_retry_count": 40,  # at limit
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_review_god", new_callable=AsyncMock) as review:
        await orch.reconcile_status_changes()

    review.assert_not_called()
    assert orch._sm.get_lane("lane-1")["status"] == "gate_failed"


@pytest.mark.asyncio
async def test_dispatch_lane_failure_does_not_corrupt_sibling_lanes(setup):
    """When one lane's execution god fails, sibling lanes in the same graph
    are not affected."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "pending",
            "prompt": "fix bug",
            "worktree": str(tmp_path),
        },
        {
            "feature_id": "lane-2",
            "status": "pending",
            "prompt": "add feature",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    fail_result = SpawnResult(exit_code=1, stdout="", stderr="error")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=fail_result):
        await orch.dispatch_lane("lane-1")

    lane1 = orch._sm.get_lane("lane-1")
    lane2 = orch._sm.get_lane("lane-2")
    assert lane1["status"] == "exec_failed"
    # lane-2 must be untouched
    assert lane2["status"] == "pending"
    assert lane2["prompt"] == "add feature"


@pytest.mark.asyncio
async def test_invalid_transition_does_not_corrupt_lane_state(setup):
    """An invalid state transition raises InvalidTransitionError and leaves
    the lane in its original state."""
    from xmuse_core.platform.state_machine import InvalidTransitionError

    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "pending",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with pytest.raises(InvalidTransitionError):
        orch._sm.transition("lane-1", "merged")  # pending → merged is invalid

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "pending"


@pytest.mark.asyncio
async def test_reconcile_handles_empty_lanes_without_error(setup):
    """reconcile_status_changes on an empty lane list completes without error."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": []}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    # Must not raise
    await orch.reconcile_status_changes()


@pytest.mark.asyncio
async def test_review_plane_error_does_not_prevent_lane_merge_on_reviewed(setup):
    """A review plane failure during on_lane_reviewed must not prevent the lane
    from transitioning to merged (graceful degradation)."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "reviewed",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "review_decision": "merge",
            "review_summary": "No findings.",
            "review_verdict_id": "verdict-error-recovery-1",
            # Deliberately omit review_task_id to trigger review plane error
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_auto_merge", new_callable=AsyncMock, return_value=True):
        await orch.on_lane_reviewed("lane-1")

    # Lane must reach merged despite the review plane error
    assert orch._sm.get_lane("lane-1")["status"] == "merged"


@pytest.mark.asyncio
async def test_gate_failure_preserves_lane_prompt_and_graph_id(setup):
    """A gate failure must not overwrite the lane's prompt or graph_id."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "executed",
            "prompt": "build the feature",
            "worktree": str(tmp_path),
            "graph_id": "graph-preserve",
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(orch, "_run_gate", new_callable=AsyncMock, return_value=False):
        with patch.object(orch, "_run_review_god", new_callable=AsyncMock):
            await orch._on_lane_executed("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["prompt"] == "build the feature"
    assert lane["graph_id"] == "graph-preserve"


@pytest.mark.asyncio
async def test_concurrent_dispatch_does_not_double_transition_to_exec_failed(setup):
    """Concurrent dispatch calls for the same lane do not cause double transitions
    or corrupt the retry_count."""
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "pending",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    fail_result = SpawnResult(exit_code=1, stdout="", stderr="error")

    with patch.object(orch._spawner, "spawn", new_callable=AsyncMock,
                      return_value=fail_result):
        # Only one dispatch should succeed (pending → dispatched is a valid
        # transition only once); the second will raise InvalidTransitionError
        # which the caller must handle.
        try:
            await asyncio.gather(
                orch.dispatch_lane("lane-1"),
                orch.dispatch_lane("lane-1"),
            )
        except Exception:
            pass

    lane = orch._sm.get_lane("lane-1")
    # The lane must be in a consistent terminal state, not in an intermediate one
    assert lane["status"] in ("exec_failed", "dispatched", "executed")
    # retry_count must not exceed 1 from a single failure cycle
    assert lane.get("retry_count", 0) <= 1


@pytest.mark.asyncio
async def test_execution_spawn_retries_transient_exception_without_projection_telemetry(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "dispatched",
            "prompt": "fix",
            "worktree": str(tmp_path),
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    orch._recovery.config = orch._recovery.config.__class__(
        max_attempts=2,
        initial_delay_s=0,
        max_delay_s=0,
    )

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        side_effect=[
            TimeoutError("temporary spawn outage"),
            SpawnResult(exit_code=0, stdout="", stderr=""),
        ],
    ) as spawn:
        with patch.object(orch, "_on_lane_executed", new_callable=AsyncMock):
            await orch._run_execution_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "executed"
    assert spawn.await_count == 2
    assert "recovery_events" not in lane
    assert "last_recovery_event" not in lane
    assert "failure_error" not in lane


@pytest.mark.asyncio
async def test_review_spawn_retries_transient_result_without_projection_telemetry(
    setup,
):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    orch._recovery.config = orch._recovery.config.__class__(
        max_attempts=2,
        initial_delay_s=0,
        max_delay_s=0,
    )

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        side_effect=[
            SpawnResult(exit_code=1, stdout="", stderr="429 too many requests"),
            SpawnResult(exit_code=0, stdout="approved", stderr=""),
        ],
    ) as spawn:
        with patch.object(orch, "on_lane_reviewed", new_callable=AsyncMock):
            await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "reviewed"
    assert spawn.await_count == 2
    assert "recovery_events" not in lane
    assert "last_recovery_event" not in lane
    assert "failure_error" not in lane


@pytest.mark.asyncio
async def test_review_spawn_circuit_open_marks_infra_retry(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )
    orch._recovery.config = orch._recovery.config.__class__(
        max_attempts=1,
        circuit_failure_threshold=1,
        circuit_recovery_timeout_s=30,
    )
    orch._recovery.circuit("orchestrator.review_god").record_failure()

    await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_infra_unavailable"
    assert lane["review_infra_reason"] == "circuit_open"
    assert lane["degraded_component"] == "review_god"


@pytest.mark.asyncio
async def test_review_spawn_non_transient_failure_preserves_valid_state(setup):
    tmp_path, lanes_path = setup
    lanes_path.write_text(json.dumps({"lanes": [
        {
            "feature_id": "lane-1",
            "status": "gated",
            "prompt": "fix",
            "worktree": str(tmp_path),
            "gate_passed": True,
        },
    ]}))
    orch = PlatformOrchestrator(
        lanes_path=lanes_path, xmuse_root=tmp_path, mcp_port=9999,
    )

    with patch.object(
        orch._spawner,
        "spawn",
        new_callable=AsyncMock,
        side_effect=RuntimeError("bad review command"),
    ):
        await orch._run_review_god("lane-1")

    lane = orch._sm.get_lane("lane-1")
    assert lane["status"] == "gate_failed"
    assert lane["failure_reason"] == "review_spawn_failed"
    assert lane["review_infra_reason"] == "RuntimeError"
