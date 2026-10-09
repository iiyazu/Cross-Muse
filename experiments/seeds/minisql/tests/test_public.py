"""Public tests for the minisql task.  These are the tests the agents can see.

They cover the happy paths of SPEC.md only.  The acceptance suite is wider.
Run with:  python -m unittest discover -s tests -v
"""
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


class TestParse(unittest.TestCase):
    def test_select_star(self):
        self.assertEqual(
            parse("SELECT * FROM movies"),
            Select(columns=("*",), table="movies"),
        )

    def test_full_statement(self):
        stmt = parse(
            "select id, title from movies "
            "where year >= 1979 and year < 2020 "
            "order by year desc, title asc limit 2;"
        )
        self.assertEqual(stmt.columns, ("id", "title"))
        self.assertEqual(stmt.table, "movies")
        self.assertEqual(
            stmt.where,
            (Condition("year", ">=", 1979), Condition("year", "<", 2020)),
        )
        self.assertEqual(stmt.order_by, (OrderKey("year", True), OrderKey("title", False)))
        self.assertEqual(stmt.limit, 2)

    def test_norm_ne_operator(self):
        stmt = parse("SELECT * FROM movies WHERE title <> 'Alien'")
        self.assertEqual(stmt.where, (Condition("title", "!=", "Alien"),))

    def test_parse_errors(self):
        for sql in (
            "",
            "   ",
            "SELEC * FROM movies",
            "SELECT * FROM",
            "SELECT * FROM movies WHERE",
            "SELECT *, id FROM movies",
            "SELECT * FROM movies LIMIT -1",
            "SELECT * FROM movies WHERE year = NULL",
            "SELECT 'abc FROM movies",
        ):
            with self.assertRaises(ParseError, msg=sql):
                parse(sql)


class TestExecute(unittest.TestCase):
    def test_select_star_keeps_source_order(self):
        result = execute(parse("SELECT * FROM movies"), MOVIES)
        self.assertEqual(result.columns, ("id", "title", "year", "score"))
        self.assertEqual(result.rows, MOVIES.rows)

    def test_where_order_limit(self):
        result = execute(
            parse("SELECT title, score FROM movies WHERE score >= 79 ORDER BY score DESC LIMIT 2"),
            MOVIES,
        )
        self.assertEqual(result.columns, ("title", "score"))
        self.assertEqual(result.rows, (("Stalker", 100), ("Alien", 85)))

    def test_is_null(self):
        result = execute(parse("SELECT id FROM movies WHERE year IS NULL"), MOVIES)
        self.assertEqual(result.rows, ((4,),))
        result = execute(parse("SELECT id FROM movies WHERE year IS NOT NULL"), MOVIES)
        self.assertEqual(result.rows, ((1,), (2,), (3,)))

    def test_unknown_column(self):
        for sql in (
            "SELECT nope FROM movies",
            "SELECT id FROM movies WHERE nope = 1",
            "SELECT id FROM movies ORDER BY nope",
        ):
            with self.assertRaises(ExecutionError, msg=sql):
                execute(parse(sql), MOVIES)

    def test_ragged_table(self):
        broken = Table(columns=("a", "b"), rows=((1,),))
        with self.assertRaises(ExecutionError):
            execute(parse("SELECT * FROM t"), broken)


class TestFormat(unittest.TestCase):
    def test_format_table(self):
        result = execute(parse("SELECT id, title FROM movies WHERE id <= 2"), MOVIES)
        self.assertEqual(
            format_table(result),
            "id | title\n"
            "---+--------\n"
            "1  | Alien\n"
            "2  | Arrival",
        )

    def test_null_and_empty_result(self):
        result = ResultSet(columns=("id", "year"), rows=((4, None),))
        self.assertEqual(format_table(result), "id | year\n---+-----\n4  | NULL")

    def test_no_rows(self):
        result = execute(parse("SELECT id FROM movies WHERE id > 100"), MOVIES)
        self.assertEqual(format_table(result), "id\n--")


class TestContract(unittest.TestCase):
    def test_errors_are_value_errors(self):
        self.assertTrue(issubclass(ParseError, MiniSQLError))
        self.assertTrue(issubclass(ExecutionError, MiniSQLError))
        self.assertTrue(issubclass(MiniSQLError, ValueError))

    def test_parse_error_position(self):
        error = ParseError("boom", 4)
        self.assertEqual(error.position, 4)
        self.assertEqual(error.message, "boom")
        self.assertEqual(str(error), "at 4: boom")


if __name__ == "__main__":
    unittest.main()
