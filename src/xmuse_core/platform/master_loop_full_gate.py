"""Full-quality-gate helpers for the legacy Xmuse master loop."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from xmuse_core.platform.master_loop_lanes import (
    FULL_QUALITY_GATE_PRIORITY,
    FULL_QUALITY_GATE_REPAIR_PRIORITY,
    FULL_QUALITY_GATE_TASK_TYPE,
    coerce_priority,
    is_active_full_gate_family_lane,
)


def has_active_full_quality_gate(lanes: list[dict[str, Any]]) -> bool:
    return any(is_active_full_gate_family_lane(lane) for lane in lanes)


def compact_full_gate_family_queue(
    lanes: list[dict[str, Any]],
    *,
    preferred_feature_id: str | None = None,
) -> bool:
    active_family_lanes = [
        lane
        for lane in lanes
        if isinstance(lane, dict) and is_active_full_gate_family_lane(lane)
    ]
    if len(active_family_lanes) <= 1:
        return False

    running = [
        lane
        for lane in active_family_lanes
        if lane.get("status", "pending") == "running"
    ]
    keep = next(
        (
            lane
            for lane in active_family_lanes
            if lane.get("feature_id") == preferred_feature_id
        ),
        None,
    )
    if keep is None and running:
        keep = running[0]
    if keep is None:
        keep = max(
            active_family_lanes,
            key=lambda lane: coerce_priority(lane.get("priority")),
        )

    changed = False
    for lane in active_family_lanes:
        if lane is keep:
            continue
        if lane.get("status", "pending") != "pending":
            continue
        lane["status"] = "failed"
        lane["discarded_reason"] = "superseded_full_quality_gate_family"
        lane["discarded_by"] = keep.get("feature_id")
        changed = True
    return changed


def next_full_gate_batch(lanes: list[dict[str, Any]], *, interval: int) -> list[str]:
    covered: set[str] = set()
    for lane in lanes:
        if lane.get("task_type") != FULL_QUALITY_GATE_TASK_TYPE:
            continue
        batch = lane.get("batch_lane_ids", [])
        if isinstance(batch, list):
            covered.update(item for item in batch if isinstance(item, str))

    batch_lane_ids: list[str] = []
    for lane in lanes:
        feature_id = lane.get("feature_id")
        if not isinstance(feature_id, str):
            continue
        if lane.get("status") != "done":
            continue
        if lane.get("task_type") == FULL_QUALITY_GATE_TASK_TYPE:
            continue
        if feature_id in covered:
            continue
        batch_lane_ids.append(feature_id)
        if len(batch_lane_ids) >= interval:
            break
    return batch_lane_ids


def full_gate_feature_id(batch_lane_ids: list[str], head_sha: str) -> str:
    digest = hashlib.sha1(
        "\n".join([head_sha, *batch_lane_ids]).encode("utf-8")
    ).hexdigest()[:10]
    short_head = head_sha[:8] if head_sha else "unknown"
    return f"full-quality-gate-{short_head}-{digest}"


def build_full_gate_lane(
    *,
    feature_id: str,
    batch_lane_ids: list[str],
    head_sha: str,
) -> dict[str, Any]:
    return {
        "feature_id": feature_id,
        "task_type": FULL_QUALITY_GATE_TASK_TYPE,
        "status": "pending",
        "worktree": ".",
        "prompt": "Run the strict-product xmuse quality gate.",
        "gate_profiles": ["strict-product"],
        "capabilities": ["test"],
        "depends_on": [],
        "source": "full_quality_gate",
        "priority": FULL_QUALITY_GATE_PRIORITY,
        "batch_lane_ids": batch_lane_ids,
        "head_sha": head_sha,
        "base_head_sha": head_sha,
    }


def build_full_gate_repair_lane(
    *,
    repair_id: str,
    gate_feature_id: str,
    artifact_path: Path,
    artifact_rel: str,
    errors: list[str],
    batch_lane_ids: list[Any],
    head_sha: str,
) -> dict[str, Any]:
    output = "\n\n".join(errors)[-6000:]
    return {
        "feature_id": repair_id,
        "task_type": "execute",
        "status": "pending",
        "branch": f"feat/{repair_id}",
        "prompt": (
            "Fix the failing full xmuse quality gate.\n\n"
            "Profile: strict-product\n"
            f"Artifact: {artifact_rel}\n"
            f"Head SHA: {head_sha}\n"
            f"Batch lane ids: {batch_lane_ids}\n\n"
            "Failure output:\n"
            f"{output}\n\n"
            "Make the minimal fix, then verify with the strict-product gate profile."
        ),
        "capabilities": ["code", "test"],
        "gate_profiles": ["strict-product"],
        "depends_on": [],
        "source": "full_quality_gate",
        "priority": FULL_QUALITY_GATE_REPAIR_PRIORITY,
        "full_gate_feature_id": gate_feature_id,
        "full_gate_artifact": artifact_rel,
        "head_sha": head_sha,
        "base_head_sha": head_sha,
        "batch_lane_ids": batch_lane_ids,
    }
