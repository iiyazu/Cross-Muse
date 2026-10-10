"""Paths, defaults and the per-workspace state directory."""
import hashlib
import json
import os
from pathlib import Path

HUMAN = "human"
HUB = "hub"

# Runaway guards (design §4.4 item 4). Safety stops, not budgets.
DEFAULTS = {
    "wake": "mention",               # experiment switch: mention | all (group threads wake every agent member; group A)
    "alignment": "on",               # experiment switch: on | off (off: no pack section, no curate, xmuse_context = recent messages)
    "max_chain_wakes": 12,           # wakes per causal chain started by one human message
    "max_chain_tokens": 20_000_000,  # processed tokens per chain
    "chat_warn_tokens": 50_000,      # chat wakes over this log a warning (M1c task 2)
    "code_warn_tokens": None,        # code wakes never warn (dsh 12-44w is normal); empty on purpose
    "agent_hourly_turns": 40,
    "agent_hourly_tokens": 30_000_000,
    "turn_timeout": 1800,            # seconds before a running turn is interrupted
    "sweep_interval": 15,            # low-frequency fallback scan
    "recent_n": 8,                   # thread messages in a fresh-session bootstrap pack
    "align_global_cap": 40,          # active entries per view layer (design §4.5.1 item 4)
    "align_role_cap": 20,
    "align_thread_cap": 15,
    "align_snapshot_tokens": 12_000,  # injected alignment budgets, estimated as len(text)//3
    "align_delta_tokens": 2_000,
    "body_limit": 4_000,             # chars per xmuse_send body; bigger content goes in a workspace file
    "session_notice_tokens": 400_000,  # one notice per session when its context first passes this
    "memoryos_url": "",              # MemoryOS base URL; empty = not used (contract XMUSE2-M2-MO-CONTRACT)
    "compact_drop_ratio": 0.5,       # a turn's context below this share of the last one's means the vendor compacted
    "recall_budget_tokens": 2_000,  # per over-cap layer, sent as /recall budget_tokens
    "curate_timeout_s": 480,         # /curate collab (background): 2 attempts x 200 s worst case (max_repairs 1)
    "similar_timeout_s": 30,         # /similar (background); a cold embedding cache takes ~3 s
}

MODELS = {"claude": "claude-opus-5-5", "opencode": "opencode-go/muse-spark-1.3-contributor",
          "dsh": "deepseek-official/deepseek-v4-flash"}
FAMILIES = {"claude": "anthropic", "opencode": "opencode", "dsh": "deepseek"}

REPO = Path(__file__).resolve().parents[3]
SHIM = REPO / "shim" / "server.ts"
SKILL = REPO / "skill" / "xmuse-collab"
TEMPLATES = REPO / "templates"
HOOK = Path(__file__).resolve().parent / "hook.py"
DSH_HOOK = Path(__file__).resolve().parent / "dsh_hook.py"


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
