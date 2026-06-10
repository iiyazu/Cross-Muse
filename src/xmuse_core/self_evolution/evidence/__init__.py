"""Evidence-bundle assembly helpers for self-evolution."""

from xmuse_core.self_evolution.evidence.aggregator import (
    aggregate_run_terminal,
    build_evidence_bundle,
)
from xmuse_core.self_evolution.evidence.review_text import (
    review_confirmation_summaries,
    review_finding_summaries,
    review_recovery_reason,
    review_risk_summaries,
    review_scope_refs,
)
from xmuse_core.self_evolution.evidence.signal_order import (
    ordered_signal_summary_refs,
    rank_lane_signal_summary_refs,
)
from xmuse_core.self_evolution.evidence.text import (
    compact_confirmation_text,
    compact_middle_text,
    compact_risk_text,
    compact_signal_text,
    compact_untracked_risk_text,
)

__all__ = [
    "aggregate_run_terminal",
    "build_evidence_bundle",
    "compact_confirmation_text",
    "compact_middle_text",
    "compact_risk_text",
    "compact_signal_text",
    "compact_untracked_risk_text",
    "ordered_signal_summary_refs",
    "rank_lane_signal_summary_refs",
    "review_confirmation_summaries",
    "review_finding_summaries",
    "review_recovery_reason",
    "review_risk_summaries",
    "review_scope_refs",
]
