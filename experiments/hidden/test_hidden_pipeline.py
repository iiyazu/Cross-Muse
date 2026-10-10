"""Hidden acceptance tests for the pipeline seed (SPEC.md).

These live outside ``seeds/pipeline`` and are copied in only after the run, so the
agents never see them.  They cover the edge cases and the cross-slice conventions
that the public tests deliberately leave out: cycles, self-dependencies, unknown
dependencies, duplicate definitions, empty input and the deterministic tie rules.

Run with:  python -m unittest discover -s . -p "test_hidden_*.py" -v
"""
import dataclasses
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


class TestParsePlanHidden(unittest.TestCase):
    def test_empty_input_is_an_empty_plan(self):
        for text in ("", "   ", "\n\t\n", "# only a comment\n", "\n# a\n\n   \n"):
            self.assertEqual(parse_plan(text), Plan(nodes=()), repr(text))

    def test_line_numbers_are_one_based_and_count_blanks_and_comments(self):
        for text, line in (
            ("\n# comment\nbad line here\na: b\n", 3),
            ("a:\n\n# c\n1bad:\n", 4),
            ("#x\na: b,\n", 2),
        ):
            with self.assertRaises(PlanError) as cm:
                parse_plan(text)
            self.assertEqual(cm.exception.line, line, repr(text))

    def test_duplicate_node_definition_is_rejected(self):
        for text, line in (
            ("a: b\na: c\n", 2),
            ("a:\na:\n", 2),
            ("a:\nb: a\na: c\n", 3),
            ("a:\nb:\na:\n", 3),
        ):
            with self.assertRaises(PlanError) as cm:
                parse_plan(text)
            self.assertEqual(cm.exception.line, line, repr(text))

    def test_duplicate_dependency_is_rejected(self):
        for text, line in (("a: b, b\n", 1), ("a:\nb: c, c\n", 2), ("a: b ,b\n", 1)):
            with self.assertRaises(PlanError) as cm:
                parse_plan(text)
            self.assertEqual(cm.exception.line, line, repr(text))

    def test_self_dependency_is_a_plan_error(self):
        for text, line in (("a: a\n", 1), ("a: b, a\n", 1), ("a:\nb: b\n", 2)):
            with self.assertRaises(PlanError) as cm:
                parse_plan(text)
            self.assertEqual(cm.exception.line, line, repr(text))
        # It is a PlanError, not a GraphError/CycleError: the parser sees it.
        with self.assertRaises(PlanError):
            parse_plan("a: a")

    def test_identifiers_are_strict(self):
        for text in (
            "1a:\n",
            "-a:\n",
            "a b:\n",
            "a-b:\n",
            "\u00e9:\n",
            "a: 1b\n",
            "a: b-1\n",
            "a: b.c\n",
            "a: 'b'\n",
        ):
            with self.assertRaises(PlanError, msg=repr(text)):
                parse_plan(text)

    def test_names_are_case_sensitive(self):
        plan = parse_plan("Build:\nbuild:\n")
        self.assertEqual([node.name for node in plan.nodes], ["Build", "build"])

    def test_dependency_order_is_preserved(self):
        plan = parse_plan("z:\ny:\nx:  z ,y  \n")
        self.assertEqual(plan.nodes, (Node("z", ()), Node("y", ()), Node("x", ("z", "y"))))

    def test_whitespace_around_the_colon_is_allowed(self):
        plan = parse_plan("a\t:\tb\n")
        self.assertEqual(plan.nodes, (Node("a", ("b",)),))

    def test_comments_blanks_and_crlf(self):
        plan = parse_plan("# c\r\na: b\r\n\r\n   # indented comment\r\nb:\r\n")
        self.assertEqual(plan.nodes, (Node("a", ("b",)), Node("b", ())))

    def test_forward_references_are_allowed(self):
        plan = parse_plan("test: compile\ncompile:\n")
        self.assertEqual(plan.nodes, (Node("test", ("compile",)), Node("compile", ())))

    def test_non_string_is_a_type_error(self):
        for value in (7, None, ["a:"], b"a:"):
            with self.assertRaises(TypeError, msg=repr(value)):
                parse_plan(value)

    def test_plan_error_defaults_to_line_zero(self):
        error = PlanError("boom")
        self.assertEqual(error.line, 0)
        self.assertEqual(error.message, "boom")
        self.assertEqual(str(error), "line 0: boom")

    def test_records_are_frozen_dataclasses(self):
        plan = parse_plan("a: b\nb:\n")
        self.assertTrue(dataclasses.is_dataclass(plan))
        self.assertTrue(dataclasses.is_dataclass(plan.nodes[0]))
        with self.assertRaises(AttributeError):
            plan.nodes = ()
        with self.assertRaises(AttributeError):
            plan.nodes[0].name = "other"
        self.assertEqual(Node("a"), Node(name="a", deps=()))
        self.assertEqual(Plan(()), Plan(nodes=()))


