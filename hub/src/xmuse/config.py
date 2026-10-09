"""Paths, defaults and the per-workspace state directory."""
import hashlib
import json
import os
from pathlib import Path

HUMAN = "human"
HUB = "hub"

# Runaway guards (design §4.4 item 4). Safety stops, not budgets.
DEFAULTS = {
    "max_chain_wakes": 12,           # wakes per causal chain started by one human message
    "max_chain_tokens": 20_000_000,  # processed tokens per chain
    "agent_hourly_turns": 40,
    "agent_hourly_tokens": 30_000_000,
    "turn_timeout": 1800,            # seconds before a running turn is interrupted
    "sweep_interval": 15,            # low-frequency fallback scan
    "recent_n": 8,                   # thread messages in a fresh-session bootstrap pack
}

# Rotate to a fresh session once the context read by the last model call of a turn
# exceeds this (design §4.1 principle 9). See report for the choice.
ROTATE_AT = {"claude": 120_000, "opencode": 120_000, "dsh": 120_000}

MODELS = {"claude": "claude-opus-5-5", "opencode": "opencode-go/muse-spark-1.3-contributor",
          "dsh": "deepseek-official/deepseek-v4-flash"}
FAMILIES = {"claude": "anthropic", "opencode": "opencode", "dsh": "deepseek"}

REPO = Path(__file__).resolve().parents[3]
SHIM = REPO / "shim" / "server.ts"
SKILL = REPO / "skill" / "xmuse-collab"
TEMPLATES = REPO / "templates"
HOOK = Path(__file__).resolve().parent / "hook.py"


def state_root() -> Path:
    return Path(os.environ.get("XMUSE_STATE_ROOT") or Path.home() / ".local" / "state" / "xmuse")


def state_dir_for(ws: Path) -> Path:
    ws = ws.resolve()
    return state_root() / f"{ws.name}-{hashlib.sha256(str(ws).encode()).hexdigest()[:8]}"


def find_state(start: Path | None = None) -> Path:
    """Walk up from `start` (default cwd) to the workspace pointer written by `xmuse init`."""
    if os.environ.get("XMUSE_STATE"):
        return Path(os.environ["XMUSE_STATE"])
    p = (start or Path.cwd()).resolve()
    for d in (p, *p.parents):
        f = d / ".xmuse.json"
        if f.exists():
            return Path(json.loads(f.read_text())["state"])
    raise SystemExit(f"no xmuse workspace at or above {p}; run `xmuse init <workspace>` first")


def load(state: Path) -> dict:
    cfg = json.loads((state / "config.json").read_text())
    return {**DEFAULTS, **cfg}
