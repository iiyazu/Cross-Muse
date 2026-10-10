"""Shared data structures and error types for the ledger package.

This module is the frozen contract described in SPEC.md.  Every convention that
the three work slices have to agree on (amount unit, currency encoding, error
taxonomy) lives here, so that no slice has to guess what another slice means.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


class LedgerError(ValueError):
    """Base class of every error raised by this package."""


class ParseError(LedgerError):
    """The transaction text cannot be parsed.

    ``line`` is the 1-based line number in the source text, or 0 when the bad
    token is not attached to a line.
    """

    def __init__(self, message, line=0):
        super().__init__("line %d: %s" % (line, message))
        self.message = message
        self.line = line


class RuleError(LedgerError):
    """The rule set itself cannot be used."""


@dataclass(frozen=True)
class Transaction:
    """One parsed ledger line.  ``amount`` is a signed integer number of cents."""

    line: int
    date: date
    description: str
    amount: int
    currency: str


@dataclass(frozen=True)
class Rule:
    """A category rule.  ``pattern`` uses ``*`` and ``?`` wildcards (see SPEC.md)."""

    name: str
    pattern: str
    category: str


@dataclass(frozen=True)
class CategoryTotal:
    """Aggregate for one (category, currency) pair.  ``net`` is signed cents."""

    category: str
    currency: str
    net: int
    count: int


@dataclass(frozen=True)
class Report:
    """Aggregated result.  ``rows`` is sorted by (currency, category)."""

    rows: tuple
    unmatched: tuple
