from __future__ import annotations

import importlib.util
import json
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
MODULE_PATH = PROJECT / "xmuse" / "operator_action_cli.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("xmuse_operator_action_cli", MODULE_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_operator_action_cli_selects_god_cli_through_contract(tmp_path: Path) -> None:
    cli = _load_module()
    output = tmp_path / "operator-action.json"

    rc = cli.main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--action",
            "select_god_cli",
            "--conversation-id",
            "conv-prod",
            "--capability",
            "select_god_cli",
            "--actor-id",
            "operator",
            "--idempotency-key",
            "select-codex-god",
            "--payload-json",
            '{"cli_id": "codex.god"}',
            "--output",
            str(output),
        ]
    )

    assert rc == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["action"] == "select_god_cli"
    assert result["status"] == "ok"
    assert result["fact_state"] == "god_cli_selected"
    assert (
        result["payload"]["selection"]["durable_state_ref"]
        == "god_cli_selection:conv-prod"
    )

    selection_store = json.loads(
        (tmp_path / "god_cli_selections.json").read_text(encoding="utf-8")
    )
    selection = selection_store["selections"]["conv-prod"]
    assert selection["cli_id"] == "codex.god"
    assert selection["selected_by"] == "operator"
    assert selection["idempotency_key"] == "select-codex-god"


def test_operator_action_cli_denies_without_required_capability(
    tmp_path: Path,
) -> None:
    cli = _load_module()
    output = tmp_path / "operator-action-denied.json"

    rc = cli.main(
        [
            "--xmuse-root",
            str(tmp_path),
            "--action",
            "select_god_cli",
            "--conversation-id",
            "conv-prod",
            "--actor-id",
            "operator",
            "--idempotency-key",
            "select-codex-god",
            "--payload-json",
            '{"cli_id": "codex.god"}',
            "--output",
            str(output),
        ]
    )

    assert rc == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["action"] == "select_god_cli"
    assert result["status"] == "denied"
    assert result["fact_state"] == "denied"
    assert "missing capability select_god_cli" in result["summary"]
    assert not (tmp_path / "god_cli_selections.json").exists()
