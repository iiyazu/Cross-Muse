from __future__ import annotations

import inspect
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from xmuse import chat_api_execution_runtime as execution_runtime
from xmuse import data_cli, data_restore, data_runtime_guard
from xmuse.chat_api_foundation import create_chat_api_foundation
from xmuse_core.chat.room_execution_contracts import (
    ExecutionRiskEvaluation,
    ExecutionWorkspaceGuard,
)
from xmuse_core.chat.room_execution_controller_store import RoomExecutionControllerStore
from xmuse_core.chat.room_execution_runtime_store import RoomExecutionRuntimeStore
from xmuse_core.runtime.processes import build_process_inventory

DIGEST = "sha256:" + "a" * 64


@pytest.mark.parametrize(
    ("adapter", "method_names"),
    (
        (
            RoomExecutionControllerStore,
            (
                "claim_requested_run",
                "reclaim_run_controller",
                "get_controller_material",
                "advance_run",
                "record_gate_evidence",
                "prepare_promotion",
                "mark_promotion_applying",
                "resolve_promotion",
                "acknowledge_cancel",
                "finalize_run",
            ),
        ),
        (RoomExecutionRuntimeStore, ("reconcile_consensus_candidate",)),
    ),
)
def test_execution_capability_adapters_reject_uncontracted_keywords(
    adapter: type[object], method_names: tuple[str, ...]
) -> None:
    for method_name in method_names:
        parameters = inspect.signature(getattr(adapter, method_name)).parameters.values()

        assert all(parameter.kind is not inspect.Parameter.VAR_KEYWORD for parameter in parameters)


def _runtime(tmp_path: Path) -> execution_runtime.RoomExecutionRuntime:
    return execution_runtime.RoomExecutionRuntime(
        root=tmp_path / "runtime",
        execution_root=tmp_path / "repo",
        launcher_root=tmp_path,
        generation="generation-one",
    )


def test_runtime_store_withholds_operator_controller_and_room_capabilities(
    tmp_path: Path,
) -> None:
    store = RoomExecutionRuntimeStore(tmp_path / "chat.db")

    assert not hasattr(store, "set_policy")
    assert not hasattr(store, "apply_operator_decision")
    assert not hasattr(store, "request_cancel")
    assert not hasattr(store, "claim_requested_run")
    assert not hasattr(store, "record_gate_evidence")
    assert not hasattr(store, "finalize_run")
    assert not hasattr(store, "bind_review_material_receipt")


def test_consensus_kill_switch_is_frozen_and_new_run_starts_only_once_per_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XMUSE_ENABLE_AGENT_CONSENSUS_EXECUTION", "1")
    runtime = _runtime(tmp_path)
    monkeypatch.setenv("XMUSE_ENABLE_AGENT_CONSENSUS_EXECUTION", "0")
    calls: list[object] = []
    gate_plan = object()

    class Store:
        def list_endorsed_candidate_ids(self, *, limit: int):
            assert limit == 20
            return ["candidate-one"]

        def reconcile_consensus_candidate(self, **kwargs):
            calls.append(kwargs["kill_switch_enabled"])
            calls.append(kwargs["gate_plan"])
            return {"run": {"run_id": "run-one"}}

        def list_controller_recovery(self, *, limit: int):
            assert limit == 500
            return [{"run_id": "run-one"}]

    runtime.store = Store()  # type: ignore[assignment]
    runtime._candidate = lambda _candidate_id: {"candidate_id": "candidate-one"}  # type: ignore[method-assign]
    runtime._risk_evaluation = lambda _candidate: ExecutionRiskEvaluation(  # type: ignore[method-assign]
        True, "room_execution_low_risk/v1", DIGEST
    )
    runtime._gate_plan = lambda _paths: gate_plan  # type: ignore[method-assign]
    monkeypatch.setattr(
        execution_runtime,
        "candidate_from_mapping",
        lambda _candidate: SimpleNamespace(base_head="a" * 40, allowed_files=("x.py",)),
    )
    monkeypatch.setattr(
        execution_runtime,
        "build_workspace_guard",
        lambda *_args: ExecutionWorkspaceGuard("a" * 40, True, DIGEST, frozenset({"x.py"})),
    )
    runtime.start_run = lambda run_id: calls.append(run_id)  # type: ignore[method-assign]

    result = runtime.reconcile_once()

    assert runtime.consensus_kill_switch_enabled is True
    assert result == {"consensus_checked": 1, "controllers_checked": 1}
    assert calls == [True, gate_plan, "run-one"]


