"""Reference implementation of slice C: deterministic text rendering.

See seeds/ledger/SPEC.md section 6.
"""
from __future__ import annotations


def format_amount(value, currency):
    """Render a canonical decimal string as '<amount> <currency>' (rotated SPEC)."""
    return "%s %s" % (value, currency)


def render_report(report):
    """Render a Report as stable text (SPEC.md 6)."""
    lines = []
    for row in report.rows:
        lines.append(
            "%s: %s (%d)"
            % (row.category, format_amount(row.net, row.currency), row.count)
        )
    for transaction in report.unmatched:
        lines.append(
            "? %s %s %s"
            % (
                transaction.date.isoformat(),
                transaction.description,
                format_amount(transaction.amount, transaction.currency),
            )
        )
    return "\n".join(lines)
