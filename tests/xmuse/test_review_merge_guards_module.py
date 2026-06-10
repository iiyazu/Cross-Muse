from __future__ import annotations

from xmuse_core.platform.review_merge_guards import (
    IncompleteLineageTerminationError,
    LineageMergeReport,
)
from xmuse_core.platform.review_plane import (
    IncompleteLineageTerminationError as ReviewPlaneErrorExport,
)
from xmuse_core.platform.review_plane import LineageMergeReport as ReviewPlaneReportExport


def test_review_plane_reexports_merge_guard_types() -> None:
    assert ReviewPlaneErrorExport is IncompleteLineageTerminationError
    assert ReviewPlaneReportExport is LineageMergeReport


def test_lineage_merge_report_completion_contract() -> None:
    report = LineageMergeReport(
        graph_id="graph-a",
        merged_lineages=["lane-1"],
    )
    assert report.is_complete is True
    report.open_lineages.append("lane-2")
    assert report.is_complete is False


def test_incomplete_lineage_termination_error_carries_context() -> None:
    err = IncompleteLineageTerminationError(
        "lane-a",
        "graph-a",
        open_lineages=["lane-b"],
        unmerged_lineages=["lane-c"],
    )

    assert err.lane_id == "lane-a"
    assert err.graph_id == "graph-a"
    assert err.open_lineages == ["lane-b"]
    assert err.unmerged_lineages == ["lane-c"]
    assert "lane-b" in str(err)
    assert "lane-c" in str(err)
