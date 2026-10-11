"""Reference implementation of slice C: deterministic text rendering.

See seeds/ledger/SPEC.md section 6.
"""
from __future__ import annotations


def format_amount(cents, currency):
    """Render signed integer cents as '<amount> <currency>' (SPEC.md 6)."""
    sign = "-" if cents < 0 else ""
    value = abs(int(cents))
    return "%s%d.%02d %s" % (sign, value // 100, value % 100, currency)


def render_report(report):
    """Render a Report as stable text (SPEC.md 6)."""
    lines = []
    for row in report.rows:
        lines.append(
            "%s: %s (%d)"
            % (row.category, format_amount(row.net, row.currency), row.count)
        )
    return "\n".join(lines)
