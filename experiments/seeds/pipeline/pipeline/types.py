"""Shared data structures and error types for the pipeline package.

This module is the frozen contract described in SPEC.md.  The parser, the
scheduler and the log renderer all speak the record types defined here, so no
slice has to guess what another slice means.
"""
from __future__ import annotations

from dataclasses import dataclass


class PipelineError(ValueError):
    """Base class of every error raised by this package."""


class PlanError(PipelineError):
    """The task definition text cannot be parsed.

    ``line`` is the 1-based line number in the source text, or 0 when the
    problem is not attached to a line.
    """

    def __init__(self, message, line=0):
        super().__init__("line %d: %s" % (line, message))
        self.message = message
        self.line = line


class GraphError(PipelineError):
    """The dependency graph itself cannot be used.

    ``nodes`` is the tuple of node names the error is about, sorted ascending
    and deduplicated.
    """

    def __init__(self, message, nodes=()):
        super().__init__(message)
        self.message = message
        self.nodes = tuple(sorted(set(nodes)))


class CycleError(GraphError):
    """The dependency graph contains a cycle.

    ``cycle`` is the cycle as a tuple of node names, rotated so that the first
    name is the lexicographically smallest member of the cycle and the first
    name is not repeated at the end.  ``nodes`` (inherited) is the same set of
    names, sorted.
    """

    def __init__(self, message, cycle=()):
        super().__init__(message, tuple(sorted(set(cycle))))
        self.cycle = tuple(cycle)


class LogError(PipelineError):
    """The schedule and the step records cannot be rendered together."""


@dataclass(frozen=True)
class Node:
    """One task.  ``deps`` are node names, in the order they were written."""

    name: str
    deps: tuple = ()


@dataclass(frozen=True)
class Plan:
    """A parsed task definition.  ``nodes`` is in written order."""

    nodes: tuple = ()


@dataclass(frozen=True)
class Schedule:
    """A scheduled plan.

    ``levels[k]`` holds the nodes that can run concurrently at level ``k``,
    sorted by name.  ``order`` is ``levels`` flattened.
    """

    order: tuple = ()
    levels: tuple = ()


@dataclass(frozen=True)
class Step:
    """One line of the execution log.  ``status`` is ok, failed or skipped."""

    node: str
    status: str
    detail: str = ""
