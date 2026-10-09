"""Hidden acceptance tests for the minisql seed (SPEC.md).

These live outside ``seeds/minisql`` and are copied in only after the run, so the
agents never see them.  They cover the edge cases and the cross-slice conventions
that the public tests deliberately leave out.

Run with:  python -m unittest discover -s . -p "test_hidden_*.py" -v
"""
import dataclasses
import unittest

from minisql import (
    Condition,
    ExecutionError,
    MiniSQLError,
    OrderKey,
    ParseError,
    ResultSet,
    Select,
    Table,
    execute,
    format_table,
    parse,
)

MOVIES = Table(
    columns=("id", "title", "year", "score"),
    rows=(
        (1, "Alien", 1979, 85),
        (2, "Arrival", 2016, 79),
        (3, "Solaris", 1972, 71),
        (4, "Stalker", None, 100),
    ),
)

PAIRS = Table(
    columns=("g", "n"),
    rows=(("a", 2), ("b", 1), ("a", 1), ("b", 2)),
)


class TestParserHidden(unittest.TestCase):
    def test_empty_and_blank_statements(self):
        for sql in ("", "   ", "\n\t "):
            with self.assertRaises(ParseError) as cm:
                parse(sql)
            self.assertEqual(cm.exception.position, 0, repr(sql))

    def test_keywords_are_case_insensitive(self):
        stmt = parse(
            "select ID from MovieS where A is not null order by B desc limit 3"
        )
        self.assertEqual(stmt.columns, ("ID",))
        self.assertEqual(stmt.table, "MovieS")
        self.assertEqual(stmt.where, (Condition("A", "IS NOT NULL", None),))
        self.assertEqual(stmt.order_by, (OrderKey("B", True),))
        self.assertEqual(stmt.limit, 3)

    def test_reserved_words_are_not_identifiers(self):
        for sql in (
            "SELECT from FROM movies",
            "SELECT id FROM order",
            "SELECT * FROM movies WHERE select = 1",
            "SELECT * FROM movies ORDER BY limit",
        ):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)

    def test_string_literals_and_escapes(self):
        stmt = parse("SELECT * FROM movies WHERE title = 'it''s a ''trap'''")
        self.assertEqual(stmt.where, (Condition("title", "=", "it's a 'trap'"),))
        stmt = parse("SELECT * FROM movies WHERE title = ''")
        self.assertEqual(stmt.where, (Condition("title", "=", ""),))

    def test_unterminated_string_reports_the_opening_quote(self):
        sql = "SELECT * FROM movies WHERE title = 'abc"
        with self.assertRaises(ParseError) as cm:
            parse(sql)
        self.assertEqual(cm.exception.position, sql.index("'"))

    def test_ne_is_normalized(self):
        for operator in ("<>", "!="):
            stmt = parse("SELECT * FROM movies WHERE title %s 'x'" % operator)
            self.assertEqual(stmt.where, (Condition("title", "!=", "x"),))
            self.assertEqual(stmt.where[0].op, "!=")

    def test_negative_number_literal(self):
        stmt = parse("SELECT * FROM movies WHERE score > -5")
        self.assertEqual(stmt.where, (Condition("score", ">", -5),))
        self.assertIsInstance(stmt.where[0].value, int)

    def test_string_values_stay_strings(self):
        stmt = parse("SELECT * FROM movies WHERE year = '1979'")
        self.assertEqual(stmt.where, (Condition("year", "=", "1979"),))

    def test_limit_variants(self):
        self.assertIsNone(parse("SELECT * FROM movies").limit)
        self.assertEqual(parse("SELECT * FROM movies LIMIT 0").limit, 0)
        self.assertEqual(parse("SELECT * FROM movies LIMIT 17").limit, 17)
        for sql in (
            "SELECT * FROM movies LIMIT -1",
            "SELECT * FROM movies LIMIT x",
            "SELECT * FROM movies LIMIT 1.5",
            "SELECT * FROM movies LIMIT",
        ):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)

    def test_error_positions_are_character_offsets(self):
        sql = "SELECT * FROM movies WHERE year == 1979"
        with self.assertRaises(ParseError) as cm:
            parse(sql)
        self.assertEqual(cm.exception.position, sql.index("==") + 1)

        sql = "SELECT * FROM movies WHERE year > 1979 % 2"
        with self.assertRaises(ParseError) as cm:
            parse(sql)
        self.assertEqual(cm.exception.position, sql.index("%"))

        sql = "SELECT * FROM movies WHERE year >"
        with self.assertRaises(ParseError) as cm:
            parse(sql)
        self.assertEqual(cm.exception.position, len(sql))

    def test_star_is_exclusive(self):
        for sql in ("SELECT *, id FROM movies", "SELECT id, * FROM movies"):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)

    def test_duplicate_columns_allowed(self):
        stmt = parse("SELECT id, id FROM movies")
        self.assertEqual(stmt.columns, ("id", "id"))

    def test_trailing_semicolon_and_junk(self):
        self.assertEqual(parse("SELECT * FROM movies;").table, "movies")
        self.assertEqual(parse("SELECT * FROM movies ;  ").table, "movies")
        for sql in ("SELECT * FROM movies; extra", "SELECT * FROM movies extra"):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)

    def test_where_requires_and(self):
        with self.assertRaises(ParseError):
            parse("SELECT * FROM movies WHERE year = 1979 score = 85")

    def test_is_null_spellings(self):
        self.assertEqual(
            parse("SELECT * FROM movies WHERE year IS NULL").where,
            (Condition("year", "IS NULL", None),),
        )
        for sql in (
            "SELECT * FROM movies WHERE year IS 5",
            "SELECT * FROM movies WHERE year IS NOT",
            "SELECT * FROM movies WHERE year IS NOT 5",
            "SELECT * FROM movies WHERE year IS",
        ):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)

    def test_comparing_with_null_is_a_parse_error(self):
        for sql in (
            "SELECT * FROM movies WHERE year = NULL",
            "SELECT * FROM movies WHERE year <> NULL",
        ):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)

    def test_unknown_characters(self):
        for sql in (
            "SELECT movies.id FROM movies",
            "SELECT * FROM movies WHERE year ! 1979",
            "SELECT (id) FROM movies",
        ):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)

    def test_missing_table_name(self):
        with self.assertRaises(ParseError):
            parse("SELECT * FROM")

    def test_whitespace_and_newlines(self):
        stmt = parse("\n  SELECT\n  *\n  FROM\n  movies\n  WHERE\n  id\n  >\n  1\n")
        self.assertEqual(stmt.where, (Condition("id", ">", 1),))

    def test_multi_key_order_by(self):
        stmt = parse("SELECT * FROM movies ORDER BY year DESC, title, id ASC")
        self.assertEqual(
            stmt.order_by,
            (OrderKey("year", True), OrderKey("title", False), OrderKey("id", False)),
        )

    def test_parser_error_taxonomy(self):
        self.assertTrue(issubclass(ParseError, MiniSQLError))
        self.assertTrue(issubclass(MiniSQLError, ValueError))
        with self.assertRaises(ValueError):
            parse("nonsense")


