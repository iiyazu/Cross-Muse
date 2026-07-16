from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from xmuse_core.chat.memoryos_supervisor import (
    MEMORYOS_DERIVED_RELATIVE,
    MEMORYOS_RUNTIME_SCHEMA,
    MemoryOSSupervisorError,
    browser_memoryos_status,
    memoryos_child_environment,
    memoryos_command,
    read_memoryos_status,
    resolve_memoryos_executable,
    safe_memoryos_status,
    write_memoryos_status,
)


def _stamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def test_sidecar_environment_is_fixed_offline_and_drops_ambient_secrets(
    tmp_path: Path,
) -> None:
    environment = memoryos_child_environment(
        {
            "PATH": "/safe/bin",
            "HOME": "/safe/home",
            "OPENAI_API_KEY": "provider-secret",
            "DEEPSEEK_API_KEY": "provider-secret",
            "QDRANT_URL": "http://remote.invalid",
            "HTTP_PROXY": "http://proxy.invalid",
            "HTTPS_PROXY": "http://proxy.invalid",
            "ALL_PROXY": "http://proxy.invalid",
            "XMUSE_OPERATOR_TOKEN": "operator-secret",
            "KEEP": "not-allowlisted",
        },
        xmuse_root=tmp_path,
        generation="generation-1",
        api_key="memory-server-key",
    )

    assert environment["DATA_DIR"] == str(tmp_path / MEMORYOS_DERIVED_RELATIVE)
    assert environment["MEMORYOS_MEMORY_ARCH"] == "v3"
    assert environment["MEMORYOS_RECALL_PIPELINE"] == "v2"
    assert environment["MEMORYOS_AGENT_KERNEL"] == "off"
    assert environment["MEMORYOS_PAGING_MODE"] == "off"
    assert environment["MEMORYOS_ITEM_EXTRACTION"] == "false"
    assert environment["MEMORYOS_REWRITE_ENABLED"] == "false"
    assert environment["MEMORYOS_RERANK_ENABLED"] == "false"
    assert environment["MEMORYOS_ARCHIVAL_VECTOR_ENABLED"] == "false"
    assert environment["MEMORYOS_API_KEY"] == "memory-server-key"
    for forbidden in (
        "OPENAI_API_KEY",
        "DEEPSEEK_API_KEY",
        "QDRANT_URL",
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "XMUSE_OPERATOR_TOKEN",
        "KEEP",
    ):
        assert forbidden not in environment


def test_full_local_sidecar_selects_offline_hybrid_and_external_governance(
    tmp_path: Path,
) -> None:
    environment = memoryos_child_environment(
        {},
        xmuse_root=tmp_path,
        generation="generation-full-local",
        api_key="memory-server-key",
        profile="full-local",
    )

    assert environment["MEMORYOS_AGENT_KERNEL"] == "external"
    assert environment["MEMORYOS_ITEM_EXTRACTION"] == "true"
    assert environment["MEMORYOS_PAGING_MODE"] == "heuristic"
    assert environment["MEMORYOS_EMBEDDING_PROVIDER"] == "fastembed"
    assert environment["MEMORYOS_FASTEMBED_OFFLINE"] == "1"
    assert environment["HF_HUB_OFFLINE"] == "1"
    assert environment["TRANSFORMERS_OFFLINE"] == "1"


def test_executable_and_command_are_fixed_loopback_without_api_key(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "memoryos"
    executable.write_text("#!/bin/sh\n", encoding="utf-8")
    executable.chmod(0o700)

    resolved = resolve_memoryos_executable(executable)
    command = memoryos_command(resolved)

    assert command == (
        str(resolved),
        "api",
        "--host",
        "127.0.0.1",
        "--port",
        "8301",
    )
    assert "memory-server-key" not in " ".join(command)
    link = tmp_path / "memoryos-link"
    link.symlink_to(executable)
    with pytest.raises(MemoryOSSupervisorError) as exc_info:
        resolve_memoryos_executable(link)
    assert exc_info.value.code == "memoryos_executable_invalid"


def test_browser_status_distinguishes_disabled_invalid_and_stale_receipts(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 7, 12, 12, 0, tzinfo=UTC)
    assert browser_memoryos_status(tmp_path, now=now) == safe_memoryos_status(None)

    path = tmp_path / "memoryos-status.json"
    path.write_text("not-json", encoding="utf-8")
    invalid = browser_memoryos_status(tmp_path, now=now)
    assert invalid == {
        "schema_version": MEMORYOS_RUNTIME_SCHEMA,
        "enabled": True,
        "state": "degraded",
        "code": "memoryos_receipt_invalid",
        "heartbeat_at": None,
        "started_at": None,
    }

    write_memoryos_status(
        tmp_path,
        enabled=True,
        state="ready",
        code="ready",
        generation="generation-1",
        pid=123,
        start_identity="linux-proc-starttime:123",
        started_at=_stamp(now - timedelta(minutes=1)),
        heartbeat_at=_stamp(now - timedelta(seconds=21)),
    )
    stale = browser_memoryos_status(tmp_path, now=now)
    assert stale["state"] == "degraded"
    assert stale["code"] == "memoryos_heartbeat_stale"
    assert "pid" not in stale
    assert "generation" not in stale
    assert "start_identity" not in stale


def test_status_receipt_is_private_and_safe_view_never_exposes_identity(
    tmp_path: Path,
) -> None:
    write_memoryos_status(
        tmp_path,
        enabled=True,
        state="ready",
        code="ready",
        generation="generation-secret",
        pid=321,
        start_identity="linux-proc-starttime:321",
        started_at="2026-07-12T12:00:00Z",
        heartbeat_at="2026-07-12T12:00:01Z",
    )
    receipt = read_memoryos_status(tmp_path)
    assert receipt is not None
    assert receipt["pid"] == 321
    assert (tmp_path / "memoryos-status.json").stat().st_mode & 0o777 == 0o600
    safe = safe_memoryos_status(receipt)
    serialized = json.dumps(safe)
    assert "generation-secret" not in serialized
    assert "linux-proc" not in serialized
    assert "321" not in serialized
    assert "pid" not in safe
    assert str(tmp_path) not in serialized
