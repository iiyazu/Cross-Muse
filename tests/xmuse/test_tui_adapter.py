"""Tests for XmuseAdapter using fixture data."""
from pathlib import Path

import pytest

import xmuse_core.platform.read_envelopes as read_envelopes
from xmuse.tui.adapter.xmuse_adapter import (
    XmuseAdapter,
    _build_features,
    _build_health,
    _inbox_status_cards,
    _merge_runtime_health,
    _peer_latency_cards,
    _runtime_closure_cards,
    _runtime_health_from_inspector,
)
from xmuse_core.chat.inbox_store import ChatInboxStore
from xmuse_core.chat.participant_store import ParticipantStore, RoleTemplateStore
from xmuse_core.chat.store import ChatStore
from xmuse_core.chat.stream_store import ChatStreamStore, PeerTurnLatencyTraceStore
from xmuse_core.providers.god_cli_registration_store import GodCliRegistrationStore
from xmuse_core.providers.god_cli_registry import GodCliCapability, GodCliRegistration

ROOT = Path(__file__).resolve().parents[2] / "xmuse"


def _manual_god_cli_registration_payload() -> dict[str, object]:
    return {
        "cli_id": "custom.peer",
        "display_name": "Custom Peer",
        "command_family": "custom-cli",
        "provider_profile_ref": "custom.peer",
        "capabilities": ["peer_god"],
        "supports_persistent_sessions": True,
        "supports_mcp_writeback": True,
        "state_write_allowed": True,
        "proof_level": "real_provider_proof",
        "proof_refs": ["provider-run://custom.peer/live-smoke-1"],
    }


def test_build_features_empty():
    assert _build_features([]) == {}


def test_build_features_single():
    lanes = [{"feature_plan_feature_id": "C1", "status": "merged"}]
    result = _build_features(lanes)
    assert result["C1"]["total"] == 1
    assert result["C1"]["merged"] == 1


def test_build_features_missing_id():
    lanes = [{"feature_group": "C1", "status": "merged"}, {"status": None}]
    result = _build_features(lanes)
    assert "?" in result


def test_build_features_uses_plan_feature_id_for_compact_items():
    lanes = [{"plan_feature_id": "T1", "status": "merged"}]
    result = _build_features(lanes)
    assert result["T1"]["total"] == 1
    assert result["T1"]["merged"] == 1


def test_build_health_empty():
    h = _build_health([])
    assert h == {"live": 0, "merged": 0, "failed": 0, "total": 0}


def test_build_health_counts():
    lanes = [
        {"status": "merged"},
        {"status": "dispatched"},
        {"status": "failed"},
        {"status": "gated"},
    ]
    h = _build_health(lanes)
    assert h["live"] == 2
    assert h["merged"] == 1
    assert h["failed"] == 1
    assert h["total"] == 4


def test_build_health_null_status():
    lanes = [{"status": "merged"}, {"status": None}, {}, {"status": "dispatched"}]
    h = _build_health(lanes)
    assert h["merged"] == 1
    assert h["live"] == 1
    assert h["total"] == 4


def test_runtime_health_from_inspector_counts_provider_sessions():
    health = _runtime_health_from_inspector(
        {
            "session_health": {
                "items": [
                    {
                        "status": "starting",
                        "provider_session_id": "thread-architect",
                        "provider_binding_status": "active",
                    },
                    {
                        "status": "starting",
                        "provider_session_id": None,
                        "provider_binding_status": None,
                    },
                    {
                        "status": "stopped",
                        "provider_session_id": None,
                        "provider_binding_status": None,
                    },
                    {
                        "status": "starting",
                        "provider_session_id": "thread-review",
                        "provider_binding_status": "failed",
                    },
                ]
            }
        }
    )

    assert health == {
        "counts": {
            "live": 1,
            "stale": 1,
            "failed": 1,
            "degraded_fallback": 0,
        },
        "source": "chat_inspector.session_health",
    }


def test_merge_runtime_health_uses_inspector_live_when_worklist_has_none():
    merged = _merge_runtime_health(
        {"counts": {"live": 0, "stale": 0, "failed": 0, "degraded_fallback": 0}},
        {"counts": {"live": 3, "stale": 0, "failed": 0}, "source": "chat_inspector"},
    )

    assert merged["counts"]["live"] == 3
    assert merged["source"] == "chat_inspector"


def test_adapter_group_conversations_require_default_god_participants(tmp_path):
    root = tmp_path
    db = root / "chat.db"
    chat = ChatStore(db)
    roles = RoleTemplateStore(db)
    participants = ParticipantStore(db)
    archived = chat.create_conversation("xmuse self-evolution: reliability")
    partial = chat.create_conversation("A-xmuse reliability feature graph wave")
    group = chat.create_conversation("User mission")

    review_template = roles.get_by_slug("review")
    architect_template = roles.get_by_slug("architect")
    execute_template = roles.get_by_slug("execute")
    assert review_template and architect_template and execute_template

    participants.add(
        conversation_id=partial.id,
        role="review",
        display_name="Review GOD",
        cli_kind="codex",
        model="gpt-5.4",
        role_template_id=review_template.id,
    )
    for role, template in [
        ("architect", architect_template),
        ("review", review_template),
        ("execute", execute_template),
    ]:
        participants.add(
            conversation_id=group.id,
            role=role,
            display_name=f"{role}-god",
            cli_kind="codex",
            model="gpt-5.4",
            role_template_id=template.id,
        )

    adapter = XmuseAdapter(root)

    groups = adapter.list_group_conversations()
    archived_rows = adapter.list_archived_conversations()

    assert [item["id"] for item in groups] == [group.id]
    assert {item["id"] for item in archived_rows} == {archived.id, partial.id}