class TestScheduleHidden(unittest.TestCase):
    def test_empty_plan_schedules_to_nothing(self):
        self.assertEqual(schedule(Plan(nodes=())), Schedule(order=(), levels=()))
        self.assertEqual(schedule(parse_plan("# nothing\n")), Schedule(order=(), levels=()))

    def test_levels_use_the_longest_path(self):
        # d depends on a (level 0) and on c (level 2), so d must be level 3.
        sched = schedule(parse_plan("a:\nb: a\nc: b\nd: a, c\ne: d\n"))
        self.assertEqual(
            sched.levels, (("a",), ("b",), ("c",), ("d",), ("e",))
        )

    def test_ties_are_broken_by_name(self):
        sched = schedule(parse_plan("m:\nz:\na: m\nb: m\n"))
        self.assertEqual(sched.levels, (("m", "z"), ("a", "b")))
        self.assertEqual(sched.order, ("m", "z", "a", "b"))

    def test_order_is_the_levels_flattened(self):
        # A plain min-heap topological sort would give (a, b, c) here; the SPEC
        # says order is levels flattened, which is (a, c, b).
        sched = schedule(parse_plan("a:\nb: a\nc:\n"))
        self.assertEqual(sched.levels, (("a", "c"), ("b",)))
        self.assertEqual(sched.order, ("a", "c", "b"))
        self.assertEqual(
            sched.order, tuple(name for level in sched.levels for name in level)
        )

    def test_forward_references_are_scheduled(self):
        sched = schedule(parse_plan("package: test\ntest: compile\ncompile:\n"))
        self.assertEqual(sched.levels, (("compile",), ("test",), ("package",)))

    def test_unknown_dependency_is_a_graph_error(self):
        with self.assertRaises(GraphError) as cm:
            schedule(parse_plan("a: nope\n"))
        self.assertEqual(cm.exception.nodes, ("nope",))

    def test_all_unknown_dependencies_are_collected_sorted(self):
        with self.assertRaises(GraphError) as cm:
            schedule(parse_plan("a: y, x\nb: x\nc: z\n"))
        self.assertEqual(cm.exception.nodes, ("x", "y", "z"))

    def test_self_dependency_in_a_hand_built_plan_is_a_cycle(self):
        with self.assertRaises(CycleError) as cm:
            schedule(Plan(nodes=(Node("a", ("a",)),)))
        self.assertEqual(cm.exception.cycle, ("a",))
        self.assertEqual(cm.exception.nodes, ("a",))

    def test_cycle_is_reported_deterministically(self):
        for text, cycle in (
            ("a: b\nb: a\n", ("a", "b")),
            ("a: b\nb: c\nc: a\n", ("a", "b", "c")),
            ("z: a\na: b\nb: a\n", ("a", "b")),
            ("a: b\nb: a\nx: y\ny: x\n", ("a", "b")),
            ("b: c\nc: b\na: b\n", ("b", "c")),
        ):
            with self.assertRaises(CycleError) as cm:
                schedule(parse_plan(text))
            self.assertEqual(cm.exception.cycle, cycle, repr(text))

    def test_cycle_skips_nodes_that_only_lead_into_it(self):
        # The smallest remaining node is `a`, which is not on the cycle.
        with self.assertRaises(CycleError) as cm:
            schedule(parse_plan("a: c\nb: c\nc: d\nd: c\n"))
        self.assertEqual(cm.exception.cycle, ("c", "d"))

    def test_cycle_error_is_a_graph_error(self):
        self.assertTrue(issubclass(CycleError, GraphError))
        error = CycleError("cycle", ("c", "a", "b"))
        self.assertEqual(error.cycle, ("c", "a", "b"))
        self.assertEqual(error.nodes, ("a", "b", "c"))
        self.assertEqual(str(error), "cycle")

    def test_duplicate_nodes_in_a_hand_built_plan_are_rejected(self):
        with self.assertRaises(GraphError) as cm:
            schedule(Plan(nodes=(Node("a", ()), Node("a", ("b",)))))
        self.assertEqual(cm.exception.nodes, ("a",))

    def test_duplicate_dependency_in_a_hand_built_plan_is_tolerated(self):
        sched = schedule(Plan(nodes=(Node("a", ("b", "b")), Node("b", ()))))
        self.assertEqual(sched.levels, (("b",), ("a",)))

    def test_only_a_plan_is_accepted(self):
        for value in (None, "a:", [Node("a")], Schedule()):
            with self.assertRaises(GraphError, msg=repr(value)):
                schedule(value)

    def test_schedule_is_frozen_and_pure(self):
        plan = parse_plan("a:\nb: a\n")
        before = plan.nodes
        sched = schedule(plan)
        self.assertIsInstance(sched, Schedule)
        self.assertIsInstance(sched.order, tuple)
        self.assertIsInstance(sched.levels, tuple)
        self.assertTrue(all(isinstance(level, tuple) for level in sched.levels))
        self.assertEqual(plan.nodes, before)
        self.assertEqual(schedule(plan), sched)
        with self.assertRaises(AttributeError):
            sched.order = ()

    def test_error_taxonomy(self):
        self.assertTrue(issubclass(PipelineError, ValueError))
        self.assertTrue(issubclass(PlanError, PipelineError))
        self.assertTrue(issubclass(GraphError, PipelineError))
        self.assertTrue(issubclass(LogError, PipelineError))
        self.assertEqual(GraphError("m", ("b", "a", "b")).nodes, ("a", "b"))
        self.assertEqual(GraphError("m").nodes, ())


