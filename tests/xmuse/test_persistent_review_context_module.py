from __future__ import annotations

from pathlib import Path

from xmuse_core.platform.execution import persistent_review_context
from xmuse_core.platform.execution.review_god import (
    _persistent_review_prompt as legacy_persistent_review_prompt,
)
from xmuse_core.platform.execution.review_god import (
    _review_request_id as legacy_review_request_id,
)


def test_persistent_review_context_module_owns_review_request_ids() -> None:
    request_id = persistent_review_context.review_request_id(
        "review god/session",
        "lane:conv:graph:feature",
    )

    assert request_id == "review-review-god-session-lane-conv-graph-feature"


def test_persistent_review_context_module_appends_routing_block() -> None:
    prompt = persistent_review_context.persistent_review_prompt(
        "Review this lane.  \n",
        review_request_id="review-1",
        identity_key="feature-review",
    )

    assert prompt.startswith("Review this lane.\n\n## Persistent Review Routing")
    assert "- review_request_id: review-1" in prompt
    assert "- persistent_review_identity: feature-review" in prompt


def test_persistent_review_context_reports_missing_chat_db(tmp_path: Path) -> None:
    assert persistent_review_context.conversation_history_for_prompt(
        "conv-1",
        xmuse_root=tmp_path,
    ) == "## Conversation History\n\n- unavailable: chat.db missing"


def test_review_god_preserves_persistent_review_compat_exports() -> None:
    assert legacy_review_request_id is persistent_review_context.review_request_id
    assert (
        legacy_persistent_review_prompt
        is persistent_review_context.persistent_review_prompt
    )
