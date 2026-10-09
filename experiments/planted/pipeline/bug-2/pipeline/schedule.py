"""PLANTED BUG 2 -- do not ship.  See planted/pipeline/BUGS.md.

Only ``schedule`` differs from the reference: ``levels`` is still computed by the
layered Kahn pass, but ``order`` is produced by a second, independent min-heap
topological sort.  Every graph still schedules, the result is still a valid
topological order and the public tests still pass -- it just is not ``levels``
flattened, so it disagrees with the SPEC tie rule whenever an independent node
sorts after a shallower node's name.
"""
from __future__ import annotations

import heapq

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
    """Deterministic cycle search over the nodes Kahn could not peel (SPEC 5.3)."""
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


def _topological_order(deps_of, known):
    """A valid topological order taken from a min-heap of ready nodes."""
    children = {name: [] for name in known}
    indegree = {}
    for name in known:
        deps = set(deps_of[name])
        indegree[name] = len(deps)
        for dep in deps:
            children[dep].append(name)
    ready = [name for name in known if indegree[name] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        name = heapq.heappop(ready)
        order.append(name)
        for child in children[name]:
            indegree[child] -= 1
            if indegree[child] == 0:
                heapq.heappush(ready, child)
    return tuple(order)


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

    # Bug: `order` is a second topological sort, not the flattened levels.
    order = _topological_order(deps_of, known)
    return Schedule(order=order, levels=tuple(levels))
