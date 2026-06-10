from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xmuse_core.structuring.models import PlanningEvent, PlanningEventStatus
from xmuse_core.structuring.planning_event_store import PlanningEventStore


def _event(
    *,
    event_id: str = "pevt-1",
    event_type: str = "blueprint.approved",
    planning_run_id: str | None = None,
    created_at: str = "2026-05-31T00:00:00Z",
    updated_at: str = "2026-05-31T00:00:00Z",
) -> PlanningEvent:
    return PlanningEvent(
        event_id=event_id,
        event_type=event_type,
        planning_run_id=planning_run_id,
        conversation_id="conv-1",
        blueprint_ref="resolution:res-1:mission_blueprint",
        dedupe_key="conv-1:resolution:res-1:1",
        idempotency_key=f"{event_type}:{event_id}",
        status=PlanningEventStatus.QUEUED,
        attempt=0,
        lease_owner=None,
        lease_expires_at=None,
        payload={"request_id": "req-1"},
        created_at=created_at,
        updated_at=updated_at,
    )


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(UTC)


def test_sqlite_queue_supports_enqueue_claim_heartbeat_attach_and_ack(tmp_path: Path) -> None:
    store = PlanningEventStore(tmp_path / "planning_queue.sqlite3")
    queued = store.enqueue(_event())

    claimed = store.claim_next(worker_id="worker-1", lease_ttl=timedelta(seconds=30))
    assert claimed is not None
    assert claimed.event_id == queued.event_id
    assert claimed.status is PlanningEventStatus.CLAIMED
    assert claimed.attempt == 1
    assert claimed.lease_owner == "worker-1"
    original_expiry = claimed.lease_expires_at

    heartbeated = store.heartbeat(claimed.event_id)
    assert heartbeated.lease_expires_at is not None
    assert original_expiry is not None
    assert _parse(heartbeated.lease_expires_at) > _parse(original_expiry)

    attached = store.attach_planning_run(claimed.event_id, planning_run_id="planrun-1")
    assert attached.planning_run_id == "planrun-1"

    acked = store.ack(claimed.event_id)
    assert acked.status is PlanningEventStatus.ACKED
    assert acked.lease_owner is None
    assert acked.lease_expires_at is None

    reloaded = store.get(claimed.event_id)
    assert reloaded == acked


def test_sqlite_queue_claim_next_can_filter_by_event_type(tmp_path: Path) -> None:
    store = PlanningEventStore(tmp_path / "planning_queue.sqlite3")
    approved = store.enqueue(_event(event_id="pevt-approved"))
    started = store.enqueue(
        _event(
            event_id="pevt-started",
            event_type="planning.started",
            planning_run_id="planrun-1",
            created_at="2026-05-31T00:00:01Z",
            updated_at="2026-05-31T00:00:01Z",
        )
    )

    claimed = store.claim_next(
        worker_id="worker-1",
        lease_ttl=timedelta(seconds=30),
        event_type="planning.started",
    )

    assert claimed == started.model_copy(
        update={
            "status": PlanningEventStatus.CLAIMED,
            "attempt": 1,
            "lease_owner": "worker-1",
            "lease_expires_at": claimed.lease_expires_at,
            "lease_ttl_seconds": 30,
            "updated_at": claimed.updated_at,
        }
    )
    assert store.get(approved.event_id).status is PlanningEventStatus.QUEUED


def test_sqlite_queue_nack_requeues_after_retry_window(tmp_path: Path) -> None:
    store = PlanningEventStore(tmp_path / "planning_queue.sqlite3")
    queued = store.enqueue(
        _event(
            event_id="pevt-2",
            event_type="planning.started",
            planning_run_id="planrun-1",
        )
    )
    claimed = store.claim_next(worker_id="worker-1", lease_ttl=timedelta(seconds=5))
    assert claimed is not None

    nacked = store.nack(
        queued.event_id,
        retry_after=timedelta(seconds=60),
        reason="planner_unavailable",
    )
    assert nacked.status is PlanningEventStatus.QUEUED
    assert nacked.lease_owner is None
    assert nacked.lease_expires_at is None
    assert nacked.last_error_reason == "planner_unavailable"
    assert nacked.available_at is not None

    assert store.claim_next(worker_id="worker-2", lease_ttl=timedelta(seconds=5)) is None


def test_sqlite_queue_reclaims_stale_leases(tmp_path: Path) -> None:
    store = PlanningEventStore(tmp_path / "planning_queue.sqlite3")
    store.enqueue(
        _event(
            event_id="pevt-3",
            event_type="planning.started",
            planning_run_id="planrun-1",
        )
    )
    claimed = store.claim_next(worker_id="worker-1", lease_ttl=timedelta(seconds=1))
    assert claimed is not None

    reclaimed = store.reclaim_stale_leases(
        now=_parse(claimed.lease_expires_at) + timedelta(seconds=1)  # type: ignore[arg-type]
    )
    assert [event.event_id for event in reclaimed] == [claimed.event_id]
    assert reclaimed[0].status is PlanningEventStatus.QUEUED
    assert reclaimed[0].recovered_from_stale_lease is True

    claimed_again = store.claim_next(
        worker_id="worker-2",
        lease_ttl=timedelta(seconds=30),
        now=_parse(claimed.lease_expires_at) + timedelta(seconds=2),  # type: ignore[arg-type]
    )
    assert claimed_again is not None
    assert claimed_again.event_id == claimed.event_id
    assert claimed_again.lease_owner == "worker-2"
    assert claimed_again.attempt == 2


def test_json_backend_persists_queue_state_for_tests(tmp_path: Path) -> None:
    path = tmp_path / "planning_queue.json"
    store = PlanningEventStore(path, backend="json")
    queued = store.enqueue(_event(event_id="pevt-json"))

    claimed = store.claim_next(worker_id="worker-1", lease_ttl=timedelta(seconds=30))
    assert claimed is not None
    acked = store.ack(queued.event_id)
    assert acked.status is PlanningEventStatus.ACKED

    reloaded = PlanningEventStore(path, backend="json").get(queued.event_id)
    assert reloaded.status is PlanningEventStatus.ACKED
    assert reloaded.attempt == 1


def test_file_backend_alias_persists_queue_state_for_tests(tmp_path: Path) -> None:
    path = tmp_path / "planning_queue.json"
    store = PlanningEventStore(path, backend="file")
    queued = store.enqueue(_event(event_id="pevt-file"))

    claimed = store.claim_next(worker_id="worker-1", lease_ttl=timedelta(seconds=30))
    assert claimed is not None
    acked = store.ack(queued.event_id)
    assert acked.status is PlanningEventStatus.ACKED

    reloaded = PlanningEventStore(path, backend="file").get(queued.event_id)
    assert reloaded.status is PlanningEventStatus.ACKED
    assert reloaded.attempt == 1


def test_non_blueprint_events_require_planning_run_id() -> None:
    with pytest.raises(
        ValueError,
        match="planning_run_id is required for events after blueprint.approved",
    ):
        _event(event_id="pevt-validate", event_type="planning.started")
