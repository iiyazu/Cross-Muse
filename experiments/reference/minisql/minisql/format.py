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
    widths = []
    for index, name in enumerate(columns):
        width = len(name)
        for row in rendered:
            if len(row[index]) > width:
                width = len(row[index])
        widths.append(width)

    def line(cells):
        parts = []
        for index, cell in enumerate(cells):
            if index == len(cells) - 1:
                parts.append(cell)
            else:
                parts.append(cell.ljust(widths[index]))
        return " | ".join(parts)

    lines = [line(tuple(columns)), "-+-".join("-" * width for width in widths)]
    lines.extend(line(row) for row in rendered)
    return "\n".join(lines)
