from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse_core.chat.memoryos_supervisor import (
    MEMORYOS_RESTART_BACKOFF_S,
    MEMORYOS_RUNTIME_SCHEMA,
    MemoryOSSupervisorError,
    clear_memoryos_derived_cache,
    memoryos_incident_guard,
    memoryos_rebuildability,
    memoryos_restart_backoff_seconds,
    prepare_memoryos_derived_cache,
    read_memoryos_status,
    safe_memoryos_status,
    write_memoryos_status,
)


def test_v2_receipt_reads_v1_and_exposes_only_safe_recovery_fields(tmp_path: Path) -> None:
    legacy = {
        "schema_version": "xmuse_memoryos_runtime/v1",
        "enabled": True,
        "state": "degraded",
        "code": "memoryos_health_unavailable",
        "generation": "generation-secret",
        "pid": 123,
        "start_identity": "linux-proc-starttime:123",
        "started_at": "2026-07-12T00:00:00Z",
        "heartbeat_at": "2026-07-12T00:00:01Z",
    }
    (tmp_path / "memoryos-status.json").write_text(json.dumps(legacy), encoding="utf-8")

    normalized = read_memoryos_status(tmp_path)
    assert normalized is not None
    assert normalized["schema_version"] == MEMORYOS_RUNTIME_SCHEMA
    assert normalized["consecutive_restart_count"] == 0
    assert normalized["next_retry_at"] is None
    assert normalized["last_healthy_at"] is None

    receipt = write_memoryos_status(
        tmp_path,
        enabled=True,
        state="recovering",
        code="memoryos_process_exited",
        generation="generation-secret",
        pid=321,
        start_identity="linux-proc-starttime:321",
        started_at="2026-07-12T00:00:00Z",
        heartbeat_at="2026-07-12T00:00:02Z",
        consecutive_restart_count=3,
        next_retry_at="2026-07-12T00:00:06Z",
        last_healthy_at="2026-07-12T00:00:01Z",
    )
    safe = safe_memoryos_status(receipt)
    assert safe == {
        "schema_version": MEMORYOS_RUNTIME_SCHEMA,
        "enabled": True,
        "state": "recovering",
        "code": "memoryos_process_exited",
        "profile": "archive-only",
        "heartbeat_at": "2026-07-12T00:00:02Z",
        "started_at": "2026-07-12T00:00:00Z",
        "consecutive_restart_count": 3,
        "next_retry_at": "2026-07-12T00:00:06Z",
        "last_healthy_at": "2026-07-12T00:00:01Z",
    }
    serialized = json.dumps(safe)
    assert "generation-secret" not in serialized
    assert "linux-proc" not in serialized
    assert "321" not in serialized


def test_restart_backoff_is_fixed_bounded_and_rejects_invalid_counts() -> None:
    assert MEMORYOS_RESTART_BACKOFF_S == (1, 2, 4, 8, 16, 30)
    assert [memoryos_restart_backoff_seconds(index) for index in range(1, 9)] == [
        1,
        2,
        4,
        8,
        16,
        30,
        30,
        30,
    ]
    for value in (0, -1, True):
        with pytest.raises(MemoryOSSupervisorError) as exc_info:
            memoryos_restart_backoff_seconds(value)
        assert exc_info.value.code == "memoryos_restart_count_invalid"


def test_rebuildability_uses_strict_codes_and_opaque_guard() -> None:
    payload = {
        "schema_version": MEMORYOS_RUNTIME_SCHEMA,
        "enabled": True,
        "state": "recovering",
        "code": "memoryos_crash_loop",
        "generation": "private-generation",
        "pid": 42,
        "start_identity": "private-start",
        "consecutive_restart_count": 6,
        "next_retry_at": "2026-07-12T00:00:30Z",
    }
    first = memoryos_rebuildability(payload)
    assert first["available"] is True
    assert first["reason_code"] == "memoryos_crash_loop"
    assert first["incident_id"] == memoryos_incident_guard(payload)
    assert "private" not in str(first["incident_id"])
    assert memoryos_rebuildability({**payload, "code": "memoryos_health_unavailable"}) == {
        "available": False,
        "reason_code": "memoryos_rebuild_not_available",
        "incident_id": None,
    }


def test_fixed_cache_clear_unlinks_nested_symlinks_without_following_them(
    tmp_path: Path,
) -> None:
    target = tmp_path / "runtime" / "memoryos-derived"
    target.mkdir(parents=True)
    (target / "memoryos.db").write_bytes(b"derived")
    nested = target / "nested"
    nested.mkdir()
    (nested / "index.bin").write_bytes(b"index")
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("preserve", encoding="utf-8")
    (target / "sentinel-link").symlink_to(sentinel)

    assert clear_memoryos_derived_cache(tmp_path) is True
    assert not target.exists()
    assert sentinel.read_text(encoding="utf-8") == "preserve"
    assert clear_memoryos_derived_cache(tmp_path) is False

    unsafe_runtime = tmp_path / "unsafe-root"
    unsafe_runtime.mkdir()
    (unsafe_runtime / "runtime").symlink_to(tmp_path / "runtime", target_is_directory=True)
    with pytest.raises(MemoryOSSupervisorError) as exc_info:
        clear_memoryos_derived_cache(unsafe_runtime)
    assert exc_info.value.code == "memoryos_derived_cache_unsafe"

    unsafe_target = tmp_path / "unsafe-target"
    (unsafe_target / "runtime").mkdir(parents=True)
    (unsafe_target / "runtime" / "memoryos-derived").symlink_to(
        tmp_path / "runtime", target_is_directory=True
    )
    with pytest.raises(MemoryOSSupervisorError) as target_error:
        clear_memoryos_derived_cache(unsafe_target)
    assert target_error.value.code == "memoryos_derived_cache_unsafe"


def test_fixed_cache_prepare_is_no_follow_and_private(tmp_path: Path) -> None:
    (tmp_path / "runtime").mkdir()

    prepared = prepare_memoryos_derived_cache(tmp_path)

    assert prepared == tmp_path / "runtime" / "memoryos-derived"
    assert prepared.is_dir()
    assert prepared.stat().st_mode & 0o777 == 0o700

    prepared.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    prepared.symlink_to(outside, target_is_directory=True)
    with pytest.raises(MemoryOSSupervisorError) as error:
        prepare_memoryos_derived_cache(tmp_path)
    assert error.value.code == "memoryos_derived_cache_unsafe"