def test_runtime_builds_profile_plan_from_trusted_repository_and_toolchain_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    candidate = {
        "candidate_id": "candidate-one",
        "allowed_files": ["src/example.py"],
    }
    exact = SimpleNamespace(
        base_head="a" * 40,
        allowed_files=("src/example.py",),
    )
    guard = ExecutionWorkspaceGuard("a" * 40, True, DIGEST, frozenset({"src/example.py"}))
    runtime._candidate = lambda _candidate_id: candidate  # type: ignore[method-assign]
    monkeypatch.setattr(execution_runtime, "candidate_from_mapping", lambda _value: exact)
    monkeypatch.setattr(execution_runtime, "build_workspace_guard", lambda *_args: guard)
    monkeypatch.setattr(
        execution_runtime,
        "build_repository_manifest_digest",
        lambda root, profile: (
            DIGEST
            if root == runtime.execution_root and profile.profile_id == "xmuse-monorepo/v2"
            else (_ for _ in ()).throw(AssertionError("unexpected repository evidence"))
        ),
    )
    observed_gate_ids: list[tuple[str, ...]] = []

    def toolchain(root, profile, *, gate_ids):
        assert root == runtime.execution_root
        assert profile.profile_id == "xmuse-monorepo/v2"
        observed_gate_ids.append(tuple(gate_ids))
        return "sha256:" + "b" * 64

    monkeypatch.setattr(execution_runtime, "build_toolchain_capability_digest", toolchain)

    actual_guard, risk, plan = runtime.decision_context("candidate-one")

    assert actual_guard is guard
    assert risk is None
    assert plan.profile_id == "xmuse-monorepo/v2"
    assert plan.gate_ids == (
        "patch_diff_check",
        "backend_ruff",
        "backend_mypy",
        "backend_pytest",
    )
    assert observed_gate_ids == [runtime.execution_profile.gate_ids]


def test_backend_candidate_cannot_bypass_globally_blocked_monorepo_profile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    candidate = {
        "candidate_id": "candidate-one",
        "allowed_files": ["src/example.py"],
    }
    runtime._candidate = lambda _candidate_id: candidate  # type: ignore[method-assign]
    monkeypatch.setattr(
        execution_runtime,
        "candidate_from_mapping",
        lambda _value: SimpleNamespace(
            base_head="a" * 40,
            allowed_files=("src/example.py",),
        ),
    )
    monkeypatch.setattr(
        execution_runtime,
        "build_workspace_guard",
        lambda *_args: ExecutionWorkspaceGuard(
            "a" * 40, True, DIGEST, frozenset({"src/example.py"})
        ),
    )
    monkeypatch.setattr(
        execution_runtime,
        "build_repository_manifest_digest",
        lambda *_args: DIGEST,
    )
    observed_gate_ids: list[tuple[str, ...]] = []

    def toolchain(_root, profile, *, gate_ids):
        selected = tuple(gate_ids)
        observed_gate_ids.append(selected)
        if selected == profile.gate_ids:
            raise execution_runtime.RoomExecutionSandboxError(
                "execution_frontend_dependencies_unavailable"
            )
        return "sha256:" + "b" * 64

    monkeypatch.setattr(execution_runtime, "build_toolchain_capability_digest", toolchain)

    with pytest.raises(
        execution_runtime.RoomExecutionSandboxError,
        match="execution_frontend_dependencies_unavailable",
    ):
        runtime.decision_context("candidate-one")

    assert observed_gate_ids == [runtime.execution_profile.gate_ids]


def test_profile_status_is_safe_and_blocks_on_capability_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    monkeypatch.setattr(
        execution_runtime,
        "build_repository_manifest_digest",
        lambda *_args: DIGEST,
    )
    monkeypatch.setattr(
        execution_runtime,
        "build_toolchain_capability_digest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            execution_runtime.RoomExecutionSandboxError(
                "execution_frontend_dependencies_unavailable"
            )
        ),
    )

    status = runtime.profile_status()

    assert status["profile_id"] == "xmuse-monorepo/v2"
    assert status["readiness"] == {
        "state": "blocked",
        "ready": False,
        "code": "execution_frontend_dependencies_unavailable",
    }
    assert "workspace" not in str(status).lower()
    assert "digest" not in str(status).lower()