def test_adapter_send_message_posts_human_message_to_chat_api(monkeypatch, tmp_path):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id": "msg-api-1"}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-tui")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "chat_post_message")
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    message_id = adapter.send_message("conv-1", "user", "user", "please improve TUI")

    assert message_id == "msg-api-1"
    assert calls == [
        {
            "url": "http://chat-api/api/chat/conversations/conv-1/messages",
            "json": {
                "author": "user",
                "role": "human",
                "content": "@architect please improve TUI",
            },
            "headers": {
                "X-XMUSE-API-Key": "secret",
                "X-XMuse-Operator-Id": "operator-tui",
                "X-XMuse-Operator-Role": "operator",
                "X-XMuse-Operator-Capabilities": "chat_post_message",
            },
        }
    ]


def test_adapter_poll_messages_adds_display_author_for_participant_ids(tmp_path):
    root = tmp_path
    db = root / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conversation = chat.create_conversation("Mission")
    participant = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="architect-god",
        cli_kind="codex",
        model="gpt-5.4",
        role_template_id=None,
    )
    chat.add_message(
        conversation.id,
        author=participant.participant_id,
        role="assistant",
        content="在。",
    )

    messages, error = XmuseAdapter(root).poll_messages(conversation.id)

    assert error is None
    assert messages[0]["author"] == participant.participant_id
    assert messages[0]["display_author"] == "architect-god"


def test_adapter_poll_messages_includes_active_stream_state(tmp_path):
    root = tmp_path
    db = root / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conversation = chat.create_conversation("Mission")
    participant = participants.add(
        conversation_id=conversation.id,
        role="architect",
        display_name="architect-god",
        cli_kind="codex",
        model="gpt-5.4",
        role_template_id=None,
    )
    stream = ChatStreamStore(db).start_or_reset(
        conversation_id=conversation.id,
        author=participant.participant_id,
        role="assistant",
        request_id="inbox-stream-1",
        source_inbox_item_id="inbox-stream-1",
    )
    ChatStreamStore(db).append_delta(stream.id, "Drafting...")

    messages, error = XmuseAdapter(root).poll_messages(conversation.id)

    assert error is None
    stream_message = next(message for message in messages if message["id"] == stream.id)
    assert stream_message["envelope_type"] == "stream"
    assert stream_message["envelope_json"]["status"] == "active"
    assert stream_message["envelope_json"]["source_inbox_item_id"] == "inbox-stream-1"
    assert stream_message["content"] == "Drafting..."


def test_adapter_operator_evidence_action_exports_transcript_artifact(tmp_path):
    root = tmp_path
    chat = ChatStore(root / "chat.db")
    conversation = chat.create_conversation("Mission")
    chat.add_message(
        conversation.id,
        author="architect",
        role="assistant",
        content="Freeze the blueprint.",
        envelope_json={
            "speech_act": "decide",
            "god_id": "architect-god",
            "provider_id": "codex",
            "decision_scope": "blueprint.freeze",
            "target_ref": "blueprint:conv-1:1",
        },
    )

    result = XmuseAdapter(root).run_operator_evidence_action(
        "transcript",
        conversation.id,
    )

    assert result["action"] == "transcript_export"
    assert result["status"] == "ok"
    assert result["proof_level"] == "contract_proof"
    assert result["artifact_path"]
    artifact_path = Path(result["artifact_path"])
    assert artifact_path.exists()
    assert root / "work" / "operator_evidence" in artifact_path.parents


def test_adapter_operator_evidence_action_loads_github_memory_and_blockers(
    monkeypatch,
    tmp_path,
):
    adapter = XmuseAdapter(tmp_path)
    monkeypatch.setattr(adapter, "_message_snapshot", lambda conv_id: [])
    monkeypatch.setattr(adapter, "_worklist_envelope_snapshot", lambda conv_id: {})
    monkeypatch.setattr(
        adapter,
        "get_conversation_inspector",
        lambda conv_id: {
            "memory_trace": {
                "proof_level": "live_service_proof",
                "fact_state": "observed",
                "session_id": "mem-session-1",
                "source_refs": ["memory://conversation/conv-1/session/mem-session-1"],
            },
            "github_truth": {
                "proof_level": "server_side_enforcement_proof",
                "fact_state": "merge_ready",
                "source_refs": ["github://repo/pull/42"],
            },
            "blueprint_freeze": {
                "proof_level": "contract_proof",
                "fact_state": "blocked",
                "blockers": [
                    {
                        "reason": "needs review evidence",
                        "source_refs": ["message:msg-review"],
                        "target_refs": ["blueprint:conv-1:1"],
                    }
                ],
            },
        },
    )

    github = adapter.run_operator_evidence_action("github", "conv-1")
    memory = adapter.run_operator_evidence_action("memory", "conv-1")
    blockers = adapter.run_operator_evidence_action("blockers", "conv-1")

    assert github["action"] == "github_truth_load"
    assert github["status"] == "ok"
    assert github["proof_level"] == "server_side_enforcement_proof"
    assert memory["action"] == "memory_trace_load"
    assert memory["proof_level"] == "live_service_proof"
    assert blockers["action"] == "blocker_navigation"
    assert blockers["target_refs"] == ["blueprint:conv-1:1"]


def test_adapter_operator_control_action_selects_god_cli_with_capability(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "select_god_cli")

    result = XmuseAdapter(tmp_path).run_operator_control_action(
        "select_god_cli",
        "conv-1",
        {"cli_id": "codex.god"},
    )

    assert result["action"] == "select_god_cli"
    assert result["status"] == "ok"
    assert result["fact_state"] == "god_cli_selected"
    assert result["payload"]["selection"]["cli_id"] == "codex.god"
    assert result["payload"]["selection"]["conversation_id"] == "conv-1"


