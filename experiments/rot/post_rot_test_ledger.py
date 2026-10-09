#!/usr/bin/env python3
"""Post-rot acceptance tests for the ledger seed.

These tests encode the conventions that are **deliberately overturned mid-task**
by the human (see ``rot/ledger.md``).  They must NOT pass on the original
reference implementation -- ``verify.py`` asserts exactly that, which proves the
file is a live detector and not a no-op.

After a rot, the experiment scores each agent by which of these tests pass:

  * ``RotOneDecimalStringAmounts``  -- ROT-1, amounts become canonical
    2-decimal strings instead of integer cents.
  * ``RotTwoUncategorized``         -- ROT-2, unmatched transactions become an
    ``uncategorized`` category row instead of a separate ``Report.unmatched``
    layer.

Run with:  python -m unittest discover -s . -p "post_rot_test_*.py" -v
"""
import inspect
import unittest

import ledger
from ledger import Rule, apply_rules, format_amount, parse_amount, parse_ledger


class RotOneDecimalStringAmounts(unittest.TestCase):
    """ROT-1: money is a canonical 2-decimal string, never integer cents."""

    def test_rot1_parse_amount_returns_canonical_string(self):
        self.assertEqual(parse_amount("3.50"), "3.50")
        self.assertEqual(parse_amount("3.5"), "3.50")
        self.assertEqual(parse_amount("+1200"), "1200.00")
        self.assertEqual(parse_amount("0"), "0.00")
        self.assertEqual(parse_amount("-0.05"), "-0.05")
        self.assertEqual(parse_amount("1.15"), "1.15")
        self.assertIsInstance(parse_amount("1.15"), str)

    def test_rot1_transaction_amount_is_string(self):
        txn = parse_ledger("2026-02-01|a|-3.50|USD\n")[0]
        self.assertIsInstance(txn.amount, str)
        self.assertEqual(txn.amount, "-3.50")

    def test_rot1_net_is_string_and_sums_exactly(self):
        txns = parse_ledger("2026-02-01|a|-0.10|USD\n2026-02-02|a|-0.20|USD\n")
        report = apply_rules(txns, [Rule("r", "a", "c")])
        self.assertIsInstance(report.rows[0].net, str)
        self.assertEqual(report.rows[0].net, "-0.30")

    def test_rot1_format_amount_takes_a_string(self):
        self.assertEqual(format_amount("-3.50", "USD"), "-3.50 USD")
        self.assertEqual(format_amount("0.00", "EUR"), "0.00 EUR")

    def test_rot1_no_float_anywhere_in_the_package(self):
        for module in (ledger.parse, ledger.rules, ledger.report):
            source = inspect.getsource(module)
            self.assertNotIn("float(", source, module.__name__)


class RotTwoUncategorized(unittest.TestCase):
    """ROT-2: unmatched transactions become an ``uncategorized`` row."""

    TEXT = "2026-02-01|hit|1|USD\n2026-02-02|miss|-2.50|USD\n2026-02-03|miss2|-1.00|EUR\n"

    def _report(self):
        return apply_rules(parse_ledger(self.TEXT), [Rule("r", "hit", "cat")])

    def test_rot2_unmatched_becomes_uncategorized_rows(self):
        keys = [(row.currency, row.category) for row in self._report().rows]
        self.assertIn(("EUR", "uncategorized"), keys)
        self.assertIn(("USD", "uncategorized"), keys)

    def test_rot2_report_has_no_unmatched_layer(self):
        self.assertEqual(self._report().unmatched, ())

    def test_rot2_uncategorized_sorted_with_everything_else(self):
        keys = [(row.currency, row.category) for row in self._report().rows]
        self.assertEqual(
            keys,
            [("EUR", "uncategorized"), ("USD", "cat"), ("USD", "uncategorized")],
        )


if __name__ == "__main__":
    unittest.main()
