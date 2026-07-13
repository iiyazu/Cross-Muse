from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from xmuse.workroom_memoryos import (
    MemoryOSRuntimeControl,
    control_gate,
    defer_memoryos_for_unknown_port,
    generation_is_current,
    mark_memoryos_healthy,
    memoryos_record_for_identity,
    prepare_memoryos_spawn,
    schedule_memoryos_recovery,
    set_memoryos_rebuilding,
)
from xmuse.workroom_processes import ProcessIdentity


@dataclass
class FakeProcess:
    pid: int
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


def _control(tmp_path: Path) -> MemoryOSRuntimeControl:
    return MemoryOSRuntimeControl(
        executable=tmp_path / "memoryos",
        api_key="server-only-secret",
        url="http://127.0.0.1:8100",
    )


def test_control_repr_never_persists_or_exposes_api_key(tmp_path: Path) -> None:
    control = _control(tmp_path)

    assert "server-only-secret" not in repr(control)
    assert control.process is None
    assert control.record is None


def test_generation_guard_requires_current_nonterminal_manifest() -> None:
    assert generation_is_current(
        expected_generation="g1",
        current_manifest={"generation": "g1", "state": "ready"},
    )
    for manifest in (
        None,
        {"generation": "g2", "state": "ready"},
        {"generation": "g1", "state": "stopping"},
        {"generation": "g1", "state": "stopped"},
        {"generation": "g1", "state": "failed"},
    ):
        assert not generation_is_current(
            expected_generation="g1",
            current_manifest=manifest,
        )


def test_recovery_uses_bounded_backoff_and_crash_loop_code(tmp_path: Path) -> None:
    control = _control(tmp_path)
    expected_delays = [1, 2, 4, 8, 16, 30, 30]

    for attempt, delay in enumerate(expected_delays, start=1):
        decision = schedule_memoryos_recovery(
            control,
            code="memoryos_process_exited",
            monotonic_now=100.0,
            wall_time_now="2026-07-13T00:00:00Z",
        )
        assert control.next_retry_monotonic == 100.0 + delay
        assert control.next_retry_at == f"2026-07-13T00:00:{delay:02d}Z"
        assert decision.state == "recovering"
        assert decision.code == (
            "memoryos_crash_loop" if attempt >= 6 else "memoryos_process_exited"
        )


def test_unknown_port_defers_without_forgetting_process_identity(tmp_path: Path) -> None:
    control = _control(tmp_path)
    process = FakeProcess(41)
    record = {"pid": 41, "start_identity": "start:41"}
    control.process = process
    control.record = record

    decision = defer_memoryos_for_unknown_port(
        control,
        monotonic_now=10.0,
        wall_time_now="2026-07-13T00:00:00Z",
    )

    assert decision.state == "degraded"
    assert decision.code == "memoryos_port_in_use"
    assert control.next_retry_monotonic == 15.0
    assert control.process is process
    assert control.record is record


def test_memoryos_record_requires_exact_shared_identity_proof(tmp_path: Path) -> None:
    process = FakeProcess(41)
    environment = {
        "XMUSE_ROOT": str(tmp_path),
        "XMUSE_WORKROOM_GENERATION": "g1",
        "XMUSE_WORKROOM_SERVICE": "memoryos",
    }
    identity = ProcessIdentity(
        start_identity="linux-proc-starttime:41",
        pgid=41,
        environment=environment,
    )

    record = memoryos_record_for_identity(
        process,
        identity,
        generation="g1",
        xmuse_root=tmp_path,
    )
    assert record == {
        "service": "memoryos",
        "pid": 41,
        "pgid": 41,
        "start_identity": "linux-proc-starttime:41",
        "generation": "g1",
        "host": "127.0.0.1",
        "port": 8301,
        "log_path": str(tmp_path / "logs" / "workroom-memoryos.log"),
    }

    for key, value in (
        ("XMUSE_ROOT", str(tmp_path / "other")),
        ("XMUSE_WORKROOM_GENERATION", "g2"),
        ("XMUSE_WORKROOM_SERVICE", "chat_api"),
    ):
        wrong = ProcessIdentity(
            start_identity=identity.start_identity,
            pgid=identity.pgid,
            environment={**environment, key: value},
        )
        assert (
            memoryos_record_for_identity(
                process,
                wrong,
                generation="g1",
                xmuse_root=tmp_path,
            )
            is None
        )


def test_rebuild_and_retry_gates_are_single_step_and_side_effect_bounded(
    tmp_path: Path,
) -> None:
    control = _control(tmp_path)
    control.consecutive_restart_count = 3
    control.next_retry_monotonic = 20.0
    control.retry_state = "recovering"
    control.retry_code = "memoryos_process_exited"

    waiting = control_gate(control, monotonic_now=10.0)
    assert waiting is not None and waiting.code == "memoryos_process_exited"
    assert control_gate(control, monotonic_now=20.0) is None

    set_memoryos_rebuilding(control, True)
    rebuilding = control_gate(control, monotonic_now=20.0)
    assert rebuilding is not None and rebuilding.state == "rebuilding"
    assert control.next_retry_monotonic is None

    control.rebuild_blocked_code = "memoryos_derived_cache_unsafe"
    blocked = control_gate(control, monotonic_now=20.0)
    assert blocked is not None and blocked.code == "memoryos_derived_cache_unsafe"


def test_spawn_and_healthy_steps_preserve_sixty_second_reset(tmp_path: Path) -> None:
    control = _control(tmp_path)
    control.consecutive_restart_count = 2
    control.next_retry_monotonic = 5.0
    control.next_retry_at = "later"

    spawning = prepare_memoryos_spawn(
        control,
        started_at="2026-07-13T00:00:00Z",
    )
    assert spawning.state == "recovering"
    assert control.next_retry_monotonic is None
    assert control.next_retry_at is None

    assert (
        mark_memoryos_healthy(
            control,
            monotonic_now=100.0,
            wall_time_now="2026-07-13T00:00:01Z",
        ).state
        == "ready"
    )
    assert control.consecutive_restart_count == 2
    mark_memoryos_healthy(
        control,
        monotonic_now=159.9,
        wall_time_now="2026-07-13T00:01:00Z",
    )
    assert control.consecutive_restart_count == 2
    mark_memoryos_healthy(
        control,
        monotonic_now=160.0,
        wall_time_now="2026-07-13T00:01:01Z",
    )
    assert control.consecutive_restart_count == 0
