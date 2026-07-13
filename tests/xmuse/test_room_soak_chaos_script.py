from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping, Sequence
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

    assert selected == ("attempt_live", "god_beta", beta)


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
    }
    source = Path(soak.__file__).read_text(encoding="utf-8")
    assert "provider_output" not in source
    assert soak._safe_result_strings(
        {"schema_version": "room_soak_chaos_result/v1", "status": "passed"},
        (),
    )
    assert not soak._safe_result_strings({"operator_token": "secret"}, ())


def test_real_browser_spec_is_explicit_and_emits_counts_only() -> None:
    project = Path(__file__).resolve().parents[2]
    source = (project / "frontend" / "e2e" / "room-soak-real.spec.ts").read_text(encoding="utf-8")

    assert 'process.env.XMUSE_SOAK_BROWSER === "1"' in source
    assert "XMUSE_OPERATOR_TOKEN" not in source
    evidence_block = source[source.index("await atomicJson(evidencePath") :]
    assert "room_ids" not in evidence_block
    assert "console_errors" in evidence_block
    assert "page_errors" in evidence_block
