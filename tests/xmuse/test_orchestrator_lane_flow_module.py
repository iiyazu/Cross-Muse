from __future__ import annotations

from pathlib import Path

from xmuse_core.platform import orchestrator, orchestrator_lane_flow


def test_orchestrator_exposes_extracted_lane_flow_functions() -> None:
    assert orchestrator.dispatch_lane_flow is orchestrator_lane_flow.dispatch_lane
    assert orchestrator.run_execution_god_flow is orchestrator_lane_flow.run_execution_god


class _FakeStateMachine:
    def __init__(self) -> None:
        self.lanes: dict[str, dict] = {}

    def update_metadata(self, lane_id: str, metadata: dict) -> dict:
        lane = {**self.lanes[lane_id], **metadata}
        self.lanes[lane_id] = lane
        return lane


class _FakeOrchestrator:
    def __init__(self, tmp_path: Path) -> None:
        self._root = tmp_path / "runtime"
        self._repo_root = tmp_path / "repo"
        self._sm = _FakeStateMachine()
        self.created_worktrees: list[tuple[Path, str]] = []

    def _create_or_reuse_worktree(self, *, worktree: Path, branch: str) -> None:
        self.created_worktrees.append((worktree, branch))
        worktree.mkdir(parents=True, exist_ok=True)


def test_ensure_lane_worktree_splits_shared_execution_root(
    tmp_path: Path,
    monkeypatch,
) -> None:
    shared_execution_root = tmp_path / "execution-worktree"
    shared_execution_root.mkdir()
    fake = _FakeOrchestrator(tmp_path)
    fake._sm.lanes = {
        "lane-alpha": {
            "feature_id": "lane-alpha",
            "worktree": str(shared_execution_root),
        },
        "lane-beta": {
            "feature_id": "lane-beta",
            "worktree": str(shared_execution_root),
        },
    }
    monkeypatch.setattr(
        orchestrator_lane_flow,
        "_ensure_existing_worktree_branch",
        lambda worktree, branch: (branch, True),
    )
    monkeypatch.setattr(
        orchestrator_lane_flow,
        "_worktree_head_sha",
        lambda worktree: "base-head",
    )

    alpha = orchestrator_lane_flow.ensure_lane_worktree(
        fake,
        fake._sm.lanes["lane-alpha"],
    )
    beta = orchestrator_lane_flow.ensure_lane_worktree(
        fake,
        fake._sm.lanes["lane-beta"],
    )

    assert alpha["worktree"] != str(shared_execution_root)
    assert beta["worktree"] != str(shared_execution_root)
    assert alpha["worktree"] != beta["worktree"]
    assert alpha["branch"] == "lane-alpha"
    assert beta["branch"] == "lane-beta"
    assert fake.created_worktrees == [
        (tmp_path / "execution-worktree-lane-alpha", "lane-alpha"),
        (tmp_path / "execution-worktree-lane-beta", "lane-beta"),
    ]
