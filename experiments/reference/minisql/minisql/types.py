"""Shared data structures and error types for the minisql package.

This module is the frozen contract described in SPEC.md.  The parser, the engine
and the formatter all speak the record types defined here, so none of them has to
guess what another slice means.
"""
from __future__ import annotations

from dataclasses import dataclass


class MiniSQLError(ValueError):
    """Base class of every error raised by this package."""


class ParseError(MiniSQLError):
    """The statement cannot be tokenized or parsed.

    ``position`` is the 0-based character offset of the offending character (or
    ``len(sql)`` when the statement simply ends too early).
    """

    def __init__(self, message, position=0):
        super().__init__("at %d: %s" % (position, message))
        self.message = message
        self.position = position


class ExecutionError(MiniSQLError):
    """The statement is syntactically fine but cannot be executed."""


@dataclass(frozen=True)
class Condition:
    """One WHERE predicate.  ``op`` is never ``"<>"`` -- that is normalized."""

    column: str
    op: str
    value: object = None


@dataclass(frozen=True)
class OrderKey:
    """One ORDER BY key."""

    column: str
    descending: bool = False


@dataclass(frozen=True)
class Select:
    """The parsed statement.  ``columns == ("*",)`` means "every column"."""

    columns: tuple
    table: str
    where: tuple = ()
    order_by: tuple = ()
    limit: object = None


@dataclass(frozen=True)
class Table:
    """An in-memory relation.  Cells are int, str or None."""

    columns: tuple
    rows: tuple


@dataclass(frozen=True)
class ResultSet:
    """The outcome of a query.  ``columns`` uses the table's canonical spelling."""

    columns: tuple
    rows: tuple
