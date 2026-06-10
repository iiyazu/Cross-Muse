from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_ROOT = ROOT / "tests" / "fixtures" / "xmuse" / "contracts"

EXPECTED_EVENT_FIXTURES = {
    "blueprint.approved": "events/blueprint.approved.v1.json",
    "planning.started": "events/planning.started.v1.json",
    "planning.failed": "events/planning.failed.v1.json",
    "feature_plan.ready": "events/feature_plan.ready.v1.json",
    "graph_set.ready": "events/graph_set.ready.v1.json",
    "graph_set.failed": "events/graph_set.failed.v1.json",
    "lane.ready": "events/lane.ready.v1.json",
    "lane.updated": "events/lane.updated.v1.json",
    "lane.blocked": "events/lane.blocked.v1.json",
    "review.verdict": "events/review.verdict.v1.json",
    "takeover.requested": "events/takeover.requested.v1.json",
    "takeover.resolved": "events/takeover.resolved.v1.json",
    "run.terminal": "events/run.terminal.v1.json",
    "blueprint.gap_found": "events/blueprint.gap_found.v1.json",
}

# Non-standard fixture files that exist in the artifacts directory but aren't
# xmuse.artifact.v1 contract fixtures. They use their own schema and are
# excluded from contract fixture validation.
_NON_CONTRACT_FIXTURES = {
    "artifacts/chat_memory_taxonomy.v1.json",
    "artifacts/chat_replay_packet.v1.json",
}