class TestEngineHidden(unittest.TestCase):
    def test_columns_use_the_table_spelling(self):
        result = execute(parse("SELECT ID, Title FROM MOVIES"), MOVIES)
        self.assertEqual(result.columns, ("id", "title"))
        self.assertEqual(result.rows[0], (1, "Alien"))

    def test_star_keeps_table_column_order(self):
        result = execute(parse("SELECT * FROM movies"), MOVIES)
        self.assertEqual(result.columns, ("id", "title", "year", "score"))
        self.assertEqual(result.rows, MOVIES.rows)

    def test_where_column_is_case_insensitive(self):
        result = execute(parse("SELECT id FROM movies WHERE YEAR = 1979"), MOVIES)
        self.assertEqual(result.rows, ((1,),))

    def test_unknown_column_everywhere(self):
        for sql in (
            "SELECT nope FROM movies",
            "SELECT id FROM movies WHERE nope = 1",
            "SELECT id FROM movies ORDER BY nope",
        ):
            with self.assertRaises(ExecutionError, msg=sql):
                execute(parse(sql), MOVIES)

    def test_nulls_never_satisfy_comparisons(self):
        result = execute(parse("SELECT id FROM movies WHERE year != 1979"), MOVIES)
        self.assertEqual(result.rows, ((2,), (3,)))
        result = execute(parse("SELECT id FROM movies WHERE year > 1900"), MOVIES)
        self.assertEqual(result.rows, ((1,), (2,), (3,)))
        result = execute(parse("SELECT id FROM movies WHERE year = 1979"), MOVIES)
        self.assertEqual(result.rows, ((1,),))

    def test_is_null_and_is_not_null(self):
        self.assertEqual(
            execute(parse("SELECT id FROM movies WHERE year IS NULL"), MOVIES).rows,
            ((4,),),
        )
        self.assertEqual(
            execute(parse("SELECT id, year FROM movies WHERE year IS NOT NULL"), MOVIES).rows,
            ((1, 1979), (2, 2016), (3, 1972)),
        )

    def test_null_ordering_asc_then_desc(self):
        ascending = execute(parse("SELECT id FROM movies ORDER BY year"), MOVIES).rows
        self.assertEqual(ascending, ((4,), (3,), (1,), (2,)))
        descending = execute(parse("SELECT id FROM movies ORDER BY year DESC"), MOVIES).rows
        self.assertEqual(descending, ((2,), (1,), (3,), (4,)))

    def test_multi_key_mixed_directions(self):
        rows = execute(parse("SELECT g, n FROM t ORDER BY g ASC, n DESC"), PAIRS).rows
        self.assertEqual(rows, (("a", 2), ("a", 1), ("b", 2), ("b", 1)))
        rows = execute(parse("SELECT g, n FROM t ORDER BY n DESC, g DESC"), PAIRS).rows
        self.assertEqual(rows, (("b", 2), ("a", 2), ("b", 1), ("a", 1)))

    def test_sort_is_stable(self):
        table = Table(columns=("g", "n"), rows=(("a", 1), ("b", 1), ("a", 1), ("b", 1)))
        rows = execute(parse("SELECT g, n FROM t ORDER BY n"), table).rows
        self.assertEqual(rows, (("a", 1), ("b", 1), ("a", 1), ("b", 1)))

    def test_order_by_key_outside_the_select_list(self):
        rows = execute(parse("SELECT title FROM movies ORDER BY score DESC"), MOVIES).rows
        self.assertEqual(
            rows, (("Stalker",), ("Alien",), ("Arrival",), ("Solaris",))
        )

    def test_order_by_mixed_types_raises(self):
        table = Table(columns=("v",), rows=(("a",), (1,)))
        with self.assertRaises(ExecutionError):
            execute(parse("SELECT * FROM t ORDER BY v"), table)

    def test_where_mixed_types_raises(self):
        table = Table(columns=("v",), rows=(("a",), (1,)))
        with self.assertRaises(ExecutionError):
            execute(parse("SELECT * FROM t WHERE v = 1"), table)

    def test_limit_zero_and_larger_than_table(self):
        self.assertEqual(execute(parse("SELECT * FROM movies LIMIT 0"), MOVIES).rows, ())
        self.assertEqual(len(execute(parse("SELECT * FROM movies LIMIT 99"), MOVIES).rows), 4)

    def test_projection_keeps_duplicate_columns(self):
        result = execute(parse("SELECT id, id FROM movies"), MOVIES)
        self.assertEqual(result.columns, ("id", "id"))
        self.assertEqual(result.rows, ((1, 1), (2, 2), (3, 3), (4, 4)))

    def test_row_arity_is_validated(self):
        for rows in (((1,),), ((1, 2, 3),)):
            with self.assertRaises(ExecutionError):
                execute(parse("SELECT * FROM t"), Table(columns=("a", "b"), rows=rows))

    def test_result_shape_and_immutability(self):
        before = MOVIES.rows
        result = execute(parse("SELECT * FROM movies ORDER BY score DESC"), MOVIES)
        self.assertIsInstance(result, ResultSet)
        self.assertIsInstance(result.columns, tuple)
        self.assertIsInstance(result.rows, tuple)
        self.assertTrue(all(isinstance(row, tuple) for row in result.rows))
        self.assertEqual(MOVIES.rows, before)

    def test_select_returns_the_original_scalar_objects(self):
        result = execute(parse("SELECT year FROM movies WHERE id = 1"), MOVIES)
        self.assertEqual(result.rows, ((1979,),))

    def test_records_are_frozen_dataclasses(self):
        stmt = parse("SELECT * FROM movies")
        self.assertTrue(dataclasses.is_dataclass(stmt))
        with self.assertRaises(AttributeError):
            stmt.table = "other"
        with self.assertRaises(AttributeError):
            MOVIES.columns = ("x",)
        self.assertEqual(Select(columns=("*",), table="t"), Select(("*",), "t"))
        self.assertEqual(Table(("a",), ()), Table(columns=("a",), rows=()))


