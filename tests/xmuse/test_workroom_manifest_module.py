from __future__ import annotations

import json
from pathlib import Path

import pytest

from xmuse import workroom_manifest


def _manifest(generation: str = "gen-1") -> dict[str, object]:
    return {
        "schema_version": workroom_manifest.SCHEMA_VERSION,
        "generation": generation,
        "state": "ready",
        "updated_at": "old",
    }


def test_read_missing_manifest_has_no_write_side_effect(tmp_path: Path) -> None:
    root = tmp_path / "missing-root"
    assert workroom_manifest.read_manifest(root / "workroom-runtime.json") is None
    assert not root.exists()


def test_atomic_manifest_round_trip_and_invalid_schema(tmp_path: Path) -> None:
    path = tmp_path / "workroom-runtime.json"
    payload = _manifest()
    workroom_manifest.atomic_write_manifest(path, payload)

    assert workroom_manifest.read_manifest(path) == payload
    assert list(tmp_path.glob(".workroom-runtime.json.*.tmp")) == []

    path.write_text(json.dumps({"schema_version": "future"}), encoding="utf-8")
    with pytest.raises(workroom_manifest.ManifestError) as error:
        workroom_manifest.read_manifest(path)
    assert error.value.code == "invalid_manifest"


def test_base_and_update_manifest_are_value_builders(tmp_path: Path) -> None:
    profile = {"schema_version": "room_execution_gate_profile/v1", "id": "docs/v1"}
    manifest = workroom_manifest.base_manifest(
        generation="gen-1",
        version="1.2.3",
        started_at="2026-07-13T00:00:00Z",
        repo_root=tmp_path / "repo",
        xmuse_root=tmp_path / "runtime",
        manager_pid=42,
        manager_start_identity="start-42",
        runner_pid_file=tmp_path / "runner.pid",
        mcp_pid_file=tmp_path / "mcp.pid",
        runner_status_file=tmp_path / "runner-status.json",
        execution_workspace=tmp_path / "workspace",
        execution_gate_profile=profile,
        memory_enabled=True,
    )
    profile["id"] = "mutated"
    updated = workroom_manifest.update_manifest(
        manifest, updated_at="2026-07-13T00:00:01Z", state="ready"
    )

    assert manifest["state"] == "starting"
    assert manifest["updated_at"] == "2026-07-13T00:00:00Z"
    assert updated["state"] == "ready"
    assert updated["execution"]["gate_profile"]["id"] == "docs/v1"  # type: ignore[index]


def test_generation_guard_never_overwrites_new_owner(tmp_path: Path) -> None:
    path = tmp_path / "workroom-runtime.json"
    newer = _manifest("gen-2")
    workroom_manifest.atomic_write_manifest(path, newer)

    assert (
        workroom_manifest.write_if_generation_current(
            path,
            _manifest("gen-1"),
            state="failed",
            updated_at="2026-07-13T00:00:00Z",
        )
        is None
    )
    assert workroom_manifest.read_manifest(path) == newer

    written = workroom_manifest.write_if_generation_current(
        path,
        newer,
        state="stopped",
        updated_at="2026-07-13T00:00:01Z",
        terminal_at="2026-07-13T00:00:02Z",
    )
    assert written is not None
    assert written["stopped_at"] == "2026-07-13T00:00:02Z"
    assert workroom_manifest.read_manifest(path) == written
