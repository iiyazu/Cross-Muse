from __future__ import annotations

import json
import multiprocessing
import subprocess
import time
from pathlib import Path

import pytest

from xmuse_core.platform.execution import merger as execution_merger
from xmuse_core.platform.execution.merger import auto_merge


def _hold_merge_lock(
    repo: str,
    ready_file: str,
    hold_seconds: float,
    target_branch: str | None = None,
) -> None:
    with execution_merger._merge_lock(Path(repo), target_branch=target_branch):
        Path(ready_file).write_text("ready", encoding="utf-8")
        time.sleep(hold_seconds)


@pytest.mark.asyncio
async def test_auto_merge_rejects_missing_branch_and_worktree(tmp_path: Path) -> None:
    lane = {"feature_id": "lane-1", "status": "reviewed", "prompt": "fix"}

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=tmp_path)

    assert merged is False
    assert lane["merge_failure_reason"] == "merge_context_missing"
    assert "branch" in lane["merge_failure_detail"]
    assert "worktree" in lane["merge_failure_detail"]


@pytest.mark.asyncio
async def test_auto_merge_allows_explicit_noop_without_branch(tmp_path: Path) -> None:
    lane = {
        "feature_id": "lane-docs",
        "status": "reviewed",
        "prompt": "inspect only",
        "integration_mode": "noop",
    }

    merged = await auto_merge(lane_id="lane-docs", lane=lane, worktree=tmp_path)

    assert merged is True
    assert lane.get("merge_failure_reason") is None


@pytest.mark.asyncio
async def test_auto_merge_rejects_missing_branch_ref(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=tmp_path, check=True)
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "missing-branch",
        "worktree": str(tmp_path),
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=tmp_path)

    assert merged is False
    assert lane["merge_failure_reason"] == "merge_branch_missing"


