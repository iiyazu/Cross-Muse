from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.overnight_replay_bundle import (
    ReplayBundleSection,
    build_overnight_replay_bundle,
    write_overnight_replay_bundle,
)


def test_overnight_replay_bundle_links_sections_without_upgrading_proof_levels(
    tmp_path: Path,
) -> None:
    sections = [
        ReplayBundleSection(
            section_id="deliberation_transcript",
            status="ok",
            proof_level="real_provider_proof",
            source_authority="chat_store",
            source_refs=("memory://conversation/conv-1/message/m1",),
            artifacts=("artifact://transcript.json",),
            summary="natural transcript captured",
        ),
        ReplayBundleSection(
            section_id="frozen_blueprint",
            status="ok",
            proof_level="contract_proof",
            source_authority="blueprint_store",
            source_refs=("blueprint:bp-1",),
            artifacts=("artifact://blueprint.json",),
            summary="blueprint revision frozen",
        ),
        ReplayBundleSection(
            section_id="feature_lineage",
            status="ok",
            proof_level="contract_proof",
            source_authority="graph_set_store",
            source_refs=("feature:feature-1", "lane:lane-1"),
            artifacts=("artifact://lineage.json",),
            summary="feature graph lineage preserved",
        ),
        ReplayBundleSection(
            section_id="memoryos_trace",
            status="manual_gap",
            proof_level="manual_gap",
            source_authority="memoryos_rest",
            source_refs=(),
            artifacts=(),
            summary="MemoryOS Lite was not configured",
            next_action="Enable MemoryOS Lite and rerun live trace capture.",
        ),
        ReplayBundleSection(
            section_id="memory_governance",
            status="ok",
            proof_level="contract_proof",
            source_authority="memoryos_governance_policy",
            source_refs=("memory-governance:policy:S5",),
            artifacts=("artifact://memory-governance.json",),
            summary="MemoryOS promotion policy evaluated",
        ),
        ReplayBundleSection(
            section_id="github_truth",
            status="ok",
            proof_level="server_side_enforcement_proof",
            source_authority="github_server",
            source_refs=("github:pr:43",),
            artifacts=("artifact://github-truth.json",),
            summary="GitHub branch/check truth captured",
        ),
        ReplayBundleSection(
            section_id="supervisor",
            status="ok",
            proof_level="contract_proof",
            source_authority="overnight_operator_supervisor",
            source_refs=("goal:stage:S4",),
            artifacts=("artifact://overnight-supervisor.json",),
            summary="checkpoint and heartbeat journal captured",
        ),
        ReplayBundleSection(
            section_id="release_readiness",
            status="blocked",
            proof_level="contract_proof",
            source_authority="release_readiness_capture",
            source_refs=("release-readiness:current",),
            artifacts=("artifact://release-readiness.json",),
            summary="release readiness has live MemoryOS blocker",
            blocked_reason="live_memoryos is required but not configured",
        ),
    ]

    bundle = build_overnight_replay_bundle(
        run_id="overnight-1",
        sections=sections,
    )
    output = tmp_path / "overnight-replay-bundle.json"
    write_overnight_replay_bundle(bundle=bundle, output_path=output)

    assert bundle["schema_version"] == "xmuse.overnight_replay_bundle.v1"
    assert bundle["run_id"] == "overnight-1"
    assert bundle["authority"] == "replay_index_only"
    assert bundle["decision"] == "blocked"
    assert bundle["proof_level_summary"] == {
        "contract_proof": 5,
        "manual_gap": 1,
        "real_provider_proof": 1,
        "server_side_enforcement_proof": 1,
    }
    assert [section["section_id"] for section in bundle["sections"]] == [
        "deliberation_transcript",
        "frozen_blueprint",
        "feature_lineage",
        "memoryos_trace",
        "memory_governance",
        "github_truth",
        "supervisor",
        "release_readiness",
    ]
    assert bundle["blockers"] == [
        {
            "section_id": "memoryos_trace",
            "reason": "memoryos_trace status is manual_gap: MemoryOS Lite was not configured",
            "owner": "operator",
            "next_action": "Enable MemoryOS Lite and rerun live trace capture.",
        },
        {
            "section_id": "release_readiness",
            "reason": "live_memoryos is required but not configured",
            "owner": "operator",
            "next_action": None,
        },
    ]
    assert json.loads(output.read_text(encoding="utf-8")) == bundle


def test_overnight_replay_bundle_reports_missing_required_sections() -> None:
    bundle = build_overnight_replay_bundle(
        run_id="overnight-missing",
        sections=[
            ReplayBundleSection(
                section_id="supervisor",
                status="ok",
                proof_level="contract_proof",
                source_authority="overnight_operator_supervisor",
                source_refs=("goal:stage:S4",),
                artifacts=("artifact://overnight-supervisor.json",),
                summary="supervisor captured",
            )
        ],
    )

    missing_ids = [
        blocker["section_id"]
        for blocker in bundle["blockers"]
        if blocker["reason"] == "required replay section is missing"
    ]

    assert bundle["decision"] == "blocked"
    assert missing_ids == [
        "deliberation_transcript",
        "frozen_blueprint",
        "feature_lineage",
        "memoryos_trace",
        "memory_governance",
        "github_truth",
        "release_readiness",
    ]


def test_overnight_replay_bundle_excludes_tombstoned_source_refs_from_active_refs() -> None:
    bundle = build_overnight_replay_bundle(
        run_id="overnight-tombstone",
        tombstoned_source_refs=("message:deleted",),
        sections=[
            ReplayBundleSection(
                section_id="memoryos_trace",
                status="ok",
                proof_level="live_service_proof",
                source_authority="memoryos_rest",
                source_refs=("message:deleted", "message:kept"),
                artifacts=("artifact://memoryos-trace.json",),
                summary="MemoryOS trace captured",
            )
        ],
    )

    memoryos = bundle["sections"][0]

    assert memoryos["source_refs"] == ["message:deleted", "message:kept"]
    assert memoryos["active_source_refs"] == ["message:kept"]
    assert {
        "section_id": "memoryos_trace",
        "reason": "section contains tombstoned source refs: message:deleted",
        "owner": "operator",
        "next_action": "Remove tombstoned refs or regenerate the MemoryOS trace.",
    } in bundle["blockers"]
