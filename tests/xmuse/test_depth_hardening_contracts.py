from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_DOC = PROJECT_ROOT / "docs" / "xmuse" / "schema-migration-strategy.md"
PERMISSION_DOC = PROJECT_ROOT / "docs" / "xmuse" / "mcp-permission-model.md"
PRODUCTION_OPS = PROJECT_ROOT / "docs" / "xmuse" / "production-operations.md"
MCP_SERVER_PATH = PROJECT_ROOT / "xmuse" / "mcp_server.py"
PLATFORM_RUNNER_PATH = PROJECT_ROOT / "xmuse" / "platform_runner.py"

DURABLE_STORES = {
    "chat.db",
    "god_sessions.json",
    "feature_graph_statuses.json",
    "feature_graph_artifacts.json",
    "planning_runs.sqlite3",
    "planning_events.sqlite3",
    "provider_session_bindings.json",
    "feature_lanes.json",
    "active_sessions.json",
    "error_knowledge.json",
    "coordinator_incidents.jsonl",
    "provider_selection_records.jsonl",
    "feature_lanes.json.writer_lease.json",
    "feature_plans/*.json",
    "feature_plans/*.deliberation.json",
    "graph_sets/*.json",
    "lane_graphs/*.json",
    "audit_events.json",
    "final_actions.json",
}

HIGH_RISK_STORES = {
    "chat.db",
    "god_sessions.json",
    "planning_runs.sqlite3",
    "planning_events.sqlite3",
    "feature_lanes.json",
    "active_sessions.json",
    "feature_plans/*.json",
    "graph_sets/*.json",
    "lane_graphs/*.json",
    "audit_events.json",
    "final_actions.json",
}

IDENTITY_BOUND_CHAT_TOOLS = {
    "chat_post_message",
    "chat_read_inbox",
    "chat_mark_inbox",
    "chat_mention",
    "chat_emit_proposal",
    "chat_approve_proposal",
    "chat_create_collaboration_request",
    "chat_record_collaboration_response",
    "chat_raise_collaboration_blocker",
    "chat_resolve_collaboration_blocker",
    "chat_evaluate_dispatch_gate",
    "chat_emit_blueprint_proposal",
}

REPRESENTATIVE_IDENTITY_RUNTIME_TOOLS = {
    "chat_post_message",
    "chat_read_inbox",
    "chat_mark_inbox",
    "chat_mention",
    "chat_emit_proposal",
    "chat_approve_proposal",
    "chat_emit_blueprint_proposal",
}


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _mcp_call(client: TestClient, name: str, arguments: dict[str, object]) -> dict:
    response = client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": f"call-{name}",
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        },
    )
    assert response.status_code == 200
    return response.json()["result"]["structuredContent"]


