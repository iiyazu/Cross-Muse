from __future__ import annotations

import json
from pathlib import Path

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts")


def _load_json(relative: str) -> dict:
    path = CONTRACT_ROOT / relative
    return json.loads(path.read_text(encoding="utf-8"))


def test_parallel_event_fixtures_freeze_delivery_contract() -> None:
    expected_events = {
        "events/blueprint.approved.v1.json": {
            "event_type": "blueprint.approved",
            "producer_session": "S1",
            "consumer_sessions": ["S2", "S3"],
        },
        "events/feature_plan.ready.v1.json": {
            "event_type": "feature_plan.ready",
            "producer_session": "S3",
            "consumer_sessions": ["S4", "S7", "S8"],
        },
        "events/graph_set.ready.v1.json": {
            "event_type": "graph_set.ready",
            "producer_session": "S4",
            "consumer_sessions": ["S2", "S5", "S7"],
        },
        "events/planning.failed.v1.json": {
            "event_type": "planning.failed",
            "producer_session": "S3",
            "consumer_sessions": ["S1", "S2", "S7"],
        },
        "events/graph_set.failed.v1.json": {
            "event_type": "graph_set.failed",
            "producer_session": "S4",
            "consumer_sessions": ["S1", "S2", "S7"],
        },
        "events/lane.updated.v1.json": {
            "event_type": "lane.updated",
            "producer_session": "S5",
            "consumer_sessions": ["S1", "S7"],
        },
        "events/review.verdict.v1.json": {
            "event_type": "review.verdict",
            "producer_session": "S5",
            "consumer_sessions": ["S2", "S5", "S7"],
        },
        "events/takeover.requested.v1.json": {
            "event_type": "takeover.requested",
            "producer_session": "S5",
            "consumer_sessions": ["S1", "S2", "S7"],
        },
        "events/takeover.resolved.v1.json": {
            "event_type": "takeover.resolved",
            "producer_session": "S2",
            "consumer_sessions": ["S1", "S5", "S7"],
        },
        "events/blueprint.gap_found.v1.json": {
            "event_type": "blueprint.gap_found",
            "producer_session": "S2",
            "consumer_sessions": ["S1", "S3", "S7"],
        },
    }

    seen_idempotency_keys: set[str] = set()
    for relative, expected in expected_events.items():
        event = _load_json(relative)
        assert event["schema_version"] == "xmuse.event.v1"
        assert event["event_type"] == expected["event_type"]
        assert event["event_id"].startswith(f"evt_{event['event_type'].replace('.', '_')}_")
        assert event["producer_session"] == expected["producer_session"]
        assert event["consumer_sessions"] == expected["consumer_sessions"]
        assert event["delivery"] == "at_least_once"
        assert event["idempotency_key"]
        assert event["idempotency_key"] not in seen_idempotency_keys
        seen_idempotency_keys.add(event["idempotency_key"])
        assert event["aggregate"]["id"]
        assert event["aggregate"]["version"] >= 1
        assert event["created_at"].endswith("Z")
        assert event["payload"]["artifact_refs"]
        assert event["payload"]["source_refs"]


