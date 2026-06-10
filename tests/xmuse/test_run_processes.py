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
