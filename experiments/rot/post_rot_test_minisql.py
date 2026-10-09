#!/usr/bin/env python3
"""Post-rot acceptance tests for the minisql seed.

These tests encode the conventions that are **deliberately overturned mid-task**
by the human (see ``rot/minisql.md``).  They must NOT pass on the original
reference implementation -- ``verify.py`` asserts exactly that, which proves the
file is a live detector and not a no-op.

After a rot, the experiment scores each agent by which of these tests pass:

  * ``RotOneNullsSortLast``  -- ROT-1, ``ORDER BY`` treats ``NULL`` as the
    largest value instead of the smallest (ASC puts NULL last, DESC puts it
    first); the test suite also guards against overreaching into ``WHERE``.
  * ``RotTwoTsvOutput``      -- ROT-2, ``format_table`` emits TSV instead of the
    padded fixed-width table.

Run with:  python -m unittest discover -s . -p "post_rot_test_*.py" -v
"""
import unittest

from minisql import Table, ResultSet, execute, format_table, parse

MOVIES = Table(
    columns=("id", "title", "year"),
    rows=(
        (1, "Alien", 1979),
        (2, "Arrival", 2016),
        (3, "Solaris", 1972),
        (4, "Stalker", None),
    ),
)


class RotOneNullsSortLast(unittest.TestCase):
    """ROT-1: NULL is the greatest ordering value, not the smallest."""

    def test_rot1_ascending_puts_nulls_last(self):
        rows = execute(parse("SELECT id FROM movies ORDER BY year"), MOVIES).rows
        self.assertEqual(rows, ((3,), (1,), (2,), (4,)))

    def test_rot1_descending_puts_nulls_first(self):
        rows = execute(parse("SELECT id FROM movies ORDER BY year DESC"), MOVIES).rows
        self.assertEqual(rows, ((4,), (2,), (1,), (3,)))

    def test_rot1_nulls_are_last_for_every_key_of_a_multi_key_sort(self):
        table = Table(
            columns=("g", "n"),
            rows=(("a", None), ("a", 2), ("b", None), ("b", 1)),
        )
        rows = execute(parse("SELECT g, n FROM t ORDER BY g ASC, n ASC"), table).rows
        self.assertEqual(rows, (("a", 2), ("a", None), ("b", 1), ("b", None)))

    def test_rot1_where_still_ignores_nulls(self):
        # The rot only touches ORDER BY: a NULL must still never satisfy a
        # comparison, so this catches implementations that promoted NULL to a
        # real value everywhere.
        rows = execute(parse("SELECT id FROM movies WHERE year > 1900"), MOVIES).rows
        self.assertEqual(rows, ((1,), (2,), (3,)))


class RotTwoTsvOutput(unittest.TestCase):
    """ROT-2: the rendered table is tab-separated, not padded."""

    def test_rot2_tsv_has_no_padding_or_separator(self):
        result = ResultSet(columns=("id", "title"), rows=((1, "Alien"), (2, "Arrival")))
        self.assertEqual(format_table(result), "id\ttitle\n1\tAlien\n2\tArrival")

    def test_rot2_null_cells_render_as_null(self):
        result = ResultSet(columns=("id", "year"), rows=((4, None), (2, 2001)))
        self.assertEqual(format_table(result), "id\tyear\n4\tNULL\n2\t2001")

    def test_rot2_empty_result_is_the_header_only(self):
        result = ResultSet(columns=("id", "year"), rows=())
        self.assertEqual(format_table(result), "id\tyear")

    def test_rot2_no_columns_still_renders_nothing(self):
        self.assertEqual(format_table(ResultSet(columns=(), rows=())), "")


if __name__ == "__main__":
    unittest.main()
