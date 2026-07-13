from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.xmuse.room_fixtures import RoomTestStore
from xmuse.chat_api import create_app
from xmuse.chat_api_memory import register_room_memory_routes
from xmuse_core.chat.memoryos_supervisor import write_memoryos_status


class _MemoryError(ValueError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class _Store:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def get_binding(self, *, conversation_id: str, scope_type: str = "room"):
        return None

    def list_candidates(self, *, conversation_id: str, approval_state=None, limit=50):
        return [
            {
                "candidate_id": "memory-candidate-1",
                "conversation_id": conversation_id,
                "kind": "user_preference",
                "content": "Use concise replies.",
                "content_sha256": "sha256:" + "a" * 64,
                "candidate_digest": "sha256:" + "a" * 64,
                "source_activity_ids": ["activity-1"],
                "approval_state": "pending",
                "publish_state": "not_queued",
                "target_scope": "local_user",
                "revision": 2,
            }
        ]

    def count_candidates(self, conversation_id: str, *, approval_state=None):
        return 1

    def count_outbox_by_state(self, *, conversation_id: str):
        return {"pending": 1}

    def list_attempt_receipts(self, *, conversation_id: str, limit=20):
        return []

    def get_candidate(self, candidate_id: str):
        return (
            self.list_candidates(conversation_id="conv-1")[0]
            if candidate_id == "memory-candidate-1"
            else None
        )

    def resolve_candidate(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs["expected_candidate_digest"] != "sha256:" + "a" * 64:
            raise _MemoryError("room_memory_candidate_guard_mismatch")
        return {
            "action_id": kwargs["client_action_id"],
            "status": "applied",
            "candidate": {
                "candidate_id": kwargs["candidate_id"],
                "conversation_id": "conv-1",
                "approval_state": ("approved" if kwargs["decision"] == "approve" else "rejected"),
                "publish_state": "not_queued",
                "revision": 3,
                "content": "must-not-leak-from-action-receipt",
            },
        }


def _client(store: _Store, token: str | None = "operator-secret") -> TestClient:
    app = FastAPI()
    register_room_memory_routes(
        app,
        root=Path("/tmp/xmuse-memory-api-test"),
        binding_store_factory=lambda _path: store,
        governance_store_factory=lambda _path: store,
        delivery_store_factory=lambda _path: store,
        recall_store_factory=lambda _path: store,
        operator_token=token,
        runtime_status_provider=lambda: {
            "enabled": True,
            "state": "ready",
            "api_key": "must-not-leak",
        },
        conversation_exists=lambda conversation_id: conversation_id == "conv-1",
    )
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"X-XMuse-Operator-Token": "operator-secret"}


def test_memory_read_is_room_scoped_bounded_and_no_store() -> None:
    client = _client(_Store())
    response = client.get("/api/chat/conversations/conv-1/memory")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["schema_version"] == "room_memory_projection/v1"
    assert "must-not-leak" not in response.text
    assert client.get("/api/chat/conversations/conv-2/memory").status_code == 404


def test_memory_resolve_requires_operator_and_exact_guarded_body() -> None:
    store = _Store()
    client = _client(store)
    body = {
        "client_action_id": "memory-action-1",
        "decision": "approve",
        "expected_digest": "sha256:" + "a" * 64,
        "expected_revision": 2,
    }
    path = "/api/chat/operator/memory-candidates/memory-candidate-1/resolve"

    assert client.post(path, json=body).status_code == 401
    assert (
        client.post(path, headers=_headers(), json={**body, "archive_id": "bad"}).status_code == 422
    )
    response = client.post(path, headers=_headers(), json=body)
    assert response.status_code == 200
    assert response.json() == {
        "action_id": "memory-action-1",
        "status": "applied",
        "candidate_id": "memory-candidate-1",
        "conversation_id": "conv-1",
        "approval_state": "approved",
        "publish_state": "not_queued",
        "revision": 3,
        "reason_code": None,
        "proof_boundary": "operator_action_receipt_not_memory_or_room_authority",
    }
    assert store.calls[0] == {
        "candidate_id": "memory-candidate-1",
        "decision": "approve",
        "client_action_id": "memory-action-1",
        "operator_identity": "operator:local",
        "expected_candidate_digest": "sha256:" + "a" * 64,
        "expected_revision": 2,
    }


def test_memory_guard_conflict_is_409_for_immediate_projection_refresh() -> None:
    client = _client(_Store())
    response = client.post(
        "/api/chat/operator/memory-candidates/memory-candidate-1/resolve",
        headers=_headers(),
        json={
            "client_action_id": "memory-action-conflict",
            "decision": "reject",
            "expected_digest": "sha256:" + "b" * 64,
            "expected_revision": 2,
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "room_memory_candidate_guard_mismatch"


def test_default_chat_api_freshness_checks_memoryos_receipt_without_leaking_identity(
    tmp_path: Path,
) -> None:
    conversation_id = RoomTestStore(tmp_path / "chat.db").create_conversation("memory").id
    stale = datetime.now(UTC) - timedelta(seconds=30)
    write_memoryos_status(
        tmp_path,
        enabled=True,
        state="ready",
        code="ready",
        generation="secret-generation",
        pid=12345,
        start_identity="secret-process-identity",
        started_at=stale.isoformat(),
        heartbeat_at=stale.isoformat(),
    )
    client = TestClient(create_app(tmp_path))

    response = client.get(f"/api/chat/conversations/{conversation_id}/memory")

    assert response.status_code == 200
    assert response.json()["runtime"]["state"] == "degraded"
    assert response.json()["runtime"]["code"] == "memoryos_heartbeat_stale"
    for secret in ("12345", "secret-generation", "secret-process-identity", str(tmp_path)):
        assert secret not in response.text

    leaked_pid = "9876543210"
    (tmp_path / "memoryos-status.json").write_text(f'{{"pid":{leaked_pid}}}', encoding="utf-8")
    invalid = client.get(f"/api/chat/conversations/{conversation_id}/memory")
    assert invalid.json()["runtime"]["code"] == "memoryos_receipt_invalid"
    assert leaked_pid not in invalid.text
