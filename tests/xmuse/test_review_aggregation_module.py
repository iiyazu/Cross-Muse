from __future__ import annotations

from xmuse_core.platform.review_aggregation import RunTerminalAggregator
from xmuse_core.platform.review_plane import RunTerminalAggregator as ReviewPlaneExport


def test_review_plane_reexports_run_terminal_aggregator() -> None:
    assert ReviewPlaneExport is RunTerminalAggregator
