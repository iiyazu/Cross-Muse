from __future__ import annotations

import copy
import fcntl
import json
import os
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from xmuse_core.platform.projection.allowlist import (
    sanitize_projection_lane,
    strip_runtime_telemetry,
)
from xmuse_core.platform.state_validation import (
    StateTransitionValidator,
    StateValidationError,
)


class ProjectionRevisionConflict(ValueError):
    pass


class DuplicateLaneError(ValueError):
    pass


class ProjectionWriteSkipped(Exception):
    pass


@dataclass(frozen=True)
class ProjectionUpdateResult:
    data: dict[str, Any]
    projection_revision: int
    wrote: bool = True


class LaneProjectionSyncer:
    def __init__(
        self,
        path: Path | str,
        *,
        validator: StateTransitionValidator | None = None,
    ) -> None:
        self._path = Path(path)
        self._validator = validator

    def read(self) -> dict[str, Any]:
        with self._locked():
            return _hydrate_projection_document(
                self._read_unlocked(),
                projection_root=self._path.parent,
            )

    def update(
        self,
        mutator: Callable[[dict[str, Any]], dict[str, Any] | None],
        *,
        expected_revision: int | None = None,
    ) -> ProjectionUpdateResult:
        with self._locked():
            stored = self._read_unlocked()
            current_revision = _projection_revision(stored)
            if expected_revision is not None and expected_revision != current_revision:
                raise ProjectionRevisionConflict(
                    f"projection revision conflict: expected {expected_revision}, "
                    f"found {current_revision}"
                )
            data = _hydrate_projection_document(
                stored,
                projection_root=self._path.parent,
            )

            try:
                candidate = mutator(data)
            except ProjectionWriteSkipped:
                return ProjectionUpdateResult(
                    data=copy.deepcopy(data),
                    projection_revision=current_revision,
                    wrote=False,
                )
            if candidate is not None:
                if not isinstance(candidate, dict):
                    raise ValueError("projection mutator must return an object or None")
                data = candidate
            data = self._prepare_for_write(data, next_revision=current_revision + 1)
            self._write_unlocked(data)
            return ProjectionUpdateResult(
                data=_hydrate_projection_document(
                    copy.deepcopy(data),
                    projection_root=self._path.parent,
                ),
                projection_revision=int(data["projection_revision"]),
            )

    def append_lane(
        self,
        lane: dict[str, Any],
        *,
        on_duplicate: str = "raise",
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        if on_duplicate not in {"raise", "return_existing"}:
            raise ValueError("on_duplicate must be 'raise' or 'return_existing'")

        with self._locked():
            data = self._read_unlocked()
            current_revision = _projection_revision(data)
            if expected_revision is not None and expected_revision != current_revision:
                raise ProjectionRevisionConflict(
                    f"projection revision conflict: expected {expected_revision}, "
                    f"found {current_revision}"
                )
            lanes = data.setdefault("lanes", [])
            if not isinstance(lanes, list):
                raise ValueError("feature_lanes.json lanes must be a list")
            lane_id = lane.get("feature_id")
            for existing in lanes:
                if isinstance(existing, dict) and existing.get("feature_id") == lane_id:
                    if on_duplicate == "return_existing":
                        return _hydrate_projection_lane(
                            copy.deepcopy(existing),
                            projection_root=self._path.parent,
                        )
                    raise DuplicateLaneError(f"lane already exists: {lane_id}")

            lanes.append(
                sanitize_projection_lane(
                    lane,
                    projection_root=self._path.parent,
                )
            )
            data = self._prepare_for_write(
                data,
                next_revision=current_revision + 1,
            )
            self._write_unlocked(data)
            return {
                **_hydrate_projection_lane(
                    copy.deepcopy(data["lanes"][-1]),
                    projection_root=self._path.parent,
                ),
                "projection_revision": int(data["projection_revision"]),
            }

    def replace_lanes(self, lanes: list[dict[str, Any]]) -> dict[str, Any]:
        result = self.update(lambda data: {**data, "lanes": list(lanes)})
        return result.data

    def metadata_update(self, lane_id: str, metadata: dict[str, Any]) -> dict[str, Any]:
        metadata = strip_runtime_telemetry(metadata)
        updated: dict[str, Any] | None = None

        def mutate(data: dict[str, Any]) -> None:
            nonlocal updated
            lane = _find_lane(data, lane_id)
            before = copy.deepcopy(lane)
            if "status" in metadata and metadata["status"] != before.get("status"):
                raise StateValidationError(
                    f"invariant_preservation: {lane_id}: "
                    "status cannot change during metadata update; use transition()"
                )
            if "feature_id" in metadata and metadata["feature_id"] != before.get("feature_id"):
                raise StateValidationError(
                    f"invariant_preservation: {lane_id}: "
                    "feature_id cannot change during metadata update"
                )
            lane.update(metadata)
            updated = copy.deepcopy(lane)

        result = self.update(mutate)
        if updated is None:
            raise KeyError(f"lane not found: {lane_id}")
        return copy.deepcopy(_find_lane(result.data, lane_id))

    def update_lane(
        self,
        lane_id: str,
        mutator: Callable[[dict[str, Any]], Any],
    ) -> dict[str, Any]:
        updated: dict[str, Any] | None = None

        def mutate(data: dict[str, Any]) -> None:
            nonlocal updated
            lane = _find_lane(data, lane_id)
            mutator(lane)
            updated = copy.deepcopy(lane)

        result = self.update(mutate)
        if updated is None:
            raise KeyError(f"lane not found: {lane_id}")
        return copy.deepcopy(_find_lane(result.data, lane_id))

    @contextmanager
    def _locked(self):
        lock_path = self._path.with_name(f"{self._path.name}.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    def _read_unlocked(self) -> dict[str, Any]:
        if not self._path.exists():
            return {"lanes": []}
        data = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError(f"{self._path} JSON root must be an object")
        lanes = data.get("lanes")
        if not isinstance(lanes, list):
            raise ValueError("feature_lanes.json lanes must be a list")
        return data

    def _write_unlocked(self, data: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_name(f"{self._path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        tmp.write_text(
            json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self._path)

    def _prepare_for_write(
        self,
        data: dict[str, Any],
        *,
        next_revision: int,
    ) -> dict[str, Any]:
        data = copy.deepcopy(data)
        lanes = data.setdefault("lanes", [])
        if not isinstance(lanes, list):
            raise ValueError("feature_lanes.json lanes must be a list")
        data["lanes"] = [
            sanitize_projection_lane(
                lane,
                projection_root=self._path.parent,
            )
            if isinstance(lane, dict)
            else lane
            for lane in lanes
        ]
        data["projection_revision"] = next_revision
        validator = self._validator
        if validator is not None:
            validator.validate_state(data).raise_if_invalid()
        else:
            _validate_duplicate_lane_ids(data)
        return data

def _hydrate_projection_document(
    data: dict[str, Any],
    *,
    projection_root: Path,
) -> dict[str, Any]:
    hydrated = copy.deepcopy(data)
    lanes = hydrated.get("lanes")
    if not isinstance(lanes, list):
        return hydrated
    hydrated["lanes"] = [
        _hydrate_projection_lane(lane, projection_root=projection_root)
        if isinstance(lane, dict)
        else lane
        for lane in lanes
    ]
    return hydrated


def _hydrate_projection_lane(
    lane: dict[str, Any],
    *,
    projection_root: Path,
) -> dict[str, Any]:
    hydrated = copy.deepcopy(lane)
    if isinstance(hydrated.get("prompt"), str):
        return hydrated
    prompt_ref = hydrated.get("prompt_ref")
    if not isinstance(prompt_ref, str) or not prompt_ref.strip():
        return hydrated
    prompt_path = _resolve_prompt_ref(prompt_ref, projection_root=projection_root)
    try:
        hydrated["prompt"] = prompt_path.read_text(encoding="utf-8")
    except OSError:
        return hydrated
    return hydrated

def _resolve_prompt_ref(prompt_ref: str, *, projection_root: Path) -> Path:
    prompt_path = Path(prompt_ref)
    if prompt_path.is_absolute():
        return prompt_path
    candidates = [projection_root / prompt_path]
    if projection_root.name == "xmuse":
        candidates.append(projection_root.parent / prompt_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def _find_lane(data: dict[str, Any], lane_id: str) -> dict[str, Any]:
    lanes = data.get("lanes", [])
    if not isinstance(lanes, list):
        raise ValueError("feature_lanes.json lanes must be a list")
    for lane in lanes:
        if isinstance(lane, dict) and lane.get("feature_id") == lane_id:
            return lane
    raise KeyError(f"lane not found: {lane_id}")


def _projection_revision(data: dict[str, Any]) -> int:
    revision = data.get("projection_revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("projection_revision must be a non-negative integer")
    return revision


def _validate_duplicate_lane_ids(data: dict[str, Any]) -> None:
    list_fields = {
        "capabilities",
        "depends_on",
        "gate_profiles",
        "review_evidence_refs",
    }
    string_fields = {
        "feature_id",
        "status",
        "prompt",
        "worktree",
        "graph_id",
        "resolution_id",
        "conversation_id",
        "failure_reason",
        "final_action",
        "review_decision",
        "final_action_hold_id",
        "patch_lane_id",
        "proof_boundary",
    }
    int_fields = {
        "retry_count",
        "review_retry_count",
        "graph_version",
        "priority",
    }
    seen: set[str] = set()
    for lane in data.get("lanes", []):
        if not isinstance(lane, dict):
            raise StateValidationError("state_schema: lane must be an object")
        lane_id = lane.get("feature_id")
        if not isinstance(lane_id, str) or not lane_id:
            raise StateValidationError("state_schema: feature_id must be a non-empty string")
        if lane_id in seen:
            raise StateValidationError(f"state_schema: {lane_id}: duplicate feature_id")
        seen.add(lane_id)
        for field_name in string_fields:
            value = lane.get(field_name)
            if value is not None and not isinstance(value, str):
                raise StateValidationError(
                    f"state_schema: {lane_id}: {field_name} must be a string"
                )
        for field_name in list_fields:
            value = lane.get(field_name)
            if value is not None and not isinstance(value, list):
                raise StateValidationError(
                    f"state_schema: {lane_id}: {field_name} must be a list"
                )
        for field_name in int_fields:
            value = lane.get(field_name)
            if value is not None and (
                isinstance(value, bool) or not isinstance(value, int) or value < 0
            ):
                raise StateValidationError(
                    f"state_schema: {lane_id}: "
                    f"{field_name} must be a non-negative integer"
                )
        gate_passed = lane.get("gate_passed")
        if gate_passed is not None and not isinstance(gate_passed, bool):
            raise StateValidationError(
                f"state_schema: {lane_id}: gate_passed must be a boolean"
            )
