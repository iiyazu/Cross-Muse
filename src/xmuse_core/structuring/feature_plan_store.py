from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Any

from pydantic import BaseModel, Field, field_validator

from xmuse_core.chat.models import ResolutionStatus, StructuredResolution
from xmuse_core.namespaces import build_scoped_storage_name
from xmuse_core.structuring.decomposition_review import (
    build_graph_set_decomposition_review,
)
from xmuse_core.structuring.feature_graph_builder import build_feature_graph_set
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.models import (
    ApprovedMissionBlueprint,
    FeatureGraphSet,
    FeaturePlanFeature,
    FeaturePlanProposal,
    FeaturePlanProposalApproval,
    FeaturePlanProposalStatus,
)
from xmuse_core.structuring.planning_contracts import (
    PlannerGodResponse,
    PlanningReviewResponse,
)
from xmuse_core.structuring.projection import project_feature_graph_set_ready_lanes


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_approved_mission_blueprint(resolution: StructuredResolution) -> ApprovedMissionBlueprint:
    if resolution.status != ResolutionStatus.APPROVED:
        raise ValueError("resolution must be approved")
    content = resolution.content
    if content.get("type") != "mission_blueprint":
        raise ValueError("resolution content must be a mission blueprint")
    return ApprovedMissionBlueprint(
        resolution_id=resolution.id,
        conversation_id=resolution.conversation_id,
        version=resolution.version,
        title=str(content.get("title") or resolution.goal_summary),
        body=str(content.get("body") or ""),
        acceptance_criteria=list(content.get("acceptance_criteria") or []),
        references=list(content.get("references") or []),
        blueprint_ref=str(content.get("blueprint_ref") or ""),
        proposal_blueprint_ref=content.get("proposal_blueprint_ref"),
        revision_of=content.get("revision_of"),
    )


def build_feature_plan_proposal(
    *,
    proposal_id: str,
    source_blueprint: StructuredResolution | ApprovedMissionBlueprint,
    features: list[FeaturePlanFeature],
    conversation_id: str | None = None,
) -> FeaturePlanProposal:
    blueprint = (
        read_approved_mission_blueprint(source_blueprint)
        if isinstance(source_blueprint, StructuredResolution)
        else source_blueprint
    )
    return FeaturePlanProposal(
        id=proposal_id,
        conversation_id=conversation_id or blueprint.conversation_id,
        source_blueprint=blueprint,
        features=features,
    )


def approve_feature_plan_proposal(
    proposal: FeaturePlanProposal,
    *,
    approval: FeaturePlanProposalApproval,
) -> FeaturePlanProposal:
    return proposal.model_copy(
        update={
            "status": FeaturePlanProposalStatus.APPROVED,
            "approval": approval,
        },
        deep=True,
    )


def save_approved_feature_plan_artifacts(
    proposal: FeaturePlanProposal,
    *,
    approval: FeaturePlanProposalApproval,
    resolution_id: str,
    version: int,
    feature_plans_root: Path | str,
    graph_sets_root: Path | str,
    lanes_path: Path | str,
) -> FeaturePlanProposal:
    approved_record = approve_feature_plan_proposal(proposal, approval=approval)
    FeaturePlanStore(feature_plans_root).save(approved_record)
    save_feature_graph_set_artifacts(
        approved_record,
        resolution_id=resolution_id,
        version=version,
        graph_sets_root=graph_sets_root,
        lanes_path=lanes_path,
    )
    return approved_record


