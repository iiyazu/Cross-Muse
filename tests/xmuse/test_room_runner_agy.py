"""Antigravity transport selection (agy CLI default, agentapi opt-in)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

from xmuse import room_runner, room_runner_composition, room_runner_memory
from xmuse_core.chat.room_agy_transport import AgyRoomObservationTransport
from xmuse_core.chat.room_antigravity_transport import AntigravityTransportConfig
from xmuse_core.chat.room_controls import RoomObservationControlStore
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_review_store import RoomExecutionReviewStore
from xmuse_core.chat.room_skill_decisions import RoomAttemptSkillDecisionStore
from xmuse_core.skills.catalog import SkillCatalog


def test_antigravity_transport_defaults_to_cli() -> None:
    assert room_runner._resolve_antigravity_transport_name({}) == "cli"
    assert (
        room_runner._resolve_antigravity_transport_name({"XMUSE_ANTIGRAVITY_TRANSPORT": ""})
        == "cli"
    )
    assert (
        room_runner._resolve_antigravity_transport_name({"XMUSE_ANTIGRAVITY_TRANSPORT": "cli"})
        == "cli"
    )
    assert (
        room_runner._resolve_antigravity_transport_name({"XMUSE_ANTIGRAVITY_TRANSPORT": "agentapi"})
        == "agentapi"
    )


def test_antigravity_transport_rejects_unknown_names() -> None:
    with pytest.raises(room_runner.RoomRunnerError) as exc_info:
        room_runner._resolve_antigravity_transport_name({"XMUSE_ANTIGRAVITY_TRANSPORT": "grpc"})
    assert exc_info.value.code == "room_runner_antigravity_transport_invalid"


def _agy_files(tmp_path: Path) -> tuple[Path, Path]:
    agy = tmp_path / "agy"
    agy.write_text("#!/bin/sh\n")
    home_python = tmp_path / "home" / "bin" / "python3"
    home_python.parent.mkdir(parents=True)
    home_python.write_text("#!/bin/sh\n")
    return agy, home_python


def _which(names: dict[str, str]) -> Any:
    def _resolve(command: str) -> str | None:
        return names.get(command)

    return _resolve


def test_resolve_agy_paths_prefers_the_explicit_command(tmp_path: Path) -> None:
    agy, _ = _agy_files(tmp_path)
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\n")
    home = tmp_path / "home"
    environ = {
        "XMUSE_AGY_COMMAND": str(agy),
        "XMUSE_AGY_MODEL": "gemini-3.8-flash-high",
        "HOME": str(home),
    }
    resolved, model, bridge, python3 = room_runner._resolve_agy_paths(
        environ=environ,
        executable_resolver=_which({"bwrap": str(bwrap), "python3": "/usr/bin/python3"}),
    )
    assert resolved == agy
    assert model == "gemini-3.8-flash-high"
    assert bridge == Path(room_runner.__file__).resolve().parent / "room_mcp_stdio.py"
    assert bridge.is_file()
    assert python3 == Path("/usr/bin/python3").resolve()


def test_resolve_agy_paths_falls_back_to_path_and_default_model(tmp_path: Path) -> None:
    agy, _ = _agy_files(tmp_path)
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\n")
    environ = {"HOME": str(tmp_path / "home")}
    resolved, model, _bridge, _python3 = room_runner._resolve_agy_paths(
        environ=environ,
        executable_resolver=_which(
            {"agy": str(agy), "bwrap": str(bwrap), "python3": "/usr/bin/python3"}
        ),
    )
    assert resolved == agy
    assert model == "gemini-3.8-flash-high"


def test_resolve_agy_paths_fails_closed(tmp_path: Path) -> None:
    agy, home_python = _agy_files(tmp_path)
    bwrap = tmp_path / "bwrap"
    bwrap.write_text("#!/bin/sh\n")
    home = tmp_path / "home"
    base = {"HOME": str(home), "XMUSE_AGY_COMMAND": str(agy)}
    with pytest.raises(room_runner.RoomRunnerError) as exc_info:
        room_runner._resolve_agy_paths(
            environ=dict(base),
            executable_resolver=_which({"python3": "/usr/bin/python3"}),
        )
    assert exc_info.value.code == "room_runner_agy_sandbox_unavailable"
    with pytest.raises(room_runner.RoomRunnerError) as exc_info:
        room_runner._resolve_agy_paths(
            environ={"HOME": str(home)},
            executable_resolver=_which({}),
        )
    assert exc_info.value.code == "room_runner_agy_executable_unavailable"
    with pytest.raises(room_runner.RoomRunnerError) as exc_info:
        room_runner._resolve_agy_paths(
            environ=dict(base),
            executable_resolver=_which({"bwrap": str(bwrap), "python3": str(home_python)}),
        )
    assert exc_info.value.code == "room_runner_agy_python_unavailable"


def test_agy_config_builds_a_read_only_resumable_route(tmp_path: Path) -> None:
    agy = tmp_path / "agy"
    agy.write_text("#!/bin/sh\n")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    config = room_runner._agy_config(
        root=tmp_path,
        worktree=worktree,
        room_mcp_url="http://127.0.0.1:8100/mcp/room",
        agy_executable=agy,
        model="gemini-3.8-flash-high",
        bridge_script=Path(room_runner.__file__).resolve().parent / "room_mcp_stdio.py",
        python3=Path("/usr/bin/python3"),
        environ={"HOME": str(tmp_path), "XMUSE_OPENCODE_BWRAP": "/usr/sbin/bwrap"},
    )
    assert config.confinement == "os_read_only_sandbox"
    assert config.owner is False
    fresh = config.command_builder(None)
    assert "--conversation" not in fresh
    assert fresh[-1] == "-p="
    assert str(worktree.resolve()) in fresh
    assert str(tmp_path.resolve()) in fresh
    resumed = config.command_builder("conv-1")
    assert resumed[resumed.index("--conversation") + 1] == "conv-1"
    assert resumed[-1] == "-p="


def _composition_common(tmp_path: Path, name: str) -> dict[str, Any]:
    db_path = tmp_path / "chat.db"
    RoomDatabase(db_path).initialize()
    memory = room_runner_memory.compose_room_runner_memory(
        db_path,
        worker_id=f"memory-{name}",
        environ={},
    )
    return {
        "root": tmp_path,
        "worktree": tmp_path,
        "launchers": {},
        "controls": RoomObservationControlStore(db_path),
        "skill_decisions": RoomAttemptSkillDecisionStore(db_path),
        "skill_catalog": SkillCatalog.load_bundled(),
        "execution_store": RoomExecutionReviewStore(db_path),
        "max_concurrent_rooms": 1,
        "delivery_timeout_s": 10,
        "cleanup_grace_s": 1,
        "runner_generation": f"generation-{name}",
        "runner_boot_id": f"boot-{name}",
        "memory_recall": memory.recall,
        "memory_context_receipts": memory.context_receipts,
        "memory_delivery_pump": memory.delivery_pump,
    }


def test_composition_routes_agy_cli_for_antigravity(tmp_path: Path) -> None:
    agy = tmp_path / "agy"
    agy.write_text("#!/bin/sh\n")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    common = _composition_common(tmp_path, "agy-route")
    agy_config = room_runner._agy_config(
        root=tmp_path,
        worktree=worktree,
        room_mcp_url="http://127.0.0.1:8100/mcp/room",
        agy_executable=agy,
        model="gemini-3.8-flash-high",
        bridge_script=Path(room_runner.__file__).resolve().parent / "room_mcp_stdio.py",
        python3=Path(sys.executable).resolve(),
        environ={"HOME": "/root", "XMUSE_OPENCODE_BWRAP": "/usr/sbin/bwrap"},
    )
    composition = room_runner_composition.compose_room_runtime(**common, agy_config=agy_config)
    assert len(composition.agy_transports) == 1
    assert composition.antigravity_transports == ()
    route = composition.host._transport._routes["antigravity"]
    assert isinstance(route, AgyRoomObservationTransport)
    assert route is composition.agy_transports[0]
    policy = composition.host._policy
    assert policy.provider_min_delivery_timeout_s == {"antigravity": 420.0}


def test_composition_keeps_agentapi_when_configured(tmp_path: Path) -> None:
    common = _composition_common(tmp_path, "agentapi-route")
    composition = room_runner_composition.compose_room_runtime(
        **common,
        antigravity_config=AntigravityTransportConfig(
            workspace=tmp_path,
            agentapi_command=(sys.executable, "-c", "pass"),
            brain_dir=tmp_path / "brain",
        ),
    )
    assert len(composition.antigravity_transports) == 1
    assert composition.agy_transports == ()
    assert "antigravity" in composition.host._transport._routes
