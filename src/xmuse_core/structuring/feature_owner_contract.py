from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xmuse_core.namespaces import build_projection_lane_id
from xmuse_core.structuring.ready_set import build_graph_ready_set

_SUCCESS_STATUSES = {"done", "merged", "completed"}
_BLOCKABLE_STATUSES = {"pending", "reworking", "blocked", "failed"}
_DEPENDENCY_UNSATISFIED = "dependency_unsatisfied"
_DEPENDENCY_MISSING = "dependency_missing"
_LANE_STATUS_BLOCKED = "lane_status_blocked"
_LANE_STATUS_FAILED = "lane_status_failed"


class FeatureOwnerReadySetProvenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority: str = "graph_native_ready_set"
    computed_from: str
    graph_set_id: str
    feature_graph_id: str
    source_refs: list[str] = Field(min_length=1)
    projection_authority: bool = False
    status_write_policy: str = "read_only_contract_no_status_writes"

    @field_validator(
        "authority",
        "computed_from",
        "graph_set_id",
        "feature_graph_id",
        "status_write_policy",
    )
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _require_text(value)

    @field_validator("source_refs")
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_text(value) for value in values]

    @model_validator(mode="after")
    def _validate_authority(self) -> FeatureOwnerReadySetProvenance:
        if self.authority != "graph_native_ready_set":
            raise ValueError("ready_set_provenance authority must be graph_native_ready_set")
        if self.projection_authority:
            raise ValueError("ready_set_provenance must not use projection authority")
        if self.status_write_policy != "read_only_contract_no_status_writes":
            raise ValueError(
                "ready_set_provenance status_write_policy must be "
                "read_only_contract_no_status_writes"
            )
        if "feature_lanes" in self.computed_from:
            raise ValueError("feature_lanes.json is projection, not ready-set authority")
        if any("feature_lanes.json" in ref for ref in self.source_refs):
            raise ValueError("feature_lanes.json is projection, not ready-set authority")
        return self


