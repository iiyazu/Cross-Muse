"""Replay fixture tests: load frozen contract fixtures and verify they can be
consumed as structured read data without re-generating from a live run.

Each test loads one or more .json fixtures from the contracts directory and
validates that the fixture's payload is structurally valid for the read
surface contract it represents (event, artifact, card, read envelope,
session interface).
"""
from __future__ import annotations

import json
from pathlib import Path

FIXTURES_ROOT = (
    Path(__file__).resolve().parents[2]
    / "tests" / "fixtures" / "xmuse" / "contracts"
)


def _load_fixture(*parts: str) -> dict:
    path = FIXTURES_ROOT.joinpath(*parts)
    return json.loads(path.read_text(encoding="utf-8"))


def test_replay_event_fixtures_as_read_contract_payload() -> None:
    """Load each event fixture and verify its payload is structurally valid
    for read-side contract consumers (dashboard cards, MCP notifications)."""
    for relative in sorted(FIXTURES_ROOT.rglob("events/*.json")):
        event = json.loads(relative.read_text(encoding="utf-8"))
        assert event["schema_version"] == "xmuse.event.v1"
        assert event["delivery"] == "at_least_once"
        assert event["dedupe_strategy"] == "idempotency_key"
        assert isinstance(event["event_id"], str) and event["event_id"]
        assert isinstance(event["aggregate"], dict)
        assert isinstance(event["aggregate"]["version"], int)

        payload = event.get("payload", {})
        assert isinstance(payload, dict)
        artifact_refs = payload.get("artifact_refs")
        if artifact_refs is not None:
            assert isinstance(artifact_refs, list)


def test_replay_artifact_fixtures_as_read_contract_payload() -> None:
    """Load each artifact fixture and verify lineage/ownership fields that
    both dashboard drill-down and MCP read tools depend on."""
    for relative in sorted(FIXTURES_ROOT.rglob("artifacts/*.json")):
        artifact = json.loads(relative.read_text(encoding="utf-8"))
        if artifact.get("schema_version") != "xmuse.artifact.v1":
            continue
        assert isinstance(artifact["artifact_id"], str)
        assert isinstance(artifact["version"], int)
        assert artifact["version"] >= 1
        assert isinstance(artifact.get("lineage"), dict)
        assert isinstance(artifact.get("ownership"), dict)
        source_event_ref = artifact.get("source_event_ref")
        if source_event_ref is not None:
            assert isinstance(source_event_ref, str)


def test_replay_read_envelope_cards_resolve_to_card_fixtures() -> None:
    """Load the TUI worklist read envelope fixture and verify each card
    embedded in it matches the corresponding standalone card fixture.
    This demonstrates a live replay path: envelope → card drill-down."""
    envelope = _load_fixture("read_envelopes", "tui_worklist.v1.json")
    assert envelope["schema_version"] == "xmuse.read_envelope.v1"
    assert envelope["mutation_allowed"] is False

    for card_from_envelope in envelope.get("cards", []):
        card_type = card_from_envelope["card_type"]
        card_fixture = _load_fixture("cards", f"{card_type}.v1.json")
        assert card_fixture["card_type"] == card_type
        assert card_fixture["intent_id"] == card_from_envelope["intent_id"]
        assert card_fixture["schema_version"] == "xmuse.card.v1"
        assert isinstance(card_fixture["artifact_refs"], list)
        assert isinstance(card_fixture["drilldown_refs"], list)


def test_replay_card_fixtures_are_self_describing_replay_units() -> None:
    """Each card fixture is a self-contained replay unit that dashboard and
    TUI can consume directly without runtime state."""
    card_types = [
        "feature_plan_ready",
        "run_progress",
        "lane_blocked",
        "review_verdict",
        "takeover_requested",
    ]
    for card_type in card_types:
        card = _load_fixture("cards", f"{card_type}.v1.json")
        assert card["schema_version"] == "xmuse.card.v1"
        assert card["card_type"] == card_type
        assert isinstance(card["intent_id"], str)
        assert isinstance(card["title"], str)
        assert isinstance(card["summary"], str)
        assert isinstance(card["artifact_refs"], list)
        assert isinstance(card["drilldown_refs"], list)
        for ref in card["drilldown_refs"]:
            assert ref["api_href"].startswith("/")


def test_replay_event_artifact_chain_is_traceable() -> None:
    """Load one event fixture and verify each artifact_ref resolves to a real
    artifact fixture on disk with matching artifact_type, artifact_id and
    artifact_ref."""
    event = _load_fixture("events", "graph_set.ready.v1.json")
    payload = event.get("payload", {})
    for ref_entry in payload.get("artifact_refs", []):
        expected_type = ref_entry.get("artifact_type")
        expected_id = ref_entry.get("artifact_id")
        expected_ref = ref_entry.get("ref")
        if not (expected_type and expected_id and expected_ref):
            continue
        fixture_path = FIXTURES_ROOT / "artifacts" / f"{expected_type}.v1.json"
        if not fixture_path.exists():
            alt = sorted(
                p for p in (FIXTURES_ROOT / "artifacts").glob(f"{expected_type}*.json")
            )
            assert alt, (
                f"replay trace: no artifact fixture for type={expected_type}, "
                f"id={expected_id}, ref={expected_ref}"
            )
            fixture_path = alt[0]
        artifact = json.loads(fixture_path.read_text(encoding="utf-8"))
        assert artifact.get("artifact_type") == expected_type, (
            f"fixture {fixture_path.name} artifact_type {artifact.get('artifact_type')} "
            f"!= event ref {expected_type}"
        )
        assert artifact.get("artifact_id") == expected_id, (
            f"fixture {fixture_path.name} artifact_id {artifact.get('artifact_id')} "
            f"!= event ref {expected_id}"
        )
        assert artifact.get("artifact_ref") == expected_ref, (
            f"fixture {fixture_path.name} artifact_ref {artifact.get('artifact_ref')} "
            f"!= event ref {expected_ref}"
        )


def test_replay_interface_fixture_describes_all_parallel_sessions() -> None:
    """The session interface fixture is a static manifest that parallel
    development sessions consume as their I/O contract.  No live data needed."""
    interface = _load_fixture("interfaces", "xmuse_parallel_sessions.v1.json")
    assert interface["schema_version"] == "xmuse.session_interfaces.v1"
    sessions = {s["session"] for s in interface["sessions"]}
    assert sessions == {f"S{i}" for i in range(1, 9)}
    for session in interface["sessions"]:
        assert session["inputs"]
        assert session["outputs"]
        assert session["must_not_write"]
        assert "feature_lanes.json" in session["must_not_write"]
