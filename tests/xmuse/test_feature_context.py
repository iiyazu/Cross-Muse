import json
from pathlib import Path

from xmuse_core.platform.feature_context import build_feature_context_bundle
from xmuse_core.platform.memory_refs import MemoryCategory, MemoryRef, MemoryScope


def test_feature_context_bundle_separates_summary_from_primary_refs(tmp_path: Path) -> None:
    blueprint = tmp_path / "docs" / "blueprint.md"
    blueprint.parent.mkdir(parents=True)
    blueprint.write_text("Blueprint acceptance: chat stays frontdoor first.", encoding="utf-8")
    gate_report = tmp_path / "logs" / "gates" / "lane-a" / "report.json"
    gate_report.parent.mkdir(parents=True)
    gate_report.write_text(json.dumps({"passed": True, "commands": ["pytest"]}), encoding="utf-8")
    lanes = [
        {
            "feature_id": "lane-a",
            "status": "gated",
            "graph_id": "graph-frontdoor",
            "conversation_id": "conv-1",
            "feature_plan_id": "plan-1",
            "feature_plan_feature_id": "chat-workspace-frontdoor",
            "feature_title": "Chat Workspace Frontdoor",
            "feature_goal": "Keep dashboard details behind chat cards.",
            "acceptance_criteria": ["Cards summarize work without dashboard noise."],
            "blueprint_refs": ["docs/blueprint.md"],
            "review_summary": "Previous review asked for compact cards.",
            "retry_count": 1,
            "prompt": "Implement compact cards.",
        },
        {
            "feature_id": "lane-b",
            "status": "pending",
            "graph_id": "graph-frontdoor",
            "conversation_id": "conv-1",
            "feature_plan_feature_id": "chat-workspace-frontdoor",
            "depends_on": ["lane-a"],
        },
        {
            "feature_id": "other-lane",
            "status": "pending",
            "graph_id": "other-graph",
            "feature_plan_feature_id": "other-feature",
        },
    ]

    bundle = build_feature_context_bundle(lanes[0], all_lanes=lanes, xmuse_root=tmp_path)

    assert bundle.feature_id == "chat-workspace-frontdoor"
    assert "Chat Workspace Frontdoor" in bundle.compact_summary
    assert "Title source: lane_metadata.feature_title" in bundle.compact_summary
    assert "Goal source: lane_metadata.feature_goal" in bundle.compact_summary
    assert "Cards summarize work" in bundle.compact_summary
    assert "lane-a: gated" in bundle.compact_summary
    assert "lane-b: pending" in bundle.compact_summary
    assert "other-lane" not in bundle.compact_summary
    assert "Previous review asked for compact cards." in bundle.compact_summary
    assert {
        "kind": "blueprint",
        "ref": "docs/blueprint.md",
        "exists": True,
    } in bundle.primary_refs
    assert {
        "kind": "gate_report",
        "ref": "logs/gates/lane-a/report.json",
        "exists": True,
    } in bundle.primary_refs


def test_feature_context_bundle_is_conversation_scoped(tmp_path: Path) -> None:
    lanes = [
        {
            "feature_id": "lane-a",
            "status": "gated",
            "graph_id": "graph-a",
            "conversation_id": "conv-a",
            "feature_plan_feature_id": "shared-feature",
        },
        {
            "feature_id": "lane-b",
            "status": "pending",
            "graph_id": "graph-a",
            "conversation_id": "conv-a",
            "feature_plan_feature_id": "shared-feature",
        },
        {
            "feature_id": "lane-other-conv",
            "status": "failed",
            "graph_id": "graph-b",
            "conversation_id": "conv-b",
            "feature_plan_feature_id": "shared-feature",
        },
    ]

    bundle = build_feature_context_bundle(lanes[0], all_lanes=lanes, xmuse_root=tmp_path)

    assert "lane-a: gated" in bundle.compact_summary
    assert "lane-b: pending" in bundle.compact_summary
    assert "lane-other-conv" not in bundle.compact_summary


def test_feature_context_bundle_keeps_memory_refs_separate_from_primary_refs(
    tmp_path: Path,
) -> None:
    ref = MemoryRef(
        scope=MemoryScope.FEATURE,
        category=MemoryCategory.FEATURE_HISTORY,
        session_id="ses_feature_1",
        title="Feature Alpha History",
        conversation_id="conv-1",
        feature_id="feature-alpha",
        primary_evidence_refs=["lane.review_summary"],
    )
    lane = {
        "feature_id": "lane-a",
        "status": "gated",
        "graph_id": "graph-a",
        "conversation_id": "conv-1",
        "feature_plan_feature_id": "feature-alpha",
        "memory_refs": [ref.model_dump(mode="json")],
        "blueprint_refs": ["docs/blueprint.md"],
    }

    bundle = build_feature_context_bundle(lane, all_lanes=[lane], xmuse_root=tmp_path)

    assert bundle.memory_refs == [ref.model_dump(mode="json")]
    assert {
        "kind": "blueprint",
        "ref": "docs/blueprint.md",
        "exists": False,
    } in bundle.primary_refs
    assert "## Memory References" in bundle.as_prompt_context()
    assert "memoryos://feature/conv-1/feature-alpha/ses_feature_1" in bundle.as_prompt_context()
    assert "primary refs: lane.review_summary" in bundle.as_prompt_context()
