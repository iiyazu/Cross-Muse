"""Reference implementation of slice C: deterministic execution log.

See seeds/pipeline/SPEC.md section 6.
"""
from __future__ import annotations

from .types import LogError, Schedule, Step

_STATUSES = ("ok", "failed", "skipped")


def render_log(schedule, steps):
    """Render one line per step in schedule order (SPEC.md 6)."""
    if not isinstance(schedule, Schedule):
        raise LogError("expected a Schedule, got %r" % (type(schedule).__name__,))

    level_of = {}
    for index, level in enumerate(schedule.levels):
        for name in level:
            if name in level_of:
                raise LogError("node %r appears in more than one level" % (name,))
            level_of[name] = index

    order = tuple(schedule.order)
    if len(set(order)) != len(order):
        raise LogError("schedule.order repeats a node")
    if set(order) != set(level_of):
        raise LogError("schedule.order and schedule.levels cover different nodes")

    by_node = {}
    for step in steps:
        if not isinstance(step, Step):
            raise LogError("expected a Step, got %r" % (type(step).__name__,))
        if step.node in by_node:
            raise LogError("duplicate step for node %r" % (step.node,))
        if step.node not in level_of:
            raise LogError("unknown node %r" % (step.node,))
        if step.status not in _STATUSES:
            raise LogError("unknown status %r" % (step.status,))
        if not isinstance(step.detail, str):
            raise LogError("detail of node %r is not a string" % (step.node,))
        if "\n" in step.detail or "\r" in step.detail:
            raise LogError("detail of node %r contains a line break" % (step.node,))
        by_node[step.node] = step

    missing = [name for name in order if name not in by_node]
    if missing:
        raise LogError("missing steps for: %s" % ", ".join(missing))

    lines = []
    for index, name in enumerate(order, start=1):
        step = by_node[name]
        line = "%d. L%d %s %s" % (index, level_of[name], step.status, name)
        if step.detail:
            line += ": " + step.detail
        lines.append(line)
    return "\n".join(lines)
