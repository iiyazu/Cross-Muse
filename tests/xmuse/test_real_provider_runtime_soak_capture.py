from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import PeerTurnLatencyTraceStore
from xmuse_core.platform.real_provider_runtime_release_gate import (
    build_real_provider_runtime_release_gate,
)
from xmuse_core.platform.real_provider_runtime_soak_capture import (
    export_real_provider_runtime_soak_artifact,
)


def _stage_timings(offset: float) -> dict[str, dict[str, float]]:
    return {
        "ray_actor_delivery_start": {"at": offset + 1.0},
        "codex_app_server_turn_start": {"at": offset + 2.0},
        "chat_post_message": {"at": offset + 3.0},
        "trace_persisted": {"at": offset + 4.0},
    }


def _seed_runtime_soak(
    tmp_path: Path,
    *,
    resume_delivery_mode: str = "mcp_writeback",
    resume_degraded_reason: str | None = None,
) -> tuple[Path, str, str, str]:
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conversation = chat.create_conversation("Provider runtime soak")
    architect = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="Architect GOD",
        cli_kind="codex",
        model="gpt-5.5",
    )
    registry = GodSessionRegistry(tmp_path / "god_sessions.json")
    session = registry.create(
        role="architect",
        agent_name="architect-god",
        runtime="codex",
        session_address="@architect",
        session_inbox_id="inbox-architect",
        conversation_id=conversation.id,
        participant_id=architect.participant_id,
        model="gpt-5.5",
    )
    registry.update_provider_binding(
        session.god_session_id,
        provider_session_id="codex-thread-1",
        provider_session_kind="codex_app_server_thread",
        provider_binding_status="active",
        provider_binding_failure_reason=None,
    )
    traces = PeerTurnLatencyTraceStore(db)
    traces.record(
        conversation_id=conversation.id,
        inbox_item_id="inbox-fresh",
        participant_id=architect.participant_id,
        target_role="architect",
        message_created_at="2026-06-12T00:00:00Z",
        inbox_claimed_at="2026-06-12T00:00:01Z",
        delivery_started_at=1.0,
        provider_turn_started_at=2.0,
        first_delta_at=None,
        writeback_at=4.0,
        total_latency_ms=3000,
        delivery_mode="mcp_writeback",
        degraded_reason=None,
        stage_timings=_stage_timings(0.0),
    )
    traces.record(
        conversation_id=conversation.id,
        inbox_item_id="inbox-resume",
        participant_id=architect.participant_id,
        target_role="architect",
        message_created_at="2026-06-12T00:10:00Z",
        inbox_claimed_at="2026-06-12T00:10:01Z",
        delivery_started_at=11.0,
        provider_turn_started_at=12.0,
        first_delta_at=None,
        writeback_at=14.0,
        total_latency_ms=3000,
        delivery_mode=resume_delivery_mode,
        degraded_reason=resume_degraded_reason,
        stage_timings=_stage_timings(10.0),
    )
    return db, tmp_path / "god_sessions.json", conversation.id, session.god_session_id


def test_real_provider_runtime_soak_export_accepts_fresh_resume_mcp_writeback(
    tmp_path: Path,
) -> None:
    db, registry_path, conversation_id, god_session_id = _seed_runtime_soak(tmp_path)

    output = tmp_path / "real-provider-runtime.json"
    artifact = export_real_provider_runtime_soak_artifact(
        chat_db_path=db,
        registry_path=registry_path,
        conversation_id=conversation_id,
        fresh_inbox_item_id="inbox-fresh",
        resume_inbox_item_id="inbox-resume",
        runtime_backend="ray",
        transport="codex-app-server",
        output_path=output,
        run_id="real-soak-pr43-d208877",
    )

    assert artifact == json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "xmuse.real_provider_runtime.v1"
    assert artifact["proof_level"] == "real_provider_proof"
    assert artifact["fact_state"] == "observed"
    assert artifact["run_id"] == "real-soak-pr43-d208877"
    assert artifact["conversation_id"] == conversation_id
    assert artifact["source_refs"] == [
        f"chat:conversation:{conversation_id}",
        f"god_session:{god_session_id}",
        "peer_latency:inbox-fresh",
        "peer_latency:inbox-resume",
    ]
    assert artifact["provider_runtime"] == {
        "provider_id": "codex",
        "runtime_backend": "ray",
        "transport": "codex-app-server",
        "provider_session_id": "codex-thread-1",
        "mcp_writeback": True,
    }
    assert artifact["restart_resume"] == {
        "fresh_provider_session_id": "codex-thread-1",
        "resumed_provider_session_id": "codex-thread-1",
        "provider_session_reused": True,
    }
    assert [turn["phase"] for turn in artifact["turns"]] == ["fresh", "resume"]
    assert artifact["blockers"] == []

    gate = build_real_provider_runtime_release_gate(artifact, artifact_path=output)
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "real_provider_proof"


def test_real_provider_runtime_soak_export_blocks_stdout_fallback(
    tmp_path: Path,
) -> None:
    db, registry_path, conversation_id, _god_session_id = _seed_runtime_soak(
        tmp_path,
        resume_delivery_mode="stdout_fallback",
        resume_degraded_reason="stdout_fallback",
    )

    artifact = export_real_provider_runtime_soak_artifact(
        chat_db_path=db,
        registry_path=registry_path,
        conversation_id=conversation_id,
        fresh_inbox_item_id="inbox-fresh",
        resume_inbox_item_id="inbox-resume",
        runtime_backend="ray",
        transport="codex-app-server",
        output_path=tmp_path / "real-provider-runtime.json",
    )

    assert artifact["proof_level"] == "manual_gap"
    assert artifact["fact_state"] == "blocked"
    assert artifact["provider_runtime"]["mcp_writeback"] is False
    assert artifact["blockers"] == [
        {
            "reason": "provider_turn_not_mcp_writeback",
            "source_refs": ["peer_latency:inbox-resume"],
        },
        {
            "reason": "provider_turn_degraded",
            "source_refs": ["peer_latency:inbox-resume"],
        },
    ]


def test_real_provider_runtime_soak_export_rejects_fake_or_local_runtime_labels(
    tmp_path: Path,
) -> None:
    db, registry_path, conversation_id, _god_session_id = _seed_runtime_soak(tmp_path)

    artifact = export_real_provider_runtime_soak_artifact(
        chat_db_path=db,
        registry_path=registry_path,
        conversation_id=conversation_id,
        fresh_inbox_item_id="inbox-fresh",
        resume_inbox_item_id="inbox-resume",
        runtime_backend="local-ray",
        transport="stdout-fallback",
        output_path=tmp_path / "real-provider-runtime.json",
    )

    assert artifact["proof_level"] == "manual_gap"
    assert artifact["provider_runtime"]["runtime_backend"] == "local-ray"
    assert artifact["provider_runtime"]["transport"] == "stdout-fallback"
    assert artifact["blockers"] == [
        {
            "reason": "fake_or_local_runtime_label",
            "source_refs": [f"conversation:{conversation_id}"],
        }
    ]


def test_real_provider_runtime_soak_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-real-provider-runtime-soak-capture"]
        == "xmuse.real_provider_runtime_soak_capture:main"
    )
