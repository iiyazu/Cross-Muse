"""Hidden acceptance tests for SPEC.md (copied in after the run; the agents never see them)."""
import unittest

from textkit import slugify


class Hidden(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(slugify("Hello, World!"), "hello-world")
        self.assertEqual(slugify("Crème brûlée"), "creme-brulee")
        self.assertEqual(slugify("Straße 5"), "strasse-5")
        self.assertEqual(slugify("a b c", sep="_"), "a_b_c")
        self.assertEqual(slugify("hello big world", max_len=10), "hello-big")

    def test_runs_and_edges(self):
        self.assertEqual(slugify("  --a__b--  "), "a-b")
        self.assertEqual(slugify("ÖL & Gas"), "ol-gas")
        self.assertEqual(slugify("日本語"), "")
        self.assertEqual(slugify("x日本y"), "x-y")
        self.assertEqual(slugify("!!!"), "")

    def test_max_len(self):
        self.assertEqual(slugify("supercalifragilistic word", max_len=5), "super")
        self.assertEqual(slugify("ab cd", max_len=4), "ab")
        self.assertEqual(slugify("ab cd", max_len=5), "ab-cd")
        self.assertEqual(slugify("a b", sep="--", max_len=3), "a")
        self.assertTrue(len(slugify("one two three four", max_len=12)) <= 12)

    def test_bad_args(self):
        for sep in ("", "a", "-1-"):
            with self.assertRaises(ValueError):
                slugify("x", sep=sep)
        with self.assertRaises(ValueError):
            slugify("x", max_len=0)
