"""Proposal drafting, review, guardrail, and landing helpers."""

from xmuse_core.self_evolution.proposal.drafter import (
    dedup_signal_refs,
    draft,
    has_duplicate_evolution,
)
from xmuse_core.self_evolution.proposal.reviewer import (
    guardrail_check,
    land,
    review,
)

__all__ = [
    "dedup_signal_refs",
    "draft",
    "guardrail_check",
    "has_duplicate_evolution",
    "land",
    "review",
]
