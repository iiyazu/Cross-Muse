from __future__ import annotations

from typing import Any

_GRAY_BOX_CARD_TYPES = {
    "proposal",
    "mission_blueprint",
    "lane_graph",
    "feature_plan",
    "feature_graph_set",
    "blueprint_execution_started",
    "feature_plan_ready",
    "lane_graph_ready",
    "run_progress",
    "run_takeover",
    "run_terminal",
    "health_summary",
    "worklist_summary",
    "review_verdict",
    "takeover",
    "peer_request",
    "peer_result",
}


def normalize_envelope(
    envelope: dict[str, Any] | None,
    *,
    envelope_type: str = "message",
) -> dict[str, Any]:
    data = dict(envelope or {})
    data.setdefault("schema_version", 1)
    data.setdefault("type", envelope_type)
    if data["schema_version"] != 1:
        raise ValueError("unsupported envelope schema_version")
    if not isinstance(data["type"], str) or not data["type"]:
        raise ValueError("envelope type must be a non-empty string")
    if "cards" in data:
        data["cards"] = _normalize_cards(data.get("cards"))
    return data


def _normalize_cards(cards: Any) -> list[dict[str, Any]]:
    if cards is None:
        return []
    if not isinstance(cards, list):
        raise ValueError("envelope cards must be a list")
    return [_normalize_card(card) for card in cards]


def _normalize_card(card: Any) -> dict[str, Any]:
    if not isinstance(card, dict):
        raise ValueError("envelope card must be an object")
    data = dict(card)
    card_type = data.get("card_type")
    if not isinstance(card_type, str) or not card_type:
        raise ValueError("envelope card_type must be a non-empty string")
    if card_type in _GRAY_BOX_CARD_TYPES:
        for field in ("href", "api_href"):
            value = data.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"envelope {card_type} card requires {field}")
    return data


def mission_blueprint_envelope(
    *,
    title: str,
    body: str,
    acceptance_criteria: list[str],
    blueprint_ref: str,
    revision_of: str | None = None,
    references: list[str] | None = None,
) -> dict[str, Any]:
    if not title.strip():
        raise ValueError("blueprint title must be non-empty")
    if not body.strip():
        raise ValueError("blueprint body must be non-empty")
    criteria = [item.strip() for item in acceptance_criteria if item.strip()]
    if not criteria:
        raise ValueError("blueprint acceptance_criteria must contain at least one item")

    envelope = {
        "schema_version": 1,
        "type": "mission_blueprint",
        "title": title.strip(),
        "body": body.strip(),
        "acceptance_criteria": criteria,
        "blueprint_ref": blueprint_ref,
        "references": references or [],
    }
    if revision_of is not None:
        envelope["revision_of"] = revision_of
    return normalize_envelope(envelope, envelope_type="mission_blueprint")
