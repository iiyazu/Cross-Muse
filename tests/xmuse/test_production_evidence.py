from __future__ import annotations

from xmuse_core.platform.production_evidence import ProductionEvidenceEnvelope


def test_production_evidence_envelope_serializes_required_stage_action_fields() -> None:
    envelope = ProductionEvidenceEnvelope(
        run_id="overnight-1",
        stage_id="S1",
        action="checkpoint",
        status="ok",
        proof_level="contract_proof",
        source_authority="overnight_operator_supervisor",
        source_refs=("goal:stage:S1",),
        target_refs=("artifact://result.json",),
        commands=("uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q",),
        test_results=("1 passed",),
        artifacts=("artifact://checkpoint.json",),
        owner="codex",
        summary="checkpoint captured",
        next_action="continue to S2",
    )

    payload = envelope.model_dump()

    assert payload["schema_version"] == "xmuse.production_evidence.v1"
    assert payload["run_id"] == "overnight-1"
    assert payload["stage_id"] == "S1"
    assert payload["action"] == "checkpoint"
    assert payload["status"] == "ok"
    assert payload["proof_level"] == "contract_proof"
    assert payload["source_authority"] == "overnight_operator_supervisor"
    assert payload["source_refs"] == ["goal:stage:S1"]
    assert payload["target_refs"] == ["artifact://result.json"]
    assert payload["commands"] == [
        "uv run pytest tests/xmuse/test_overnight_operator_supervisor.py -q"
    ]
    assert payload["test_results"] == ["1 passed"]
    assert payload["artifacts"] == ["artifact://checkpoint.json"]
    assert payload["blocked_reason"] is None
    assert payload["owner"] == "codex"
    assert payload["summary"] == "checkpoint captured"
    assert payload["next_action"] == "continue to S2"
    assert "gate_id" not in payload


def test_production_evidence_can_include_non_authoritative_release_gate_projection() -> None:
    envelope = ProductionEvidenceEnvelope(
        stage_id="S4",
        action="manual_gap",
        status="manual_gap",
        proof_level="manual_gap",
        source_authority="overnight_operator_supervisor",
        blocked_reason="XMUSE_LIVE_MEMORYOS_LITE is not enabled",
        owner="operator",
        gate_id="goal-stage-S4-manual-gap",
        kind="local_validation",
        configured=False,
        required=False,
        summary="optional live MemoryOS gate was not configured",
    )

    payload = envelope.model_dump()

    assert payload["gate_id"] == "goal-stage-S4-manual-gap"
    assert payload["kind"] == "local_validation"
    assert payload["configured"] is False
    assert payload["required"] is False
    assert payload["blocked_reason"] == "XMUSE_LIVE_MEMORYOS_LITE is not enabled"
