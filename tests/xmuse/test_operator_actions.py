from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.live_gate_status_capture import ProbeResult
from xmuse_core.platform.operator_actions import (
    OperatorActionCapability,
    OperatorActionRequest,
    OperatorActionService,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


def test_operator_action_denies_god_selection_without_capability(tmp_path: Path) -> None:
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
    )
    request = OperatorActionRequest(
        action="select_god_cli",
        actor_id="operator-1",
        capabilities=(),
        idempotency_key="idem-1",
        payload={"cli_id": "codex.god", "conversation_id": "conv-1"},
        source="tui",
    )

    result = service.handle(request)

    assert result.status == "denied"
    assert result.audit_id is not None
    assert result.proof_level == "contract_proof"
    assert "missing capability select_god_cli" in result.summary
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "operator-actions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert audit_rows[-1]["status"] == "denied"
    assert audit_rows[-1]["action"] == "select_god_cli"


def test_operator_action_selects_god_cli_with_audited_capability(tmp_path: Path) -> None:
    selection_store = GodCliSelectionStore(tmp_path / "god_cli_selections.json")
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
        selection_store=selection_store,
    )
    request = OperatorActionRequest(
        action="select_god_cli",
        actor_id="operator-1",
        capabilities=(OperatorActionCapability.SELECT_GOD_CLI,),
        idempotency_key="idem-2",
        payload={"cli_id": "codex.god", "conversation_id": "conv-1"},
        source="tui",
    )

    result = service.handle(request)

    assert result.status == "ok"
    assert result.fact_state == "god_cli_selected"
    assert result.payload["selection"]["cli_id"] == "codex.god"
    assert result.payload["selection"]["conversation_id"] == "conv-1"
    assert result.payload["selection"]["source_authority"] == "operator_action_contract"
    assert result.audit_id is not None
    assert result.payload["selection"]["durable_state_ref"] == "god_cli_selection:conv-1"
    stored = selection_store.get("conv-1")
    assert stored is not None
    assert stored.cli_id == "codex.god"
    assert stored.audit_id == result.audit_id
    assert stored.idempotency_key == "idem-2"


def test_operator_action_blocks_opencode_peer_god_without_peer_proof(tmp_path: Path) -> None:
    selection_store = GodCliSelectionStore(tmp_path / "god_cli_selections.json")
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
        selection_store=selection_store,
    )
    request = OperatorActionRequest(
        action="select_god_cli",
        actor_id="operator-1",
        capabilities=(OperatorActionCapability.SELECT_GOD_CLI,),
        idempotency_key="idem-3",
        payload={
            "cli_id": "opencode.deepseek_flash_worker",
            "conversation_id": "conv-1",
        },
        source="tui",
    )

    result = service.handle(request)

    assert result.status == "blocked"
    assert result.fact_state == "blocked"
    assert "does not advertise peer_god" in result.summary
    assert result.payload["selection_allowed"] is False
    assert selection_store.get("conv-1") is None


def test_operator_action_registers_manual_god_cli_with_audited_capability(
    tmp_path: Path,
) -> None:
    registration_store = GodCliRegistrationStore(tmp_path / "god_cli_registrations.json")
    selection_store = GodCliSelectionStore(tmp_path / "god_cli_selections.json")
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
        registration_store=registration_store,
        selection_store=selection_store,
    )

    register_result = service.handle(
        OperatorActionRequest(
            action="register_god_cli",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.REGISTER_GOD_CLI,),
            idempotency_key="idem-register-1",
            payload=_manual_registration_payload(),
            source="tui",
        )
    )
    select_result = service.handle(
        OperatorActionRequest(
            action="select_god_cli",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.SELECT_GOD_CLI,),
            idempotency_key="idem-select-registered-1",
            payload={"cli_id": "custom.peer", "conversation_id": "conv-1"},
            source="tui",
        )
    )

    assert register_result.status == "ok"
    assert register_result.fact_state == "god_cli_registered"
    assert register_result.payload["registration"]["cli_id"] == "custom.peer"
    assert register_result.payload["registration"]["proof_refs"] == [
        "provider-run://custom.peer/live-smoke-1"
    ]
    assert (
        register_result.payload["durable_state_ref"]
        == "god_cli_registration:custom.peer"
    )
    stored = registration_store.get("custom.peer")
    assert stored is not None
    assert stored.audit_id == register_result.audit_id
    assert stored.registration.cli_id == "custom.peer"
    assert select_result.status == "ok"
    assert select_result.payload["selection"]["cli_id"] == "custom.peer"
    assert selection_store.get("conv-1").cli_id == "custom.peer"


