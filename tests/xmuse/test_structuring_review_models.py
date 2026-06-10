from __future__ import annotations

from xmuse_core.structuring.models import ReviewVerdict as ModelsReviewVerdict
from xmuse_core.structuring.models import StructuredEvidenceBundle as ModelsBundle
from xmuse_core.structuring.review_models import (
    ReviewDecision,
    ReviewVerdict,
    StructuredEvidenceBundle,
)


def test_structuring_models_reexports_review_models() -> None:
    assert ModelsReviewVerdict is ReviewVerdict
    assert ModelsBundle is StructuredEvidenceBundle


def test_review_verdict_model_keeps_existing_contract() -> None:
    verdict = ReviewVerdict(
        id="verdict-1",
        lane_id="lane-1",
        decision=ReviewDecision.MERGE,
        summary="Looks good.",
    )

    assert verdict.status == "finalized"
    assert verdict.evidence_refs == []
    assert verdict.patch_instructions is None
