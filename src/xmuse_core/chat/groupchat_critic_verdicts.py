from __future__ import annotations

from typing import Any, Literal

GROUPCHAT_CRITIC_VERDICT_ENVELOPE_TYPE = "groupchat_critic_verdict"
GroupchatCriticDecision = Literal["clearance", "blocked"]


class GroupchatCriticVerdictError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def groupchat_critic_verdict_decision(
    envelope: dict[str, Any] | None,
    *,
    expected_proposal_id: str,
) -> GroupchatCriticDecision:
    if not isinstance(envelope, dict):
        raise GroupchatCriticVerdictError("missing_critic_verdict", "message has no envelope")
    if envelope.get("type") != GROUPCHAT_CRITIC_VERDICT_ENVELOPE_TYPE:
        raise GroupchatCriticVerdictError(
            "missing_critic_verdict",
            "message envelope is not groupchat_critic_verdict",
        )
    _matches(envelope.get("proposal_id"), expected_proposal_id, "proposal_id")
    _required_text(envelope.get("summary"), "summary")
    _evidence_refs(envelope.get("evidence_refs"))
    return _decision(envelope.get("decision"))


def _matches(value: object, expected: str, field_name: str) -> None:
    actual = _required_text(value, field_name)
    if actual != expected:
        raise GroupchatCriticVerdictError(
            "critic_verdict_mismatch",
            f"{field_name}={actual} expected={expected}",
        )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise GroupchatCriticVerdictError(f"invalid_{field_name}", field_name)
    text = value.strip()
    if not text:
        raise GroupchatCriticVerdictError(f"missing_{field_name}", field_name)
    return text


def _decision(value: object) -> GroupchatCriticDecision:
    if value == "clearance" or value == "blocked":
        return value
    raise GroupchatCriticVerdictError("invalid_critic_decision", str(value))


def _evidence_refs(value: object) -> list[str]:
    if not isinstance(value, list):
        raise GroupchatCriticVerdictError("invalid_evidence_refs", "evidence_refs")
    refs = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not refs:
        raise GroupchatCriticVerdictError("missing_evidence_refs", "evidence_refs")
    return refs
