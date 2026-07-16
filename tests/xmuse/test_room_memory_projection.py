from __future__ import annotations

import json

from xmuse_core.chat.room_memory_projection import (
    build_room_memory_projection,
    build_room_memory_projection_v2,
)


class _Store:
    def get_binding(self, *, conversation_id: str, scope_type: str = "room"):
        assert conversation_id == "conv-1" and scope_type == "room"
        return {
            "session_state": "bound",
            "attachment_state": "attached",
            "revision": 2,
            "updated_at": "2026-07-12T01:00:00Z",
            "session_id": "must-not-leak",
            "archive_id": "must-not-leak",
        }

    def list_candidates(self, *, conversation_id: str, approval_state=None, limit=50):
        assert conversation_id == "conv-1" and approval_state == "pending" and limit == 20
        return [
            {
                "candidate_id": "memory-candidate-1",
                "conversation_id": "conv-1",
                "author_participant_id": "participant-1",
                "source_attempt_id": "must-not-leak",
                "kind": "project_rule",
                "content": "Prefer deterministic tests.",
                "content_sha256": "sha256:" + "e" * 64,
                "candidate_digest": "sha256:" + "a" * 64,
                "source_activity_ids": ["activity-1"],
                "approval_state": "pending",
                "publish_state": "not_queued",
                "target_scope": "project",
                "revision": 3,
                "reason_code": None,
                "created_at": "2026-07-12T01:00:00Z",
                "updated_at": "2026-07-12T01:01:00Z",
                "raw_provider_output": "must-not-leak",
            },
            {
                "candidate_id": "wrong-room",
                "conversation_id": "conv-2",
                "kind": "room_fact",
                "content": "wrong",
                "content_sha256": "sha256:" + "b" * 64,
                "approval_state": "pending",
                "publish_state": "not_queued",
                "target_scope": "room",
                "revision": 0,
            },
        ]

    def count_candidates(self, conversation_id: str, *, approval_state=None):
        assert conversation_id == "conv-1" and approval_state == "pending"
        return 23

    def count_outbox_by_state(self, *, conversation_id: str):
        assert conversation_id == "conv-1"
        return {"pending": 4, "claimed": 1, "failed": 2, "conflict": 1, "delivered": 9}

    def list_attempt_receipts(self, *, conversation_id: str, limit=20):
        assert conversation_id == "conv-1" and limit == 8
        return [
            {
                "receipt_id": "memory-receipt-1",
                "attempt_id": "must-not-leak",
                "observation_id": "must-not-leak",
                "participant_id": "participant-1",
                "status": "ok",
                "memory_schema_version": "metadata.v3_context",
                "latency_ms": 12,
                "item_count": 1,
                "item_refs": [
                    {
                        "document_id": "must-not-leak",
                        "item_id": "must-not-leak",
                        "source_activity_ids": ["activity-1"],
                        "content_sha256": "sha256:" + "c" * 64,
                        "archive_scope": "project",
                    }
                ],
                "evidence_sha256": "sha256:" + "d" * 64,
                "created_at": "2026-07-12T01:02:00Z",
                "prompt": "must-not-leak",
            }
        ]

    def list_external_advisory_receipts(self, conversation_id: str, *, limit=20):
        assert conversation_id == "conv-1" and limit == 8
        return []


def _projection(store: _Store, **kwargs):
    return build_room_memory_projection(
        "conv-1",
        binding_store=store,
        governance_store=store,
        delivery_store=store,
        recall_store=store,
        advisory_store=store,
        **kwargs,
    )


