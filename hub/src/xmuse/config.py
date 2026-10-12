"""Paths, defaults and the per-workspace state directory."""
import hashlib
import json
import os
from pathlib import Path

HUMAN = "human"
HUB = "hub"
VIA_CLI = "cli"  # `via` of messages sent with the admin token (`xmuse send`): human, but from a terminal command

# Runaway guards (design §4.4 item 4). Safety stops, not budgets.
DEFAULTS = {
    "wake": "mention",               # experiment switch: mention | all (group threads wake every agent member; group A)
    "alignment": "on",               # experiment switch: on | off (off: no pack section, no curate, xmuse_context = recent messages)
    # T14 master switch (team group T-plain): off = only kind=message. No decision/assumption/question/handoff entries,
    # no injection, no scope or question routing, no dependency wake; tools and prompts no longer offer them.
    "info_layer": "on",
    "review_gate": True,             # done next=none is handed to a member with role "reviewer" first (evidence.py)
    "stall_notice": True,            # a turn that ends with handoffs unreturned notifies the assigner (stall.py)
    "preset_tick": 2.0,             # seconds between checks of a running orchestration preset (preset.py)
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
    "host_batch_max_s": 600,         # completed results wait at most this long after the first for the host's batch (T0)
}

MODELS = {"claude": "claude-opus-5-5", "opencode": "opencode-go/muse-spark-1.3-contributor",
          "dsh": "opencode-go/muse-spark-1.3-contributor"}
FAMILIES = {"claude": "anthropic", "opencode": "opencode", "dsh": "deepseek"}  # fallback when the model says nothing
# The family a peer sees is the model's, not the shell's (audit C; T8): dsh running muse-spark is not "deepseek".
MODEL_FAMILIES = [("claude", "anthropic"), ("deepseek", "deepseek"), ("muse-spark", "opencode"), ("gpt-", "openai"),
                  ("gemini", "google"), ("qwen", "qwen"), ("glm", "zhipu"), ("kimi", "moonshot")]


def family(vendor: str, model: str | None) -> str:
    m = (model or "").lower()
    return next((f for key, f in MODEL_FAMILIES if key in m), FAMILIES[vendor])

REPO = Path(__file__).resolve().parents[3]
SHIM = REPO / "shim" / "server.ts"
SKILL = REPO / "skill" / "xmuse-collab"
TEMPLATES = REPO / "templates"
HOOK = Path(__file__).resolve().parent / "hook.py"
DSH_HOOK = Path(__file__).resolve().parent / "dsh_hook.py"


def state_root() -> Path:
    if os.environ.get("XMUSE_STATE_ROOT"):
        return Path(os.environ["XMUSE_STATE_ROOT"])
    if os.name == "nt":  # Windows-native hub (D1): %LOCALAPPDATA%\xmuse\<room>-<hash>
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "xmuse"
    return Path.home() / ".local" / "state" / "xmuse"


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
            return Path(json.loads(f.read_text(encoding="utf-8"))["state"])
    raise SystemExit(f"no xmuse workspace at or above {p}; run `xmuse init <workspace>` first")


def load(state: Path) -> dict:
    cfg = json.loads((state / "config.json").read_text(encoding="utf-8"))
    return {**DEFAULTS, **cfg}


def info_on(cfg: dict) -> bool:
    return cfg.get("info_layer", "on") != "off"


def alignment_on(cfg: dict) -> bool:
    """Alignment shown to agents (packs, xmuse_context view, curate): needs the info layer too."""
    return info_on(cfg) and cfg.get("alignment", "on") != "off"
