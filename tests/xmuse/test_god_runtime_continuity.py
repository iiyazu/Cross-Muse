from __future__ import annotations

from xmuse_core.agents.god_session_registry import GodSessionRecord
from xmuse_core.platform.god_runtime_continuity import (
    build_selected_god_runtime_continuity_view,
)
from xmuse_core.platform.tui_vision_read_model import build_tui_vision_read_model
from xmuse_core.providers.god_cli_registry import build_default_god_cli_registry
from xmuse_core.providers.god_cli_selection_store import GodCliSelectionRecord


def _selection(cli_id: str) -> GodCliSelectionRecord:
    return GodCliSelectionRecord(
        conversation_id="conv-1",
        cli_id=cli_id,
        selected_by="operator",
        audit_id="audit-select-1",
        idempotency_key=f"select:{cli_id}",
        selected_at_utc="2026-06-13T00:00:00Z",
    )


def _session(
    *,
    agent_name: str,
    runtime: str,
    provider_session_id: str | None = "provider-thread-1",
    provider_binding_status: str | None = "active",
    last_heartbeat_at_utc: str | None = None,
) -> GodSessionRecord:
    return GodSessionRecord(
        god_session_id="god-session-1",
        role="architect",
        agent_name=agent_name,
        runtime=runtime,
        session_address="@architect",
        session_inbox_id="inbox-architect",
        conversation_id="conv-1",
        participant_id="participant-architect",
        status="active",
        model="production-model",
        feature_scope_id="feature:lane-a",
        provider_session_id=provider_session_id,
        provider_session_kind="provider_thread",
        provider_binding_status=provider_binding_status,
        provider_binding_failure_reason=None,
        last_heartbeat_at_utc=last_heartbeat_at_utc,
    )


def test_selected_god_runtime_view_joins_selection_registration_and_session() -> None:
    view = build_selected_god_runtime_continuity_view(
        conversation_id="conv-1",
        selections=[_selection("codex.god")],
        sessions=[_session(agent_name="codex.god", runtime="codex")],
        god_cli_registry=build_default_god_cli_registry(),
    )

    assert view["schema_version"] == "xmuse.god_runtime_continuity.v1"
    assert view["read_only"] is True
    assert view["proof_level"] == "contract_proof"
    assert view["fact_state"] == "observed"
    assert view["blockers"] == []
    assert view["source_refs"] == [
        "god_cli_selection:conv-1",
        "god_cli_registration:codex.god",
        "god_session:god-session-1",
        "provider_session:provider-thread-1",
    ]
    assert view["items"] == [
        {
            "god_id": "codex.god",
            "cli_id": "codex.god",
            "selected": True,
            "role": "architect",
            "participant_id": "participant-architect",
            "provider_profile_ref": "codex.god",
            "provider_session_id": "provider-thread-1",
            "provider_session_kind": "provider_thread",
            "provider_binding_status": "active",
            "capability_scope": [
                "peer_god",
                "bounded_deliberation",
                "lane_coordination",
                "planning",
                "takeover",
            ],
            "allowed_speech_acts": [
                "propose",
                "ask",
                "challenge",
                "object",
                "vote",
                "decide",
                "handoff",
                "evidence",
                "retract",
            ],
            "session_status": "active",
            "heartbeat_freshness": "unknown",
            "last_heartbeat_at_utc": None,
            "waiting_reason": None,
            "proof_level": "contract_proof",
            "bounded": False,
            "peer_god_ready": True,
            "provider_session_ready": True,
            "model": "production-model",
            "feature_scope_id": "feature:lane-a",
            "source_refs": [
                "god_cli_selection:conv-1",
                "god_cli_registration:codex.god",
                "god_session:god-session-1",
                "provider_session:provider-thread-1",
            ],
            "selection": {
                "selected_by": "operator",
                "audit_id": "audit-select-1",
                "selected_at_utc": "2026-06-13T00:00:00Z",
                "proof_level": "contract_proof",
            },
        }
    ]


def test_opencode_runtime_view_stays_bounded_without_peer_god_prerequisites() -> None:
    view = build_selected_god_runtime_continuity_view(
        conversation_id="conv-1",
        selections=[_selection("opencode.deepseek_flash_worker")],
        sessions=[
            _session(
                agent_name="opencode.deepseek_flash_worker",
                runtime="opencode",
                provider_session_id="opencode-session-1",
            )
        ],
        god_cli_registry=build_default_god_cli_registry(),
    )

    assert view["proof_level"] == "contract_proof"
    assert view["fact_state"] == "blocked"
    assert view["blockers"] == [
        {
            "reason": "selected CLI lacks peer_god capability",
            "source_refs": [
                "god_cli_selection:conv-1",
                "god_cli_registration:opencode.deepseek_flash_worker",
                "god_session:god-session-1",
                "provider_session:opencode-session-1",
            ],
        }
    ]
    item = view["items"][0]
    assert item["cli_id"] == "opencode.deepseek_flash_worker"
    assert item["bounded"] is True
    assert item["peer_god_ready"] is False
    assert item["provider_session_ready"] is True
    assert item["waiting_reason"] == "selected CLI lacks peer_god capability"
    assert item["proof_level"] == "contract_proof"