def test_parallel_artifact_fixtures_freeze_lineage_contract() -> None:
    expected_artifacts = {
        "artifacts/blueprint.v1.json": "blueprint",
        "artifacts/feature_evidence_bundle.v1.json": "feature_evidence_bundle",
        "artifacts/feature_graph_blocked_review_plan.v1.json": "feature_graph_blocked_review_plan",
        "artifacts/feature_graph_patch_forward_gate_result.v1.json": "feature_graph_patch_forward_gate_result",  # noqa: E501
        "artifacts/feature_graph_patch_forward_merge_guard_decision.v1.json": "feature_graph_patch_forward_merge_guard_decision",  # noqa: E501
        "artifacts/feature_graph_patch_forward_merge_guard_handoff.v1.json": "feature_graph_patch_forward_merge_guard_handoff",  # noqa: E501
        "artifacts/feature_graph_patch_forward_plan.v1.json": "feature_graph_patch_forward_plan",
        "artifacts/feature_graph_provider_binding_degradation_event.v1.json": "feature_graph_status_event",  # noqa: E501
        "artifacts/feature_graph_review_status_transition_plan.v1.json": "feature_graph_review_status_transition_plan",  # noqa: E501
        "artifacts/feature_graph_rework_packet.v1.json": "rework_packet",
        "artifacts/feature_graph_status.v1.json": "feature_graph_status",
        "artifacts/feature_graph_status_event.v1.json": "feature_graph_status_event",
        "artifacts/feature_graph_status_running_claim.v1.json": "feature_graph_status",
        "artifacts/feature_graph_takeover_decision.v1.json": "feature_graph_takeover_decision",
        "artifacts/feature_graph_takeover_followup_review_application.v1.json": "feature_graph_takeover_followup_review_application",  # noqa: E501
        "artifacts/feature_graph_takeover_handoff.v1.json": "feature_graph_takeover_handoff",
        "artifacts/feature_graph_takeover_outcome.v1.json": "feature_graph_takeover_outcome",
        "artifacts/feature_graph_takeover_plan.v1.json": "feature_graph_takeover_plan",
        "artifacts/feature_graph_takeover_review_handoff.v1.json": "feature_graph_takeover_review_handoff",  # noqa: E501
        "artifacts/feature_graph_worker_claim_plan.v1.json": "feature_graph_worker_claim_plan",
        "artifacts/feature_graph_worker_evidence_submission_plan.v1.json": "feature_graph_worker_evidence_submission_plan",  # noqa: E501
        "artifacts/feature_plan.v1.json": "feature_plan",
        "artifacts/feature_review_verdict.v1.json": "feature_review_verdict",
        "artifacts/graph_set.v1.json": "graph_set",
        "artifacts/lane_graph.v1.json": "lane_graph",
        "artifacts/provider_session_binding.v1.json": "provider_session_binding",
        "artifacts/rework_packet.v1.json": "rework_packet",
    }

    for relative, artifact_type in expected_artifacts.items():
        artifact = _load_json(relative)
        assert artifact["schema_version"] == "xmuse.artifact.v1"
        assert artifact["artifact_type"] == artifact_type
        assert artifact["artifact_ref"].startswith(f"{artifact_type}:")
        assert artifact["artifact_id"]
        assert artifact["version"] >= 1
        assert artifact["created_at"].endswith("Z")
        assert artifact["source_refs"]
        assert artifact["lineage"]["source_event_refs"]
        assert artifact["ownership"]["producer_session"].startswith("S")
        assert artifact["ownership"]["consumer_sessions"]


def test_parallel_read_envelope_and_card_fixtures_are_renderable_contracts() -> None:
    envelope = _load_json("read_envelopes/tui_worklist.v1.json")
    assert envelope["schema_version"] == "xmuse.read_envelope.v1"
    assert envelope["envelope_type"] == "tui_worklist"
    assert envelope["conversation_id"]
    assert envelope["generated_at"].endswith("Z")
    assert {card["intent_id"] for card in envelope["cards"]} == {
        "intent_feature_plan_ready_demo",
        "intent_run_progress_demo",
        "intent_lane_blocked_demo",
        "intent_review_verdict_demo",
        "intent_takeover_requested_demo",
    }
    assert envelope["worklist"]
    assert envelope["run_health"]["status"] in {"healthy", "degraded", "blocked"}

    for relative in (
        "cards/feature_plan_ready.v1.json",
        "cards/run_progress.v1.json",
        "cards/lane_blocked.v1.json",
        "cards/review_verdict.v1.json",
        "cards/takeover_requested.v1.json",
    ):
        card = _load_json(relative)
        assert card["schema_version"] == "xmuse.card.v1"
        assert card["intent_id"].startswith("intent_")
        assert card["card_type"]
        assert card["title"]
        assert card["summary"]
        assert card["artifact_refs"]
        assert card["drilldown_refs"]


def test_parallel_session_io_manifest_covers_all_module_sessions() -> None:
    manifest = _load_json("interfaces/xmuse_parallel_sessions.v1.json")
    expected_sessions = {f"S{index}" for index in range(1, 9)}

    assert manifest["schema_version"] == "xmuse.session_interfaces.v1"
    sessions = {session["session"]: session for session in manifest["sessions"]}
    assert set(sessions) == expected_sessions
    for session in sessions.values():
        assert session["ready_flag"].endswith(".ready.json")
        assert session["owner"]
        assert session["allowed_files"]
        assert all("feature_lanes.json" not in path for path in session["allowed_files"])
        assert "feature_lanes.json" in session["must_not_write"]
        assert session["inputs"]
        assert session["outputs"]
