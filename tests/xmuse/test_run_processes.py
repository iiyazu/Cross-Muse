from __future__ import annotations

from pathlib import Path

from xmuse_core.platform.run_processes import (
    build_process_inventory,
    discover_xmuse_runtime_processes,
)


def test_run_processes_module_discovers_runtime_services(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    for pid, ppid, cmdline in [
        (101, 1, b"uv\0run\0python\0xmuse/platform_runner.py\0--max-hours\08\0"),
        (102, 101, b"python3\0xmuse/platform_runner.py\0--max-hours\08\0"),
        (201, 1, b"python3\0xmuse/mcp_server.py\0"),
        (301, 1, b"python3\0xmuse/dashboard_api.py\0"),
        (801, 1, b"codex\0exec\0--yolo\0prompt\0"),
    ]:
        path = proc_root / str(pid)
        path.mkdir(parents=True)
        path.joinpath("cmdline").write_bytes(cmdline)
        path.joinpath("status").write_text(f"Name:\ttest\nPPid:\t{ppid}\n")

    inventory = discover_xmuse_runtime_processes(proc_root)

    assert inventory["runner_pids"] == [102]
    assert inventory["mcp_pids"] == [201]
    assert inventory["counts_by_service"]["dashboard_api"] == 1
    assert inventory["counts_by_service"]["codex_worker"] == 1


def test_run_processes_module_scopes_parallel_runtime_roots(tmp_path: Path) -> None:
    proc_root = tmp_path / "proc"
    root_a = tmp_path / "run-a"
    root_b = tmp_path / "run-b"
    entries = [
        (
            91,
            1,
            [
                b"/bin/bash",
                b"-lc",
                (
                    b"RUN_B=/tmp/run-b XMUSE_ROOT=\"$RUN_B\" uv run python -c "
                    b"'from xmuse.chat_api import create_app; create_app()'"
                ),
            ],
            {},
        ),
        (
            92,
            1,
            [
                b"/bin/bash",
                b"-lc",
                (
                    b"RUN_B=/tmp/run-b XMUSE_ROOT=\"$RUN_B\" uv run python -c "
                    b"'from xmuse.mcp_server import create_app; create_app()'"
                ),
            ],
            {},
        ),
        (
            101,
            1,
            [b"uv", b"run", b"xmuse-platform-runner", b"--xmuse-root", str(root_a).encode()],
            {"XMUSE_ROOT": str(root_a)},
        ),
        (
            102,
            101,
            [
                b"python",
                b"/tmp/.venv/bin/xmuse-platform-runner",
                b"--xmuse-root",
                str(root_a).encode(),
            ],
            {"XMUSE_ROOT": str(root_a)},
        ),
        (
            111,
            1,
            [b"uv", b"run", b"xmuse-platform-runner", b"--xmuse-root", str(root_b).encode()],
            {"XMUSE_ROOT": str(root_b)},
        ),
        (
            112,
            111,
            [
                b"python",
                b"/tmp/.venv/bin/xmuse-platform-runner",
                b"--xmuse-root",
                str(root_b).encode(),
            ],
            {"XMUSE_ROOT": str(root_b)},
        ),
        (
            201,
            1,
            [
                b"python",
                b"-c",
                b"from xmuse.mcp_server import create_app; create_app()",
            ],
            {"XMUSE_ROOT": str(root_a)},
        ),
        (
            211,
            1,
            [
                b"python",
                b"-c",
                b"from xmuse.mcp_server import create_app; create_app()",
            ],
            {"XMUSE_ROOT": str(root_b)},
        ),
        (
            301,
            1,
            [
                b"python",
                b"-c",
                b"from xmuse.chat_api import create_app; create_app()",
            ],
            {"XMUSE_ROOT": str(root_a)},
        ),
        (
            311,
            1,
            [
                b"python",
                b"-c",
                b"from xmuse.chat_api import create_app; create_app()",
            ],
            {"XMUSE_ROOT": str(root_b)},
        ),
        (
            701,
            102,
            [b"python", b"-m", b"xmuse_core.agents.codex_persistent"],
            {"XMUSE_ROOT": str(root_a)},
        ),
        (
            711,
            112,
            [b"python", b"-m", b"xmuse_core.agents.codex_persistent"],
            {"XMUSE_ROOT": str(root_b)},
        ),
    ]
    for pid, ppid, args, environ in entries:
        path = proc_root / str(pid)
        path.mkdir(parents=True)
        path.joinpath("cmdline").write_bytes(b"\0".join(args) + b"\0")
        path.joinpath("environ").write_bytes(
            b"\0".join(
                f"{key}={value}".encode()
                for key, value in environ.items()
            )
            + b"\0"
        )
        path.joinpath("status").write_text(f"Name:\ttest\nPPid:\t{ppid}\n")

    inventory = discover_xmuse_runtime_processes(proc_root, xmuse_root=root_a)

    assert inventory["runner_pids"] == [102]
    assert inventory["mcp_pids"] == [201]
    assert inventory["counts_by_service"] == {
        "runner": 1,
        "mcp": 1,
        "chat_api": 1,
        "persistent_god_shim": 1,
    }
    assert inventory["warnings"] == []


def test_run_processes_module_keeps_inventory_warning_contract() -> None:
    inventory = build_process_inventory(
        runner_pids=[11, 12],
        mcp_pids=[],
        services={"scheduler_monitor": [21, 22]},
    )

    assert [warning["code"] for warning in inventory["warnings"]] == [
        "duplicate_runner_processes",
        "missing_mcp_process",
        "duplicate_scheduler_monitor_processes",
    ]
    assert inventory["evidence"]["hard"][0]["service"] == "runner"
    assert {item["service"] for item in inventory["services"]} == {
        "runner",
        "scheduler_monitor",
    }
