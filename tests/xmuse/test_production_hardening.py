from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from xmuse.chat_api import _auth_token_from_env, create_app
from xmuse_core.chat.store import ChatStore
from xmuse_core.platform.mcp_permissions import authorize_mcp_tool
from xmuse_core.platform.production_readiness import (
    GITHUB_APP_MIGRATION_PLAN,
    PRODUCTION_SLO_TARGETS,
)
from xmuse_core.platform.runtime_retention import cleanup_runtime_state


def test_chat_api_auth_rejects_anonymous_write_when_enabled(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, auth_token="secret"))

    rejected = client.post("/api/chat/conversations", json={"title": "Blocked"})
    missing_capability = client.post(
        "/api/chat/conversations",
        json={"title": "Still blocked"},
        headers={"X-XMUSE-API-Key": "secret"},
    )
    accepted = client.post(
        "/api/chat/conversations",
        json={"title": "Allowed"},
        headers={
            "X-XMUSE-API-Key": "secret",
            "X-XMuse-Operator-Role": "operator",
            "X-XMuse-Operator-Capabilities": "chat_create_conversation",
        },
    )

    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "authentication required"}
    assert missing_capability.status_code == 403
    assert missing_capability.json()["detail"] == {
        "code": "missing_capability",
        "message": "missing capability chat_create_conversation",
        "required_capability": "chat_create_conversation",
    }
    assert accepted.status_code == 201


def test_chat_api_auth_token_can_be_loaded_from_env(monkeypatch) -> None:
    monkeypatch.setenv("XMUSE_CHAT_API_AUTH_TOKEN", "server-secret")
    monkeypatch.setenv("XMUSE_CHAT_API_KEY", "client-secret")

    assert _auth_token_from_env() == "server-secret"

    monkeypatch.delenv("XMUSE_CHAT_API_AUTH_TOKEN")

    assert _auth_token_from_env() == "client-secret"


