from __future__ import annotations

import json
import signal
import sqlite3
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from scripts import room_soak_chaos as soak


class _FakeProcess:
    def __init__(self, pid: int = 500) -> None:
        self._pid = pid
        self.running = True
        self.terminated = False
        self.killed = False

    @property
    def pid(self) -> int:
        return self._pid

    def poll(self) -> int | None:
        return None if self.running else 0

    def terminate(self) -> None:
        self.terminated = True
        self.running = False

    def kill(self) -> None:
        self.killed = True
        self.running = False

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.running = False
        return 0


def _ci_evidence() -> dict[str, Any]:
    return {
        "schema_version": "room_soak_ci_evidence/v1",
        "profile_id": "ci-sim",
        "configuration": {
            "room_count": 12,
            "agents_per_room": 4,
            "human_turns_per_room": 20,
            "max_concurrent_provider_deliveries": 4,
        },
        "counts": {
            "human_posts": 240,
            "correlations": 240,
            "attempts": 960,
            "outcomes": 960,
            "root_attempts": 960,
            "peer_attempts": 0,
            "respond": 240,
            "noop": 720,
            "other_outcomes": 0,
            "skill_decisions": 960,
            "settled_correlations": 240,
        },
        "concurrency": {
            "max_active_deliveries": 4,
            "rooms_first_claimed": 12,
            "attempts_until_all_rooms_first_claimed": 12,
            "max_active_posts": 12,
            "queued_correlations_before_host": 12,
        },
        "latency_samples_ms": {
            "post_to_claim": [{"ordinal": 1, "latency_ms": 1}],
            "post_to_outcome": [{"ordinal": 1, "latency_ms": 2}],
            "post_to_settled": [{"ordinal": 1, "latency_ms": 3}],
        },
        "violations": {
            "duplicate_outcome": 0,
            "cross_room_identity": 0,
            "cross_room_causality": 0,
            "unsettled_correlation": 0,
        },
        "residual": {
            "live_leases": 0,
            "cleanup_pending": 0,
            "recovery_pending": 0,
            "exhausted": 0,
            "incomplete_attempts": 0,
        },
        "storage": {"database_bytes": 1, "wal_bytes": 0, "sqlite_integrity": "ok"},
    }


class _FakeSystem:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.clock = 0.0
        self.spawned = False
        self.ci_roots: list[Path] = []
        self.writes: list[Path] = []
        self.commands: list[tuple[str, ...]] = []
        self.process = _FakeProcess()

    def now(self) -> str:
        return "2026-07-12T00:00:00.000Z"

    def monotonic(self) -> float:
        return self.clock

    def sleep(self, seconds: float) -> None:
        self.clock += seconds

    def which(self, command: str) -> str | None:
        return f"/fake/{command}"

    def snapshot(self, _repo_root: Path) -> soak.RepositorySnapshot:
        return soak.RepositorySnapshot("head", True, "a" * 64, "b" * 64)

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> soak.CommandResult:
        del cwd, env, timeout_s
        self.commands.append(tuple(command))
        if "status" in command and "xmuse-workroom" in command:
            return soak.CommandResult(
                1,
                json.dumps(
                    {
                        "schema_version": "xmuse_workroom_status/v2",
                        "state": "stopped",
                        "services": [],
                    }
                ),
            )
        return soak.CommandResult(0)

    def spawn(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
    ) -> _FakeProcess:
        del command, cwd, env
        self.spawned = True
        return self.process

    def run_ci(self, *, runtime_root: Path) -> Mapping[str, Any]:
        self.ci_roots.append(runtime_root)
        return _ci_evidence()

    def build_result(self, **kwargs: Any) -> dict[str, Any]:
        evidence = kwargs["evidence"]
        integrity = evidence["storage"]["sqlite_integrity"]
        unsettled = evidence["violations"]["unsettled_correlation"]
        return {
            "schema_version": "room_soak_chaos_result/v1",
            "profile_id": evidence["profile_id"],
            "status": "passed" if integrity == "ok" and unsettled == 0 else "failed",
            "digest": "c" * 64,
        }

    def validate(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        return dict(payload)

    def evaluate(self, payload: Mapping[str, Any]) -> tuple[bool, tuple[str, ...]]:
        passed = payload.get("status") == "passed"
        return passed, (() if passed else ("soak_failed",))

    def write(self, path: Path, payload: Mapping[str, Any]) -> None:
        self.writes.append(path)
        path.write_text(json.dumps(payload), encoding="utf-8")

    def dependencies(self) -> soak.SoakDependencies:
        return soak.SoakDependencies(
            run=self.run,
            spawn=self.spawn,
            which=self.which,
            sleep=self.sleep,
            monotonic=self.monotonic,
            now=self.now,
            port_available=lambda _host, _port: True,
            repository_snapshot=self.snapshot,
            process_sample=lambda _pid: soak.ProcessSample(100, 10, 2),
            get_profile=lambda profile_id: {"profile_id": profile_id},
            build_result=self.build_result,
            validate_result=self.validate,
            evaluate_result=self.evaluate,
            write_result=self.write,
            run_ci_sim=self.run_ci,
        )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "frontend").mkdir(parents=True)
    return repo


def test_ci_sim_delegates_to_core_and_writes_only_safe_result(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    runtime = tmp_path / "runtime"
    result_path = tmp_path / "result.json"

    result = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id="ci-sim",
            runtime_root=runtime,
            result_path=result_path,
        ),
        dependencies=system.dependencies(),
    )

    assert result["status"] == "passed"
    assert system.ci_roots == [runtime]
    assert system.spawned is False
    assert json.loads(result_path.read_text(encoding="utf-8")) == result
    assert str(repo) not in json.dumps(result)
    assert str(runtime) not in json.dumps(result)


def test_live_soak_cost_confirmation_fails_before_start(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)

    result = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id="live-soak",
            runtime_root=tmp_path / "runtime",
            result_path=tmp_path / "result.json",
        ),
        dependencies=system.dependencies(),
    )

    assert result == {
        "schema_version": soak.CLI_ERROR_SCHEMA,
        "status": "blocked",
        "reason_code": "soak_provider_cost_confirmation_required",
        "proof_boundary": soak.CLI_ERROR_PROOF_BOUNDARY,
    }
    assert system.spawned is False
    assert not any("codex" in command for command in system.commands)


def test_live_endurance_requires_cost_then_memory_executable_before_start(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)

    missing_cost = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id=soak.ENDURANCE_PROFILE_ID,
            runtime_root=tmp_path / "runtime-cost",
            result_path=tmp_path / "result-cost.json",
        ),
        dependencies=system.dependencies(),
    )
    assert missing_cost["reason_code"] == "soak_provider_cost_confirmation_required"

    missing_memory = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id=soak.ENDURANCE_PROFILE_ID,
            runtime_root=tmp_path / "runtime-memory",
            result_path=tmp_path / "result-memory.json",
            confirm_provider_cost=True,
        ),
        dependencies=system.dependencies(),
    )
    assert missing_memory["reason_code"] == "soak_memoryos_executable_required"
    assert system.spawned is False


def test_memory_recovery_requires_executable_before_start(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)

    result = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id="memory-recovery",
            runtime_root=tmp_path / "runtime",
            result_path=tmp_path / "result.json",
        ),
        dependencies=system.dependencies(),
    )

    assert result == {
        "schema_version": soak.CLI_ERROR_SCHEMA,
        "status": "blocked",
        "reason_code": "soak_memoryos_executable_required",
        "proof_boundary": soak.CLI_ERROR_PROOF_BOUNDARY,
    }
    assert system.spawned is False


def test_goal_memory_profile_requires_cost_and_safe_memory_executable(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    executable = tmp_path / "memoryos"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o755)

    missing_cost = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id=soak.GOAL_MEMORY_PROFILE_ID,
            runtime_root=tmp_path / "runtime-cost",
            result_path=tmp_path / "result-cost.json",
            memoryos_executable=executable,
        ),
        dependencies=system.dependencies(),
    )
    assert missing_cost["reason_code"] == "soak_provider_cost_confirmation_required"

    symlink = tmp_path / "memoryos-link"
    symlink.symlink_to(executable)
    unsafe = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id=soak.GOAL_MEMORY_PROFILE_ID,
            runtime_root=tmp_path / "runtime-link",
            result_path=tmp_path / "result-link.json",
            memoryos_executable=symlink,
            confirm_provider_cost=True,
        ),
        dependencies=system.dependencies(),
    )
    assert unsafe["reason_code"] == "soak_memoryos_executable_unsafe"
    assert system.spawned is False


@pytest.mark.parametrize("raised", [RuntimeError("boom"), KeyboardInterrupt()])
def test_live_exception_always_stops_owned_workroom(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    raised: BaseException,
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)

    def fail_live(*args: Any, **kwargs: Any) -> Mapping[str, Any]:
        state = kwargs.get("state") or args[-1]
        assert isinstance(state, soak._LiveState)
        state.manager = system.process
        system.spawned = True
        raise raised

    monkeypatch.setattr(soak, "_run_live", fail_live)
    result = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id="live-short",
            runtime_root=tmp_path / "runtime",
            result_path=tmp_path / "result.json",
            build_frontend=False,
        ),
        dependencies=system.dependencies(),
    )

    assert result["status"] == "failed"
    assert system.process.terminated is True
    assert any("stop" in command and "xmuse-workroom" in command for command in system.commands)


