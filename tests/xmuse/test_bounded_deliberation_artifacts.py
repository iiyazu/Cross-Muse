from __future__ import annotations

import pytest

from xmuse_core.chat.protocol_v2 import GodSpeechAct
from xmuse_core.providers.bounded_deliberation import (
    normalize_bounded_deliberation_output,
)
from xmuse_core.providers.models import ProviderId, ProviderProfileId, RiskTier, TaskCapability
from xmuse_core.providers.policy import ProviderPolicyDecision


def _decision() -> ProviderPolicyDecision:
    return ProviderPolicyDecision(
        provider_id=ProviderId.OPENCODE,
        profile_id=ProviderProfileId.DEEPSEEK_FLASH_WORKER,
        task_type=TaskCapability.BOUNDED_DELIBERATION,
        lane_risk=RiskTier.LOW,
        peer_type="deliberation",
        selected_model="deepseek-v4-flash",
        selection_reason="Bounded OpenCode deliberation test decision.",
        allowed_speech_acts=("propose", "ask", "challenge"),
        state_write_allowed=False,
    )


def test_bounded_deliberation_output_normalizes_allowed_speech_act() -> None:
    message = normalize_bounded_deliberation_output(
        decision=_decision(),
        output={
            "speech_act": "challenge",
            "payload": {"question": "Which server-side evidence proves this?"},
            "references": ["github:pr/12"],
            "confidence": 0.74,
        },
        conversation_id="conv-opencode",
        thread_id="thread-evidence",
        targets=["codex.god"],
        lane_scope="lane-github-truth",
    )

    assert message.version == "god_speech_act_message.v1"
    assert message.sender_god == "opencode.deepseek_flash_worker"
    assert message.speech_act is GodSpeechAct.CHALLENGE
    assert message.targets == ["codex.god"]
    assert message.references == ["github:pr/12"]
    assert message.lane_scope == "lane-github-truth"
    assert message.confidence == 0.74
    assert message.message_id.startswith("bounded-deliberation:")


@pytest.mark.parametrize("speech_act", ["object", "vote", "decide", "evidence", "handoff"])
def test_bounded_deliberation_output_rejects_forbidden_speech_acts(
    speech_act: str,
) -> None:
    with pytest.raises(ValueError, match="not allowed"):
        normalize_bounded_deliberation_output(
            decision=_decision(),
            output={
                "speech_act": speech_act,
                "payload": {"body": "Escalate authority."},
                "references": ["blueprint:bp-1"],
            },
            conversation_id="conv-opencode",
            thread_id="thread-evidence",
            targets=["codex.god"],
        )


@pytest.mark.parametrize(
    "output",
    [
        {"speech_act": "propose", "payload": {"body": "Mutate state."}, "state_write": True},
        {
            "speech_act": "ask",
            "payload": {"question": "Can I write?"},
            "durable_writes": ["feature_lanes.json"],
        },
        {
            "speech_act": "propose",
            "payload": {"body": "Write back."},
            "writeback": {"kind": "lane_status"},
        },
    ],
)
def test_bounded_deliberation_output_rejects_direct_state_writes(
    output: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="state-write"):
        normalize_bounded_deliberation_output(
            decision=_decision(),
            output=output,
            conversation_id="conv-opencode",
            thread_id="thread-evidence",
            targets=["codex.god"],
        )


def test_bounded_deliberation_output_requires_bounded_decision() -> None:
    decision = _decision().model_copy(update={"task_type": TaskCapability.REVIEW})

    with pytest.raises(ValueError, match="bounded_deliberation"):
        normalize_bounded_deliberation_output(
            decision=decision,
            output={"speech_act": "propose", "payload": {"body": "Review it."}},
            conversation_id="conv-opencode",
            thread_id="thread-evidence",
            targets=["codex.god"],
        )


def test_bounded_deliberation_rejects_forbidden_act_from_bad_policy() -> None:
    decision = _decision().model_copy(
        update={"allowed_speech_acts": ("propose", "ask", "challenge", "decide")}
    )

    with pytest.raises(ValueError, match="not allowed"):
        normalize_bounded_deliberation_output(
            decision=decision,
            output={"speech_act": "decide", "payload": {"body": "Merge it."}},
            conversation_id="conv-opencode",
            thread_id="thread-evidence",
            targets=["codex.god"],
        )
