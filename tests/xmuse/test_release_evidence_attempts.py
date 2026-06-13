from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.protocol_v2 import GodSpeechAct, GodSpeechActMessageV1
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.platform.operator_actions import OperatorActionRequest
from xmuse_core.platform.release_evidence_attempts import run_release_evidence_attempt_action
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


def test_release_evidence_attempt_exports_ready_candidates_and_records_gaps(
    tmp_path: Path,
) -> None:
    conversation_id = _seed_ready_runtime_inputs(tmp_path)
    release_dir = tmp_path / "work" / "release_readiness"

    result = run_release_evidence_attempt_action(
        OperatorActionRequest(
            action="attempt_release_evidence",
            actor_id="operator-1",
            capabilities=("release_gate",),
            idempotency_key="idem-attempt-1",
            payload={
                "conversation_id": conversation_id,
                "target_refs": ["blueprint:bp-1"],
                "runtime_backend": "ray",
                "transport": "codex-app-server",
                "run_id": "soak-pr43",
            },
            source="chat_api",
        ),
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={"XMUSE_MEMORYOS_LITE_URL": "http://memoryos.example?token=secret-token"},
    )

    attempts = {attempt["kind"]: attempt for attempt in result["attempts"]}
    assert result["schema_version"] == "xmuse.release_evidence_attempt.v1"
    assert result["decision"] == "blocked"
    assert attempts["natural_deliberation"]["status"] == "ok"
    assert attempts["real_provider_runtime"]["status"] == "ok"
    assert attempts["live_memoryos"]["status"] == "blocked"
    assert attempts["live_memoryos"]["proof_level"] == "manual_gap"
    assert "memoryos_lite_live_environment_missing" in attempts["live_memoryos"]["blockers"]
    assert (release_dir / "natural-transcript.json").exists()
    assert (release_dir / "god-runtime-continuity.json").exists()
    assert (release_dir / "real-provider-runtime.json").exists()
    assert not (release_dir / "memoryos-trace.json").exists()
    report = json.loads((release_dir / "release-evidence-attempt.json").read_text())
    assert report["decision"] == "blocked"
    assert "secret-token" not in str(report)


def test_release_evidence_attempt_blocks_when_candidates_are_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    conversation = ChatStore(tmp_path / "chat.db").create_conversation("Missing")
    monkeypatch.chdir(tmp_path)
    release_dir = Path("work") / "release_readiness"

    result = run_release_evidence_attempt_action(
        OperatorActionRequest(
            action="attempt_release_evidence",
            actor_id="operator-1",
            capabilities=("release_gate",),
            idempotency_key="idem-attempt-2",
            payload={"conversation_id": conversation.id},
            source="chat_api",
        ),
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
    )

    expected_report = tmp_path / "work" / "release_readiness" / "release-evidence-attempt.json"
    attempts = {attempt["kind"]: attempt for attempt in result["attempts"]}
    assert result["decision"] == "blocked"
    assert attempts["natural_deliberation"]["status"] == "blocked"
    assert attempts["real_provider_runtime"]["status"] == "blocked"
    assert attempts["live_memoryos"]["status"] == "blocked"
    assert attempts["github_server_truth"]["status"] == "blocked"
    assert "natural_god_speech_act_messages_missing" in attempts["natural_deliberation"][
        "blockers"
    ]
    assert "peer_turn_latency_traces_table_missing" in attempts["real_provider_runtime"][
        "blockers"
    ]
    assert attempts["natural_deliberation"]["next_action"] == (
        "Capture a natural multi-GOD transcript and selected GOD runtime "
        "continuity, then run attempt_release_evidence for natural_deliberation."
    )
    assert attempts["real_provider_runtime"]["next_action"] == (
        "Capture fresh and resume MCP writeback provider turns, then run "
        "attempt_release_evidence for real_provider_runtime with real "
        "runtime_backend and transport labels."
    )
    assert attempts["live_memoryos"]["next_action"] == (
        "Configure live MemoryOS Lite and provide a complete task payload, then "
        "run attempt_release_evidence for live_memoryos to capture a live trace."
    )
    assert attempts["github_server_truth"]["next_action"] == (
        "Provide repo and pull_request_number, then run attempt_release_evidence "
        "for github_server_truth to capture read-only GitHub server truth."
    )
    assert result["report_path"] == str(expected_report.resolve(strict=False))
    assert not (tmp_path / "work" / "release_readiness" / "natural-transcript.json").exists()
    assert not (tmp_path / "work" / "release_readiness" / "real-provider-runtime.json").exists()
    assert not (tmp_path / "work" / "release_readiness" / "memoryos-trace.json").exists()
    assert expected_report.exists()


