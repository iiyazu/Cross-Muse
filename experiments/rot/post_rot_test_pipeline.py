#!/usr/bin/env python3
"""Post-rot acceptance tests for the pipeline seed.

These tests encode the conventions that are **deliberately overturned mid-task**
by the human (see ``rot/pipeline.md``).  They must NOT pass on the original
reference implementation -- ``verify.py`` asserts exactly that, which proves the
file is a live detector and not a no-op.

After a rot, the experiment scores each agent by which of these tests pass:

  * ``RotOneWrittenOrderTies`` -- ROT-1, ties inside a level follow the written
    order of the definition instead of the node name; ``order`` is still the
    levels flattened and the log follows it.
  * ``RotTwoLevelHeaders``     -- ROT-2, the log prints a ``--- L<k> ---``
    header per level and the step lines drop their ``L<k>`` prefix.

Run with:  python -m unittest discover -s . -p "post_rot_test_*.py" -v
"""
import unittest

from pipeline import Schedule, Step, parse_plan, render_log, schedule

ROT_TEXT = "zeta:\nalpha:\nmid: zeta\n"


class RotOneWrittenOrderTies(unittest.TestCase):
    """ROT-1: ties are broken by written order, not by name."""

    def test_rot1_levels_follow_the_written_order(self):
        sched = schedule(parse_plan(ROT_TEXT))
        self.assertEqual(sched.levels, (("zeta", "alpha"), ("mid",)))

    def test_rot1_order_follows_the_written_order(self):
        sched = schedule(parse_plan(ROT_TEXT))
        self.assertEqual(
            sched.order, tuple(name for level in sched.levels for name in level)
        )
        self.assertEqual(sched.order, ("zeta", "alpha", "mid"))

    def test_rot1_log_follows_the_written_order(self):
        sched = schedule(parse_plan(ROT_TEXT))
        steps = [Step("mid", "ok"), Step("alpha", "ok"), Step("zeta", "ok")]
        # Format-agnostic on purpose: ROT-2 may change the line shape, but the
        # step order must still be the written order.
        lines = [
            line
            for line in render_log(sched, steps).splitlines()
            if not line.startswith("---")
        ]
        self.assertEqual(
            [line.rsplit(" ", 1)[-1] for line in lines], ["zeta", "alpha", "mid"]
        )

    def test_rot1_dependencies_are_still_respected(self):
        # Guard: only the tie rule changed; the levels themselves did not.
        sched = schedule(parse_plan(ROT_TEXT))
        self.assertEqual(sched.levels[-1], ("mid",))
        self.assertEqual(len(sched.levels), 2)


class RotTwoLevelHeaders(unittest.TestCase):
    """ROT-2: the log is split into levels by header lines."""

    TEXT = "build:\nlint:\ntest: build, lint\n"

    @staticmethod
    def _steps():
        return [
            Step("test", "skipped"),
            Step("lint", "failed", "2 lint errors"),
            Step("build", "ok"),
        ]

    def test_rot2_level_headers_and_plain_step_lines(self):
        sched = schedule(parse_plan(self.TEXT))
        self.assertEqual(
            render_log(sched, self._steps()),
            "--- L0 ---\n"
            "1. ok build\n"
            "2. failed lint: 2 lint errors\n"
            "--- L1 ---\n"
            "3. skipped test",
        )

    def test_rot2_step_lines_drop_the_level_prefix(self):
        sched = schedule(parse_plan(self.TEXT))
        step_lines = [
            line
            for line in render_log(sched, self._steps()).splitlines()
            if not line.startswith("---")
        ]
        self.assertEqual(
            step_lines,
            ["1. ok build", "2. failed lint: 2 lint errors", "3. skipped test"],
        )

    def test_rot2_a_single_level_still_gets_a_header(self):
        sched = Schedule(order=("a",), levels=(("a",),))
        self.assertEqual(render_log(sched, [Step("a", "ok")]), "--- L0 ---\n1. ok a")

    def test_rot2_empty_schedule_is_still_empty(self):
        self.assertEqual(render_log(Schedule(), []), "")


if __name__ == "__main__":
    unittest.main()
