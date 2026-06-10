from __future__ import annotations

import copy
import json
import logging
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.observability import (
    current_observability_context,
    log_event,
    observability_context,
    timed_core_operation,
)
from xmuse_core.platform.projection.syncer import (
    LaneProjectionSyncer,
    ProjectionWriteSkipped,
    strip_runtime_telemetry,
)
from xmuse_core.platform.state_validation import (
    StateTransition,
    StateTransitionValidator,
    StateValidationError,
)

MAX_RETRIES = 2
logger = logging.getLogger(__name__)
RUNTIME_TELEMETRY_FIELDS = frozenset(
    {
        "recovery_events",
        "last_recovery_event",
        "failure_error",
    }
)

VALID_TRANSITIONS: dict[str, set[str]] = {
    "pending": {"dispatched"},
    "dispatched": {"executed", "exec_failed"},
    "executed": {"gated", "gate_failed"},
    "gated": {"reviewed", "rejected", "gate_failed"},
    "reviewed": {"merged", "failed", "awaiting_final_action", "reworking"},
    "awaiting_final_action": {"merged", "failed"},
    "rejected": {"reworking", "failed"},
    "reworking": {"dispatched"},
    "exec_failed": {"failed", "reworking"},
    "gate_failed": {"failed", "reworking", "gated"},
}


class InvalidTransitionError(ValueError):
    pass


LaneMutationGuard = Callable[[dict[str, Any], dict[str, Any]], None]


def stage0_projection_syncer(path: Path | str) -> LaneProjectionSyncer:
    """Return the state-machine guarded Stage 0 projection writer."""

    return LaneProjectionSyncer(
        Path(path),
        validator=StateTransitionValidator(VALID_TRANSITIONS),
    )


