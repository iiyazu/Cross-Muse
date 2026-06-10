from __future__ import annotations

from typing import get_type_hints

from xmuse_core.platform.execution import persistent_review_session
from xmuse_core.platform.execution.review_god import (
    ConfiguredReviewPeerAttempt as LegacyConfiguredReviewPeerAttempt,
)
from xmuse_core.platform.execution.review_god import (
    PersistentReviewSessionLayer as LegacyPersistentReviewSessionLayer,
)


def test_persistent_review_session_module_owns_attempt_contract() -> None:
    attempt = persistent_review_session.ConfiguredReviewPeerAttempt(
        attempted=True,
        delivered=False,
        required_failed=True,
    )

    assert attempt.attempted is True
    assert attempt.delivered is False
    assert attempt.required_failed is True


def test_persistent_review_session_module_declares_receive_message_contract() -> None:
    hints = get_type_hints(
        persistent_review_session.PersistentReviewSessionLayer.receive_message
    )

    assert "god_session_id" in hints
    assert "return" in hints


def test_review_god_preserves_persistent_review_session_compat_exports() -> None:
    assert (
        LegacyConfiguredReviewPeerAttempt
        is persistent_review_session.ConfiguredReviewPeerAttempt
    )
    assert (
        LegacyPersistentReviewSessionLayer
        is persistent_review_session.PersistentReviewSessionLayer
    )