def test_adapter_operator_control_action_prefers_chat_api_contract(
    monkeypatch,
    tmp_path,
):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "action": "select_god_cli",
                "status": "ok",
                "proof_level": "contract_proof",
                "fact_state": "god_cli_selected",
                "actor_id": "operator-api",
                "audit_id": "operator-action:api",
                "summary": "Selected GOD CLI codex.god.",
                "payload": {
                    "selection": {
                        "cli_id": "codex.god",
                        "conversation_id": "conv-1",
                        "durable_state_ref": "god_cli_selection:conv-1",
                    }
                },
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-api")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "select_god_cli")
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)

    result = XmuseAdapter(
        tmp_path,
        chat_api_base_url="http://chat-api",
    ).run_operator_control_action(
        "select-god-cli",
        "conv-1",
        {"cli_id": "codex.god"},
    )

    assert result["audit_id"] == "operator-action:api"
    assert len(calls) == 1
    assert calls[0]["url"] == "http://chat-api/api/chat/operator/actions"
    assert calls[0]["json"]["action"] == "select_god_cli"
    assert calls[0]["json"]["idempotency_key"].startswith("tui:select_god_cli:")
    assert calls[0]["json"]["payload"] == {
        "cli_id": "codex.god",
        "conversation_id": "conv-1",
    }
    assert calls[0]["headers"] == {
        "X-XMUSE-API-Key": "secret",
        "X-XMuse-Operator-Id": "operator-api",
        "X-XMuse-Operator-Role": "operator",
        "X-XMuse-Operator-Capabilities": "select_god_cli",
    }


def test_adapter_operator_control_action_does_not_fallback_after_api_rejection(
    monkeypatch,
    tmp_path,
):
    class _Response:
        status_code = 404

        def raise_for_status(self):
            raise RuntimeError("api rejected request")

        def json(self):
            return {
                "detail": {
                    "code": "unknown_conversation",
                    "message": "conversation not found",
                }
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers):
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "select_god_cli")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)

    result = XmuseAdapter(
        tmp_path,
        chat_api_base_url="http://chat-api",
    ).run_operator_control_action(
        "select_god_cli",
        "missing-conv",
        {"cli_id": "codex.god"},
    )

    assert result["status"] == "blocked"
    assert result["fact_state"] == "blocked"
    assert result["payload"]["api_status_code"] == 404
    assert not (tmp_path / "god_cli_selections.json").exists()


def test_adapter_operator_control_action_denies_without_capability(tmp_path):
    result = XmuseAdapter(tmp_path).run_operator_control_action(
        "select_god_cli",
        "conv-1",
        {"cli_id": "codex.god"},
    )

    assert result["status"] == "denied"
    assert "missing capability select_god_cli" in result["summary"]


def test_adapter_operator_control_action_registers_god_cli_locally(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv(
        "XMUSE_TUI_OPERATOR_CAPABILITIES",
        "register_god_cli,select_god_cli",
    )
    adapter = XmuseAdapter(tmp_path)

    register_result = adapter.run_operator_control_action(
        "register_god_cli",
        "conv-1",
        _manual_god_cli_registration_payload(),
    )
    select_result = adapter.run_operator_control_action(
        "select_god_cli",
        "conv-1",
        {"cli_id": "custom.peer"},
    )

    assert register_result["action"] == "register_god_cli"
    assert register_result["status"] == "ok"
    assert register_result["payload"]["registration"]["cli_id"] == "custom.peer"
    assert select_result["status"] == "ok"
    assert select_result["payload"]["selection"]["cli_id"] == "custom.peer"
    stored = GodCliRegistrationStore(tmp_path / "god_cli_registrations.json").get(
        "custom.peer"
    )
    assert stored is not None
    assert stored.registration.proof_refs == ("provider-run://custom.peer/live-smoke-1",)


def test_adapter_operator_control_action_exports_natural_release_evidence_locally(
    monkeypatch,
    tmp_path,
):
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "release_gate")
    conversation = ChatStore(tmp_path / "chat.db").create_conversation(
        "Natural export",
    )

    result = XmuseAdapter(tmp_path).run_operator_control_action(
        "export_natural_deliberation_transcript",
        conversation.id,
        {"target_refs": ["blueprint:bp-1"]},
    )

    assert result["status"] == "ok"
    assert result["fact_state"] == "release_evidence_exported"
    exported = result["payload"]["export"]
    assert exported["kind"] == "natural_deliberation"
    assert exported["gate"]["gate_id"] == "natural-god-deliberation"
    assert (tmp_path / "work" / "release_readiness" / "natural-transcript.json").exists()
    assert (
        tmp_path / "work" / "release_readiness" / "artifacts" / "natural-deliberation.json"
    ).exists()


def test_adapter_records_operator_action_tui_command_event(tmp_path):
    adapter = XmuseAdapter(tmp_path)

    recorded = adapter.record_tui_command_event(
        {
            "command": "/god select codex.god",
            "conversation_id": "conv-1",
            "read_surface_authority": "operator_action_contract",
            "surface_ref": "operator_action_contract:conv-1",
        }
    )

    assert recorded is not None
    assert recorded["read_surface_authority"] == "operator_action_contract"
    assert adapter.list_tui_command_events("conv-1") == [recorded]


def test_adapter_create_group_conversation_uses_chat_api(monkeypatch, tmp_path):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "id": "conv-new",
                "title": "New mission",
                "participants": [
                    {"role": "architect"},
                    {"role": "review"},
                    {"role": "execute"},
                ],
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-tui")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "chat_create_conversation")
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    conversation = adapter.create_group_conversation("New mission")

    assert conversation["id"] == "conv-new"
    assert calls == [
        {
            "url": "http://chat-api/api/chat/conversations",
            "json": {
                "title": "New mission",
                "preset_id": "architect-review-execute",
                "init_mode": "proposal_then_approve",
            },
            "headers": {
                "X-XMUSE-API-Key": "secret",
                "X-XMuse-Operator-Id": "operator-tui",
                "X-XMuse-Operator-Role": "operator",
                "X-XMuse-Operator-Capabilities": "chat_create_conversation",
            },
        }
    ]


