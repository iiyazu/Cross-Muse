"""Slice A: transaction text -> Transaction objects.  See SPEC.md section 4."""
from __future__ import annotations


def parse_amount(token, line=0):
    """Parse an amount literal into signed integer cents (SPEC.md 4)."""
    raise NotImplementedError


def parse_ledger(text):
    """Parse the whole ledger text into a list of Transaction (SPEC.md 4)."""
    raise NotImplementedError
