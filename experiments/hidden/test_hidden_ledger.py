"""Hidden acceptance tests for the ledger seed (SPEC.md).

These live outside ``seeds/ledger`` and are copied in only after the run, so the
agents never see them.  They cover the edge cases and the cross-slice conventions
that the public tests deliberately leave out.

Run with:  python -m unittest discover -s . -p "test_hidden_*.py" -v
"""
import dataclasses
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


class TestParseAmountHidden(unittest.TestCase):
    def test_exact_cents_never_through_float(self):
        # 1.15 * 100 == 114.99999999999999 in binary floating point.
        self.assertEqual(parse_amount("1.15"), 115)
        self.assertEqual(parse_amount("0.29"), 29)
        self.assertEqual(parse_amount("8.16"), 816)
        self.assertEqual(parse_amount("-1.15"), -115)
        self.assertEqual(parse_amount("-0.07"), -7)
        self.assertEqual(parse_amount("2.67"), 267)

    def test_large_amount_is_exact(self):
        self.assertEqual(parse_amount("1234567890123.45"), 123456789012345)

    def test_single_and_double_decimals(self):
        self.assertEqual(parse_amount("3.5"), 350)
        self.assertEqual(parse_amount("3.50"), 350)
        self.assertEqual(parse_amount("0.5"), 50)
        self.assertEqual(parse_amount("0"), 0)
        self.assertEqual(parse_amount("-0"), 0)
        self.assertEqual(parse_amount("-0.00"), 0)

    def test_surrounding_whitespace_is_stripped(self):
        self.assertEqual(parse_amount(" 5 "), 500)
        self.assertEqual(parse_amount("\t-2.25\n"), -225)

    def test_rejects_bad_shapes(self):
        bad = [
            "3.505",  # three decimals
            ".5",
            "5.",
            "1,000",
            "1e3",
            "-",
            "+",
            "",
            " ",
            "1 000",
            "1.2.3",
            "0x10",
            "--1",
            "-+1",
            "3.-5",
        ]
        for token in bad:
            with self.assertRaises(ParseError):
                parse_amount(token)

    def test_rejects_non_ascii_digits(self):
        for token in ("\u0663", "1\u0662", "\uff11", "\u06f1"):
            with self.assertRaises(ParseError):
                parse_amount(token)

    def test_line_defaults_to_zero(self):
        with self.assertRaises(ParseError) as cm:
            parse_amount("nope")
        self.assertEqual(cm.exception.line, 0)


class TestParseLedgerHidden(unittest.TestCase):
    def test_line_numbers_count_comments_and_blanks(self):
        text = "\n# comment\n2026-02-01|a|1|USD\n\n2026-02-02|b|2|USD\n"
        txns = parse_ledger(text)
        self.assertEqual([t.line for t in txns], [3, 5])

    def test_crlf_and_trailing_whitespace(self):
        txns = parse_ledger("2026-02-01| coffee  beans |1.5|USD  \r\n")
        self.assertEqual(len(txns), 1)
        self.assertEqual(txns[0].description, "coffee  beans")
        self.assertEqual(txns[0].amount, 150)

    def test_returns_plain_list_in_file_order(self):
        text = "2026-02-03|c|3|USD\n2026-02-01|a|1|USD\n2026-02-02|b|2|USD\n"
        txns = parse_ledger(text)
        self.assertIsInstance(txns, list)
        self.assertEqual([t.description for t in txns], ["c", "a", "b"])
        self.assertEqual(txns[0].date, date(2026, 2, 3))

    def test_rejects_wrong_field_count(self):
        for text, line in (
            ("2026-02-01|a|1|USD|extra\n", 1),
            ("2026-02-01|a|1\n", 1),
            ("ok|2026-02-01|a|1|USD\n", 1),
        ):
            with self.assertRaises(ParseError) as cm:
                parse_ledger(text)
            self.assertEqual(cm.exception.line, line, text)

    def test_rejects_bad_currency(self):
        for currency in ("usd", "US", "USDD", "US1", "U S", "\u00dcSD", ""):
            with self.assertRaises(ParseError) as cm:
                parse_ledger("2026-02-01|a|1|%s\n" % currency)
            self.assertEqual(cm.exception.line, 1)

    def test_rejects_bad_dates(self):
        for bad in ("2026-02-30", "2026-13-01", "2026-00-10", "2026-1-01", "26-02-01",
                    "2026/02/01", "20260201", "2026-02-01T00:00"):
            with self.assertRaises(ParseError) as cm:
                parse_ledger("2026-02-01|a|1|USD\n%s|a|1|USD\n" % bad)
            self.assertEqual(cm.exception.line, 2, bad)

    def test_accepts_leap_day(self):
        txns = parse_ledger("2024-02-29|a|1|USD\n")
        self.assertEqual(txns[0].date, date(2024, 2, 29))

    def test_rejects_empty_description(self):
        with self.assertRaises(ParseError) as cm:
            parse_ledger("2026-02-01|   |1|USD\n")
        self.assertEqual(cm.exception.line, 1)

    def test_error_reports_the_offending_line(self):
        with self.assertRaises(ParseError) as cm:
            parse_ledger("# c\n2026-02-01|a|1|USD\n2026-02-02|b|1.234|USD\n")
        self.assertEqual(cm.exception.line, 3)

    def test_comment_only_and_empty_input(self):
        self.assertEqual(parse_ledger(""), [])
        self.assertEqual(parse_ledger("\n\n# only comments\n"), [])


