"""PLANTED BUG 2 -- do not ship.  See planted/minisql/BUGS.md.

Only ``_find_column`` differs from the reference: the lookup compares column
names verbatim instead of case-insensitively.  Every public test writes the
column names exactly the way the table declares them, so nothing is red until a
query uses another spelling.
"""
from __future__ import annotations

from .types import ExecutionError, ResultSet, Table


def _find_column(name, table):
    """Resolve a column name to the table's spelling."""
    # Bug: the SPEC says the match is case-insensitive.
    for column in table.columns:
        if column == name:
            return column
    raise ExecutionError("unknown column %r" % (name,))


def _matches(value, operator, other):
    if operator == "IS NULL":
        return value is None
    if operator == "IS NOT NULL":
        return value is not None
    if value is None:
        return False
    if type(value) is not type(other):
        raise ExecutionError(
            "cannot compare %s with %s" % (type(value).__name__, type(other).__name__)
        )
    if operator == "=":
        return value == other
    if operator == "!=":
        return value != other
    if operator == "<":
        return value < other
    if operator == "<=":
        return value <= other
    if operator == ">":
        return value > other
    if operator == ">=":
        return value >= other
    raise ExecutionError("unknown operator %r" % (operator,))


def execute(stmt, table):
    """Filter, sort, project and limit (SPEC.md 5)."""
    if not isinstance(table, Table):
        raise ExecutionError("expected a Table, got %r" % (type(table).__name__,))
    width = len(table.columns)
    for row in table.rows:
        if len(row) != width:
            raise ExecutionError(
                "row has %d values but the table has %d columns" % (len(row), width)
            )

    if stmt.columns == ("*",):
        selected = tuple(table.columns)
    else:
        selected = tuple(_find_column(name, table) for name in stmt.columns)

    positions = {name: index for index, name in enumerate(table.columns)}
    conditions = [(positions[_find_column(cond.column, table)], cond) for cond in stmt.where]
    order_keys = [
        (positions[_find_column(key.column, table)], key.descending) for key in stmt.order_by
    ]

    rows = []
    for row in table.rows:
        keep = True
        for position, condition in conditions:
            if not _matches(row[position], condition.op, condition.value):
                keep = False
                break
        if keep:
            rows.append(row)

    for position, descending in reversed(order_keys):
        try:
            rows.sort(
                key=lambda row, position=position: (row[position] is not None, row[position]),
                reverse=descending,
            )
        except TypeError:
            raise ExecutionError("cannot order by a column holding mixed types") from None

    if stmt.limit is not None:
        rows = rows[: stmt.limit]

    projected = tuple(tuple(row[positions[name]] for name in selected) for row in rows)
    return ResultSet(columns=selected, rows=projected)
