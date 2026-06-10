from __future__ import annotations

from pathlib import Path

from xmuse_core.platform.review_evidence_bundle import ReviewEvidenceBundleAssembler
from xmuse_core.platform.review_plane import ReviewPlaneController


def test_review_plane_uses_extracted_evidence_bundle_assembler(tmp_path: Path) -> None:
    controller = ReviewPlaneController(
        lanes_path=tmp_path / "feature_lanes.json",
        store_path=tmp_path / "review_plane.json",
        final_actions_path=tmp_path / "final_actions.json",
    )

    assembler = controller._evidence_bundle_assembler()

    assert isinstance(assembler, ReviewEvidenceBundleAssembler)
