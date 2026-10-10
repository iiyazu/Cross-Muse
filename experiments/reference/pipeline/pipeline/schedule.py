"""Reference implementation of slice B: turn a Plan into a Schedule.

See seeds/pipeline/SPEC.md section 5.
"""
from __future__ import annotations

from .types import CycleError, GraphError, Plan, Schedule


def _check_shape(plan):
    """Return the set of node names, rejecting non-Plans and duplicates."""
    if not isinstance(plan, Plan):
        raise GraphError("expected a Plan, got %r" % (type(plan).__name__,))
    known = set()
    for node in plan.nodes:
        if node.name in known:
            raise GraphError("duplicate node %r" % (node.name,), (node.name,))
        known.add(node.name)
    return known


def _missing_dependencies(plan, known):
    missing = set()
    for node in plan.nodes:
        for dep in node.deps:
            if dep not in known:
                missing.add(dep)
    return tuple(sorted(missing))


def _find_cycle(deps_of, remaining):
    """Deterministic cycle search over the nodes Kahn could not peel (SPEC 5.3).

    Start at the smallest remaining name; walk dependencies in ascending name
    order; the first back edge onto the current path closes the cycle, which is
    then rotated so it starts at its smallest member.
    """
    pool = set(remaining)
    for start in sorted(pool):
        path = [start]
        positions = {start: 0}
        stack = [(start, iter(sorted(dep for dep in deps_of[start] if dep in pool)))]
        while stack:
            _, pending = stack[-1]
            for dep in pending:
                if dep in positions:
                    found = path[positions[dep]:]
                    pivot = found.index(min(found))
                    return tuple(found[pivot:] + found[:pivot])
                path.append(dep)
                positions[dep] = len(path) - 1
                stack.append(
                    (dep, iter(sorted(dep2 for dep2 in deps_of[dep] if dep2 in pool)))
                )
                break
            else:
                stack.pop()
                del positions[path.pop()]
    return ()


def schedule(plan):
    """Validate the graph and compute order/levels (SPEC.md 5)."""
    known = _check_shape(plan)
    missing = _missing_dependencies(plan, known)
    if missing:
        raise GraphError(
            "unknown dependencies: %s" % ", ".join(repr(name) for name in missing),
            missing,
        )
    deps_of = {node.name: tuple(node.deps) for node in plan.nodes}

    levels = []
    done = set()
    pending = set(known)
    while pending:
        ready = sorted(
            name for name in pending if all(dep in done for dep in deps_of[name])
        )
        if not ready:
            cycle = _find_cycle(deps_of, pending)
            raise CycleError(
                "dependency cycle: %s" % " -> ".join(cycle + cycle[:1]), cycle
            )
        levels.append(tuple(ready))
        done.update(ready)
        pending.difference_update(ready)

    order = tuple(name for level in levels for name in level)
    return Schedule(order=order, levels=tuple(levels))
