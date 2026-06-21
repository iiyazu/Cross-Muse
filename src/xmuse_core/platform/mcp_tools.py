from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from xmuse_core.platform.event_bus import EventBus
from xmuse_core.platform.projection.allowlist import (
    normalize_mutation_audit,
    stamp_mutation_audit,
)
from xmuse_core.platform.read_contracts import (
    build_blueprint_contract,
    build_evidence_refs,
    build_feature_plan_contract,
    build_graph_set_contract,
    build_graph_set_summary,
    build_health_contract,
    build_lane_contract,
    build_provider_inventory,
    build_review_contract,
    build_review_verdict,
    build_run_health_snapshot,
    build_takeover_context,
)
from xmuse_core.platform.state_machine import (
    InvalidTransitionError,
    LaneStateMachine,
)
from xmuse_core.platform.state_validation import StateValidationError
from xmuse_core.platform.takeover_actions import (
    apply_takeover_decision,
    normalize_takeover_guard,
    validate_takeover_guard,
)
from xmuse_core.structuring.models import ReviewGodTakeoverDecision

_MAX_EXECUTION_METADATA_ITEMS = 50
_MAX_EXECUTION_METADATA_ITEM_CHARS = 1000


def _query_terms(query: str) -> set[str]:
    return {t for t in re.findall(r"[a-zA-Z0-9_+-]+", query.lower()) if len(t) > 1}


def _text_for_search(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_text_for_search(v) for v in value.values())
    if isinstance(value, list):
        return " ".join(_text_for_search(v) for v in value)
    return str(value)


