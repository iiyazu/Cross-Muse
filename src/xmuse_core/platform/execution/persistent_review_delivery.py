from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.platform.execution.review import infer_review_fallback
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.structuring.models import ReviewDecision

_MAX_REVIEW_HISTORY = 8


class PersistentReviewReceiveLayer(Protocol):
    async def receive_message(self, god_session_id: str) -> StdoutMessage | None: ...


class PersistentReviewReceiveError(RuntimeError):
    pass


async def receive_persistent_review_result(
    persistent_session_layer: PersistentReviewReceiveLayer,
    *,
    god_session_id: str,
    timeout_s: float,
) -> StdoutMessage | None:
    deadline = time.monotonic() + timeout_s
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError()
        message = await asyncio.wait_for(
            persistent_session_layer.receive_message(god_session_id),
            timeout=remaining,
        )
        if message is None:
            return None
        if message.type == "result":
            return message
        if message.type == "error":
            raise PersistentReviewReceiveError()


async def apply_persistent_review_message(
    *,
    lane_id: str,
    sm: LaneStateMachine,
    message: StdoutMessage,
    stable_verdict_id: Callable[[str], str],
    ingest_merge_verdict: Callable[[str, str, list[str] | None], None],
    ingest_rework_verdict: Callable[[str, str, list[str] | None], None],
    on_reviewed: Callable[[str], Awaitable[None]],
    on_rejected: Callable[[str], Awaitable[None]],
    review_request_id: str,
    persistent_review_identity: str,
    extra_metadata: dict[str, Any] | None = None,
    evidence_refs: list[str] | None = None,
) -> bool:
    verdict = persistent_verdict_payload(message)
    if verdict is None:
        text = _review_text_from_message(message)
        if not text:
            return False
        decision, summary, reason = infer_review_fallback(text)
    else:
        decision = "reviewed" if verdict["decision"] == ReviewDecision.MERGE.value else "rejected"
        summary = verdict["summary"]
        reason = "persistent_result"

    refs = _dedupe_refs(
        evidence_refs or _string_list(sm.get_lane(lane_id).get("review_evidence_refs"))
    )
    if decision == "reviewed":
        verdict_id = stable_verdict_id(lane_id)
        sm.transition(
            lane_id,
            "reviewed",
            metadata=review_metadata(
                lane=sm.get_lane(lane_id),
                decision=ReviewDecision.MERGE.value,
                summary=summary,
                fallback="persistent",
                fallback_reason=reason,
            )
            | {
                "review_verdict_id": verdict_id,
                "review_evidence_refs": refs,
                "review_delivery_mode": "persistent",
                "persistent_review_degraded": False,
                "review_request_id": review_request_id,
                "persistent_review_identity": persistent_review_identity,
            }
            | (extra_metadata or {}),
        )
        ingest_merge_verdict(lane_id, summary, refs)
        await on_reviewed(lane_id)
        return True

    sm.transition(
        lane_id,
        "rejected",
        metadata=review_metadata(
            lane=sm.get_lane(lane_id),
            decision=ReviewDecision.REWORK.value,
            summary=summary,
            fallback="persistent",
            fallback_reason=reason,
        )
        | {
            "review_evidence_refs": refs,
            "review_delivery_mode": "persistent",
            "persistent_review_degraded": False,
            "review_request_id": review_request_id,
            "persistent_review_identity": persistent_review_identity,
        }
        | (extra_metadata or {}),
    )
    ingest_rework_verdict(lane_id, summary, refs)
    await on_rejected(lane_id)
    return True


def review_metadata(
    *,
    lane: dict[str, Any],
    decision: str,
    summary: str,
    fallback: str,
    fallback_reason: str,
) -> dict[str, Any]:
    entry = {
        "decision": decision,
        "summary": summary,
        "fallback": fallback,
        "fallback_reason": fallback_reason,
        "recorded_at": time.time(),
    }
    history = lane.get("review_history")
    if not isinstance(history, list):
        history = []
    return {
        "review_decision": decision,
        "review_summary": summary,
        "review_fallback": fallback,
        "review_fallback_reason": fallback_reason,
        "review_history": [*history, entry][-_MAX_REVIEW_HISTORY:],
    }


def record_persistent_review_degraded(
    sm: LaneStateMachine,
    lane_id: str,
    *,
    reason: str,
    review_request_id: str | None = None,
) -> None:
    metadata: dict[str, Any] = {
        "review_delivery_mode": "one_shot_fallback",
        "persistent_review_degraded": True,
        "persistent_review_degraded_reason": reason,
    }
    if review_request_id is not None:
        metadata["review_request_id"] = review_request_id
    sm.update_metadata(lane_id, metadata)


def persistent_verdict_payload(message: StdoutMessage) -> dict[str, str] | None:
    if message.type != "result":
        return None
    payload = message.artifacts.get("review_verdict")
    if not isinstance(payload, dict):
        return None
    decision = str(payload.get("decision") or "").strip().lower()
    if decision == ReviewDecision.PATCH_FORWARD.value:
        decision = ReviewDecision.REWORK.value
    if decision == ReviewDecision.TERMINATE.value:
        decision = ReviewDecision.REWORK.value
    if decision not in {ReviewDecision.MERGE.value, ReviewDecision.REWORK.value}:
        return None
    summary = str(payload.get("summary") or "").strip()
    if not summary:
        return None
    return {"decision": decision, "summary": summary}


def _review_text_from_message(message: StdoutMessage) -> str:
    candidates = [
        message.message,
        message.artifacts.get("reply_text"),
        message.artifacts.get("message"),
        message.artifacts.get("result"),
        message.artifacts.get("stdout"),
    ]
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _dedupe_refs(value: list[str]) -> list[str]:
    refs: list[str] = []
    seen: set[str] = set()
    for item in value:
        ref = item.strip()
        if not ref or ref in seen:
            continue
        seen.add(ref)
        refs.append(ref)
    return refs
