"""ReviewPlaneController: persistent auditor for lane review work.

This module implements the ``review_plane`` blueprint track.  It makes Review
GOD a persistent auditor by:

1. Creating a ``ReviewTask`` when a lane enters review.
2. Accepting a ``ReviewVerdict`` emitted by Review GOD and persisting it.
3. Driving the lane state transition through ``VerdictAdapterResult``.
4. Recording the full task→verdict→transition lineage so that every
   ``approve``, ``requeue``, ``patch_forward``, and ``terminate`` decision is
   auditable from the store.

The controller is intentionally stateless between calls; all state lives in
``VerdictStore`` and the lane file managed by ``LaneStateMachine``.

Merge guards (evbundle_6259476d67dd414a8be293d1025ccb8c)
---------------------------------------------------------
Evidence bundle evbundle_6259476d67dd414a8be293d1025ccb8c showed a graph
lineage terminating without a proper merge verdict, leaving sibling lineages
stranded and the run-level terminal status ambiguous.

Three guards are added to prevent this:

``check_lineage_merge_completeness``
    Inspects every lane lineage in a graph and classifies each as
    ``merged``, ``terminated_without_merge``, or ``open``.  Returns a
    :class:`LineageMergeReport` that callers and the evidence bundle can
    use to surface incomplete terminations.

``assert_termination_safe``
    Called before a ``TERMINATE`` verdict is ingested.  Raises
    :class:`IncompleteLineageTerminationError` when the termination would
    leave one or more sibling lineages in the same graph open and without
    a merge verdict, preventing the review plane from allowing termination
    in an incomplete state.

``record_incomplete_termination``
    Writes a structured incomplete-termination signal into the verdict
    store for a lane that reached a terminal state without a merge verdict.
    The signal is picked up by ``assemble_evidence_bundle`` as a negative
    signal ref so the next planning cycle can reason about the gap.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.chat.acceptance_spine import AcceptanceSpineStore
from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.platform.review_aggregation import RunTerminalAggregator
from xmuse_core.platform.review_evidence_bundle import ReviewEvidenceBundleAssembler
from xmuse_core.platform.review_merge_guards import (
    IncompleteLineageTerminationError,
    LineageMergeReport,
)
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.platform.verdict_adapter import VerdictAdapterResult, adapt_review_verdict
from xmuse_core.structuring.models import (
    LaneGraph,
    ReviewDecision,
    ReviewTask,
    ReviewTaskStatus,
    ReviewVerdict,
    RunTerminalAggregation,
    StructuredEvidenceBundle,
)
from xmuse_core.structuring.verdict_store import (
    ClarificationStore,
    EvidenceBundleStore,
    VerdictStore,
)

logger = logging.getLogger(__name__)


def _utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


# ---------------------------------------------------------------------------
# Merge-guard types
# ---------------------------------------------------------------------------

# Lane statuses that represent a clean merge outcome.
_MERGED_STATUSES: frozenset[str] = frozenset({"merged", "done", "completed"})

# Lane statuses that represent a terminal failure / stop without merge.
#
# ``gate_failed`` is intentionally excluded: the state machine allows it to
# retry, rework, or return to gated, so it is still an open/recoverable lineage
# until projected to ``failed``.
_FAILED_STATUSES: frozenset[str] = frozenset({"failed", "exec_failed"})

# Lane statuses that are still actively in-flight (not yet terminal).
_OPEN_STATUSES: frozenset[str] = frozenset(
    {
        "pending",
        "dispatched",
        "executed",
        "gated",
        "reviewed",
        "reworking",
        "awaiting_final_action",
        "rejected",
        "gate_failed",
    }
)


class ReviewPlaneController:
    """Coordinates the full review lifecycle for a single lane.

    Usage::

        controller = ReviewPlaneController(
            lanes_path=Path("xmuse/feature_lanes.json"),
            store_path=Path("xmuse/review_plane.json"),
            final_actions_path=Path("xmuse/final_actions.json"),
        )

        # When a lane enters review (after gate passes):
        task = controller.open_review_task(lane_id="my-lane")

        # When Review GOD emits a verdict:
        result = controller.ingest_verdict(
            task_id=task.task_id,
            verdict=ReviewVerdict(
                id="verdict-abc",
                lane_id="my-lane",
                decision=ReviewDecision.MERGE,
                summary="No findings.",
            ),
            require_final_action_approval=False,
        )
        # result.transition_status is the new lane status (or None for holds)
    """

    def __init__(
        self,
        *,
        lanes_path: Path | str,
        store_path: Path | str,
        final_actions_path: Path | str,
        require_final_action_approval: bool = False,
        clarification_store_path: Path | str | None = None,
    ) -> None:
        self._lanes_path = Path(lanes_path)
        self._store_path = Path(store_path)
        self._sm = LaneStateMachine(self._lanes_path)
        self._store = VerdictStore(self._store_path)
        self._final_actions_path = Path(final_actions_path)
        self._final_action_store = FinalActionGateStore(self._final_actions_path)
        self._require_final_action_approval = require_final_action_approval
        self._clarification_store: ClarificationStore | None = (
            ClarificationStore(Path(clarification_store_path))
            if clarification_store_path is not None
            else None
        )

    @property
    def store(self) -> VerdictStore:
        return self._store

    # ------------------------------------------------------------------
    # Task lifecycle
    # ------------------------------------------------------------------

    def open_review_task(
        self,
        lane_id: str,
        *,
        gate_report_ref: str | None = None,
    ) -> ReviewTask:
        """Create a ReviewTask for *lane_id* and persist it.

        If a pending task already exists for this lane it is returned as-is
        (idempotent).
        """
        existing = [
            t
            for t in self._store.list_tasks_for_lane(lane_id)
            if t.status == ReviewTaskStatus.PENDING
        ]
        if existing:
            return existing[-1]

        lane = self._sm.get_lane(lane_id)
        task = ReviewTask(
            task_id=_new_id("rtask"),
            lane_id=lane_id,
            graph_id=str(lane.get("graph_id") or "") or None,
            resolution_id=str(lane.get("resolution_id") or "") or None,
            lane_prompt=str(lane.get("prompt", "")),
            gate_report_ref=gate_report_ref,
            status=ReviewTaskStatus.PENDING,
            created_at=_utc_now(),
        )
        return self._store.save_task(task)

    def cancel_review_task(self, task_id: str) -> ReviewTask:
        """Mark a task as cancelled (e.g. lane was retried before verdict).

        The read-modify-write is performed atomically via
        :meth:`VerdictStore.cancel_task` so a concurrent verdict emission
        cannot silently overwrite the cancellation.
        """
        return self._store.cancel_task(task_id, updated_at=_utc_now())

    # ------------------------------------------------------------------
    # Verdict ingestion
    # ------------------------------------------------------------------

    def ingest_verdict(
        self,
        task_id: str,
        verdict: ReviewVerdict,
        *,
        require_final_action_approval: bool | None = None,
    ) -> VerdictAdapterResult:
        """Persist *verdict*, update the task, and drive the lane transition.

        Returns the ``VerdictAdapterResult`` so callers can act on
        ``transition_status``, ``final_action``, and ``patch_lane``.

        The lane state machine transition is **not** applied here; the caller
        (e.g. ``PlatformOrchestrator``) is responsible for calling
        ``sm.transition()``.  This keeps the controller side-effect-free with
        respect to the lane file and easy to test.

        Merge guard (evbundle_6259476d67dd414a8be293d1025ccb8c):
            When the verdict decision is ``TERMINATE``, :meth:`assert_termination_safe`
            is called before the verdict is persisted.  If the graph still has
            open or unmerged sibling lineages the call raises
            :class:`IncompleteLineageTerminationError` and the verdict is
            **not** stored, preventing the review plane from allowing
            termination in an incomplete state.
        """
        task = self._store.get_task(task_id)

        # Merge guard: block TERMINATE verdicts when sibling lineages are
        # still open or have already terminated without a merge verdict.
        if verdict.decision == ReviewDecision.TERMINATE:
            lane = self._sm.get_lane(verdict.lane_id)
            graph_id = lane.get("graph_id")
            if graph_id:
                self.assert_termination_safe(verdict.lane_id, str(graph_id))

        # Stamp the verdict with the task_id for lineage
        if verdict.task_id is None:
            verdict = verdict.model_copy(update={"task_id": task_id})
        if verdict.created_at is None:
            verdict = verdict.model_copy(update={"created_at": _utc_now()})

        # Stamp the task with updated_at before the atomic write so the
        # timestamp is consistent with the verdict's created_at.
        task = task.model_copy(update={"updated_at": _utc_now()})

        # Persist both records atomically: the task transitions to
        # verdict_emitted and its verdict_id is linked to verdict.id in a
        # single locked write.  This closes the split-brain window where
        # save_verdict and save_task were called separately and a crash (or
        # concurrent reader) could observe a verdict with no corresponding
        # verdict_emitted task.
        task, verdict = self._store.save_task_and_verdict(task, verdict)
        review_verdict_ref = f"{self._store_path.name}#verdict={verdict.id}"
        if task.resolution_id:
            self._attach_acceptance_spine_review_verdict(
                resolution_id=task.resolution_id,
                review_verdict_ref=review_verdict_ref,
            )

        lane = self._sm.get_lane(verdict.lane_id)
        use_final_action = (
            require_final_action_approval
            if require_final_action_approval is not None
            else self._require_final_action_approval
        )
        result = adapt_review_verdict(
            verdict,
            lane=lane,
            require_final_action_approval=use_final_action,
        )

        # Persist the final-action hold if one was produced
        if result.final_action is not None:
            hold = self._final_action_store.create_hold(
                lane_id=result.final_action.lane_id,
                verdict_id=result.final_action.verdict_id,
                action=result.final_action.action,
                target_status=result.final_action.target_status,
                summary=result.final_action.summary,
            )
            self._attach_acceptance_spine_final_action_hold(
                review_verdict_ref=review_verdict_ref,
                hold_id=hold.id,
            )

        return result

    def _acceptance_spine_store(self) -> AcceptanceSpineStore | None:
        chat_db_path = self._store_path.parent / "chat.db"
        if not chat_db_path.exists():
            return None
        return AcceptanceSpineStore(chat_db_path)

    def _attach_acceptance_spine_review_verdict(
        self,
        *,
        resolution_id: str,
        review_verdict_ref: str,
    ) -> None:
        store = self._acceptance_spine_store()
        if store is None:
            return
        store.attach_review_verdict_for_resolution(
            resolution_id=resolution_id,
            review_verdict_ref=review_verdict_ref,
        )

    def _attach_acceptance_spine_final_action_hold(
        self,
        *,
        review_verdict_ref: str,
        hold_id: str,
    ) -> None:
        store = self._acceptance_spine_store()
        if store is None:
            return
        store.attach_final_action_for_review_verdict(
            review_verdict_ref=review_verdict_ref,
            final_action_ref=f"{self._final_actions_path.name}#hold={hold_id}",
            manual_gaps=["github_gate_unverified"],
            blocked_reason="final_action_pending",
        )

    # ------------------------------------------------------------------
    # Lineage queries
    # ------------------------------------------------------------------

    def verdict_lineage_for_lane(self, lane_id: str) -> list[dict[str, Any]]:
        """Return the full task→verdict lineage for *lane_id*.

        Each entry is a dict with ``task`` and ``verdict`` keys (verdict may be
        None if the task has not yet emitted one).
        """
        tasks = self._store.list_tasks_for_lane(lane_id)
        verdicts_by_id = {v.id: v for v in self._store.list_verdicts_for_lane(lane_id)}
        lineage: list[dict[str, Any]] = []
        for task in tasks:
            verdict = verdicts_by_id.get(task.verdict_id or "") if task.verdict_id else None
            lineage.append(
                {
                    "task": task.model_dump(mode="json"),
                    "verdict": verdict.model_dump(mode="json") if verdict else None,
                }
            )
        return lineage

    def has_verdict_lineage(self, lane_id: str) -> bool:
        """Return True if *lane_id* has at least one finalized verdict."""
        return any(v.status == "finalized" for v in self._store.list_verdicts_for_lane(lane_id))

    def _has_merge_verdict(self, lane_id: str) -> bool:
        """Return True if *lane_id* has at least one finalized MERGE verdict."""
        return any(
            v.status == "finalized" and v.decision == ReviewDecision.MERGE
            for v in self._store.list_verdicts_for_lane(lane_id)
        )

    # ------------------------------------------------------------------
    # Merge guards (evbundle_6259476d67dd414a8be293d1025ccb8c)
    # ------------------------------------------------------------------

    def _collect_graph_lane_ids(self, graph_id: str) -> list[str]:
        """Return all lane IDs belonging to *graph_id* including lineage descendants."""
        all_lanes = self._sm.get_lanes()
        graph_lane_ids: list[str] = [
            str(lane["feature_id"])
            for lane in all_lanes
            if isinstance(lane.get("feature_id"), str) and lane.get("graph_id") == graph_id
        ]
        seen: set[str] = set(graph_lane_ids)
        changed = True
        while changed:
            changed = False
            for lane in all_lanes:
                fid = lane.get("feature_id")
                src = lane.get("source_lane_id")
                if (
                    isinstance(fid, str)
                    and isinstance(src, str)
                    and src in seen
                    and fid not in seen
                ):
                    graph_lane_ids.append(fid)
                    seen.add(fid)
                    changed = True
        return graph_lane_ids

    def check_lineage_merge_completeness(self, graph_id: str) -> LineageMergeReport:
        """Inspect every lane lineage in *graph_id* and classify its merge state.

        Each lane lineage is classified as one of:

        ``merged_lineages``
            The lane reached a merged/done/completed status **or** has at
            least one finalized MERGE verdict in the review plane.

        ``terminated_without_merge``
            The lane reached a terminal failure state (``failed`` or
            ``exec_failed``) without a corresponding MERGE verdict.  This is
            the incomplete-termination signal captured by
            evidence bundle evbundle_6259476d67dd414a8be293d1025ccb8c.

        ``open_lineages``
            The lane is still in-flight (not yet in any terminal state).

        Returns a :class:`LineageMergeReport` with the classification results.
        """
        graph_lane_ids = self._collect_graph_lane_ids(graph_id)
        all_lanes = self._sm.get_lanes()
        lane_map: dict[str, dict[str, Any]] = {
            str(lane["feature_id"]): lane
            for lane in all_lanes
            if isinstance(lane.get("feature_id"), str)
        }

        report = LineageMergeReport(graph_id=graph_id)
        for lane_id in graph_lane_ids:
            lane = lane_map.get(lane_id)
            if lane is None:
                # Lane referenced in graph but not yet projected — still open.
                report.open_lineages.append(lane_id)
                continue

            status = str(lane.get("status", "pending"))
            if status in _MERGED_STATUSES or self._has_merge_verdict(lane_id):
                report.merged_lineages.append(lane_id)
            elif status in _FAILED_STATUSES:
                report.terminated_without_merge.append(lane_id)
            else:
                report.open_lineages.append(lane_id)

        return report

    def assert_termination_safe(self, lane_id: str, graph_id: str) -> None:
        """Raise :class:`IncompleteLineageTerminationError` if termination is unsafe.

        A termination is considered unsafe when the graph still has sibling
        lineages that are either:

        - Still open (in-flight) — terminating now would strand them.
        - Already terminated without a merge verdict — the graph has an
          existing incomplete-termination signal that must be acknowledged
          before another termination is allowed.

        This guard is called by :meth:`ingest_verdict` before a
        ``TERMINATE`` verdict is persisted, preventing the review plane from
        allowing termination in an incomplete state.

        Args:
            lane_id: The lane whose termination is being requested.
            graph_id: The graph the lane belongs to.

        Raises:
            IncompleteLineageTerminationError: When the termination is unsafe.
        """
        report = self.check_lineage_merge_completeness(graph_id)

        # Exclude the lane being terminated from the sibling checks — it is
        # expected to be in-flight at this point.
        open_siblings = [lid for lid in report.open_lineages if lid != lane_id]
        unmerged_siblings = [lid for lid in report.terminated_without_merge if lid != lane_id]

        if open_siblings or unmerged_siblings:
            raise IncompleteLineageTerminationError(
                lane_id,
                graph_id,
                open_lineages=open_siblings,
                unmerged_lineages=unmerged_siblings,
            )

    def record_incomplete_termination(
        self,
        lane_id: str,
        graph_id: str,
        *,
        reason: str = "terminated_without_merge",
    ) -> ReviewVerdict:
        """Persist an incomplete-termination signal for *lane_id*.

        Called when a lane reaches a terminal failure state without a merge
        verdict.  The signal is stored as a synthetic ``TERMINATE`` verdict
        with ``status="incomplete_termination"`` so that:

        - :meth:`check_lineage_merge_completeness` can distinguish lanes that
          have been explicitly acknowledged from those that silently failed.
        - :meth:`assemble_evidence_bundle` picks it up as a negative signal
          ref, giving the next planning cycle a concrete reference to the gap.

        The verdict is idempotent: if an incomplete-termination verdict already
        exists for *lane_id* it is returned as-is without creating a duplicate.

        Args:
            lane_id: The lane that terminated without a merge verdict.
            graph_id: The graph the lane belongs to.
            reason: Human-readable reason for the incomplete termination.

        Returns:
            The persisted :class:`ReviewVerdict` for the incomplete termination.
        """
        # Idempotency: return existing incomplete-termination verdict if present.
        existing = [
            v
            for v in self._store.list_verdicts_for_lane(lane_id)
            if v.status == "incomplete_termination"
        ]
        if existing:
            return existing[-1]

        verdict_id = _new_id("incomplete-term")
        verdict = ReviewVerdict(
            id=verdict_id,
            lane_id=lane_id,
            decision=ReviewDecision.TERMINATE,
            status="incomplete_termination",
            summary=(
                f"Lane {lane_id!r} in graph {graph_id!r} reached a terminal state "
                f"without a merge verdict. Reason: {reason}. "
                f"Evidence bundle reference: evbundle_6259476d67dd414a8be293d1025ccb8c."
            ),
            terminate_reason=reason,
            created_at=_utc_now(),
        )
        self._store.save_verdict(verdict)
        logger.warning(
            "review_plane: incomplete termination recorded for lane %s in graph %s "
            "(reason=%s, verdict_id=%s)",
            lane_id,
            graph_id,
            reason,
            verdict_id,
        )
        return verdict

    def aggregate_run_terminal_status(
        self,
        graph_id: str,
        *,
        lane_graph: LaneGraph | None = None,
        final_action_store: FinalActionGateStore | None = None,
        clarification_store: ClarificationStore | None = None,
    ) -> RunTerminalAggregation:
        """Compute the run-level terminal status for *graph_id*.

        Delegates to :class:`RunTerminalAggregator` — the authoritative
        aggregation implementation for the blueprint-anchored self-evolution
        spec (evidence bundle evbundle_e72fecb39ee8439c8338891e9f4fd373).

        Inputs evaluated:

        - **Authoritative LaneGraph** (``lane_graph``): when provided, the
          canonical set of lanes for the run is seeded from
          ``LaneGraph.lanes`` rather than inferred from the ``graph_id``
          field on each lane.  This prevents phantom lanes from keeping a
          run open indefinitely.
        - **Normalized lane execution states**: the current ``status`` field
          for each lane in the state machine.
        - **Verdict lineage**: whether each lane has at least one finalized
          MERGE verdict in the verdict store.
        - **Patch-forward lineage**: ``source_lane_id`` transitive closure so
          that every descendant created through requeue, rework, or
          patch-forward is included.
        - **Final-action holds**: pending holds from ``FinalActionGateStore``
          that block run completion even when all lane lineages are closed.
          Falls back to the controller's own store when *final_action_store*
          is not provided.
        - **Clarification objects**: open ``ClarificationObject`` records from
          ``ClarificationStore`` that represent blocked-for-input states.
          Falls back to the controller's own store when *clarification_store*
          is not provided.

        Terminal outcomes:

        ``merged``
            Every lane lineage is closed cleanly; no holds or clarifications
            pending.

        ``terminated``
            Every lane lineage is closed; at least one via fail/stop
            semantics; no holds or clarifications pending.

        ``blocked_for_input``
            All lane lineages are closed, but at least one pending
            final-action hold or open clarification object remains
            unresolved.

        ``in_progress``
            At least one lane lineage is still open (not yet in a terminal
            state).
        """
        effective_final_action_store = final_action_store or self._final_action_store
        effective_clarification_store = clarification_store or self._clarification_store

        aggregator = RunTerminalAggregator(
            sm=self._sm,
            verdict_store=self._store,
            final_action_store=effective_final_action_store,
            clarification_store=effective_clarification_store,
        )
        return aggregator.compute(graph_id, lane_graph=lane_graph)

    def verdict_lineage_for_run(self, graph_id: str) -> list[dict[str, Any]]:
        """Return the full task→verdict lineage for every lane in *graph_id*.

        Reads the lane file to discover which lanes belong to the run, then
        returns the same task→verdict structure as
        :meth:`verdict_lineage_for_lane` for each lane.

        Lanes that have no review task are omitted.  The result is ordered by
        lane appearance in the graph (original lanes first, then any
        patch-forward or requeue descendants discovered through
        ``source_lane_id`` lineage).
        """
        all_lanes = self._sm.get_lanes()
        # Seed with lanes whose graph_id matches.
        graph_lane_ids: list[str] = [
            str(lane["feature_id"])
            for lane in all_lanes
            if isinstance(lane.get("feature_id"), str) and lane.get("graph_id") == graph_id
        ]
        # Expand to include source_lane_id descendants.
        seen: set[str] = set(graph_lane_ids)
        changed = True
        while changed:
            changed = False
            for lane in all_lanes:
                fid = lane.get("feature_id")
                src = lane.get("source_lane_id")
                if (
                    isinstance(fid, str)
                    and isinstance(src, str)
                    and src in seen
                    and fid not in seen
                ):
                    graph_lane_ids.append(fid)
                    seen.add(fid)
                    changed = True

        lineage: list[dict[str, Any]] = []
        for lane_id in graph_lane_ids:
            lane_lineage = self.verdict_lineage_for_lane(lane_id)
            lineage.extend(lane_lineage)
        return lineage

    # ------------------------------------------------------------------
    # Evidence bundle assembly
    # ------------------------------------------------------------------

    def _evidence_bundle_assembler(self) -> ReviewEvidenceBundleAssembler:
        return ReviewEvidenceBundleAssembler(
            lanes_path=self._lanes_path,
            sm=self._sm,
            store=self._store,
            final_action_store=self._final_action_store,
            clarification_store=self._clarification_store,
            aggregate_run_terminal_status_fn=self.aggregate_run_terminal_status,
            verdict_lineage_for_lane_fn=self.verdict_lineage_for_lane,
            has_merge_verdict_fn=self._has_merge_verdict,
            record_incomplete_termination_fn=self.record_incomplete_termination,
        )

    def _collect_bundle_lane_ids(
        self,
        graph_id: str,
        lane_graph: LaneGraph | None,
        all_lanes: list[dict[str, Any]],
    ) -> list[str]:
        return self._evidence_bundle_assembler()._collect_bundle_lane_ids(
            graph_id,
            lane_graph,
            all_lanes,
        )

    @staticmethod
    def _append_unique_ref(refs: list[str], ref: str | None) -> None:
        ReviewEvidenceBundleAssembler._append_unique_ref(refs, ref)

    @staticmethod
    def _append_primary_ref(
        primary_refs: list[dict[str, Any]],
        seen: set[str],
        ref: dict[str, Any],
    ) -> None:
        ReviewEvidenceBundleAssembler._append_primary_ref(primary_refs, seen, ref)

    @staticmethod
    def _looks_like_artifact_ref(value: str) -> bool:
        return ReviewEvidenceBundleAssembler._looks_like_artifact_ref(value)

    def _collect_lane_artifact_refs(self, lane: dict[str, Any]) -> list[str]:
        return self._evidence_bundle_assembler()._collect_lane_artifact_refs(lane)

    def _resolve_bundle_ref_path(self, ref: str) -> Path | None:
        return self._evidence_bundle_assembler()._resolve_bundle_ref_path(ref)

    def _collect_gate_report_artifacts(self, report_ref: str) -> list[str]:
        return self._evidence_bundle_assembler()._collect_gate_report_artifacts(report_ref)

    def assemble_evidence_bundle(
        self,
        graph_id: str,
        *,
        lane_graph: LaneGraph | None = None,
        final_action_store: FinalActionGateStore | None = None,
        clarification_store: ClarificationStore | None = None,
        evidence_store: EvidenceBundleStore | None = None,
        selection_policy_id: str = "default-v1",
        selection_policy_version: str = "1",
    ) -> StructuredEvidenceBundle:
        return self._evidence_bundle_assembler().assemble_evidence_bundle(
            graph_id,
            lane_graph=lane_graph,
            final_action_store=final_action_store,
            clarification_store=clarification_store,
            evidence_store=evidence_store,
            selection_policy_id=selection_policy_id,
            selection_policy_version=selection_policy_version,
        )