class TestRulesHidden(unittest.TestCase):
    def test_pattern_must_match_the_whole_description(self):
        rule = Rule("r", "coffee", "food")
        self.assertEqual(match_rule("coffee", [rule]), rule)
        self.assertIsNone(match_rule("coffee beans", [rule]))
        self.assertIsNone(match_rule("iced coffee", [rule]))

    def test_star_and_question_mark(self):
        rule = Rule("r", "a*b?c", "x")
        self.assertEqual(match_rule("aZZbQc", [rule]), rule)
        self.assertEqual(match_rule("abbc", [rule]), rule)  # * may be empty
        self.assertEqual(match_rule("a*c", [Rule("e", "a*c", "x")]), Rule("e", "a*c", "x"))
        self.assertEqual(match_rule("ac", [Rule("e", "a*c", "x")]), Rule("e", "a*c", "x"))
        self.assertIsNone(match_rule("abc", [rule]))  # ? needs exactly one char
        self.assertIsNone(match_rule("ac", [rule]))
        self.assertIsNone(match_rule("aZZbQQc", [rule]))

    def test_regex_metacharacters_are_literal(self):
        dotted = Rule("d", "a.b", "x")
        self.assertEqual(match_rule("a.b", [dotted]), dotted)
        self.assertIsNone(match_rule("axb", [dotted]))
        bracket = Rule("b", "x[0-9]y", "x")
        self.assertEqual(match_rule("x[0-9]y", [bracket]), bracket)
        self.assertIsNone(match_rule("x5y", [bracket]))
        plus = Rule("p", "c++", "x")
        self.assertEqual(match_rule("c++", [plus]), plus)
        self.assertIsNone(match_rule("cc", [plus]))

    def test_matching_is_case_insensitive(self):
        rule = Rule("r", "Coffee*", "food")
        self.assertEqual(match_rule("coffee beans", [rule]), rule)
        self.assertEqual(match_rule("COFFEE", [rule]), rule)
        self.assertIsNone(match_rule("coffe", [rule]))

    def test_first_matching_rule_wins(self):
        rules = [Rule("first", "*", "A"), Rule("second", "*", "B")]
        self.assertEqual(match_rule("anything", rules).name, "first")
        narrowed = [Rule("specific", "rent", "A"), Rule("catchall", "*", "B")]
        self.assertEqual(match_rule("rent", narrowed).name, "specific")
        self.assertEqual(match_rule("rent2", narrowed).name, "catchall")

    def test_match_rule_with_no_rules(self):
        self.assertIsNone(match_rule("anything", []))

    def test_currencies_never_mixed(self):
        txns = [
            Transaction(1, date(2026, 2, 1), "food", -350, "USD"),
            Transaction(2, date(2026, 2, 2), "food", -250, "EUR"),
            Transaction(3, date(2026, 2, 3), "food", -100, "USD"),
        ]
        report = apply_rules(txns, [Rule("r", "*", "food")])
        self.assertEqual(
            report.rows,
            (
                CategoryTotal("food", "EUR", -250, 1),
                CategoryTotal("food", "USD", -450, 2),
            ),
        )

    def test_rows_sorted_by_currency_then_category(self):
        txns = [
            Transaction(1, date(2026, 2, 1), "z", 1, "USD"),
            Transaction(2, date(2026, 2, 2), "a", 2, "USD"),
            Transaction(3, date(2026, 2, 3), "z", 3, "CNY"),
            Transaction(4, date(2026, 2, 4), "a", 4, "EUR"),
        ]
        rules = [Rule("az", "a", "apple"), Rule("zz", "z", "zebra")]
        report = apply_rules(txns, rules)
        self.assertEqual(
            [(row.currency, row.category) for row in report.rows],
            [("CNY", "zebra"), ("EUR", "apple"), ("USD", "apple"), ("USD", "zebra")],
        )

    def test_unmatched_kept_in_input_order_and_is_a_tuple(self):
        txns = [
            Transaction(1, date(2026, 2, 1), "x1", 1, "USD"),
            Transaction(2, date(2026, 2, 2), "hit", 2, "USD"),
            Transaction(3, date(2026, 2, 3), "x2", 3, "USD"),
        ]
        report = apply_rules(txns, [Rule("r", "hit", "cat")])
        self.assertIsInstance(report, Report)
        self.assertIsInstance(report.rows, tuple)
        self.assertIsInstance(report.unmatched, tuple)
        self.assertEqual([t.description for t in report.unmatched], ["x1", "x2"])
        self.assertIsInstance(report.rows[0], CategoryTotal)

    def test_empty_transactions(self):
        report = apply_rules([], [Rule("r", "*", "cat")])
        self.assertEqual(report, Report(rows=(), unmatched=()))

    def test_bad_rule_sets_raise_rule_error(self):
        txn = [Transaction(1, date(2026, 2, 1), "a", 1, "USD")]
        for rules in (
            [Rule("", "*", "cat")],
            [Rule("n", "", "cat")],
            [Rule("n", "*", "")],
            [Rule("dup", "*", "a"), Rule("dup", "*", "b")],
        ):
            with self.assertRaises(RuleError):
                apply_rules(txn, rules)

    def test_rules_and_transactions_are_not_mutated(self):
        txns = [Transaction(1, date(2026, 2, 1), "a", 1, "USD")]
        rules = [Rule("r", "a", "cat")]
        txns_copy, rules_copy = list(txns), list(rules)
        apply_rules(txns, rules)
        self.assertEqual(txns, txns_copy)
        self.assertEqual(rules, rules_copy)


