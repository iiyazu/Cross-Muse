"""Reference implementation of slice C: fixed-width text rendering.

See seeds/minisql/SPEC.md section 6.
"""
from __future__ import annotations


def _render(value):
    if value is None:
        return "NULL"
    return str(value)


def format_table(result):
    """Render a ResultSet as stable text (SPEC.md 6)."""
    columns = tuple(result.columns)
    if not columns:
        return ""

    rendered = [tuple(_render(value) for value in row) for row in result.rows]
    lines = ["\t".join(columns)]
    lines.extend("\t".join(row) for row in rendered)
    return "\n".join(lines)
