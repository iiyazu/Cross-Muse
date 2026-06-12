from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.platform.operator_evidence_actions import (
    build_blocker_navigation_action,
    build_github_truth_action,
    build_memory_trace_action,
    export_deliberation_transcript,
)


def test_export_deliberation_transcript_preserves_structured_evidence(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "transcript.json"

    result = export_deliberation_transcript(
        conversation_id="conv-1",
        messages=[
            {
                "id": "msg-propose",
                "conversation_id": "conv-1",
                "author": "architect",
                "created_at": "2026-06-12T00:00:00Z",
                "envelope_json": {
                    "speech_act": "propose",
                    "god_id": "architect-god",
                    "provider_id": "codex",
                    "decision_scope": "blueprint.freeze",
                    "source_refs": ["memory://conversation/conv-1/source"],
                    "target_ref": "blueprint:conv-1:1",
                    "payload": {"summary": "freeze scoped blueprint"},
                },
            },
            {
                "id": "msg-challenge",
                "conversation_id": "conv-1",
                "author": "review",
                "created_at": "2026-06-12T00:01:00Z",
                "envelope_json": {
                    "act": "challenge",
                    "god_id": "review-god",
                    "provider_id": "codex",
                    "decision_scope": "blueprint.freeze",
                    "source_ref": "message:msg-propose",
                    "target_refs": ["blueprint:conv-1:1"],
                    "blocking": True,
                    "payload": {"summary": "acceptance criteria missing"},
                },
            },
        ],
        artifact_path=artifact_path,
        proof_level="contract_proof",
    )

    assert result.status == "ok"
    assert result.action == "transcript_export"
    assert result.proof_level == "contract_proof"
    assert result.fact_state == "blocked"
    assert result.artifact_path == str(artifact_path)
    assert result.manual_gap_reason is None
    assert result.source_refs == [
        "message:msg-propose",
        "memory://conversation/conv-1/source",
        "message:msg-challenge",
    ]
    assert result.target_refs == ["blueprint:conv-1:1"]

    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "xmuse.operator_transcript.v1"
    assert artifact["conversation_id"] == "conv-1"
    assert artifact["proof_level"] == "contract_proof"
    assert artifact["messages"] == [
        {
            "message_id": "msg-propose",
            "conversation_id": "conv-1",
            "god_id": "architect-god",
            "provider_id": "codex",
            "author": "architect",
            "speech_act": "propose",
            "decision_scope": "blueprint.freeze",
            "source_refs": ["memory://conversation/conv-1/source"],
            "target_refs": ["blueprint:conv-1:1"],
            "blocking": False,
            "created_at": "2026-06-12T00:00:00Z",
        },
        {
            "message_id": "msg-challenge",
            "conversation_id": "conv-1",
            "god_id": "review-god",
            "provider_id": "codex",
            "author": "review",
            "speech_act": "challenge",
            "decision_scope": "blueprint.freeze",
            "source_refs": ["message:msg-propose"],
            "target_refs": ["blueprint:conv-1:1"],
            "blocking": True,
            "created_at": "2026-06-12T00:01:00Z",
        },
    ]
    assert artifact["blockers"] == [
        {
            "message_id": "msg-challenge",
            "reason": "acceptance criteria missing",
            "target_refs": ["blueprint:conv-1:1"],
        }
    ]


def test_export_deliberation_transcript_manual_gap_when_no_structured_messages(
    tmp_path: Path,
) -> None:
    artifact_path = tmp_path / "transcript.json"

    result = export_deliberation_transcript(
        conversation_id="conv-1",
        messages=[{"id": "msg-freeform", "content": "plain text"}],
        artifact_path=artifact_path,
    )

    assert result.status == "manual_gap"
    assert result.proof_level == "manual_gap"
    assert result.fact_state == "manual_gap"
    assert result.artifact_path is None
    assert result.manual_gap_reason == "structured deliberation transcript unavailable"
    assert not artifact_path.exists()


def test_github_and_memory_actions_preserve_existing_proof_levels() -> None:
    github = build_github_truth_action(
        conversation_id="conv-1",
        github={
            "proof_level": "server_side_enforcement_proof",
            "fact_state": "merge_ready",
            "source_refs": ["github://repo/pull/42"],
            "target_refs": ["pull_request:42"],
            "manual_gap_reason": None,
        },
    )
    memory = build_memory_trace_action(
        conversation_id="conv-1",
        memory={
            "proof_level": "manual_gap",
            "fact_state": "manual_gap",
            "manual_gap_reason": "memory trace unavailable",
        },
    )

    assert github.status == "ok"
    assert github.action == "github_truth_load"
    assert github.proof_level == "server_side_enforcement_proof"
    assert github.fact_state == "merge_ready"
    assert github.source_refs == ["github://repo/pull/42"]

    assert memory.status == "manual_gap"
    assert memory.action == "memory_trace_load"
    assert memory.proof_level == "manual_gap"
    assert memory.manual_gap_reason == "memory trace unavailable"


def test_blocker_navigation_action_returns_targets_without_claiming_authority() -> None:
    result = build_blocker_navigation_action(
        conversation_id="conv-1",
        vision={
            "blueprint_freeze": {
                "blockers": [
                    {
                        "message_id": "msg-blocker",
                        "reason": "needs review evidence",
                        "target_refs": ["blueprint:conv-1:1"],
                        "source_refs": ["message:msg-review"],
                    }
                ]
            },
            "execution": {
                "blockers": [
                    {
                        "lane_id": "lane-b",
                        "reason": "dependency not merged",
                        "target_refs": ["lane:lane-b"],
                        "source_refs": ["feature_lanes_projection#projection_revision=9"],
                    }
                ]
            },
        },
    )

    assert result.status == "ok"
    assert result.action == "blocker_navigation"
    assert result.proof_level == "contract_proof"
    assert result.fact_state == "observed"
    assert result.target_refs == ["blueprint:conv-1:1", "lane:lane-b"]
    assert result.payload["navigation_targets"] == [
        {
            "kind": "blueprint",
            "label": "needs review evidence",
            "source_refs": ["message:msg-review"],
            "target_refs": ["blueprint:conv-1:1"],
        },
        {
            "kind": "lane",
            "label": "dependency not merged",
            "source_refs": ["feature_lanes_projection#projection_revision=9"],
            "target_refs": ["lane:lane-b"],
        },
    ]
