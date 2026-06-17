"""Verdict ingestion helpers extracted from PlatformOrchestrator.

Pure functions that build and ingest review verdicts through the review
plane, plus gate-report path resolution.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from xmuse_core.observability import log_event
from xmuse_core.structuring.models import ReviewDecision, ReviewVerdict

logger = logging.getLogger(__name__)


class ReviewPlaneProtocol(Protocol):
    """Minimal interface for the review plane used by verdict helpers."""

    def ingest_verdict(
        self,
        task_id: str,
        verdict: ReviewVerdict,
        *,
        require_final_action_approval: bool | None = None,
    ) -> Any: ...


class ReviewFailurePlaneProtocol(Protocol):
    """Review plane surface needed to close a failed review task."""

    @property
    def store(self) -> Any: ...


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def stable_verdict_id_for_lane(
    lane_id: str,
    *,
    lane: dict[str, Any],
) -> str:
    """Return a stable verdict ID for *lane_id* based on the current review task.

    Uses the review_task_id stamped on the lane so the verdict ID is
    deterministic within a single review cycle and does not collide across
    multiple review cycles for the same lane.
    """
    task_id = lane.get("review_task_id") or lane_id
    return f"verdict-merge-{task_id}"


def ingest_merge_verdict(
    lane_id: str,
    summary: str,
    *,
    lane: dict[str, Any],
    review_plane: ReviewPlaneProtocol,
) -> None:
    """Ingest a merge verdict through the review plane for the stdout-fallback path.

    Called when ``_run_review_god`` infers a merge decision from stdout
    rather than from an MCP status update.  This ensures the task->verdict
    lineage is preserved for the merge path so that a merged lane always
    has an auditable verdict lineage (blueprint acceptance signal).
    """
    task_id = lane.get("review_task_id")
    if not task_id:
        return
    verdict_id = str(
        lane.get("review_verdict_id", stable_verdict_id_for_lane(lane_id, lane=lane))
    )
    verdict = ReviewVerdict(
        id=verdict_id,
        lane_id=lane_id,
        decision=ReviewDecision.MERGE,
        summary=summary,
    )
    try:
        review_plane.ingest_verdict(task_id, verdict)
    except Exception:
        log_event(
            logger,
            logging.WARNING,
            "review_plane_merge_verdict_ingest_failed",
            lane_id=lane_id,
            task_id=task_id,
        )


def ingest_rework_verdict(
    lane_id: str,
    summary: str,
    *,
    lane: dict[str, Any],
    review_plane: ReviewPlaneProtocol,
) -> None:
    """Ingest a rework verdict through the review plane for the stdout-fallback path.

    Called when ``_run_review_god`` infers a rework decision from stdout
    rather than from an MCP status update.  This ensures the task->verdict
    lineage is preserved even when the lane is rejected via the fallback
    path and ``on_lane_reviewed`` is never called.
    """
    task_id = lane.get("review_task_id")
    if not task_id:
        return
    verdict = ReviewVerdict(
        id=str(lane.get("review_verdict_id", f"verdict-rework-{lane_id}")),
        lane_id=lane_id,
        decision=ReviewDecision.REWORK,
        summary=summary,
    )
    try:
        review_plane.ingest_verdict(task_id, verdict)
    except Exception:
        log_event(
            logger,
            logging.WARNING,
            "review_plane_rework_verdict_ingest_failed",
            lane_id=lane_id,
            task_id=task_id,
        )


def ingest_review_failure_verdict(
    lane_id: str,
    reason: str,
    *,
    lane: dict[str, Any],
    review_plane: ReviewFailurePlaneProtocol,
    evidence_refs: list[str] | None = None,
) -> None:
    """Close the current ReviewTask when the review provider emitted no verdict.

    This is not a semantic Review GOD decision.  It records a synthetic verdict
    with ``status="review_failed"`` so the review task is auditable without
    treating the failure as merge or rework truth.
    """
    task_id = lane.get("review_task_id")
    if not task_id:
        return
    verdict = ReviewVerdict(
        id=f"verdict-review-failure-{task_id}",
        lane_id=lane_id,
        decision=ReviewDecision.TERMINATE,
        status="review_failed",
        summary=f"Review provider did not emit a parseable verdict. Reason: {reason}.",
        evidence_refs=list(evidence_refs or []),
        terminate_reason=reason,
        task_id=str(task_id),
        created_at=_utc_now(),
    )
    try:
        task = review_plane.store.get_task(str(task_id))
        review_plane.store.save_task_and_verdict(task, verdict)
    except Exception:
        log_event(
            logger,
            logging.WARNING,
            "review_plane_failure_verdict_ingest_failed",
            lane_id=lane_id,
            task_id=str(task_id),
            reason=reason,
        )


def gate_report_ref_for_lane(lane_id: str, *, xmuse_root: Path) -> str | None:
    """Return the relative gate report path for *lane_id* if it exists."""
    report_path = xmuse_root / "logs" / "gates" / lane_id / "report.json"
    if report_path.exists():
        try:
            return str(report_path.relative_to(xmuse_root))
        except ValueError:
            return str(report_path)
    return None
