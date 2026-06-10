from __future__ import annotations

import importlib
from pathlib import Path

from xmuse_core.platform import master_loop_cli


def test_cli_module_parse_args_accepts_legacy_aliases() -> None:
    args = master_loop_cli.parse_args(
        [
            "--lanes",
            "lanes.json",
            "--agents",
            "agents.json",
            "--memoryos-url",
            "http://memoryos.test",
            "--max-concurrent",
            "4",
            "--max-hours",
            "2",
            "--no-discovery",
        ]
    )

    assert args.lanes == "lanes.json"
    assert args.config == "agents.json"
    assert args.memoryos_url == "http://memoryos.test"
    assert args.concurrency == 4
    assert args.max_hours == 2
    assert args.no_discovery is True


def test_cli_module_defaults_runtime_files_from_xmuse_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XMUSE_ROOT", str(tmp_path / "external-xmuse"))
    reloaded = importlib.reload(master_loop_cli)

    args = reloaded.parse_args([])

    assert Path(args.lanes) == tmp_path / "external-xmuse" / "feature_lanes.json"
    assert Path(args.config) == tmp_path / "external-xmuse" / "agents.json"
    assert Path(args.auto_discovery).name == "auto_discovery.py"

    importlib.reload(master_loop_cli)
