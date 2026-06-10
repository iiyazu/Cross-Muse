from __future__ import annotations

from pydantic import ValidationError

from xmuse_core.structuring.models import (
    ReviewGodTakeoverAction as ModelsTakeoverAction,
)
from xmuse_core.structuring.models import (
    ReviewGodTakeoverDecision as ModelsTakeoverDecision,
)
from xmuse_core.structuring.takeover_models import (
    ReviewGodTakeoverAction,
    ReviewGodTakeoverDecision,
    ReviewGodTakeoverEvidence,
)


def test_structuring_models_reexports_takeover_models() -> None:
    assert ModelsTakeoverAction is ReviewGodTakeoverAction
    assert ModelsTakeoverDecision is ReviewGodTakeoverDecision


def test_takeover_decision_keeps_action_alias_and_abandon_requirements() -> None:
    evidence = ReviewGodTakeoverEvidence(
        takeover_context_ref="logs/takeover/lane/context.json",
        change_ref="logs/takeover/lane/change.patch",
        verification_ref="logs/takeover/lane/verify.json",
        review_verdict_ref="review_plane.json#verdict-1",
        audit_event_ref="audit.jsonl#event-1",
        chat_card_ref="chat.db#card-1",
    )
    decision = ReviewGodTakeoverDecision(
        lane_id="lane-1",
        action="escalate",
        summary="Need a human decision.",
        evidence=evidence,
    )

    assert decision.action is ReviewGodTakeoverAction.ESCALATE_TO_HUMAN_OR_OUTER_GOD

    try:
        ReviewGodTakeoverDecision(
            lane_id="lane-1",
            action=ReviewGodTakeoverAction.ABANDON_LANE,
            summary="Cannot repair safely.",
            evidence=evidence,
        )
    except ValidationError as exc:
        assert "abandon_reason" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("abandon action without required fields was accepted")