EXPECTED_ARTIFACT_FIXTURES: dict[str, str] = {
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

EXPECTED_READ_ENVELOPE_FIXTURES = {
    "tui_worklist": "read_envelopes/tui_worklist.v1.json",
}

EXPECTED_CARD_FIXTURES = {
    "feature_plan_ready": "cards/feature_plan_ready.v1.json",
    "run_progress": "cards/run_progress.v1.json",
    "lane_blocked": "cards/lane_blocked.v1.json",
    "review_verdict": "cards/review_verdict.v1.json",
    "takeover_requested": "cards/takeover_requested.v1.json",
}

EXPECTED_INTERFACE_FIXTURE = "interfaces/xmuse_parallel_sessions.v1.json"


def _load(relative_path: str) -> dict[str, Any]:
    path = CONTRACT_ROOT / relative_path
    with path.open(encoding="utf-8") as handle:
        loaded = json.load(handle)
    assert isinstance(loaded, dict)
    return loaded


def _parse_timestamp(value: Any) -> None:
    assert isinstance(value, str) and value.endswith("Z")
    datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_ref(value: dict[str, Any], *, prefix: str | None = None) -> None:
    assert isinstance(value.get("artifact_type"), str) and value["artifact_type"]
    assert isinstance(value.get("artifact_id"), str) and value["artifact_id"]
    assert isinstance(value.get("version"), int) and value["version"] >= 1
    assert isinstance(value.get("ref"), str) and value["ref"]
    if prefix is not None:
        assert value["ref"].startswith(prefix)


def test_every_contract_fixture_declares_gate_one_metadata() -> None:
    fixture_paths = sorted(CONTRACT_ROOT.glob("**/*.json"))
    assert fixture_paths

    seen_ids: set[str] = set()
    for path in fixture_paths:
        rel = str(path.relative_to(CONTRACT_ROOT))
        if rel in _NON_CONTRACT_FIXTURES:
            continue
        fixture = _load(rel)
        schema_version = fixture.get("schema_version")

        if schema_version == "xmuse.event.v1":
            stable_id = fixture.get("event_id")
            version = fixture.get("aggregate", {}).get("version")
            source_refs = fixture.get("payload", {}).get("source_refs")
        elif schema_version == "xmuse.artifact.v1":
            stable_id = fixture.get("artifact_id")
            version = fixture.get("version")
            source_refs = fixture.get("source_refs")
        elif schema_version == "xmuse.read_envelope.v1":
            stable_id = fixture.get("envelope_id")
            version = fixture.get("version")
            source_refs = fixture.get("source_refs")
        elif schema_version == "xmuse.card.v1":
            stable_id = fixture.get("intent_id")
            version = fixture.get("version")
            source_refs = fixture.get("source_refs")
        elif schema_version == "xmuse.session_interfaces.v1":
            stable_id = fixture.get("manifest_id")
            version = fixture.get("version")
            source_refs = fixture.get("source_refs")
        else:
            raise AssertionError(f"unknown contract schema {schema_version!r}")

        assert isinstance(stable_id, str) and stable_id
        assert stable_id not in seen_ids
        seen_ids.add(stable_id)

        assert isinstance(version, int)
        assert version >= 1

        assert isinstance(source_refs, list) and source_refs
        assert all(isinstance(ref, str) and ref for ref in source_refs)

        timestamp = (
            fixture.get("created_at")
            or fixture.get("updated_at")
            or fixture.get("generated_at")
        )
        _parse_timestamp(timestamp)


def test_all_artifact_fixtures_are_in_inventory() -> None:
    actual_artifact_files = sorted(
        str(p.relative_to(CONTRACT_ROOT))
        for p in (CONTRACT_ROOT / "artifacts").glob("*.json")
        if str(p.relative_to(CONTRACT_ROOT)) not in _NON_CONTRACT_FIXTURES
    )
    missing = [f for f in actual_artifact_files if f not in EXPECTED_ARTIFACT_FIXTURES]
    assert not missing, (
        f"Artifact fixtures missing from EXPECTED_ARTIFACT_FIXTURES: {missing}"
    )


def test_event_fixtures_define_minimum_at_least_once_contract() -> None:
    for event_type, relative_path in EXPECTED_EVENT_FIXTURES.items():
        event = _load(relative_path)

        assert event["schema_version"] == "xmuse.event.v1"
        assert event["event_type"] == event_type
        assert event["delivery"] == "at_least_once"
        assert event["dedupe_strategy"] == "idempotency_key"
        assert isinstance(event.get("event_id"), str) and event["event_id"].startswith("evt_")
        assert isinstance(event.get("aggregate_key"), str) and event["aggregate_key"]
        assert isinstance(event.get("idempotency_key"), str) and event["idempotency_key"]
        assert isinstance(event.get("producer"), str) and event["producer"]
        assert isinstance(event.get("consumers"), list) and event["consumers"]
        _parse_timestamp(event.get("created_at"))

        payload = event.get("payload")
        assert isinstance(payload, dict)
        artifact_refs = payload.get("artifact_refs")
        assert isinstance(artifact_refs, list) and artifact_refs
        for artifact_ref in artifact_refs:
            assert isinstance(artifact_ref, dict)
            _assert_ref(artifact_ref)


def test_artifact_fixtures_have_stable_refs_and_source_events() -> None:
    for relative_path, expected_artifact_type in EXPECTED_ARTIFACT_FIXTURES.items():
        artifact = _load(relative_path)

        assert artifact["schema_version"] == "xmuse.artifact.v1"
        assert artifact["artifact_type"] == expected_artifact_type
        assert isinstance(artifact.get("artifact_id"), str) and artifact["artifact_id"]
        assert isinstance(artifact.get("version"), int) and artifact["version"] >= 1
        assert isinstance(artifact.get("artifact_ref"), str)
        assert artifact["artifact_ref"].startswith(f"{expected_artifact_type}:")
        assert isinstance(artifact.get("source_event_ref"), str)
        assert artifact["source_event_ref"].startswith("event:")
        _parse_timestamp(artifact.get("created_at"))
        _parse_timestamp(artifact.get("updated_at"))


def test_read_envelope_fixtures_are_read_only_and_traceable() -> None:
    for envelope_type, relative_path in EXPECTED_READ_ENVELOPE_FIXTURES.items():
        envelope = _load(relative_path)

        assert envelope["schema_version"] == "xmuse.read_envelope.v1"
        assert envelope["envelope_type"] == envelope_type
        assert envelope["mutation_allowed"] is False
        assert envelope["source_authority"] in {
            "chat_store",
            "feature_lanes_projection",
            "graph_set_artifact",
        }
        assert isinstance(envelope.get("projection_revision"), int)
        assert envelope["projection_revision"] >= 0
        _parse_timestamp(envelope.get("generated_at"))
        assert isinstance(envelope.get("cards"), list)
        assert isinstance(envelope.get("worklist"), list)
        assert isinstance(envelope.get("run_health"), dict)
        assert isinstance(envelope.get("debug_drilldown_refs"), list)


def test_card_fixtures_carry_artifact_refs_and_drilldown_targets() -> None:
    for card_type, relative_path in EXPECTED_CARD_FIXTURES.items():
        card = _load(relative_path)

        assert card["schema_version"] == "xmuse.card.v1"
        assert card["card_type"] == card_type
        assert isinstance(card.get("intent_id"), str) and card["intent_id"]
        assert isinstance(card.get("conversation_id"), str) and card["conversation_id"]
        assert isinstance(card.get("title"), str) and card["title"]
        assert isinstance(card.get("summary"), str) and card["summary"]
        assert isinstance(card.get("status"), str) and card["status"]
        assert isinstance(card.get("source_event_ref"), str)
        assert card["source_event_ref"].startswith("event:")
        _parse_timestamp(card.get("created_at"))

        artifact_refs = card.get("artifact_refs")
        assert isinstance(artifact_refs, list) and artifact_refs
        for artifact_ref in artifact_refs:
            assert isinstance(artifact_ref, dict)
            _assert_ref(artifact_ref)

        drilldown_refs = card.get("drilldown_refs")
        assert isinstance(drilldown_refs, list) and drilldown_refs
        for ref in drilldown_refs:
            assert isinstance(ref, dict)
            assert isinstance(ref.get("label"), str) and ref["label"]
            assert isinstance(ref.get("api_href"), str) and ref["api_href"].startswith("/")


def test_parallel_session_interface_fixture_declares_inputs_and_outputs() -> None:
    fixture = _load(EXPECTED_INTERFACE_FIXTURE)

    assert fixture["schema_version"] == "xmuse.session_interfaces.v1"
    sessions = fixture.get("sessions")
    assert isinstance(sessions, list)
    assert {session["session"] for session in sessions} == {
        "S1",
        "S2",
        "S3",
        "S4",
        "S5",
        "S6",
        "S7",
        "S8",
    }

    for session in sessions:
        assert isinstance(session.get("owner"), str) and session["owner"]
        assert isinstance(session.get("inputs"), list)
        assert isinstance(session.get("outputs"), list) and session["outputs"]
        assert isinstance(session.get("must_not_write"), list)
        assert isinstance(session.get("ready_flag"), str)
        assert session["ready_flag"].startswith("S")