class LaneStateMachine:
    def __init__(
        self,
        lanes_path: Path,
        *,
        history_path: Path | str | None = None,
    ) -> None:
        self._path = lanes_path
        self._history_path = Path(history_path) if history_path is not None else None
        self._validator = StateTransitionValidator(VALID_TRANSITIONS)
        self._projection = LaneProjectionSyncer(self._path, validator=self._validator)

    def _read(self) -> dict[str, Any]:
        return self._projection.read()

    def _write(self, data: dict[str, Any]) -> None:
        self._projection.update(lambda _data: data)

    def get_lane(self, lane_id: str) -> dict[str, Any]:
        for lane in self._read().get("lanes", []):
            if lane.get("feature_id") == lane_id:
                return lane
        raise KeyError(f"lane not found: {lane_id}")

    def get_lanes(self, status: str | None = None) -> list[dict[str, Any]]:
        lanes = self._read().get("lanes", [])
        if status is None:
            return lanes
        return [lane for lane in lanes if lane.get("status") == status]

    def current_projection_revision(self) -> int:
        revision = self._read().get("projection_revision", 0)
        return int(revision) if isinstance(revision, int) and not isinstance(revision, bool) else 0

    def validate(self) -> None:
        try:
            state = self._read()
        except ValueError as exc:
            raise StateValidationError(str(exc)) from exc
        self._validator.validate_state(state).raise_if_invalid()

    def transition(
        self,
        lane_id: str,
        target_status: str,
        *,
        metadata: dict[str, Any] | None = None,
        guard: LaneMutationGuard | None = None,
    ) -> dict[str, Any]:
        return self._transition(
            lane_id,
            target_status,
            metadata=metadata,
            expected_metadata=None,
            guard=guard,
        )

    def transition_if_metadata(
        self,
        lane_id: str,
        target_status: str,
        *,
        expected_metadata: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        guard: LaneMutationGuard | None = None,
    ) -> dict[str, Any] | None:
        return self._transition(
            lane_id,
            target_status,
            metadata=metadata,
            expected_metadata=expected_metadata,
            guard=guard,
        )

    def controlled_terminal_update(
        self,
        lane_id: str,
        target_status: str,
        *,
        metadata: dict[str, Any] | None = None,
        guard: LaneMutationGuard | None = None,
    ) -> dict[str, Any]:
        if target_status not in {"reworking", "merged"}:
            raise InvalidTransitionError(
                "controlled terminal update only supports reworking or merged"
            )
        with observability_context(lane_id=lane_id), timed_core_operation(
            component="state_machine",
            operation="controlled_terminal_update",
            logger=logger,
            lane_id=lane_id,
            target_status=target_status,
        ):
            transition_result: dict[str, Any] = {}
            cleaned_metadata = _without_runtime_telemetry(metadata or {})

            def mutate(data: dict[str, Any]) -> None:
                lanes = data.get("lanes", [])
                lane = None
                for lane_item in lanes:
                    if lane_item.get("feature_id") == lane_id:
                        lane = lane_item
                        break
                if lane is None:
                    raise KeyError(f"lane not found: {lane_id}")
                if guard is not None:
                    guard(lane, data)

                current = str(lane.get("status") or "pending")
                if current != "failed":
                    raise InvalidTransitionError(
                        f"controlled terminal update requires failed source, got {current}"
                    )
                lane.update(cleaned_metadata)
                lane["status"] = target_status
                lane.pop("failure_reason", None)
                lane.pop("merge_failure_reason", None)
                lane.pop("merge_failure_detail", None)
                if target_status == "reworking":
                    retries = lane.get("retry_count", 0)
                    if retries >= MAX_RETRIES and not cleaned_metadata.get(
                        "takeover_retry_override"
                    ):
                        raise InvalidTransitionError(
                            f"lane {lane_id} exceeded max retries ({MAX_RETRIES})"
                        )
                    lane["retry_count"] = retries + 1 if isinstance(retries, int) else 1
                if target_status == "merged":
                    lane["gate_passed"] = True
                lane.setdefault("trace_id", current_observability_context()["trace_id"])
                transition_result["lane"] = copy.deepcopy(lane)
                transition_result["from_status"] = current

            self._projection.update(mutate)
            lane = transition_result["lane"]
            current = transition_result["from_status"]
            self._append_state_history(
                lane_id=lane_id,
                from_status=current,
                to_status=target_status,
                metadata=cleaned_metadata,
            )
            log_event(
                logger,
                logging.INFO,
                "lane_controlled_terminal_update",
                lane_id=lane_id,
                from_status=current,
                to_status=target_status,
            )
            return lane

    def _transition(
        self,
        lane_id: str,
        target_status: str,
        *,
        metadata: dict[str, Any] | None,
        expected_metadata: dict[str, Any] | None,
        guard: LaneMutationGuard | None,
    ) -> dict[str, Any] | None:
        with observability_context(lane_id=lane_id), timed_core_operation(
            component="state_machine",
            operation="transition",
            logger=logger,
            lane_id=lane_id,
            target_status=target_status,
        ):
            transition_result: dict[str, Any] = {}

            def mutate(data: dict[str, Any]) -> None:
                lanes = data.get("lanes", [])
                lane = None
                for lane_item in lanes:
                    if lane_item.get("feature_id") == lane_id:
                        lane = lane_item
                        break
                if lane is None:
                    raise KeyError(f"lane not found: {lane_id}")
                if guard is not None:
                    guard(lane, data)

                current = lane.get("status", "pending")
                lane.setdefault("status", current)
                if expected_metadata is not None and not _metadata_matches(
                    lane,
                    expected_metadata,
                ):
                    raise ProjectionWriteSkipped()
                before = copy.deepcopy(lane)
                allowed = VALID_TRANSITIONS.get(current, set())
                if target_status not in allowed:
                    raise InvalidTransitionError(
                        f"cannot transition {lane_id} from {current} to {target_status}"
                    )

                if target_status == "reworking":
                    retries = lane.get("retry_count", 0)
                    if retries >= MAX_RETRIES and not (metadata or {}).get(
                        "takeover_retry_override"
                    ):
                        raise InvalidTransitionError(
                            f"lane {lane_id} exceeded max retries ({MAX_RETRIES})"
                        )
                    lane["retry_count"] = retries + 1

                if metadata:
                    lane.update(_without_runtime_telemetry(metadata))
                lane["status"] = target_status
                if target_status in {"reworking", "dispatched", "gated"}:
                    lane.pop("failure_reason", None)
                lane.setdefault("trace_id", current_observability_context()["trace_id"])

                self._validator.validate_transition(
                    StateTransition(
                        lane_id=lane_id,
                        source_status=str(current),
                        target_status=target_status,
                        before=before,
                        after=lane,
                    ),
                    state_after=data,
                ).raise_if_invalid()
                transition_result["lane"] = copy.deepcopy(lane)
                transition_result["from_status"] = str(current)

            update_result = self._projection.update(mutate)
            if not update_result.wrote:
                return None
            lane = transition_result["lane"]
            current = transition_result["from_status"]
            self._append_state_history(
                lane_id=lane_id,
                from_status=current,
                to_status=target_status,
                metadata=metadata or {},
            )
            log_event(
                logger,
                logging.INFO,
                "lane_transitioned",
                lane_id=lane_id,
                from_status=current,
                to_status=target_status,
            )
            return lane

    def _append_state_history(
        self,
        *,
        lane_id: str,
        from_status: str,
        to_status: str,
        metadata: dict[str, Any],
    ) -> None:
        if self._history_path is None:
            return
        data = _read_json(self._history_path, {"snapshots": []})
        snapshots = data.setdefault("snapshots", [])
        snapshots.append(
            {
                "snapshot_id": f"snap-{uuid.uuid4().hex[:12]}",
                "lane_id": lane_id,
                "state_key": to_status,
                "timestamp": _utc_timestamp(),
                "metadata": {
                    "from_status": from_status,
                    **_without_runtime_telemetry(metadata),
                },
            }
        )
        _write_json(self._history_path, data)

    def update_metadata(
        self,
        lane_id: str,
        metadata: dict[str, Any],
        *,
        guard: LaneMutationGuard | None = None,
    ) -> dict[str, Any]:
        with observability_context(lane_id=lane_id), timed_core_operation(
            component="state_machine",
            operation="update_metadata",
            logger=logger,
            lane_id=lane_id,
        ):
            cleaned_metadata = _without_runtime_telemetry(metadata)
            updated: dict[str, Any] | None = None

            def mutate(data: dict[str, Any]) -> None:
                nonlocal updated
                lanes = data.get("lanes", [])
                lane = None
                for lane_item in lanes:
                    if lane_item.get("feature_id") == lane_id:
                        lane = lane_item
                        break
                if lane is None:
                    raise KeyError(f"lane not found: {lane_id}")
                if guard is not None:
                    guard(lane, data)
                before = copy.deepcopy(lane)
                if (
                    "status" in cleaned_metadata
                    and cleaned_metadata["status"] != before.get("status")
                ):
                    raise StateValidationError(
                        f"invariant_preservation: {lane_id}: "
                        "status cannot change during metadata update; use transition()"
                    )
                lane.setdefault("trace_id", current_observability_context()["trace_id"])
                lane.update(cleaned_metadata)
                if lane.get("feature_id") != before.get("feature_id"):
                    raise StateValidationError(
                        f"invariant_preservation: {lane_id}: "
                        "feature_id cannot change during metadata update"
                    )
                for field_name in ("retry_count", "review_retry_count"):
                    previous = before.get(field_name, 0)
                    current = lane.get(field_name, 0)
                    if (
                        isinstance(previous, int)
                        and isinstance(current, int)
                        and not isinstance(previous, bool)
                        and not isinstance(current, bool)
                        and current < previous
                    ):
                        raise StateValidationError(
                            f"invariant_preservation: {lane_id}: "
                            f"{field_name} cannot decrease"
                        )
                updated = copy.deepcopy(lane)

            self._projection.update(mutate)
            if updated is None:
                raise KeyError(f"lane not found: {lane_id}")
            log_event(
                logger,
                logging.DEBUG,
                "lane_metadata_updated",
                lane_id=lane_id,
                metadata_keys=sorted(metadata),
            )
            return updated

    def append_lane(self, lane: dict[str, Any]) -> dict[str, Any]:
        lane_id = str(lane.get("feature_id", "unknown"))
        with observability_context(lane_id=lane_id), timed_core_operation(
            component="state_machine",
            operation="append_lane",
            logger=logger,
            lane_id=lane_id,
        ):
            lane = _without_runtime_telemetry(lane)
            lane.setdefault("trace_id", current_observability_context()["trace_id"])
            lane = self._projection.append_lane(lane, on_duplicate="return_existing")
            lane.pop("projection_revision", None)
            log_event(logger, logging.INFO, "lane_appended", lane_id=lane_id)
            return lane


def _metadata_matches(lane: dict[str, Any], expected_metadata: dict[str, Any]) -> bool:
    for key, expected in expected_metadata.items():
        current = lane.get("status", "pending") if key == "status" else lane.get(key)
        if current != expected:
            return False
    return True


def _without_runtime_telemetry(payload: dict[str, Any]) -> dict[str, Any]:
    return strip_runtime_telemetry(payload)


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(default)
    return data if isinstance(data, dict) else dict(default)


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def _utc_timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
