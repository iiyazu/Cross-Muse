from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.operator_actions import (
    OperatorActionCapability,
    OperatorActionRequest,
    OperatorActionService,
)
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry


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
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
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


def test_operator_action_blocks_opencode_peer_god_without_peer_proof(tmp_path: Path) -> None:
    service = OperatorActionService(
        god_cli_registry=build_default_god_cli_registry(),
        audit_dir=tmp_path,
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