def test_consensus_profile_failure_is_forwarded_as_durable_manual_required(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XMUSE_ENABLE_AGENT_CONSENSUS_EXECUTION", "1")
    runtime = _runtime(tmp_path)
    calls: list[object] = []

    class Store:
        def list_endorsed_candidate_ids(self, *, limit: int):
            return ["candidate-one"]

        def reconcile_consensus_candidate(self, **kwargs):
            calls.append(kwargs["gate_plan"])
            return {
                "status": "manual_required",
                "reason_code": "execution_gate_profile_unavailable",
                "run": None,
            }

        def list_controller_recovery(self, *, limit: int):
            return []

    runtime.store = Store()  # type: ignore[assignment]
    runtime._candidate = lambda _candidate_id: {  # type: ignore[method-assign]
        "candidate_id": "candidate-one",
        "base_head": "a" * 40,
    }
    monkeypatch.setattr(
        execution_runtime,
        "candidate_from_mapping",
        lambda _candidate: SimpleNamespace(base_head="a" * 40, allowed_files=("src/example.py",)),
    )
    monkeypatch.setattr(
        execution_runtime,
        "build_workspace_guard",
        lambda *_args: ExecutionWorkspaceGuard(
            "a" * 40, True, DIGEST, frozenset({"src/example.py"})
        ),
    )
    runtime._risk_evaluation = lambda _candidate: ExecutionRiskEvaluation(  # type: ignore[method-assign]
        True, "room_execution_low_risk/v1", DIGEST
    )
    runtime._gate_plan = lambda _paths: (_ for _ in ()).throw(  # type: ignore[method-assign]
        execution_runtime.RoomExecutionSandboxError("execution_backend_dependencies_unavailable")
    )
    runtime.start_run = lambda run_id: calls.append(run_id)  # type: ignore[method-assign]

    result = runtime.reconcile_once()

    assert result == {"consensus_checked": 1, "controllers_checked": 0}
    assert calls == [None]


def test_stop_all_scans_store_ceiling_and_fences_only_matching_live_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)
    limits: list[int] = []

    class Store:
        def list_controller_recovery(self, *, limit: int):
            limits.append(limit)
            return [
                {
                    "run_id": "live",
                    "controller_pid": 101,
                    "controller_start_identity": "start-101",
                },
                {
                    "run_id": "dead",
                    "controller_pid": 102,
                    "controller_start_identity": "start-102",
                },
            ]

    runtime.store = Store()  # type: ignore[assignment]
    monkeypatch.setattr(
        execution_runtime,
        "read_process_start_identity",
        lambda pid: "start-101" if pid == 101 else None,
    )
    stopped: list[tuple[int, str]] = []
    monkeypatch.setattr(
        execution_runtime,
        "stop_execution_controller",
        lambda *, pid, start_identity: stopped.append((pid, start_identity)) or True,
    )

    result = runtime.stop_all()

    assert limits == [500]
    assert stopped == [(101, "start-101")]
    assert result == {"stopped": 1, "pending": 0}


def test_starting_receipt_closes_preclaim_duplicate_and_shutdown_orphan_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runtime = _runtime(tmp_path)

    class Store:
        def list_controller_recovery(self, *, limit: int):
            return []

    class Process:
        def poll(self):
            return None

    runtime.store = Store()  # type: ignore[assignment]
    spawned: list[str] = []

    def ensure(_store, _config, *, run_id):
        spawned.append(run_id)
        return SimpleNamespace(
            run_id=run_id,
            controller_id="controller-one",
            pid=201,
            start_identity="start-201",
            process=Process(),
        )

    monkeypatch.setattr(execution_runtime, "ensure_execution_controller", ensure)
    stopped: list[tuple[int, str]] = []
    monkeypatch.setattr(
        execution_runtime,
        "stop_execution_controller",
        lambda *, pid, start_identity: stopped.append((pid, start_identity)) or True,
    )

    runtime.start_run("run-one")
    runtime.start_run("run-one")
    result = runtime.stop_all()

    assert spawned == ["run-one"]
    assert stopped == [(201, "start-201")]
    assert result == {"stopped": 1, "pending": 0}