def test_live_soak_distributes_four_waves_across_full_hour(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    state = soak._LiveState(
        manager=system.process,
        room_ids=[f"conv_{index:08d}" for index in range(6)],
        host_delivery_evidence_seen=True,
    )
    post_times: list[float] = []
    fault_order: list[str] = []
    before = system.snapshot(repo)

    monkeypatch.setattr(soak, "_start_workroom", lambda *args, **kwargs: {})
    monkeypatch.setattr(soak, "_create_rooms", lambda *args, **kwargs: None)

    def post_wave(*args: Any, **kwargs: Any) -> list[soak._Correlation]:
        post_times.append(deps.monotonic())
        return []

    monkeypatch.setattr(soak, "_post_wave", post_wave)
    monkeypatch.setattr(soak, "_wait_wave_settled", lambda *args, **kwargs: None)
    monkeypatch.setattr(soak, "_pause_runner", lambda *args, **kwargs: 50)
    monkeypatch.setattr(soak, "_resume_runner", lambda *args, **kwargs: None)
    monkeypatch.setattr(soak, "_pending_correlation_count", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        soak,
        "_kill_one_provider",
        lambda *args, **kwargs: fault_order.append("codex_app_server_sigkill"),
    )
    monkeypatch.setattr(
        soak,
        "_kill_runner_and_wait_recovery",
        lambda *args, **kwargs: fault_order.append("runner_sigkill"),
    )
    monkeypatch.setattr(
        soak,
        "_wait_ready",
        lambda *args, **kwargs: {
            "services": [
                {"service": "room_runner", "live": True},
                {"service": "room_mcp", "live": True},
            ]
        },
    )
    monkeypatch.setattr(soak, "_verify_browser", lambda *args, **kwargs: None)
    monkeypatch.setattr(soak, "_attempt_concurrency_peak", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        soak,
        "_database_evidence",
        lambda *args, **kwargs: {
            "profile_id": "",
            "configuration": {},
            "violations": {},
        },
    )

    soak._run_live(
        soak.SoakConfig(repo_root=repo, profile_id="live-soak"),
        deps,
        soak.LIVE_PROFILES["live-soak"],
        tmp_path / "runtime",
        tmp_path / "artifacts",
        {},
        before,
        state,
    )

    assert post_times == pytest.approx([0.0, 1200.0, 2400.0, 3600.0], abs=1.0)
    assert system.clock >= 3600.0
    assert fault_order == ["codex_app_server_sigkill", "runner_sigkill"]


def test_live_endurance_schedules_four_faults_then_steady_wave(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    spec = soak.LIVE_PROFILES[soak.ENDURANCE_PROFILE_ID]
    state = soak._LiveState(
        manager=system.process,
        room_ids=[f"conv_{index:08d}" for index in range(spec.room_count)],
        host_delivery_evidence_seen=True,
    )
    post_times: list[float] = []
    fault_order: list[str] = []
    before = system.snapshot(repo)
    proof = soak._MemoryFaultProof(
        binding=soak.ProcessBinding(61, "memory-start"),
        status_before={},
        started_at=0.0,
        run_started_at=0.0,
        cutoff_by_room={room_id: 1 for room_id in state.room_ids},
        wave0_activity_ids={"activity-anchor"},
        fault_window_activity_ids={"activity-backlog"},
        backlog_observed=True,
    )

    monkeypatch.setattr(soak, "_start_workroom", lambda *args, **kwargs: {})
    monkeypatch.setattr(soak, "_create_rooms", lambda *args, **kwargs: None)

    def post_wave(*args: Any, **kwargs: Any) -> list[soak._Correlation]:
        del args, kwargs
        post_times.append(deps.monotonic())
        if not state.endurance_prompt_categories:
            for index, (category, _message) in enumerate(soak.ENDURANCE_PROMPT_CATEGORIES):
                state.endurance_prompt_categories[category] = 7 if index < 4 else 6
        return []

    def event(kind: str, reason: str) -> soak._PendingChaosEvent:
        fault_order.append(kind)
        return soak._PendingChaosEvent(
            kind=kind,
            reason_code=reason,
            started_at=deps.monotonic(),
            run_started_at=0.0,
            recovery_ms=1,
            status={},
            active_delivery_count=0,
            managed_reconcile=kind != "codex_app_server_sigkill",
            runner_count=1,
            mcp_count=1,
        )

    monkeypatch.setattr(soak, "_post_wave", post_wave)
    monkeypatch.setattr(soak, "_wait_wave_settled", lambda *args, **kwargs: None)
    monkeypatch.setattr(soak, "_pause_runner", lambda *args, **kwargs: 50)
    monkeypatch.setattr(soak, "_resume_runner", lambda *args, **kwargs: None)
    monkeypatch.setattr(soak, "_pending_correlation_count", lambda *args, **kwargs: 2)
    monkeypatch.setattr(soak, "_begin_memoryos_fault", lambda *args, **kwargs: proof)
    monkeypatch.setattr(soak, "_assert_memory_fault_active", lambda *args, **kwargs: None)
    monkeypatch.setattr(soak, "_record_memory_fault_backlog", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        soak,
        "_kill_one_provider",
        lambda *args, **kwargs: event(
            "codex_app_server_sigkill", "codex_app_server_cleanup_confirmed"
        ),
    )
    monkeypatch.setattr(
        soak,
        "_kill_runner_and_wait_recovery",
        lambda *args, **kwargs: event("runner_sigkill", "runner_reconciled"),
    )
    monkeypatch.setattr(
        soak,
        "_wait_memoryos_recovery",
        lambda *args, **kwargs: event("memoryos_sigkill", "memoryos_reconciled"),
    )
    monkeypatch.setattr(
        soak,
        "_reset_agent_stream_cache_and_wait_recovery",
        lambda *args, **kwargs: event(
            "agent_stream_cache_delete", "agent_stream_cache_epoch_rotated"
        ),
    )

    def memory_evidence(*args: Any, **kwargs: Any) -> None:
        del args, kwargs
        state.verified_memory_evidence = {
            "enabled": True,
            "restart_count": 1,
            "outbox_delivered": 40,
            "outbox_pending": 0,
            "outbox_conflict": 0,
            "recall_receipts": 1,
            "recall_source_refs": 1,
        }

    monkeypatch.setattr(soak, "_wait_for_memory_evidence", memory_evidence)
    monkeypatch.setattr(soak, "_verify_browser", lambda *args, **kwargs: None)
    monkeypatch.setattr(soak, "_attempt_concurrency_peak", lambda *args, **kwargs: 2)
    monkeypatch.setattr(
        soak,
        "_database_evidence",
        lambda *args, **kwargs: {"profile_id": "", "configuration": {}, "violations": {}},
    )

    evidence = soak._run_live(
        soak.SoakConfig(repo_root=repo, profile_id=soak.ENDURANCE_PROFILE_ID),
        deps,
        spec,
        tmp_path / "runtime",
        tmp_path / "artifacts",
        {},
        before,
        state,
    )

    assert post_times == pytest.approx([0.0, 1440.0, 2880.0, 4320.0, 5760.0], abs=1.0)
    assert system.clock >= 7200.0
    assert fault_order == [
        "codex_app_server_sigkill",
        "runner_sigkill",
        "memoryos_sigkill",
        "agent_stream_cache_delete",
    ]
    assert [item["recovery_wave_settled"] for item in state.chaos_events] == [True] * 4
    assert "endurance_prompt_categories" not in evidence


def test_runner_pause_uses_private_binding_when_safe_status_omits_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    signals: list[tuple[int, signal.Signals]] = []
    identities = {41: "runner-start"}
    monkeypatch.setattr(
        soak,
        "_workroom_status",
        lambda *args, **kwargs: {
            "services": [{"service": "room_runner", "ready": True, "boot_id": "boot-one"}]
        },
    )
    deps = soak.SoakDependencies(
        runner_process_binding=lambda _root: soak.ProcessBinding(41, "runner-start"),
        process_start_identity=identities.get,
        signal_pid=lambda pid, sig: signals.append((pid, sig)),
    )

    binding = soak._pause_runner(
        soak.SoakConfig(repo_root=tmp_path, profile_id="live-short"),
        deps,
        tmp_path,
        {},
    )
    assert binding == soak.ProcessBinding(41, "runner-start")
    assert signals == [(41, signal.SIGSTOP)]

    identities[41] = "reused-process"
    with pytest.raises(soak.SoakError, match="soak_runner_resume_identity_lost"):
        soak._resume_runner(deps, binding)
    assert signals == [(41, signal.SIGSTOP)]


def test_runner_binding_prefers_self_receipt_over_launcher_receipt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "xmuse_core.chat.room_runtime.read_process_start_identity",
        lambda pid: {41: "runner-one", 42: "runner-two"}.get(pid),
    )
    (tmp_path / "room-runner-status.json").write_text(
        json.dumps({"pid": 41, "start_identity": "runner-one"}),
        encoding="utf-8",
    )
    assert soak._runner_process_binding(tmp_path) == soak.ProcessBinding(41, "runner-one")

    (tmp_path / "workroom_room_runner.pid.json").write_text(
        json.dumps({"pid": 42, "start_identity": "runner-two"}),
        encoding="utf-8",
    )
    assert soak._runner_process_binding(tmp_path) == soak.ProcessBinding(41, "runner-one")
    (tmp_path / "room-runner-status.json").unlink()
    assert soak._runner_process_binding(tmp_path) == soak.ProcessBinding(42, "runner-two")


def test_post_waves_overlap_first_room_without_exceeding_fixed_turn_budget(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    sequence = 0

    def http_json(
        method: str,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_s: float,
    ) -> soak.HttpJsonResponse:
        nonlocal sequence
        del method, payload, timeout_s
        sequence += 1
        room_id = url.split("/")[-2]
        return soak.HttpJsonResponse(201, {"activity_id": f"activity_{room_id}_{sequence}"})

    deps.http_json = http_json
    rooms = [f"conv_{index:08d}" for index in range(6)]
    state = soak._LiveState(room_ids=rooms)
    spec = soak.LIVE_PROFILES["live-soak"]

    for wave in range(spec.wave_count):
        soak._post_wave(spec, deps, state, wave=wave)

    by_room = {
        room_id: sum(item.conversation_id == room_id for item in state.correlations)
        for room_id in rooms
    }
    assert len(state.correlations) == spec.room_count * spec.human_turns_per_room == 24
    assert set(by_room.values()) == {spec.wave_count}
    assert state.max_active_posts == spec.room_count + 1


def test_endurance_posts_cover_six_fixed_read_only_categories_without_public_evidence(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    messages: list[str] = []

    def http_json(
        method: str,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_s: float,
    ) -> soak.HttpJsonResponse:
        del method, url, timeout_s
        messages.append(str(payload["message"]))
        return soak.HttpJsonResponse(201, {"activity_id": f"activity_{len(messages):08d}"})

    deps.http_json = http_json
    spec = soak.LIVE_PROFILES[soak.ENDURANCE_PROFILE_ID]
    state = soak._LiveState(room_ids=[f"conv_{index:08d}" for index in range(spec.room_count)])
    for wave in range(spec.wave_count):
        soak._post_wave(spec, deps, state, wave=wave)

    category_messages = dict(soak.ENDURANCE_PROMPT_CATEGORIES)
    assert len(messages) == spec.room_count * spec.human_turns_per_room == 40
    assert set(state.endurance_prompt_categories) == set(category_messages)
    assert sum(state.endurance_prompt_categories.values()) == 40
    assert all(count > 0 for count in state.endurance_prompt_categories.values())
    assert set(messages) == set(category_messages.values())
    assert all("Read-only" in message and "do not edit files" in message for message in messages)


def test_memory_recovery_uses_old_archival_anchor_across_two_phases(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    messages: list[str] = []

    def http_json(
        method: str,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_s: float,
    ) -> soak.HttpJsonResponse:
        del method, url, timeout_s
        message = payload["message"]
        request_id = payload["client_request_id"]
        assert isinstance(message, str) and isinstance(request_id, str)
        messages.append(message)
        return soak.HttpJsonResponse(201, {"activity_id": f"activity_{request_id}"})

    deps.http_json = http_json
    rooms = ["conv_00000001", "conv_00000002"]
    state = soak._LiveState(room_ids=rooms)
    spec = soak.LIVE_PROFILES["memory-recovery"]

    for wave in range(spec.wave_count):
        soak._post_wave(spec, deps, state, wave=wave)

    by_room = {
        room_id: sum(item.conversation_id == room_id for item in state.correlations)
        for room_id in rooms
    }
    assert set(by_room.values()) == {10}
    assert len([message for message in messages if "phase 1" in message]) == 18
    assert len([message for message in messages if "phase 2" in message]) == 2
    assert all("XMUSE_MEMORY_RECOVERY_ANCHOR_V1" in message for message in messages)
    assert state.max_active_posts == 18


def test_memory_evidence_proves_fault_backlog_replay_and_wave0_recall(tmp_path: Path) -> None:
    database = tmp_path / "chat.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table room_activities(
            activity_id text,
            conversation_id text,
            seq integer
        );
        create table room_observations(
            observation_id text,
            activity_id text
        );
        create table room_observation_attempts(
            attempt_id text,
            observation_id text
        );
        create table room_memory_outbox(
            conversation_id text,
            activity_id text,
            state text
        );
        create table room_memory_attempt_receipts(
            conversation_id text,
            attempt_id text,
            status text,
            source_activity_ids_json text
        );

        insert into room_activities values ('activity_wave0', 'conv_one', 1);
        insert into room_activities values ('activity_fault', 'conv_one', 2);
        insert into room_activities values ('activity_postfault', 'conv_one', 3);
        insert into room_observations values ('observation_postfault', 'activity_postfault');
        insert into room_observation_attempts values ('attempt_postfault', 'observation_postfault');
        insert into room_memory_outbox values ('conv_one', 'activity_wave0', 'delivered');
        insert into room_memory_outbox values ('conv_one', 'activity_fault', 'pending');
        insert into room_memory_attempt_receipts values (
            'conv_one', 'attempt_postfault', 'ok', '["activity_wave0"]'
        );
        """
    )
    connection.commit()
    proof = soak._MemoryFaultProof(
        binding=soak.ProcessBinding(20, "start-memory"),
        status_before={},
        started_at=1.0,
        run_started_at=0.0,
        cutoff_by_room={"conv_one": 1},
        wave0_activity_ids={"activity_wave0"},
    )
    soak._record_memory_fault_backlog(
        database,
        proof,
        [soak._Correlation("conv_one", "activity_fault", 2.0)],
    )
    assert proof.backlog_observed is True
    connection.execute(
        "update room_memory_outbox set state = 'delivered' where activity_id = ?",
        ("activity_fault",),
    )
    connection.commit()
    connection.close()

    evidence = soak._memory_evidence(
        database,
        ["conv_one"],
        enabled=True,
        restart_count=1,
        proof=proof,
    )

    assert evidence == {
        "enabled": True,
        "restart_count": 1,
        "outbox_delivered": 2,
        "outbox_pending": 0,
        "outbox_conflict": 0,
        "recall_receipts": 1,
        "recall_source_refs": 1,
    }
    assert "conv_one" not in json.dumps(evidence)


def test_memory_evidence_rejects_cross_room_source_and_wait_times_out(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "chat.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table room_activities(activity_id text, conversation_id text, seq integer);
        create table room_observations(observation_id text, activity_id text);
        create table room_observation_attempts(attempt_id text, observation_id text);
        create table room_memory_outbox(conversation_id text, activity_id text, state text);
        create table room_memory_attempt_receipts(
            conversation_id text, attempt_id text, status text, source_activity_ids_json text
        );
        insert into room_activities values ('wave0', 'conv_other', 1);
        insert into room_activities values ('fault', 'conv_one', 2);
        insert into room_activities values ('postfault', 'conv_one', 3);
        insert into room_observations values ('observation', 'postfault');
        insert into room_observation_attempts values ('attempt', 'observation');
        insert into room_memory_outbox values ('conv_one', 'fault', 'delivered');
        insert into room_memory_attempt_receipts values (
            'conv_one', 'attempt', 'ok', '["wave0"]'
        );
        """
    )
    connection.commit()
    connection.close()
    proof = soak._MemoryFaultProof(
        binding=soak.ProcessBinding(20, "start-memory"),
        status_before={},
        started_at=1.0,
        run_started_at=0.0,
        cutoff_by_room={"conv_one": 1},
        wave0_activity_ids={"wave0"},
        fault_window_activity_ids={"fault"},
        backlog_observed=True,
    )

    with pytest.raises(soak.SoakError, match="soak_memory_source_proof_invalid"):
        soak._memory_evidence(
            database,
            ["conv_one"],
            enabled=True,
            restart_count=1,
            proof=proof,
        )

    clock = [0.0]
    state = soak._LiveState(
        room_ids=["conv_one"],
        memory_fault_proof=proof,
    )
    deps = soak.SoakDependencies(
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )
    monkeypatch.setattr(
        soak,
        "_memory_evidence",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            soak.SoakError("soak_memory_recall_proof_incomplete")
        ),
    )
    monkeypatch.setattr(soak, "_sample_runtime", lambda *args, **kwargs: None)
    with pytest.raises(soak.SoakError, match="soak_memory_recovery_proof_timeout"):
        soak._wait_for_memory_evidence(
            soak.SoakConfig(
                repo_root=tmp_path,
                profile_id="memory-recovery",
                settle_timeout_s=1.0,
            ),
            deps,
            state,
            tmp_path,
            {},
        )


def test_database_evidence_orders_latency_by_post_start_and_counts_other_outcomes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "chat.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table room_activities(
            activity_id text,
            conversation_id text,
            seq integer,
            correlation_id text,
            actor_kind text,
            actor_participant_id text,
            causation_id text,
            created_at text,
            materialized_message_id text
        );
        create table participants(
            participant_id text,
            conversation_id text,
            status text
        );
        create table room_observations(
            observation_id text,
            conversation_id text,
            activity_id text,
            participant_id text,
            delivery_mode text,
            status text,
            completed_at text,
            outcome_type text,
            control_state text,
            produced_activity_id text,
            produced_message_id text
        );
        create table room_observation_batches(
            batch_id text,
            conversation_id text,
            participant_id text,
            correlation_id text,
            phase text,
            primary_observation_id text,
            member_count integer
        );
        create table room_observation_batch_members(
            batch_id text,
            observation_id text,
            activity_id text,
            activity_seq integer
        );
        create table room_observation_attempts(
            attempt_id text,
            batch_id text,
            conversation_id text,
            observation_id text,
            participant_id text,
            claimed_at text,
            state text,
            provider_phase text,
            recovery_state text,
            transport_started_at text,
            finished_at text
        );
        create table room_attempt_skill_decisions(attempt_id text);
        create table messages(id text, conversation_id text);

        insert into participants values ('part_one', 'conv_one', 'active');
        insert into participants values ('part_two', 'conv_one', 'active');
        insert into room_activities values (
            'activity_first', 'conv_one', 1, 'correlation_z', 'human', null,
            'activity_first', '2026-07-12T00:00:01.000Z', null
        );
        insert into room_activities values (
            'activity_second', 'conv_one', 2, 'correlation_a', 'human', null,
            'activity_second', '2026-07-12T00:00:00.000Z', null
        );
        insert into messages values ('message_first', 'conv_one');
        insert into messages values ('message_second', 'conv_one');
        insert into room_activities values (
            'activity_first_response', 'conv_one', 3, 'correlation_z', 'participant',
            'part_one', 'activity_first', '2026-07-12T00:00:01.030Z', 'message_first'
        );
        insert into room_activities values (
            'activity_second_response', 'conv_one', 4, 'correlation_a', 'participant',
            'part_one', 'activity_second', '2026-07-12T00:00:00.040Z', 'message_second'
        );
        insert into room_observations values (
            'observation_first', 'conv_one', 'activity_first', 'part_one', 'active',
            'completed', '2026-07-12T00:00:01.030Z', 'respond', 'active',
            'activity_first_response', 'message_first'
        );
        insert into room_observations values (
            'observation_second', 'conv_one', 'activity_second', 'part_one', 'active',
            'completed', '2026-07-12T00:00:00.040Z', 'handoff', 'active',
            'activity_second_response', 'message_second'
        );
        insert into room_observations values (
            'observation_first_peer', 'conv_one', 'activity_first', 'part_two', 'active',
            'completed', '2026-07-12T00:00:01.080Z', 'noop', 'active', null, null
        );
        insert into room_observation_batches values (
            'batch_first', 'conv_one', 'part_one', 'correlation_z', 'root',
            'observation_first', 1
        );
        insert into room_observation_batches values (
            'batch_second', 'conv_one', 'part_one', 'correlation_a', 'root',
            'observation_second', 1
        );
        insert into room_observation_batches values (
            'batch_first_peer', 'conv_one', 'part_two', 'correlation_z', 'root',
            'observation_first_peer', 1
        );
        insert into room_observation_batch_members values (
            'batch_first', 'observation_first', 'activity_first', 1
        );
        insert into room_observation_batch_members values (
            'batch_second', 'observation_second', 'activity_second', 2
        );
        insert into room_observation_batch_members values (
            'batch_first_peer', 'observation_first_peer', 'activity_first', 1
        );
        insert into room_observation_attempts values (
            'attempt_first', 'batch_first', 'conv_one', 'observation_first', 'part_one',
            '2026-07-12T00:00:01.010Z', 'completed', 'cleanup_succeeded', 'recovered',
            '2026-07-12T00:00:01.011Z', '2026-07-12T00:00:01.030Z'
        );
        insert into room_observation_attempts values (
            'attempt_second', 'batch_second', 'conv_one', 'observation_second', 'part_one',
            '2026-07-12T00:00:00.020Z', 'completed', 'cleanup_succeeded', 'recovered',
            '2026-07-12T00:00:00.021Z', '2026-07-12T00:00:00.040Z'
        );
        insert into room_observation_attempts values (
            'attempt_first_peer', 'batch_first_peer', 'conv_one', 'observation_first_peer',
            'part_two', '2026-07-12T00:00:01.015Z', 'completed',
            'cleanup_succeeded', 'recovered', '2026-07-12T00:00:01.016Z',
            '2026-07-12T00:00:01.080Z'
        );
        insert into room_attempt_skill_decisions values ('attempt_first');
        insert into room_attempt_skill_decisions values ('attempt_second');
        insert into room_attempt_skill_decisions values ('attempt_first_peer');

        insert into room_activities values (
            'activity_bad', 'conv_one', 5, 'correlation_bad', 'participant',
            'part_missing', 'activity_missing', '2026-07-12T00:00:02.000Z', null
        );
        """
    )
    connection.commit()
    connection.close()
    state = soak._LiveState(
        room_ids=["conv_one"],
        correlations=[
            soak._Correlation("conv_one", "activity_first", 1.0),
            soak._Correlation("conv_one", "activity_second", 2.0),
        ],
        rooms_first_claimed={"conv_one"},
    )

    evidence = soak._database_evidence(
        database,
        ["conv_one"],
        state=state,
        provider_orphans=0,
    )

    assert evidence["latency_samples_ms"] == {
        "post_to_claim": [
            {"ordinal": 1, "latency_ms": 10},
            {"ordinal": 2, "latency_ms": 20},
        ],
        "post_to_outcome": [
            {"ordinal": 1, "latency_ms": 30},
            {"ordinal": 2, "latency_ms": 40},
        ],
        "post_to_settled": [
            {"ordinal": 1, "latency_ms": 80},
            {"ordinal": 2, "latency_ms": 40},
        ],
    }
    assert evidence["counts"]["other_outcomes"] == 1
    assert evidence["counts"]["settled_correlations"] == 2
    assert evidence["violations"]["cross_room_identity"] == 1
    assert evidence["violations"]["cross_room_causality"] == 1

    connection = sqlite3.connect(database)
    connection.execute(
        """insert into room_observation_attempts values (
               'attempt_duplicate', 'batch_first', 'conv_one', 'observation_first',
               'part_one', '2026-07-12T00:00:01.012Z', 'completed',
               'cleanup_succeeded', 'recovered', '2026-07-12T00:00:01.013Z',
               '2026-07-12T00:00:01.031Z'
           )"""
    )
    connection.execute(
        "update room_observation_batch_members set activity_id = 'activity_second' "
        "where batch_id = 'batch_first'"
    )
    connection.execute(
        "update room_observations set produced_message_id = 'message_missing' "
        "where observation_id = 'observation_first'"
    )
    connection.execute(
        "update room_activities set correlation_id = 'correlation_wrong' "
        "where activity_id = 'activity_first_response'"
    )
    connection.commit()
    connection.row_factory = sqlite3.Row
    assert soak._duplicate_outcome_invariant_count(connection, ["conv_one"]) == 1
    assert soak._identity_invariant_count(connection, ["conv_one"]) > 1
    assert soak._causality_invariant_count(connection, ["conv_one"]) > 1
    connection.close()


def test_chaos_event_serialization_is_exact_and_safe() -> None:
    state = soak._LiveState()
    status = {
        "services": [
            {"service": "room_runner", "live": True},
            {"service": "room_mcp", "live": True},
        ]
    }
    soak._record_chaos(
        state,
        event=soak._PendingChaosEvent(
            kind="runner_sigkill",
            reason_code="runner_reconciled",
            started_at=12.0,
            run_started_at=10.0,
            recovery_ms=1200,
            status=status,
            active_delivery_count=2,
            managed_reconcile=True,
            runner_count=1,
            mcp_count=1,
        ),
        recovery_wave_settled=True,
    )

    assert state.chaos_events == [
        {
            "seq": 1,
            "kind": "runner_sigkill",
            "reason_code": "runner_reconciled",
            "offset_ms": 2000,
            "recovery_ms": 1200,
            "runner_count": 1,
            "mcp_count": 1,
            "active_delivery_count": 2,
            "managed_reconcile": True,
            "recovery_wave_settled": True,
        }
    ]


def test_provider_fault_target_must_be_a_current_delivering_attempt(tmp_path: Path) -> None:
    database = tmp_path / "chat.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table room_observation_attempts(
            attempt_id text,
            observation_id text,
            conversation_id text,
            participant_id text,
            state text,
            god_session_id text,
            claimed_at text
        );
        create table room_observations(
            observation_id text,
            participant_id text,
            status text
        );
        insert into room_observation_attempts values (
            'attempt_old', 'observation_old', 'conv_other', 'participant_old',
            'completed', 'god_alpha', '2026-07-12T00:00:00Z'
        );
        insert into room_observation_attempts values (
            'attempt_live', 'observation_live', 'conv_preferred', 'participant_live',
            'delivering', 'god_beta', '2026-07-12T00:00:01Z'
        );
        insert into room_observations values (
            'observation_live', 'participant_live', 'claimed'
        );
        insert into room_observations values (
            'observation_next', 'participant_live', 'pending'
        );
        """
    )
    connection.commit()
    connection.close()
    alpha = soak.ProcessBinding(10, "start-alpha")
    beta = soak.ProcessBinding(20, "start-beta")

    selected = soak._active_provider_binding(
        database,
        {"god_alpha": alpha, "god_beta": beta},
        preferred_conversation_id="conv_preferred",
        require_pending_followup=True,
    )

    assert selected == soak._ProviderFaultTarget(
        attempt_id="attempt_live",
        god_session_id="god_beta",
        conversation_id="conv_preferred",
        participant_id="participant_live",
        binding=beta,
    )


