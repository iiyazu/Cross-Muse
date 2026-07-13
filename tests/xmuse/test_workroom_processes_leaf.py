from __future__ import annotations

import signal
from dataclasses import dataclass
from pathlib import Path

import pytest

from xmuse.workroom_processes import (
    ProcessIdentity,
    ProcessLifecycleError,
    record_process,
    service_is_live,
    stop_service_record,
    stop_spawned_processes,
)


@dataclass
class FakeProcess:
    pid: int
    returncode: int | None = None

    def poll(self) -> int | None:
        return self.returncode


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += seconds


def _identity(root: Path, *, generation: str = "g1", service: str = "chat_api") -> ProcessIdentity:
    return ProcessIdentity(
        start_identity="linux-proc-starttime:42",
        pgid=42,
        environment={
            "XMUSE_ROOT": str(root),
            "XMUSE_WORKROOM_GENERATION": generation,
            "XMUSE_WORKROOM_SERVICE": service,
        },
    )


def test_record_process_requires_exact_generation_root_and_service(tmp_path: Path) -> None:
    clock = FakeClock()
    process = FakeProcess(42)
    identity = _identity(tmp_path)

    record = record_process(
        process,
        service="chat_api",
        generation="g1",
        host="127.0.0.1",
        port=8201,
        url="http://127.0.0.1:8201/health",
        log_path=tmp_path / "chat.log",
        xmuse_root=tmp_path,
        inspector=lambda _pid: identity,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert record == {
        "service": "chat_api",
        "pid": 42,
        "pgid": 42,
        "start_identity": "linux-proc-starttime:42",
        "generation": "g1",
        "host": "127.0.0.1",
        "port": 8201,
        "url": "http://127.0.0.1:8201/health",
        "log_path": str(tmp_path / "chat.log"),
    }
    assert service_is_live(
        record,
        generation="g1",
        xmuse_root=tmp_path,
        inspector=lambda _pid: identity,
    )


@pytest.mark.parametrize("wrong_field", ["root", "generation", "service", "start"])
def test_service_identity_guard_fails_closed(tmp_path: Path, wrong_field: str) -> None:
    record = {
        "service": "chat_api",
        "pid": 42,
        "pgid": 42,
        "start_identity": "linux-proc-starttime:42",
    }
    identity = _identity(
        tmp_path if wrong_field != "root" else tmp_path / "other",
        generation="g1" if wrong_field != "generation" else "g2",
        service="chat_api" if wrong_field != "service" else "frontend",
    )
    if wrong_field == "start":
        identity = ProcessIdentity(
            start_identity="linux-proc-starttime:other",
            pgid=42,
            environment=identity.environment,
        )

    assert not service_is_live(
        record,
        generation="g1",
        xmuse_root=tmp_path,
        inspector=lambda _pid: identity,
    )


def test_record_process_preserves_timeout_and_exit_errors(tmp_path: Path) -> None:
    clock = FakeClock()
    process = FakeProcess(42)
    kwargs = {
        "service": "chat_api",
        "generation": "g1",
        "host": "127.0.0.1",
        "port": 8201,
        "url": "http://127.0.0.1:8201/health",
        "log_path": tmp_path / "chat.log",
        "xmuse_root": tmp_path,
        "inspector": lambda _pid: None,
        "monotonic": clock.monotonic,
        "sleep": clock.sleep,
        "timeout_s": 0.1,
    }
    with pytest.raises(ProcessLifecycleError, match="could not establish") as timeout:
        record_process(process, **kwargs)
    assert timeout.value.code == "process_identity_timeout"

    process.returncode = 1
    with pytest.raises(ProcessLifecycleError, match="exited before") as exited:
        record_process(process, **kwargs)
    assert exited.value.code == "service_exited"


def test_stop_never_signals_unverified_record(tmp_path: Path) -> None:
    signals: list[tuple[int, int]] = []
    clock = FakeClock()
    record = {
        "service": "chat_api",
        "pid": 42,
        "pgid": 42,
        "start_identity": "linux-proc-starttime:42",
    }

    assert stop_service_record(
        record,
        generation="g1",
        xmuse_root=tmp_path,
        inspector=lambda _pid: _identity(tmp_path, generation="other"),
        signal_group=lambda pgid, signum: signals.append((pgid, signum)),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        timeout_s=0.1,
    )
    assert signals == []


def test_stop_escalates_only_while_exact_identity_remains_live(tmp_path: Path) -> None:
    signals: list[tuple[int, int]] = []
    clock = FakeClock()
    live = True
    record = {
        "service": "chat_api",
        "pid": 42,
        "pgid": 42,
        "start_identity": "linux-proc-starttime:42",
    }

    def inspector(_pid: int) -> ProcessIdentity | None:
        return _identity(tmp_path) if live else None

    def send(_pgid: int, signum: int) -> None:
        nonlocal live
        signals.append((_pgid, signum))
        if signum == signal.SIGKILL:
            live = False

    assert stop_service_record(
        record,
        generation="g1",
        xmuse_root=tmp_path,
        inspector=inspector,
        signal_group=send,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        timeout_s=0.1,
    )
    assert signals == [(42, signal.SIGTERM), (42, signal.SIGKILL)]


def test_cleanup_of_unrecorded_children_keeps_reverse_order_and_timeout() -> None:
    clock = FakeClock()
    processes = [FakeProcess(1), FakeProcess(2)]
    signals: list[tuple[int, int]] = []

    def send(pid: int, signum: int) -> None:
        signals.append((pid, signum))
        if signum == signal.SIGKILL:
            next(process for process in processes if process.pid == pid).returncode = -signum

    stop_spawned_processes(
        processes,
        signal_group=send,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        timeout_s=0.1,
    )

    assert signals == [
        (2, signal.SIGTERM),
        (2, signal.SIGKILL),
        (1, signal.SIGTERM),
        (1, signal.SIGKILL),
    ]
