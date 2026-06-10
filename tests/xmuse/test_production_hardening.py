from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path

from fastapi.testclient import TestClient

from xmuse.chat_api import create_app
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
    accepted = client.post(
        "/api/chat/conversations",
        json={"title": "Allowed"},
        headers={"X-XMUSE-API-Key": "secret"},
    )

    assert rejected.status_code == 401
    assert rejected.json() == {"detail": "authentication required"}
    assert accepted.status_code == 201


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
