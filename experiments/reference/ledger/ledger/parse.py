"""Reference implementation of slice A: transaction text -> Transaction objects.

See seeds/ledger/SPEC.md section 4.
"""
from __future__ import annotations

import re
from datetime import date

from .types import ParseError, Transaction

_AMOUNT_RE = re.compile(r"[+-]?[0-9]+(?:\.[0-9]{1,2})?\Z")
_DATE_RE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}\Z")
_CURRENCY_RE = re.compile(r"[A-Z]{3}\Z")


def parse_amount(token, line=0):
    """Parse an amount literal into signed integer cents (SPEC.md 4)."""
    if not isinstance(token, str):
        raise ParseError("amount must be a string, got %r" % (token,), line)
    text = token.strip()
    if not _AMOUNT_RE.match(text):
        raise ParseError("invalid amount %r" % (token,), line)
    sign = 1
    if text[0] in "+-":
        if text[0] == "-":
            sign = -1
        text = text[1:]
    whole, _, frac = text.partition(".")
    frac = (frac + "00")[:2]
    return sign * (int(whole) * 100 + int(frac))


def _parse_date(text, line):
    if not _DATE_RE.match(text):
        raise ParseError("invalid date %r (expected YYYY-MM-DD)" % (text,), line)
    try:
        return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))
    except ValueError:
        raise ParseError("impossible calendar date %r" % (text,), line) from None


def parse_ledger(text):
    """Parse the whole ledger text into a list of Transaction (SPEC.md 4)."""
    if not isinstance(text, str):
        raise TypeError("parse_ledger expects a string, got %r" % (type(text).__name__,))
    transactions = []
    for number, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        fields = [field.strip() for field in stripped.split("|")]
        if len(fields) != 4:
            raise ParseError(
                "expected 4 fields separated by '|', got %d" % (len(fields),), number
            )
        date_text, description, amount_text, currency = fields
        when = _parse_date(date_text, number)
        if not description:
            raise ParseError("empty description", number)
        amount = parse_amount(amount_text, number)
        if not _CURRENCY_RE.match(currency):
            raise ParseError(
                "currency must be 3 uppercase ASCII letters, got %r" % (currency,), number
            )
        transactions.append(Transaction(number, when, description, amount, currency))
    return transactions