class TestFormatHidden(unittest.TestCase):
    def test_exact_three_column_layout(self):
        result = ResultSet(
            columns=("id", "title", "year"),
            rows=((1, "Alien", 1979), (2, "Solaris", None), (3, "A", 2001)),
        )
        self.assertEqual(
            format_table(result),
            "id | title   | year\n"
            "---+---------+-----\n"
            "1  | Alien   | 1979\n"
            "2  | Solaris | NULL\n"
            "3  | A       | 2001",
        )

    def test_empty_result_keeps_the_header(self):
        result = ResultSet(columns=("id", "year"), rows=())
        self.assertEqual(format_table(result), "id | year\n---+-----")

    def test_no_columns_renders_nothing(self):
        self.assertEqual(format_table(ResultSet(columns=(), rows=())), "")

    def test_single_column_is_not_padded(self):
        result = ResultSet(columns=("id",), rows=((1,), (22,)))
        self.assertEqual(format_table(result), "id\n--\n1\n22")

    def test_wide_values_expand_the_column(self):
        result = ResultSet(columns=("a", "b"), rows=(("long value", "x"),))
        self.assertEqual(format_table(result), "a          | b\n-----------+--\nlong value | x")

    def test_negative_and_string_cells(self):
        result = ResultSet(columns=("n", "s"), rows=((-5, "0"), (10, "")))
        self.assertEqual(format_table(result), "n  | s\n---+--\n-5 | 0\n10 | ")

    def test_rendering_is_deterministic(self):
        result = execute(parse("SELECT * FROM movies ORDER BY score DESC"), MOVIES)
        self.assertEqual(format_table(result), format_table(result))

    def test_no_trailing_whitespace_or_newline(self):
        text = format_table(execute(parse("SELECT title, year FROM movies"), MOVIES))
        self.assertFalse(text.endswith("\n"))
        for line in text.splitlines():
            self.assertEqual(line, line.rstrip(), repr(line))


if __name__ == "__main__":
    unittest.main()