@pytest.mark.asyncio
async def test_auto_merge_uses_current_target_branch_not_hardcoded_main(
    tmp_path: Path,
) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True)
    (tmp_path / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "branch", "-M", "feat/phase-2.5-3-retrieval-agent"],
        cwd=tmp_path,
        check=True,
    )
    subprocess.run(["git", "checkout", "-b", "lane-branch"], cwd=tmp_path, check=True)
    (tmp_path / "lane.txt").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "lane.txt"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "checkout", "feat/phase-2.5-3-retrieval-agent"],
        cwd=tmp_path,
        check=True,
    )
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(tmp_path),
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=tmp_path)

    assert merged is True
    assert subprocess.run(
        ["git", "branch", "--show-current"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip() == "feat/phase-2.5-3-retrieval-agent"
    assert (tmp_path / "lane.txt").read_text(encoding="utf-8") == "lane\n"


@pytest.mark.asyncio
async def test_auto_merge_allows_stale_base_head_when_git_merge_succeeds(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "lane.txt").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "lane.txt"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "checkout", "target"], cwd=repo, check=True)
    (repo / "README.md").write_text("target advanced\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "target advanced"], cwd=repo, check=True)
    current_target_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
        "target_branch": "target",
        "base_head_sha": base_head,
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is True
    assert lane.get("merge_failure_reason") is None
    assert lane["stale_against_current_target_head"] is True
    assert lane["current_target_head"] == current_target_head
    assert lane["stale_base_head_sha"] == base_head
    assert (repo / "README.md").read_text(encoding="utf-8") == "target advanced\n"
    assert (repo / "lane.txt").read_text(encoding="utf-8") == "lane\n"


@pytest.mark.asyncio
async def test_auto_merge_stale_base_head_still_rejects_real_conflict(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "shared.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "shared.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "shared.txt").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "shared.txt"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "checkout", "target"], cwd=repo, check=True)
    (repo / "shared.txt").write_text("target\n", encoding="utf-8")
    subprocess.run(["git", "add", "shared.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "target advanced"], cwd=repo, check=True)
    current_target_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
        "target_branch": "target",
        "base_head_sha": base_head,
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is False
    assert lane["merge_failure_reason"] == "merge_conflict_or_failed"
    assert lane["merge_failure_reworkable"] is True
    assert lane["stale_against_current_target_head"] is True
    assert lane["current_target_head"] == current_target_head
    assert lane["stale_base_head_sha"] == base_head
    assert "CONFLICT" in lane["merge_failure_detail"]


@pytest.mark.asyncio
async def test_auto_merge_defers_when_target_dirty_paths_overlap_lane_changes(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "projection.py").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/projection.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "src" / "projection.py").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/projection.py"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=lane_worktree, check=True)
    (repo / "src" / "projection.py").write_text("operator dirty\n", encoding="utf-8")
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
        "target_branch": "target",
        "base_head_sha": base_head,
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is False
    assert lane["merge_failure_reason"] == "target_worktree_dirty_conflict"
    assert lane["merge_failure_reworkable"] is False
    assert lane["target_dirty_conflicting_paths"] == ["src/projection.py"]
    assert "src/projection.py" in lane["merge_failure_detail"]
    assert lane["merge_retry_after_at"] > time.time()
    assert (repo / "src" / "projection.py").read_text(encoding="utf-8") == (
        "operator dirty\n"
    )


@pytest.mark.asyncio
async def test_auto_merge_allows_unrelated_dirty_live_projection_file(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "xmuse").mkdir()
    (repo / "src" / "projection.py").write_text("base\n", encoding="utf-8")
    (repo / "xmuse" / "feature_lanes.json").write_text('{"lanes": []}\n', encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "src" / "projection.py").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/projection.py"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=lane_worktree, check=True)
    (repo / "xmuse" / "feature_lanes.json").write_text(
        '{"lanes": [{"feature_id": "live"}]}\n',
        encoding="utf-8",
    )
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
        "target_branch": "target",
        "base_head_sha": base_head,
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is True
    assert (repo / "src" / "projection.py").read_text(encoding="utf-8") == "lane\n"
    assert (repo / "xmuse" / "feature_lanes.json").read_text(encoding="utf-8") == (
        '{"lanes": [{"feature_id": "live"}]}\n'
    )


@pytest.mark.asyncio
async def test_auto_merge_ignores_dirty_paths_changed_only_on_advanced_target(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "docs").mkdir()
    (repo / "src").mkdir()
    (repo / "docs" / "blueprint.md").write_text("base\n", encoding="utf-8")
    (repo / "src" / "worker.py").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "src" / "worker.py").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/worker.py"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "checkout", "target"], cwd=repo, check=True)
    (repo / "docs" / "blueprint.md").write_text("target advanced\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/blueprint.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "target advances docs"], cwd=repo, check=True)
    (repo / "docs" / "blueprint.md").write_text("live dirty docs\n", encoding="utf-8")
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
        "target_branch": "target",
        "base_head_sha": base_head,
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is True
    assert lane.get("merge_failure_reason") is None
    assert (repo / "src" / "worker.py").read_text(encoding="utf-8") == "lane\n"
    assert (repo / "docs" / "blueprint.md").read_text(encoding="utf-8") == (
        "live dirty docs\n"
    )


def test_merge_lock_serializes_cross_process_access(tmp_path: Path) -> None:
    ready_file = tmp_path / "ready.txt"
    process = multiprocessing.Process(
        target=_hold_merge_lock,
        args=(str(tmp_path), str(ready_file), 0.35),
    )
    process.start()
    try:
        deadline = time.monotonic() + 5.0
        while not ready_file.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("child process never acquired merge lock")
            time.sleep(0.01)

        started = time.monotonic()
        with execution_merger._merge_lock(tmp_path):
            elapsed = time.monotonic() - started

        assert elapsed >= 0.25
    finally:
        process.join(timeout=5.0)
        if process.exitcode is None:
            process.kill()
            process.join(timeout=5.0)
    assert process.exitcode == 0


def test_merge_lock_serializes_same_target_across_sibling_worktrees(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    sibling_worktree = tmp_path / "lane-worktree"
    ready_file = tmp_path / "ready.txt"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(sibling_worktree), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    process = multiprocessing.Process(
        target=_hold_merge_lock,
        args=(str(repo), str(ready_file), 0.35, "main"),
    )
    process.start()
    try:
        deadline = time.monotonic() + 5.0
        while not ready_file.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("child process never acquired merge lock")
            time.sleep(0.01)

        started = time.monotonic()
        with execution_merger._merge_lock(sibling_worktree, target_branch="main"):
            elapsed = time.monotonic() - started

        assert elapsed >= 0.25
    finally:
        process.join(timeout=5.0)
        if process.exitcode is None:
            process.kill()
            process.join(timeout=5.0)
    assert process.exitcode == 0


def test_merge_lock_does_not_contend_for_distinct_target_branches(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    sibling_worktree = tmp_path / "lane-worktree"
    ready_file = tmp_path / "ready.txt"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "branch", "-M", "main"], cwd=repo, check=True)
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(sibling_worktree), "main"],
        cwd=repo,
        check=True,
        capture_output=True,
    )

    process = multiprocessing.Process(
        target=_hold_merge_lock,
        args=(str(repo), str(ready_file), 0.35, "feat/a"),
    )
    process.start()
    try:
        deadline = time.monotonic() + 5.0
        while not ready_file.exists():
            if time.monotonic() >= deadline:
                raise AssertionError("child process never acquired merge lock")
            time.sleep(0.01)

        assert execution_merger._merge_lock_path(
            repo, target_branch="feat/a"
        ) != execution_merger._merge_lock_path(repo, target_branch="feat_a")

        started = time.monotonic()
        with execution_merger._merge_lock(sibling_worktree, target_branch="feat_a"):
            elapsed = time.monotonic() - started

        assert elapsed < 0.2
    finally:
        process.join(timeout=5.0)
        if process.exitcode is None:
            process.kill()
            process.join(timeout=5.0)
    assert process.exitcode == 0


