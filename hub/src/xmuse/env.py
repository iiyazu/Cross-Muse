"""Clean environment for spawned agents (M0: CLIs spawned from the desktop app inherit dozens
of CLAUDE_*/ANTHROPIC_* variables, which re-label sessions and grow the base context)."""
import os

KEEP = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "LANG", "LC_ALL", "TERM", "TZ", "TMPDIR",
        "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")


def clean_env(extra: dict | None = None) -> dict:
    env = {k: os.environ[k] for k in KEEP if k in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    return {**env, **(extra or {})}
