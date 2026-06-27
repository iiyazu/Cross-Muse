from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from xmuse_core.providers.adapters.base import ProviderInvocationResult
from xmuse_core.providers.models import ProviderId
from xmuse_core.structuring.models import ReviewDecision

A2A_PLATFORM_REVIEW_VERDICT_TYPE = "platform_review_verdict"
A2A_PLATFORM_REVIEW_VERDICT_METADATA_KEY = "xmuse_platform_review_verdict"
PlatformReviewDecision = Literal["merge", "rework", "terminate"]


class A2APlatformReviewVerdictError(ValueError):
    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class A2APlatformReviewVerdict:
    lane_id: str
    decision: ReviewDecision
    summary: str
    evidence_refs: list[str]


def build_a2a_platform_review_verdict_envelope(
    *,
    lane_id: str,
    decision: PlatformReviewDecision,
    summary: str,
    evidence_refs: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "type": A2A_PLATFORM_REVIEW_VERDICT_TYPE,
        "lane_id": _required_text(lane_id, "lane_id"),
        "decision": _decision(decision).value,
        "summary": _required_text(summary, "summary"),
        "evidence_refs": _evidence_refs(evidence_refs),
        "authority": "review_plane/lane_state",
        "a2a_is_authority": False,
    }


def a2a_platform_review_verdict_from_provider_result(
    provider_result: ProviderInvocationResult | None,
    *,
    expected_lane_id: str,
) -> A2APlatformReviewVerdict | None:
    if provider_result is None or provider_result.provider_id is not ProviderId.A2A:
        return None
    diagnostic = provider_result.diagnostic_payload
    metadata = diagnostic.get("a2a_metadata")
    if not isinstance(metadata, dict):
        return None
    raw_envelope = metadata.get(A2A_PLATFORM_REVIEW_VERDICT_METADATA_KEY)
    if raw_envelope is None:
        return None
    if not isinstance(raw_envelope, dict):
        raise A2APlatformReviewVerdictError(
            "invalid_platform_review_verdict",
            A2A_PLATFORM_REVIEW_VERDICT_METADATA_KEY,
        )
    return platform_review_verdict_decision(
        raw_envelope,
        expected_lane_id=expected_lane_id,
    )


def platform_review_verdict_decision(
    envelope: dict[str, Any],
    *,
    expected_lane_id: str,
) -> A2APlatformReviewVerdict:
    if envelope.get("type") != A2A_PLATFORM_REVIEW_VERDICT_TYPE:
        raise A2APlatformReviewVerdictError(
            "missing_platform_review_verdict",
            "envelope type is not platform_review_verdict",
        )
    lane_id = _required_text(envelope.get("lane_id"), "lane_id")
    expected = _required_text(expected_lane_id, "expected_lane_id")
    if lane_id != expected:
        raise A2APlatformReviewVerdictError(
            "platform_review_verdict_mismatch",
            f"lane_id={lane_id} expected={expected}",
        )
    return A2APlatformReviewVerdict(
        lane_id=lane_id,
        decision=_decision(envelope.get("decision")),
        summary=_required_text(envelope.get("summary"), "summary"),
        evidence_refs=_evidence_refs(envelope.get("evidence_refs")),
    )


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise A2APlatformReviewVerdictError(f"invalid_{field_name}", field_name)
    text = value.strip()
    if not text:
        raise A2APlatformReviewVerdictError(f"missing_{field_name}", field_name)
    return text


def _decision(value: object) -> ReviewDecision:
    if value == ReviewDecision.MERGE.value:
        return ReviewDecision.MERGE
    if value == ReviewDecision.REWORK.value:
        return ReviewDecision.REWORK
    if value == ReviewDecision.TERMINATE.value:
        return ReviewDecision.TERMINATE
    raise A2APlatformReviewVerdictError("invalid_review_decision", str(value))


def _evidence_refs(value: object) -> list[str]:
    if not isinstance(value, list):
        raise A2APlatformReviewVerdictError("invalid_evidence_refs", "evidence_refs")
    refs = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    if not refs:
        raise A2APlatformReviewVerdictError("missing_evidence_refs", "evidence_refs")
    return refs