def test_operator_action_denies_god_cli_registration_without_capability(
    tmp_path: Path,
) -> None:
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
        registration_store=GodCliRegistrationStore(
            tmp_path / "god_cli_registrations.json"
        ),
    )

    result = service.handle(
        OperatorActionRequest(
            action="register_god_cli",
            actor_id="operator-1",
            capabilities=(),
            idempotency_key="idem-register-2",
            payload=_manual_registration_payload(),
            source="tui",
        )
    )

    assert result.status == "denied"
    assert result.fact_state == "denied"
    assert "missing capability register_god_cli" in result.summary


def test_operator_action_blocks_manual_peer_god_registration_without_proof_ref(
    tmp_path: Path,
) -> None:
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
        registration_store=GodCliRegistrationStore(
            tmp_path / "god_cli_registrations.json"
        ),
    )
    payload = _manual_registration_payload()
    payload["proof_refs"] = []

    result = service.handle(
        OperatorActionRequest(
            action="register_god_cli",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.REGISTER_GOD_CLI,),
            idempotency_key="idem-register-3",
            payload=payload,
            source="tui",
        )
    )

    assert result.status == "blocked"
    assert result.fact_state == "blocked"
    assert "peer_god requires proof_refs" in result.summary


def test_operator_action_retries_lane_with_guarded_workflow_capability(
    tmp_path: Path,
) -> None:
    lanes_path = _write_lanes(
        tmp_path,
        [{"feature_id": "lane-1", "status": "failed", "retry_count": 0}],
    )
    state_machine = LaneStateMachine(
        lanes_path,
        history_path=tmp_path / "state_history.json",
    )
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        lane_state_machine=state_machine,
    )

    result = service.handle(
        OperatorActionRequest(
            action="retry_lane",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.WORKFLOW_WRITE,),
            idempotency_key="idem-lane-retry-1",
            payload={
                "lane_id": "lane-1",
                "current_status": "failed",
                "reason": "retry after operator review",
            },
            source="tui",
        )
    )

    assert result.status == "ok"
    assert result.fact_state == "lane_retry_requested"
    assert result.payload["lane"]["feature_id"] == "lane-1"
    assert result.payload["lane"]["status"] == "reworking"
    assert result.payload["lane"]["retry_count"] == 1
    assert result.payload["lane"]["last_mutation_audit"] == {
        "actor": "operator-1",
        "reason": "retry after operator review",
        "request_id": "idem-lane-retry-1",
        "tool": "retry_lane",
    }
    assert state_machine.get_lane("lane-1")["status"] == "reworking"
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "operator_actions" / "operator-actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert audit_rows[-1]["action"] == "retry_lane"
    assert audit_rows[-1]["status"] == "ok"


def test_operator_action_denies_lane_retry_without_workflow_capability(
    tmp_path: Path,
) -> None:
    lanes_path = _write_lanes(
        tmp_path,
        [{"feature_id": "lane-1", "status": "failed", "retry_count": 0}],
    )
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        lane_state_machine=LaneStateMachine(lanes_path),
    )

    result = service.handle(
        OperatorActionRequest(
            action="retry_lane",
            actor_id="operator-1",
            capabilities=(),
            idempotency_key="idem-lane-retry-2",
            payload={"lane_id": "lane-1", "current_status": "failed"},
            source="tui",
        )
    )

    assert result.status == "denied"
    assert result.fact_state == "denied"
    assert "missing capability workflow_write" in result.summary
    assert json.loads(lanes_path.read_text(encoding="utf-8"))["lanes"][0]["status"] == (
        "failed"
    )


def test_operator_action_aborts_lane_with_guarded_workflow_capability(
    tmp_path: Path,
) -> None:
    lanes_path = _write_lanes(
        tmp_path,
        [{"feature_id": "lane-2", "status": "rejected", "retry_count": 1}],
    )
    state_machine = LaneStateMachine(lanes_path)
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        lane_state_machine=state_machine,
    )

    result = service.handle(
        OperatorActionRequest(
            action="abort_lane",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.WORKFLOW_WRITE,),
            idempotency_key="idem-lane-abort-1",
            payload={
                "lane_id": "lane-2",
                "current_status": "rejected",
                "reason": "operator abandoned stale lane",
            },
            source="tui",
        )
    )

    assert result.status == "ok"
    assert result.fact_state == "lane_aborted"
    assert result.payload["lane"]["status"] == "failed"
    assert result.payload["lane"]["failure_reason"] == "operator abandoned stale lane"
    assert result.payload["lane"]["last_mutation_audit"] == {
        "actor": "operator-1",
        "reason": "operator abandoned stale lane",
        "request_id": "idem-lane-abort-1",
        "tool": "abort_lane",
    }