def test_projection_whitelists_memory_evidence_and_operator_guards() -> None:
    projection = _projection(
        _Store(),
        runtime_status={
            "enabled": True,
            "state": "ready",
            "code": "ready",
            "started_at": "2026-07-12T00:00:00Z",
            "heartbeat_at": "2026-07-12T01:02:00Z",
            "pid": 123,
            "api_key": "must-not-leak",
            "url": "http://127.0.0.1:9999",
            "data_dir": "/secret/path",
        },
        generated_at="2026-07-12T01:03:00Z",
    )

    assert projection["schema_version"] == "room_memory_projection/v1"
    assert projection["enabled"] is True and projection["degraded"] is False
    assert projection["runtime"] == {
        "enabled": True,
        "degraded": False,
        "state": "ready",
        "code": "ready",
        "started_at": "2026-07-12T00:00:00Z",
        "updated_at": "2026-07-12T01:02:00Z",
        "consecutive_restart_count": 0,
        "next_retry_at": None,
        "last_healthy_at": None,
    }
    assert projection["sync"] == {
        "backlog": 8,
        "pending": 4,
        "processing": 1,
        "failed": 2,
        "conflict": 1,
        "delivered": 9,
    }
    assert projection["pending_candidate_total"] == 23
    candidate = projection["pending_candidates"][0]
    assert candidate["content"] == "Prefer deterministic tests."
    assert candidate["actions"]["resolve"] == {
        "available": True,
        "method": "POST",
        "href": "/api/chat/operator/memory-candidates/memory-candidate-1/resolve",
        "expected_digest": "sha256:" + "a" * 64,
        "expected_revision": 3,
        "allowed_decisions": ["approve", "reject"],
    }
    recall = projection["recent_recalls"][0]
    assert recall["receipt_id"] == "memory-receipt-1"
    assert recall["source_refs"] == [
        {
            "activity_id": "activity-1",
            "content_sha256": "sha256:" + "c" * 64,
            "archive_scope": "project",
        }
    ]
    encoded = json.dumps(projection, sort_keys=True)
    for secret in (
        "must-not-leak",
        "attempt_id",
        "observation_id",
        "document_id",
        "api_key",
        "data_dir",
        "127.0.0.1:9999",
    ):
        assert secret not in encoded


def test_projection_degrades_safely_and_receipt_without_opaque_id_is_minimal() -> None:
    store = _Store()
    store.list_attempt_receipts = lambda *_args, **_kwargs: [
        {
            "attempt_id": "hidden-attempt",
            "participant_id": "participant-2",
            "status": "timeout",
            "item_refs": [{"source_activity_id": "hidden-without-receipt-id"}],
            "created_at": "2026-07-12T02:00:00Z",
        }
    ]

    projection = _projection(
        store,
        runtime_status={"enabled": True, "state": "failed", "code": "sidecar_stopped"},
    )

    assert projection["degraded"] is True
    assert projection["recent_recalls"] == [
        {
            "receipt_id": None,
            "participant_id": "participant-2",
            "status": "timeout",
            "created_at": "2026-07-12T02:00:00Z",
        }
    ]


def test_projection_defaults_to_disabled_without_runtime_status() -> None:
    projection = _projection(_Store())
    assert projection["enabled"] is False
    assert projection["degraded"] is False
    assert projection["runtime"]["state"] == "disabled"


def test_v2_projection_is_capability_gated_and_keeps_v1_compatibility() -> None:
    store = _Store()
    projection = build_room_memory_projection_v2(
        "conv-1",
        binding_store=store,
        governance_store=store,
        delivery_store=store,
        recall_store=store,
        advisory_store=store,
        runtime_status={"enabled": True, "state": "ready", "profile": "full-local"},
    )
    assert projection["schema_version"] == "room_memory_projection/v2"
    assert projection["profile"] == "full-local"
    assert projection["capabilities"] == {
        "hybrid": True,
        "message_ingest": True,
        "agentic_advisory": True,
    }
    # A legacy store has no message ledger; v2 remains bounded and does not
    # invent counts from the archival outbox.
    assert projection["sync"]["messages"] == {
        "backlog": 0,
        "pending": 0,
        "processing": 0,
        "failed": 0,
        "conflict": 0,
        "delivered": 0,
    }