class TestReportHidden(unittest.TestCase):
    def test_format_amount_negative_below_one_unit(self):
        self.assertEqual(format_amount(-5, "USD"), "-0.05 USD")
        self.assertEqual(format_amount(-1, "USD"), "-0.01 USD")
        self.assertEqual(format_amount(-99, "USD"), "-0.99 USD")
        self.assertEqual(format_amount(-100, "USD"), "-1.00 USD")
        self.assertEqual(format_amount(-350, "USD"), "-3.50 USD")
        self.assertEqual(format_amount(-1000000, "USD"), "-10000.00 USD")

    def test_format_amount_positive_and_zero(self):
        self.assertEqual(format_amount(0, "XXX"), "0.00 XXX")
        self.assertEqual(format_amount(1, "XXX"), "0.01 XXX")
        self.assertEqual(format_amount(100, "XXX"), "1.00 XXX")
        self.assertEqual(format_amount(123456789, "JPY"), "1234567.89 JPY")

    def test_render_report_exact_bytes(self):
        txns = [
            Transaction(1, date(2026, 2, 1), "coffee", -350, "USD"),
            Transaction(2, date(2026, 2, 2), "salary", 120000, "USD"),
            Transaction(3, date(2026, 2, 3), "rent", -80000, "EUR"),
        ]
        rules = [Rule("food", "coffee", "food"), Rule("home", "rent", "housing")]
        self.assertEqual(
            render_report(apply_rules(txns, rules)),
            "housing: -800.00 EUR (1)\n"
            "food: -3.50 USD (1)\n"
            "? 2026-02-02 salary 1200.00 USD",
        )

    def test_render_report_unmatched_only(self):
        report = Report(
            rows=(),
            unmatched=(Transaction(4, date(2026, 3, 1), "misc thing", -7, "CNY"),),
        )
        self.assertEqual(render_report(report), "? 2026-03-01 misc thing -0.07 CNY")

    def test_render_report_empty_and_no_trailing_newline(self):
        self.assertEqual(render_report(Report(rows=(), unmatched=())), "")
        report = Report(rows=(CategoryTotal("food", "USD", 100, 1),), unmatched=())
        self.assertEqual(render_report(report), "food: 1.00 USD (1)")

    def test_render_report_is_deterministic(self):
        txns = parse_ledger(
            "2026-02-01|a|-1.15|USD\n2026-02-01|b|2.00|EUR\n2026-02-05|c|0.05|USD\n"
        )
        rules = [Rule("ab", "a", "x"), Rule("ab2", "b", "x")]
        first = render_report(apply_rules(txns, rules))
        second = render_report(apply_rules(txns, rules))
        self.assertEqual(first, second)


