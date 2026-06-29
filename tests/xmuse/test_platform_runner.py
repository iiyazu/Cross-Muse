from __future__ import annotations

import asyncio
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.chat.dispatch_queue import ChatDispatchQueueStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.integrations.memoryos_client import FakeMemoryOSClient
from xmuse_core.integrations.memoryos_namespace import conversation_namespace
from xmuse_core.platform.execution.github_ops import (
    GitHubMainCiEvidence,
    GitHubServerSideTruthEvidence,
)
from xmuse_core.platform.run_health import build_process_inventory
from xmuse_core.structuring.models import (
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


def _empty_peer_chat_worktree(root: Path) -> Path:
    worktree = root / "peer_chat_worktree"
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree


class _StaticGithubTruthCollector:
    def __init__(self, evidence: GitHubServerSideTruthEvidence) -> None:
        self._evidence = evidence

    def collect(
        self,
        *,
        repo: str,
        pull_request_number: int,
        required_checks: list[str],
    ) -> GitHubServerSideTruthEvidence:
        assert repo == self._evidence.repo
        assert pull_request_number == self._evidence.pull_request_number
        assert required_checks == self._evidence.required_checks
        return self._evidence


class _StaticMainCiTruthCollector:
    def __init__(self, evidence: GitHubMainCiEvidence) -> None:
        self._evidence = evidence

    def collect_main_ci(
        self,
        *,
        repo: str,
        merge_commit_sha: str,
    ) -> GitHubMainCiEvidence:
        assert repo == "iiyazu/Cross-Muse"
        assert merge_commit_sha == self._evidence.head_sha
        return self._evidence


def _complete_server_side_merge_truth() -> GitHubServerSideTruthEvidence:
    return GitHubServerSideTruthEvidence(
        repo="iiyazu/Cross-Muse",
        pull_request_number=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        proof_level="server_side_merge_proof",
        head_sha="abc123",
        workflow_run_id=82564030146,
        check_run_ids=[82564030146, 82564030153, 82564030160, 82564030167],
        check_run_names=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        check_run_head_shas=["abc123", "abc123", "abc123", "abc123"],
        expected_source_app="github-actions",
        branch_protection_snapshot={
            "required_status_checks": {
                "strict": True,
                "checks": [
                    {"context": "quality-gates"},
                    {"context": "contract-smoke-gates"},
                    {"context": "real-runtime-integration-gate"},
                    {"context": "peer-chat-runtime-gate"},
                ],
            },
            "required_pull_request_reviews": None,
        },
        internal_review_artifact="acceptance_gate_runner",
        internal_reviewer="platform-runner",
        internal_reviewed_head_sha="abc123",
        internal_review_verified=True,
        merge_commit_sha="4fd40a735e62be255e787ce93bdc3d5653d0255e",
        merged_at="2026-06-21T10:56:19Z",
        merge_event_id="PR_kwDOExample",
    )


def _successful_main_ci_truth() -> GitHubMainCiEvidence:
    return GitHubMainCiEvidence(
        workflow_run_id=28351375224,
        workflow_name="xmuse CI",
        head_sha="4fd40a735e62be255e787ce93bdc3d5653d0255e",
        head_branch="main",
        status="completed",
        conclusion="success",
        url="https://github.com/iiyazu/Cross-Muse/actions/runs/28351375224",
        created_at="2026-06-29T05:47:21Z",
        updated_at="2026-06-29T05:48:00Z",
    )


def _incomplete_server_side_truth() -> GitHubServerSideTruthEvidence:
    return GitHubServerSideTruthEvidence(
        repo="iiyazu/Cross-Muse",
        pull_request_number=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        proof_level="manual_gap",
        gap_reason="missing server-side truth: merge_truth",
    )


def test_peer_chat_runtime_worktree_creates_repo_backed_detached_worktree(
    monkeypatch,
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "xmuse@example.invalid"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "xmuse"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("repo context\n", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True)
    subprocess.run(
        ["git", "commit", "-m", "seed"],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    monkeypatch.setattr(platform_runner, "ROOT", repo)

    xmuse_root = tmp_path / "xmuse-root"
    worktree = platform_runner._peer_chat_runtime_worktree(xmuse_root)
    try:
        assert (worktree / "tracked.txt").read_text(encoding="utf-8") == "repo context\n"
        git_check = subprocess.run(
            ["git", "-C", str(worktree), "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert git_check.stdout.strip() == "true"
        branch = subprocess.run(
            ["git", "-C", str(worktree), "branch", "--show-current"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert branch.stdout.strip() == ""
    finally:
        subprocess.run(
            ["git", "-C", str(repo), "worktree", "remove", "--force", str(worktree)],
            check=False,
            capture_output=True,
        )


class _FakeStateMachine:
    def __init__(self, lanes=None):
        self._lanes = lanes or []

    def get_lanes(self, status: str | None = None):
        if status is None:
            return list(self._lanes)
        return [lane for lane in self._lanes if lane.get("status") == status]


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
async def test_runner_no_auto_merge_enables_final_action_hold(
    monkeypatch,
    tmp_path: Path,
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
            captured["require_final_action_approval"] = require_final_action_approval
            self._sm = _FakeStateMachine()

        async def reconcile_status_changes(self) -> None:
            return None

        async def dispatch_lane(self, lane_id: str) -> None:
            return None

    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)

    args = platform_runner.main_arg_parser().parse_args(["--no-auto-merge"])

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        require_final_action_approval=(
            args.require_final_action_approval or args.no_auto_merge
        ),
    )

    assert captured["require_final_action_approval"] is True


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
            captured["orchestrator_kwargs"] = kwargs
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
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )

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
    assert captured["scheduler_kwargs"]["post_writeback_grace_s"] == 8.0
    assert captured["scheduler_kwargs"]["claim_ttl_s"] >= (
        captured["scheduler_kwargs"]["response_wait_s"]
    )
    peer_worktree = tmp_path / "xmuse" / "peer_chat_worktree"
    assert captured["scheduler_kwargs"]["worktree"] == peer_worktree
    assert peer_worktree.is_dir()
    assert (
        captured["orchestrator_kwargs"]["review_god_session_layer"]
        is captured["scheduler_kwargs"]["god_layer"]
    )
    assert captured["scheduler_kwargs"]["memoryos_client"] is None


@pytest.mark.asyncio
async def test_runner_wires_peer_chat_memoryos_sidecar_client(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakePeerMemoryOSClient:
        def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
            self.base_url = base_url
            self.api_key = api_key

    class FakeOrchestrator:
        def __init__(self, **kwargs) -> None:
            captured["orchestrator_kwargs"] = kwargs
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
    monkeypatch.setenv("XMUSE_PEER_CHAT_MEMORYOS_API_KEY", "sidecar-key")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        platform_runner,
        "PeerChatMemoryOSClient",
        FakePeerMemoryOSClient,
    )
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
        peer_chat_memoryos_url="http://peer-memoryos.test",
    )

    memoryos_client = captured["scheduler_kwargs"]["memoryos_client"]
    assert isinstance(memoryos_client, FakePeerMemoryOSClient)
    assert memoryos_client.base_url == "http://peer-memoryos.test"
    assert memoryos_client.api_key == "sidecar-key"
    assert captured["orchestrator_kwargs"]["memoryos_client"] is None


@pytest.mark.asyncio
async def test_runner_wires_peer_chat_response_wait_and_writeback_grace_overrides(
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
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
        peer_chat_response_wait_s=432.0,
        peer_chat_post_writeback_grace_s=20.0,
    )

    assert captured["scheduler_kwargs"]["response_wait_s"] == 432.0
    assert captured["scheduler_kwargs"]["post_writeback_grace_s"] == 20.0
    assert captured["scheduler_kwargs"]["claim_ttl_s"] >= 482


@pytest.mark.asyncio
async def test_runner_uses_native_peer_god_layer_by_default(
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

    monkeypatch.delenv("XMUSE_PEER_GOD_BACKEND", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )

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
async def test_runner_builds_dispatch_bridge_with_peer_god_layer(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}

    class FakePeerMemoryOSClient:
        def __init__(self, *, base_url: str, api_key: str | None = None) -> None:
            self.base_url = base_url
            self.api_key = api_key

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
    monkeypatch.setattr(
        platform_runner,
        "PeerChatMemoryOSClient",
        FakePeerMemoryOSClient,
    )
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )
    monkeypatch.setattr(dispatch_bridge_module, "ChatDispatchBridge", FakeDispatchBridge)

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
        peer_chat_dispatch_response_wait_s=321.0,
        peer_chat_memoryos_url="http://peer-memoryos.test",
    )

    assert captured["dispatch_bridge_kwargs"]["bridge_id"] == "platform-runner-dispatch"
    assert (
        captured["dispatch_bridge_kwargs"]["god_layer"]
        is captured["scheduler_kwargs"]["god_layer"]
    )
    assert (
        captured["dispatch_bridge_kwargs"]["worktree"]
        == captured["scheduler_kwargs"]["worktree"]
    )
    assert Path(captured["dispatch_bridge_kwargs"]["worktree"]).name == "peer_chat_worktree"
    assert captured["dispatch_bridge_kwargs"]["response_wait_s"] == 321.0
    assert captured["dispatch_bridge_kwargs"]["claim_ttl_s"] >= 351
    assert isinstance(captured["scheduler_kwargs"]["memoryos_client"], FakePeerMemoryOSClient)
    assert (
        captured["dispatch_bridge_kwargs"]["memoryos_client"]
        is captured["scheduler_kwargs"]["memoryos_client"]
    )


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
async def test_runner_prewarm_ray_peer_god_layer_when_explicitly_selected(
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

    monkeypatch.setenv("XMUSE_PEER_GOD_BACKEND", "ray")
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(ray_session_layer_module.RayGodSessionLayer, "prewarm", fake_prewarm)
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )

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
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )

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
async def test_runner_can_force_native_peer_god_layer_from_run_argument(
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

    monkeypatch.delenv("XMUSE_PEER_GOD_BACKEND", raising=False)
    monkeypatch.setattr(platform_runner, "PlatformOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(peer_scheduler_module, "PeerChatScheduler", FakePeerScheduler)
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
    )

    await platform_runner.run(
        lanes_path=tmp_path / "feature_lanes.json",
        xmuse_root=tmp_path / "xmuse",
        mcp_port=8100,
        max_hours=0,
        max_concurrent=1,
        peer_chat_enabled=True,
        peer_god_backend="native",
    )

    assert type(captured["scheduler_kwargs"]["god_layer"]).__name__ == "GodSessionLayer"


def test_platform_runner_accepts_peer_god_backend_cli_argument() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--peer-chat", "--peer-god-backend", "native"]
    )

    assert args.peer_chat is True
    assert args.peer_god_backend == "native"




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
        lambda **_kwargs: build_process_inventory(
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


def test_platform_runner_defaults_peer_chat_writeback_grace() -> None:
    args = platform_runner.main_arg_parser().parse_args([])

    platform_runner.validate_args(args)
    assert args.peer_chat_response_wait_s == 900.0
    assert args.peer_chat_post_writeback_grace_s == 8.0


def test_platform_runner_supports_peer_chat_wait_overrides() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--peer-chat",
            "--peer-chat-response-wait-s",
            "432",
            "--peer-chat-post-writeback-grace-s",
            "20",
        ]
    )

    platform_runner.validate_args(args)
    assert args.peer_chat_response_wait_s == 432.0
    assert args.peer_chat_post_writeback_grace_s == 20.0


def test_platform_runner_supports_peer_chat_memoryos_url() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--peer-chat", "--peer-chat-memoryos-url", "http://memoryos.sidecar"]
    )

    platform_runner.validate_args(args)
    assert args.peer_chat is True
    assert args.peer_chat_memoryos_url == "http://memoryos.sidecar"


