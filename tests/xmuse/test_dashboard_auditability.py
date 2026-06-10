"""Tests for the dashboard_auditability self-evolution track.

Covers:
- SelfEvolutionAuditWriter.write() — read-model materialisation
- /api/self-evolution/audit — structured audit endpoint
- /api/self-evolution/conversations — system-authored conversations endpoint
- list_conversations() on SelfEvolutionStore
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "dashboard_api.py"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_dashboard_module():
    spec = importlib.util.spec_from_file_location("xmuse_dashboard_api", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


dashboard_api = _load_dashboard_module()
create_app = dashboard_api.create_app


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(base_dir=tmp_path))


def _seed_self_evolution_store(tmp_path: Path) -> None:
    """Seed minimal self-evolution store files for audit tests."""
    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        se_dir / "lineage.json",
        {
            "lineage": [
                {
                    "lineage_id": "evlineage_abc123",
                    "source_run_id": "res_source-graph-v1",
                    "source_resolution_id": "res_source",
                    "evidence_bundle_id": "evbundle_001",
                    "evolution_proposal_id": "evprop_001",
                    "review_decision_id": "evreview_001",
                    "guardrail_decision_id": "evguard_001",
                    "spawned_conversation_id": "conv_spawned_001",
                    "spawned_proposal_id": "prop_spawned_001",
                    "spawned_resolution_id": "res_spawned_001",
                    "spawned_graph_id": "res_spawned_001-graph-v1",
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["dashboard_auditability"],
                    "terminal_aggregation_ref": "runagg_001",
                    "created_at": "2026-05-28T07:00:00Z",
                }
            ]
        },
    )

    _write_json(
        se_dir / "proposals.json",
        {
            "proposals": [
                {
                    "proposal_id": "evprop_001",
                    "source_run_id": "res_source-graph-v1",
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["dashboard_auditability"],
                    "status": "landed",
                    "draft_version": 1,
                    "author_session_id": "god-session-architect",
                    "scope_summary": "Advance dashboard_auditability track",
                    "why_now": "source run merged",
                    "evidence_bundle_id": "evbundle_001",
                    "candidate_graph": {"lanes": []},
                    "review_status": "approve",
                    "spawned_conversation_id": "conv_spawned_001",
                    "spawned_resolution_id": "res_spawned_001",
                    "created_at": "2026-05-28T07:00:00Z",
                }
            ]
        },
    )

    _write_json(
        se_dir / "run_aggregations.json",
        {
            "aggregations": [
                {
                    "aggregation_id": "runagg_001",
                    "run_id": "res_source-graph-v1",
                    "resolution_id": "res_source",
                    "graph_id": "res_source-graph-v1",
                    "status": "merged",
                    "terminal": True,
                    "reason": "all graph lineage lanes merged",
                    "lane_counts": {"total": 1, "terminal": 1, "merged": 1},
                    "lane_statuses": [
                        {
                            "feature_id": "lane-001",
                            "raw_status": "merged",
                            "normalized_status": "merged",
                            "terminal": True,
                        }
                    ],
                    "open_lineages": [],
                    "blocked_objects": [],
                    "final_action_holds": [],
                    "created_at": "2026-05-28T06:59:00Z",
                }
            ]
        },
    )

    _write_json(
        se_dir / "conversations.json",
        {
            "conversations": [
                {
                    "conversation_id": "conv_spawned_001",
                    "proposal_id": "evprop_001",
                    "source_run_id": "res_source-graph-v1",
                    "created_by": "evolution-controller",
                    "created_at": "2026-05-28T07:00:00Z",
                }
            ]
        },
    )

    # Stub feature_lanes.json so the dashboard app can start
    _write_json(tmp_path / "feature_lanes.json", {"lanes": []})


def _seed_e2e_self_evolution_lineage(tmp_path: Path) -> dict[str, str]:
    """Seed a complete self-evolution chain used by dashboard E2E tests."""
    ids = {
        "lane_id": "dashboard-auditability-e2e",
        "source_run_id": "res_dashboard_auditability-graph-v1",
        "spawned_graph_id": "res_dashboard_auditability_next-graph-v1",
        "lineage_id": "evlineage_dashboard_auditability_e2e",
        "proposal_id": "evprop_dashboard_auditability_e2e",
        "aggregation_id": "runagg_dashboard_auditability_e2e",
        "conversation_id": "conv_dashboard_auditability_e2e",
        "evidence_bundle_id": "evbundle_6cbce74f29d64d05a5ec28928a268465",
    }
    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        se_dir / "lineage.json",
        {
            "lineage": [
                {
                    "lineage_id": ids["lineage_id"],
                    "source_run_id": ids["source_run_id"],
                    "source_resolution_id": "res_dashboard_auditability",
                    "evidence_bundle_id": ids["evidence_bundle_id"],
                    "evolution_proposal_id": ids["proposal_id"],
                    "review_decision_id": "evreview_dashboard_auditability_e2e",
                    "guardrail_decision_id": "evguard_dashboard_auditability_e2e",
                    "spawned_conversation_id": ids["conversation_id"],
                    "spawned_proposal_id": "prop_dashboard_auditability_e2e",
                    "spawned_resolution_id": "res_dashboard_auditability_next",
                    "spawned_graph_id": ids["spawned_graph_id"],
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["dashboard_auditability"],
                    "terminal_aggregation_ref": ids["aggregation_id"],
                    "created_at": "2026-05-28T10:00:00Z",
                }
            ]
        },
    )
    _write_json(
        se_dir / "proposals.json",
        {
            "proposals": [
                {
                    "proposal_id": ids["proposal_id"],
                    "source_run_id": ids["source_run_id"],
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["dashboard_auditability"],
                    "status": "landed",
                    "draft_version": 1,
                    "author_session_id": "god-session-dashboard-auditability",
                    "scope_summary": "Verify dashboard auditability end to end",
                    "why_now": "audit surface must correlate state and lineage",
                    "evidence_bundle_id": ids["evidence_bundle_id"],
                    "candidate_graph": {
                        "lanes": [
                            {
                                "feature_id": ids["lane_id"],
                                "feature_group": "dashboard_auditability/e2e",
                                "prompt": "Add dashboard auditability E2E coverage",
                            }
                        ]
                    },
                    "review_status": "approve",
                    "spawned_conversation_id": ids["conversation_id"],
                    "spawned_resolution_id": "res_dashboard_auditability_next",
                    "created_at": "2026-05-28T10:00:00Z",
                }
            ]
        },
    )
    _write_json(
        se_dir / "run_aggregations.json",
        {
            "aggregations": [
                {
                    "aggregation_id": ids["aggregation_id"],
                    "run_id": ids["source_run_id"],
                    "resolution_id": "res_dashboard_auditability",
                    "graph_id": ids["source_run_id"],
                    "status": "merged",
                    "terminal": True,
                    "reason": "all graph lineage lanes merged",
                    "lane_counts": {"total": 1, "terminal": 1, "merged": 1},
                    "lane_statuses": [
                        {
                            "feature_id": ids["lane_id"],
                            "raw_status": "merged",
                            "normalized_status": "merged",
                            "terminal": True,
                        }
                    ],
                    "open_lineages": [],
                    "blocked_objects": [],
                    "final_action_holds": [],
                    "created_at": "2026-05-28T09:59:00Z",
                }
            ]
        },
    )
    _write_json(
        se_dir / "conversations.json",
        {
            "conversations": [
                {
                    "conversation_id": ids["conversation_id"],
                    "proposal_id": ids["proposal_id"],
                    "source_run_id": ids["source_run_id"],
                    "created_by": "evolution-controller",
                    "created_at": "2026-05-28T10:00:00Z",
                }
            ]
        },
    )
    return ids


async def _record_lane_activity(tmp_path: Path, ids: dict[str, str]) -> None:
    from xmuse_core.platform.event_bus import EventBus
    from xmuse_core.platform.state_machine import LaneStateMachine

    _write_json(
        tmp_path / "feature_lanes.json",
        {
            "lanes": [
                {
                    "feature_id": ids["lane_id"],
                    "status": "pending",
                    "prompt": "Add dashboard auditability E2E coverage",
                    "graph_id": ids["source_run_id"],
                }
            ]
        },
    )
    state_machine = LaneStateMachine(
        tmp_path / "feature_lanes.json",
        history_path=tmp_path / "state_history.json",
    )
    bus = EventBus(audit_log_path=tmp_path / "audit_events.json")

    state_machine.transition(
        ids["lane_id"],
        "dispatched",
        metadata={
            "source_run_id": ids["source_run_id"],
            "evidence_bundle_id": ids["evidence_bundle_id"],
        },
    )
    await bus.publish(
        "lane_dispatched",
        {
            "lane_id": ids["lane_id"],
            "source_run_id": ids["source_run_id"],
            "evidence_bundle_id": ids["evidence_bundle_id"],
        },
    )
    state_machine.transition(
        ids["lane_id"],
        "executed",
        metadata={
            "source_run_id": ids["source_run_id"],
            "spawned_graph_id": ids["spawned_graph_id"],
            "evidence_bundle_id": ids["evidence_bundle_id"],
            "lineage_id": ids["lineage_id"],
        },
    )
    await bus.publish(
        "lane_executed",
        {
            "lane_id": ids["lane_id"],
            "source_run_id": ids["source_run_id"],
            "spawned_graph_id": ids["spawned_graph_id"],
            "evidence_bundle_id": ids["evidence_bundle_id"],
            "lineage_id": ids["lineage_id"],
        },
    )


def _records_by(records: list[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    return {str(record[key]): record for record in records if isinstance(record, dict)}


# ---------------------------------------------------------------------------
# End-to-end dashboard auditability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dashboard_auditability_e2e_correlates_state_events_and_lineage(
    tmp_path: Path,
) -> None:
    ids = _seed_e2e_self_evolution_lineage(tmp_path)
    await _record_lane_activity(tmp_path, ids)
    client = _client(tmp_path)

    state_response = client.get(
        "/api/dashboard/state-history",
        params={"lane_id": ids["lane_id"]},
    )
    event_response = client.get(
        "/api/dashboard/audit-events",
        params={"event_type": "lane_executed"},
    )
    lineage_response = client.get(
        "/api/dashboard/lineage",
        params={"run_id": ids["source_run_id"]},
    )
    audit_response = client.get("/api/self-evolution/audit")

    assert state_response.status_code == 200
    assert event_response.status_code == 200
    assert lineage_response.status_code == 200
    assert audit_response.status_code == 200

    snapshots = state_response.json()["snapshots"]
    snapshots_by_state = _records_by(snapshots, "state_key")
    assert list(snapshots_by_state) == ["dispatched", "executed"]
    executed_snapshot = snapshots_by_state["executed"]
    assert executed_snapshot["metadata"]["from_status"] == "dispatched"
    assert executed_snapshot["metadata"]["source_run_id"] == ids["source_run_id"]
    assert executed_snapshot["metadata"]["spawned_graph_id"] == ids["spawned_graph_id"]
    assert executed_snapshot["metadata"]["lineage_id"] == ids["lineage_id"]

    events = event_response.json()["events"]
    assert len(events) == 1
    executed_event = events[0]
    assert executed_event["metadata"]["lane_id"] == ids["lane_id"]
    assert executed_event["metadata"]["source_run_id"] == ids["source_run_id"]
    assert executed_event["metadata"]["spawned_graph_id"] == ids["spawned_graph_id"]
    assert executed_event["metadata"]["lineage_id"] == ids["lineage_id"]

    lineage = lineage_response.json()
    assert lineage["total_edges"] == 1
    assert lineage["edges"][0]["lineage_id"] == ids["lineage_id"]
    assert lineage["edges"][0]["source_node"] == ids["source_run_id"]
    assert lineage["edges"][0]["target_node"] == ids["spawned_graph_id"]
    assert lineage["edges"][0]["target_track_ids"] == ["dashboard_auditability"]

    audit_entries = audit_response.json()["entries"]
    assert len(audit_entries) == 1
    audit_entry = audit_entries[0]
    assert audit_entry["lineage_id"] == executed_event["metadata"]["lineage_id"]
    assert audit_entry["source_run_id"] == executed_snapshot["metadata"]["source_run_id"]
    assert audit_entry["spawned_graph_id"] == executed_snapshot["metadata"]["spawned_graph_id"]
    assert audit_entry["target_track_ids"] == ["dashboard_auditability"]
    assert audit_entry["proposal"]["candidate_lane_count"] == 1
    assert audit_entry["aggregation"]["status"] == "merged"
    assert audit_entry["conversation"]["created_by"] == "evolution-controller"


@pytest.mark.asyncio
async def test_dashboard_auditability_e2e_filters_noisy_records_without_breaking_audit(
    tmp_path: Path,
) -> None:
    ids = _seed_e2e_self_evolution_lineage(tmp_path)
    await _record_lane_activity(tmp_path, ids)
    client = _client(tmp_path)

    history = json.loads((tmp_path / "state_history.json").read_text(encoding="utf-8"))
    history["snapshots"].extend(
        [
            "not-a-snapshot",
            {
                "snapshot_id": "snap-unrelated",
                "lane_id": "unrelated-lane",
                "state_key": "executed",
                "timestamp": "2026-05-28T10:05:00Z",
                "metadata": {"source_run_id": "unrelated-run"},
            },
            {
                "snapshot_id": "snap-no-ts",
                "lane_id": ids["lane_id"],
                "state_key": "merged",
                "metadata": {"source_run_id": ids["source_run_id"]},
            },
        ]
    )
    _write_json(tmp_path / "state_history.json", history)

    events = json.loads((tmp_path / "audit_events.json").read_text(encoding="utf-8"))
    events["events"].extend(
        [
            "not-an-event",
            {
                "event_id": "evt-unrelated",
                "event_type": "lane_executed",
                "timestamp": "2026-05-28T10:05:00Z",
                "metadata": {"lane_id": "unrelated-lane", "source_run_id": "unrelated-run"},
            },
            {
                "event_id": "evt-no-ts",
                "event_type": "lane_executed",
                "metadata": {"lane_id": ids["lane_id"], "source_run_id": ids["source_run_id"]},
            },
        ]
    )
    _write_json(tmp_path / "audit_events.json", events)

    lineage = json.loads(
        (tmp_path / "self_evolution" / "lineage.json").read_text(encoding="utf-8")
    )
    lineage["lineage"].extend(
        [
            "not-a-lineage-record",
            {
                "lineage_id": "evlineage_orphan",
                "source_run_id": "orphan-run",
                "source_resolution_id": "res-orphan",
                "evidence_bundle_id": "evbundle_orphan",
                "evolution_proposal_id": "evprop_orphan",
                "review_decision_id": "evreview_orphan",
                "guardrail_decision_id": "evguard_orphan",
                "spawned_conversation_id": "conv_orphan",
                "spawned_proposal_id": "prop_orphan",
                "spawned_resolution_id": "res_orphan_next",
                "spawned_graph_id": "orphan-graph",
                "blueprint_set_id": "xmuse-self-evolution-v0",
                "target_track_ids": ["dashboard_auditability"],
                "created_at": "2026-05-28T10:06:00Z",
            },
        ]
    )
    _write_json(tmp_path / "self_evolution" / "lineage.json", lineage)

    state_response = client.get(
        "/api/dashboard/state-history",
        params={
            "lane_id": ids["lane_id"],
            "since": "2026-01-01T00:00:00Z",
        },
    )
    event_response = client.get(
        "/api/dashboard/audit-events",
        params={
            "event_type": "lane_executed",
            "since": "2026-01-01T00:00:00Z",
        },
    )
    lineage_response = client.get(
        "/api/dashboard/lineage",
        params={"run_id": ids["source_run_id"]},
    )
    audit_response = client.get("/api/self-evolution/audit")

    assert state_response.status_code == 200
    assert event_response.status_code == 200
    assert lineage_response.status_code == 200
    assert audit_response.status_code == 200

    assert {
        snapshot["state_key"] for snapshot in state_response.json()["snapshots"]
    } == {"dispatched", "executed"}
    assert all(
        snapshot["lane_id"] == ids["lane_id"]
        for snapshot in state_response.json()["snapshots"]
    )

    event_lane_ids = {
        event["metadata"]["lane_id"] for event in event_response.json()["events"]
    }
    assert ids["lane_id"] in event_lane_ids
    assert "unrelated-lane" in event_lane_ids
    assert all("timestamp" in event for event in event_response.json()["events"])

    lineage_body = lineage_response.json()
    assert lineage_body["total_edges"] == 1
    assert lineage_body["edges"][0]["lineage_id"] == ids["lineage_id"]

    audit_entries = audit_response.json()["entries"]
    assert len(audit_entries) == 2
    known_entry = next(
        entry for entry in audit_entries if entry["lineage_id"] == ids["lineage_id"]
    )
    orphan_entry = next(
        entry for entry in audit_entries if entry["lineage_id"] == "evlineage_orphan"
    )
    assert known_entry["aggregation"]["status"] == "merged"
    assert orphan_entry["proposal_status"] == "unknown"
    assert orphan_entry["spawned_graph_id"] == "orphan-graph"


# ---------------------------------------------------------------------------
# SelfEvolutionStore.list_conversations
# ---------------------------------------------------------------------------


def test_store_list_conversations_returns_saved_conversations(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.models import EvolutionConversation
    from xmuse_core.self_evolution.store import SelfEvolutionStore

    store = SelfEvolutionStore(tmp_path)
    conv = EvolutionConversation(
        conversation_id="conv_test_001",
        proposal_id="evprop_test_001",
        source_run_id="res_test-graph-v1",
        created_by="evolution-controller",
        created_at="2026-05-28T08:00:00Z",
    )
    store.save_conversation(conv)

    result = store.list_conversations()

    assert len(result) == 1
    assert result[0].conversation_id == "conv_test_001"
    assert result[0].created_by == "evolution-controller"


def test_store_list_conversations_returns_empty_when_no_file(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.store import SelfEvolutionStore

    store = SelfEvolutionStore(tmp_path)
    assert store.list_conversations() == []


# ---------------------------------------------------------------------------
# SelfEvolutionAuditWriter
# ---------------------------------------------------------------------------


def test_audit_writer_creates_read_model_files(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    _seed_self_evolution_store(tmp_path)
    writer = SelfEvolutionAuditWriter(
        store_root=tmp_path / "self_evolution",
        read_models_root=tmp_path / "read_models",
    )

    payload = writer.write()

    assert (tmp_path / "read_models" / "self_evolution_audit.json").exists()
    assert (tmp_path / "read_models" / "self_evolution_conversations.json").exists()
    assert payload["schema_version"] == "1"
    assert isinstance(payload["entries"], list)


def test_audit_writer_joins_lineage_with_proposal(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    _seed_self_evolution_store(tmp_path)
    writer = SelfEvolutionAuditWriter(
        store_root=tmp_path / "self_evolution",
        read_models_root=tmp_path / "read_models",
    )

    payload = writer.write()

    assert len(payload["entries"]) == 1
    entry = payload["entries"][0]
    assert entry["lineage_id"] == "evlineage_abc123"
    assert entry["proposal_id"] == "evprop_001"
    assert entry["proposal_status"] == "landed"
    assert entry["status_label"] == "landed"
    assert entry["scope_summary"] == "Advance dashboard_auditability track"
    assert entry["target_track_ids"] == ["dashboard_auditability"]


def test_audit_writer_joins_lineage_with_aggregation(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    _seed_self_evolution_store(tmp_path)
    writer = SelfEvolutionAuditWriter(
        store_root=tmp_path / "self_evolution",
        read_models_root=tmp_path / "read_models",
    )

    payload = writer.write()

    entry = payload["entries"][0]
    assert entry["run_terminal_status"] == "merged"
    assert entry["run_terminal_reason"] == "all graph lineage lanes merged"
    assert entry["lane_counts"] == {"total": 1, "terminal": 1, "merged": 1}
    assert entry["blocked_objects"] == []
    assert entry["final_action_holds"] == []


def test_audit_writer_joins_lineage_with_conversation(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    _seed_self_evolution_store(tmp_path)
    writer = SelfEvolutionAuditWriter(
        store_root=tmp_path / "self_evolution",
        read_models_root=tmp_path / "read_models",
    )

    payload = writer.write()

    entry = payload["entries"][0]
    assert entry["spawned_conversation_id"] == "conv_spawned_001"
    assert entry["conversation_created_by"] == "evolution-controller"


def test_audit_writer_entries_sorted_most_recent_first(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        se_dir / "lineage.json",
        {
            "lineage": [
                {
                    "lineage_id": "evlineage_older",
                    "source_run_id": "res_a-graph-v1",
                    "source_resolution_id": "res_a",
                    "evidence_bundle_id": "evbundle_a",
                    "evolution_proposal_id": "evprop_a",
                    "review_decision_id": "evreview_a",
                    "guardrail_decision_id": "evguard_a",
                    "spawned_conversation_id": "conv_a",
                    "spawned_proposal_id": "prop_a",
                    "spawned_resolution_id": "res_spawned_a",
                    "spawned_graph_id": "res_spawned_a-graph-v1",
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["graph_authority"],
                    "created_at": "2026-05-27T10:00:00Z",
                },
                {
                    "lineage_id": "evlineage_newer",
                    "source_run_id": "res_b-graph-v1",
                    "source_resolution_id": "res_b",
                    "evidence_bundle_id": "evbundle_b",
                    "evolution_proposal_id": "evprop_b",
                    "review_decision_id": "evreview_b",
                    "guardrail_decision_id": "evguard_b",
                    "spawned_conversation_id": "conv_b",
                    "spawned_proposal_id": "prop_b",
                    "spawned_resolution_id": "res_spawned_b",
                    "spawned_graph_id": "res_spawned_b-graph-v1",
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["review_plane"],
                    "created_at": "2026-05-28T09:00:00Z",
                },
            ]
        },
    )
    for name in ("proposals.json", "run_aggregations.json", "conversations.json"):
        _write_json(se_dir / name, {name.replace(".json", ""): []})

    writer = SelfEvolutionAuditWriter(
        store_root=se_dir,
        read_models_root=tmp_path / "read_models",
    )
    payload = writer.write()

    assert payload["entries"][0]["lineage_id"] == "evlineage_newer"
    assert payload["entries"][1]["lineage_id"] == "evlineage_older"


def test_audit_writer_tolerates_missing_store_files(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)
    # No files at all

    writer = SelfEvolutionAuditWriter(
        store_root=se_dir,
        read_models_root=tmp_path / "read_models",
    )
    payload = writer.write()

    assert payload["entries"] == []


def test_audit_writer_status_label_for_guardrail_blocked(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        se_dir / "lineage.json",
        {
            "lineage": [
                {
                    "lineage_id": "evlineage_blocked",
                    "source_run_id": "res_c-graph-v1",
                    "source_resolution_id": "res_c",
                    "evidence_bundle_id": "evbundle_c",
                    "evolution_proposal_id": "evprop_blocked",
                    "review_decision_id": "evreview_c",
                    "guardrail_decision_id": "evguard_c",
                    "spawned_conversation_id": "conv_c",
                    "spawned_proposal_id": "prop_c",
                    "spawned_resolution_id": "res_spawned_c",
                    "spawned_graph_id": "res_spawned_c-graph-v1",
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["reliability_hardening"],
                    "created_at": "2026-05-28T08:00:00Z",
                }
            ]
        },
    )
    _write_json(
        se_dir / "proposals.json",
        {
            "proposals": [
                {
                    "proposal_id": "evprop_blocked",
                    "source_run_id": "res_c-graph-v1",
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["reliability_hardening"],
                    "status": "guardrail_blocked",
                    "draft_version": 1,
                    "author_session_id": "god-session-architect",
                    "scope_summary": "Advance reliability_hardening",
                    "why_now": "source run merged",
                    "evidence_bundle_id": "evbundle_c",
                    "candidate_graph": {"lanes": []},
                    "review_status": "approve",
                    "created_at": "2026-05-28T08:00:00Z",
                }
            ]
        },
    )
    for name in ("run_aggregations.json", "conversations.json"):
        _write_json(se_dir / name, {name.replace(".json", ""): []})

    writer = SelfEvolutionAuditWriter(
        store_root=se_dir,
        read_models_root=tmp_path / "read_models",
    )
    payload = writer.write()

    entry = payload["entries"][0]
    assert entry["proposal_status"] == "guardrail_blocked"
    assert entry["status_label"] == "blocked by guardrail"


def test_audit_writer_conversations_file_includes_track_ids(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    _seed_self_evolution_store(tmp_path)
    writer = SelfEvolutionAuditWriter(
        store_root=tmp_path / "self_evolution",
        read_models_root=tmp_path / "read_models",
    )
    writer.write()

    data = json.loads(
        (tmp_path / "read_models" / "self_evolution_conversations.json").read_text(
            encoding="utf-8"
        )
    )
    assert data["schema_version"] == "1"
    assert len(data["conversations"]) == 1
    conv = data["conversations"][0]
    assert conv["conversation_id"] == "conv_spawned_001"
    assert conv["target_track_ids"] == ["dashboard_auditability"]
    assert conv["status_label"] == "landed"


# ---------------------------------------------------------------------------
# Dashboard API — /api/self-evolution/audit
# ---------------------------------------------------------------------------


def test_audit_endpoint_returns_structured_snapshot(tmp_path: Path) -> None:
    _seed_self_evolution_store(tmp_path)
    client = _client(tmp_path)

    response = client.get("/api/self-evolution/audit")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1"
    assert isinstance(body["entries"], list)
    assert len(body["entries"]) == 1
    entry = body["entries"][0]
    assert entry["lineage_id"] == "evlineage_abc123"
    assert entry["target_track_ids"] == ["dashboard_auditability"]
    assert entry["proposal_status"] == "landed"
    assert entry["run_terminal_status"] == "merged"


def test_audit_endpoint_tolerates_empty_store(tmp_path: Path) -> None:
    _write_json(tmp_path / "feature_lanes.json", {"lanes": []})
    (tmp_path / "self_evolution").mkdir(parents=True, exist_ok=True)
    client = _client(tmp_path)

    response = client.get("/api/self-evolution/audit")

    assert response.status_code == 200
    assert response.json()["entries"] == []


def test_audit_endpoint_materialises_read_model_file(tmp_path: Path) -> None:
    _seed_self_evolution_store(tmp_path)
    client = _client(tmp_path)

    client.get("/api/self-evolution/audit")

    audit_file = tmp_path / "read_models" / "self_evolution_audit.json"
    assert audit_file.exists()
    data = json.loads(audit_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"
    assert len(data["entries"]) == 1


# ---------------------------------------------------------------------------
# Dashboard API — /api/self-evolution/conversations
# ---------------------------------------------------------------------------


def test_conversations_endpoint_returns_system_authored_conversations(
    tmp_path: Path,
) -> None:
    _seed_self_evolution_store(tmp_path)
    client = _client(tmp_path)

    response = client.get("/api/self-evolution/conversations")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "1"
    assert isinstance(body["conversations"], list)
    assert len(body["conversations"]) == 1
    conv = body["conversations"][0]
    assert conv["conversation_id"] == "conv_spawned_001"
    assert conv["created_by"] == "evolution-controller"
    assert conv["target_track_ids"] == ["dashboard_auditability"]


def test_conversations_endpoint_tolerates_empty_store(tmp_path: Path) -> None:
    _write_json(tmp_path / "feature_lanes.json", {"lanes": []})
    (tmp_path / "self_evolution").mkdir(parents=True, exist_ok=True)
    client = _client(tmp_path)

    response = client.get("/api/self-evolution/conversations")

    assert response.status_code == 200
    body = response.json()
    assert body["conversations"] == []


def test_conversations_endpoint_materialises_read_model_file(tmp_path: Path) -> None:
    _seed_self_evolution_store(tmp_path)
    client = _client(tmp_path)

    client.get("/api/self-evolution/conversations")

    conv_file = tmp_path / "read_models" / "self_evolution_conversations.json"
    assert conv_file.exists()
    data = json.loads(conv_file.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1"


# ---------------------------------------------------------------------------
# Audit entry — blocked_objects and final_action_holds are surfaced
# ---------------------------------------------------------------------------


def test_audit_entry_surfaces_blocked_objects(tmp_path: Path) -> None:
    from xmuse_core.self_evolution.audit_writer import SelfEvolutionAuditWriter

    se_dir = tmp_path / "self_evolution"
    se_dir.mkdir(parents=True, exist_ok=True)

    _write_json(
        se_dir / "lineage.json",
        {
            "lineage": [
                {
                    "lineage_id": "evlineage_blocked_input",
                    "source_run_id": "res_blocked-graph-v1",
                    "source_resolution_id": "res_blocked",
                    "evidence_bundle_id": "evbundle_blocked",
                    "evolution_proposal_id": "evprop_blocked_input",
                    "review_decision_id": "evreview_blocked",
                    "guardrail_decision_id": "evguard_blocked",
                    "spawned_conversation_id": "conv_blocked",
                    "spawned_proposal_id": "prop_blocked",
                    "spawned_resolution_id": "res_spawned_blocked",
                    "spawned_graph_id": "res_spawned_blocked-graph-v1",
                    "blueprint_set_id": "xmuse-self-evolution-v0",
                    "target_track_ids": ["clarification_recovery"],
                    "created_at": "2026-05-28T09:30:00Z",
                }
            ]
        },
    )
    _write_json(
        se_dir / "run_aggregations.json",
        {
            "aggregations": [
                {
                    "aggregation_id": "runagg_blocked",
                    "run_id": "res_blocked-graph-v1",
                    "resolution_id": "res_blocked",
                    "graph_id": "res_blocked-graph-v1",
                    "status": "blocked_for_input",
                    "terminal": False,
                    "reason": "one or more lanes request clarification",
                    "lane_counts": {"total": 1, "terminal": 0},
                    "lane_statuses": [],
                    "open_lineages": [],
                    "blocked_objects": [
                        {
                            "lane_id": "lane-blocked",
                            "missing_input": "API key for external service",
                            "owner": "human",
                            "resume_path": "provide key and reproject",
                        }
                    ],
                    "final_action_holds": [],
                    "created_at": "2026-05-28T09:29:00Z",
                }
            ]
        },
    )
    for name in ("proposals.json", "conversations.json"):
        _write_json(se_dir / name, {name.replace(".json", ""): []})

    writer = SelfEvolutionAuditWriter(
        store_root=se_dir,
        read_models_root=tmp_path / "read_models",
    )
    payload = writer.write()

    entry = payload["entries"][0]
    assert entry["run_terminal_status"] == "blocked_for_input"
    assert len(entry["blocked_objects"]) == 1
    assert entry["blocked_objects"][0]["missing_input"] == "API key for external service"