class TestLogHidden(unittest.TestCase):
    TEXT = "compile:\nlint:\ntest: compile, lint\npackage: test\n"

    def test_lines_follow_schedule_order_not_step_order(self):
        sched = schedule(parse_plan(self.TEXT))
        steps = [
            Step("package", "skipped"),
            Step("test", "failed", "2 tests failed"),
            Step("lint", "ok"),
            Step("compile", "ok"),
        ]
        self.assertEqual(
            render_log(sched, steps),
            "1. L0 ok compile\n"
            "2. L0 ok lint\n"
            "3. L1 failed test: 2 tests failed\n"
            "4. L2 skipped package",
        )

    def test_log_follows_the_level_order(self):
        sched = schedule(parse_plan("a:\nb: a\nc:\n"))
        steps = [Step("b", "ok"), Step("c", "ok"), Step("a", "ok")]
        self.assertEqual(
            render_log(sched, steps), "1. L0 ok a\n2. L0 ok c\n3. L1 ok b"
        )

    def test_detail_is_appended_only_when_present(self):
        sched = Schedule(order=("a", "b"), levels=(("a", "b"),))
        self.assertEqual(
            render_log(sched, [Step("a", "ok"), Step("b", "failed", "boom")]),
            "1. L0 ok a\n2. L0 failed b: boom",
        )

    def test_detail_whitespace_is_preserved(self):
        sched = Schedule(order=("a",), levels=(("a",),))
        self.assertEqual(
            render_log(sched, [Step("a", "ok", "  padded  ")]),
            "1. L0 ok a:   padded  ",
        )

    def test_indices_are_not_zero_padded(self):
        text = "\n".join("n%02d:" % i for i in range(1, 11))
        sched = schedule(parse_plan(text))
        steps = [Step("n%02d" % i, "ok") for i in range(1, 11)]
        lines = render_log(sched, steps).splitlines()
        self.assertEqual(lines[0], "1. L0 ok n01")
        self.assertEqual(lines[9], "10. L0 ok n10")

    def test_steps_may_be_any_iterable(self):
        sched = Schedule(order=("a",), levels=(("a",),))
        self.assertEqual(render_log(sched, (step for step in [Step("a", "ok")])), "1. L0 ok a")

    def test_missing_unknown_and_duplicate_steps_are_rejected(self):
        sched = Schedule(order=("a", "b"), levels=(("a",), ("b",)))
        with self.assertRaises(LogError):
            render_log(sched, [Step("a", "ok")])
        with self.assertRaises(LogError):
            render_log(sched, [Step("a", "ok"), Step("b", "ok"), Step("c", "ok")])
        with self.assertRaises(LogError):
            render_log(sched, [Step("a", "ok"), Step("a", "ok")])
        with self.assertRaises(LogError):
            render_log(sched, [Step("a", "ok"), "b"])

    def test_status_must_be_known(self):
        sched = Schedule(order=("a",), levels=(("a",),))
        for status in ("done", "OK", "", "ok ", "failed "):
            with self.assertRaises(LogError, msg=repr(status)):
                render_log(sched, [Step("a", status)])

    def test_detail_must_be_one_line(self):
        sched = Schedule(order=("a",), levels=(("a",),))
        for detail in ("a\nb", "a\rb", "a\r\nb", "\n"):
            with self.assertRaises(LogError, msg=repr(detail)):
                render_log(sched, [Step("a", "ok", detail)])

    def test_detail_must_be_a_string(self):
        sched = Schedule(order=("a",), levels=(("a",),))
        for detail in (7, None, ["x"]):
            with self.assertRaises(LogError, msg=repr(detail)):
                render_log(sched, [Step("a", "ok", detail)])

    def test_inconsistent_schedule_is_rejected(self):
        for sched in (
            Schedule(order=("a",), levels=(("a",), ("b",))),
            Schedule(order=("a", "a"), levels=(("a",),)),
            Schedule(order=("a",), levels=()),
            Schedule(order=("a",), levels=(("a",), ("a",))),
            Schedule(order=(), levels=(("a",),)),
        ):
            with self.assertRaises(LogError, msg=repr(sched)):
                render_log(sched, [Step("a", "ok")])

    def test_empty_schedule_and_no_steps(self):
        self.assertEqual(render_log(Schedule(), []), "")
        self.assertEqual(render_log(Schedule(), ()), "")
        self.assertEqual(render_log(Schedule(order=(), levels=()), iter([])), "")

    def test_no_trailing_newline(self):
        sched = schedule(parse_plan(self.TEXT))
        text = render_log(sched, [Step(name, "ok") for name in sched.order])
        self.assertFalse(text.endswith("\n"))
        self.assertEqual(len(text.splitlines()), 4)

    def test_non_schedule_is_a_log_error(self):
        for value in (None, "a", 7, Plan(nodes=())):
            with self.assertRaises(LogError, msg=repr(value)):
                render_log(value, [])


if __name__ == "__main__":
    unittest.main()