@pytest.mark.parametrize("wait_s", ["0", "-1", "nan", "inf"])
def test_platform_runner_rejects_invalid_peer_chat_response_wait(
    wait_s: str,
) -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--peer-chat-response-wait-s", wait_s]
    )

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


@pytest.mark.parametrize("grace", ["-1", "nan", "inf"])
def test_platform_runner_rejects_invalid_peer_chat_writeback_grace(
    grace: str,
) -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--peer-chat-post-writeback-grace-s", grace]
    )

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


def test_runner_parser_supports_acceptance_gated_goal() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--goal",
            "Run a bounded acceptance gate smoke.",
            "--acceptance-gate",
            "--github-pr",
            "154",
        ]
    )

    platform_runner.validate_args(args)
    assert args.goal == "Run a bounded acceptance gate smoke."
    assert args.acceptance_gate is True
    assert args.github_pr == 154


def test_runner_parser_supports_existing_final_action_resolution() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--resolve-final-action",
            "--lane-id",
            "lane-ready",
            "--github-pr",
            "155",
            "--github-head-sha",
            "abc123",
        ]
    )

    platform_runner.validate_args(args)
    assert args.resolve_final_action is True
    assert args.lane_id == "lane-ready"
    assert args.github_pr == 155
    assert args.github_head_sha == "abc123"


