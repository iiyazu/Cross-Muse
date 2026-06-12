from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.agents.god_session_registry import GodSessionRegistry
from xmuse_core.platform.god_runtime_continuity_capture import (
    capture_selected_god_runtime_continuity_artifact,
)
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionStore


def _seed_selected_god_runtime(tmp_path: Path, *, heartbeat: str) -> tuple[Path, Path, Path]:
    selection_store = tmp_path / "god_cli_selections.json"
    session_registry = tmp_path / "god_sessions.json"
    registration_store = tmp_path / "god_cli_registrations.json"

    GodCliSelectionStore(selection_store).record_selection(
        conversation_id="conv-prod-1",
        cli_id="codex.god",
        selected_by="operator",
        audit_id="operator-action:select-1",
        idempotency_key="select:conv-prod-1:codex.god",
        selected_at_utc="2026-06-13T00:00:00Z",
    )
    registry = GodSessionRegistry(session_registry)
    session = registry.create(
        role="architect",
        agent_name="codex.god",
        runtime="codex",
        session_address="@architect",
        session_inbox_id="inbox-architect",
        conversation_id="conv-prod-1",
        participant_id="participant-architect",
        model="gpt-5.5",
        feature_scope_id="feature:vision-closure",
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
        heartbeat_at_utc=heartbeat,
        status="active",
    )
    return selection_store, registration_store, session_registry


def test_capture_selected_god_runtime_continuity_artifact_from_durable_stores(
    tmp_path: Path,
) -> None:
    selection_store, registration_store, session_registry = _seed_selected_god_runtime(
        tmp_path,
        heartbeat="2026-06-13T00:04:30Z",
    )
    output = tmp_path / "artifacts" / "god-runtime-continuity.json"

    artifact = capture_selected_god_runtime_continuity_artifact(
        conversation_id="conv-prod-1",
        selection_store_path=selection_store,
        registration_store_path=registration_store,
        registry_path=session_registry,
        output_path=output,
        now_utc="2026-06-13T00:05:00Z",
        heartbeat_ttl_seconds=120,
    )

    assert artifact == json.loads(output.read_text(encoding="utf-8"))
    assert artifact["schema_version"] == "xmuse.god_runtime_continuity.v1"
    assert artifact["conversation_id"] == "conv-prod-1"
    assert artifact["proof_level"] == "contract_proof"
    assert artifact["fact_state"] == "observed"
    assert artifact["blockers"] == []
    assert artifact["source_authority"] == [
        "god_cli_selection_store",
        "god_cli_registry",
        "god_session_registry",
    ]
    assert artifact["source_refs"] == [
        "god_cli_selection:conv-prod-1",
        "god_cli_registration:codex.god",
        artifact["items"][0]["source_refs"][2],
        "provider_session:codex-thread-1",
        artifact["items"][0]["source_refs"][4],
    ]
    assert artifact["items"][0]["peer_god_ready"] is True
    assert artifact["items"][0]["heartbeat_freshness"] == "fresh"
    assert artifact["items"][0]["last_heartbeat_at_utc"] == "2026-06-13T00:04:30Z"


def test_capture_selected_god_runtime_continuity_blocks_stale_heartbeat(
    tmp_path: Path,
) -> None:
    selection_store, registration_store, session_registry = _seed_selected_god_runtime(
        tmp_path,
        heartbeat="2026-06-13T00:00:00Z",
    )

    artifact = capture_selected_god_runtime_continuity_artifact(
        conversation_id="conv-prod-1",
        selection_store_path=selection_store,
        registration_store_path=registration_store,
        registry_path=session_registry,
        output_path=tmp_path / "god-runtime-continuity.json",
        now_utc="2026-06-13T00:10:00Z",
        heartbeat_ttl_seconds=300,
    )

    assert artifact["proof_level"] == "manual_gap"
    assert artifact["fact_state"] == "blocked"
    assert artifact["manual_gap_reason"] == "GOD session heartbeat stale"
    assert artifact["items"][0]["peer_god_ready"] is False
    assert artifact["items"][0]["heartbeat_freshness"] == "stale"


def test_capture_selected_god_runtime_continuity_reports_missing_selection(
    tmp_path: Path,
) -> None:
    artifact = capture_selected_god_runtime_continuity_artifact(
        conversation_id="conv-missing",
        selection_store_path=tmp_path / "god_cli_selections.json",
        registration_store_path=tmp_path / "god_cli_registrations.json",
        registry_path=tmp_path / "god_sessions.json",
        output_path=tmp_path / "god-runtime-continuity.json",
        now_utc="2026-06-13T00:10:00Z",
    )

    assert artifact["proof_level"] == "manual_gap"
    assert artifact["fact_state"] == "manual_gap"
    assert artifact["manual_gap_reason"] == "selected GOD CLI unavailable"
    assert artifact["blockers"] == [
        {
            "reason": "selected GOD CLI unavailable",
            "source_refs": ["conversation:conv-missing"],
        }
    ]


def test_god_runtime_continuity_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-god-runtime-continuity-capture"]
        == "xmuse.god_runtime_continuity_capture:main"
    )

    script = Path("xmuse/god_runtime_continuity_capture.py").read_text(encoding="utf-8")
    assert "--conversation-id" in script
    assert "--selection-store" in script
    assert "--registration-store" in script
    assert "--registry" in script
    assert "--heartbeat-ttl-seconds" in script
