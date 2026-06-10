import json

from xmuse_core.chat.health_cards import build_run_health_chat_card


def test_run_health_chat_card_summarizes_operational_counts_without_embeds() -> None:
    card = build_run_health_chat_card(
        "conv-overnight",
        {
            "counts": {
                "live": 2,
                "stale": 1,
                "retrying": 3,
                "blocked": 4,
                "infra_failed": 5,
                "terminal": 6,
                "degraded_fallback": 8,
                "takeover_context_needed": 9,
                "unsafe_to_release_dependents": 7,
            },
            "groups": {
                "live": ["live-lane-a", "live-lane-b"],
                "stale": ["stale-lane"],
                "infra_failed": ["infra-lane"],
            },
            "processes": {"runner_pids": [1234], "mcp_pids": [5678]},
            "warnings": [{"message": "verbose runtime warning belongs behind API link"}],
            "review_rework_alignment": {
                "operator_attention_samples": [{"lane_id": "retry-lane"}]
            },
            "takeover_context": {
                "needed_lanes": [{"lane_id": "takeover-lane", "reason": "stale_worker"}]
            },
            "peer_delivery": {
                "counts_by_delivery_mode": {
                    "configured_peer": 2,
                    "one_shot_fallback": 1,
                    "required_peer_failed": 1,
                },
                "required_peer_failures": [
                    {"lane_id": "required-peer-lane", "peer_degraded_reason": "ensure_failed"}
                ],
                "degraded_or_fallback_lanes": [
                    {"lane_id": "fallback-lane", "peer_delivery_mode": "one_shot_fallback"}
                ],
            },
        },
        created_at="2026-05-30T12:00:00Z",
    )

    payload = card.model_dump(mode="json")

    assert payload["card_type"] == "health_summary"
    assert payload["source_id"] == "run_health"
    assert payload["href"] == "/dashboard/health"
    assert payload["api_href"] == "/api/run-health"
    assert payload["counts"] == {
        "live": 2,
        "stale": 1,
        "retrying": 3,
        "blocked": 4,
        "infra_failed": 5,
        "terminal": 6,
        "degraded_fallback": 8,
        "required_peer_failures": 1,
        "takeover_context_needed": 9,
    }
    assert payload["summary"] == (
        "2 live, 1 stale, 3 retrying, 4 blocked, 5 infra failed, 6 terminal, "
        "8 degraded fallback, 1 required peer failures, 9 takeover context needed"
    )
    assert payload["status"] == "degraded"
    assert payload["metadata"] == {
        "peer_delivery_modes": {
            "configured_peer": 2,
            "one_shot_fallback": 1,
            "required_peer_failed": 1,
        }
    }

    encoded = json.dumps(payload)
    assert "live-lane-a" not in encoded
    assert "required-peer-lane" not in encoded
    assert "takeover-lane" not in encoded
    assert "verbose runtime warning" not in encoded
    assert "runner_pids" not in encoded
    assert "operator_attention_samples" not in encoded


def test_run_health_chat_card_defaults_missing_counts_to_zero() -> None:
    card = build_run_health_chat_card(
        "conv-overnight",
        {"counts": {"live": 1}},
        created_at="2026-05-30T12:00:00Z",
    )

    assert card.counts == {
        "live": 1,
        "stale": 0,
        "retrying": 0,
        "blocked": 0,
        "infra_failed": 0,
        "terminal": 0,
        "degraded_fallback": 0,
        "required_peer_failures": 0,
        "takeover_context_needed": 0,
    }
    assert card.status == "ok"
