from __future__ import annotations

from xmuse_core.agents.protocol import StdoutMessage
from xmuse_core.platform.execution import persistent_review_delivery
from xmuse_core.platform.execution.review_god import (
    PersistentReviewReceiveError as LegacyPersistentReviewReceiveError,
)
from xmuse_core.platform.execution.review_god import (
    _persistent_verdict_payload as legacy_persistent_verdict_payload,
)


def test_persistent_review_delivery_module_owns_verdict_payload_parsing() -> None:
    message = StdoutMessage(
        type="result",
        message="done",
        artifacts={
            "review_verdict": {
                "decision": "patch-forward",
                "summary": "Needs a bounded follow-up patch.",
            }
        },
    )

    assert persistent_review_delivery.persistent_verdict_payload(message) == {
        "decision": "rework",
        "summary": "Needs a bounded follow-up patch.",
    }


def test_persistent_review_delivery_rejects_non_result_messages() -> None:
    message = StdoutMessage(type="progress", message="still working")

    assert persistent_review_delivery.persistent_verdict_payload(message) is None


def test_review_god_preserves_persistent_review_delivery_compat_exports() -> None:
    assert (
        legacy_persistent_verdict_payload
        is persistent_review_delivery.persistent_verdict_payload
    )
    assert (
        LegacyPersistentReviewReceiveError
        is persistent_review_delivery.PersistentReviewReceiveError
    )
