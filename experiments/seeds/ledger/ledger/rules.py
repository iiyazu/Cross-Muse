"""Slice B: rule matching and aggregation.  See SPEC.md section 5."""
from __future__ import annotations


def match_rule(description, rules):
    """Return the first Rule whose pattern matches description, else None."""
    raise NotImplementedError


def apply_rules(transactions, rules):
    """Match every transaction and aggregate into a Report (SPEC.md 5)."""
    raise NotImplementedError