def test_adapter_get_bootstrap_status_uses_chat_api_endpoint(monkeypatch, tmp_path):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "conversation_id": "conv-draft",
                "status": "drafting",
                "draft_id": "bootstrap-draft:conv-draft",
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            calls.append({"method": "GET", "url": url})
            return _Response()

    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")
    adapter.list_group_conversations = lambda: pytest.fail("must not infer status from group list")

    status = adapter.get_bootstrap_status("conv-draft")

    assert status == {
        "conversation_id": "conv-draft",
        "status": "drafting",
        "draft_id": "bootstrap-draft:conv-draft",
    }
    assert calls == [
        {
            "method": "GET",
            "url": "http://chat-api/api/chat/conversations/conv-draft/bootstrap/status",
        }
    ]


def test_adapter_create_bootstrap_proposal_uses_chat_api_auth_headers(
    monkeypatch,
    tmp_path,
):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"proposal": {"proposal_id": "bootstrap-proposal:conv-1"}}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-tui")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "chat_bootstrap")
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    proposal = adapter.create_bootstrap_proposal("conv-1")

    assert proposal == {"proposal": {"proposal_id": "bootstrap-proposal:conv-1"}}
    assert calls == [
        {
            "url": (
                "http://chat-api/api/chat/conversations/conv-1/"
                "bootstrap/proposals"
            ),
            "json": {"source": "deterministic"},
            "headers": {
                "X-XMUSE-API-Key": "secret",
                "X-XMuse-Operator-Id": "operator-tui",
                "X-XMuse-Operator-Role": "operator",
                "X-XMuse-Operator-Capabilities": "chat_bootstrap",
            },
        }
    ]


def test_adapter_apply_bootstrap_proposal_uses_chat_api_auth_headers(
    monkeypatch,
    tmp_path,
):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"bootstrap": {"status": "applied"}}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-tui")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "chat_bootstrap")
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    applied = adapter.apply_bootstrap_proposal(
        "conv-1",
        "bootstrap-proposal:conv-1",
    )

    assert applied == {"bootstrap": {"status": "applied"}}
    assert calls == [
        {
            "url": "http://chat-api/api/chat/conversations/conv-1/bootstrap/apply",
            "json": {"proposal_id": "bootstrap-proposal:conv-1"},
            "headers": {
                "X-XMUSE-API-Key": "secret",
                "X-XMuse-Operator-Id": "operator-tui",
                "X-XMuse-Operator-Role": "operator",
                "X-XMuse-Operator-Capabilities": "chat_bootstrap",
            },
        }
    ]


def test_adapter_approve_proposal_uses_chat_api_endpoint(monkeypatch, tmp_path):
    calls = []

    class _Response:
        status_code = 200

        def json(self):
            return {"id": "res-1", "status": "approved"}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-tui")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ROLE", "operator")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_CAPABILITIES", "chat_approve_proposal")
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    result = adapter.approve_proposal(
        "proposal-1",
        approved_by="human",
        approval_mode="manual",
        goal_summary="Approve from TUI",
    )

    assert result == {"id": "res-1", "status": "approved"}
    assert calls == [
        {
            "url": "http://chat-api/api/chat/proposals/proposal-1/approve",
            "json": {
                "approved_by": ["human"],
                "approval_mode": "manual",
                "goal_summary": "Approve from TUI",
            },
            "headers": {
                "X-XMUSE-API-Key": "secret",
                "X-XMuse-Operator-Id": "operator-tui",
                "X-XMuse-Operator-Role": "operator",
                "X-XMuse-Operator-Capabilities": "chat_approve_proposal",
            },
        }
    ]


def test_adapter_get_conversation_inspector_uses_chat_api_endpoint(monkeypatch, tmp_path):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "conversation": {"id": "conv-1"},
                "collaboration": {"active_runs": 1, "runs": []},
                "blockers": {"active": 0, "items": []},
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            calls.append({"method": "GET", "url": url})
            return _Response()

    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    inspector = adapter.get_conversation_inspector("conv-1")

    assert inspector == {
        "conversation": {"id": "conv-1"},
        "collaboration": {"active_runs": 1, "runs": []},
        "blockers": {"active": 0, "items": []},
    }
    assert calls == [
        {
            "method": "GET",
            "url": "http://chat-api/api/chat/conversations/conv-1/inspector",
        }
    ]


def test_adapter_get_participants_prefers_chat_api(monkeypatch, tmp_path):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "participants": [
                    {
                        "participant_id": "part-architect",
                        "role": "architect",
                        "display_name": "architect-god",
                    }
                ]
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            calls.append({"method": "GET", "url": url})
            return _Response()

    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    participants = adapter.get_participants("conv-1")

    assert participants == [
        {
            "participant_id": "part-architect",
            "role": "architect",
            "display_name": "architect-god",
        }
    ]
    assert calls == [
        {
            "method": "GET",
            "url": "http://chat-api/api/chat/conversations/conv-1/participants",
        }
    ]