def _markdown_table_rows(content: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for line in content.splitlines():
        if not line.startswith("| "):
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if not cells or cells[0] in {"Store", "---"}:
            continue
        if set(cells[0]) == {"-"}:
            continue
        rows[cells[0]] = cells
    return rows


def _all_mcp_tool_names() -> set[str]:
    server = _load_module("xmuse_mcp_server_v11_contract", MCP_SERVER_PATH)
    return {schema["name"] for schema in server._all_tool_schemas()}


def test_schema_migration_strategy_classifies_all_durable_stores() -> None:
    content = _read(SCHEMA_DOC)
    rows = _markdown_table_rows(content)

    assert DURABLE_STORES <= set(rows)
    assert "Inventory Corrections" in content
    assert "destructive migrations are out of scope" in content

    for store in DURABLE_STORES:
        row_text = " | ".join(rows[store]).lower()
        assert re.search(r"\b(high|medium|low|ephemeral|legacy)\b", row_text), store
        assert "stance:" in row_text, store

    for store in HIGH_RISK_STORES:
        row_text = " | ".join(rows[store]).lower()
        assert "version" in row_text, store
        assert ("reject" in row_text or "additive-only" in row_text), store


def test_mcp_permission_metadata_covers_every_registered_tool() -> None:
    from xmuse_core.platform.mcp_permissions import (
        DISABLED_MCP_TOOL_NAMES,
        IDENTITY_BOUND_CHAT_TOOL_NAMES,
        MCP_TOOL_PERMISSIONS,
        REGISTERED_MCP_TOOL_NAMES,
        PermissionCategory,
    )

    registered_tool_names = _all_mcp_tool_names()
    assert REGISTERED_MCP_TOOL_NAMES == registered_tool_names
    assert set(MCP_TOOL_PERMISSIONS) == registered_tool_names | DISABLED_MCP_TOOL_NAMES
    assert DISABLED_MCP_TOOL_NAMES == {
        "memory_search",
        "memory_build_context",
        "memory_ingest",
    }
    assert DISABLED_MCP_TOOL_NAMES.isdisjoint(registered_tool_names)
    assert IDENTITY_BOUND_CHAT_TOOL_NAMES == IDENTITY_BOUND_CHAT_TOOLS

    categories = {metadata.permission_category for metadata in MCP_TOOL_PERMISSIONS.values()}
    assert {
        PermissionCategory.READ_ONLY,
        PermissionCategory.WRITE,
        PermissionCategory.IDENTITY_BOUND_GOD,
        PermissionCategory.ADMIN_OPERATOR,
    } <= categories

    for name, metadata in MCP_TOOL_PERMISSIONS.items():
        if metadata.permission_category is PermissionCategory.READ_ONLY:
            assert metadata.mutates is False, name
            assert metadata.access == "read", name
        if metadata.mutates:
            assert metadata.permission_category is not PermissionCategory.READ_ONLY, name
        if name in IDENTITY_BOUND_CHAT_TOOLS:
            assert metadata.identity_verification == "god_session", name
            assert metadata.scope == "conversation_participant_session", name


def test_mcp_permission_doc_matches_metadata_and_separates_auth_from_identity() -> None:
    from xmuse_core.platform.mcp_permissions import MCP_TOOL_PERMISSIONS

    content = _read(PERMISSION_DOC)

    for phrase in (
        "API authentication is not implemented",
        "identity verification is not API authentication",
        "audit guard is not authorization",
        "permission category is declarative",
    ):
        assert phrase in content

    for name, metadata in MCP_TOOL_PERMISSIONS.items():
        assert name in content
        assert metadata.permission_category.value in content


def _identity_tool_args(
    tool_name: str,
    *,
    conversation_id: str,
    participant_id: str,
    god_session_id: str,
) -> dict[str, object]:
    base: dict[str, object] = {
        "conversation_id": conversation_id,
        "participant_id": participant_id,
        "god_session_id": god_session_id,
    }
    if tool_name == "chat_post_message":
        return {
            **base,
            "client_request_id": "req-post",
            "content": "reply",
            "reply_to_inbox_item_id": "inbox-missing",
        }
    if tool_name == "chat_read_inbox":
        return base
    if tool_name == "chat_mark_inbox":
        return {**base, "inbox_item_id": "inbox-missing", "status": "read"}
    if tool_name == "chat_mention":
        return {
            **base,
            "client_request_id": "req-mention",
            "target_address": "@review",
            "content": "please review",
        }
    if tool_name == "chat_emit_proposal":
        return {
            **base,
            "client_request_id": "req-proposal",
            "summary": "proposal",
            "lanes": [
                {
                    "feature_id": "lane-v11",
                    "prompt": "check v11",
                    "depends_on": [],
                    "capabilities": ["code"],
                }
            ],
        }
    if tool_name == "chat_approve_proposal":
        return {
            **base,
            "client_request_id": "req-approve-proposal",
            "proposal_id": "proposal-missing",
            "goal_summary": "approve proposal",
        }
    if tool_name == "chat_emit_blueprint_proposal":
        return {
            **base,
            "client_request_id": "req-blueprint",
            "title": "Blueprint",
            "body": "body",
            "acceptance_criteria": ["criterion"],
        }
    raise AssertionError(f"unknown identity-bound tool: {tool_name}")


def test_identity_bound_chat_mcp_tools_reject_wrong_conversation_participant_and_session(
    tmp_path: Path,
) -> None:
    server = _load_module("xmuse_mcp_server_v11_identity", MCP_SERVER_PATH)
    xmuse_root = tmp_path / "xmuse"
    client = TestClient(server.create_app(xmuse_root=xmuse_root))

    created = _mcp_call(client, "chat_create_conversation", {"title": "V11 identity"})
    other = _mcp_call(client, "chat_create_conversation", {"title": "Other"})
    conversation_id = created["conversation"]["id"]
    other_conversation_id = other["conversation"]["id"]
    architect = next(
        participant
        for participant in created["participants"]
        if participant["role"] == "architect"
    )
    review = next(
        participant for participant in created["participants"] if participant["role"] == "review"
    )
    session = next(
        session
        for session in created["participant_sessions"]
        if session["participant_id"] == architect["participant_id"]
    )

    for tool_name in sorted(REPRESENTATIVE_IDENTITY_RUNTIME_TOOLS):
        wrong_conversation = _mcp_call(
            client,
            tool_name,
            _identity_tool_args(
                tool_name,
                conversation_id=other_conversation_id,
                participant_id=architect["participant_id"],
                god_session_id=session["god_session_id"],
            ),
        )
        assert wrong_conversation["error"]["code"] == "session_participant_mismatch"

        wrong_participant = _mcp_call(
            client,
            tool_name,
            _identity_tool_args(
                tool_name,
                conversation_id=conversation_id,
                participant_id=review["participant_id"],
                god_session_id=session["god_session_id"],
            ),
        )
        assert wrong_participant["error"]["code"] == "session_participant_mismatch"

        wrong_session = _mcp_call(
            client,
            tool_name,
            _identity_tool_args(
                tool_name,
                conversation_id=conversation_id,
                participant_id=architect["participant_id"],
                god_session_id="god-missing",
            ),
        )
        assert wrong_session["error"]["code"] == "unknown_god_session"


def test_cleanup_health_distinguishes_report_only_detection_from_automated_cleanup() -> None:
    platform_runner = _load_module("xmuse_platform_runner_v11_cleanup", PLATFORM_RUNNER_PATH)

    cleanup = platform_runner._cleanup_health(
        {
            "codex_app_server": 1,
            "raylet": 2,
            "gcs_server": 1,
            "ray_worker": 3,
        },
        runner_count=0,
    )

    assert cleanup["status"] == "dirty"
    assert {item["code"] for item in cleanup["leftovers"]} == {
        "leftover_codex_app_server",
        "leftover_raylet",
        "leftover_gcs_server",
        "leftover_ray_worker",
    }
    for item in cleanup["leftovers"]:
        assert item["action"] == "report_only"
        assert item["automated_cleanup"] is False
        assert item["operator_action"] == "inspect_and_cleanup_manually"


def test_cleanup_contract_docs_separate_automated_cleanup_from_detection() -> None:
    production = _read(PRODUCTION_OPS)
    schema = _read(SCHEMA_DOC)

    for content in (production, schema):
        assert "automated cleanup" in content
        assert "report-only detection" in content
        assert "leftover_codex_app_server" in content
        assert "action=report_only" in content
