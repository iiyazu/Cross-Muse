import json

from xmuse_core.agents.persistent_peer import PeerHandle, PeerRequestResult
from xmuse_core.chat.peer_request_cards import (
    build_peer_request_chat_card,
    build_peer_result_chat_card,
)


def _peer_handle() -> PeerHandle:
    return PeerHandle(
        conversation_id="conv-peer",
        participant_id="part-review",
        god_session_id="god-review",
        role="review",
        cli_kind="codex",
        runtime="codex",
        model="gpt-5.5",
        prompt_fingerprint="sha256:abc",
        worktree="/tmp/worktree",
        feature_scope_id="feature-alpha",
    )


def test_peer_request_chat_card_contract_is_compact_and_linkable() -> None:
    card = build_peer_request_chat_card(
        _peer_handle(),
        request_id="req-123",
        message_type="review",
        created_at="2026-05-31T09:00:00Z",
        lane_id="lane-1",
        feature_id="feature-alpha",
        graph_id="graph-alpha",
        prompt="large request prompt belongs behind the drill-down",
        context={"raw": "large context belongs behind the drill-down"},
    )

    payload = card.model_dump(mode="json")

    assert payload["card_type"] == "peer_request"
    assert payload["source_id"] == "req-123"
    assert payload["title"] == "Review request"
    assert payload["summary"] == "Sent review request req-123 to review peer"
    assert payload["status"] == "sent"
    assert payload["href"] == (
        "/dashboard/peer-chat/conversations/conv-peer#peer-request-req-123"
    )
    assert payload["api_href"] == "/api/peer-requests/req-123"
    assert payload["counts"] == {
        "lane_refs": 1,
        "feature_refs": 1,
    }
    assert payload["metadata"] == {
        "request_id": "req-123",
        "message_type": "review",
        "participant_id": "part-review",
        "god_session_id": "god-review",
        "role": "review",
        "cli_kind": "codex",
        "runtime": "codex",
        "model": "gpt-5.5",
        "feature_scope_id": "feature-alpha",
        "lane_id": "lane-1",
        "feature_id": "feature-alpha",
        "graph_id": "graph-alpha",
    }

    encoded = json.dumps(payload)
    assert "large request prompt" not in encoded
    assert "large context" not in encoded
    assert "prompt_fingerprint" not in encoded
    assert "/tmp/worktree" not in encoded


def test_peer_result_chat_card_contract_maps_status_and_keeps_artifacts_linked() -> None:
    card = build_peer_result_chat_card(
        _peer_handle(),
        PeerRequestResult(
            status="peer_error",
            request_id="req-123",
            reason="review_rejected",
            error_message="verbose failure output belongs behind the drill-down",
        ),
        message_type="review",
        created_at="2026-05-31T09:05:00Z",
        lane_id="lane-1",
        feature_id="feature-alpha",
        graph_id="graph-alpha",
    )

    payload = card.model_dump(mode="json")

    assert payload["card_type"] == "peer_result"
    assert payload["source_id"] == "req-123"
    assert payload["title"] == "Review result"
    assert payload["summary"] == "Peer review request req-123 finished with peer_error"
    assert payload["status"] == "failed"
    assert payload["href"] == (
        "/dashboard/peer-chat/conversations/conv-peer#peer-result-req-123"
    )
    assert payload["api_href"] == "/api/peer-requests/req-123/result"
    assert payload["counts"] == {
        "lane_refs": 1,
        "feature_refs": 1,
    }
    assert payload["metadata"] == {
        "request_id": "req-123",
        "message_type": "review",
        "participant_id": "part-review",
        "god_session_id": "god-review",
        "role": "review",
        "cli_kind": "codex",
        "runtime": "codex",
        "model": "gpt-5.5",
        "feature_scope_id": "feature-alpha",
        "lane_id": "lane-1",
        "feature_id": "feature-alpha",
        "graph_id": "graph-alpha",
        "result_status": "peer_error",
        "reason": "review_rejected",
    }

    encoded = json.dumps(payload)
    assert "verbose failure output" not in encoded
    assert "artifacts" not in encoded