def test_operator_action_blocks_lane_action_when_guard_mismatches(
    tmp_path: Path,
) -> None:
    lanes_path = _write_lanes(
        tmp_path,
        [{"feature_id": "lane-1", "status": "failed", "retry_count": 0}],
    )
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        lane_state_machine=LaneStateMachine(lanes_path),
    )

    result = service.handle(
        OperatorActionRequest(
            action="retry_lane",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.WORKFLOW_WRITE,),
            idempotency_key="idem-lane-retry-3",
            payload={"lane_id": "lane-1", "current_status": "dispatched"},
            source="tui",
        )
    )

    assert result.status == "blocked"
    assert result.fact_state == "blocked"
    assert "state guard mismatch" in result.summary
    assert LaneStateMachine(lanes_path).get_lane("lane-1")["status"] == "failed"


def test_operator_action_freezes_blueprint_with_audited_capability(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def _freeze_handler(request: OperatorActionRequest) -> dict[str, object]:
        calls.append(request.payload)
        return {
            "decision": {"status": "allowed"},
            "blueprint": {"blueprint_id": "bp-1", "status": "frozen"},
            "resolution": {"id": "res-1"},
        }

    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        blueprint_freeze_handler=_freeze_handler,
    )

    result = service.handle(
        OperatorActionRequest(
            action="freeze_blueprint",
            actor_id="operator-1",
            capabilities=("chat_freeze_blueprint",),
            idempotency_key="idem-freeze-1",
            payload=_blueprint_freeze_payload(),
            source="tui",
        )
    )

    assert result.status == "ok"
    assert result.fact_state == "blueprint_frozen"
    assert result.payload["source_authority"] == "operator_action_contract"
    assert result.payload["freeze"]["blueprint"]["blueprint_id"] == "bp-1"
    assert calls == [_blueprint_freeze_payload()]
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "operator_actions" / "operator-actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert audit_rows[-1]["action"] == "freeze_blueprint"
    assert audit_rows[-1]["status"] == "ok"


def test_operator_action_denies_blueprint_freeze_without_capability(
    tmp_path: Path,
) -> None:
    calls: list[dict[str, object]] = []

    def _freeze_handler(request: OperatorActionRequest) -> dict[str, object]:
        calls.append(request.payload)
        return {"decision": {"status": "allowed"}}

    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        blueprint_freeze_handler=_freeze_handler,
    )

    result = service.handle(
        OperatorActionRequest(
            action="freeze_blueprint",
            actor_id="operator-1",
            capabilities=(),
            idempotency_key="idem-freeze-2",
            payload=_blueprint_freeze_payload(),
            source="tui",
        )
    )

    assert result.status == "denied"
    assert result.fact_state == "denied"
    assert "missing capability chat_freeze_blueprint" in result.summary
    assert calls == []


def test_operator_action_blocks_blueprint_freeze_without_handler(
    tmp_path: Path,
) -> None:
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
    )

    result = service.handle(
        OperatorActionRequest(
            action="freeze_blueprint",
            actor_id="operator-1",
            capabilities=("chat_freeze_blueprint",),
            idempotency_key="idem-freeze-3",
            payload=_blueprint_freeze_payload(),
            source="tui",
        )
    )

    assert result.status == "blocked"
    assert result.fact_state == "blocked"
    assert "requires a blueprint freeze handler" in result.summary


def test_operator_action_exports_release_evidence_with_audited_capability(
    tmp_path: Path,
) -> None:
    calls: list[OperatorActionRequest] = []

    def _export_handler(request: OperatorActionRequest) -> dict[str, object]:
        calls.append(request)
        return {
            "kind": "natural_deliberation",
            "artifact_path": str(tmp_path / "natural-transcript.json"),
            "gate_path": str(tmp_path / "artifacts" / "natural-deliberation.json"),
            "artifact": {
                "schema_version": "xmuse.operator_transcript.v1",
                "proof_level": "manual_gap",
                "fact_state": "blocked",
            },
            "gate": {
                "gate_id": "natural-god-deliberation",
                "status": "blocked",
                "proof_level": "manual_gap",
            },
        }

    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_evidence_export_handler=_export_handler,
    )

    result = service.handle(
        OperatorActionRequest(
            action="export_natural_deliberation_transcript",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.RELEASE_GATE,),
            idempotency_key="idem-release-export-1",
            payload={
                "conversation_id": "conv-1",
                "target_refs": ["blueprint:bp-1"],
            },
            source="tui",
        )
    )

    assert result.status == "ok"
    assert result.fact_state == "release_evidence_exported"
    assert result.proof_level == "contract_proof"
    assert result.payload["source_authority"] == "operator_action_contract"
    assert result.payload["export"]["kind"] == "natural_deliberation"
    assert result.payload["export"]["gate"]["gate_id"] == "natural-god-deliberation"
    assert calls and calls[0].action == "export_natural_deliberation_transcript"
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "operator_actions" / "operator-actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert audit_rows[-1]["action"] == "export_natural_deliberation_transcript"
    assert audit_rows[-1]["status"] == "ok"