def test_adapter_add_participant_uses_chat_api(monkeypatch, tmp_path):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "participant_id": "part-execute",
                "role": "execute",
                "display_name": "Execution GOD",
            }

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def post(self, url, json, headers=None):
            calls.append({"url": url, "json": json, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-tui")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ROLE", "operator")
    monkeypatch.setenv(
        "XMUSE_TUI_OPERATOR_CAPABILITIES",
        "chat_manage_participants",
    )
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    participant = adapter.add_participant(
        "conv-1",
        "execute",
        display_name="Execution GOD",
        model="gpt-5.4",
    )

    assert participant["participant_id"] == "part-execute"
    assert calls == [
        {
            "url": "http://chat-api/api/chat/conversations/conv-1/participants",
            "json": {
                "role": "execute",
                "display_name": "Execution GOD",
                "model": "gpt-5.4",
            },
            "headers": {
                "X-XMUSE-API-Key": "secret",
                "X-XMuse-Operator-Id": "operator-tui",
                "X-XMuse-Operator-Role": "operator",
                "X-XMuse-Operator-Capabilities": "chat_manage_participants",
            },
        }
    ]


def test_adapter_remove_participant_resolves_unique_role_and_uses_chat_api(
    monkeypatch,
    tmp_path,
):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def delete(self, url, headers=None):
            calls.append({"method": "DELETE", "url": url, "headers": headers})
            return _Response()

    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ID", "operator-tui")
    monkeypatch.setenv("XMUSE_TUI_OPERATOR_ROLE", "operator")
    monkeypatch.setenv(
        "XMUSE_TUI_OPERATOR_CAPABILITIES",
        "chat_manage_participants",
    )
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "secret")
    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")
    adapter.get_participants = lambda conv_id: [
        {
            "participant_id": "part-execute",
            "role": "execute",
            "display_name": "execute-god",
        }
    ]

    assert adapter.remove_participant("conv-1", "execute") is True
    assert calls == [
        {
            "method": "DELETE",
            "url": (
                "http://chat-api/api/chat/conversations/conv-1/"
                "participants/part-execute"
            ),
            "headers": {
                "X-XMUSE-API-Key": "secret",
                "X-XMuse-Operator-Id": "operator-tui",
                "X-XMuse-Operator-Role": "operator",
                "X-XMuse-Operator-Capabilities": "chat_manage_participants",
            },
        }
    ]


def test_adapter_remove_participant_refuses_ambiguous_role(tmp_path):
    adapter = XmuseAdapter(tmp_path)
    adapter.get_participants = lambda conv_id: [
        {"participant_id": "part-review-1", "role": "review"},
        {"participant_id": "part-review-2", "role": "review"},
    ]

    assert adapter.remove_participant("conv-1", "review") is False


def test_adapter_list_role_templates_uses_chat_api(monkeypatch, tmp_path):
    calls = []

    class _Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"role_templates": [{"id": "tmpl-custom", "slug": "custom"}]}

    class _Client:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return None

        def get(self, url):
            calls.append({"method": "GET", "url": url})
            return _Response()

    monkeypatch.setattr("xmuse.tui.adapter.xmuse_adapter.httpx.Client", _Client)
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")

    assert adapter.list_role_templates() == [{"id": "tmpl-custom", "slug": "custom"}]
    assert calls == [
        {"method": "GET", "url": "http://chat-api/api/chat/role-templates"}
    ]


def test_adapter_builds_route_and_pending_cards_from_inbox(tmp_path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conv = chat.create_conversation("User mission")
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="architect-god",
        cli_kind="codex",
        model="gpt-5.4",
    )
    message = chat.add_message(conv.id, "user", "human", "@architect improve TUI")
    inbox = ChatInboxStore(db)
    item = inbox.create_item(
        conversation_id=conv.id,
        target_participant_id=architect.participant_id,
        target_role="architect",
        target_address="@architect",
        sender_participant_id=None,
        sender_address="@human",
        source_message_id=message.id,
        item_type="mention",
        payload={"content": message.content},
    )

    routed_cards = _inbox_status_cards(tmp_path, conv.id)

    assert routed_cards == [
        {
            "id": f"card_inbox_route_{item.id}",
            "conversation_id": conv.id,
            "card_type": "peer_route_status",
            "source_id": item.id,
            "title": "Routed to Architect GOD",
            "summary": "已路由给 Architect GOD，等待处理。",
            "status": "routed",
            "href": f"/dashboard/peer-chat/conversations/{conv.id}#inbox-{item.id}",
            "api_href": f"/api/chat/conversations/{conv.id}/messages",
            "created_at": item.updated_at,
            "counts": {"nudge_count": 0},
            "metadata": {
                "target_role": "architect",
                "target_participant_id": architect.participant_id,
                "source_message_id": message.id,
            },
        }
    ]

    claimed = inbox.claim_next(owner="sched-test", claim_ttl_s=30)
    assert claimed is not None
    pending_cards = _inbox_status_cards(tmp_path, conv.id)

    assert pending_cards[0]["card_type"] == "peer_pending"
    assert pending_cards[0]["title"] == "Architect GOD is thinking"
    assert pending_cards[0]["status"] == "pending"
    assert "正在处理" in pending_cards[0]["summary"]


def test_adapter_builds_degraded_peer_latency_cards(tmp_path):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conv = chat.create_conversation("User mission")
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="architect-god",
        cli_kind="codex",
        model="gpt-5.4",
    )
    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv.id,
        inbox_item_id="inbox-latency-1",
        participant_id=architect.participant_id,
        target_role="architect",
        message_created_at="2026-06-04T01:00:00Z",
        inbox_claimed_at="2026-06-04T01:00:01Z",
        delivery_started_at=10.0,
        provider_turn_started_at=10.2,
        first_delta_at=10.8,
        writeback_at=11.5,
        total_latency_ms=1500,
        delivery_mode="stdout_fallback",
        degraded_reason="stdout_fallback",
    )

    cards = _peer_latency_cards(tmp_path, conv.id)

    assert cards == [
        {
            "id": "card_peer_latency_inbox-latency-1",
            "conversation_id": conv.id,
            "card_type": "peer_latency",
            "source_id": "inbox-latency-1",
            "title": "Architect GOD degraded",
            "summary": "stdout_fallback in 1500ms",
            "status": "degraded",
            "href": f"/dashboard/peer-chat/conversations/{conv.id}#latency-inbox-latency-1",
            "api_href": f"/api/dashboard/peer-chat/conversations/{conv.id}/inspector",
            "created_at": 11.5,
            "counts": {"total_latency_ms": 1500},
            "metadata": {
                "delivery_mode": "stdout_fallback",
                "degraded_reason": "stdout_fallback",
                "target_role": "architect",
                "participant_id": architect.participant_id,
            },
        }
    ]


