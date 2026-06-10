from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from xmuse_core.structuring.models import PlanningRun, PlanningRunStatus
from xmuse_core.structuring.planning_run_store import PlanningRunStore


def _run(
    *,
    planning_run_id: str = "planrun-1",
    dedupe_key: str = "conv-1:resolution:res-1:1",
    rerun_sequence: int = 0,
    rerun_of: str | None = None,
    status: PlanningRunStatus = PlanningRunStatus.PLANNING,
    feature_plan_id: str | None = None,
    feature_plan_version: int | None = None,
    graph_set_id: str | None = None,
    graph_set_version: int | None = None,
    audit_refs: list[str] | None = None,
    chat_card_refs: list[str] | None = None,
    created_at: str = "2026-05-31T00:00:00Z",
    updated_at: str = "2026-05-31T00:00:00Z",
) -> PlanningRun:
    return PlanningRun(
        planning_run_id=planning_run_id,
        conversation_id="conv-1",
        blueprint_ref="resolution:res-1:mission_blueprint",
        blueprint_version=1,
        dedupe_key=dedupe_key,
        rerun_sequence=rerun_sequence,
        rerun_of=rerun_of,
        status=status,
        feature_plan_id=feature_plan_id,
        feature_plan_version=feature_plan_version,
        graph_set_id=graph_set_id,
        graph_set_version=graph_set_version,
        risk_level="unknown",
        created_by="god",
        audit_refs=audit_refs or [],
        chat_card_refs=chat_card_refs or [],
        retry_count=0,
        created_at=created_at,
        updated_at=updated_at,
    )


def test_initial_create_round_trips_required_identity_and_artifact_fields(
    tmp_path: Path,
) -> None:
    store = PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    run = _run(
        feature_plan_id="feature-plan-1",
        feature_plan_version=2,
        graph_set_id="graph-set-1",
        graph_set_version=3,
        audit_refs=["audit:planning.started"],
        chat_card_refs=["card:blueprint_execution_started"],
    )

    saved = store.save(run)
    loaded = store.get(run.planning_run_id)

    assert saved == run
    assert loaded == run


def test_duplicate_approval_reuses_existing_initial_run_after_terminal_completion(
    tmp_path: Path,
) -> None:
    store = PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    dedupe_key = "conv-1:resolution:res-1:1"

    first = store.create_or_get_initial(
        conversation_id="conv-1",
        blueprint_ref="resolution:res-1:mission_blueprint",
        blueprint_version=1,
        dedupe_key=dedupe_key,
        planning_run_id="planrun-first",
    )
    store.save(
        first.model_copy(
            update={
                "status": PlanningRunStatus.TERMINAL,
                "updated_at": "2026-05-31T00:05:00Z",
            }
        )
    )

    reused = store.create_or_get_initial(
        conversation_id="conv-1",
        blueprint_ref="resolution:res-1:mission_blueprint",
        blueprint_version=1,
        dedupe_key=dedupe_key,
        planning_run_id="planrun-second",
    )

    assert reused.planning_run_id == first.planning_run_id
    assert [run.planning_run_id for run in store.list_by_dedupe_key(dedupe_key)] == [
        first.planning_run_id
    ]


def test_get_active_by_dedupe_key_returns_current_rerun(tmp_path: Path) -> None:
    store = PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    dedupe_key = "conv-1:resolution:res-1:1"
    initial = _run(
        planning_run_id="planrun-root",
        dedupe_key=dedupe_key,
        status=PlanningRunStatus.TERMINAL,
    )
    rerun = _run(
        planning_run_id="planrun-rerun-1",
        dedupe_key=dedupe_key,
        rerun_sequence=1,
        rerun_of=initial.planning_run_id,
        status=PlanningRunStatus.RUNNING,
        created_at="2026-05-31T00:10:00Z",
        updated_at="2026-05-31T00:10:00Z",
    )

    store.save(initial)
    store.save(rerun)

    assert store.get_active_by_dedupe_key(dedupe_key) == rerun


