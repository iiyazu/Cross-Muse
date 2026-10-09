"""Public tests for the ledger task.  These are the tests the agents can see.

They cover the happy paths of SPEC.md only.  The acceptance suite is wider.
Run with:  python -m unittest discover -s tests -v
"""
import unittest
from datetime import date

from ledger import (
    CategoryTotal,
    LedgerError,
    ParseError,
    Report,
    Rule,
    RuleError,
    Transaction,
    apply_rules,
    format_amount,
    match_rule,
    parse_amount,
    parse_ledger,
    render_report,
)

SAMPLE = """\
# 2026-02 expenses
2026-02-01|coffee beans|-3.50|USD
2026-02-01|salary|+1200.00|USD

2026-02-03|rent|-800|USD
2026-02-04|coffee beans|-2.50|EUR
"""

RULES = [Rule("food", "*coffee*", "food"), Rule("housing", "rent", "housing")]


class TestParseAmount(unittest.TestCase):
    def test_plain_integers(self):
        self.assertEqual(parse_amount("3"), 300)
        self.assertEqual(parse_amount("-800"), -80000)
        self.assertEqual(parse_amount("+1200.00"), 120000)

    def test_decimals(self):
        self.assertEqual(parse_amount("3.5"), 350)
        self.assertEqual(parse_amount("3.50"), 350)
        self.assertEqual(parse_amount("0.07"), 7)

    def test_rejects_garbage(self):
        for bad in ("3.505", ".5", "5.", "1,000", "1e3", "-", ""):
            with self.assertRaises(ParseError):
                parse_amount(bad)


class TestParseLedger(unittest.TestCase):
    def test_lines_and_values(self):
        txns = parse_ledger(SAMPLE)
        self.assertEqual(len(txns), 4)
        self.assertEqual(
            txns[0],
            Transaction(2, date(2026, 2, 1), "coffee beans", -350, "USD"),
        )
        self.assertEqual(txns[2].date, date(2026, 2, 3))
        self.assertEqual(txns[3].currency, "EUR")

    def test_empty_input(self):
        self.assertEqual(parse_ledger("# nothing here\n\n"), [])

    def test_error_carries_line_number(self):
        with self.assertRaises(ParseError) as cm:
            parse_ledger("2026-02-01|ok|1|USD\n2026-02-01|bad|1.234|USD\n")
        self.assertEqual(cm.exception.line, 2)


class TestRules(unittest.TestCase):
    def test_match_rule(self):
        self.assertEqual(match_rule("coffee beans", RULES).name, "food")
        self.assertEqual(match_rule("rent", RULES).name, "housing")
        self.assertIsNone(match_rule("salary", RULES))

    def test_apply_rules(self):
        report = apply_rules(parse_ledger(SAMPLE), RULES)
        self.assertEqual(
            report.rows,
            (
                CategoryTotal("food", "EUR", -250, 1),
                CategoryTotal("food", "USD", -350, 1),
                CategoryTotal("housing", "USD", -80000, 1),
            ),
        )
        self.assertEqual([t.description for t in report.unmatched], ["salary"])

    def test_bad_rules(self):
        with self.assertRaises(RuleError):
            apply_rules([], [Rule("", "*", "food")])


class TestReport(unittest.TestCase):
    def test_format_amount(self):
        self.assertEqual(format_amount(350, "USD"), "3.50 USD")
        self.assertEqual(format_amount(5, "EUR"), "0.05 EUR")
        self.assertEqual(format_amount(-123456, "CNY"), "-1234.56 CNY")

    def test_render_report(self):
        report = apply_rules(parse_ledger(SAMPLE), RULES)
        self.assertEqual(
            render_report(report),
            "food: -2.50 EUR (1)\n"
            "food: -3.50 USD (1)\n"
            "housing: -800.00 USD (1)\n"
            "? 2026-02-01 salary 1200.00 USD",
        )

    def test_empty_report(self):
        self.assertEqual(render_report(Report(rows=(), unmatched=())), "")


class TestContract(unittest.TestCase):
    def test_errors_are_value_errors(self):
        self.assertTrue(issubclass(ParseError, LedgerError))
        self.assertTrue(issubclass(RuleError, LedgerError))
        self.assertTrue(issubclass(LedgerError, ValueError))


if __name__ == "__main__":
    unittest.main()
