from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from xmuse_core.structuring.ready_set import build_graph_ready_set

_SUCCESS_STATUSES = {"done", "merged", "completed"}
_BLOCKABLE_STATUSES = {"pending", "reworking", "blocked", "failed"}


class FeatureOwnerExecutionContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = "xmuse.feature_owner_execution_contract.v1"
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


def _optional_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _require_text(value: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("value must be non-empty")
    return cleaned