class FeatureOwnerLaneBlocker(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lane_id: str
    blocker_type: str
    blocker_ref: str
    blocker_status: str
    dispatch_blocking: bool = True
    source_authority: str = "graph_native_ready_set"

    @field_validator(
        "lane_id",
        "blocker_type",
        "blocker_ref",
        "blocker_status",
        "source_authority",
    )
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _require_text(value)

    @model_validator(mode="after")
    def _validate_blocker(self) -> FeatureOwnerLaneBlocker:
        if self.blocker_type not in {
            _DEPENDENCY_UNSATISFIED,
            _DEPENDENCY_MISSING,
            _LANE_STATUS_BLOCKED,
            _LANE_STATUS_FAILED,
        }:
            raise ValueError("unknown lane blocker_type")
        if self.source_authority != "graph_native_ready_set":
            raise ValueError("lane blocker source_authority must be graph_native_ready_set")
        if not self.dispatch_blocking:
            raise ValueError("lane blockers must be dispatch_blocking")
        return self


class FeatureOwnerExecutionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "xmuse.feature_owner_execution_contract.v2"
    feature_id: str
    objective: str
    graph_set_id: str
    feature_graph_id: str
    source_authority: str
    source_refs: list[str] = Field(min_length=1)
    allowed_files: list[str] = Field(min_length=1)
    lane_ids: list[str] = Field(default_factory=list)
    ready_lane_ids: list[str] = Field(default_factory=list)
    blocked_lane_ids: list[str] = Field(default_factory=list)
    completed_lane_ids: list[str] = Field(default_factory=list)
    lane_count: int = 0
    lane_authority: str = "graph_native_ready_set"
    feature_lanes_projection_authority: bool = False
    ready_set_provenance: FeatureOwnerReadySetProvenance | None = None
    lane_blockers: list[FeatureOwnerLaneBlocker] = Field(default_factory=list)
    memory_refs: list[str] = Field(default_factory=list)
    required_checks: list[str] = Field(min_length=1)
    review_profile: str
    patch_forward_policy: str
    rollback_constraints: list[str] = Field(min_length=1)

    @field_validator(
        "feature_id",
        "objective",
        "graph_set_id",
        "feature_graph_id",
        "source_authority",
        "lane_authority",
        "review_profile",
        "patch_forward_policy",
    )
    @classmethod
    def _validate_text(cls, value: str) -> str:
        return _require_text(value)

    @field_validator(
        "source_refs",
        "allowed_files",
        "lane_ids",
        "ready_lane_ids",
        "blocked_lane_ids",
        "completed_lane_ids",
        "memory_refs",
        "required_checks",
        "rollback_constraints",
    )
    @classmethod
    def _validate_text_list(cls, values: list[str]) -> list[str]:
        return [_require_text(value) for value in values]

    @model_validator(mode="after")
    def _validate_authority_and_lane_sets(self) -> FeatureOwnerExecutionContract:
        if self.lane_count == 0:
            self.lane_count = len(self.lane_ids)
        if self.lane_count != len(self.lane_ids):
            raise ValueError("lane_count must match lane_ids")
        if self.feature_lanes_projection_authority:
            raise ValueError("feature_lanes.json is projection, not feature owner authority")
        if "feature_lanes" in self.source_authority:
            raise ValueError("feature_lanes.json is projection, not feature owner authority")
        if any("feature_lanes.json" in ref for ref in self.source_refs):
            raise ValueError("feature_lanes.json is projection, not feature owner authority")
        if self.lane_authority != "graph_native_ready_set":
            raise ValueError("lane_authority must be graph_native_ready_set")
        owned = set(self.lane_ids)
        if not set(self.ready_lane_ids).issubset(owned):
            raise ValueError("ready_lane_ids must be owned lanes")
        if not set(self.blocked_lane_ids).issubset(owned):
            raise ValueError("blocked_lane_ids must be owned lanes")
        if not set(self.completed_lane_ids).issubset(owned):
            raise ValueError("completed_lane_ids must be owned lanes")
        if self.ready_set_provenance is None:
            self.ready_set_provenance = FeatureOwnerReadySetProvenance(
                computed_from=self.source_authority,
                graph_set_id=self.graph_set_id,
                feature_graph_id=self.feature_graph_id,
                source_refs=list(self.source_refs),
            )
        blocker_lane_ids = {blocker.lane_id for blocker in self.lane_blockers}
        if not blocker_lane_ids.issubset(set(self.blocked_lane_ids)):
            raise ValueError("lane_blockers must reference blocked lanes")
        missing_blocker_lane_ids = set(self.blocked_lane_ids) - blocker_lane_ids
        if missing_blocker_lane_ids:
            raise ValueError("blocked_lane_ids require lane_blockers")
        return self


def build_feature_owner_execution_contract(
    *,
    feature_id: str,
    objective: str,
    graph_set_id: str,
    feature_graph_id: str,
    source_authority: str,
    source_refs: Sequence[str],
    allowed_files: Sequence[str],
    lanes: Sequence[Mapping[str, Any]],
    memory_refs: Sequence[str] = (),
    required_checks: Sequence[str],
    review_profile: str,
    patch_forward_policy: str,
    rollback_constraints: Sequence[str],
) -> FeatureOwnerExecutionContract:
    graph_lanes = [
        lane
        for lane in lanes
        if _optional_text(lane.get("graph_id")) == feature_graph_id
    ]
    ready_lanes = build_graph_ready_set(
        graph_lanes,
        graph_id=feature_graph_id,
        resolution_id=None,
    )
    ready_lane_ids = {_lane_public_id(lane) for lane in ready_lanes}
    lane_ids = [_lane_public_id(lane) for lane in graph_lanes]
    completed_lane_ids = [
        _lane_public_id(lane)
        for lane in graph_lanes
        if _optional_text(lane.get("status")) in _SUCCESS_STATUSES
    ]
    lane_blockers = _build_lane_blockers(graph_lanes)
    blocked_lane_ids = [
        lane_id
        for lane in graph_lanes
        if (lane_id := _lane_public_id(lane)) not in ready_lane_ids
        and lane_id not in completed_lane_ids
        and _optional_text(lane.get("status")) in _BLOCKABLE_STATUSES
    ]
    return FeatureOwnerExecutionContract(
        feature_id=feature_id,
        objective=objective,
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
        source_authority=source_authority,
        source_refs=list(source_refs),
        allowed_files=list(allowed_files),
        lane_ids=lane_ids,
        ready_lane_ids=[lane_id for lane_id in lane_ids if lane_id in ready_lane_ids],
        blocked_lane_ids=blocked_lane_ids,
        completed_lane_ids=completed_lane_ids,
        lane_count=len(lane_ids),
        ready_set_provenance=FeatureOwnerReadySetProvenance(
            computed_from=source_authority,
            graph_set_id=graph_set_id,
            feature_graph_id=feature_graph_id,
            source_refs=list(source_refs),
        ),
        lane_blockers=[
            blocker
            for blocker in lane_blockers
            if blocker.lane_id in set(blocked_lane_ids)
        ],
        memory_refs=list(memory_refs),
        required_checks=list(required_checks),
        review_profile=review_profile,
        patch_forward_policy=patch_forward_policy,
        rollback_constraints=list(rollback_constraints),
    )


def _lane_public_id(lane: Mapping[str, Any]) -> str:
    for key in ("lane_local_id", "lane_id", "feature_id"):
        value = _optional_text(lane.get(key))
        if value is not None:
            return value
    raise ValueError("lane is missing lane_local_id, lane_id, or feature_id")


def _build_lane_blockers(
    graph_lanes: Sequence[Mapping[str, Any]],
) -> list[FeatureOwnerLaneBlocker]:
    statuses_by_public_id = {
        _lane_public_id(lane): _optional_text(lane.get("status"))
        for lane in graph_lanes
    }
    public_id_by_identity = {
        _lane_identity(lane): _lane_public_id(lane) for lane in graph_lanes
    }
    blockers: list[FeatureOwnerLaneBlocker] = []
    for lane in graph_lanes:
        lane_id = _lane_public_id(lane)
        for dependency_id in _lane_dependency_ids(lane):
            dependency_public_id = public_id_by_identity.get(dependency_id, dependency_id)
            dependency_status = statuses_by_public_id.get(dependency_public_id)
            if dependency_status in _SUCCESS_STATUSES:
                continue
            blockers.append(
                FeatureOwnerLaneBlocker(
                    lane_id=lane_id,
                    blocker_type=(
                        _DEPENDENCY_MISSING
                        if dependency_status is None
                        else _DEPENDENCY_UNSATISFIED
                    ),
                    blocker_ref=_lane_ref(dependency_public_id),
                    blocker_status=dependency_status or "missing",
                )
            )
        status = _optional_text(lane.get("status"))
        if status == "blocked" and not _has_blocker(blockers, lane_id):
            blockers.append(
                FeatureOwnerLaneBlocker(
                    lane_id=lane_id,
                    blocker_type=_LANE_STATUS_BLOCKED,
                    blocker_ref=_lane_ref(lane_id),
                    blocker_status=status,
                )
            )
        if status == "failed" and not _has_blocker(blockers, lane_id):
            blockers.append(
                FeatureOwnerLaneBlocker(
                    lane_id=lane_id,
                    blocker_type=_LANE_STATUS_FAILED,
                    blocker_ref=_lane_ref(lane_id),
                    blocker_status=status,
                )
            )
    return blockers


def _lane_dependency_ids(lane: Mapping[str, Any]) -> list[str]:
    scoped_dependencies = _text_list(lane.get("lane_depends_on_ids"))
    if scoped_dependencies:
        return scoped_dependencies
    return _text_list(lane.get("depends_on"))


def _lane_identity(lane: Mapping[str, Any]) -> str:
    conversation_id = _optional_text(lane.get("conversation_id"))
    graph_id = _optional_text(lane.get("graph_id"))
    lane_local_id = _optional_text(lane.get("lane_local_id")) or _optional_text(
        lane.get("feature_id")
    )
    if (
        conversation_id is not None
        and graph_id is not None
        and lane_local_id is not None
    ):
        return build_projection_lane_id(
            conversation_id=conversation_id,
            graph_id=graph_id,
            lane_local_id=lane_local_id,
        )
    lane_id = _optional_text(lane.get("lane_id"))
    if lane_id is not None:
        return lane_id
    return _lane_public_id(lane)


def _lane_ref(lane_id: str) -> str:
    if lane_id.startswith("lane:"):
        return lane_id
    return f"lane:{lane_id}"


def _has_blocker(blockers: Sequence[FeatureOwnerLaneBlocker], lane_id: str) -> bool:
    return any(blocker.lane_id == lane_id for blocker in blockers)


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _text_list(value: Any) -> list[str]:
    if not isinstance(value, list | tuple):
        return []
    return [_require_text(item) for item in value if isinstance(item, str)]


def _require_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("value must be non-empty")
    return cleaned
