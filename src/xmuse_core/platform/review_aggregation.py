from __future__ import annotations

from typing import Any

from xmuse_core.platform.final_action_gate import FinalActionGateStore
from xmuse_core.platform.state_machine import LaneStateMachine
from xmuse_core.structuring.models import (
    LaneGraph,
    ReviewDecision,
    RunTerminalAggregation,
    RunTerminalStatus,
)
from xmuse_core.structuring.verdict_store import ClarificationStore, VerdictStore

_MERGED_STATUSES: frozenset[str] = frozenset({"merged", "done", "completed"})
_FAILED_STATUSES: frozenset[str] = frozenset({"failed", "exec_failed"})


class RunTerminalAggregator:
    """Computes run-level terminal outcomes from all available evidence sources."""

    def __init__(
        self,
        *,
        sm: LaneStateMachine,
        verdict_store: VerdictStore,
        final_action_store: FinalActionGateStore | None = None,
        clarification_store: ClarificationStore | None = None,
    ) -> None:
        self._sm = sm
        self._verdict_store = verdict_store
        self._final_action_store = final_action_store
        self._clarification_store = clarification_store

    def compute(
        self,
        graph_id: str,
        *,
        lane_graph: LaneGraph | None = None,
    ) -> RunTerminalAggregation:
        """Compute the run-level terminal status for *graph_id*."""
        all_lanes = self._sm.get_lanes()
        lane_map: dict[str, dict[str, Any]] = {
            str(lane["feature_id"]): lane
            for lane in all_lanes
            if isinstance(lane.get("feature_id"), str)
        }

        graph_lane_ids = self._collect_lane_ids(graph_id, lane_graph, all_lanes)
        lane_id_set: set[str] = set(graph_lane_ids)
        merged_lineages, failed_lineages, open_lineages = self._classify_lineages(
            graph_lane_ids, lane_map
        )
        open_holds = self._collect_open_holds(lane_id_set)
        open_clarification_ids = self._collect_open_clarifications(lane_id_set)
        computed_status = self._compute_status(
            open_lineages=open_lineages,
            open_holds=open_holds,
            open_clarification_ids=open_clarification_ids,
            failed_lineages=failed_lineages,
        )

        basis_parts = [
            f"graph_id={graph_id}",
            f"total_lane_lineages={len(graph_lane_ids)}",
            f"merged={len(merged_lineages)}",
            f"open={len(open_lineages)}",
            f"failed={len(failed_lineages)}",
            f"open_holds={len(open_holds)}",
            f"open_clarifications={len(open_clarification_ids)}",
        ]
        if lane_graph is not None:
            basis_parts.append(f"authoritative_graph={lane_graph.id}")

        return RunTerminalAggregation(
            graph_id=graph_id,
            status=computed_status,
            open_lane_lineages=open_lineages,
            failed_lineages=failed_lineages,
            open_final_action_holds=open_holds,
            open_clarification_ids=open_clarification_ids,
            basis="; ".join(basis_parts),
        )

    def _collect_lane_ids(
        self,
        graph_id: str,
        lane_graph: LaneGraph | None,
        all_lanes: list[dict[str, Any]],
    ) -> list[str]:
        if lane_graph is not None:
            seed_ids: list[str] = [node.feature_id for node in lane_graph.lanes]
        else:
            seed_ids = [
                str(lane["feature_id"])
                for lane in all_lanes
                if isinstance(lane.get("feature_id"), str) and lane.get("graph_id") == graph_id
            ]

        collected: list[str] = list(seed_ids)
        seen: set[str] = set(collected)
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

    def _classify_lineages(
        self,
        lane_ids: list[str],
        lane_map: dict[str, dict[str, Any]],
    ) -> tuple[list[str], list[str], list[str]]:
        merged: list[str] = []
        failed: list[str] = []
        open_: list[str] = []

        for lane_id in lane_ids:
            lane = lane_map.get(lane_id)
            if lane is None:
                open_.append(lane_id)
                continue

            status = str(lane.get("status", "pending"))
            has_merge_verdict = self._has_merge_verdict(lane_id)

            if status in _MERGED_STATUSES or has_merge_verdict:
                merged.append(lane_id)
            elif status in _FAILED_STATUSES:
                failed.append(lane_id)
            else:
                open_.append(lane_id)

        return merged, failed, open_

    def _has_merge_verdict(self, lane_id: str) -> bool:
        return any(
            v.status == "finalized" and v.decision == ReviewDecision.MERGE
            for v in self._verdict_store.list_verdicts_for_lane(lane_id)
        )

    def _collect_open_holds(self, lane_id_set: set[str]) -> list[str]:
        if self._final_action_store is None:
            return []
        return [
            hold.id
            for hold in self._final_action_store.list_actions()
            if hold.lane_id in lane_id_set and hold.status == "pending"
        ]

    def _collect_open_clarifications(self, lane_id_set: set[str]) -> list[str]:
        if self._clarification_store is None:
            return []
        return [
            c.clarification_id
            for c in self._clarification_store.list_open_for_lane_set(lane_id_set)
        ]

    @staticmethod
    def _compute_status(
        *,
        open_lineages: list[str],
        open_holds: list[str],
        open_clarification_ids: list[str],
        failed_lineages: list[str],
    ) -> RunTerminalStatus:
        if open_lineages:
            return RunTerminalStatus.IN_PROGRESS
        if open_holds or open_clarification_ids:
            return RunTerminalStatus.BLOCKED_FOR_INPUT
        if failed_lineages:
            return RunTerminalStatus.TERMINATED
        return RunTerminalStatus.MERGED
