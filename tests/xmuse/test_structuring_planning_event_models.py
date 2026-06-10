from __future__ import annotations

import pytest

from xmuse_core.structuring import planning_event_models
from xmuse_core.structuring.models import PlanningEvent as LegacyPlanningEvent
from xmuse_core.structuring.models import (
    PlanningEventStatus as LegacyPlanningEventStatus,
)


def test_planning_event_models_module_owns_event_contract() -> None:
    event = planning_event_models.PlanningEvent(
        event_id="event-1",
        event_type="blueprint.approved",
        conversation_id="conv-1",
        blueprint_ref="blueprint:conv-1:v1",
        dedupe_key="dedupe-1",
        idempotency_key="idem-1",
        created_at="2026-06-01T00:00:00Z",
        updated_at="2026-06-01T00:00:00Z",
    )

    assert event.status is planning_event_models.PlanningEventStatus.QUEUED
    assert event.planning_run_id is None


def test_planning_event_models_preserve_claimed_lease_validation() -> None:
    with pytest.raises(ValueError, match="claimed events require an active lease"):
        planning_event_models.PlanningEvent(
            event_id="event-1",
            event_type="feature_plan.ready",
            planning_run_id="run-1",
            conversation_id="conv-1",
            blueprint_ref="blueprint:conv-1:v1",
            dedupe_key="dedupe-1",
            idempotency_key="idem-1",
            status=planning_event_models.PlanningEventStatus.CLAIMED,
            created_at="2026-06-01T00:00:00Z",
            updated_at="2026-06-01T00:00:00Z",
        )


def test_structuring_models_preserves_planning_event_compat_exports() -> None:
    assert LegacyPlanningEvent is planning_event_models.PlanningEvent
    assert LegacyPlanningEventStatus is planning_event_models.PlanningEventStatus