def test_adapter_builds_runtime_closure_cards_from_inspector():
    inspector = {
        "conversation": {"id": "conv-runtime"},
        "participants": {
            "total": 4,
            "summary": {"init": 1, "architect": 1, "review": 1, "execute": 1},
        },
        "collaboration": {
            "active_runs": 1,
            "runs": [
                {
                    "run_id": "collab-1",
                    "status": "partial",
                    "orchestration_mode": "peer_consensus",
                    "initiator": "architect",
                    "targets": ["review", "execute"],
                    "response_count": 1,
                    "blocker_count": 1,
                    "updated_at": "2026-06-05T01:00:00Z",
                }
            ],
            "dispatch_gates": [
                {
                    "event_id": "gate-1",
                    "run_id": "collab-1",
                    "decision": "blocked_active_veto",
                    "proposal_ref": "proposal:lane-graph",
                    "artifact_ref": "artifact:lane-graph",
                    "created_at": "2026-06-05T01:10:00Z",
                }
            ],
        },
        "blockers": {
            "active": 1,
            "items": [
                {
                    "blocker_id": "blocker-1",
                    "run_id": "collab-1",
                    "active": True,
                    "severity": "veto",
                    "issuer": "review",
                    "blocks_dispatch": True,
                    "affected_ref": "tui:cards",
                    "reason": "Runtime cards must show dispatch closure.",
                    "created_at": "2026-06-05T01:05:00Z",
                }
            ],
        },
        "dispatch_queue": {
            "queued": 0,
            "processing": 0,
            "dispatched": 1,
            "failed": 0,
            "entries": [
                {
                    "entry_id": "dispatch-1",
                    "source": "agent",
                    "target": "execute",
                    "status": "dispatched",
                    "auto_execute": True,
                    "provider_run_ref": "provider:execute:part-execute",
                    "dispatch_evidence": "mcp_writeback:dispatch-inbox",
                    "updated_at": "2026-06-05T01:20:00Z",
                }
            ],
        },
        "peer_latency": {
            "recent_turns": [
                {
                    "inbox_item_id": "dispatch-inbox",
                    "delivery_mode": "mcp_writeback",
                    "target_role": "execute",
                    "degraded_reason": None,
                    "writeback_at": "2026-06-05T01:21:00Z",
                }
            ]
        },
    }
    bootstrap = {
        "conversation_id": "conv-runtime",
        "status": "bootstrapped",
        "preset_id": "architect-review-execute",
        "participant_plan": ["architect", "review", "execute"],
        "updated_at": "2026-06-05T00:55:00Z",
    }

    cards = _runtime_closure_cards(inspector, bootstrap=bootstrap)

    assert [card["card_type"] for card in cards] == [
        "runtime_bootstrap",
        "runtime_discussion",
        "runtime_blocker",
        "runtime_dispatch_gate",
        "runtime_dispatch_queue",
        "runtime_provider_writeback",
    ]
    by_type = {card["card_type"]: card for card in cards}
    assert by_type["runtime_bootstrap"]["summary"] == (
        "bootstrapped preset=architect-review-execute team=architect/review/execute"
    )
    assert by_type["runtime_discussion"]["summary"] == (
        "collab-1 partial peer_consensus targets=review, execute responses=1 blockers=1"
    )
    assert by_type["runtime_blocker"]["status"] == "blocked"
    assert by_type["runtime_blocker"]["metadata"]["blocks_dispatch"] is True
    assert by_type["runtime_dispatch_gate"]["summary"] == (
        "gate-1 collab-1 blocked_active_veto proposal:lane-graph artifact:lane-graph"
    )
    assert by_type["runtime_dispatch_queue"]["summary"] == (
        "dispatch-1 dispatched agent target=execute auto provider:execute:part-execute"
    )
    assert by_type["runtime_provider_writeback"]["summary"] == (
        "mcp_writeback execute evidence=dispatch-inbox"
    )
    assert all(card["conversation_id"] == "conv-runtime" for card in cards)
    assert all(
        card["api_href"] == "/api/chat/conversations/conv-runtime/inspector"
        for card in cards
    )


