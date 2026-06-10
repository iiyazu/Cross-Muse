"""CLI parsing for the legacy Xmuse master loop."""

from __future__ import annotations

import argparse
from pathlib import Path

from xmuse_core.runtime.paths import default_xmuse_root

XMUSE_ROOT = default_xmuse_root(Path("xmuse"))
PROJECT_ROOT = Path(__file__).resolve().parents[3]
XMUSE_CODE_ROOT = PROJECT_ROOT / "xmuse"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="xmuse autonomous master loop")
    parser.add_argument("--max-hours", type=float, default=10.0, help="Global timeout in hours")
    parser.add_argument(
        "--concurrency",
        "--max-concurrent",
        dest="concurrency",
        type=int,
        default=2,
        help="Max concurrent lanes",
    )
    parser.add_argument(
        "--lanes",
        default=str(XMUSE_ROOT / "feature_lanes.json"),
        help="Feature lanes file",
    )
    parser.add_argument(
        "--config",
        default=str(XMUSE_ROOT / "agents.json"),
        help="Agent registry config",
    )
    parser.add_argument(
        "--memoryos-url",
        default="http://127.0.0.1:8000",
        help="MemoryOS API URL",
    )
    parser.add_argument(
        "--auto-discovery",
        default=str(XMUSE_CODE_ROOT / "auto_discovery.py"),
        help="auto_discovery.py path",
    )
    parser.add_argument("--agents", dest="config", help=argparse.SUPPRESS)
    parser.add_argument(
        "--no-discovery",
        action="store_true",
        help="Skip auto_discovery.py at round start",
    )
    return parser.parse_args(argv)