class McpToolHandler:
    def __init__(
        self,
        *,
        state_machine: LaneStateMachine,
        xmuse_root: Path,
        on_status_change=None,
    ) -> None:
        self._sm = state_machine
        self._root = xmuse_root
        self._on_status_change = on_status_change

    def call(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        method = getattr(self, f"_tool_{tool_name}", None)
        if method is None:
            return {"error": f"unknown tool: {tool_name}"}
        try:
            return method(arguments)
        except Exception as exc:
            return {"error": str(exc)}

    def _tool_get_lane(self, args: dict[str, Any]) -> dict[str, Any]:
        return self._sm.get_lane(args["lane_id"])

    def _tool_get_gate_report(self, args: dict[str, Any]) -> dict[str, Any]:
        lane_id = args["lane_id"]
        report_path = self._root / "logs" / "gates" / lane_id / "report.json"
        if not report_path.exists():
            return {"error": f"no gate report for {lane_id}"}
        return json.loads(report_path.read_text(encoding="utf-8"))

    def _tool_get_diff(self, args: dict[str, Any]) -> dict[str, Any]:
        lane = self._sm.get_lane(args["lane_id"])
        worktree = Path(lane.get("worktree", "."))
        if not worktree.exists():
            return {"error": f"worktree not found: {worktree}"}
        result = subprocess.run(
            ["git", "diff", "HEAD"],
            cwd=worktree, capture_output=True, text=True, timeout=10,
        )
        status = subprocess.run(
            ["git", "status", "--short", "--untracked-files=all"],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=10,
        )
        status_lines = [line for line in status.stdout.splitlines() if line]
        untracked_files = [
            line[3:]
            for line in status_lines
            if line.startswith("?? ") and len(line) > 3
        ]
        return {
            "diff": result.stdout,
            "returncode": result.returncode,
            "status_short": status.stdout,
            "status_returncode": status.returncode,
            "untracked_files": untracked_files,
            "has_untracked": bool(untracked_files),
        }

    def _tool_query_knowledge(self, args: dict[str, Any]) -> dict[str, Any]:
        query = args.get("query", "")
        top_k = args.get("top_k", 3)
        ek_path = self._root / "error_knowledge.json"
        if not ek_path.exists():
            return {"query": query, "matches": []}
        data = json.loads(ek_path.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        terms = _query_terms(query)
        scored = []
        for entry in entries:
            haystack = _text_for_search(entry).lower()
            score = sum(1 for t in terms if t in haystack)
            if score:
                scored.append({"score": score, "entry": entry})
        scored.sort(key=lambda x: -x["score"])
        return {"query": query, "matches": scored[:top_k]}

    def _tool_read_lane_contract(self, args: dict[str, Any]) -> dict[str, Any]:
        lane = self._sm.get_lane(args["lane_id"])
        return build_lane_contract(lane=lane, xmuse_root=self._root)

    def _tool_read_blueprint_contract(self, args: dict[str, Any]) -> dict[str, Any]:
        return build_blueprint_contract(
            xmuse_root=self._root,
            blueprint_ref=args.get("blueprint_ref"),
            resolution_id=args.get("resolution_id"),
        )

    def _tool_read_feature_plan_contract(self, args: dict[str, Any]) -> dict[str, Any]:
        return build_feature_plan_contract(
            feature_plan_id=args["feature_plan_id"],
            lanes_path=self._sm._path,
            xmuse_root=self._root,
        )

    def _tool_read_review_contract(self, args: dict[str, Any]) -> dict[str, Any]:
        return build_review_contract(lane_id=args["lane_id"], xmuse_root=self._root)

    def _tool_read_health_contract(self, args: dict[str, Any]) -> dict[str, Any]:
        del args
        return build_health_contract(lanes_path=self._sm._path, xmuse_root=self._root)

    def _tool_read_graph_set_contract(self, args: dict[str, Any]) -> dict[str, Any]:
        return build_graph_set_contract(
            graph_set_id=args["graph_set_id"],
            lanes_path=self._sm._path,
            xmuse_root=self._root,
        )

    def _tool_read_graph_set_summary(self, args: dict[str, Any]) -> dict[str, Any]:
        return build_graph_set_summary(
            graph_set_id=args["graph_set_id"],
            lanes_path=self._sm._path,
            xmuse_root=self._root,
        )

    def _tool_read_evidence_refs(self, args: dict[str, Any]) -> dict[str, Any]:
        lane = self._sm.get_lane(args["lane_id"])
        return build_evidence_refs(
            lane=lane,
            all_lanes=self._sm.get_lanes(),
            xmuse_root=self._root,
        )

    def _tool_read_review_verdict(self, args: dict[str, Any]) -> dict[str, Any]:
        return build_review_verdict(lane_id=args["lane_id"], xmuse_root=self._root)

    def _tool_read_takeover_context(self, args: dict[str, Any]) -> dict[str, Any]:
        lane = self._sm.get_lane(args["lane_id"])
        return build_takeover_context(
            lane=lane,
            all_lanes=self._sm.get_lanes(),
            xmuse_root=self._root,
        )

    def _tool_read_run_health(self, args: dict[str, Any]) -> dict[str, Any]:
        del args
        return build_run_health_snapshot(lanes_path=self._sm._path, xmuse_root=self._root)

    def _tool_read_provider_inventory(self, args: dict[str, Any]) -> dict[str, Any]:
        del args
        return build_provider_inventory()

    def _tool_apply_takeover_decision(self, args: dict[str, Any]) -> dict[str, Any]:
        decision_payload = args.get("decision")
        if not isinstance(decision_payload, dict):
            raise ValueError("apply_takeover_decision requires decision object")
        decision = ReviewGodTakeoverDecision.model_validate(decision_payload)
        audit = normalize_mutation_audit(args.get("audit"), tool_name="apply_takeover_decision")
        snapshot = self._sm._read()
        lane = _snapshot_lane(snapshot, decision.lane_id)
        guard = normalize_takeover_guard(args.get("guard"))
        _validate_takeover_guard(
            guard=guard,
            lane=lane,
            all_lanes=_snapshot_lanes(snapshot),
            lanes_path=self._sm._path,
            xmuse_root=self._root,
            projection_revision=_snapshot_projection_revision(snapshot),
        )
        bus = EventBus(audit_log_path=self._root / "audit_events.json")
        result = apply_takeover_decision(
            state_machine=self._sm,
            xmuse_root=self._root,
            event_bus=bus,
            decision=decision,
            audit=audit,
            created_at=args.get("created_at"),
            guard=guard,
        )
        if self._on_status_change:
            lane = self._sm.get_lane(decision.lane_id)
            self._on_status_change(decision.lane_id, str(lane.get("status") or "unknown"))
        return result

    def _tool_update_lane_status(self, args: dict[str, Any]) -> dict[str, Any]:
        lane_id = args["lane_id"]
        status = args["status"]
        lane = self._sm.get_lane(lane_id)
        audit = normalize_mutation_audit(args.get("audit"), tool_name="update_lane_status")
        guard = _normalize_status_guard(args.get("guard"))
        metadata = _normalize_review_status_metadata(
            lane=lane,
            status=status,
            metadata=_normalize_lane_update_metadata(args.get("metadata")),
        )
        metadata = stamp_mutation_audit(
            metadata or {},
            audit=audit,
            tool_name="update_lane_status",
        )
        try:
            lane = self._sm.transition_if_metadata(
                lane_id,
                status,
                expected_metadata={"status": guard["current_status"]},
                metadata=metadata,
            )
            if lane is None:
                raise ValueError(
                    "state guard mismatch for update_lane_status: "
                    f"expected status {guard['current_status']}"
                )
            if self._on_status_change:
                self._on_status_change(lane_id, status)
            return lane
        except (InvalidTransitionError, StateValidationError, KeyError) as exc:
            return {"error": str(exc)}


def _normalize_review_status_metadata(
    *,
    lane: dict[str, Any],
    status: str,
    metadata: Any,
) -> dict[str, Any] | None:
    if not isinstance(metadata, dict):
        metadata = {}
    else:
        metadata = dict(metadata)
    if status == "reviewed":
        summary = str(
            metadata.get("review_summary")
            or metadata.get("reason")
            or "review accepted"
        ).strip()
        metadata["review_decision"] = "merge"
        metadata["review_summary"] = summary

        history = lane.get("review_history")
        if not isinstance(history, list):
            history = []
        entry = {
            "decision": "merge",
            "summary": str(metadata["review_summary"]),
            "fallback": "mcp",
            "fallback_reason": "update_lane_status",
            "recorded_at": time.time(),
        }
        metadata["review_history"] = [*history, entry][-8:]
        return metadata

    if status != "rejected":
        return metadata or None

    summary = str(
        metadata.get("rework_context")
        or metadata.get("reason")
        or metadata.get("review_summary")
        or "review requested rework"
    ).strip()
    metadata["review_decision"] = "rework"
    metadata["review_summary"] = summary

    history = lane.get("review_history")
    if not isinstance(history, list):
        history = []
    entry = {
        "decision": "rework",
        "summary": str(metadata["review_summary"]),
        "fallback": "mcp",
        "fallback_reason": "update_lane_status",
        "recorded_at": time.time(),
    }
    metadata["review_history"] = [*history, entry][-8:]
    return metadata


def _normalize_status_guard(
    guard: Any,
    *,
    tool_name: str = "update_lane_status",
) -> dict[str, str]:
    if not isinstance(guard, dict):
        raise ValueError(f"{tool_name} requires guard.current_status")
    current_status = guard.get("current_status")
    if not isinstance(current_status, str) or not current_status.strip():
        raise ValueError(f"{tool_name} guard.current_status is required")
    return {"current_status": current_status.strip()}


def _validate_takeover_guard(
    *,
    guard: dict[str, Any],
    lane: dict[str, Any],
    all_lanes: list[dict[str, Any]],
    lanes_path: Path,
    xmuse_root: Path,
    projection_revision: int,
) -> None:
    validate_takeover_guard(
        guard=guard,
        lane=lane,
        all_lanes=all_lanes,
        lanes_path=lanes_path,
        xmuse_root=xmuse_root,
        projection_revision=projection_revision,
    )


def _snapshot_lanes(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    lanes = snapshot.get("lanes")
    if not isinstance(lanes, list):
        raise ValueError("feature_lanes.json lanes must be a list")
    return [lane for lane in lanes if isinstance(lane, dict)]


def _snapshot_lane(snapshot: dict[str, Any], lane_id: str) -> dict[str, Any]:
    for lane in _snapshot_lanes(snapshot):
        if lane.get("feature_id") == lane_id:
            return lane
    raise KeyError(f"lane not found: {lane_id}")


def _snapshot_projection_revision(snapshot: dict[str, Any]) -> int:
    revision = snapshot.get("projection_revision", 0)
    if not isinstance(revision, int) or isinstance(revision, bool):
        return 0
    return revision


def _normalize_lane_update_metadata(metadata: Any) -> dict[str, Any]:
    if not isinstance(metadata, dict):
        return {}
    normalized = dict(metadata)
    for key in ("changed_files", "evidence_refs", "tests_run"):
        if key in normalized:
            normalized[key] = _normalize_execution_string_list_metadata(
                normalized[key],
                field_name=key,
            )
    safe_fields = {
        "changed_files",
        "evidence_refs",
        "failure_reason",
        "final_action",
        "final_action_hold_id",
        "gate_passed",
        "merge_failure_detail",
        "merge_failure_reason",
        "merge_sha",
        "patch_lane_id",
        "proof_boundary",
        "reason",
        "review_runtime",
        "review_decision",
        "review_evidence_refs",
        "review_history",
        "review_summary",
        "rework_context",
        "tests_run",
    }
    unexpected = sorted(key for key in normalized if key not in safe_fields)
    if unexpected:
        joined = ", ".join(unexpected)
        raise ValueError(f"unsafe metadata field(s) for update_lane_status: {joined}")
    return normalized


def _normalize_execution_string_list_metadata(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"update_lane_status metadata.{field_name} must be a string list")
    if len(value) > _MAX_EXECUTION_METADATA_ITEMS:
        raise ValueError(
            f"update_lane_status metadata.{field_name} exceeds "
            f"{_MAX_EXECUTION_METADATA_ITEMS} items"
        )
    normalized: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"update_lane_status metadata.{field_name} must be a string list")
        if len(item) > _MAX_EXECUTION_METADATA_ITEM_CHARS:
            raise ValueError(
                f"update_lane_status metadata.{field_name} item exceeds "
                f"{_MAX_EXECUTION_METADATA_ITEM_CHARS} characters"
            )
        normalized.append(item)
    return normalized