def save_feature_graph_set_artifacts(
    proposal: FeaturePlanProposal,
    *,
    resolution_id: str,
    version: int,
    graph_sets_root: Path | str,
    lanes_path: Path | str,
) -> FeatureGraphSet:
    graph_set = build_feature_graph_set(
        proposal.to_feature_plan(
            resolution_id=resolution_id,
            version=version,
        )
    )
    graph_set = graph_set.model_copy(
        update={
            "decomposition_review": build_graph_set_decomposition_review(
                proposal,
                graph_set,
            )
        },
        deep=True,
    )
    FeatureGraphSetStore(graph_sets_root).save(graph_set)
    FeatureGraphStatusStore(
        Path(lanes_path).parent / "feature_graph_statuses.json"
    ).initialize_from_graph_set(
        graph_set,
        updated_at=_utc_now_iso(),
    )
    project_feature_graph_set_ready_lanes(
        graph_set,
        lanes_path,
        terminal_success_feature_ids=set(),
    )
    return graph_set


def _require_text(value: str, field_name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} must be non-empty")
    return clean


class FeaturePlanDeliberationAttempt(BaseModel):
    attempt_number: int
    feature_plan_version: int
    planner_request_id: str
    planner_correlation_id: str
    planner_response: PlannerGodResponse
    proposal: FeaturePlanProposal
    ready_intent_ref: str | None = None
    proposed_event_emitted: bool = False
    review_request_id: str | None = None
    review_correlation_id: str | None = None
    review_response: PlanningReviewResponse | None = None
    reviewed_event_emitted: bool = False

    @field_validator("attempt_number", "feature_plan_version")
    @classmethod
    def _validate_positive_int(cls, value: int, info: Any) -> int:
        if value < 1:
            raise ValueError(f"{info.field_name} must be >= 1")
        return value

    @field_validator("planner_request_id", "planner_correlation_id")
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)


class FeaturePlanDeliberationRecord(BaseModel):
    planning_run_id: str
    conversation_id: str
    feature_plan_id: str
    source_blueprint_ref: str
    status: str = "planning"
    max_reworks: int = 2
    rework_count: int = 0
    artifact_refs: list[str] = Field(default_factory=list)
    audit_refs: list[str] = Field(default_factory=list)
    chat_card_refs: list[str] = Field(default_factory=list)
    attempts: list[FeaturePlanDeliberationAttempt] = Field(default_factory=list)
    failure_reason: str | None = None
    created_at: str
    updated_at: str

    @field_validator(
        "planning_run_id",
        "conversation_id",
        "feature_plan_id",
        "source_blueprint_ref",
        "status",
        "created_at",
        "updated_at",
    )
    @classmethod
    def _validate_text(cls, value: str, info: Any) -> str:
        return _require_text(value, info.field_name)

    @field_validator("max_reworks", "rework_count")
    @classmethod
    def _validate_non_negative_int(cls, value: int, info: Any) -> int:
        if value < 0:
            raise ValueError(f"{info.field_name} must be >= 0")
        return value

    @field_validator("artifact_refs", "audit_refs", "chat_card_refs")
    @classmethod
    def _validate_lists(cls, values: list[str], info: Any) -> list[str]:
        return [_require_text(str(value), info.field_name) for value in values]


class FeaturePlanStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def save(self, proposal: FeaturePlanProposal) -> Path:
        path = self._path_for(proposal.id, conversation_id=proposal.conversation_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(proposal.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def get(
        self,
        proposal_id: str,
        *,
        conversation_id: str | None = None,
    ) -> FeaturePlanProposal:
        path = self._path_for(proposal_id, conversation_id=conversation_id)
        if not path.exists():
            raise KeyError(f"feature plan not found: {proposal_id}")
        return FeaturePlanProposal.model_validate_json(path.read_text(encoding="utf-8"))

    def load(
        self,
        proposal_id: str,
        *,
        conversation_id: str | None = None,
    ) -> FeaturePlanProposal:
        return self.get(proposal_id, conversation_id=conversation_id)

    def save_deliberation(self, record: FeaturePlanDeliberationRecord) -> Path:
        path = self._deliberation_path_for(
            record.feature_plan_id,
            conversation_id=record.conversation_id,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(record.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def get_deliberation(
        self,
        feature_plan_id: str,
        *,
        conversation_id: str | None = None,
    ) -> FeaturePlanDeliberationRecord:
        path = self._deliberation_path_for(
            feature_plan_id,
            conversation_id=conversation_id,
        )
        if not path.exists():
            raise KeyError(f"feature plan deliberation not found: {feature_plan_id}")
        return FeaturePlanDeliberationRecord.model_validate_json(
            path.read_text(encoding="utf-8")
        )

    def load_deliberation(
        self,
        feature_plan_id: str,
        *,
        conversation_id: str | None = None,
    ) -> FeaturePlanDeliberationRecord:
        return self.get_deliberation(feature_plan_id, conversation_id=conversation_id)

    def _path_for(
        self,
        proposal_id: str,
        *,
        conversation_id: str | None = None,
    ) -> Path:
        self._validate_feature_plan_id(proposal_id)
        if conversation_id is None:
            matches = sorted(self._root.glob(f"*--{proposal_id}.json"))
            if len(matches) > 1:
                raise ValueError(
                    f"ambiguous feature plan id across conversations: {proposal_id}"
                )
            if matches:
                return matches[0]
            return self._root / f"{proposal_id}.json"
        scoped_name = build_scoped_storage_name(
            conversation_id=conversation_id,
            object_id=proposal_id,
        )
        return self._root / f"{scoped_name}.json"

    def _deliberation_path_for(
        self,
        feature_plan_id: str,
        *,
        conversation_id: str | None = None,
    ) -> Path:
        self._validate_feature_plan_id(feature_plan_id)
        if conversation_id is None:
            matches = sorted(self._root.glob(f"*--{feature_plan_id}.deliberation.json"))
            if len(matches) > 1:
                raise ValueError(
                    f"ambiguous feature plan id across conversations: {feature_plan_id}"
                )
            if matches:
                return matches[0]
            return self._root / f"{feature_plan_id}.deliberation.json"
        scoped_name = build_scoped_storage_name(
            conversation_id=conversation_id,
            object_id=feature_plan_id,
        )
        return self._root / f"{scoped_name}.deliberation.json"

    def _validate_feature_plan_id(self, proposal_id: str) -> None:
        _validate_safe_id(proposal_id, "feature plan")


class FeatureGraphSetStore:
    def __init__(self, root: Path | str) -> None:
        self._root = Path(root)

    def save(self, graph_set: FeatureGraphSet) -> Path:
        path = self._path_for(
            graph_set.id,
            conversation_id=graph_set.feature_plan.conversation_id,
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(graph_set.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        return path

    def get(
        self,
        graph_set_id: str,
        *,
        conversation_id: str | None = None,
    ) -> FeatureGraphSet:
        path = self._path_for(graph_set_id, conversation_id=conversation_id)
        if not path.exists():
            raise KeyError(f"feature graph set not found: {graph_set_id}")
        return FeatureGraphSet.model_validate_json(path.read_text(encoding="utf-8"))

    def load(
        self,
        graph_set_id: str,
        *,
        conversation_id: str | None = None,
    ) -> FeatureGraphSet:
        return self.get(graph_set_id, conversation_id=conversation_id)

    def _path_for(
        self,
        graph_set_id: str,
        *,
        conversation_id: str | None = None,
    ) -> Path:
        _validate_safe_id(graph_set_id, "feature graph set")
        if conversation_id is None:
            matches = sorted(self._root.glob(f"*--{graph_set_id}.json"))
            if len(matches) > 1:
                raise ValueError(
                    f"ambiguous feature graph set id across conversations: {graph_set_id}"
                )
            if matches:
                return matches[0]
            return self._root / f"{graph_set_id}.json"
        scoped_name = build_scoped_storage_name(
            conversation_id=conversation_id,
            object_id=graph_set_id,
        )
        return self._root / f"{scoped_name}.json"


def _validate_safe_id(value: str, label: str) -> None:
    path = PurePath(value)
    if (
        not value.strip()
        or path.is_absolute()
        or any(part in {"..", ""} for part in path.parts)
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(f"unsafe {label} id: {value}")