def test_operator_action_denies_release_evidence_export_without_capability(
    tmp_path: Path,
) -> None:
    calls: list[OperatorActionRequest] = []

    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_evidence_export_handler=lambda request: calls.append(request) or {},
    )

    result = service.handle(
        OperatorActionRequest(
            action="export_real_provider_runtime_soak",
            actor_id="operator-1",
            capabilities=(),
            idempotency_key="idem-release-export-2",
            payload={"conversation_id": "conv-1"},
            source="tui",
        )
    )

    assert result.status == "denied"
    assert result.fact_state == "denied"
    assert "missing capability release_gate" in result.summary
    assert calls == []


def test_operator_action_blocks_release_evidence_export_without_handler(
    tmp_path: Path,
) -> None:
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
    )

    result = service.handle(
        OperatorActionRequest(
            action="export_memoryos_live_trace",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.RELEASE_GATE,),
            idempotency_key="idem-release-export-3",
            payload={"conversation_id": "conv-1"},
            source="tui",
        )
    )

    assert result.status == "blocked"
    assert result.proof_level == "manual_gap"
    assert result.fact_state == "blocked"
    assert "requires a release evidence export handler" in result.summary


def _manual_registration_payload() -> dict[str, object]:
    return {
        "cli_id": "custom.peer",
        "display_name": "Custom Peer",
        "command_family": "custom-cli",
        "provider_profile_ref": "custom.peer",
        "capabilities": ["peer_god"],
        "supports_persistent_sessions": True,
        "supports_mcp_writeback": True,
        "state_write_allowed": True,
        "proof_level": "real_provider_proof",
        "proof_refs": ["provider-run://custom.peer/live-smoke-1"],
    }


def _blueprint_freeze_payload() -> dict[str, object]:
    return {
        "conversation_id": "conv-1",
        "target_ref": "blueprint:bp-1:1",
        "blueprint": {
            "blueprint_id": "bp-1",
            "revision": 1,
            "goal": "Ship REST-first deliberation freeze.",
            "scope": ["Append deliberation events", "Freeze a blueprint"],
            "acceptance_contracts": ["Frozen blueprint appears as a durable card"],
            "source_refs": ["memory://conversation/conv-1/message/msg-proposal"],
        },
    }


def _write_lanes(tmp_path: Path, lanes: list[dict[str, object]]) -> Path:
    lanes_path = tmp_path / "feature_lanes.json"
    lanes_path.write_text(
        json.dumps({"projection_revision": 1, "lanes": lanes}),
        encoding="utf-8",
    )
    return lanes_path


def _write_gate(path: Path, *, gate_id: str = "provider-soak") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "schema_version": "xmuse.production_evidence.v1",
                "gate_id": gate_id,
                "kind": "real_provider",
                "configured": True,
                "required": True,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "owner": "operator",
                "summary": "Provider soak was not supplied.",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_operator_action_captures_release_evidence_pack_with_capability(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "release_readiness"
    _write_gate(release_dir / "artifacts" / "provider.json")
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_readiness_dir=release_dir,
    )

    result = service.handle(
        OperatorActionRequest(
            action="capture_release_evidence_pack",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.RELEASE_GATE,),
            idempotency_key="idem-release-1",
            payload={},
            source="tui",
        )
    )

    assert result.status == "ok"
    assert result.fact_state == "release_evidence_pack_captured"
    assert result.payload["evidence_pack"]["decision"] == "blocked"
    assert result.payload["evidence_pack"]["blocker_count"] == 1
    assert (release_dir / "evidence-pack.json").exists()
    assert (release_dir / "release-readiness.json").exists()
    assert (release_dir / "proof-contamination-audit.json").exists()
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "operator_actions" / "operator-actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert audit_rows[-1]["action"] == "capture_release_evidence_pack"
    assert audit_rows[-1]["status"] == "ok"
    assert audit_rows[-1]["result_payload"]["evidence_pack"]["decision"] == "blocked"