def test_provider_recovery_proof_keeps_private_identity_and_requires_exact_actions(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "god_sessions.json").write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "god_session_id": "god-stable",
                        "conversation_id": "conv-room",
                        "participant_id": "participant-target",
                        "feature_scope_id": "room_delivery_v1",
                        "provider_session_id": "thread-after",
                        "provider_binding_status": "active",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    proof = soak._ProviderRecoveryProof(
        conversation_id="conv-room",
        participant_id="participant-target",
        god_session_id="god-stable",
        provider_session_id_before="thread-before",
        session_guard_before="sha256:" + "a" * 64,
    )
    target_view = {
        "native_snapshot": {
            "value": {
                "guards": {"session": "sha256:" + "a" * 64},
            }
        }
    }
    target, identity = soak._prove_provider_recovery_identity(
        runtime,
        proof,
        [
            ("conv-other", "participant-other", {}),
            ("conv-room", "participant-target", target_view),
        ],
    )
    assert target[:2] == ("conv-room", "participant-target")
    assert identity == {
        "god_identity_unchanged": 1,
        "delivery_provider_rebound": 1,
        "native_session_guard_unchanged": 1,
    }
    assert "god-stable" not in json.dumps(identity)

    with sqlite3.connect(runtime / "chat.db") as conn:
        conn.execute(
            """create table room_codex_bridge_actions(
                   conversation_id text, participant_id text,
                   capability_id text, status text
               )"""
        )
        conn.executemany(
            "insert into room_codex_bridge_actions values (?, ?, ?, 'applied')",
            [
                ("conv-room", "participant-target", "settings_update"),
                ("conv-room", "participant-target", "console_turn_start"),
                ("conv-room", "participant-other", "console_turn_start"),
            ],
        )
    assert soak._provider_recovery_action_counts(runtime / "chat.db", proof) == {
        "settings_update": 1,
        "console_turn_start": 1,
    }


