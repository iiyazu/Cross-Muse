from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.envelopes import normalize_envelope
from xmuse_core.chat.models import ChatCard

CONTRACT_ROOT = Path("tests/fixtures/xmuse/contracts")


def _fixture(relative_path: str) -> dict:
    return json.loads((CONTRACT_ROOT / relative_path).read_text(encoding="utf-8"))


def test_normalize_envelope_supports_compact_timeline_cards() -> None:
    envelope = normalize_envelope(
        {
            "type": "message",
            "cards": [
                {
                    "card_type": "feature_plan",
                    "source_id": "plan-alpha",
                    "title": "Alpha feature plan",
                    "summary": "2 features, 1 blocked",
                    "status": "active",
                    "href": "/dashboard/feature-graph-sets/graph-set-alpha#feature-plan",
                    "api_href": "/api/feature-graph-sets/graph-set-alpha",
                    "counts": {"features": 2, "blocked_features": 1},
                },
                {
                    "card_type": "review_verdict",
                    "source_id": "verdict-alpha",
                    "title": "Review verdict",
                    "summary": "Rework before merge",
                    "status": "finalized",
                    "href": "/dashboard/review-verdicts/verdict-alpha",
                    "api_href": "/api/review-verdicts/verdict-alpha",
                },
            ],
        }
    )

    assert envelope == {
        "schema_version": 1,
        "type": "message",
        "cards": [
            {
                "card_type": "feature_plan",
                "source_id": "plan-alpha",
                "title": "Alpha feature plan",
                "summary": "2 features, 1 blocked",
                "status": "active",
                "href": "/dashboard/feature-graph-sets/graph-set-alpha#feature-plan",
                "api_href": "/api/feature-graph-sets/graph-set-alpha",
                "counts": {"features": 2, "blocked_features": 1},
            },
            {
                "card_type": "review_verdict",
                "source_id": "verdict-alpha",
                "title": "Review verdict",
                "summary": "Rework before merge",
                "status": "finalized",
                "href": "/dashboard/review-verdicts/verdict-alpha",
                "api_href": "/api/review-verdicts/verdict-alpha",
            },
        ],
    }


def test_normalize_envelope_rejects_gray_box_cards_without_drilldown_links() -> None:
    with pytest.raises(ValueError, match="api_href"):
        normalize_envelope(
            {
                "type": "message",
                "cards": [
                    {
                        "card_type": "takeover",
                        "source_id": "lane-alpha",
                        "title": "Takeover needed",
                        "summary": "Lane alpha needs operator context",
                        "status": "needed",
                        "href": "/dashboard/lanes/lane-alpha#takeover",
                    }
                ],
            }
        )


def test_chat_card_accepts_b4_timeline_contract_types() -> None:
    for card_type in ("feature_plan", "review_verdict", "takeover"):
        card = ChatCard(
            id=f"card-{card_type}",
            conversation_id="conv-alpha",
            card_type=card_type,
            source_id=f"source-{card_type}",
            title=f"title-{card_type}",
            summary=f"summary-{card_type}",
            status="active",
            href=f"/dashboard/{card_type}/source-{card_type}",
            api_href=f"/api/{card_type}/source-{card_type}",
            created_at="2026-05-31T12:00:00Z",
        )

        assert card.card_type == card_type


def test_chat_card_accepts_s0_lane_blocked_contract_type() -> None:
    for card_type in ("lane_blocked", "takeover_requested"):
        card = ChatCard(
            id=f"card-{card_type}",
            conversation_id="conv-alpha",
            card_type=card_type,
            source_id=f"intent-{card_type}",
            title=card_type.replace("_", " ").title(),
            summary="The S0 compact card contract is renderable.",
            status="blocked",
            href=f"/dashboard/{card_type}/source",
            api_href=f"/api/dashboard/{card_type}/source",
            created_at="2026-06-02T00:06:00Z",
        )

        assert card.card_type == card_type


def test_chat_card_normalizes_real_s0_card_fixture_shape() -> None:
    payload = _fixture("cards/lane_blocked.v1.json")

    card = ChatCard.model_validate(payload)

    assert card.id == "card_intent_lane_blocked_demo"
    assert card.source_id == "intent_lane_blocked_demo"
    assert card.href == "/api/dashboard/lanes/lane_demo"
    assert card.api_href == "/api/dashboard/lanes/lane_demo"
