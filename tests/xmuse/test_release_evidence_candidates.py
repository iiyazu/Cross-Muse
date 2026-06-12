from __future__ import annotations

from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.protocol_v2 import GodSpeechAct, GodSpeechActMessageV1
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.platform.release_evidence_candidates import (
    build_release_evidence_candidate_report,
)


def test_release_evidence_candidates_identify_ready_natural_and_provider_inputs(
    tmp_path: Path,
) -> None:
    conversation_id = _seed_natural_conversation(tmp_path)
    _seed_provider_traces(tmp_path, conversation_id)

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id=conversation_id,
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://memoryos-lite.example",
        },
        memoryos_payload={
            "repo_id": "iiyazu/Cross-Muse",
            "workspace_id": "xmuse",
            "god_id": "review",
            "thread_id": "thread-1",
            "blueprint_id": "bp-1",
            "feature_id": "feature-1",
            "lane_id": "lane-1",
            "content": "live evidence",
            "query": "production evidence",
        },
    )

    natural = report["natural_deliberation"]["conversations"][0]
    provider = report["real_provider_runtime"]
    memoryos = report["live_memoryos"]
    assert report["schema_version"] == "xmuse.release_evidence_candidates.v1"
    assert natural["conversation_id"] == conversation_id
    assert natural["export_ready"] is True
    assert natural["god_speech_act_count"] == 2
    assert natural["distinct_god_count"] == 2
    assert natural["blockers"] == []
    assert provider["trace_table_present"] is True
    assert provider["export_ready"] is True
    assert provider["suggested_fresh_inbox_item_id"] == "inbox-fresh"
    assert provider["suggested_resume_inbox_item_id"] == "inbox-resume"
    assert memoryos["export_ready"] is True
    assert memoryos["configured"] is True
    assert memoryos["missing_env_keys"] == []


def test_release_evidence_candidates_report_current_gaps_without_secrets(
    tmp_path: Path,
) -> None:
    conversation = ChatStore(tmp_path / "chat.db").create_conversation("Gaps")

    report = build_release_evidence_candidate_report(
        tmp_path,
        conversation_id=conversation.id,
        env={"XMUSE_MEMORYOS_LITE_URL": "http://example.test?token=secret-token"},
        memoryos_payload={},
    )

    natural = report["natural_deliberation"]["conversations"][0]
    provider = report["real_provider_runtime"]
    memoryos = report["live_memoryos"]
    assert natural["export_ready"] is False
    assert "natural_god_speech_act_messages_missing" in natural["blockers"]
    assert provider["trace_table_present"] is False
    assert provider["export_ready"] is False
    assert "peer_turn_latency_traces_table_missing" in provider["blockers"]
    assert memoryos["configured"] is False
    assert "XMUSE_LIVE_MEMORYOS_LITE" in memoryos["missing_env_keys"]
    assert "token=secret-token" not in str(report)


def _seed_natural_conversation(tmp_path: Path) -> str:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conversation = chat.create_conversation("Candidates")
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
        runtime="opencode",
        session_address="@review",
        session_inbox_id="inbox-review",
        conversation_id=conversation.id,
        participant_id=reviewer.participant_id,
        model="opencode-prod",
    )
    registry.update_provider_binding(
        architect_session.god_session_id,
        provider_session_id="codex-thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    registry.update_provider_binding(
        reviewer_session.god_session_id,
        provider_session_id="opencode-thread-1",
        provider_session_kind="opencode_session",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
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
        ),
    )
    return conversation.id


def _seed_provider_traces(tmp_path: Path, conversation_id: str) -> None:
    db = tmp_path / "chat.db"
    participant = ParticipantStore(db).list_by_conversation(conversation_id)[0]
    traces = PeerTurnLatencyTraceStore(db)
    for inbox_id, offset in (("inbox-fresh", 0.0), ("inbox-resume", 10.0)):
        traces.record(
            conversation_id=conversation_id,
            inbox_item_id=inbox_id,
            participant_id=participant.participant_id,
            target_role="architect",
            message_created_at="2026-06-12T00:00:00Z",
            inbox_claimed_at="2026-06-12T00:00:01Z",
            delivery_started_at=offset + 1.0,
            provider_turn_started_at=offset + 2.0,
            first_delta_at=None,
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


def _speech(
    *,
    message_id: str,
    conversation_id: str,
    sender_god: str,
) -> dict[str, object]:
    message = GodSpeechActMessageV1(
        message_id=message_id,
        conversation_id=conversation_id,
        thread_id="thread-1",
        sender_god=sender_god,
        targets=["blueprint:bp-1"],
        speech_act=GodSpeechAct.VOTE,
        references=["blueprint:bp-1"],
        lane_scope="lane:lane-1",
        confidence=0.91,
        memory_refs=[],
        payload={"decision_scope": "blueprint.freeze", "vote": "approve"},
    )
    return {
        "schema_version": 1,
        "type": "god_speech_act",
        "message": message.model_dump(mode="json"),
    }
