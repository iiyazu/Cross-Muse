import json
from pathlib import Path

import pytest

from xmuse.evidence_summary import main
from xmuse_core.chat.store import ChatStore


def test_evidence_summary_cli_prints_projection_summary(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    conv = ChatStore(tmp_path / "chat.db").create_conversation("CLI evidence summary")

    exit_code = main(["--root", str(tmp_path), "--conversation-id", conv.id])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == "natural_groupchat_evidence_summary/v1"
    assert payload["projection_only"] is True
    assert payload["conversation_id"] == conv.id
    assert payload["items"][0] == {
        "kind": "conversation",
        "proof_class": "authority",
        "ref": f"chat.db:conversations#conversation={conv.id}",
        "status": "observed",
        "producer": "chat.db:conversations",
        "consumer": "natural_groupchat_evidence_summary",
        "condition": "conversation_exists",
        "proof_boundary": "conversation_authority_not_execution_or_github_truth",
    }
