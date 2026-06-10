"""Evidence bundle assembly for the review plane."""
from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.structuring.models import (
    LaneGraph,
    ReviewVerdict,
    RunTerminalAggregation,
    RunTerminalStatus,
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


@dataclass
class ReviewEvidenceBundleAssembler:
    """Assembles structured evidence bundles from review-plane dependencies."""

    lanes_path: Path
    sm: LaneStateMachine
    store: VerdictStore
    final_action_store: FinalActionGateStore
    clarification_store: ClarificationStore | None
    aggregate_run_terminal_status_fn: Callable[..., RunTerminalAggregation]
    verdict_lineage_for_lane_fn: Callable[[str], list[dict[str, Any]]]
    has_merge_verdict_fn: Callable[[str], bool]
    record_incomplete_termination_fn: Callable[..., ReviewVerdict]

    def __post_init__(self) -> None:
        self._lanes_path = Path(self.lanes_path)
        self._sm = self.sm
        self._store = self.store
        self._final_action_store = self.final_action_store
        self._clarification_store = self.clarification_store

    def aggregate_run_terminal_status(self, graph_id: str, **kwargs: Any) -> RunTerminalAggregation:
        return self.aggregate_run_terminal_status_fn(graph_id, **kwargs)

    def verdict_lineage_for_lane(self, lane_id: str) -> list[dict[str, Any]]:
        return self.verdict_lineage_for_lane_fn(lane_id)

    def _has_merge_verdict(self, lane_id: str) -> bool:
        return self.has_merge_verdict_fn(lane_id)

    def record_incomplete_termination(
        self,
        lane_id: str,
        graph_id: str,
        **kwargs: Any,
    ) -> ReviewVerdict:
        return self.record_incomplete_termination_fn(lane_id, graph_id, **kwargs)

    def _collect_bundle_lane_ids(
        self,
        graph_id: str,
        lane_graph: LaneGraph | None,
        all_lanes: list[dict[str, Any]],
    ) -> list[str]:
        """Collect run lane IDs using the same authority rules as aggregation."""
        if lane_graph is not None:
            seed_ids = [node.feature_id for node in lane_graph.lanes]
        else:
            seed_ids = [
                str(lane["feature_id"])
                for lane in all_lanes
                if isinstance(lane.get("feature_id"), str) and lane.get("graph_id") == graph_id
            ]

        collected: list[str] = []
        seen: set[str] = set()
        for lane_id in seed_ids:
            if lane_id not in seen:
                collected.append(lane_id)
                seen.add(lane_id)

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
                    collected.append(fid)
                    seen.add(fid)
                    changed = True
        return collected

    @staticmethod
    def _append_unique_ref(refs: list[str], ref: str | None) -> None:
        """Append a non-empty string ref once, preserving first-seen order."""
        if ref and ref not in refs:
            refs.append(ref)

    @staticmethod
    def _append_primary_ref(
        primary_refs: list[dict[str, Any]],
        seen: set[str],
        ref: dict[str, Any],
    ) -> None:
        """Append a primary ref once using its normalized JSON shape."""
        key = json.dumps(ref, sort_keys=True, default=str)
        if key not in seen:
            primary_refs.append(ref)
            seen.add(key)

    @staticmethod
    def _looks_like_artifact_ref(value: str) -> bool:
        """Return True for strings that look like artifact paths or refs."""
        if not value or "\n" in value:
            return False
        suffixes = (
            ".json",
            ".md",
            ".txt",
            ".stdout",
            ".stderr",
            ".log",
            ".patch",
            ".diff",
        )
        prefixes = ("logs/", "xmuse/", "artifacts/", "reports/")
        return value.startswith(prefixes) or value.endswith(suffixes) or "/" in value

    def _collect_lane_artifact_refs(self, lane: dict[str, Any]) -> list[str]:
        """Collect explicit artifact refs from lane metadata."""
        refs: list[str] = []

        def visit(value: Any) -> None:
            if isinstance(value, str):
                if self._looks_like_artifact_ref(value):
                    self._append_unique_ref(refs, value)
            elif isinstance(value, dict):
                for nested in value.values():
                    visit(nested)
            elif isinstance(value, (list, tuple, set)):
                for nested in value:
                    visit(nested)

        for key in (
            "artifacts",
            "artifact_refs",
            "output_artifacts",
            "result_artifacts",
        ):
            if key in lane:
                visit(lane.get(key))

        for key, value in lane.items():
            if not isinstance(value, str):
                continue
            if key in {"worktree", "prompt", "failure_reason", "review_summary"}:
                continue
            if (
                key.endswith("_artifact")
                or key.endswith("_artifact_ref")
                or key.endswith("_artifact_path")
                or key in {"artifact_path", "result_path", "patch_path", "diff_path"}
            ) and self._looks_like_artifact_ref(value):
                self._append_unique_ref(refs, value)
        return refs

    def _resolve_bundle_ref_path(self, ref: str) -> Path | None:
        path = Path(ref)
        if path.is_absolute():
            return path if path.exists() else None
        candidate = self._lanes_path.parent / path
        return candidate if candidate.exists() else None

    def _collect_gate_report_artifacts(self, report_ref: str) -> list[str]:
        """Collect stdout/stderr artifacts referenced by a gate report."""
        path = self._resolve_bundle_ref_path(report_ref)
        if path is None:
            return []
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(payload, dict):
            return []

        refs: list[str] = []
        artifact_dir = payload.get("artifact_dir")
        if isinstance(artifact_dir, str) and self._looks_like_artifact_ref(artifact_dir):
            self._append_unique_ref(refs, artifact_dir)
        for result in payload.get("command_results", []):
            if not isinstance(result, dict):
                continue
            for key in ("stdout_path", "stderr_path"):
                value = result.get(key)
                if isinstance(value, str) and self._looks_like_artifact_ref(value):
                    self._append_unique_ref(refs, value)
        return refs

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
        """Assemble a StructuredEvidenceBundle from a terminal run.

        Collects the run terminal status, verdict lineage, gate report refs,
        patch-forward / requeue lineage refs, and negative signal refs.
        Every cited item is also recorded in ``primary_refs`` so the bundle
        satisfies the evidence curation contract from the spec.

        The bundle is persisted in *evidence_store* when provided.

        Args:
            graph_id: The lane graph ID of the terminal run.
            lane_graph: Optional authoritative :class:`LaneGraph`.  When
                provided its ``lanes`` list seeds the lane-ID collection so
                that the aggregation is not dependent on the ``graph_id``
                field being correctly stamped on every lane.
            final_action_store: Optional store used to check pending holds.
                Falls back to the controller's own store when not provided.
            clarification_store: Optional store used to check open
                clarification objects.  Falls back to the controller's own
                store when not provided.
            evidence_store: Optional store to persist the assembled bundle.
            selection_policy_id: Identifies the evidence selection policy.
            selection_policy_version: Version of the selection policy.

        Returns:
            The assembled :class:`StructuredEvidenceBundle`.
        """
        effective_final_action_store = final_action_store or self._final_action_store
        effective_clarification_store = clarification_store or self._clarification_store
        aggregation = self.aggregate_run_terminal_status(
            graph_id,
            lane_graph=lane_graph,
            final_action_store=effective_final_action_store,
            clarification_store=effective_clarification_store,
        )
        if aggregation.status is RunTerminalStatus.IN_PROGRESS:
            raise RuntimeError(f"source run is not terminal: {aggregation.status.value}")

        all_lanes = self._sm.get_lanes()
        graph_lane_ids = self._collect_bundle_lane_ids(graph_id, lane_graph, all_lanes)
        graph_lane_id_set = set(graph_lane_ids)
        lane_map: dict[str, dict[str, Any]] = {
            str(lane["feature_id"]): lane
            for lane in all_lanes
            if isinstance(lane.get("feature_id"), str)
        }

        # Collect verdict refs and gate report refs from the lineage.
        verdict_refs: list[str] = []
        gate_report_refs: list[str] = []
        lineage_refs: list[str] = []
        artifact_refs: list[str] = []
        signal_refs: list[str] = []
        primary_refs: list[dict[str, Any]] = []
        primary_seen: set[str] = set()
        verdict_decision_counts: dict[str, int] = {}
        processed_verdict_ids: set[str] = set()

        self._append_primary_ref(
            primary_refs,
            primary_seen,
            {
                "type": "run_terminal_aggregation",
                "ref": f"run_terminal_aggregation:{graph_id}",
                "lane_id": None,
                "graph_id": graph_id,
                "status": aggregation.status.value,
                "open_lane_lineages": aggregation.open_lane_lineages,
                "failed_lineages": aggregation.failed_lineages,
                "open_final_action_holds": aggregation.open_final_action_holds,
                "open_clarification_ids": aggregation.open_clarification_ids,
                "basis": aggregation.basis,
            },
        )
        self._append_primary_ref(
            primary_refs,
            primary_seen,
            {
                "type": "selection_policy",
                "lane_id": None,
                "graph_id": graph_id,
                "policy_id": selection_policy_id,
                "policy_version": selection_policy_version,
                "curation_contract": (
                    "cluster_by_evidence_class; summarize_counts_and_previews; "
                    "retain_full_primary_refs_for_all_cited_or_summarized_items"
                ),
            },
        )

        # Full primary lane references support the curation contract: the
        # summary can remain compact while dashboards and reviewers can still
        # reconstruct which lane states contributed to the bundle.
        for lane_id in graph_lane_ids:
            lane = lane_map.get(lane_id)
            if lane is None:
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "lane_status",
                        "lane_id": lane_id,
                        "graph_id": graph_id,
                        "status": "missing",
                    },
                )
                continue

            self._append_primary_ref(
                primary_refs,
                primary_seen,
                {
                    "type": "lane_status",
                    "lane_id": lane_id,
                    "graph_id": lane.get("graph_id") or graph_id,
                    "resolution_id": lane.get("resolution_id"),
                    "status": str(lane.get("status", "")),
                    "source_lane_id": lane.get("source_lane_id"),
                    "failure_reason": lane.get("failure_reason"),
                },
            )

            for artifact_ref in self._collect_lane_artifact_refs(lane):
                self._append_unique_ref(artifact_refs, artifact_ref)
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "artifact",
                        "lane_id": lane_id,
                        "graph_id": lane.get("graph_id") or graph_id,
                        "ref": artifact_ref,
                        "source": "lane_metadata",
                    },
                )

            for key in ("gate_report_ref", "gate_report_path", "gate_report"):
                value = lane.get(key)
                if not isinstance(value, str) or not value:
                    continue
                self._append_unique_ref(gate_report_refs, value)
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "gate_report",
                        "lane_id": lane_id,
                        "graph_id": lane.get("graph_id") or graph_id,
                        "ref": value,
                        "source": "lane_metadata",
                    },
                )
                for artifact_ref in self._collect_gate_report_artifacts(value):
                    self._append_unique_ref(artifact_refs, artifact_ref)
                    self._append_primary_ref(
                        primary_refs,
                        primary_seen,
                        {
                            "type": "artifact",
                            "lane_id": lane_id,
                            "graph_id": lane.get("graph_id") or graph_id,
                            "ref": artifact_ref,
                            "source": "gate_report",
                            "gate_report_ref": value,
                        },
                    )

        lineage: list[dict[str, Any]] = []
        for lane_id in graph_lane_ids:
            lineage.extend(self.verdict_lineage_for_lane(lane_id))

        for entry in lineage:
            task = entry.get("task")
            verdict = entry.get("verdict")
            if task:
                lane_id = str(task.get("lane_id", ""))
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "review_task",
                        "id": task["task_id"],
                        "lane_id": lane_id,
                        "graph_id": task.get("graph_id") or graph_id,
                        "resolution_id": task.get("resolution_id"),
                        "status": task.get("status"),
                        "verdict_id": task.get("verdict_id"),
                        "gate_report_ref": task.get("gate_report_ref"),
                    },
                )
                if task.get("gate_report_ref"):
                    gate_report_ref = str(task["gate_report_ref"])
                    self._append_unique_ref(gate_report_refs, gate_report_ref)
                    self._append_primary_ref(
                        primary_refs,
                        primary_seen,
                        {
                            "type": "gate_report",
                            "lane_id": lane_id,
                            "graph_id": task.get("graph_id") or graph_id,
                            "ref": gate_report_ref,
                            "task_id": task.get("task_id"),
                        },
                    )
                    for artifact_ref in self._collect_gate_report_artifacts(gate_report_ref):
                        self._append_unique_ref(artifact_refs, artifact_ref)
                        self._append_primary_ref(
                            primary_refs,
                            primary_seen,
                            {
                                "type": "artifact",
                                "lane_id": lane_id,
                                "graph_id": task.get("graph_id") or graph_id,
                                "ref": artifact_ref,
                                "source": "gate_report",
                                "gate_report_ref": gate_report_ref,
                            },
                        )
            if verdict:
                verdict_id = str(verdict["id"])
                decision = str(verdict["decision"])
                self._append_unique_ref(verdict_refs, verdict_id)
                processed_verdict_ids.add(verdict_id)
                verdict_decision_counts[decision] = verdict_decision_counts.get(decision, 0) + 1
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "review_verdict",
                        "ref": verdict_id,
                        "id": verdict_id,
                        "lane_id": verdict["lane_id"],
                        "graph_id": graph_id,
                        "decision": decision,
                        "status": verdict.get("status"),
                        "summary": verdict["summary"],
                        "task_id": verdict.get("task_id"),
                        "evidence_refs": verdict.get("evidence_refs", []),
                    },
                )
                for evidence_ref in verdict.get("evidence_refs", []) or []:
                    if isinstance(evidence_ref, str) and self._looks_like_artifact_ref(
                        evidence_ref
                    ):
                        self._append_unique_ref(artifact_refs, evidence_ref)
                        self._append_primary_ref(
                            primary_refs,
                            primary_seen,
                            {
                                "type": "artifact",
                                "lane_id": verdict["lane_id"],
                                "graph_id": graph_id,
                                "ref": evidence_ref,
                                "source": "review_verdict",
                                "verdict_id": verdict_id,
                            },
                        )

        # Include finalized verdicts that exist in the store even if the
        # corresponding ReviewTask lineage is unavailable.  Normal task→verdict
        # lineage remains the preferred path, but preserving orphan verdicts
        # keeps the bundle audit-complete for manually repaired stores.
        for lane_id in graph_lane_ids:
            for verdict in self._store.list_verdicts_for_lane(lane_id):
                if verdict.id in processed_verdict_ids:
                    continue
                verdict_id = verdict.id
                decision = str(verdict.decision)
                self._append_unique_ref(verdict_refs, verdict_id)
                processed_verdict_ids.add(verdict_id)
                verdict_decision_counts[decision] = verdict_decision_counts.get(decision, 0) + 1
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "review_verdict",
                        "ref": verdict_id,
                        "id": verdict_id,
                        "lane_id": verdict.lane_id,
                        "graph_id": graph_id,
                        "decision": decision,
                        "status": verdict.status,
                        "summary": verdict.summary,
                        "task_id": verdict.task_id,
                        "evidence_refs": verdict.evidence_refs,
                    },
                )
                for evidence_ref in verdict.evidence_refs:
                    if isinstance(evidence_ref, str) and self._looks_like_artifact_ref(
                        evidence_ref
                    ):
                        self._append_unique_ref(artifact_refs, evidence_ref)
                        self._append_primary_ref(
                            primary_refs,
                            primary_seen,
                            {
                                "type": "artifact",
                                "lane_id": verdict.lane_id,
                                "graph_id": graph_id,
                                "ref": evidence_ref,
                                "source": "review_verdict",
                                "verdict_id": verdict_id,
                            },
                        )

        # Collect lineage refs (patch-forward / requeue descendants).
        for lane in all_lanes:
            fid = lane.get("feature_id")
            src = lane.get("source_lane_id")
            if (
                isinstance(fid, str)
                and isinstance(src, str)
                and fid in graph_lane_id_set
                and src in graph_lane_id_set
            ):
                ref = f"lane:{fid}:source:{src}"
                self._append_unique_ref(lineage_refs, ref)
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "lane_lineage",
                        "ref": ref,
                        "lane_id": fid,
                        "graph_id": lane.get("graph_id") or graph_id,
                        "source_lane_id": src,
                        "status": str(lane.get("status", "")),
                        "failure_reason": lane.get("failure_reason"),
                    },
                )

        # Collect negative signal refs for failed lineages.
        # For each failed lineage that never received a merge verdict, record
        # an incomplete-termination signal (evbundle_6259476d67dd414a8be293d1025ccb8c)
        # so the next planning cycle has a concrete reference to the gap.
        for lane_id in aggregation.failed_lineages:
            lane = lane_map.get(lane_id)
            if lane:
                failure_reason = lane.get("failure_reason") or "unknown"
                ref = f"negative:lane:{lane_id}:{failure_reason}"
                self._append_unique_ref(signal_refs, ref)
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "negative_signal",
                        "ref": ref,
                        "lane_id": lane_id,
                        "graph_id": lane.get("graph_id") or graph_id,
                        "failure_reason": failure_reason,
                        "status": str(lane.get("status", "")),
                    },
                )

                # Merge guard: persist an incomplete-termination verdict for
                # any failed lineage that never received a merge verdict.
                # This is idempotent — duplicate calls return the existing verdict.
                if not self._has_merge_verdict(lane_id):
                    try:
                        incomplete_verdict = self.record_incomplete_termination(
                            lane_id,
                            graph_id,
                            reason=failure_reason,
                        )
                        if incomplete_verdict.id not in processed_verdict_ids:
                            verdict_id = incomplete_verdict.id
                            decision = str(incomplete_verdict.decision)
                            self._append_unique_ref(verdict_refs, verdict_id)
                            processed_verdict_ids.add(verdict_id)
                            verdict_decision_counts[decision] = (
                                verdict_decision_counts.get(decision, 0) + 1
                            )
                            self._append_primary_ref(
                                primary_refs,
                                primary_seen,
                                {
                                    "type": "review_verdict",
                                    "ref": verdict_id,
                                    "id": verdict_id,
                                    "lane_id": incomplete_verdict.lane_id,
                                    "graph_id": graph_id,
                                    "decision": decision,
                                    "status": incomplete_verdict.status,
                                    "summary": incomplete_verdict.summary,
                                    "task_id": incomplete_verdict.task_id,
                                    "evidence_refs": incomplete_verdict.evidence_refs,
                                },
                            )
                        incomplete_ref = (
                            f"incomplete_termination:lane:{lane_id}:{incomplete_verdict.id}"
                        )
                        self._append_unique_ref(signal_refs, incomplete_ref)
                        self._append_primary_ref(
                            primary_refs,
                            primary_seen,
                            {
                                "type": "incomplete_termination",
                                "ref": incomplete_ref,
                                "lane_id": lane_id,
                                "graph_id": lane.get("graph_id") or graph_id,
                                "verdict_id": incomplete_verdict.id,
                                "failure_reason": failure_reason,
                                "evidence_bundle_ref": "evbundle_6259476d67dd414a8be293d1025ccb8c",
                            },
                        )
                    except Exception:
                        logger.warning(
                            "review_plane: failed to record incomplete termination "
                            "for lane %s in graph %s",
                            lane_id,
                            graph_id,
                        )

        if effective_final_action_store is not None and aggregation.open_final_action_holds:
            hold_ids = set(aggregation.open_final_action_holds)
            for hold in effective_final_action_store.list_actions():
                if hold.id not in hold_ids:
                    continue
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "final_action_hold",
                        "id": hold.id,
                        "lane_id": hold.lane_id,
                        "graph_id": graph_id,
                        "verdict_id": hold.verdict_id,
                        "action": hold.action,
                        "target_status": hold.target_status,
                        "status": hold.status,
                        "summary": hold.summary,
                    },
                )

        if effective_clarification_store is not None and aggregation.open_clarification_ids:
            clarification_ids = set(aggregation.open_clarification_ids)
            for clarification in effective_clarification_store.list_all():
                if clarification.clarification_id not in clarification_ids:
                    continue
                self._append_primary_ref(
                    primary_refs,
                    primary_seen,
                    {
                        "type": "clarification",
                        "id": clarification.clarification_id,
                        "lane_id": clarification.lane_id,
                        "graph_id": clarification.graph_id or graph_id,
                        "resolution_id": clarification.resolution_id,
                        "status": clarification.status,
                        "question": clarification.question,
                        "context": clarification.context,
                    },
                )

        # Derive source_resolution_id from the first graph lane that has one.
        source_resolution_id: str | None = lane_graph.resolution_id if lane_graph else None
        for lane in all_lanes:
            if (
                not source_resolution_id
                and lane.get("feature_id") in graph_lane_id_set
                and lane.get("resolution_id")
            ):
                source_resolution_id = str(lane["resolution_id"])
                break

        # Build a curated summary.  The summary is intentionally clustered by
        # evidence class for planner efficiency; primary_refs retains the full
        # lane-scoped source references for every cited class.
        total = len(graph_lane_ids)
        status_value = aggregation.status.value
        decision_summary = (
            ", ".join(
                f"{decision}={count}" for decision, count in sorted(verdict_decision_counts.items())
            )
            or "none"
        )
        failed_preview = ", ".join(aggregation.failed_lineages[:5]) or "none"
        if len(aggregation.failed_lineages) > 5:
            failed_preview += f", +{len(aggregation.failed_lineages) - 5} more"
        open_preview = ", ".join(aggregation.open_lane_lineages[:5]) or "none"
        if len(aggregation.open_lane_lineages) > 5:
            open_preview += f", +{len(aggregation.open_lane_lineages) - 5} more"
        summary = (
            f"Run {graph_id} reached terminal status '{status_value}'. "
            f"Total lane lineages: {total}. "
            f"Open: {len(aggregation.open_lane_lineages)}. "
            f"Failed: {len(aggregation.failed_lineages)}. "
            f"Open holds: {len(aggregation.open_final_action_holds)}. "
            f"Open clarifications: {len(aggregation.open_clarification_ids)}. "
            f"Verdicts: {len(verdict_refs)}. "
            f"Gate reports: {len(gate_report_refs)}. "
            f"Artifacts: {len(artifact_refs)}. "
            f"Signals: {len(signal_refs)}. "
            f"Verdict decisions: {decision_summary}. "
            f"Failed lineages: {failed_preview}. "
            f"Open lineages: {open_preview}."
        )

        bundle = StructuredEvidenceBundle(
            bundle_id=_new_id("evbundle"),
            source_run_id=graph_id,
            source_resolution_id=source_resolution_id,
            selection_policy_id=selection_policy_id,
            selection_policy_version=selection_policy_version,
            summary=summary,
            run_terminal_status=aggregation.status,
            verdict_refs=verdict_refs,
            gate_report_refs=gate_report_refs,
            lineage_refs=lineage_refs,
            artifact_refs=artifact_refs,
            signal_refs=signal_refs,
            primary_refs=primary_refs,
            created_at=_utc_now(),
        )

        if evidence_store is not None:
            evidence_store.save(bundle)

        return bundle
