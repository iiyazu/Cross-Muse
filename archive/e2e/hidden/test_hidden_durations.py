"""Hidden acceptance tests for SPEC.md (copied in after the run; the agents never see them)."""
import unittest

from durations import format_duration, parse_duration


class Hidden(unittest.TestCase):
    def test_parse(self):
        cases = {"1h30m": 5400, "90s": 90, "2d": 172800, "1h 5m 3s": 3903, " 1H ": 3600, "1.5h": 5400,
                 "0s": 0, "1d1h1m1s": 90061, "0.5s": 1, "1.25m": 75, "10M": 600}
        for text, want in cases.items():
            self.assertEqual(parse_duration(text), want, text)

    def test_invalid(self):
        for text in ("", "   ", "h", "10", "1x", "1m1h", "1h1h", "-1h", "+1h", "1 h", "1h-", "1..5h", ".h"):
            with self.assertRaises(ValueError, msg=text) as e:
                parse_duration(text)
            if text.strip():
                self.assertIn(text.strip(), str(e.exception))

    def test_format(self):
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(5400), "1h30m")
        self.assertEqual(format_duration(90061), "1d1h1m1s")
        self.assertEqual(format_duration(86400), "1d")
        for bad in (-1, 1.5, True, "5"):
            with self.assertRaises(ValueError):
                format_duration(bad)

    def test_round_trip(self):
        for n in list(range(0, 200)) + [3599, 3600, 3601, 86399, 86400, 999999]:
            self.assertEqual(parse_duration(format_duration(n)), n)
