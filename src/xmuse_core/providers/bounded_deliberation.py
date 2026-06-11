from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from xmuse_core.chat.protocol_v2 import GodSpeechAct, GodSpeechActMessageV1
from xmuse_core.providers.models import TaskCapability
from xmuse_core.providers.policy import ProviderPolicyDecision

_STATE_WRITE_KEYS = (
    "state_write",
    "state_write_requested",
    "durable_writes",
    "durable_state_write",
    "mutations",
    "writeback",
)
_CANONICAL_BOUNDED_SPEECH_ACTS = frozenset({"propose", "ask", "challenge"})


def normalize_bounded_deliberation_output(
    *,
    decision: ProviderPolicyDecision,
    output: Mapping[str, Any],
    conversation_id: str,
    thread_id: str,
    targets: Sequence[str],
    lane_scope: str | None = None,
) -> GodSpeechActMessageV1:
    """Normalize bounded provider output into a GOD speech-act artifact.

    This is a contract boundary only. It does not write to chat storage or any
    durable xmuse state.
    """

    _validate_bounded_decision(decision)
    _reject_state_write(output)

    speech_act = _coerce_speech_act(output.get("speech_act"))
    if (
        speech_act.value not in decision.allowed_speech_acts
        or speech_act.value not in _CANONICAL_BOUNDED_SPEECH_ACTS
    ):
        raise ValueError(f"speech_act {speech_act.value!r} is not allowed")

    payload = _coerce_payload(output.get("payload"))
    references = _coerce_text_list(output.get("references"))
    memory_refs = _coerce_text_list(output.get("memory_refs"))
    causal_parent_id = _optional_text(output.get("causal_parent_id"))
    confidence = _coerce_confidence(output.get("confidence"))
    sender_god = decision.provider_profile_ref
    message_id = _message_id(
        sender_god=sender_god,
        conversation_id=conversation_id,
        thread_id=thread_id,
        speech_act=speech_act,
        payload=payload,
        references=references,
        causal_parent_id=causal_parent_id,
        lane_scope=lane_scope,
    )

    return GodSpeechActMessageV1(
        message_id=message_id,
        conversation_id=conversation_id,
        thread_id=thread_id,
        sender_god=sender_god,
        targets=list(targets),
        speech_act=speech_act,
        references=references,
        causal_parent_id=causal_parent_id,
        lane_scope=lane_scope,
        confidence=confidence,
        memory_refs=memory_refs,
        payload=payload,
    )


def _validate_bounded_decision(decision: ProviderPolicyDecision) -> None:
    if decision.task_type is not TaskCapability.BOUNDED_DELIBERATION:
        raise ValueError("decision.task_type must be bounded_deliberation")
    if decision.state_write_allowed:
        raise ValueError("bounded deliberation decision must not allow state-write")
    if not decision.allowed_speech_acts:
        raise ValueError("bounded deliberation decision requires allowed_speech_acts")
    if not set(decision.allowed_speech_acts).issubset(_CANONICAL_BOUNDED_SPEECH_ACTS):
        raise ValueError("bounded deliberation decision contains speech acts that are not allowed")


def _reject_state_write(output: Mapping[str, Any]) -> None:
    for key in _STATE_WRITE_KEYS:
        if output.get(key):
            raise ValueError(f"bounded deliberation output requested state-write via {key}")


def _coerce_speech_act(value: Any) -> GodSpeechAct:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("speech_act must be a non-empty string")
    return GodSpeechAct(value.strip())


def _coerce_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError("payload must be a non-empty object")
    return dict(value)


def _coerce_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, str):
        raise ValueError("text list fields must be lists of strings")
    items = [str(item).strip() for item in value if str(item).strip()]
    return items


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_confidence(value: Any) -> float:
    if value is None:
        return 0.5
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("confidence must be numeric")
    return float(value)


def _message_id(
    *,
    sender_god: str,
    conversation_id: str,
    thread_id: str,
    speech_act: GodSpeechAct,
    payload: Mapping[str, Any],
    references: list[str],
    causal_parent_id: str | None,
    lane_scope: str | None,
) -> str:
    digest_payload = {
        "sender_god": sender_god,
        "conversation_id": conversation_id,
        "thread_id": thread_id,
        "speech_act": speech_act.value,
        "payload": payload,
        "references": references,
        "causal_parent_id": causal_parent_id,
        "lane_scope": lane_scope,
    }
    digest = hashlib.sha256(
        json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return f"bounded-deliberation:{digest[:24]}"
