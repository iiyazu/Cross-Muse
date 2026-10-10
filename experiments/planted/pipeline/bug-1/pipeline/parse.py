"""PLANTED BUG 1 -- do not ship.  See planted/pipeline/BUGS.md.

Only the duplicate-name handling differs from the reference: the parser collects
nodes into a ``name -> deps`` table and lets a later definition silently replace
an earlier one, instead of raising ``PlanError`` on the repeated line.  Every
well-formed definition still parses correctly, so only a test that feeds the
parser the same node twice can tell.
"""
from __future__ import annotations

import re

from .types import Node, Plan, PlanError

_LINE_RE = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)\s*:\s*(.*)\Z")
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def _parse_line(line, number):
    match = _LINE_RE.match(line)
    if match is None:
        raise PlanError("expected '<name>: [dep, ...]'", number)
    name = match.group(1)
    rest = match.group(2).strip()
    if not rest:
        return Node(name, ())
    deps = []
    seen = set()
    for chunk in rest.split(","):
        dep = chunk.strip()
        if _NAME_RE.match(dep) is None:
            raise PlanError("invalid dependency name %r" % (chunk,), number)
        if dep == name:
            raise PlanError("node %r depends on itself" % (name,), number)
        if dep in seen:
            raise PlanError("duplicate dependency %r" % (dep,), number)
        seen.add(dep)
        deps.append(dep)
    return Node(name, tuple(deps))


def parse_plan(text):
    """Parse one task definition into a frozen Plan (SPEC.md 4)."""
    if not isinstance(text, str):
        raise TypeError("parse_plan expects a string, got %r" % (type(text).__name__,))
    order = []
    table = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        node = _parse_line(line, number)
        # Bug: a repeated node name overwrites the earlier definition; the
        # duplicate line is never reported.
        if node.name not in table:
            order.append(node.name)
        table[node.name] = node.deps
    return Plan(nodes=tuple(Node(name, table[name]) for name in order))