def test_operator_action_denies_release_evidence_pack_without_capability(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "release_readiness"
    _write_gate(release_dir / "artifacts" / "provider.json")
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_readiness_dir=release_dir,
    )

    result = service.handle(
        OperatorActionRequest(
            action="capture_release_evidence_pack",
            actor_id="operator-1",
            capabilities=(),
            idempotency_key="idem-release-2",
            payload={},
            source="tui",
        )
    )

    assert result.status == "denied"
    assert result.fact_state == "denied"
    assert "missing capability release_gate" in result.summary
    assert not (release_dir / "evidence-pack.json").exists()


def test_operator_action_blocks_release_evidence_pack_paths_outside_release_root(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "release_readiness"
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_readiness_dir=release_dir,
    )

    result = service.handle(
        OperatorActionRequest(
            action="capture_release_evidence_pack",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.RELEASE_GATE,),
            idempotency_key="idem-release-3",
            payload={"output_path": str(tmp_path / "outside-pack.json")},
            source="tui",
        )
    )

    assert result.status == "blocked"
    assert result.fact_state == "blocked"
    assert "must stay under release readiness root" in result.summary
    assert not (tmp_path / "outside-pack.json").exists()


def test_operator_action_refreshes_live_gate_status_with_capability(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "release_readiness"
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_readiness_dir=release_dir,
        live_gate_env={"XMUSE_LIVE_MEMORYOS_LITE": "1"},
        live_gate_command_runner=_fake_probe_runner(),
    )

    result = service.handle(
        OperatorActionRequest(
            action="refresh_live_gate_status",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.RELEASE_GATE,),
            idempotency_key="idem-refresh-1",
            payload={},
            source="tui",
        )
    )

    output_dir = release_dir / "artifacts" / "live_gate_status"
    assert result.status == "ok"
    assert result.fact_state == "live_gate_status_refreshed"
    assert result.payload["live_gate_status"]["artifact_count"] == 4
    assert [
        (gate["gate_id"], gate["status"], gate["proof_level"])
        for gate in result.payload["gate_statuses"]
    ] == [
        ("github-server-truth", "blocked", "manual_gap"),
        ("live-memoryos", "blocked", "manual_gap"),
        ("natural-god-deliberation", "manual_gap", "manual_gap"),
        ("real-provider-runtime", "blocked", "manual_gap"),
    ]
    assert [
        blocker["gate_id"] for blocker in result.payload["blockers"]
    ] == [
        "github-server-truth",
        "live-memoryos",
        "natural-god-deliberation",
        "real-provider-runtime",
    ]
    assert result.payload["output_dir"] == str(output_dir.resolve(strict=False))
    assert sorted(path.name for path in output_dir.glob("*.json")) == [
        "github-server-truth-status.json",
        "live-memoryos-status.json",
        "natural-deliberation-status.json",
        "real-provider-status.json",
    ]
    audit_rows = [
        json.loads(line)
        for line in (tmp_path / "operator_actions" / "operator-actions.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    assert audit_rows[-1]["action"] == "refresh_live_gate_status"
    assert audit_rows[-1]["status"] == "ok"


def test_operator_action_denies_live_gate_status_refresh_without_capability(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "release_readiness"
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_readiness_dir=release_dir,
        live_gate_command_runner=_fake_probe_runner(),
    )

    result = service.handle(
        OperatorActionRequest(
            action="refresh_live_gate_status",
            actor_id="operator-1",
            capabilities=(),
            idempotency_key="idem-refresh-2",
            payload={},
            source="tui",
        )
    )

    assert result.status == "denied"
    assert result.fact_state == "denied"
    assert "missing capability release_gate" in result.summary
    assert not (release_dir / "artifacts" / "live_gate_status").exists()


def test_operator_action_blocks_live_gate_status_paths_outside_release_root(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "release_readiness"
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path / "operator_actions",
        release_readiness_dir=release_dir,
        live_gate_command_runner=_fake_probe_runner(),
    )

    result = service.handle(
        OperatorActionRequest(
            action="refresh_live_gate_status",
            actor_id="operator-1",
            capabilities=(OperatorActionCapability.RELEASE_GATE,),
            idempotency_key="idem-refresh-3",
            payload={"output_dir": str(tmp_path / "outside-live-gates")},
            source="tui",
        )
    )

    assert result.status == "blocked"
    assert result.fact_state == "blocked"
    assert "must stay under release readiness root" in result.summary
    assert not (tmp_path / "outside-live-gates").exists()


def _fake_probe_runner():
    def run(command: tuple[str, ...]) -> ProbeResult:
        return ProbeResult(
            name=" ".join(command),
            command=command,
            returncode=0,
            stdout="ok",
            stderr="",
        )

    return run
