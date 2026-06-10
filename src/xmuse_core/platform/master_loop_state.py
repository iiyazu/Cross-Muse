"""State mutation helpers for the legacy Xmuse master loop."""

from __future__ import annotations

from typing import Any


def mark_stale_running_lanes(
    lanes: list[dict[str, Any]],
    *,
    now: float,
    stale_hours: float,
) -> bool:
    changed = False
    for lane in lanes:
        if lane.get("status") != "running":
            continue
        started = lane.get("started_at")
        if not isinstance(started, (int, float)):
            lane["started_at"] = now
            changed = True
            continue
        hours_running = (now - started) / 3600
        if hours_running >= stale_hours:
            lane["status"] = "failed"
            lane["gc_reason"] = f"stuck_running_{hours_running:.1f}h"
            changed = True
    return changed