def test_get_latest_terminal_or_failed_by_dedupe_key_prefers_latest_closed_run(
    tmp_path: Path,
) -> None:
    store = PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    dedupe_key = "conv-1:resolution:res-1:1"
    terminal = _run(
        planning_run_id="planrun-root",
        dedupe_key=dedupe_key,
        status=PlanningRunStatus.TERMINAL,
        updated_at="2026-05-31T00:05:00Z",
    )
    failed = _run(
        planning_run_id="planrun-rerun-1",
        dedupe_key=dedupe_key,
        rerun_sequence=1,
        rerun_of=terminal.planning_run_id,
        status=PlanningRunStatus.FAILED,
        created_at="2026-05-31T00:10:00Z",
        updated_at="2026-05-31T00:15:00Z",
    )
    active = _run(
        planning_run_id="planrun-rerun-2",
        dedupe_key=dedupe_key,
        rerun_sequence=2,
        rerun_of=failed.planning_run_id,
        status=PlanningRunStatus.RUNNING,
        created_at="2026-05-31T00:20:00Z",
        updated_at="2026-05-31T00:20:00Z",
    )

    store.save(terminal)
    store.save(failed)
    store.save(active)

    assert store.get_latest_terminal_or_failed_by_dedupe_key(dedupe_key) == failed


def test_default_runtime_policy_values_are_persisted(tmp_path: Path) -> None:
    db_path = tmp_path / "planning_runs.sqlite3"
    store = PlanningRunStore(db_path)
    run = store.create_or_get_initial(
        conversation_id="conv-1",
        blueprint_ref="resolution:res-1:mission_blueprint",
        blueprint_version=1,
        dedupe_key="conv-1:resolution:res-1:1",
        planning_run_id="planrun-defaults",
    )

    stored = store.get(run.planning_run_id)
    assert stored.trigger_owner == "GOD"
    assert stored.human_trigger_enabled is False
    assert stored.manual_review_mode is False
    assert stored.review_policy == "risk_adaptive"
    assert stored.queue_backend == "sqlite"
    assert stored.external_mq == "disabled"

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            select
                trigger_owner,
                human_trigger_enabled,
                manual_review_mode,
                review_policy,
                queue_backend,
                external_mq
            from planning_runs
            where planning_run_id = ?
            """,
            (run.planning_run_id,),
        ).fetchone()

    assert row == ("GOD", 0, 0, "risk_adaptive", "sqlite", "disabled")


def test_unique_dedupe_key_and_rerun_sequence_is_enforced(tmp_path: Path) -> None:
    store = PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    dedupe_key = "conv-1:resolution:res-1:1"
    store.save(
        _run(
            planning_run_id="planrun-rerun-1",
            dedupe_key=dedupe_key,
            rerun_sequence=1,
            rerun_of="planrun-root",
            status=PlanningRunStatus.FAILED,
        )
    )

    with pytest.raises(sqlite3.IntegrityError):
        store.save(
            _run(
                planning_run_id="planrun-rerun-2",
                dedupe_key=dedupe_key,
                rerun_sequence=1,
                rerun_of="planrun-root",
                status=PlanningRunStatus.TERMINAL,
            )
        )


def test_append_artifact_refs_is_idempotent(tmp_path: Path) -> None:
    store = PlanningRunStore(tmp_path / "planning_runs.sqlite3")
    run = store.save(_run())

    first = store.append_artifact_refs(
        run.planning_run_id,
        audit_refs=[
            "audit_events.json#evt-1",
            "audit_events.json#evt-1",
        ],
        chat_card_refs=["card-intent-1", "card-intent-1"],
        human_trigger_enabled=True,
        updated_at="2026-05-31T00:05:00Z",
    )
    second = store.append_artifact_refs(
        run.planning_run_id,
        audit_refs=["audit_events.json#evt-1"],
        chat_card_refs=["card-intent-1"],
        human_trigger_enabled=True,
        updated_at="2026-05-31T00:06:00Z",
    )

    assert first.audit_refs == ["audit_events.json#evt-1"]
    assert first.chat_card_refs == ["card-intent-1"]
    assert first.human_trigger_enabled is True
    assert second.audit_refs == ["audit_events.json#evt-1"]
    assert second.chat_card_refs == ["card-intent-1"]
