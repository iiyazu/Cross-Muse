from __future__ import annotations

from typing import Any, Literal

REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE = "review_trigger_verdict"
ReviewTriggerDecision = Literal["dispatch_allowed", "blocked"]


class ReviewTriggerVerdictError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def build_review_trigger_verdict_envelope(
    *,
    review_trigger_inbox_id: str,
    source_message_id: str,
    proposal_id: str,
    decision: ReviewTriggerDecision,
    summary: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE,
        "review_trigger_inbox_id": _required_text(
            review_trigger_inbox_id,
            "review_trigger_inbox_id",
        ),
        "source_message_id": _required_text(source_message_id, "source_message_id"),
        "proposal_id": _required_text(proposal_id, "proposal_id"),
        "decision": _decision(decision),
        "summary": _required_text(summary, "summary"),
        "evidence_refs": _evidence_refs(evidence_refs),
    }


def review_trigger_verdict_decision(
    envelope: dict[str, Any] | None,
    *,
    expected_inbox_item_id: str,
    expected_source_message_id: str,
    expected_proposal_id: str,
) -> ReviewTriggerDecision:
    if not isinstance(envelope, dict):
        raise ReviewTriggerVerdictError("missing_review_verdict", "message has no envelope")
    if envelope.get("type") != REVIEW_TRIGGER_VERDICT_ENVELOPE_TYPE:
        raise ReviewTriggerVerdictError(
            "missing_review_verdict",
            "message envelope is not review_trigger_verdict",
        )
    _matches(
        envelope.get("review_trigger_inbox_id"),
        expected_inbox_item_id,
        "review_trigger_inbox_id",
    )
    _matches(envelope.get("source_message_id"), expected_source_message_id, "source_message_id")
    _matches(envelope.get("proposal_id"), expected_proposal_id, "proposal_id")
    _required_text(envelope.get("summary"), "summary")
    _evidence_refs(envelope.get("evidence_refs"))
    return _decision(envelope.get("decision"))


def _matches(value: object, expected: str, field_name: str) -> None:
    actual = _required_text(value, field_name)
    if actual != expected:
        raise ReviewTriggerVerdictError(
            "review_verdict_mismatch",
            f"{field_name}={actual} expected={expected}",
        )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise ReviewTriggerVerdictError(f"invalid_{field_name}", field_name)
    text = value.strip()
    if not text:
        raise ReviewTriggerVerdictError(f"missing_{field_name}", field_name)
    return text


def _decision(value: object) -> ReviewTriggerDecision:
    if value == "dispatch_allowed" or value == "blocked":
        return value
    raise ReviewTriggerVerdictError("invalid_review_decision", str(value))


def _evidence_refs(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ReviewTriggerVerdictError("invalid_evidence_refs", "evidence_refs")
    refs = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not refs:
        raise ReviewTriggerVerdictError("missing_evidence_refs", "evidence_refs")
    return refs
