from __future__ import annotations

import json
import subprocess
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.operator_actions import OperatorActionRequest
from xmuse_core.platform.release_evidence_export_actions import (
    run_release_evidence_export_action,
)
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


class _FakeGhApiRunner:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        endpoint = command[2]
        response = self.responses.get(endpoint)
        if response is None:
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="not found",
            )
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(response),
            stderr="",
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
    runtime_path = release_dir / "god-runtime-continuity.json"
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    assert gate["gate_id"] == "natural-god-deliberation"
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert runtime["schema_version"] == "xmuse.god_runtime_continuity.v1"
    assert runtime["conversation_id"] == conversation.id
    assert str(runtime_path) in gate["artifacts"]
    assert result["god_runtime_path"] == str(runtime_path.resolve(strict=False))
    assert result["god_runtime"] == runtime
    assert result["gate"] == gate


def test_release_export_action_can_skip_natural_god_runtime_compatibility(
    tmp_path: Path,
) -> None:
    conversation = ChatStore(tmp_path / "chat.db").create_conversation(
        "Natural export compatibility",
    )
    release_dir = tmp_path / "work" / "release_readiness"
    request = OperatorActionRequest(
        action="export_natural_deliberation_transcript",
        actor_id="operator-1",
        capabilities=("release_gate",),
        idempotency_key="idem-natural-export-skip-runtime",
        payload={
            "conversation_id": conversation.id,
            "target_refs": ["blueprint:bp-1"],
            "god_runtime": "skip",
        },
        source="chat_api",
    )

    result = run_release_evidence_export_action(
        request,
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
    )

    assert result["kind"] == "natural_deliberation"
    assert "god_runtime_path" not in result
    assert not (release_dir / "god-runtime-continuity.json").exists()
    gate = json.loads(
        (release_dir / "artifacts" / "natural-deliberation.json").read_text(
            encoding="utf-8"
        )
    )
    assert str(release_dir / "god-runtime-continuity.json") not in gate["artifacts"]


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


def test_release_export_action_writes_memoryos_manual_gap_without_live_configuration(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "work" / "release_readiness"
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

    result = run_release_evidence_export_action(
        request,
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
    )

    artifact_path = release_dir / "memoryos-trace.json"
    gate_path = release_dir / "artifacts" / "live-memoryos.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert result["kind"] == "live_memoryos"
    assert result["artifact_path"] == str(artifact_path.resolve(strict=False))
    assert result["gate_path"] == str(gate_path.resolve(strict=False))
    assert artifact["schema_version"] == "xmuse.memoryos_lite_trace.v1"
    assert artifact["proof_level"] == "manual_gap"
    assert artifact["fact_state"] == "blocked"
    assert artifact["session_id"] == ""
    assert artifact["trace_events"] == []
    assert artifact["blockers"] == [
        {
            "reason": "memoryos_lite_live_environment_missing",
            "source_refs": [],
        }
    ]
    assert gate["gate_id"] == "live-memoryos"
    assert gate["status"] == "blocked"
    assert gate["proof_level"] == "manual_gap"
    assert result["artifact"] == artifact
    assert result["gate"] == gate


def test_release_export_action_writes_github_truth_snapshot_and_gate(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "work" / "release_readiness"
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/43": {
                "node_id": "PR_node_43",
                "merged": False,
                "merged_at": None,
                "merge_commit_sha": None,
                "head": {"sha": "head123"},
            },
            "repos/iiyazu/Cross-Muse/pulls/43/reviews": [],
            "repos/iiyazu/Cross-Muse/branches/main/protection": {
                "required_status_checks": {
                    "checks": [
                        {"context": "quality-gates"},
                        {"context": "contract-smoke-gates"},
                    ],
                },
            },
            "repos/iiyazu/Cross-Muse/commits/head123/check-runs": {
                "check_runs": [
                    {
                        "id": 111,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 112,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ],
            },
        }
    )
    request = OperatorActionRequest(
        action="export_github_server_truth",
        actor_id="operator-1",
        capabilities=("release_gate",),
        idempotency_key="idem-github-export",
        payload={
            "repo": "iiyazu/Cross-Muse",
            "pull_request_number": 43,
            "required_checks": ["quality-gates", "contract-smoke-gates"],
            "expected_head_sha": "head123",
        },
        source="chat_api",
    )

    result = run_release_evidence_export_action(
        request,
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
        github_truth_runner=runner,
    )

    artifact_path = release_dir / "github-server-truth-snapshot.json"
    gate_path = release_dir / "artifacts" / "github-server-truth.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    assert result["kind"] == "github_server_truth"
    assert result["artifact_path"] == str(artifact_path.resolve(strict=False))
    assert result["gate_path"] == str(gate_path.resolve(strict=False))
    assert result["artifact"] == artifact
    assert result["gate"] == gate
    assert artifact["schema_version"] == "github_server_side_truth_capture.v1"
    assert artifact["repo"] == "iiyazu/Cross-Muse"
    assert artifact["pull_request_number"] == 43
    assert artifact["head_sha_matches_expected"] is True
    assert artifact["can_emit_pr_merged"] is False
    assert artifact["merged"] is False
    assert gate["gate_id"] == "github-server-truth"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "server_side_enforcement_proof"
    assert all(command[:2] == ["gh", "api"] for command in runner.commands)
    assert not any(
        token in command
        for command in runner.commands
        for token in ("--method", "PATCH", "POST", "PUT", "DELETE")
    )


def test_release_export_action_writes_god_runtime_continuity_artifact(
    tmp_path: Path,
) -> None:
    release_dir = tmp_path / "work" / "release_readiness"
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id="conv-prod-1",
        cli_id="codex.god",
        selected_by="operator",
        audit_id="operator-action:select-1",
        idempotency_key="select:conv-prod-1",
        selected_at_utc="2026-06-13T00:00:00Z",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = registry.create(
        role="architect",
        agent_name="codex.god",
        runtime="codex",
        session_address="@architect",
        session_inbox_id="inbox-architect",
        conversation_id="conv-prod-1",
        participant_id="participant-architect",
        model="gpt-5.5",
    )
    registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="codex-thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    registry.record_heartbeat(
        session.god_session_id,
        heartbeat_at_utc="2026-06-13T00:04:30Z",
        status="active",
    )
    request = OperatorActionRequest(
        action="export_god_runtime_continuity",
        actor_id="operator-1",
        capabilities=("release_gate",),
        idempotency_key="idem-god-runtime-export",
        payload={
            "conversation_id": "conv-prod-1",
            "now_utc": "2026-06-13T00:05:00Z",
            "heartbeat_ttl_seconds": 120,
        },
        source="chat_api",
    )

    result = run_release_evidence_export_action(
        request,
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
    )

    artifact_path = release_dir / "god-runtime-continuity.json"
    artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert result["kind"] == "god_runtime_continuity"
    assert result["artifact_path"] == str(artifact_path.resolve(strict=False))
    assert "gate_path" not in result
    assert "gate" not in result
    assert result["artifact"] == artifact
    assert artifact["schema_version"] == "xmuse.god_runtime_continuity.v1"
    assert artifact["conversation_id"] == "conv-prod-1"
    assert artifact["fact_state"] == "observed"
    assert artifact["items"][0]["peer_god_ready"] is True
    assert artifact["items"][0]["heartbeat_freshness"] == "fresh"
