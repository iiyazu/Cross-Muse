from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from xmuse_core.chat.models import ResolutionStatus, StructuredResolution
from xmuse_core.structuring.feature_plan_store import read_approved_mission_blueprint
from xmuse_core.structuring.models import PlanningEvent
from xmuse_core.structuring.planning_event_store import PlanningEventStore


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_blueprint_approval_dedupe_key(
    *,
    conversation_id: str,
    blueprint_artifact_id: str,
    resolution_id: str,
) -> str:
    return ":".join((conversation_id, blueprint_artifact_id, resolution_id))


class BlueprintApprovalEventProducer:
    def __init__(
        self,
        store: PlanningEventStore,
        *,
        now: Callable[[], str] = _utc_now_iso,
        human_trigger_enabled: bool = False,
    ) -> None:
        self._store = store
        self._now = now
        self._human_trigger_enabled = human_trigger_enabled

    def enqueue_for_resolution(self, resolution: StructuredResolution) -> PlanningEvent | None:
        if resolution.status is not ResolutionStatus.APPROVED:
            return None
        if resolution.content.get("type") != "mission_blueprint":
            return None

        blueprint = read_approved_mission_blueprint(resolution)
        blueprint_artifact_id = blueprint.proposal_blueprint_ref or blueprint.blueprint_ref
        timestamp = self._now()
        event = PlanningEvent(
            event_id=f"pevt_{resolution.id}_blueprint_approved",
            event_type="blueprint.approved",
            planning_run_id=None,
            conversation_id=resolution.conversation_id,
            blueprint_ref=blueprint.blueprint_ref,
            dedupe_key=build_blueprint_approval_dedupe_key(
                conversation_id=resolution.conversation_id,
                blueprint_artifact_id=blueprint_artifact_id,
                resolution_id=resolution.id,
            ),
            idempotency_key=f"blueprint.approved:{resolution.id}",
            payload={
                "resolution_id": resolution.id,
                "resolution_version": resolution.version,
                "blueprint_artifact_id": blueprint_artifact_id,
                "goal_summary": resolution.goal_summary,
                "approved_by": list(resolution.approved_by),
                "approval_mode": resolution.approval_mode,
                "human_trigger_enabled": self._human_trigger_enabled,
            },
            created_at=timestamp,
            updated_at=timestamp,
        )
        return self._store.enqueue(event)


def produce_blueprint_approval_event(
    base_dir: Path | str,
    resolution: StructuredResolution,
) -> PlanningEvent | None:
    root = Path(base_dir)
    return BlueprintApprovalEventProducer(
        PlanningEventStore(root / "planning_events.sqlite3")
    ).enqueue_for_resolution(resolution)