def test_release_evidence_attempt_exports_github_when_requested(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls: list[OperatorActionRequest] = []

    def _fake_export(
        request: OperatorActionRequest,
        **_kwargs: object,
    ) -> dict[str, object]:
        calls.append(request)
        return {
            "kind": "github_server_truth",
            "artifact_path": str(
                tmp_path / "work" / "release_readiness" / "github-server-truth-snapshot.json"
            ),
            "gate_path": str(
                tmp_path
                / "work"
                / "release_readiness"
                / "artifacts"
                / "github-server-truth.json"
            ),
            "gate": {
                "gate_id": "github-server-truth",
                "status": "ok",
                "proof_level": "server_side_enforcement_proof",
            },
        }

    monkeypatch.setattr(
        "xmuse_core.platform.release_evidence_attempts.run_release_evidence_export_action",
        _fake_export,
    )
    release_dir = tmp_path / "work" / "release_readiness"

    result = run_release_evidence_attempt_action(
        OperatorActionRequest(
            action="attempt_release_evidence",
            actor_id="operator-1",
            capabilities=("release_gate",),
            idempotency_key="idem-attempt-github",
            payload={
                "kind": "github",
                "repo": "iiyazu/Cross-Muse",
                "pull_request_number": 43,
                "required_checks": ["quality-gates", "contract-smoke-gates"],
                "expected_head_sha": "head123",
            },
            source="chat_api",
        ),
        xmuse_root=tmp_path,
        release_readiness_dir=release_dir,
        env={},
    )

    assert result["decision"] == "ok"
    assert result["attempted_kinds"] == ["github_server_truth"]
    assert result["attempts"][0]["kind"] == "github_server_truth"
    assert result["attempts"][0]["gate_id"] == "github-server-truth"
    assert calls and calls[0].action == "export_github_server_truth"
    assert calls[0].payload["repo"] == "iiyazu/Cross-Muse"
    assert calls[0].payload["expected_head_sha"] == "head123"


def _seed_ready_runtime_inputs(tmp_path: Path) -> str:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conversation = chat.create_conversation("Release attempt")
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    reviewer = participants.add(
        conversation_id=conversation.id,
        role="review",
        display_name="Review GOD",
        cli_kind="opencode",
        model="opencode-prod",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    architect_session = registry.create(
        role="architect",
        agent_name="architect-god",
        runtime="codex",
        session_address="@architect",
        session_inbox_id="inbox-architect",
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        model="gpt-5.5",
    )
    reviewer_session = registry.create(
        role="review",
        agent_name="review-god",
        runtime="codex",
        session_address="@review",
        session_inbox_id="inbox-review",
        conversation_id=conversation.id,
        participant_id=reviewer.participant_id,
        model="gpt-5.5-review",
    )
    GodCliSelectionStore(tmp_path / "god_cli_selections.json").record_selection(
        conversation_id=conversation.id,
        cli_id="codex.god",
        selected_by="operator",
        audit_id="operator-action:select-codex",
        idempotency_key=f"select:{conversation.id}:codex.god",
        selected_at_utc="2026-06-13T00:00:00Z",
    )
    registry.update_provider_binding(
        architect_session.god_session_id,
        provider_session_id="codex-thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    registry.record_heartbeat(
        architect_session.god_session_id,
        heartbeat_at_utc=_utcnow(),
        status="active",
    )
    registry.update_provider_binding(
        reviewer_session.god_session_id,
        provider_session_id="codex-thread-review",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    registry.record_heartbeat(
        reviewer_session.god_session_id,
        heartbeat_at_utc=_utcnow(),
        status="active",
    )
    chat.add_message(
        conversation_id=conversation.id,
        author=architect.participant_id,
        role="assistant",
        content="I propose freezing bp-1.",
        envelope_type="god_speech_act",
        envelope_json=_speech(
            message_id="speech-1",
            conversation_id=conversation.id,
            sender_god="architect-god",
            speech_act=GodSpeechAct.PROPOSE,
        ),
    )
    chat.add_message(
        conversation_id=conversation.id,
        author=reviewer.participant_id,
        role="assistant",
        content="I vote approve.",
        envelope_type="god_speech_act",
        envelope_json=_speech(
            message_id="speech-2",
            conversation_id=conversation.id,
            sender_god="review-god",
            speech_act=GodSpeechAct.VOTE,
        ),
    )
    traces = PeerTurnLatencyTraceStore(db)
    for inbox_id, offset in (("inbox-fresh", 0.0), ("inbox-resume", 10.0)):
        traces.record(
            conversation_id=conversation.id,
            inbox_item_id=inbox_id,
            participant_id=architect.participant_id,
            target_role="architect",
            message_created_at="2026-06-12T00:00:00Z",
            inbox_claimed_at="2026-06-12T00:00:01Z",
            delivery_started_at=offset + 1.0,
            provider_turn_started_at=offset + 2.0,
            first_delta_at=offset + 2.5,
            writeback_at=offset + 4.0,
            total_latency_ms=3000,
            delivery_mode="mcp_writeback",
            degraded_reason=None,
            stage_timings={
                "ray_actor_delivery_start": {"at": offset + 1.0},
                "codex_app_server_turn_start": {"at": offset + 2.0},
                "chat_post_message": {"at": offset + 3.0},
                "trace_persisted": {"at": offset + 4.0},
            },
        )
    return conversation.id


def _speech(
    *,
    message_id: str,
    conversation_id: str,
    sender_god: str,
    speech_act: GodSpeechAct,
) -> dict[str, object]:
    payload: dict[str, object] = {"decision_scope": "blueprint.freeze"}
    if speech_act is GodSpeechAct.VOTE:
        payload["vote"] = "approve"
    message = GodSpeechActMessageV1(
        message_id=message_id,
        conversation_id=conversation_id,
        thread_id="thread-1",
        sender_god=sender_god,
        targets=["blueprint:bp-1"],
        speech_act=speech_act,
        references=["blueprint:bp-1"],
        lane_scope="lane:lane-1",
        confidence=0.91,
        memory_refs=[],
        payload=payload,
    )
    return {
        "schema_version": 1,
        "type": "god_speech_act",
        "message": message.model_dump(mode="json"),
    }


def _utcnow() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
