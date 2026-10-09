import unittest

from durations import format_duration, parse_duration


class TestDurations(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(parse_duration("1h30m"), 5400)
        self.assertEqual(format_duration(5400), "1h30m")


if __name__ == "__main__":
    unittest.main()