def test_provider_recovery_proof_rejects_unchanged_guard_and_duplicate_action(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    (runtime / "god_sessions.json").write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "god_session_id": "god-stable",
                        "conversation_id": "conv-room",
                        "participant_id": "participant-target",
                        "feature_scope_id": "room_delivery_v1",
                        "provider_session_id": "thread-before",
                        "provider_binding_status": "active",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    guard = "sha256:" + "a" * 64
    proof = soak._ProviderRecoveryProof(
        conversation_id="conv-room",
        participant_id="participant-target",
        god_session_id="god-stable",
        provider_session_id_before="thread-before",
        session_guard_before=guard,
    )
    with pytest.raises(soak.SoakError, match="soak_provider_recovery_delivery_session_unchanged"):
        soak._prove_provider_recovery_identity(
            runtime,
            proof,
            [
                (
                    "conv-room",
                    "participant-target",
                    {"native_snapshot": {"value": {"guards": {"session": guard}}}},
                )
            ],
        )

    with sqlite3.connect(runtime / "chat.db") as conn:
        conn.execute(
            """create table room_codex_bridge_actions(
                   conversation_id text, participant_id text,
                   capability_id text, status text
               )"""
        )
        conn.executemany(
            "insert into room_codex_bridge_actions values (?, ?, ?, 'applied')",
            [
                ("conv-room", "participant-target", "settings_update"),
                ("conv-room", "participant-target", "settings_update"),
                ("conv-room", "participant-target", "console_turn_start"),
            ],
        )
    with pytest.raises(
        soak.SoakError,
        match="soak_provider_recovery_native_action_evidence_invalid",
    ):
        soak._provider_recovery_action_counts(runtime / "chat.db", proof)


def test_native_action_refreshes_stale_guard_after_409_without_changing_action_id(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    stale_guard = "sha256:" + "a" * 64
    fresh_guard = "sha256:" + "b" * 64
    action_id = "codex_action_once"

    def projection(guard: str, *, applied: bool = False) -> dict[str, Any]:
        return {
            "participants": [
                {
                    "participant": {"participant_id": "participant-target"},
                    "capabilities": {
                        "actions": [
                            {
                                "capability_id": "console_turn_start",
                                "available": True,
                                "expected_session_guard": guard,
                                "expected_turn_guard": guard,
                                "confirmation_required": False,
                            }
                        ]
                    },
                    "room_bridge": {
                        "actions": (
                            [{"action_id": action_id, "status": "applied"}] if applied else []
                        )
                    },
                }
            ]
        }

    projections = iter(
        [
            projection(stale_guard),
            projection(fresh_guard),
            projection(fresh_guard, applied=True),
        ]
    )
    monkeypatch.setattr(soak, "_codex_projection", lambda *_args: next(projections))
    posted: list[Mapping[str, Any]] = []

    def http_json(
        method: str,
        url: str,
        payload: Mapping[str, Any],
        *,
        timeout_s: float,
    ) -> soak.HttpJsonResponse:
        del method, url, timeout_s
        posted.append(payload)
        if len(posted) == 1:
            return soak.HttpJsonResponse(409, {"detail": "codex_native_guard_conflict"})
        return soak.HttpJsonResponse(202, {"action_id": action_id})

    deps.http_json = http_json
    result = soak._invoke_native_action(
        soak.SoakConfig(repo_root=repo, profile_id=soak.GOAL_MEMORY_PROFILE_ID),
        deps,
        "conv-room",
        "participant-target",
        "console_turn_start",
        {"text": "safe"},
        timeout_s=5.0,
    )

    assert result == projection(fresh_guard, applied=True)
    assert len(posted) == 2
    assert posted[0]["client_action_id"] == posted[1]["client_action_id"]
    assert posted[0]["expected_session_guard"] == stale_guard
    assert posted[1]["expected_session_guard"] == fresh_guard


def test_goal_native_coverage_does_not_require_recovered_session_to_steer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    rooms = [f"conv-{index}" for index in range(4)]
    participants_by_room: dict[str, list[dict[str, Any]]] = {}
    flat: list[tuple[str, str]] = []
    for room_index, room_id in enumerate(rooms):
        participants_by_room[room_id] = []
        for agent_index in range(2):
            participant_id = f"participant-{room_index}-{agent_index}"
            flat.append((room_id, participant_id))
            participants_by_room[room_id].append(
                {
                    "participant": {"participant_id": participant_id},
                    "capabilities": {
                        "value": {
                            "models": [
                                {
                                    "id": "model-one",
                                    "model": "model-one",
                                    "efforts": ["max", "high", "medium"],
                                }
                            ]
                        }
                    },
                }
            )

    def codex_projection(_deps: object, conversation_id: str) -> dict[str, Any]:
        return {
            "participants": participants_by_room[conversation_id],
            "native_events": {"latest_event_seq": 0},
        }

    monkeypatch.setattr(soak, "_codex_projection", codex_projection)
    recovered = flat[0]
    monkeypatch.setattr(
        soak,
        "_prove_provider_recovery_identity",
        lambda *_args: (
            (*recovered, participants_by_room[recovered[0]][0]),
            {"god_identity_unchanged": 1, "session_guard_changed": 1},
        ),
    )
    calls: list[tuple[str, str, str]] = []

    def invoke(
        _config: object,
        _deps: object,
        conversation_id: str,
        participant_id: str,
        capability_id: str,
        _request: Mapping[str, Any],
        **_kwargs: object,
    ) -> dict[str, Any]:
        calls.append((conversation_id, participant_id, capability_id))
        return {}

    monkeypatch.setattr(soak, "_invoke_native_action", invoke)
    monkeypatch.setattr(
        soak,
        "_wait_native_state",
        lambda *_args, **_kwargs: {
            "native_snapshot": {"value": {"goal": {"status": "paused"}, "active_turn": False}}
        },
    )
    monkeypatch.setattr(
        soak,
        "_provider_recovery_action_counts",
        lambda *_args: {"settings_update": 1, "console_turn_start": 1},
    )
    monkeypatch.setattr(soak, "_wait_goal_continuation", lambda *_args: 1)
    state = soak._LiveState(
        room_ids=rooms,
        provider_recovery_proof=soak._ProviderRecoveryProof(
            conversation_id=recovered[0],
            participant_id=recovered[1],
            god_session_id="god-stable",
            provider_session_id_before="thread-before",
            session_guard_before="sha256:" + "a" * 64,
        ),
    )

    soak._prepare_goal_native_capabilities(
        soak.SoakConfig(repo_root=repo, profile_id=soak.GOAL_MEMORY_PROFILE_ID),
        deps,
        state,
        tmp_path / "runtime",
    )
    soak._resume_goal_for_hold(
        soak.SoakConfig(repo_root=repo, profile_id=soak.GOAL_MEMORY_PROFILE_ID),
        deps,
        state,
    )

    recovered_calls = [item[2] for item in calls if item[:2] == recovered]
    assert recovered_calls == ["settings_update", "console_turn_start"]
    console_targets = [item[:2] for item in calls if item[2] == "console_turn_start"]
    steer_targets = [item[:2] for item in calls if item[2] == "turn_steer"]
    goal_targets = [item[:2] for item in calls if item[2] == "goal_set"]
    pause_targets = [item[:2] for item in calls if item[2] == "goal_pause"]
    resume_targets = [item[:2] for item in calls if item[2] == "goal_resume"]
    assert len(console_targets) == 2
    assert len(steer_targets) == len(goal_targets) == 1
    assert steer_targets[0] != recovered
    assert goal_targets[0] not in {recovered, steer_targets[0]}
    assert pause_targets == resume_targets == goal_targets
    goal_capabilities = [item[2] for item in calls if item[:2] == goal_targets[0]]
    assert goal_capabilities[-3:] == ["goal_set", "goal_pause", "goal_resume"]
    assert state.goal_memory_evidence["goal_initial_continuation_checkpoint"] == 1
    assert state.goal_memory_evidence["goal_auto_continuations"] == 1


def test_post_cache_native_evidence_uses_one_non_goal_participant_per_room(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    deps = _FakeSystem(repo).dependencies()
    rooms = [f"conv-{index}" for index in range(4)]
    participants = [
        (room, f"participant-{room_index}-{agent_index}")
        for room_index, room in enumerate(rooms)
        for agent_index in range(2)
    ]
    goal_target = participants[0]
    calls: list[tuple[str, str, str]] = []

    def invoke(
        _config: object,
        _deps: object,
        conversation_id: str,
        participant_id: str,
        capability_id: str,
        _request: Mapping[str, Any],
        **_kwargs: object,
    ) -> dict[str, Any]:
        calls.append((conversation_id, participant_id, capability_id))
        return {}

    monkeypatch.setattr(soak, "_invoke_native_action", invoke)
    projection_calls: dict[str, int] = {}

    def projection(_deps: object, conversation_id: str) -> dict[str, Any]:
        projection_calls[conversation_id] = projection_calls.get(conversation_id, 0) + 1
        participant_id = next(
            item[1] for item in participants if item[0] == conversation_id and item != goal_target
        )
        return {
            "native_events": {
                "latest_event_seq": 10,
                "items": [
                    {"kind": kind, "participant_id": participant_id, "event_seq": 11 + index}
                    for index, kind in enumerate(soak.REQUIRED_NATIVE_EVENT_KINDS)
                ],
            }
        }

    monkeypatch.setattr(
        soak,
        "_codex_projection",
        projection,
    )
    state = soak._LiveState(
        room_ids=rooms,
        goal_memory_evidence={
            "participants": participants,
            "goal_room": goal_target[0],
            "goal_participant": goal_target[1],
        },
    )

    soak._rebuild_native_event_evidence_after_cache_reset(
        soak.SoakConfig(repo_root=repo, profile_id=soak.GOAL_MEMORY_PROFILE_ID),
        deps,
        state,
    )

    assert len(calls) == len(rooms)
    assert {item[0] for item in calls} == set(rooms)
    assert all(item[2] == "console_turn_start" for item in calls)
    assert goal_target not in {(item[0], item[1]) for item in calls}


def test_provider_recovery_requires_durable_cleanup_proof(tmp_path: Path) -> None:
    database = tmp_path / "chat.db"
    connection = sqlite3.connect(database)
    connection.execute(
        """create table room_observation_attempts(
               attempt_id text, provider_phase text, provider_cleanup_reason text
           )"""
    )
    connection.execute(
        "insert into room_observation_attempts values ('attempt', 'cleanup_succeeded', null)"
    )
    connection.commit()

    assert not soak._provider_cleanup_confirmed(database, "attempt")
    connection.execute(
        "update room_observation_attempts set provider_cleanup_reason = 'abort_succeeded'"
    )
    connection.commit()
    connection.close()
    assert soak._provider_cleanup_confirmed(database, "attempt")


def test_goal_model_combinations_exclude_models_not_supported_in_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path))
    (tmp_path / "models_cache.json").write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "room-safe", "supported_in_api": True},
                    {"slug": "room-unsafe", "supported_in_api": False},
                ]
            }
        ),
        encoding="utf-8",
    )

    combinations = soak._goal_model_combinations(
        [
            {"id": "room-safe", "model": "room-safe", "efforts": ["max", "medium"]},
            {"id": "room-unsafe", "model": "room-unsafe", "efforts": ["max", "medium"]},
            {"id": "unknown", "model": "unknown", "efforts": ["max"]},
        ]
    )

    assert combinations == [
        ("room-safe", "room-safe", "max"),
        ("unknown", "unknown", "max"),
        ("room-safe", "room-safe", "medium"),
    ]


