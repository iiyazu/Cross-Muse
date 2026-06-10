from __future__ import annotations

from xmuse_core.platform import master_loop_state


def test_state_module_marks_stale_running_lanes_and_initializes_missing_start() -> None:
    lanes = [
        {"feature_id": "missing-start", "status": "running"},
        {"feature_id": "stale", "status": "running", "started_at": 0.0},
        {"feature_id": "done", "status": "done"},
    ]

    changed = master_loop_state.mark_stale_running_lanes(
        lanes,
        now=5 * 3600,
        stale_hours=4,
    )

    assert changed is True
    assert lanes[0]["started_at"] == 5 * 3600
    assert lanes[1]["status"] == "failed"
    assert lanes[1]["gc_reason"] == "stuck_running_5.0h"
