from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.models import Conversation
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.protocol_v2 import GodSpeechAct, GodSpeechActMessageV1
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.natural_deliberation_release_gate import (
    build_natural_deliberation_release_gate,
)
from xmuse_core.platform.natural_deliberation_transcript_capture import (
    export_natural_deliberation_transcript_artifact,
)


def _conversation(tmp_path: Path) -> tuple[Path, Conversation]:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    return db, chat.create_conversation("Natural GOD transcript")


def _speech(
    *,
    message_id: str,
    conversation_id: str,
    sender_god: str,
    speech_act: GodSpeechAct,
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
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
        memory_refs=["memory://conversation/conv-live/source"],
        payload=payload
        or {
            "decision_scope": "blueprint.freeze",
            "summary": "Ready to freeze.",
        },
    )
    return {
        "schema_version": 1,
        "type": "god_speech_act",
        "message": message.model_dump(mode="json"),
    }


def test_natural_transcript_export_accepts_real_multi_god_speech_acts(
    tmp_path: Path,
) -> None:
    db, conversation = _conversation(tmp_path)
    chat = ChatStore(db)
    participants = ParticipantStore(db)
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
            payload={
                "decision_scope": "blueprint.freeze",
                "vote": "approve",
            },
        ),
    )

    output = tmp_path / "natural-transcript.json"
    artifact = export_natural_deliberation_transcript_artifact(
        chat_db_path=db,
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation.id,
        output_path=output,
        target_refs=["blueprint:bp-1"],
    )

    assert artifact == json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "xmuse.operator_transcript.v1"
    assert artifact["conversation_id"] == conversation.id
    assert artifact["proof_level"] == "real_provider_proof"
    assert artifact["fact_state"] == "observed"
    assert artifact["natural_deliberation"] is True
    assert artifact["source_refs"] == [
        f"memory://conversation/{conversation.id}/transcript",
        "chat:message:speech-1",
        "blueprint:bp-1",
        "memory://conversation/conv-live/source",
        "chat:message:speech-2",
    ]
    assert artifact["messages"] == [
        {
            "message_id": "speech-1",
            "conversation_id": conversation.id,
            "god_id": "architect-god",
            "provider_id": "codex",
            "provider_profile": "god",
            "session_id": "codex-thread-1",
            "speech_act": "propose",
            "decision_scope": "blueprint.freeze",
            "source_refs": [
                "chat:message:speech-1",
                "blueprint:bp-1",
                "memory://conversation/conv-live/source",
            ],
            "target_refs": ["blueprint:bp-1"],
            "blocking": False,
        },
        {
            "message_id": "speech-2",
            "conversation_id": conversation.id,
            "god_id": "review-god",
            "provider_id": "opencode",
            "provider_profile": "review",
            "session_id": "opencode-thread-1",
            "speech_act": "vote",
            "decision_scope": "blueprint.freeze",
            "source_refs": [
                "chat:message:speech-2",
                "blueprint:bp-1",
                "memory://conversation/conv-live/source",
            ],
            "target_refs": ["blueprint:bp-1"],
            "blocking": False,
        },
    ]
    assert artifact["blockers"] == []

    gate = build_natural_deliberation_release_gate(artifact, artifact_path=output)
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "real_provider_proof"


def test_natural_transcript_export_rejects_deterministic_deliberation_replay(
    tmp_path: Path,
) -> None:
    db, conversation = _conversation(tmp_path)
    chat = ChatStore(db)
    chat.add_message(
        conversation_id=conversation.id,
        author="review-agent",
        role="assistant",
        content="Approve by deterministic route.",
        envelope_type="deliberation",
        envelope_json={
            "type": "deliberation",
            "message": {
                "version": "deliberation_message.v1",
                "msg_id": "det-1",
                "conversation_id": conversation.id,
                "agent_id": "review-agent",
                "lamport_ts": 1,
                "kind": "vote",
                "parent_id": None,
                "target_ref": "blueprint:bp-1",
                "mentions": [],
                "payload": {"vote": "approve"},
                "source_refs": ["blueprint:bp-1"],
                "objection_level": None,
                "decision_scope": "blueprint.freeze",
            },
        },
    )

    artifact = export_natural_deliberation_transcript_artifact(
        chat_db_path=db,
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation.id,
        output_path=tmp_path / "natural-transcript.json",
    )

    assert artifact["proof_level"] == "manual_gap"
    assert artifact["natural_deliberation"] is False
    assert artifact["messages"] == []
    assert artifact["blockers"] == [
        {
            "reason": "natural_god_speech_act_messages_missing",
            "source_refs": [f"conversation:{conversation.id}"],
        }
    ]


def test_natural_transcript_export_blocks_missing_provider_session_metadata(
    tmp_path: Path,
) -> None:
    db, conversation = _conversation(tmp_path)
    chat = ChatStore(db)
    participants = ParticipantStore(db)
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
        cli_kind="codex",
        model="gpt-5.5",
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
    )
    registry.create(
        role="review",
        agent_name="review-god",
        runtime="codex",
        session_address="@review",
        session_inbox_id="inbox-review",
        conversation_id=conversation.id,
        participant_id=reviewer.participant_id,
    )
    registry.update_provider_binding(
        architect_session.god_session_id,
        provider_session_id="codex-thread-1",
        provider_session_kind="codex_app_server_thread",
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
            payload={
                "decision_scope": "blueprint.freeze",
                "vote": "approve",
            },
        ),
    )

    artifact = export_natural_deliberation_transcript_artifact(
        chat_db_path=db,
        registry_path=tmp_path / "god_sessions.json",
        conversation_id=conversation.id,
        output_path=tmp_path / "natural-transcript.json",
    )

    assert artifact["proof_level"] == "manual_gap"
    assert artifact["natural_deliberation"] is True
    assert artifact["fact_state"] == "blocked"
    assert artifact["blockers"] == [
        {
            "reason": "provider_session_metadata_missing",
            "source_refs": ["chat:message:speech-2", "god:review-god"],
        }
    ]


def test_natural_transcript_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-natural-deliberation-transcript-capture"]
        == "xmuse.natural_deliberation_transcript_capture:main"
    )