def test_goal_model_combinations_prefer_runtime_scoped_codex_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "host-codex"))
    host_cache = tmp_path / "host-codex" / "models_cache.json"
    host_cache.parent.mkdir()
    host_cache.write_text(
        json.dumps({"models": [{"slug": "room-model", "supported_in_api": True}]}),
        encoding="utf-8",
    )
    runtime_cache = tmp_path / "runtime" / "room-codex-home" / "models_cache.json"
    runtime_cache.parent.mkdir(parents=True)
    runtime_cache.write_text(
        json.dumps({"models": [{"slug": "room-model", "supported_in_api": False}]}),
        encoding="utf-8",
    )

    assert (
        soak._goal_model_combinations(
            [{"id": "room-model", "model": "room-model", "efforts": ["max"]}],
            runtime_root=tmp_path,
        )
        == []
    )


def test_goal_participant_prefers_bounded_effort_over_max_assignment() -> None:
    assignments = [
        ("room-a", "participant-a", "gpt-5.6-sol", "max"),
        ("room-b", "participant-b", "gpt-5.6-terra", "max"),
        ("room-c", "participant-c", "gpt-5.4", "low"),
        ("room-d", "participant-d", "gpt-5.6-luna", "medium"),
    ]

    selected = soak._select_goal_participant(
        assignments,
        (
            ("room-a", "participant-a"),
            ("room-b", "participant-b"),
            ("room-d", "participant-d"),
        ),
    )

    assert selected == ("room-c", "participant-c", "gpt-5.4", "low")


def test_goal_participant_fails_closed_without_bounded_effort() -> None:
    with pytest.raises(soak.SoakError, match="soak_codex_goal_participant_unavailable"):
        soak._select_goal_participant(
            [
                ("room-a", "participant-a", "gpt-5.6-sol", "max"),
                ("room-b", "participant-b", "gpt-5.6-terra", "high"),
            ],
            (),
        )