def test_chat_api_production_profile_requires_write_auth_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XMUSE_DEPLOYMENT_PROFILE", "production")
    monkeypatch.delenv("XMUSE_CHAT_API_AUTH_TOKEN", raising=False)
    monkeypatch.delenv("XMUSE_CHAT_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="XMUSE_CHAT_API_AUTH_TOKEN"):
        create_app(tmp_path)


def test_chat_api_production_profile_uses_env_write_auth_token(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XMUSE_DEPLOYMENT_PROFILE", "production")
    monkeypatch.setenv("XMUSE_CHAT_API_AUTH_TOKEN", "server-secret")

    client = TestClient(create_app(tmp_path))
    rejected = client.post("/api/chat/conversations", json={"title": "Blocked"})
    accepted = client.post(
        "/api/chat/conversations",
        json={"title": "Allowed"},
        headers={
            "X-XMUSE-API-Key": "server-secret",
            "X-XMuse-Operator-Role": "operator",
            "X-XMuse-Operator-Capabilities": "chat_create_conversation",
        },
    )

    assert rejected.status_code == 401
    assert accepted.status_code == 201


def test_chat_api_auth_blocks_viewer_even_with_write_capability(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, auth_token="secret"))

    response = client.post(
        "/api/chat/conversations",
        json={"title": "Viewer blocked"},
        headers={
            "X-XMUSE-API-Key": "secret",
            "X-XMuse-Operator-Role": "viewer",
            "X-XMuse-Operator-Capabilities": "chat_create_conversation",
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == {
        "code": "role_not_authorized",
        "message": "viewer role cannot mutate Chat API write surface",
        "required_capability": "chat_create_conversation",
    }


def test_chat_api_auth_allows_admin_without_explicit_capability(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path, auth_token="secret"))

    response = client.post(
        "/api/chat/conversations",
        json={"title": "Admin allowed"},
        headers={
            "X-XMUSE-API-Key": "secret",
            "X-XMuse-Operator-Role": "admin",
        },
    )

    assert response.status_code == 201


def test_chat_api_operator_action_keeps_action_capability_when_auth_enabled(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path, auth_token="secret"))
    conversation = client.post(
        "/api/chat/conversations",
        json={"title": "Mission"},
        headers={
            "X-XMUSE-API-Key": "secret",
            "X-XMuse-Operator-Role": "operator",
            "X-XMuse-Operator-Capabilities": "chat_create_conversation",
        },
    ).json()

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMUSE-API-Key": "secret",
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Role": "operator",
            "X-XMuse-Operator-Capabilities": "select_god_cli",
        },
        json={
            "action": "select_god_cli",
            "payload": {
                "conversation_id": conversation["id"],
                "cli_id": "codex.god",
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_chat_api_release_gate_operator_action_when_auth_enabled(
    tmp_path: Path,
) -> None:
    client = TestClient(create_app(tmp_path, auth_token="secret"))
    artifacts_dir = tmp_path / "work" / "release_readiness" / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    (artifacts_dir / "provider.json").write_text(
        json.dumps(
            {
                "schema_version": "xmuse.production_evidence.v1",
                "gate_id": "provider-soak",
                "kind": "real_provider",
                "configured": True,
                "required": True,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "owner": "operator",
                "summary": "Provider soak was not supplied.",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    response = client.post(
        "/api/chat/operator/actions",
        headers={
            "X-XMUSE-API-Key": "secret",
            "X-XMuse-Operator-Id": "operator-1",
            "X-XMuse-Operator-Role": "operator",
            "X-XMuse-Operator-Capabilities": "release_gate",
        },
        json={
            "action": "capture_release_evidence_pack",
            "idempotency_key": "idem-release-auth",
            "payload": {},
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["payload"]["evidence_pack"]["decision"] == "blocked"


def test_mcp_rbac_blocks_viewer_lane_and_memory_mutation() -> None:
    lane_decision = authorize_mcp_tool("update_lane_status", role="viewer")
    memory_decision = authorize_mcp_tool("memory_ingest", role="viewer")
    unauthenticated_operator_decision = authorize_mcp_tool("memory_ingest", role="operator")
    operator_decision = authorize_mcp_tool(
        "memory_ingest",
        role="operator",
        host_auth_enabled=True,
    )

    assert lane_decision.allowed is False
    assert lane_decision.reason == "role viewer cannot mutate write tool update_lane_status"
    assert memory_decision.allowed is False
    assert memory_decision.reason == "memory write tool memory_ingest requires host auth/RBAC"
    assert unauthenticated_operator_decision.allowed is False
    assert unauthenticated_operator_decision.reason == (
        "memory write tool memory_ingest requires host auth/RBAC"
    )
    assert operator_decision.allowed is True


def test_chat_store_migration_preserves_existing_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "chat.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            create table conversations (
                id text primary key,
                title text not null,
                created_at text not null
            );
            create table messages (
                id text primary key,
                conversation_id text not null references conversations(id),
                author text not null,
                role text not null,
                content text not null,
                created_at text not null
            );
            insert into conversations values (
                'conv-old',
                'Old conversation',
                '2026-01-01T00:00:00Z'
            );
            insert into messages values (
                'msg-old',
                'conv-old',
                'human',
                'human',
                'Preserve me',
                '2026-01-01T00:00:01Z'
            );
            """
        )

    store = ChatStore(db_path)

    assert store.list_conversations()[0].id == "conv-old"
    assert store.list_messages("conv-old")[0].content == "Preserve me"
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("pragma table_info(messages)").fetchall()}
        migrations = conn.execute("select version from schema_migrations").fetchall()
    assert {"envelope_type", "envelope_json", "mentions_json", "reply_to_message_id"} <= columns
    assert ("chat_store_v1",) in migrations


def test_runtime_cleanup_never_deletes_durable_authority_records(tmp_path: Path) -> None:
    durable_paths = [
        tmp_path / "chat.db",
        tmp_path / "planning_events.sqlite3",
        tmp_path / "lane_graphs" / "graph.json",
        tmp_path / "feature_plans" / "plan.json",
    ]
    transient_paths = [
        tmp_path / "logs" / "old.log",
        tmp_path / "work" / "scratch.txt",
        tmp_path / "history" / "trace.jsonl",
    ]
    for path in [*durable_paths, *transient_paths]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("data", encoding="utf-8")
        old = time.time() - 10_000
        os.utime(path, (old, old))

    report = cleanup_runtime_state(tmp_path, max_age_seconds=1)

    assert sorted(report.deleted_relative_paths) == [
        "history/trace.jsonl",
        "logs/old.log",
        "work/scratch.txt",
    ]
    assert all(path.exists() for path in durable_paths)


def test_production_readiness_declares_slo_targets_and_github_app_plan() -> None:
    assert PRODUCTION_SLO_TARGETS == {
        "blueprint_freeze_p95_seconds": 90,
        "ready_lane_dispatch_p95_seconds": 5,
        "memory_search_p95_ms_sqlite_poc": 300,
        "feature_pr_cycle_p95_minutes_excluding_human_wait": 30,
    }
    assert any("GitHub App" in item for item in GITHUB_APP_MIGRATION_PLAN)
    assert any("required checks" in item for item in GITHUB_APP_MIGRATION_PLAN)