class TestContractsHidden(unittest.TestCase):
    def test_error_taxonomy(self):
        self.assertTrue(issubclass(ParseError, LedgerError))
        self.assertTrue(issubclass(RuleError, LedgerError))
        self.assertTrue(issubclass(LedgerError, ValueError))
        with self.assertRaises(ValueError):
            parse_ledger("garbage\n")
        with self.assertRaises(ValueError):
            apply_rules([], [Rule("", "*", "x")])

    def test_parse_error_attributes(self):
        error = ParseError("boom", 7)
        self.assertEqual(error.line, 7)
        self.assertEqual(error.message, "boom")
        self.assertEqual(str(error), "line 7: boom")

    def test_records_are_frozen_dataclasses(self):
        txn = Transaction(1, date(2026, 2, 1), "a", 1, "USD")
        self.assertTrue(dataclasses.is_dataclass(txn))
        self.assertEqual(txn, Transaction(1, date(2026, 2, 1), "a", 1, "USD"))
        with self.assertRaises(AttributeError):
            txn.amount = 5
        with self.assertRaises(AttributeError):
            Rule("n", "*", "c").name = "other"
        self.assertTrue(dataclasses.is_dataclass(CategoryTotal))
        self.assertTrue(dataclasses.is_dataclass(Report))

    def test_end_to_end(self):
        text = (
            "# february\n"
            "2026-02-01|coffee beans|-3.50|USD\n"
            "2026-02-01|salary|+1200.00|USD\n"
            "2026-02-03|rent|-800|USD\n"
            "2026-02-04|Coffee Beans|-2.50|EUR\n"
            "2026-02-05|mystery|-1.15|USD\n"
        )
        rules = [Rule("food", "*coffee*", "food"), Rule("housing", "rent", "housing")]
        report = apply_rules(parse_ledger(text), rules)
        self.assertEqual(
            render_report(report),
            "food: -2.50 EUR (1)\n"
            "food: -3.50 USD (1)\n"
            "housing: -800.00 USD (1)\n"
            "? 2026-02-01 salary 1200.00 USD\n"
            "? 2026-02-05 mystery -1.15 USD",
        )


if __name__ == "__main__":
    unittest.main()
