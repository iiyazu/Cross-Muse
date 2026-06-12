from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.operator_actions import (
    OperatorActionBlockedError,
    OperatorActionRequest,
)
from xmuse_core.platform.release_evidence_export_actions import (
    run_release_evidence_export_action,
)


def test_release_export_action_writes_natural_transcript_and_gate(
    tmp_path: Path,
) -> None:
    conversation = ChatStore(tmp_path / "chat.db").create_conversation(
        "Natural export",
    )
    release_dir = tmp_path / "work" / "release_readiness"
    request = OperatorActionRequest(
        action="export_natural_deliberation_transcript",
        actor_id="operator-1",
        capabilities=("release_gate",),
        idempotency_key="idem-natural-export",
        payload={
            "conversation_id": conversation.id,
            "target_refs": ["blueprint:bp-1"],
        },
        source="chat_api",
    )

    result = run_release_evidence_export_action(
        request,
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
    )

    artifact_path = release_dir / "natural-transcript.json"
    gate_path = release_dir / "artifacts" / "natural-deliberation.json"
    assert result["kind"] == "natural_deliberation"
    assert result["artifact_path"] == str(artifact_path.resolve(strict=False))
    assert result["gate_path"] == str(gate_path.resolve(strict=False))
    assert json.loads(artifact_path.read_text(encoding="utf-8"))["schema_version"] == (
        "xmuse.operator_transcript.v1"
    )
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "natural-god-deliberation"
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert result["gate"] == gate


def test_release_export_action_writes_provider_soak_and_gate(
    tmp_path: Path,
) -> None:
    conversation = ChatStore(tmp_path / "chat.db").create_conversation(
        "Provider export",
    )
    release_dir = tmp_path / "work" / "release_readiness"
    request = OperatorActionRequest(
        action="export_real_provider_runtime_soak",
        actor_id="operator-1",
        capabilities=("release_gate",),
        idempotency_key="idem-provider-export",
        payload={
            "conversation_id": conversation.id,
            "fresh_inbox_item_id": "inbox-fresh",
            "resume_inbox_item_id": "inbox-resume",
            "runtime_backend": "ray",
            "transport": "codex-app-server",
            "run_id": "soak-pr43",
        },
        source="chat_api",
    )

    result = run_release_evidence_export_action(
        request,
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
    )

    artifact_path = release_dir / "real-provider-runtime.json"
    gate_path = release_dir / "artifacts" / "real-provider-runtime.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert result["kind"] == "real_provider_runtime"
    assert result["artifact"] == artifact
    assert artifact["schema_version"] == "xmuse.real_provider_runtime.v1"
    assert artifact["run_id"] == "soak-pr43"
    assert gate["gate_id"] == "real-provider-runtime"
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"


def test_release_export_action_blocks_memoryos_without_live_configuration(
    tmp_path: Path,
) -> None:
    request = OperatorActionRequest(
        action="export_memoryos_live_trace",
        actor_id="operator-1",
        capabilities=("release_gate",),
        idempotency_key="idem-memoryos-export",
        payload={
            "conversation_id": "conv-1",
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-1",
            "actor_id": "review",
            "content": "live evidence",
            "query": "production evidence",
        },
        source="chat_api",
    )

    with pytest.raises(OperatorActionBlockedError) as exc_info:
        run_release_evidence_export_action(
            request,
            xmuse_root=tmp_path,
            release_readiness_dir=tmp_path / "work" / "release_readiness",
            env={},
        )

    assert "XMUSE_LIVE_MEMORYOS_LITE=1" in exc_info.value.summary