def test_merge_lock_records_owner_heartbeat_and_reclaims_stale_metadata(
    tmp_path: Path,
) -> None:
    metadata_path = tmp_path / ".xmuse_merge.lock.json"
    metadata_path.write_text(
        json.dumps(
            {
                "owner_id": "lane-old",
                "owner_pid": 999999,
                "heartbeat_at": 10.0,
                "expires_at": 20.0,
            }
        ),
        encoding="utf-8",
    )

    with execution_merger._merge_lock(
        tmp_path,
        owner_id="lane-1",
        now=30.0,
        heartbeat_ttl_s=15.0,
    ):
        persisted = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert persisted["owner_id"] == "lane-1"
    assert persisted["heartbeat_at"] == 30.0
    assert persisted["expires_at"] == 45.0
    assert persisted["reclaimed_from_owner_id"] == "lane-old"
    assert isinstance(persisted["owner_pid"], int)
    assert not metadata_path.exists()


@pytest.mark.asyncio
async def test_auto_merge_commits_dirty_lane_worktree_before_merging(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(
        ["git", "branch", "-M", "feat/phase-2.5-3-retrieval-agent"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "feat/phase-2.5-3-retrieval-agent",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "lane.txt").write_text("lane\n", encoding="utf-8")
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is True
    assert (repo / "lane.txt").read_text(encoding="utf-8") == "lane\n"
    assert "merge_worktree_commit" in lane
    assert subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=lane_worktree,
        check=True,
        capture_output=True,
        text=True,
    ).stdout == ""


@pytest.mark.asyncio
async def test_auto_merge_records_conflict_stdout_and_unmerged_files(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "conflict.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "conflict.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "conflict.txt").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "conflict.txt"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=lane_worktree, check=True)
    (repo / "conflict.txt").write_text("target\n", encoding="utf-8")
    subprocess.run(["git", "add", "conflict.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "target"], cwd=repo, check=True)
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is False
    assert lane["merge_failure_reason"] == "merge_conflict_or_failed"
    assert lane["merge_failure_reworkable"] is True
    assert "CONFLICT" in lane["merge_failure_detail"]
    assert "conflict.txt" in lane["merge_failure_detail"]


@pytest.mark.asyncio
async def test_auto_merge_does_not_mark_non_conflict_merge_failure_reworkable(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "target.txt").write_text("target\n", encoding="utf-8")
    subprocess.run(["git", "add", "target.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "target"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "--orphan", "lane-branch"], cwd=repo, check=True)
    subprocess.run(["git", "rm", "-rf", "."], cwd=repo, check=True, capture_output=True)
    (repo / "lane.txt").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "lane.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=repo, check=True)
    subprocess.run(["git", "checkout", "target"], cwd=repo, check=True)
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(repo),
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is False
    assert lane["merge_failure_reason"] == "merge_failed"
    assert lane["merge_failure_reworkable"] is False
    assert "refusing to merge unrelated histories" in lane["merge_failure_detail"]


@pytest.mark.asyncio
async def test_auto_merge_exception_overwrites_stale_merge_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(tmp_path),
        "merge_failure_reason": "merge_conflict_or_failed",
        "merge_failure_reworkable": True,
        "merge_failure_detail": "old conflict",
    }

    def raise_runtime_error(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        raise RuntimeError("boom")

    monkeypatch.setattr(execution_merger.subprocess, "run", raise_runtime_error)

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=tmp_path)

    assert merged is False
    assert lane["merge_failure_reason"] == "auto_merge_error"
    assert lane["merge_failure_reworkable"] is False
    assert lane["merge_failure_detail"] == "boom"


@pytest.mark.asyncio
async def test_auto_merge_revalidates_target_head_under_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "repo"
    lane_worktree = tmp_path / "lane-worktree"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "-M", "target"], cwd=repo, check=True)
    base_head = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    subprocess.run(
        [
            "git",
            "worktree",
            "add",
            "-b",
            "lane-branch",
            str(lane_worktree),
            "target",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    (lane_worktree / "lane.txt").write_text("lane\n", encoding="utf-8")
    subprocess.run(["git", "add", "lane.txt"], cwd=lane_worktree, check=True)
    subprocess.run(["git", "commit", "-m", "lane"], cwd=lane_worktree, check=True)

    drifted_head = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    head_reads = iter((base_head, drifted_head))

    def fake_current_target_head(_repo: Path, _target_branch: str) -> str:
        return next(head_reads, drifted_head)

    monkeypatch.setattr(execution_merger, "_current_target_head", fake_current_target_head)
    lane = {
        "feature_id": "lane-1",
        "status": "reviewed",
        "prompt": "fix",
        "branch": "lane-branch",
        "worktree": str(lane_worktree),
        "target_branch": "target",
        "base_head_sha": base_head,
    }

    merged = await auto_merge(lane_id="lane-1", lane=lane, worktree=repo)

    assert merged is False
    assert lane["merge_failure_reason"] == "stale_target_head"
    assert lane["stale_against_current_target_head"] is True
    assert lane["current_target_head"] == drifted_head
    assert "changed while merge lock was held" in lane["merge_failure_detail"]
