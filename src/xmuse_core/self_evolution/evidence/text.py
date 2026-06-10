"""Pure text-compaction helpers extracted from SelfEvolutionController.

These shape evidence-signal strings to bounded widths for inclusion in
structured evidence summaries. They are pure functions with no controller
state and form a closed cluster (only calling each other).
"""

from __future__ import annotations

import re


def compact_signal_text(value: str, max_chars: int) -> str:
    """Collapse whitespace and truncate with an ellipsis suffix."""
    compact = " ".join(value.split())
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."


def compact_middle_text(value: str, max_chars: int) -> str:
    """Truncate in the middle, keeping head and tail context."""
    if len(value) <= max_chars:
        return value
    if max_chars <= 3:
        return "." * max_chars
    head_chars = (max_chars - 3) // 2
    tail_chars = max_chars - 3 - head_chars
    return f"{value[:head_chars]}...{value[-tail_chars:]}"


def compact_confirmation_text(value: str, max_chars: int) -> str:
    """Truncate a confirmation, preserving a trailing ``-> result`` suffix."""
    compact = " ".join(value.split())
    if len(compact) <= max_chars:
        return compact

    match = re.search(r"(?:\s+->\s+|:\s+)[^:>]+$", compact)
    if match is None:
        return compact_signal_text(compact, max_chars)

    suffix = compact[match.start() :]
    head_chars = max_chars - len(suffix) - 3
    if head_chars < 24:
        return compact_signal_text(compact, max_chars)
    return f"{compact[:head_chars].rstrip()}...{suffix}"


def compact_risk_text(value: str, max_chars: int) -> str:
    """Truncate a residual-risk line, preferring an untracked-file summary."""
    compact = " ".join(value.split())
    if len(compact) <= max_chars:
        return compact
    untracked_summary = compact_untracked_risk_text(compact, max_chars)
    if untracked_summary:
        return untracked_summary
    return compact_middle_text(compact, max_chars)


def compact_untracked_risk_text(value: str, max_chars: int) -> str | None:
    """Summarize an untracked-file residual risk, or None if not applicable."""
    if "untracked" not in value.lower():
        return None

    untracked_match = re.search(
        r"((?:src|tests|xmuse|docs)/[^\s,;]+(?:\s+is)?\s+untracked)",
        value,
        flags=re.IGNORECASE,
    )
    if untracked_match is None:
        return None

    prefix = value[: untracked_match.start()].rstrip(" .,;")
    prefix = re.sub(r"\s+(?:and|with)$", "", prefix, flags=re.IGNORECASE).strip()
    if not prefix:
        prefix = value[: max_chars // 3].rstrip(" .,;")
    tracked_diff_match = re.search(
        r"rather\s+than\s+a\s+clean\s+tracked\s+diff\.?",
        value,
        flags=re.IGNORECASE,
    )
    tail = tracked_diff_match.group(0).rstrip(".") + "." if tracked_diff_match else ""

    parts = [prefix.rstrip(" .,;"), untracked_match.group(1).rstrip(" .,;")]
    if tail:
        parts.append(tail)
    summary = "; ".join(parts)
    if len(summary) <= max_chars:
        return summary

    compact_parts = [
        compact_signal_text(parts[0], max(24, max_chars // 3)),
        parts[1],
    ]
    if tail:
        compact_parts.append(tail)
    summary = "; ".join(compact_parts)
    if len(summary) <= max_chars:
        return summary

    return compact_middle_text(summary, max_chars)