def test_runtime_view_reports_manual_gap_without_provider_session_metadata() -> None:
    view = build_selected_god_runtime_continuity_view(
        conversation_id="conv-1",
        selections=[_selection("codex.god")],
        sessions=[
            _session(
                agent_name="codex.god",
                runtime="codex",
                provider_session_id=None,
                provider_binding_status=None,
            )
        ],
        god_cli_registry=build_default_god_cli_registry(),
    )

    assert view["proof_level"] == "manual_gap"
    assert view["fact_state"] == "blocked"
    assert view["manual_gap_reason"] == "provider session metadata unavailable"
    assert view["blockers"] == [
        {
            "reason": "provider session metadata unavailable",
            "source_refs": [
                "god_cli_selection:conv-1",
                "god_cli_registration:codex.god",
                "god_session:god-session-1",
            ],
        }
    ]
    item = view["items"][0]
    assert item["peer_god_ready"] is False
    assert item["provider_session_ready"] is False
    assert item["waiting_reason"] == "provider session metadata unavailable"
    assert item["proof_level"] == "manual_gap"


def test_runtime_view_reports_fresh_heartbeat_when_within_ttl() -> None:
    view = build_selected_god_runtime_continuity_view(
        conversation_id="conv-1",
        selections=[_selection("codex.god")],
        sessions=[
            _session(
                agent_name="codex.god",
                runtime="codex",
                last_heartbeat_at_utc="2026-06-13T00:04:30Z",
            )
        ],
        god_cli_registry=build_default_god_cli_registry(),
        now_utc="2026-06-13T00:05:00Z",
        heartbeat_ttl_seconds=120,
    )

    assert view["proof_level"] == "contract_proof"
    assert view["fact_state"] == "observed"
    assert view["blockers"] == []
    item = view["items"][0]
    assert item["heartbeat_freshness"] == "fresh"
    assert item["last_heartbeat_at_utc"] == "2026-06-13T00:04:30Z"
    assert item["peer_god_ready"] is True
    assert "god_session_heartbeat:god-session-1" in item["source_refs"]


def test_runtime_view_blocks_stale_heartbeat_without_upgrading_proof() -> None:
    view = build_selected_god_runtime_continuity_view(
        conversation_id="conv-1",
        selections=[_selection("codex.god")],
        sessions=[
            _session(
                agent_name="codex.god",
                runtime="codex",
                last_heartbeat_at_utc="2026-06-13T00:00:00Z",
            )
        ],
        god_cli_registry=build_default_god_cli_registry(),
        now_utc="2026-06-13T00:10:00Z",
        heartbeat_ttl_seconds=300,
    )

    assert view["proof_level"] == "manual_gap"
    assert view["fact_state"] == "blocked"
    assert view["manual_gap_reason"] == "GOD session heartbeat stale"
    assert view["blockers"] == [
        {
            "reason": "GOD session heartbeat stale",
            "source_refs": [
                "god_cli_selection:conv-1",
                "god_cli_registration:codex.god",
                "god_session:god-session-1",
                "provider_session:provider-thread-1",
                "god_session_heartbeat:god-session-1",
            ],
        }
    ]
    item = view["items"][0]
    assert item["heartbeat_freshness"] == "stale"
    assert item["waiting_reason"] == "GOD session heartbeat stale"
    assert item["peer_god_ready"] is False
    assert item["proof_level"] == "manual_gap"


def test_tui_vision_read_model_projects_god_runtime_without_authority_upgrade() -> None:
    runtime = build_selected_god_runtime_continuity_view(
        conversation_id="conv-1",
        selections=[_selection("codex.god")],
        sessions=[_session(agent_name="codex.god", runtime="codex")],
        god_cli_registry=build_default_god_cli_registry(),
    )

    model = build_tui_vision_read_model(
        conversation_id="conv-1",
        god_runtime=runtime,
    )

    assert model["god_runtime"]["proof_level"] == "contract_proof"
    assert model["god_runtime"]["fact_state"] == "observed"
    assert model["god_runtime"]["read_only"] is True
    assert model["god_runtime"]["items"] == [
        {
            "god_id": "codex.god",
            "cli_id": "codex.god",
            "provider_profile_ref": "codex.god",
            "provider_session_id": "provider-thread-1",
            "capability_scope": [
                "peer_god",
                "bounded_deliberation",
                "lane_coordination",
                "planning",
                "takeover",
            ],
            "session_status": "active",
            "heartbeat_freshness": "unknown",
            "waiting_reason": None,
            "proof_level": "contract_proof",
            "bounded": False,
            "peer_god_ready": True,
            "provider_session_ready": True,
        }
    ]
