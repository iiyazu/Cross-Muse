"""Clean environment for spawned agents (M0: CLIs spawned from the desktop app inherit dozens
of CLAUDE_*/ANTHROPIC_* variables, which re-label sessions and grow the base context)."""
import os

KEEP = ("HOME", "USER", "LOGNAME", "PATH", "SHELL", "LANG", "LC_ALL", "TERM", "TZ", "TMPDIR",
        "XDG_RUNTIME_DIR", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")
# Windows: without SYSTEMROOT node aborts at start (ncrypto CSPRNG), and the user's profile and temp
# directories are where every vendor CLI keeps its login and state.
KEEP_WINDOWS = ("SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "PATHEXT", "USERPROFILE", "USERNAME", "USERDOMAIN",
                "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES",
                "PROGRAMFILES(X86)", "PROGRAMW6432", "COMMONPROGRAMFILES", "TEMP", "TMP", "NUMBER_OF_PROCESSORS",
                "PROCESSOR_ARCHITECTURE", "OS", "PYTHONUTF8")


def clean_env(extra: dict | None = None) -> dict:
    keep = KEEP + KEEP_WINDOWS if os.name == "nt" else KEEP
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env.setdefault("LANG", "C.UTF-8")
    return {**env, **(extra or {})}
