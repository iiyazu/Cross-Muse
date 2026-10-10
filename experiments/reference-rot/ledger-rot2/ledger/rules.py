"""Reference implementation of slice B: rule matching and aggregation.

See seeds/ledger/SPEC.md section 5.
"""
from __future__ import annotations

import re

from .types import CategoryTotal, Report, Rule, RuleError


def _compile(pattern):
    """Translate a SPEC pattern into a regex anchored at both ends.

    Only ``*`` and ``?`` are wildcards; every other character is a literal.
    """
    parts = []
    for char in pattern:
        if char == "*":
            parts.append(".*")
        elif char == "?":
            parts.append(".")
        else:
            parts.append(re.escape(char))
    return re.compile("".join(parts) + r"\Z", re.IGNORECASE)


def match_rule(description, rules):
    """Return the first Rule whose pattern matches description, else None."""
    for rule in rules:
        if _compile(rule.pattern).match(description):
            return rule
    return None


def _check_rules(rules):
    seen = set()
    for rule in rules:
        if not isinstance(rule, Rule):
            raise RuleError("not a Rule: %r" % (rule,))
        for field in ("name", "pattern", "category"):
            value = getattr(rule, field)
            if not isinstance(value, str) or value == "":
                raise RuleError(
                    "rule %r: %s must be a non-empty string" % (rule.name, field)
                )
        if rule.name in seen:
            raise RuleError("duplicate rule name %r" % (rule.name,))
        seen.add(rule.name)


def apply_rules(transactions, rules):
    """Match every transaction and aggregate into a Report (SPEC.md 5)."""
    rules = list(rules)
    _check_rules(rules)
    compiled = [(rule, _compile(rule.pattern)) for rule in rules]

    buckets = {}
    for transaction in transactions:
        category = "uncategorized"
        for rule, regex in compiled:
            if regex.match(transaction.description):
                category = rule.category
                break
        key = (transaction.currency, category)
        previous = buckets.get(key)
        if previous is None:
            buckets[key] = CategoryTotal(category, transaction.currency, transaction.amount, 1)
        else:
            buckets[key] = CategoryTotal(
                category,
                transaction.currency,
                previous.net + transaction.amount,
                previous.count + 1,
            )
    rows = tuple(buckets[key] for key in sorted(buckets))
    return Report(rows=rows, unmatched=())
