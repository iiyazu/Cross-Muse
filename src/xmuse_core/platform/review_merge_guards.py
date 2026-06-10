from __future__ import annotations

from dataclasses import dataclass, field


class IncompleteLineageTerminationError(RuntimeError):
    """Raised when a termination would leave graph lineages without a merge."""

    def __init__(
        self,
        lane_id: str,
        graph_id: str,
        *,
        open_lineages: list[str],
        unmerged_lineages: list[str],
    ) -> None:
        self.lane_id = lane_id
        self.graph_id = graph_id
        self.open_lineages = list(open_lineages)
        self.unmerged_lineages = list(unmerged_lineages)
        parts: list[str] = [f"termination of lane {lane_id!r} in graph {graph_id!r} is unsafe:"]
        if open_lineages:
            parts.append(f"  open lineages: {open_lineages}")
        if unmerged_lineages:
            parts.append(f"  unmerged lineages: {unmerged_lineages}")
        super().__init__("\n".join(parts))


@dataclass
class LineageMergeReport:
    """Result of review-plane lineage merge completeness checks."""

    graph_id: str
    merged_lineages: list[str] = field(default_factory=list)
    terminated_without_merge: list[str] = field(default_factory=list)
    open_lineages: list[str] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return not self.terminated_without_merge and not self.open_lineages