def test_adapter_poll_cards_merges_runtime_closure_cards(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")
    adapter.get_conversation_inspector = lambda conv_id: {
        "conversation": {"id": conv_id},
        "collaboration": {
            "runs": [
                {
                    "run_id": "collab-1",
                    "status": "done",
                    "orchestration_mode": "peer_consensus",
                    "targets": ["review", "execute"],
                    "response_count": 2,
                    "blocker_count": 0,
                    "updated_at": "2026-06-05T02:00:00Z",
                }
            ]
        },
    }
    adapter.get_bootstrap_status = lambda conv_id: {
        "conversation_id": conv_id,
        "status": "proposal_ready",
        "preset_id": "architect-review-execute",
        "participant_plan": ["architect", "review", "execute"],
        "updated_at": "2026-06-05T01:00:00Z",
    }

    cards, err = adapter.poll_cards("conv-runtime")

    assert err is None
    assert [card["card_type"] for card in cards] == [
        "runtime_bootstrap",
        "runtime_discussion",
    ]
    second_cards, second_err = adapter.poll_cards("conv-runtime")
    assert second_err is None
    assert second_cards == []


def test_adapter_poll_cards_does_not_suppress_numeric_latency_after_iso_runtime_card(
    tmp_path,
):
    db = tmp_path / "chat.db"
    chat = ChatStore(db)
    participants = ParticipantStore(db)
    conv = chat.create_conversation("Runtime latency")
    architect = participants.add(
        conversation_id=conv.id,
        role="architect",
        display_name="architect-god",
        cli_kind="codex",
        model="gpt-5.4",
    )
    adapter = XmuseAdapter(tmp_path, chat_api_base_url="http://chat-api")
    adapter.get_conversation_inspector = lambda conv_id: {"conversation": {"id": conv_id}}
    adapter.get_bootstrap_status = lambda conv_id: {
        "conversation_id": conv_id,
        "status": "proposal_ready",
        "preset_id": "architect-review-execute",
        "participant_plan": ["architect", "review", "execute"],
        "updated_at": "2026-06-05T01:00:00Z",
    }

    first_cards, first_err = adapter.poll_cards(conv.id)
    assert first_err is None
    assert [card["card_type"] for card in first_cards] == ["runtime_bootstrap"]

    PeerTurnLatencyTraceStore(db).record(
        conversation_id=conv.id,
        inbox_item_id="inbox-latency-after-runtime",
        participant_id=architect.participant_id,
        target_role="architect",
        message_created_at="2026-06-05T01:00:01Z",
        inbox_claimed_at="2026-06-05T01:00:02Z",
        delivery_started_at=10.0,
        provider_turn_started_at=10.1,
        first_delta_at=10.2,
        writeback_at=11.5,
        total_latency_ms=1500,
        delivery_mode="stdout_fallback",
        degraded_reason="stdout_fallback",
    )

    second_cards, second_err = adapter.poll_cards(conv.id)

    assert second_err is None
    assert [card["card_type"] for card in second_cards] == ["peer_latency"]
    assert second_cards[0]["source_id"] == "inbox-latency-after-runtime"


async def test_adapter_poll_returns_delta():
    adapter = XmuseAdapter(ROOT)
    delta = await adapter.poll_delta(conv_id=None)
    assert delta is not None
    assert isinstance(delta.lanes, list)


async def test_adapter_poll_delta_uses_compact_worklist_envelope(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path)
    envelope = {
        "projection_revision": 11,
        "items": [
            {
                "lane_id": "lane-conv-a",
                "lane_local_id": "T1-02",
                "plan_feature_id": "T1",
                "feature_label": "Envelope Implementation",
                "effective_status": "ready",
                "ready": True,
                "blocked": False,
                "rework": False,
                "scoped_dependency_ids": ["lane-root"],
                "priority": 2,
                "provider_selection_ref": {
                    "api_href": "/api/tui/provider-selection-records?lane_id=lane-conv-a",
                    "label": "Provider selection",
                },
                "debug_refs": {
                    "lane": {
                        "api_href": "/api/lanes/lane-conv-a",
                        "label": "Lane detail",
                    },
                    "takeover": {
                        "api_href": (
                            "/api/lanes/lane-conv-a/"
                            "takeover-context?conversation_id=conv-a"
                        ),
                        "label": "Takeover context",
                    },
                },
                "prompt_summary": "Use the typed worklist envelope.",
            }
        ],
        "run_health": {
            "counts": {"live": 0, "stale": 0, "terminal": 0, "degraded_fallback": 0},
        },
    }

    monkeypatch.setattr(adapter, "poll_messages", lambda conv_id: ([], None))
    monkeypatch.setattr(adapter, "poll_cards", lambda conv_id: ([], None))

    async def _poll_worklist_envelope(conv_id: str | None = None):
        return envelope, None

    monkeypatch.setattr(adapter, "poll_worklist_envelope", _poll_worklist_envelope)

    delta = await adapter.poll_delta(conv_id="conv-a")

    assert delta.lanes == envelope["items"]
    assert delta.run_health == envelope["run_health"]
    assert delta.features["T1"]["total"] == 1
    assert delta.features["T1"]["merged"] == 0
    assert delta.features["T1"]["lanes"] == envelope["items"]


async def test_adapter_poll_worklist_envelope_reloads_same_revision_when_health_changes(
    monkeypatch,
    tmp_path,
):
    adapter = XmuseAdapter(tmp_path)
    base_envelope = {
        "schema_version": "1",
        "read_model_version": "1",
        "source_authority": "feature_lanes_projection",
        "projection_revision": 11,
        "generated_at": "2026-06-01T12:00:00Z",
        "items": [],
        "run_health": {
            "counts": {"live": 1, "stale": 0, "terminal": 0, "degraded_fallback": 0},
            "warnings": [],
        },
        "degraded": False,
        "stale": False,
        "provider_selection_refs": {},
        "degradation": {
            "degraded": False,
            "stale": False,
            "warning_codes": [],
            "reasons": [],
        },
        "runtime_backend": {"configured": "native", "source_authority": "runtime_backend_config"},
        "fallback_reason": None,
        "fallback": {"active": False, "count": 0, "lane_ids": [], "reason": None},
        "graph_lineage": {
            "degraded": False,
            "authoritative_graph_id": None,
            "checked_graph_ids": [],
            "mismatched_graph_ids": [],
            "missing_projection_lane_ids": [],
            "unexpected_projection_lane_ids": [],
            "warning_codes": [],
        },
        "debug_drilldown_refs": {},
        "debug_refs": {},
    }
    degraded_envelope = {
        **base_envelope,
        "generated_at": "2026-06-01T12:00:05Z",
        "run_health": {
            "counts": {"live": 0, "stale": 1, "terminal": 0, "degraded_fallback": 0},
            "warnings": [{"code": "missing_runner"}],
        },
        "degraded": True,
        "stale": True,
        "degradation": {
            "degraded": True,
            "stale": True,
            "warning_codes": ["missing_runner"],
            "reasons": ["runner missing"],
        },
        "fallback_reason": "runner missing",
        "fallback": {
            "active": True,
            "count": 1,
            "lane_ids": ["lane-conv-a"],
            "reason": "runner missing",
        },
        "graph_lineage": {
            "degraded": True,
            "authoritative_graph_id": "graph-T1",
            "checked_graph_ids": ["graph-T1"],
            "mismatched_graph_ids": ["graph-T1"],
            "missing_projection_lane_ids": ["lane-conv-a"],
            "unexpected_projection_lane_ids": [],
            "warning_codes": ["graph_lineage_projection_mismatch"],
        },
    }

    class _Envelope:
        def __init__(self, payload: dict):
            self._payload = payload

        def model_dump(self, mode: str = "json") -> dict:
            return self._payload

    payloads = [
        _Envelope(base_envelope),
        _Envelope(degraded_envelope),
        _Envelope(degraded_envelope),
    ]

    def _build_tui_worklist_envelope(*args, **kwargs):
        return payloads.pop(0)

    monkeypatch.setattr(
        read_envelopes,
        "build_tui_worklist_envelope",
        _build_tui_worklist_envelope,
    )

    first, first_error = await adapter.poll_worklist_envelope("conv-a")
    second, second_error = await adapter.poll_worklist_envelope("conv-a")
    third, third_error = await adapter.poll_worklist_envelope("conv-a")

    assert first_error is None
    assert second_error is None
    assert third_error is None
    assert first == base_envelope
    assert second == degraded_envelope
    assert third is None


def test_adapter_builds_workbench_lane_detail_from_read_models(monkeypatch, tmp_path):
    adapter = XmuseAdapter(tmp_path)

    class _Envelope:
        def model_dump(self, mode="json"):
            return {
                "conversation_id": "conv-a",
                "items": [
                    {
                        "lane_id": "lane-a",
                        "lane_local_id": "T1-01",
                        "plan_feature_id": "T1",
                        "feature_label": "Closure workbench",
                        "effective_status": "dispatched",
                        "priority": 3,
                        "scoped_dependency_ids": ["T1-00"],
                        "provider_selection_ref": {
                            "api_href": "/api/tui/provider-selection-records?lane_id=lane-a"
                        },
                        "debug_refs": {
                            "lane": {"api_href": "/api/lanes/lane-a"},
                            "takeover_context": {
                                "api_href": "/api/lanes/lane-a/takeover-context"
                            },
                        },
                    }
                ],
            }

    monkeypatch.setattr(
        read_envelopes,
        "build_tui_worklist_envelope",
        lambda *args, **kwargs: _Envelope(),
    )
    monkeypatch.setattr(
        "xmuse.tui.adapter.xmuse_adapter._conversation_runtime_timeline_detail",
        lambda root, conversation_id: {
            "conversation_id": conversation_id,
            "source_authority": "chat_inspector",
            "events": [
                {
                    "event_id": "evt-runtime-1",
                    "event_type": "dispatch",
                    "title": "Dispatch",
                    "summary": "lane-a dispatched to execute",
                    "status": "dispatched",
                    "created_at": "2026-06-05T01:00:00Z",
                }
            ],
        },
    )
    monkeypatch.setattr(
        adapter,
        "list_tui_command_events",
        lambda conv_id=None: [
            {
                "event_id": "tui_cmd_1",
                "command": "/discussion",
                "conversation_id": "conv-a",
                "read_surface_authority": "chat_inspector",
                "surface_ref": "chat_inspector:conv-a",
                "created_at": "2026-06-05T01:01:00Z",
            }
        ],
    )

    detail = adapter.get_workbench_lane_detail("conv-a", "lane-a")

    assert detail is not None
    assert detail["task"]["lane_id"] == "lane-a"
    assert detail["task"]["feature_label"] == "Closure workbench"
    assert detail["source_authority"] == "tui_worklist_envelope"
    assert [event["event_id"] for event in detail["execution_log"]["events"]] == [
        "evt-runtime-1",
        "tui_cmd_1",
    ]
    assert detail["execution_log"]["events"][1]["event_type"] == "tui_command"


def test_adapter_get_provider_inventory_flattens_provider_read_contract(tmp_path):
    GodCliRegistrationStore(tmp_path / "god_cli_registrations.json").record_registration(
        registration=GodCliRegistration(
            cli_id="custom.peer",
            display_name="Custom Peer",
            command_family="custom-cli",
            provider_profile_ref="custom.peer",
            capabilities=(GodCliCapability.PEER_GOD,),
            allowed_speech_acts=("propose", "decide"),
            supports_persistent_sessions=True,
            supports_mcp_writeback=True,
            state_write_allowed=True,
            proof_level="real_provider_proof",
            proof_refs=("provider-run://custom.peer/live-smoke-1",),
        ),
        registered_by="operator-1",
        audit_id="operator-action:provider-board",
        idempotency_key="idem-provider-board",
    )

    rows = XmuseAdapter(tmp_path).get_provider_inventory()

    codex_god = next(
        row
        for row in rows
        if row["provider_id"] == "codex" and row["profile_id"] == "god"
    )
    opencode_worker = next(
        row
        for row in rows
        if row["provider_id"] == "opencode"
        and row["profile_id"] == "deepseek_flash_worker"
    )
    custom_peer = next(
        row
        for row in rows
        if row["provider_profile_ref"] == "custom.peer"
    )

    assert codex_god["boundary_role"] == "production_groupchat_god"
    assert codex_god["runtime_kind"] == "codex_cli"
    assert codex_god["transport"] == "cli"
    assert codex_god["session_continuity"] == "persistent_supported"
    assert codex_god["proof_level"] == "contract_proof"
    assert "bounded_deliberation" in codex_god["capabilities"]
    assert opencode_worker["boundary_role"] == "bounded_secondary"
    assert opencode_worker["runtime_kind"] == "opencode_cli"
    assert opencode_worker["session_continuity"] == "bounded"
    assert opencode_worker["waiting_reason"] == "secondary bounded worker"
    assert custom_peer["provider_id"] == "custom-cli"
    assert custom_peer["boundary_role"] == "manual_registered_peer_god"
    assert custom_peer["runtime_kind"] == "custom-cli"
    assert custom_peer["transport"] == "cli"
    assert custom_peer["proof_level"] == "real_provider_proof"
    assert custom_peer["registration_kind"] == "manual"