def test_runner_rejects_resolve_final_action_without_hold_selector() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        ["--resolve-final-action", "--github-pr", "155"]
    )

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_runner_parser_supports_create_final_action_pr() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--create-final-action-pr",
            "--final-action-id",
            "final-pr",
            "--github-repo",
            "iiyazu/Cross-Muse",
            "--pr-base-branch",
            "main",
            "--pr-branch-prefix",
            "codex/",
        ]
    )

    platform_runner.validate_args(args)
    assert args.create_final_action_pr is True
    assert args.final_action_id == "final-pr"
    assert args.github_repo == "iiyazu/Cross-Muse"
    assert args.pr_base_branch == "main"
    assert args.pr_branch_prefix == "codex/"


def test_runner_rejects_create_final_action_pr_without_hold_selector() -> None:
    args = platform_runner.main_arg_parser().parse_args(["--create-final-action-pr"])

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_runner_parser_supports_opt_in_live_github_capture(tmp_path: Path) -> None:
    review_artifact = tmp_path / "internal-review.json"
    review_artifact.write_text('{"review":"accepted"}\n', encoding="utf-8")
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--goal",
            "Run live capture.",
            "--acceptance-gate",
            "--github-pr",
            "155",
            "--github-live-capture",
            "--internal-review-artifact",
            str(review_artifact),
            "--internal-reviewer",
            "platform-runner",
            "--internal-reviewed-head-sha",
            "abc123",
        ]
    )

    platform_runner.validate_args(args)
    assert args.github_live_capture is True
    assert args.internal_review_artifact == review_artifact
    assert args.internal_reviewer == "platform-runner"
    assert args.internal_reviewed_head_sha == "abc123"


def test_runner_parser_supports_main_ci_capture_without_internal_review_args() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--capture-final-action-main-ci",
            "--final-action-id",
            "final-main-ci",
            "--github-live-capture",
        ]
    )

    platform_runner.validate_args(args)
    assert args.capture_final_action_main_ci is True
    assert args.final_action_id == "final-main-ci"


def test_runner_rejects_main_ci_capture_without_live_capture() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--capture-final-action-main-ci",
            "--final-action-id",
            "final-main-ci",
        ]
    )

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_runner_parser_supports_dispatch_sidecar_handoff_capture() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--capture-dispatch-sidecar-handoff",
            "--dispatch-entry-id",
            "dispatch:conv:res:execute",
            "--peer-chat-memoryos-url",
            "http://memoryos.test",
        ]
    )

    platform_runner.validate_args(args)
    assert args.capture_dispatch_sidecar_handoff is True
    assert args.dispatch_entry_id == "dispatch:conv:res:execute"


def test_runner_rejects_dispatch_sidecar_handoff_capture_without_url() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--capture-dispatch-sidecar-handoff",
            "--dispatch-entry-id",
            "dispatch:conv:res:execute",
        ]
    )

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_runner_rejects_live_capture_without_internal_review_artifact() -> None:
    args = platform_runner.main_arg_parser().parse_args(
        [
            "--goal",
            "Run live capture.",
            "--acceptance-gate",
            "--github-pr",
            "155",
            "--github-live-capture",
            "--internal-reviewer",
            "platform-runner",
            "--internal-reviewed-head-sha",
            "abc123",
        ]
    )

    with pytest.raises(SystemExit):
        platform_runner.validate_args(args)


