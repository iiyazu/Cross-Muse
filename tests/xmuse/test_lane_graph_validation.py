from __future__ import annotations

import pytest

from xmuse_core.structuring.graph_validation import validate_lane_collection
from xmuse_core.structuring.models import LaneNode


def test_validate_lane_collection_rejects_duplicate_lane_ids() -> None:
    lanes = [
        LaneNode(feature_id="duplicate", prompt="Build first."),
        LaneNode(feature_id="duplicate", prompt="Build second."),
    ]

    with pytest.raises(ValueError, match="duplicate lane id: duplicate"):
        validate_lane_collection(lanes)


def test_validate_lane_collection_checks_internal_dependency_cycles_only() -> None:
    lanes = [
        LaneNode(feature_id="root", prompt="Build root."),
        LaneNode(feature_id="worker", prompt="Build worker.", depends_on=["external"]),
    ]

    validate_lane_collection(lanes)
