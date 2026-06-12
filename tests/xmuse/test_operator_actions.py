from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.live_gate_status_capture import ProbeResult
from xmuse_core.platform.operator_actions import (
    OperatorActionCapability,
    OperatorActionRequest,
    OperatorActionService,
)
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