def test_acceptance_gated_goal_run_blocks_without_server_side_merge_proof(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"

    result = platform_runner.run_acceptance_gated_goal(
        goal="Record a short acceptance-gated smoke task.",
        xmuse_root=xmuse_root,
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=154,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        head_sha="abc123",
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "github_gate_unverified"

    gate_payload = json.loads(
        (xmuse_root / "github_gate_evidence.json").read_text(encoding="utf-8")
    )
    final_actions = json.loads(
        (xmuse_root / "final_actions.json").read_text(encoding="utf-8")
    )
    hold = final_actions["holds"][0]
    evidence = gate_payload["items"][0]
    assert evidence["final_action_id"] == hold["id"]
    assert evidence["repo"] == "iiyazu/Cross-Muse"
    assert evidence["pull_request_number"] == 154
    assert evidence["required_checks"] == [
        "quality-gates",
        "contract-smoke-gates",
        "real-runtime-integration-gate",
        "peer-chat-runtime-gate",
    ]
    assert evidence["can_accept"] is False
    assert evidence["evidence"]["proof_level"] == "manual_gap"
    assert evidence["evidence"]["internal_reviewed_head_sha"] == "abc123"
    assert hold.get("github_gate_evidence_ref") is None
    assert hold["github_gate_gap_ref"] == (
        f"github_gate_evidence.json#evidence={evidence['id']}"
    )

    spines = AcceptanceSpineStore(xmuse_root / "chat.db").list_by_conversation(
        result["conversation_id"]
    )
    assert len(spines) == 1
    assert spines[0].status.value == "blocked"
    assert spines[0].blocked_reason == "github_gate_unverified"
    assert spines[0].github_gate_evidence_ref is None
    assert result["durable_refs"]["github_gate_evidence_ref"] == (
        f"github_gate_evidence.json#evidence={evidence['id']}"
    )

    lanes_payload = json.loads(
        (xmuse_root / "feature_lanes.json").read_text(encoding="utf-8")
    )
    lane = lanes_payload["lanes"][0]
    assert lane["feature_id"] == result["lane_id"]
    assert lane["status"] == "blocked_for_input"
    assert lane["blocked_reason"] == "github_gate_unverified"
    assert "failure_reason" not in lane
    assert lane["final_action_ref"] == f"final_actions.json#hold={hold['id']}"
    assert lane["github_gate_gap_ref"] == hold["github_gate_gap_ref"]

    health = platform_runner.health_once(
        xmuse_root / "feature_lanes.json",
        live_pids=set(),
        xmuse_root=xmuse_root,
    )
    assert health["counts"]["live"] == 0
    assert health["counts"]["terminal"] == 1
    assert health["counts"]["takeover_context_needed"] == 0
    assert health["groups"]["terminal"] == [result["lane_id"]]
    assert health["groups"]["takeover_context_needed"] == []


def test_acceptance_gated_goal_run_accepts_with_server_side_merge_proof(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"

    result = platform_runner.run_acceptance_gated_goal(
        goal="Record an accepted acceptance-gated smoke task.",
        xmuse_root=xmuse_root,
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        head_sha="abc123",
        github_gate_collector=_StaticGithubTruthCollector(
            _complete_server_side_merge_truth()
        ),
        main_ci_collector=_StaticMainCiTruthCollector(_successful_main_ci_truth()),
    )

    assert result["status"] == "accepted"
    assert result["blocked_reason"] is None

    gate_payload = json.loads(
        (xmuse_root / "github_gate_evidence.json").read_text(encoding="utf-8")
    )
    final_actions = json.loads(
        (xmuse_root / "final_actions.json").read_text(encoding="utf-8")
    )
    hold = final_actions["holds"][0]
    evidence = gate_payload["items"][0]
    assert evidence["final_action_id"] == hold["id"]
    assert evidence["can_accept"] is True
    assert evidence["evidence"]["proof_level"] == "server_side_merge_proof"
    assert evidence["main_ci"] == {
        "workflow_run_id": 28351375224,
        "workflow_name": "xmuse CI",
        "head_sha": "4fd40a735e62be255e787ce93bdc3d5653d0255e",
        "head_branch": "main",
        "status": "completed",
        "conclusion": "success",
        "url": "https://github.com/iiyazu/Cross-Muse/actions/runs/28351375224",
        "created_at": "2026-06-29T05:47:21Z",
        "updated_at": "2026-06-29T05:48:00Z",
        "gap_reason": None,
    }
    assert hold["github_gate_evidence_ref"] == (
        f"github_gate_evidence.json#evidence={evidence['id']}"
    )
    assert hold.get("github_gate_gap_ref") is None

    spines = AcceptanceSpineStore(xmuse_root / "chat.db").list_by_conversation(
        result["conversation_id"]
    )
    assert len(spines) == 1
    assert spines[0].status.value == "accepted"
    assert spines[0].blocked_reason is None
    assert spines[0].github_gate_evidence_ref == hold["github_gate_evidence_ref"]

    lanes_payload = json.loads(
        (xmuse_root / "feature_lanes.json").read_text(encoding="utf-8")
    )
    lane = lanes_payload["lanes"][0]
    assert lane["feature_id"] == result["lane_id"]
    assert lane["status"] == "merged"
    assert lane["integration_mode"] == "noop"
    assert lane["final_action_ref"] == f"final_actions.json#hold={hold['id']}"
    assert lane["github_gate_evidence_ref"] == hold["github_gate_evidence_ref"]

    health = platform_runner.health_once(
        xmuse_root / "feature_lanes.json",
        live_pids=set(),
        xmuse_root=xmuse_root,
    )
    assert health["counts"]["live"] == 0
    assert health["counts"]["terminal"] == 1
    assert health["counts"]["unsafe_to_release_dependents"] == 0
    assert health["groups"]["terminal"] == [result["lane_id"]]
    assert health["groups"]["unsafe_to_release_dependents"] == []


def test_resolve_existing_final_action_accepts_with_server_side_merge_proof(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    xmuse_root.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-gh-proof",
                        "status": "awaiting_final_action",
                        "prompt": "ready for github proof",
                        "final_action_hold_id": "final-gh-proof",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-gh-proof",
                        "lane_id": "lane-gh-proof",
                        "verdict_id": "verdict-gh-proof",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after GitHub proof",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = platform_runner.resolve_existing_final_action_with_github_gate(
        xmuse_root=xmuse_root,
        lane_id="lane-gh-proof",
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        head_sha="abc123",
        github_gate_collector=_StaticGithubTruthCollector(
            _complete_server_side_merge_truth()
        ),
        main_ci_collector=_StaticMainCiTruthCollector(_successful_main_ci_truth()),
    )

    assert result["status"] == "accepted"
    assert result["blocked_reason"] is None
    gate_payload = json.loads(
        (xmuse_root / "github_gate_evidence.json").read_text(encoding="utf-8")
    )
    final_actions = json.loads(
        (xmuse_root / "final_actions.json").read_text(encoding="utf-8")
    )
    lanes = json.loads((xmuse_root / "feature_lanes.json").read_text(encoding="utf-8"))
    evidence = gate_payload["items"][0]
    hold = final_actions["holds"][0]
    lane = lanes["lanes"][0]
    assert evidence["can_accept"] is True
    assert evidence["main_ci"]["conclusion"] == "success"
    assert evidence["main_ci"]["head_sha"] == (
        evidence["evidence"]["merge_commit_sha"]
    )
    assert hold["status"] == "approved"
    assert hold["github_gate_evidence_ref"] == (
        f"github_gate_evidence.json#evidence={evidence['id']}"
    )
    assert lane["status"] == "merged"
    assert lane["github_gate_evidence_ref"] == hold["github_gate_evidence_ref"]
    assert lane["final_action_ref"] == "final_actions.json#hold=final-gh-proof"


def test_capture_existing_final_action_main_ci_updates_accepted_gate_record(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    xmuse_root.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-main-ci",
                        "status": "awaiting_final_action",
                        "prompt": "ready for main ci proof",
                        "final_action_hold_id": "final-main-ci",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-main-ci",
                        "lane_id": "lane-main-ci",
                        "verdict_id": "verdict-main-ci",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after GitHub proof",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    accepted = platform_runner.resolve_existing_final_action_with_github_gate(
        xmuse_root=xmuse_root,
        final_action_id="final-main-ci",
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        head_sha="abc123",
        github_gate_collector=_StaticGithubTruthCollector(
            _complete_server_side_merge_truth()
        ),
    )
    before = json.loads(
        (xmuse_root / "github_gate_evidence.json").read_text(encoding="utf-8")
    )
    assert before["items"][0]["main_ci"] is None

    captured = platform_runner.capture_existing_final_action_main_ci(
        xmuse_root=xmuse_root,
        final_action_id="final-main-ci",
        main_ci_collector=_StaticMainCiTruthCollector(_successful_main_ci_truth()),
    )

    after = json.loads(
        (xmuse_root / "github_gate_evidence.json").read_text(encoding="utf-8")
    )
    assert captured["status"] == "captured"
    assert captured["blocked_reason"] is None
    assert captured["github_gate_evidence_ref"] == accepted["durable_refs"][
        "github_gate_evidence_ref"
    ]
    assert len(after["items"]) == 1
    assert after["items"][0]["main_ci"]["conclusion"] == "success"
    assert after["items"][0]["main_ci"]["head_sha"] == (
        after["items"][0]["evidence"]["merge_commit_sha"]
    )


@pytest.mark.asyncio
async def test_capture_existing_dispatch_sidecar_handoff_records_continuity(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    xmuse_root.mkdir()
    db = xmuse_root / "chat.db"
    chat = ChatStore(db)
    conv = chat.create_conversation("Dispatch sidecar handoff")
    intake = chat.add_message(conv.id, "Human", "human", "Run sidecar handoff")
    proposal = chat.create_proposal(
        conversation_id=conv.id,
        author="Architect GOD",
        proposal_type="lane_graph",
        content='{"summary":"sidecar handoff"}',
        references=[intake.id],
    )
    resolution = chat.approve_proposal(
        proposal.id,
        approved_by=["human"],
        approval_mode="human",
        goal_summary="Run sidecar handoff",
    )
    dispatch = ChatDispatchQueueStore(db).enqueue_agent_auto_dispatch(
        conversation_id=conv.id,
        proposal_id=proposal.id,
        resolution_id=resolution.id,
        collaboration_run_id="collab-sidecar",
        artifact_ref="artifact:sidecar-lane-graph",
        gate_refs=["review_trigger_verdict:sidecar"],
    )
    memoryos = FakeMemoryOSClient()

    result = await platform_runner.capture_existing_dispatch_sidecar_handoff(
        xmuse_root=xmuse_root,
        dispatch_entry_id=dispatch.entry_id,
        memoryos_client=memoryos,
        actor_id="platform-runner-test",
    )

    expected_refs = [
        f"chat_dispatch_queue:{dispatch.entry_id}",
        f"proposal:{proposal.id}",
        "review_trigger_verdict:sidecar",
        f"resolution:{resolution.id}",
        "collaboration:collab-sidecar",
        "artifact:sidecar-lane-graph",
    ]
    assert result["status"] == "captured"
    assert result["dispatch_entry_id"] == dispatch.entry_id
    assert result["sidecar_status"] == "recorded"
    assert result["source_refs"] == expected_refs
    assert result["continuity_refs"] == [
        f"memory://conversation/{conv.id}/refs/chat_dispatch_queue:{dispatch.entry_id}"
    ]
    pages = await memoryos.search(
        conversation_namespace(conv.id),
        query="dispatch handoff",
    )
    assert len(pages) == 1
    assert pages[0].actor_id == "platform-runner-test"
    assert pages[0].source_refs == expected_refs
    traces = PeerTurnLatencyTraceStore(db).list_recent(conv.id, limit=5)
    [trace] = traces
    assert trace["delivery_mode"] == "memoryos_sidecar_dispatch_handoff"
    assert trace["supporting_context"] == {
        "memoryos_sidecar": {
            "status": "recorded",
            "authority": "memoryos_sidecar",
            "proof_level": "contract",
            "namespace_uri": f"memory://conversation/{conv.id}",
            "degraded_reason": None,
            "source_refs": expected_refs,
            "continuity_refs": result["continuity_refs"],
        }
    }


def test_resolve_existing_final_action_blocks_on_github_gate_gap(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    xmuse_root.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-gh-gap",
                        "status": "awaiting_final_action",
                        "prompt": "ready for github proof",
                        "final_action_hold_id": "final-gh-gap",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-gh-gap",
                        "lane_id": "lane-gh-gap",
                        "verdict_id": "verdict-gh-gap",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after GitHub proof",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = platform_runner.resolve_existing_final_action_with_github_gate(
        xmuse_root=xmuse_root,
        lane_id="lane-gh-gap",
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        github_gate_collector=_StaticGithubTruthCollector(_incomplete_server_side_truth()),
    )

    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "github_gate_unverified"
    final_actions = json.loads(
        (xmuse_root / "final_actions.json").read_text(encoding="utf-8")
    )
    lanes = json.loads((xmuse_root / "feature_lanes.json").read_text(encoding="utf-8"))
    hold = final_actions["holds"][0]
    lane = lanes["lanes"][0]
    assert hold["status"] == "blocked"
    assert hold["github_gate_gap_ref"].startswith("github_gate_evidence.json#evidence=")
    assert "github_gate_evidence_ref" not in hold
    assert lane["status"] == "blocked_for_input"
    assert lane["blocked_reason"] == "github_gate_unverified"
    assert lane["github_gate_gap_ref"] == hold["github_gate_gap_ref"]


def test_resolve_existing_final_action_blocks_on_expected_head_mismatch(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    xmuse_root.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-head-mismatch",
                        "status": "awaiting_final_action",
                        "prompt": "ready for github proof",
                        "final_action_hold_id": "final-head-mismatch",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-head-mismatch",
                        "lane_id": "lane-head-mismatch",
                        "verdict_id": "verdict-head-mismatch",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after GitHub proof",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    result = platform_runner.resolve_existing_final_action_with_github_gate(
        xmuse_root=xmuse_root,
        lane_id="lane-head-mismatch",
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        head_sha="different-head",
        github_gate_collector=_StaticGithubTruthCollector(
            _complete_server_side_merge_truth()
        ),
    )

    assert result["status"] == "blocked"
    gate_payload = json.loads(
        (xmuse_root / "github_gate_evidence.json").read_text(encoding="utf-8")
    )
    evidence = gate_payload["items"][0]
    assert evidence["can_accept"] is False
    assert evidence["gap_reason"] == "github evidence head SHA mismatch"
    assert evidence["evidence"]["proof_level"] == "manual_gap"
    assert evidence["evidence"]["head_sha"] == "abc123"
    final_actions = json.loads(
        (xmuse_root / "final_actions.json").read_text(encoding="utf-8")
    )
    assert final_actions["holds"][0]["status"] == "blocked"
    assert final_actions["holds"][0]["github_gate_gap_ref"] == (
        f"github_gate_evidence.json#evidence={evidence['id']}"
    )


def test_resolve_existing_final_action_projection_preflight_failure_keeps_hold_pending(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    xmuse_root.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-preflight",
                        "status": "awaiting_final_action",
                        "prompt": "ready for github proof",
                        "final_action_hold_id": "different-final-action",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-preflight",
                        "lane_id": "lane-preflight",
                        "verdict_id": "verdict-preflight",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after GitHub proof",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError, match="final-action projection hold mismatch"):
        platform_runner.resolve_existing_final_action_with_github_gate(
            xmuse_root=xmuse_root,
            lane_id="lane-preflight",
            github_repo="iiyazu/Cross-Muse",
            github_pull_request=155,
            required_checks=[
                "quality-gates",
                "contract-smoke-gates",
                "real-runtime-integration-gate",
                "peer-chat-runtime-gate",
            ],
            github_gate_collector=_StaticGithubTruthCollector(
                _complete_server_side_merge_truth()
            ),
        )

    final_actions = json.loads(
        (xmuse_root / "final_actions.json").read_text(encoding="utf-8")
    )
    assert final_actions["holds"][0]["status"] == "pending"
    assert not (xmuse_root / "github_gate_evidence.json").exists()


def test_resolve_existing_final_action_can_retry_after_github_gate_gap(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    xmuse_root.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-gh-retry",
                        "status": "awaiting_final_action",
                        "prompt": "ready for github proof",
                        "final_action_hold_id": "final-gh-retry",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-gh-retry",
                        "lane_id": "lane-gh-retry",
                        "verdict_id": "verdict-gh-retry",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after GitHub proof",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    blocked = platform_runner.resolve_existing_final_action_with_github_gate(
        xmuse_root=xmuse_root,
        final_action_id="final-gh-retry",
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        github_gate_collector=_StaticGithubTruthCollector(_incomplete_server_side_truth()),
    )
    accepted = platform_runner.resolve_existing_final_action_with_github_gate(
        xmuse_root=xmuse_root,
        final_action_id="final-gh-retry",
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        head_sha="abc123",
        github_gate_collector=_StaticGithubTruthCollector(
            _complete_server_side_merge_truth()
        ),
    )

    assert blocked["status"] == "blocked"
    assert accepted["status"] == "accepted"
    final_actions = json.loads(
        (xmuse_root / "final_actions.json").read_text(encoding="utf-8")
    )
    lanes = json.loads((xmuse_root / "feature_lanes.json").read_text(encoding="utf-8"))
    hold = final_actions["holds"][0]
    lane = lanes["lanes"][0]
    assert hold["status"] == "approved"
    assert "github_gate_gap_ref" not in hold
    assert hold["github_gate_evidence_ref"] == accepted["durable_refs"][
        "github_gate_evidence_ref"
    ]
    assert lane["status"] == "merged"
    assert lane["github_gate_evidence_ref"] == hold["github_gate_evidence_ref"]
    assert "github_gate_gap_ref" not in lane


class _FakeFinalActionPrCommandRunner:
    def __init__(self, *, dirty: bool = True) -> None:
        self.dirty = dirty
        self.commands: list[tuple[tuple[str, ...], Path]] = []
        self.base_synced = False

    def __call__(
        self,
        command,
        *,
        cwd=None,
        capture_output=True,
        text=True,
        timeout=None,
        check=False,
    ):
        del capture_output, text, timeout, check
        cmd = tuple(str(part) for part in command)
        self.commands.append((cmd, Path(cwd or ".")))
        if cmd[:3] == ("git", "rev-parse", "--is-inside-work-tree"):
            return subprocess.CompletedProcess(command, 0, stdout="true\n", stderr="")
        if cmd[:3] == ("git", "status", "--porcelain"):
            stdout = "?? docs/xmuse/new.md\n" if self.dirty else ""
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        if cmd[:2] == ("git", "checkout"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if cmd[:2] == ("git", "add"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if cmd[:2] == ("git", "commit"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="[codex/lane-pr 1234567] docs: add lane-pr\n",
                stderr="",
            )
        if cmd[:3] == ("git", "fetch", "origin"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if cmd[:3] == ("git", "merge", "--no-edit"):
            self.base_synced = True
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="Merge made by the 'ort' strategy.\n",
                stderr="",
            )
        if cmd[:3] == ("git", "rev-parse", "HEAD"):
            stdout = "syncedhead123\n" if self.base_synced else "head123\n"
            return subprocess.CompletedProcess(command, 0, stdout=stdout, stderr="")
        if cmd[:2] == ("git", "push"):
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
        if cmd[:3] == ("gh", "pr", "create"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout="https://github.com/iiyazu/Cross-Muse/pull/999\n",
                stderr="",
            )
        if cmd[:3] == ("gh", "pr", "view"):
            return subprocess.CompletedProcess(
                command,
                0,
                stdout=json.dumps(
                    {
                        "number": 999,
                        "url": "https://github.com/iiyazu/Cross-Muse/pull/999",
                        "headRefOid": (
                            "syncedhead123" if self.base_synced else "head123"
                        ),
                    }
                )
                + "\n",
                stderr="",
            )
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="unexpected")


def test_create_final_action_pull_request_records_pr_without_resolving_hold(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    worktree = tmp_path / "worktree"
    xmuse_root.mkdir()
    worktree.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-pr",
                        "status": "awaiting_final_action",
                        "worktree": str(worktree),
                        "branch": "lane-pr",
                        "base_head_sha": "base123",
                        "final_action_hold_id": "final-pr",
                        "review_verdict_id": "verdict-pr",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-pr",
                        "lane_id": "lane-pr",
                        "verdict_id": "verdict-pr",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after PR",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    runner = _FakeFinalActionPrCommandRunner()

    result = platform_runner.create_final_action_pull_request(
        xmuse_root=xmuse_root,
        final_action_id="final-pr",
        github_repo="iiyazu/Cross-Muse",
        command_runner=runner,
    )

    assert result["status"] == "created"
    assert result["pull_request_number"] == 999
    pr_payload = json.loads(
        (xmuse_root / "final_action_prs.json").read_text(encoding="utf-8")
    )
    record = pr_payload["items"][0]
    assert record["final_action_id"] == "final-pr"
    assert record["lane_id"] == "lane-pr"
    assert record["head_branch"] == "codex/lane-pr"
    assert record["head_sha"] == "syncedhead123"
    assert record["commit_sha"] == "syncedhead123"
    assert record["proof_boundary"] == "pull_request_created_not_merge_truth"
    holds = json.loads((xmuse_root / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"
    lanes = json.loads((xmuse_root / "feature_lanes.json").read_text(encoding="utf-8"))
    lane = lanes["lanes"][0]
    assert lane["status"] == "awaiting_final_action"
    assert lane["pull_request_number"] == 999
    assert lane["pull_request_url"] == "https://github.com/iiyazu/Cross-Muse/pull/999"
    assert lane["pull_request_head_sha"] == "syncedhead123"
    assert any(cmd[:3] == ("gh", "pr", "create") for cmd, _cwd in runner.commands)
    commands = [cmd for cmd, _cwd in runner.commands]
    assert ("git", "fetch", "origin", "main") in commands
    assert ("git", "merge", "--no-edit", "origin/main") in commands
    assert commands.index(("git", "merge", "--no-edit", "origin/main")) < commands.index(
        ("git", "push", "-u", "origin", "HEAD:refs/heads/codex/lane-pr")
    )


def test_create_final_action_pull_request_requires_worktree_changes(
    tmp_path: Path,
) -> None:
    xmuse_root = tmp_path / "runtime"
    worktree = tmp_path / "worktree"
    xmuse_root.mkdir()
    worktree.mkdir()
    (xmuse_root / "feature_lanes.json").write_text(
        json.dumps(
            {
                "lanes": [
                    {
                        "feature_id": "lane-clean",
                        "status": "awaiting_final_action",
                        "worktree": str(worktree),
                        "branch": "lane-clean",
                        "base_head_sha": "base123",
                        "final_action_hold_id": "final-clean",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (xmuse_root / "final_actions.json").write_text(
        json.dumps(
            {
                "holds": [
                    {
                        "id": "final-clean",
                        "lane_id": "lane-clean",
                        "verdict_id": "verdict-clean",
                        "action": "merge",
                        "target_status": "reviewed",
                        "status": "pending",
                        "summary": "merge after PR",
                    }
                ]
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    runner = _FakeFinalActionPrCommandRunner(dirty=False)

    with pytest.raises(RuntimeError, match="final action worktree has no changes"):
        platform_runner.create_final_action_pull_request(
            xmuse_root=xmuse_root,
            lane_id="lane-clean",
            github_repo="iiyazu/Cross-Muse",
            command_runner=runner,
        )

    assert not (xmuse_root / "final_action_prs.json").exists()
    holds = json.loads((xmuse_root / "final_actions.json").read_text(encoding="utf-8"))
    assert holds["holds"][0]["status"] == "pending"
    assert not any(cmd[:3] == ("gh", "pr", "create") for cmd, _cwd in runner.commands)


def test_acceptance_gated_live_capture_gap_stays_blocked(tmp_path: Path) -> None:
    xmuse_root = tmp_path / "runtime"

    result = platform_runner.run_acceptance_gated_goal(
        goal="Record a blocked live capture smoke task.",
        xmuse_root=xmuse_root,
        github_repo="iiyazu/Cross-Muse",
        github_pull_request=155,
        required_checks=[
            "quality-gates",
            "contract-smoke-gates",
            "real-runtime-integration-gate",
            "peer-chat-runtime-gate",
        ],
        head_sha="abc123",
        github_gate_collector=_StaticGithubTruthCollector(
            _incomplete_server_side_truth()
        ),
    )

    gate_payload = json.loads(
        (xmuse_root / "github_gate_evidence.json").read_text(encoding="utf-8")
    )
    assert result["status"] == "blocked"
    assert result["blocked_reason"] == "github_gate_unverified"
    assert gate_payload["items"][0]["can_accept"] is False
    assert gate_payload["items"][0]["evidence"]["proof_level"] == "manual_gap"


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
        lambda **_kwargs: build_process_inventory(runner_pids=[11, 12], mcp_pids=[]),
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
        lambda **_kwargs: build_process_inventory(
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
        lambda **_kwargs: build_process_inventory(runner_pids=[11], mcp_pids=[], services={}),
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
        lambda **_kwargs: build_process_inventory(runner_pids=[11], mcp_pids=[], services={}),
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


def test_health_once_marks_native_peer_backend_and_cleanup_dirty(
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
        lambda **_kwargs: build_process_inventory(
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
    assert operations["readiness"]["ray_god_layer"]["status"] == "native_configured"
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
        lambda **_kwargs: build_process_inventory(runner_pids=[], mcp_pids=[]),
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
        lambda **_kwargs: build_process_inventory(runner_pids=[], mcp_pids=[]),
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
        lambda **_kwargs: build_process_inventory(runner_pids=[], mcp_pids=[]),
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
                "review_peer_cli_kind": "opencode",
                "review_peer_model": "opencode-go/deepseek-v4-flash",
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
        lambda **_kwargs: build_process_inventory(runner_pids=[], mcp_pids=[]),
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
            "review_peer_cli_kind": "opencode",
            "review_peer_model": "opencode-go/deepseek-v4-flash",
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
    monkeypatch.setattr(
        platform_runner,
        "_peer_chat_runtime_worktree",
        _empty_peer_chat_worktree,
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
        graph_id=None,
        resolution_id=None,
    )

    assert [lane["feature_id"] for lane in lanes] == ["lane-1", "lane-3"]


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


def test_repair_stale_dispatched_lanes_marks_dead_worker_exec_failed(monkeypatch) -> None:
    class FakeStateMachine:
        def __init__(self) -> None:
            self._lanes = [
                {
                    "feature_id": "dead-worker",
                    "status": "dispatched",
                    "worker_pid": 123,
                    "dispatched_at": 100.0,
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

    class FakeOrchestrator:
        def __init__(self) -> None:
            self._sm = FakeStateMachine()

    orch = FakeOrchestrator()
    monkeypatch.setattr(platform_runner, "_live_pids", lambda: {456})

    platform_runner._repair_stale_dispatched_lanes(
        orch,
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
        )
    ]
    assert orch._sm.get_lanes()[1]["status"] == "dispatched"
    assert orch._sm.get_lanes()[2]["status"] == "dispatched"
    assert orch._sm.get_lanes()[3]["status"] == "dispatched"
    assert orch._sm.get_lanes()[3]["worker_pid"] == 1000
    assert orch._sm.get_lanes()[4]["status"] == "dispatched"


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
