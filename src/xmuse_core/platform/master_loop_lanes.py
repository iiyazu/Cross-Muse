"""Lane projection helpers for the legacy Xmuse master loop."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path
from typing import Any

from xmuse_core.agents.consumer import TaskDescriptor
from xmuse_core.platform.projection.syncer import (
    LaneProjectionSyncer,
    ProjectionWriteSkipped,
)

logger = logging.getLogger("xmuse.master_loop.lanes")

ROOT = Path(__file__).resolve().parents[3]
WORKTREE_BASE = ROOT.parent
FULL_QUALITY_GATE_TASK_TYPE = "full_quality_gate"
FULL_QUALITY_GATE_PRIORITY = 100
FULL_QUALITY_GATE_REPAIR_PRIORITY = 110
TERMINAL_LANE_STATUSES = {"done", "failed", "merge_failed"}
MAX_LANE_RETRIES = 2

_TASK_DESCRIPTOR_FIELDS = {
    "feature_id",
    "task_type",
    "prompt",
    "worktree",
    "capabilities",
    "developed_by_runtime",
    "priority",
    "gate_profile",
    "gate_profiles",
    "base_head_sha",
}


def coerce_priority(value: Any) -> int:
    return value if isinstance(value, int) else 0


def root_head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def lane_metadata(lane: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in lane.items() if key not in _TASK_DESCRIPTOR_FIELDS}


def is_full_gate_family_lane(lane: dict[str, Any]) -> bool:
    return (
        lane.get("task_type") == FULL_QUALITY_GATE_TASK_TYPE
        or lane.get("source") == "full_quality_gate"
        or isinstance(lane.get("full_gate_feature_id"), str)
    )


def is_terminal_lane(lane: dict[str, Any]) -> bool:
    return lane.get("status", "pending") in TERMINAL_LANE_STATUSES


def should_retry_lane(lane: dict[str, Any]) -> bool:
    """Check if a failed lane is eligible for automatic retry."""
    if lane.get("status") != "failed":
        return False
    if lane.get("auto_retry") is not True:
        return False
    if is_full_gate_family_lane(lane):
        return False
    retry_count = lane.get("retry_count", 0)
    if retry_count >= MAX_LANE_RETRIES:
        return False
    if lane.get("no_retry"):
        return False
    return True


def is_active_full_gate_family_lane(lane: dict[str, Any]) -> bool:
    return is_full_gate_family_lane(lane) and not is_terminal_lane(lane)


def ensure_worktree(
    feature_id: str,
    branch: str | None = None,
    *,
    worktree_base: Path = WORKTREE_BASE,
    root_head_sha_fn: Any = root_head_sha,
    fast_forward_fn: Any | None = None,
) -> Path:
    """Create or reuse a git worktree for a feature lane."""

    wt_path = worktree_base / f"memoryOS-{feature_id}"
    if wt_path.exists():
        (fast_forward_fn or fast_forward_existing_worktree)(
            wt_path,
            root_head_sha_fn=root_head_sha_fn,
        )
        return wt_path

    branch_name = branch or f"feat/{feature_id}"
    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(wt_path), "HEAD"],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    if result.returncode != 0:
        subprocess.run(
            ["git", "worktree", "add", str(wt_path), branch_name],
            capture_output=True,
            text=True,
            cwd=ROOT,
        )

    if wt_path.exists():
        logger.info("Worktree ready: %s", wt_path)
    else:
        logger.warning("Failed to create worktree for %s: %s", feature_id, result.stderr)
    return wt_path


def fast_forward_existing_worktree(
    wt_path: Path,
    *,
    root_head_sha_fn: Any = root_head_sha,
) -> None:
    root_head = root_head_sha_fn()
    if not root_head:
        return

    status = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True,
        text=True,
        cwd=wt_path,
    )
    if status.returncode != 0:
        logger.warning("Failed to inspect worktree status: %s", wt_path)
        return
    if status.stdout.strip():
        logger.info("Attempting worktree fast-forward with local changes: %s", wt_path)

    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", "HEAD", root_head],
        capture_output=True,
        text=True,
        cwd=wt_path,
    )
    if ancestor.returncode != 0:
        logger.info("Skipping worktree fast-forward for divergent worktree: %s", wt_path)
        return

    merged = subprocess.run(
        ["git", "merge", "--ff-only", root_head],
        capture_output=True,
        text=True,
        cwd=wt_path,
    )
    if merged.returncode != 0:
        logger.warning(
            "Failed to fast-forward worktree %s to %s: %s",
            wt_path,
            root_head,
            merged.stderr.strip(),
        )


def load_lanes(
    path: Path,
    *,
    ensure_worktree_fn: Any = ensure_worktree,
    root_head_sha_fn: Any = root_head_sha,
    fast_forward_fn: Any = fast_forward_existing_worktree,
) -> list[TaskDescriptor]:
    """Load pending lanes whose dependencies are complete."""

    tasks: list[tuple[int, TaskDescriptor, bool]] = []
    syncer = LaneProjectionSyncer(path)

    def mutate(data: dict[str, Any]) -> None:
        all_lanes = data.get("lanes", [])
        done_ids = {
            lane["feature_id"]
            for lane in all_lanes
            if isinstance(lane, dict) and lane.get("status") == "done"
        }
        mutated = False

        for index, lane in enumerate(all_lanes):
            if not isinstance(lane, dict):
                continue
            if is_terminal_lane(lane):
                if lane.get("status") == "failed" and should_retry_lane(lane):
                    lane["status"] = "pending"
                    lane["retry_count"] = lane.get("retry_count", 0) + 1
                    mutated = True
                else:
                    continue

            deps = lane.get("depends_on", [])
            if deps and not all(dep in done_ids for dep in deps):
                logger.debug("Skipping %s (unmet deps: %s)", lane["feature_id"], deps)
                continue

            task_type = lane.get("task_type", "execute")
            worktree = lane.get("worktree")
            if task_type == FULL_QUALITY_GATE_TASK_TYPE:
                worktree = worktree or "."
            elif not worktree or worktree == ".":
                worktree = str(
                    ensure_worktree_fn(lane["feature_id"], branch=lane.get("branch"))
                )
                lane["worktree"] = worktree
                lane["base_head_sha"] = lane.get("base_head_sha") or root_head_sha_fn()
                mutated = True
            elif Path(worktree).exists():
                fast_forward_fn(Path(worktree))

            base_head_sha = lane.get("base_head_sha")
            tasks.append(
                (
                    index,
                    TaskDescriptor(
                        feature_id=lane["feature_id"],
                        task_type=task_type,
                        prompt=lane["prompt"],
                        worktree=worktree,
                        required_capabilities=lane.get("capabilities", ["code"]),
                        developed_by_runtime=lane.get("developed_by_runtime"),
                        priority=coerce_priority(lane.get("priority")),
                        gate_profile=(
                            lane.get("gate_profile")
                            if isinstance(lane.get("gate_profile"), str)
                            else None
                        ),
                        gate_profiles=[
                            item
                            for item in lane.get("gate_profiles", [])
                            if isinstance(item, str)
                        ],
                        lane_metadata=lane_metadata(lane),
                        base_head_sha=(
                            base_head_sha if isinstance(base_head_sha, str) else None
                        ),
                    ),
                    is_active_full_gate_family_lane(lane),
                )
            )

        if not mutated:
            raise ProjectionWriteSkipped()

    syncer.update(mutate)

    ordered = sorted(tasks, key=lambda item: (-item[1].priority, item[0]))
    selected: list[TaskDescriptor] = []
    full_gate_family_selected = False
    for _, task, is_full_gate_family in ordered:
        if is_full_gate_family:
            if full_gate_family_selected:
                continue
            full_gate_family_selected = True
        selected.append(task)
    return selected


def update_lane_status(lanes_path: Path, feature_id: str, status: str) -> None:
    """Write lane status back to feature_lanes.json through the projection syncer."""
    update_lane_fields(lanes_path, feature_id, {"status": status})
    logger.info("Lane %s -> %s", feature_id, status)


def update_lane_fields(
    lanes_path: Path,
    feature_id: str,
    fields: dict[str, Any],
) -> None:
    """Update a lane atomically through the shared projection syncer."""
    LaneProjectionSyncer(lanes_path).update_lane(
        feature_id,
        lambda lane: lane.update(fields),
    )


_coerce_priority = coerce_priority
_root_head_sha = root_head_sha
_lane_metadata = lane_metadata
_is_full_gate_family_lane = is_full_gate_family_lane
_is_terminal_lane = is_terminal_lane
_should_retry_lane = should_retry_lane
_is_active_full_gate_family_lane = is_active_full_gate_family_lane
_fast_forward_existing_worktree = fast_forward_existing_worktree
_update_lane_fields = update_lane_fields