def test_runtime_provider_discovery_owns_only_runner_descendants(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from xmuse_core.runtime import processes

    monkeypatch.setattr(
        processes,
        "discover_xmuse_runtime_processes",
        lambda **kwargs: {
            "services": [
                {"service": "codex_app_server", "pids": [201, 301]},
                {"service": "codex_worker", "pids": [202]},
            ]
        },
    )
    monkeypatch.setattr(
        soak,
        "_runner_process_binding",
        lambda _root: soak.ProcessBinding(100, "runner-start"),
    )
    monkeypatch.setattr(
        soak,
        "_provider_bindings",
        lambda _root: {"god_owned": soak.ProcessBinding(150, "wrapper-start")},
    )

    def descends(pid: int, ancestors: set[int]) -> bool:
        if ancestors == {100}:
            return pid in {150, 201, 202}
        return ancestors == {150} and pid == 201

    monkeypatch.setattr(
        soak,
        "_process_descends_from",
        descends,
    )

    assert soak._runtime_provider_pids(tmp_path) == (150, 201, 202)


@pytest.mark.parametrize(
    "profile_id",
    [soak.GOAL_MEMORY_PROFILE_ID, soak.ENDURANCE_PROFILE_ID],
)
def test_full_local_preflight_copies_proven_cache_and_runs_offline(
    tmp_path: Path,
    profile_id: str,
) -> None:
    source = tmp_path / "proven-cache"
    blobs = source / "models--qdrant--bge-small-en-v1.5-onnx-q" / "blobs"
    snapshot = source / "models--qdrant--bge-small-en-v1.5-onnx-q" / "snapshots" / "revision"
    blobs.mkdir(parents=True)
    snapshot.mkdir(parents=True)
    (blobs / "model").write_bytes(b"proved-model")
    (snapshot / "model_optimized.onnx").symlink_to("../../blobs/model")
    executable = tmp_path / "memoryos-venv" / "memoryos"
    python = executable.parent / "python"
    executable.parent.mkdir()
    executable.write_text("", encoding="utf-8")
    python.write_text("", encoding="utf-8")
    python.chmod(0o700)
    captured: dict[str, object] = {}

    def run(command, *, cwd, env, timeout_s):
        captured.update(command=command, cwd=cwd, env=env, timeout_s=timeout_s)
        return soak.CommandResult(0)

    runtime_root = tmp_path / "runtime-root"
    soak._prepare_full_local_memory_cache(
        soak.SoakConfig(
            repo_root=tmp_path,
            profile_id=profile_id,
            memoryos_executable=executable,
        ),
        soak.SoakDependencies(run=run),
        runtime_root,
        {soak.SOAK_FASTEMBED_CACHE_SOURCE_ENV: str(source)},
    )

    copied = runtime_root / "runtime" / "fastembed-cache"
    assert (copied / snapshot.relative_to(source) / "model_optimized.onnx").is_symlink()
    assert (copied / snapshot.relative_to(source) / "model_optimized.onnx").read_bytes() == (
        b"proved-model"
    )
    proof_env = captured["env"]
    assert isinstance(proof_env, dict)
    assert proof_env["HF_HUB_OFFLINE"] == "1"
    assert proof_env["TRANSFORMERS_OFFLINE"] == "1"
    assert proof_env["MEMORYOS_FASTEMBED_OFFLINE"] == "1"


def test_full_local_preflight_fails_closed_without_cache_source(tmp_path: Path) -> None:
    executable = tmp_path / "memoryos-venv" / "memoryos"
    python = executable.parent / "python"
    executable.parent.mkdir()
    executable.write_text("", encoding="utf-8")
    python.write_text("", encoding="utf-8")
    python.chmod(0o700)

    with pytest.raises(soak.SoakError, match="soak_memoryos_fastembed_cache_source_required"):
        soak._prepare_full_local_memory_cache(
            soak.SoakConfig(
                repo_root=tmp_path,
                profile_id=soak.GOAL_MEMORY_PROFILE_ID,
                memoryos_executable=executable,
            ),
            soak.SoakDependencies(),
            tmp_path / "runtime-root",
            {},
        )


def test_provider_fault_identity_selects_only_room_delivery_scope(tmp_path: Path) -> None:
    (tmp_path / "god_sessions.json").write_text(
        json.dumps(
            {
                "sessions": [
                    {
                        "god_session_id": "god-native",
                        "conversation_id": "conv-1",
                        "participant_id": "part-1",
                        "feature_scope_id": "room_native_v1",
                    },
                    {
                        "god_session_id": "god-delivery",
                        "conversation_id": "conv-1",
                        "participant_id": "part-1",
                        "feature_scope_id": "room_delivery_v1",
                        "provider_session_id": "thread-delivery",
                        "provider_binding_status": "active",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )

    assert (
        soak._registered_god_session_id(
            tmp_path,
            conversation_id="conv-1",
            participant_id="part-1",
        )
        == "god-delivery"
    )


def test_provider_fault_never_signals_unowned_or_reused_pid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    connection = sqlite3.connect(runtime / "chat.db")
    connection.executescript(
        """
        create table room_observation_attempts(
            attempt_id text, observation_id text, conversation_id text,
            participant_id text, state text, god_session_id text, claimed_at text
        );
        create table room_observations(
            observation_id text, participant_id text, status text
        );
        insert into room_observation_attempts values (
            'attempt_live', 'observation_live', 'conv_preferred', 'participant_live',
            'delivering', 'god_beta', '2026-07-12T00:00:01Z'
        );
        insert into room_observations values (
            'observation_live', 'participant_live', 'claimed'
        );
        insert into room_observations values (
            'observation_next', 'participant_live', 'pending'
        );
        """
    )
    connection.commit()
    connection.close()
    status = {
        "state": "ready",
        "services": [
            {
                "service": "room_runner",
                "ready": True,
                "host": {"active_delivery_count": 1},
            },
            {"service": "room_mcp", "ready": True},
        ],
    }
    monkeypatch.setattr(soak, "_wait_for_active_deliveries", lambda *args, **kwargs: status)
    config = soak.SoakConfig(repo_root=tmp_path, profile_id="live-short")

    for owned, identity, expected in (
        ((), "start-beta", "soak_provider_fault_target_unavailable"),
        ((20,), "reused-beta", "soak_provider_fault_identity_lost"),
    ):
        clock = [0.0]
        signals: list[tuple[int, int]] = []
        deps = soak.SoakDependencies(
            monotonic=lambda clock=clock: clock[0],
            sleep=lambda seconds, clock=clock: clock.__setitem__(0, clock[0] + seconds),
            provider_bindings=lambda _root: {"god_beta": soak.ProcessBinding(20, "start-beta")},
            runtime_provider_pids=lambda _root, owned=owned: owned,
            process_start_identity=lambda _pid, identity=identity: identity,
            signal_pid=lambda pid, sig, signals=signals: signals.append((pid, sig)),
        )
        with pytest.raises(soak.SoakError, match=expected):
            soak._kill_one_provider(
                config,
                deps,
                soak._LiveState(room_ids=["conv_preferred"]),
                runtime,
                {},
                run_started_at=0.0,
            )
        assert signals == []


def test_provider_fault_signals_unique_owned_native_descendant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wrapper = soak.ProcessBinding(20, "wrapper-start")
    identities = {20: "wrapper-start", 21: "native-start", 22: "other-start"}
    monkeypatch.setattr(
        soak,
        "_process_descends_from",
        lambda pid, ancestors: ancestors == {20} and pid in {21, 22},
    )

    target = soak._provider_signal_target(
        wrapper,
        (20, 21),
        read_identity=identities.get,
    )
    ambiguous = soak._provider_signal_target(
        wrapper,
        (20, 21, 22),
        read_identity=identities.get,
    )

    assert target == soak.ProcessBinding(21, "native-start")
    assert ambiguous is None


def test_provider_fault_fences_and_signals_native_then_wrapper() -> None:
    wrapper = soak.ProcessBinding(20, "wrapper-start")
    native = soak.ProcessBinding(21, "native-start")
    identities = {20: "wrapper-start", 21: "native-start"}
    signals: list[tuple[int, int]] = []

    def signal_pid(pid: int, sig: int) -> None:
        signals.append((pid, sig))
        identities.pop(pid)

    soak._signal_provider_process_tree(
        wrapper,
        native,
        read_identity=identities.get,
        signal_pid=signal_pid,
    )
    assert signals == [(21, soak.signal.SIGKILL), (20, soak.signal.SIGKILL)]

    identities = {20: "reused", 21: "native-start"}
    signals.clear()
    with pytest.raises(soak.SoakError, match="soak_provider_fault_identity_lost"):
        soak._signal_provider_process_tree(
            wrapper,
            native,
            read_identity=identities.get,
            signal_pid=signal_pid,
        )
    assert signals == []


def test_projection_cache_leaf_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime-root"
    cache_dir = runtime / "runtime"
    cache_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("cache", encoding="utf-8")
    cache = cache_dir / "room-codex-projection.sqlite3"
    cache.symlink_to(outside)
    with pytest.raises(soak.SoakError, match="soak_projection_cache_unsafe"):
        soak._unlink_projection_cache_leaf(runtime)
    cache.unlink()
    cache.write_text("cache", encoding="utf-8")
    os_link = tmp_path / "cache-hardlink"
    os_link.hardlink_to(cache)
    with pytest.raises(soak.SoakError, match="soak_projection_cache_unsafe"):
        soak._unlink_projection_cache_leaf(runtime)
    assert cache.exists()


def test_projection_cache_reset_fences_runner_before_unlink_and_uses_managed_reconcile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime-root"
    cache_dir = runtime / "runtime"
    cache_dir.mkdir(parents=True)
    cache = cache_dir / "room-codex-projection.sqlite3"
    cache.write_text("cache", encoding="utf-8")
    identity = {41: "runner-start"}
    clock = [0.0]
    boot = ["boot-before"]
    runtime_lock_held = [False]

    def status(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {
            "state": "ready",
            "services": [
                {"service": "frontend", "ready": True},
                {"service": "chat_api", "ready": True},
                {
                    "service": "room_runner",
                    "ready": True,
                    "pid": 41 if boot[0] == "boot-before" else 42,
                    "boot_id": boot[0],
                    "host": {"active_delivery_count": 0},
                },
                {"service": "room_mcp", "ready": True},
            ],
        }

    monkeypatch.setattr(soak, "_workroom_status", status)
    monkeypatch.setattr(soak, "_sample_runtime", lambda *args, **kwargs: None)
    from xmuse import chat_api_runtime
    from xmuse_core.chat import room_runtime_supervisor

    @contextmanager
    def runtime_lock(*args: Any, **kwargs: Any):
        del args, kwargs
        runtime_lock_held[0] = True
        try:
            yield
        finally:
            runtime_lock_held[0] = False

    monkeypatch.setattr(chat_api_runtime, "_locked_workroom_runtime_start", runtime_lock)
    monkeypatch.setattr(
        chat_api_runtime,
        "_stop_workroom_room_runtime_locked",
        lambda *args, **kwargs: (identity.pop(41), {"state": "stopped"})[-1],
    )

    def direct_ensure_is_forbidden(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        raise AssertionError("the soak process must not start the managed Room runtime")

    monkeypatch.setattr(room_runtime_supervisor, "ensure_room_runtime", direct_ensure_is_forbidden)

    def sleep(seconds: float) -> None:
        assert runtime_lock_held[0] is False
        clock[0] += seconds
        boot[0] = "boot-after"
        identity[42] = "runner-after"

    deps = soak.SoakDependencies(
        monotonic=lambda: clock[0],
        sleep=sleep,
        runner_process_binding=lambda _root: (
            soak.ProcessBinding(41, "runner-start")
            if boot[0] == "boot-before"
            else soak.ProcessBinding(42, "runner-after")
        ),
        process_start_identity=identity.get,
        runtime_service_counts=lambda _root: {"room_runner": 1, "room_mcp": 1},
    )

    event = soak._reset_projection_cache_and_wait_recovery(
        soak.SoakConfig(repo_root=tmp_path, profile_id=soak.GOAL_MEMORY_PROFILE_ID),
        deps,
        soak._LiveState(),
        runtime,
        {},
        run_started_at=0.0,
    )

    assert not cache.exists()
    assert event.kind == "codex_projection_cache_delete"
    assert event.runner_count == event.mcp_count == 1


def test_agent_stream_cache_reset_requires_owned_runner_stop_and_rotates_epoch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime = tmp_path / "runtime-root"
    cache = runtime / "runtime" / "room-agent-streams.sqlite3"
    cache.parent.mkdir(parents=True)

    def initialize(epoch: str) -> None:
        connection = sqlite3.connect(cache)
        connection.executescript(
            "create table stream_meta(singleton integer primary key, schema_version text, "
            "epoch text, next_seq integer);"
        )
        connection.execute(
            "insert into stream_meta values(1, 'room_agent_stream_cache/v1', ?, 1)",
            (epoch,),
        )
        connection.commit()
        connection.close()

    initialize("epoch-before")
    identity = {41: "runner-start"}
    clock = [0.0]
    boot = ["boot-before"]

    def status(*args: Any, **kwargs: Any) -> dict[str, Any]:
        del args, kwargs
        return {
            "state": "ready",
            "services": [
                {"service": "frontend", "ready": True},
                {"service": "chat_api", "ready": True},
                {
                    "service": "room_runner",
                    "ready": True,
                    "pid": 41 if boot[0] == "boot-before" else 42,
                    "boot_id": boot[0],
                    "host": {"active_delivery_count": 0},
                },
                {"service": "room_mcp", "ready": True},
            ],
        }

    monkeypatch.setattr(soak, "_workroom_status", status)
    monkeypatch.setattr(soak, "_sample_runtime", lambda *args, **kwargs: None)
    from xmuse import chat_api_runtime

    @contextmanager
    def runtime_lock(*args: Any, **kwargs: Any):
        del args, kwargs
        yield

    monkeypatch.setattr(chat_api_runtime, "_locked_workroom_runtime_start", runtime_lock)
    monkeypatch.setattr(
        chat_api_runtime,
        "_workroom_room_runtime_config",
        lambda *args, **kwargs: type("RuntimeConfig", (), {"generation": "generation"})(),
    )

    def stop(*args: Any, **kwargs: Any) -> dict[str, str]:
        del args, kwargs
        identity.pop(41)
        return {"state": "stopped"}

    monkeypatch.setattr(chat_api_runtime, "_stop_workroom_room_runtime_locked", stop)

    def sleep(seconds: float) -> None:
        clock[0] += seconds
        boot[0] = "boot-after"
        identity[42] = "runner-after"
        if not cache.exists():
            initialize("epoch-after")

    deps = soak.SoakDependencies(
        monotonic=lambda: clock[0],
        sleep=sleep,
        runner_process_binding=lambda _root: (
            soak.ProcessBinding(41, "runner-start")
            if boot[0] == "boot-before"
            else soak.ProcessBinding(42, "runner-after")
        ),
        process_start_identity=identity.get,
        runtime_service_counts=lambda _root: {"room_runner": 1, "room_mcp": 1},
    )
    event = soak._reset_agent_stream_cache_and_wait_recovery(
        soak.SoakConfig(repo_root=tmp_path, profile_id=soak.ENDURANCE_PROFILE_ID),
        deps,
        soak._LiveState(),
        runtime,
        {},
        run_started_at=0.0,
    )

    assert soak._agent_stream_cache_epoch(runtime) == "epoch-after"
    assert event.kind == "agent_stream_cache_delete"
    assert event.reason_code == "agent_stream_cache_epoch_rotated"
    assert event.active_delivery_count == 0
    assert event.managed_reconcile is True


def test_agent_stream_cache_delete_rejects_symlink_and_hardlink(tmp_path: Path) -> None:
    runtime = tmp_path / "runtime-root"
    cache_dir = runtime / "runtime"
    cache_dir.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("cache", encoding="utf-8")
    cache = cache_dir / "room-agent-streams.sqlite3"
    cache.symlink_to(outside)
    with pytest.raises(soak.SoakError, match="soak_agent_stream_cache_unsafe"):
        soak._unlink_agent_stream_cache(runtime)
    cache.unlink()
    cache.write_text("cache", encoding="utf-8")
    hardlink = tmp_path / "cache-hardlink"
    hardlink.hardlink_to(cache)
    with pytest.raises(soak.SoakError, match="soak_agent_stream_cache_unsafe"):
        soak._unlink_agent_stream_cache(runtime)
    assert cache.exists()


def test_cleanup_incomplete_preserves_auto_runtime_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    runtime = tmp_path / "owned-runtime"
    artifacts = tmp_path / "owned-artifacts"

    def mkdtemp(*, prefix: str) -> str:
        path = runtime if "runtime" in prefix else artifacts
        path.mkdir()
        return str(path)

    monkeypatch.setattr(soak.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(
        soak,
        "_run_live",
        lambda *args, **kwargs: (_ for _ in ()).throw(soak.SoakError("live_failed")),
    )
    deps = system.dependencies()
    deps.provider_pids = lambda _root: (77,)
    deps.runtime_provider_pids = lambda _root: ()
    deps.runtime_service_counts = lambda _root: {
        "room_runner": 0,
        "room_mcp": 0,
        "codex": 0,
    }

    result = soak.run_soak(
        soak.SoakConfig(
            repo_root=repo,
            profile_id="live-short",
            result_path=tmp_path / "result.json",
            build_frontend=False,
        ),
        dependencies=deps,
    )

    assert result["reason_code"] == "soak_cleanup_incomplete"
    assert runtime.is_dir()
    assert system.clock >= soak.CLEANUP_PROVIDER_TIMEOUT_S


def test_readiness_rejects_duplicate_owned_runtime_service(tmp_path: Path) -> None:
    clock = [0.0]
    status = {
        "state": "ready",
        "services": [
            {"service": "room_runner", "ready": True},
            {"service": "room_mcp", "ready": True},
        ],
    }
    deps = soak.SoakDependencies(
        run=lambda *args, **kwargs: soak.CommandResult(0, json.dumps(status)),
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        runtime_service_counts=lambda _root: {
            "room_runner": 2,
            "room_mcp": 1,
            "codex": 0,
        },
    )
    with pytest.raises(soak.SoakError, match="soak_workroom_readiness_timeout"):
        soak._wait_ready(
            soak.SoakConfig(
                repo_root=tmp_path,
                profile_id="live-short",
                readiness_timeout_s=0.5,
            ),
            deps,
            soak._LiveState(),
            tmp_path,
            {},
        )


def test_attempt_concurrency_and_resource_windows_fail_closed(tmp_path: Path) -> None:
    database = tmp_path / "chat.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        create table room_observation_attempts(
            attempt_id text, conversation_id text, state text, provider_phase text,
            transport_started_at text, finished_at text
        );
        insert into room_observation_attempts values (
            'one', 'conv_one', 'completed', 'cleanup_succeeded',
            '2026-07-12T00:00:00Z', '2026-07-12T00:00:02Z'
        );
        insert into room_observation_attempts values (
            'two', 'conv_one', 'completed', 'cleanup_succeeded',
            '2026-07-12T00:00:01Z', '2026-07-12T00:00:03Z'
        );
        """
    )
    connection.commit()
    assert soak._attempt_concurrency_peak(database, ["conv_one"]) == 2
    connection.execute(
        "update room_observation_attempts set finished_at = null where attempt_id = 'two'"
    )
    connection.commit()
    connection.close()
    with pytest.raises(soak.SoakError, match="soak_attempt_interval_incomplete"):
        soak._attempt_concurrency_peak(database, ["conv_one"])

    samples = [
        soak.ProcessSample(100, 10, 2, offset_ms=0),
        soak.ProcessSample(200, 20, 3, offset_ms=1_000),
        soak.ProcessSample(400, 30, 4, offset_ms=2_000),
    ]
    assert soak._resource_evidence(samples, warmup_cutoff_ms=1_000) == {
        "rss_warmup_median_bytes": 150,
        "rss_steady_state_max_bytes": 400,
        "fd_warmup": 15,
        "fd_steady_state_max": 30,
        "process_count_max": 4,
    }
    with pytest.raises(soak.SoakError, match="soak_resource_sampling_window_incomplete"):
        soak._resource_evidence(samples[:2], warmup_cutoff_ms=1_000)


def test_default_browser_verifier_passes_only_explicit_paths_and_no_token(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    captured: dict[str, str] = {}

    def run(
        command: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout_s: float,
    ) -> soak.CommandResult:
        del cwd, timeout_s
        assert command[-1] == "room-soak-real.spec.ts"
        assert "XMUSE_OPERATOR_TOKEN" not in env
        captured.update(env)
        Path(env["XMUSE_SOAK_BROWSER_EVIDENCE_PATH"]).write_text(
            json.dumps(
                {
                    "schema_version": soak.BROWSER_EVIDENCE_SCHEMA,
                    "refreshes": 2,
                    "console_errors": 0,
                    "page_errors": 0,
                }
            ),
            encoding="utf-8",
        )
        return soak.CommandResult(0)

    deps = system.dependencies()
    deps.run = run
    request = soak.BrowserVerificationRequest(
        repo_root=repo,
        frontend_url=soak.FRONTEND_URL,
        room_ids=("conv_00000001", "conv_00000002"),
        artifact_dir=tmp_path / "artifacts",
        timeout_s=10,
        environment={"PATH": "/fake"},
    )

    evidence = soak._default_browser_verify(request, deps)

    assert evidence["refreshes"] == 2
    assert captured["XMUSE_SOAK_BROWSER"] == "1"
    browser_input = json.loads(
        Path(captured["XMUSE_SOAK_BROWSER_INPUT_PATH"]).read_text(encoding="utf-8")
    )
    assert browser_input["room_ids"] == ["conv_00000001", "conv_00000002"]


def test_profile_matrix_is_fixed_and_live_result_has_no_private_fields() -> None:
    assert {
        key: (
            value.room_count,
            value.agents_per_room,
            value.wave_count,
            value.human_turns_per_room,
            value.max_attempts,
            value.minimum_duration_s,
            value.memory_recovery,
        )
        for key, value in soak.LIVE_PROFILES.items()
    } == {
        "live-short": (4, 2, 2, 2, 48, 0.0, False),
        "live-soak": (6, 2, 4, 4, 128, 3600.0, False),
        "memory-recovery": (2, 2, 2, 10, None, 0.0, True),
        soak.ENDURANCE_PROFILE_ID: (8, 2, 5, 5, 192, 7200.0, True),
        soak.GOAL_MEMORY_PROFILE_ID: (4, 2, 4, 4, 128, 3600.0, True),
    }
    source = Path(soak.__file__).read_text(encoding="utf-8")
    assert "provider_output" not in source
    assert soak._safe_result_strings(
        {"schema_version": "room_soak_chaos_result/v1", "status": "passed"},
        (),
    )
    assert soak._safe_result_strings(
        {
            "numeric_usage": {
                "input_tokens": 10,
                "cached_input_tokens": 2,
                "output_tokens": 3,
                "total_tokens": 15,
            }
        },
        (),
    )
    assert not soak._safe_result_strings({"operator_token": "secret"}, ())
    assert not soak._safe_result_strings({"input_tokens": "secret"}, ())


def test_goal_native_continuation_and_peer_wait_are_projection_proven() -> None:
    assert soak._goal_console_turn_request("inspect") == {
        "text": "inspect",
        "mode": "default",
    }
    goal_request = soak._goal_native_request()
    assert goal_request["token_budget"] == 1_000_000
    assert 0 < len(str(goal_request["objective"])) <= 4_000
    native = {
        "native_events": {
            "items": [
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 10},
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 11},
                {"kind": "turn_started", "participant_id": "part-peer", "event_seq": 12},
            ]
        }
    }
    assert soak._goal_turn_started_count(native, "part-goal", 9) == 2
    assert soak._goal_turn_started_count(native, "part-goal", 10) == 1

    room = {
        "turns": [
            {
                "root_activity_id": "activity-root",
                "status": "active",
                "participants": [
                    {
                        "participant_id": "part-goal",
                        "state": "pending",
                        "frontier": {"phase": "root", "attempt_count": 0},
                    },
                    {
                        "participant_id": "part-peer",
                        "state": "respond",
                        "latest_outcome": {"outcome_type": "respond"},
                    },
                ],
            }
        ]
    }
    assert (
        soak._goal_hold_projection_count(
            room,
            root_activity_ids=["activity-root"],
            goal_participant_id="part-goal",
        )
        == 1
    )
    room["turns"][0]["participants"][0]["frontier"]["attempt_count"] = 1
    assert (
        soak._goal_hold_projection_count(
            room,
            root_activity_ids=["activity-root"],
            goal_participant_id="part-goal",
        )
        == 0
    )


def test_goal_hold_projection_waits_for_runner_recovery_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty = {"turns": []}
    ready = {
        "turns": [
            {
                "root_activity_id": "activity-root",
                "status": "active",
                "participants": [
                    {
                        "participant_id": "part-goal",
                        "state": "pending",
                        "frontier": {"phase": "root", "attempt_count": 0},
                    },
                    {
                        "participant_id": "part-peer",
                        "state": "respond",
                        "latest_outcome": {"outcome_type": "respond"},
                    },
                ],
            }
        ]
    }
    projections = iter((empty, ready))
    monkeypatch.setattr(soak, "_room_projection", lambda _deps, _conversation: next(projections))
    clock = [0.0]
    deps = soak.SoakDependencies(
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    assert (
        soak._wait_goal_hold_projection(
            deps,
            "conv-room",
            root_activity_ids=["activity-root"],
            goal_participant_id="part-goal",
            deadline=1.0,
        )
        == 1
    )
    assert clock[0] == pytest.approx(0.25)


def test_goal_peer_delivery_requires_completed_attempt(tmp_path: Path) -> None:
    database = tmp_path / "chat.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """create table room_observations(
                   observation_id text primary key,
                   activity_id text not null,
                   participant_id text not null
               )"""
        )
        connection.execute(
            """create table room_observation_attempts(
                   attempt_id text primary key,
                   observation_id text not null,
                   state text not null
               )"""
        )
        connection.executemany(
            "insert into room_observations values (?,?,?)",
            (
                ("obs-goal", "activity-root", "part-goal"),
                ("obs-peer", "activity-root", "part-peer"),
            ),
        )
        connection.execute(
            "insert into room_observation_attempts values (?,?,?)",
            ("attempt-peer", "obs-peer", "claimed"),
        )
        connection.commit()

    assert (
        soak._other_completed_goal_attempt_count(
            database,
            ["activity-root"],
            "part-goal",
        )
        == 0
    )
    with sqlite3.connect(database) as connection:
        connection.execute(
            "update room_observation_attempts set state = 'completed' where attempt_id = ?",
            ("attempt-peer",),
        )
        connection.commit()
    assert (
        soak._other_completed_goal_attempt_count(
            database,
            ["activity-root"],
            "part-goal",
        )
        == 1
    )


def _goal_progress_projection(
    events: list[dict[str, Any]],
    *,
    status: str | None = "active",
) -> dict[str, Any]:
    projection: dict[str, Any] = {
        "native_events": {"items": events},
        "participants": [],
    }
    if status is not None:
        projection["participants"] = [
            {
                "participant": {"participant_id": "part-goal"},
                "native_snapshot": {
                    "value": {"goal": {"status": status}, "active_turn": status == "active"}
                },
            }
        ]
    return projection


def test_goal_progress_observer_allows_long_first_turn_with_continuous_progress() -> None:
    observer = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    observer.observe(
        _goal_progress_projection(
            [{"kind": "turn_started", "participant_id": "part-goal", "event_seq": 10}]
        ),
        1.0,
    )
    observer.observe(
        _goal_progress_projection(
            [
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 10},
                {
                    "kind": "goal_updated",
                    "status": "active",
                    "participant_id": "part-goal",
                    "event_seq": 11,
                },
                {
                    "kind": "token_usage_updated",
                    "participant_id": "part-goal",
                    "event_seq": 12,
                },
            ]
        ),
        1_000.0,
    )

    assert observer.turn_started_count == 1
    assert observer.continuation_checkpoint_count == 1
    assert observer.last_progress_at == 1_000.0
    assert observer.stop_reason(1_050.0, wall_s=None, idle_s=60.0) is None
    assert observer.stop_reason(100_000.0, wall_s=None, idle_s=None) is None


def test_goal_progress_observer_proves_in_turn_continuation_checkpoint() -> None:
    observer = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    observer.observe(
        _goal_progress_projection(
            [
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 10},
                {
                    "kind": "goal_updated",
                    "status": "active",
                    "participant_id": "part-goal",
                    "event_seq": 13,
                },
            ]
        ),
        10.0,
    )

    assert observer.turn_started_count == 1
    assert observer.continuation_checkpoint_count == 1
    assert observer.stop_reason(10.0, wall_s=1.0, idle_s=1.0) is None


def test_goal_progress_checkpoint_requires_order_and_is_idempotent() -> None:
    observer = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    first = _goal_progress_projection(
        [
            {
                "kind": "goal_updated",
                "status": "active",
                "participant_id": "part-goal",
                "event_seq": 10,
            },
            {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 11},
            {
                "kind": "goal_updated",
                "status": "active",
                "participant_id": "part-peer",
                "event_seq": 12,
            },
        ]
    )
    observer.observe(first, 1.0)
    observer.observe(first, 2.0)
    assert observer.continuation_checkpoint_count == 0

    completed = _goal_progress_projection(
        first["native_events"]["items"]
        + [
            {
                "kind": "goal_updated",
                "status": "active",
                "participant_id": "part-goal",
                "event_seq": 13,
            }
        ]
    )
    observer.observe(completed, 3.0)
    observer.observe(completed, 4.0)
    assert observer.continuation_checkpoint_count == 1


def test_goal_progress_observer_uses_events_while_snapshot_is_missing() -> None:
    observer = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    observer.observe(
        _goal_progress_projection(
            [
                {
                    "kind": "goal_updated",
                    "status": "active",
                    "participant_id": "part-goal",
                    "event_seq": 10,
                },
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 11},
            ],
            status=None,
        ),
        1.0,
    )
    observer.observe(
        _goal_progress_projection(
            [
                {
                    "kind": "token_usage_updated",
                    "participant_id": "part-goal",
                    "event_seq": 12,
                }
            ],
            status=None,
        ),
        121.0,
    )
    observer.observe(
        _goal_progress_projection(
            [
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 13},
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 13},
                {"kind": "turn_started", "participant_id": "part-peer", "event_seq": 14},
            ],
            status=None,
        ),
        181.0,
    )

    assert observer.turn_started_count == 2
    assert observer.last_progress_at == 181.0
    assert observer.stop_reason(181.0, wall_s=None, idle_s=60.0) is None


def test_goal_progress_observer_terminal_event_is_sticky_without_snapshot() -> None:
    observer = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    observer.observe(
        _goal_progress_projection(
            [
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 10},
                {
                    "kind": "goal_updated",
                    "status": "complete",
                    "participant_id": "part-goal",
                    "event_seq": 11,
                },
            ],
            status=None,
        ),
        10.0,
    )
    observer.observe(_goal_progress_projection([], status=None), 11.0)

    assert observer.stop_reason(11.0, wall_s=None, idle_s=None) == (
        "soak_codex_goal_terminal_before_continuation"
    )


def test_goal_progress_terminal_wins_same_poll_as_checkpoint() -> None:
    observer = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    observer.observe(
        _goal_progress_projection(
            [
                {"kind": "turn_started", "participant_id": "part-goal", "event_seq": 10},
                {
                    "kind": "goal_updated",
                    "status": "active",
                    "participant_id": "part-goal",
                    "event_seq": 11,
                },
                {
                    "kind": "goal_updated",
                    "status": "complete",
                    "participant_id": "part-goal",
                    "event_seq": 12,
                },
            ],
            status=None,
        ),
        10.0,
    )

    assert observer.continuation_checkpoint_count == 1
    assert observer.stop_reason(10.0, wall_s=None, idle_s=None) == (
        "soak_codex_goal_terminal_before_continuation"
    )


def test_goal_progress_observer_reports_optional_guard_reasons() -> None:
    wall = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    assert wall.stop_reason(120.0, wall_s=120.0, idle_s=None) == (
        "soak_goal_guard_wall_limit_reached"
    )

    idle = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    idle.observe(
        _goal_progress_projection(
            [{"kind": "goal_updated", "participant_id": "part-goal", "event_seq": 10}]
        ),
        50.0,
    )
    assert idle.stop_reason(111.0, wall_s=None, idle_s=60.0) == (
        "soak_goal_guard_idle_limit_reached"
    )


def test_goal_progress_observer_reports_terminal_before_continuation() -> None:
    observer = soak._GoalContinuationObserver.start("part-goal", 9, 0.0)
    observer.observe(
        _goal_progress_projection(
            [{"kind": "turn_started", "participant_id": "part-goal", "event_seq": 10}],
            status="complete",
        ),
        10.0,
    )

    assert observer.turn_started_count == 1
    assert observer.stop_reason(10.0, wall_s=None, idle_s=None) == (
        "soak_codex_goal_terminal_before_continuation"
    )


def test_goal_guards_are_optional_cli_outer_limits() -> None:
    config = soak.SoakConfig(repo_root=Path("."), profile_id=soak.GOAL_MEMORY_PROFILE_ID)
    assert config.goal_guard_wall_s is None
    assert config.goal_guard_idle_s is None
    args = soak.build_parser().parse_args(
        [
            soak.GOAL_MEMORY_PROFILE_ID,
            "--goal-guard-wall-s",
            "3600",
            "--goal-guard-idle-s",
            "900",
        ]
    )
    assert args.goal_guard_wall_s == 3600.0
    assert args.goal_guard_idle_s == 900.0
    endurance = soak.build_parser().parse_args(
        [
            soak.ENDURANCE_PROFILE_ID,
            "--confirm-provider-cost",
            "--memoryos-executable",
            "/tmp/memoryos",
        ]
    )
    assert endurance.profile == soak.ENDURANCE_PROFILE_ID
    assert endurance.confirm_provider_cost is True


def test_goal_pause_waits_for_paused_thread_to_become_idle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    calls: list[str] = []
    checks: list[tuple[bool, bool, float, str]] = []
    active = {"native_snapshot": {"value": {"goal": {"status": "paused"}, "active_turn": True}}}
    idle = {"native_snapshot": {"value": {"goal": {"status": "paused"}, "active_turn": False}}}

    def invoke(*args: object, **_kwargs: object) -> dict[str, object]:
        calls.append(str(args[4]))
        return {}

    def wait(
        _deps: object,
        _conversation_id: str,
        _participant_id: str,
        predicate: Any,
        *,
        timeout_s: float,
        code: str,
    ) -> Mapping[str, Any]:
        checks.append((predicate(active), predicate(idle), timeout_s, code))
        return idle

    monkeypatch.setattr(soak, "_invoke_native_action", invoke)
    monkeypatch.setattr(soak, "_wait_native_state", wait)
    soak._pause_native_goal(
        soak.SoakConfig(
            repo_root=repo,
            profile_id=soak.GOAL_MEMORY_PROFILE_ID,
            settle_timeout_s=777.0,
        ),
        deps,
        "conv-goal",
        "part-goal",
    )

    assert calls == ["goal_pause"]
    assert checks == [
        (True, True, 30.0, "soak_codex_goal_pause_unproven"),
        (False, True, 777.0, "soak_codex_goal_pause_idle_unproven"),
    ]


def test_goal_pause_interrupts_the_guarded_running_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    calls: list[str] = []
    active = {
        "participant": {"participant_id": "part-goal"},
        "native_snapshot": {"value": {"goal": {"status": "paused"}, "active_turn": True}},
    }
    idle = {
        "participant": {"participant_id": "part-goal"},
        "native_snapshot": {"value": {"goal": {"status": "paused"}, "active_turn": False}},
    }
    waits = iter((active, idle))

    def invoke(*args: object, **_kwargs: object) -> dict[str, object]:
        calls.append(str(args[4]))
        return {}

    monkeypatch.setattr(soak, "_invoke_native_action", invoke)
    monkeypatch.setattr(soak, "_wait_native_state", lambda *_args, **_kwargs: next(waits))

    soak._pause_native_goal(
        soak.SoakConfig(repo_root=repo, profile_id=soak.GOAL_MEMORY_PROFILE_ID),
        deps,
        "conv-goal",
        "part-goal",
    )

    assert calls == ["goal_pause", "turn_interrupt"]


@pytest.mark.parametrize(
    ("guard_kwargs", "expected"),
    [
        ({"goal_guard_wall_s": 1.0}, "soak_goal_guard_wall_limit_reached"),
        ({"goal_guard_idle_s": 1.0}, "soak_goal_guard_idle_limit_reached"),
    ],
)
def test_goal_guard_pauses_through_native_action_before_reporting_limit(
    guard_kwargs: dict[str, float], expected: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    deps = system.dependencies()
    projection = _goal_progress_projection([], status="active")
    calls: list[str] = []
    monkeypatch.setattr(soak, "_codex_projection", lambda *_args: projection)

    def invoke(*_args: object, **_kwargs: object) -> dict[str, object]:
        calls.append(str(_args[4]))
        return _goal_progress_projection(
            [
                {
                    "kind": "goal_updated",
                    "status": "paused",
                    "participant_id": "part-goal",
                    "event_seq": 10,
                }
            ],
            status="paused",
        )

    monkeypatch.setattr(soak, "_invoke_native_action", invoke)
    config = soak.SoakConfig(
        repo_root=repo,
        profile_id=soak.GOAL_MEMORY_PROFILE_ID,
        **guard_kwargs,
    )
    system.clock = 1.0

    with pytest.raises(soak.SoakError, match=expected):
        soak._wait_goal_continuation(config, deps, "conv_goal", "part-goal", 9)

    assert calls == ["goal_pause"]


def test_goal_guard_reports_terminal_race_instead_of_pause_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    system.clock = 1.0
    deps = system.dependencies()
    projections = iter(
        [
            _goal_progress_projection([], status="active"),
            _goal_progress_projection(
                [
                    {
                        "kind": "goal_updated",
                        "status": "complete",
                        "participant_id": "part-goal",
                        "event_seq": 10,
                    }
                ],
                status=None,
            ),
        ]
    )
    monkeypatch.setattr(soak, "_codex_projection", lambda *_args: next(projections))

    def reject(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise soak.SoakError("soak_codex_goal_pause_not_applied")

    monkeypatch.setattr(soak, "_invoke_native_action", reject)
    config = soak.SoakConfig(
        repo_root=repo,
        profile_id=soak.GOAL_MEMORY_PROFILE_ID,
        goal_guard_wall_s=1.0,
    )

    with pytest.raises(soak.SoakError, match="soak_codex_goal_terminal_before_continuation"):
        soak._wait_goal_continuation(config, deps, "conv_goal", "part-goal", 9)


def test_goal_guard_uses_distinct_pause_unconfirmed_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repo(tmp_path)
    system = _FakeSystem(repo)
    system.clock = 1.0
    deps = system.dependencies()
    monkeypatch.setattr(
        soak,
        "_codex_projection",
        lambda *_args: _goal_progress_projection([], status="active"),
    )

    def reject(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise soak.SoakError("soak_codex_goal_pause_not_applied")

    monkeypatch.setattr(soak, "_invoke_native_action", reject)
    config = soak.SoakConfig(
        repo_root=repo,
        profile_id=soak.GOAL_MEMORY_PROFILE_ID,
        goal_guard_wall_s=1.0,
    )

    with pytest.raises(soak.SoakError, match="soak_goal_guard_pause_unconfirmed"):
        soak._wait_goal_continuation(config, deps, "conv_goal", "part-goal", 9)


def test_goal_fault_mapping_requires_exact_reconcile_evidence() -> None:
    events = [
        {
            "kind": kind,
            "reason_code": reason,
            "recovery_ms": 10,
            "active_delivery_count": active,
            "runner_count": 1,
            "mcp_count": 1,
            "managed_reconcile": managed,
            "recovery_wave_settled": True,
        }
        for kind, reason, managed, active in (
            ("codex_app_server_sigkill", "codex_app_server_cleanup_confirmed", False, 1),
            ("runner_sigkill", "runner_reconciled", True, 2),
            ("memoryos_sigkill", "memoryos_reconciled", True, 0),
            ("codex_projection_cache_delete", "codex_projection_cache_rebuilt", True, 0),
        )
    ]
    mapped = soak._map_goal_faults(events)
    assert [item["reason_code"] for item in mapped] == [item["reason_code"] for item in events]
    events[1]["managed_reconcile"] = False
    with pytest.raises(soak.SoakError, match="soak_fault_sequence_invalid"):
        soak._map_goal_faults(events)


def test_goal_browser_item_and_top_digests_are_independently_verified(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    state = soak._LiveState(room_ids=[f"conv_{index:08d}" for index in range(4)])
    viewports: dict[str, dict[str, int | str]] = {}
    for key, (width, height) in {
        "640x900": (640, 900),
        "1280x720": (1280, 720),
        "1440x900": (1440, 900),
    }.items():
        numeric = {
            "width": width,
            "height": height,
            "room_count": 4,
            "refresh_count": 4,
            "console_error_count": 0,
            "page_error_count": 0,
            "http_5xx_count": 0,
            "native_snapshot_count": 8,
            "native_capabilities_count": 8,
            "native_event_count": 32,
            "native_event_kind_count": 4,
            "history_partial_count": 8,
        }
        viewports[key] = {**numeric, "digest": soak._canonical_digest_json(numeric)}
    payload = {
        "schema_version": soak.GOAL_BROWSER_EVIDENCE_SCHEMA,
        "consumer": soak.GOAL_BROWSER_CONSUMER,
        "headed": True,
        "viewports": viewports,
        "digest": soak._canonical_digest_json(
            {"consumer": soak.GOAL_BROWSER_CONSUMER, "headed": True, "viewports": viewports}
        ),
    }
    deps = _FakeSystem(repo).dependencies()
    deps.browser_verifier = lambda _request: payload
    config = soak.SoakConfig(profile_id=soak.GOAL_MEMORY_PROFILE_ID, repo_root=repo)
    result = soak._verify_goal_browser(config, deps, state, tmp_path, {})
    assert result["headed"] is True
    viewports["640x900"]["refresh_count"] = 3
    with pytest.raises(soak.SoakError, match="soak_browser_evidence_invalid"):
        soak._verify_goal_browser(config, deps, state, tmp_path, {})


def test_real_browser_spec_is_explicit_and_emits_counts_only() -> None:
    project = Path(__file__).resolve().parents[2]
    source = (project / "frontend" / "e2e" / "room-soak-real.spec.ts").read_text(encoding="utf-8")

    assert 'process.env.XMUSE_SOAK_BROWSER === "1"' in source
    assert "XMUSE_OPERATOR_TOKEN" not in source
    evidence_start = source.index("async function updateEvidence")
    evidence_block = source[evidence_start : source.index("\ntest", evidence_start)]
    assert "room_ids" not in evidence_block
    assert "viewports" in evidence_block
    assert "digest" in evidence_block
