from __future__ import annotations

from pathlib import Path

from xmuse_core.platform import master_loop_full_gate


def test_full_gate_module_compacts_active_family_and_selects_next_batch() -> None:
    lanes = [
        {"feature_id": "done-1", "status": "done", "task_type": "execute"},
        {"feature_id": "done-2", "status": "done", "task_type": "execute"},
        {
            "feature_id": "old-gate",
            "status": "pending",
            "task_type": "full_quality_gate",
            "priority": 100,
        },
        {
            "feature_id": "repair",
            "status": "pending",
            "source": "full_quality_gate",
            "full_gate_feature_id": "failed-gate",
            "priority": 110,
        },
    ]

    changed = master_loop_full_gate.compact_full_gate_family_queue(
        lanes,
        preferred_feature_id="repair",
    )

    assert changed is True
    assert lanes[2]["status"] == "failed"
    assert lanes[2]["discarded_by"] == "repair"
    assert master_loop_full_gate.has_active_full_quality_gate(lanes) is True
    assert master_loop_full_gate.next_full_gate_batch(lanes, interval=2) == [
        "done-1",
        "done-2",
    ]


def test_full_gate_module_builds_gate_and_repair_lane_payloads() -> None:
    gate = master_loop_full_gate.build_full_gate_lane(
        feature_id="full-quality-gate-head-digest",
        batch_lane_ids=["lane-a", "lane-b"],
        head_sha="head-sha",
    )
    repair = master_loop_full_gate.build_full_gate_repair_lane(
        repair_id="full-quality-gate-repair-gate-1",
        gate_feature_id="gate-1",
        artifact_path=Path("xmuse/logs/full_quality_gate/gate-1.log"),
        artifact_rel="xmuse/logs/full_quality_gate/gate-1.log",
        errors=["pytest failed"],
        batch_lane_ids=["lane-a"],
        head_sha="head-sha",
    )

    assert gate["task_type"] == "full_quality_gate"
    assert gate["worktree"] == "."
    assert gate["gate_profiles"] == ["strict-product"]
    assert gate["priority"] == 100
    assert repair["source"] == "full_quality_gate"
    assert repair["priority"] == 110
    assert "Profile: strict-product" in repair["prompt"]
    assert "pytest failed" in repair["prompt"]