def test_execution_failures_neither_block_api_start_nor_skip_room_shutdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("XMUSE_WORKROOM_MANAGED", "1")
    events: list[str] = []

    def room_stop(_root):
        events.append("room-stop")
        return {"state": "stopped"}

    def execution_reconcile():
        events.append("execution-reconcile-failed")
        raise RuntimeError("transient execution failure")

    def execution_stop():
        events.append("execution-stop-failed")
        raise RuntimeError("controller inspection unavailable")

    app, _context = create_chat_api_foundation(
        tmp_path,
        execution_worktree=tmp_path / "repo",
        auth_token=None,
        initialize_database=False,
        workroom_runtime_starter=lambda *_args: {"state": "ready", "ready": True},
        workroom_runtime_stopper=room_stop,
        workroom_runtime_inspector=lambda *_args: {
            "state": "ready",
            "ready": True,
            "code": "ready",
        },
        workroom_runtime_recoverer=lambda *_args: {},
        workroom_runtime_reconcile_interval_s=60,
        title="execution composition test",
        execution_reconciler=execution_reconcile,
        execution_stopper=execution_stop,
        execution_reconcile_interval_s=60,
    )

    with TestClient(app) as client:
        assert client.get("/health").status_code == 200

    assert events[0:3] == [
        "room-stop",
        "execution-reconcile-failed",
        "execution-stop-failed",
    ]
    assert events[-1] == "room-stop"
    assert events.count("room-stop") == 2
    assert app.state.execution_runtime_stop == {
        "state": "error",
        "code": "room_execution_runtime_stop_failed",
    }


def test_execution_controller_duplicates_are_a_hard_process_guard() -> None:
    inventory = build_process_inventory(services={"execution_controller": [101, 102]})

    assert inventory["services"][0]["state"] == "multiple"
    assert inventory["evidence"]["hard"] == [
        {
            "code": "duplicate_execution_controller_processes",
            "severity": "hard",
            "message": "multiple xmuse exact-patch execution controller processes are running",
            "service": "execution_controller",
            "count": 2,
            "pids": [101, 102],
        }
    ]


def test_data_guard_blocks_a_scoped_execution_controller(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        data_runtime_guard,
        "runtime_probe",
        lambda _root: {
            "managed": {"state": "stopped", "manager_live": False, "services": []},
            "inventory": {"services": [{"service": "execution_controller", "pids": [911]}]},
            "global_inventory": {"services": []},
        },
    )

    with pytest.raises(data_cli.DataError) as raised:
        data_runtime_guard.assert_runtime_stopped(
            tmp_path,
            probe=data_runtime_guard.runtime_probe,
        )

    assert raised.value.code == "workroom_running"
    assert raised.value.details["pids"] == [911]


def test_restore_fences_nonterminal_execution_without_replaying_process_action(
    tmp_path: Path,
) -> None:
    database = tmp_path / "chat.db"
    with sqlite3.connect(database) as conn:
        conn.executescript(
            """
            create table room_execution_authorizations (
                authorization_id text primary key,
                status text,
                reason_code text,
                invalidated_at text
            );
            create table room_execution_runs (
                run_id text primary key,
                authorization_id text,
                state text,
                revision integer,
                reason_code text,
                controller_id text,
                controller_generation text,
                controller_pid integer,
                controller_start_identity text,
                finished_at text,
                updated_at text
            );
            create table room_execution_promotion_journal (
                run_id text primary key,
                status text
            );
            """
        )
        for suffix in ("verify", "promote", "done"):
            conn.execute(
                "insert into room_execution_authorizations values (?, 'consumed', null, null)",
                (f"auth-{suffix}",),
            )
        conn.execute(
            "insert into room_execution_runs values "
            "('run-verify','auth-verify','verifying',3,null,'old','gen',11,'start',null,'old')"
        )
        conn.execute(
            "insert into room_execution_runs values "
            "('run-promote','auth-promote','promoting',4,null,'old','gen',12,'start',null,'old')"
        )
        conn.execute(
            "insert into room_execution_runs values "
            "('run-done','auth-done','succeeded',5,'ok','old','gen',13,'start','done','old')"
        )
        conn.execute(
            "insert into room_execution_promotion_journal values ('run-promote','applying')"
        )

    result = data_restore.fence_restored_execution_runs(
        database,
        operation_id="restore-one",
    )

    assert result == {"blocked": 2, "promotion_unverifiable": 1}
    with sqlite3.connect(database) as conn:
        rows = {
            row[0]: row[1:]
            for row in conn.execute(
                "select run_id,state,reason_code,controller_id,controller_pid "
                "from room_execution_runs order by run_id"
            )
        }
        assert rows["run-verify"] == (
            "blocked",
            "room_execution_restore_reauthorization_required",
            None,
            None,
        )
        assert rows["run-promote"] == (
            "blocked",
            "room_execution_promotion_unverifiable",
            None,
            None,
        )
        assert rows["run-done"] == ("succeeded", "ok", "old", 13)
        statuses = dict(
            conn.execute("select authorization_id,status from room_execution_authorizations")
        )
        assert statuses == {
            "auth-verify": "invalidated",
            "auth-promote": "invalidated",
            "auth-done": "consumed",
        }
