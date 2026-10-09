"""Public tests for the pipeline task.  These are the tests the agents can see.

They cover the happy paths of SPEC.md only.  The acceptance suite is wider.
Run with:  python -m unittest discover -s tests -v
"""
import unittest

from pipeline import (
    CycleError,
    GraphError,
    LogError,
    Node,
    PipelineError,
    Plan,
    PlanError,
    Schedule,
    Step,
    parse_plan,
    render_log,
    schedule,
)

TEXT = """\
# build graph
compile:
lint:
test: compile, lint
package: test
"""


class TestParsePlan(unittest.TestCase):
    def test_nodes_in_written_order(self):
        self.assertEqual(
            parse_plan(TEXT),
            Plan(
                nodes=(
                    Node("compile", ()),
                    Node("lint", ()),
                    Node("test", ("compile", "lint")),
                    Node("package", ("test",)),
                )
            ),
        )

    def test_empty_and_comment_only_input(self):
        self.assertEqual(parse_plan(""), Plan(nodes=()))
        self.assertEqual(parse_plan("# nothing here\n\n"), Plan(nodes=()))

    def test_rejects_bad_syntax(self):
        for text in ("compile", "1bad:", ": dep", "a: b,", "a: b c", "a: a"):
            with self.assertRaises(PlanError, msg=text):
                parse_plan(text)


class TestSchedule(unittest.TestCase):
    def test_levels_and_order(self):
        result = schedule(parse_plan(TEXT))
        self.assertEqual(
            result.levels,
            (("compile", "lint"), ("test",), ("package",)),
        )
        self.assertEqual(result.order, ("compile", "lint", "test", "package"))

    def test_empty_plan(self):
        self.assertEqual(schedule(Plan(nodes=())), Schedule(order=(), levels=()))


class TestLog(unittest.TestCase):
    def test_log_lines(self):
        result = schedule(parse_plan(TEXT))
        steps = [
            Step("compile", "ok"),
            Step("lint", "ok"),
            Step("test", "failed", "2 tests failed"),
            Step("package", "skipped"),
        ]
        self.assertEqual(
            render_log(result, steps),
            "1. L0 ok compile\n"
            "2. L0 ok lint\n"
            "3. L1 failed test: 2 tests failed\n"
            "4. L2 skipped package",
        )

    def test_empty_schedule(self):
        self.assertEqual(render_log(Schedule(), []), "")


class TestContract(unittest.TestCase):
    def test_errors_are_value_errors(self):
        self.assertTrue(issubclass(PlanError, PipelineError))
        self.assertTrue(issubclass(GraphError, PipelineError))
        self.assertTrue(issubclass(CycleError, GraphError))
        self.assertTrue(issubclass(LogError, PipelineError))
        self.assertTrue(issubclass(PipelineError, ValueError))

    def test_plan_error_fields(self):
        error = PlanError("boom", 4)
        self.assertEqual(error.line, 4)
        self.assertEqual(error.message, "boom")
        self.assertEqual(str(error), "line 4: boom")

    def test_graph_error_fields(self):
        error = GraphError("nope", ("b", "a", "b"))
        self.assertEqual(error.nodes, ("a", "b"))
        self.assertEqual(str(error), "nope")


if __name__ == "__main__":
    unittest.main()
