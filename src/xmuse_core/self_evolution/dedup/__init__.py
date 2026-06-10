"""Proposal deduplication identity and continuation records."""

from xmuse_core.self_evolution.dedup.identity import (
    dedup_identity,
    dedup_signal_refs,
    has_duplicate_evolution,
    record_dedup_continue,
)

__all__ = [
    "dedup_identity",
    "dedup_signal_refs",
    "has_duplicate_evolution",
    "record_dedup_continue",
]
