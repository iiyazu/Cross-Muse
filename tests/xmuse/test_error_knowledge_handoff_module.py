from __future__ import annotations

from pathlib import Path

from xmuse_core.knowledge import handoff_artifacts


def test_handoff_module_builds_result_review_ack_and_slave_state(tmp_path: Path) -> None:
    result_md = handoff_artifacts.render_result_markdown(
        feature_id="xmuse-error-knowledge",
        status="usable",
        run_id="run-1",
        record_count=2,
        cluster_count=1,
        method_count=1,
        proposal_count=0,
        blockers=[],
    )
    review = handoff_artifacts.build_review_verdict(
        feature_id="xmuse-error-knowledge",
        status="usable",
        blockers=[],
    )
    ack = handoff_artifacts.build_ack(
        feature_id="xmuse-error-knowledge",
        status="usable",
        root=tmp_path,
        head_ref="branch@sha",
        run_id="run-1",
        blockers=[],
    )
    slave_state = handoff_artifacts.build_slave_state(
        feature_id="xmuse-error-knowledge",
        status="usable",
        root=tmp_path,
        now="2026-05-25T00:00:00Z",
        run_id="run-1",
    )

    assert "- Status: `usable`" in result_md
    assert "No MemoryOS runtime" in result_md
    assert review["verdict"] == "PASS"
    assert review["v3_default_preserved"] is True
    assert ack["ack_level"] == "usable"
    assert ack["verification_commands"][0]["command"] == (
        "uv run pytest tests/xmuse/test_error_knowledge.py -q"
    )
    assert slave_state["state"] == "ready_for_master_review"
    assert slave_state["artifacts"]["knowledge_run"] == (
        "xmuse/knowledge/runs/run-1.json"
    )


def test_handoff_module_marks_failed_status_consistently(tmp_path: Path) -> None:
    review = handoff_artifacts.build_review_verdict(
        feature_id="xmuse-error-knowledge",
        status="failed",
        blockers=["simulated partial object write failure"],
    )
    ack = handoff_artifacts.build_ack(
        feature_id="xmuse-error-knowledge",
        status="failed",
        root=tmp_path,
        head_ref="unknown",
        run_id="run-2",
        blockers=["simulated partial object write failure"],
    )
    slave_state = handoff_artifacts.build_slave_state(
        feature_id="xmuse-error-knowledge",
        status="failed",
        root=tmp_path,
        now="2026-05-25T00:00:00Z",
        run_id="run-2",
    )

    assert review["verdict"] == "FAIL"
    assert ack["ack_level"] == "failed"
    assert slave_state["state"] == "feature_blocked"
