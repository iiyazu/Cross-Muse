"""Machine-local hub registry and the sidebar credential (XMUSE2-VIEW-API v0.1, section 8.1).

One directory per OS user (Windows: %LOCALAPPDATA%\\xmuse, elsewhere ${XDG_STATE_HOME:-~/.local/state}/xmuse;
XMUSE_REGISTRY_DIR overrides, tests always set it):
  - hubs.json    {"hubs": [{room_id, name, dir, url, host, pid, started_at}]}: every running hub writes its own entry
                 on start and removes it on exit; readers drop entries whose pid is gone (a killed hub leaves one).
  - install.json {python, distro, os}: how to start a hub here; the panel reads it when no hub is running
  - sidebar.key  32 random bytes as hex, mode 600, made by the first hub that starts. A sidebar plugin reads it and
                 sends it as x-xmuse-sidebar; agent processes are not given it and the shell policy refuses commands
                 that name the file. Same OS user, so this keeps agents from joining on their own, nothing more.
"""
import fnmatch
import hmac
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import time
from pathlib import Path

from . import proc

KEY_NAME = "sidebar.key"
_LOCK_WAIT, _LOCK_STALE = 10.0, 15.0


def directory() -> Path:
    env = os.environ.get("XMUSE_REGISTRY_DIR")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "xmuse"
    return Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state") / "xmuse"


def hubs_path() -> Path:
    return directory() / "hubs.json"


def key_path() -> Path:
    return directory() / KEY_NAME


# ---- hubs.json ----------------------------------------------------------------------------------------------

class _Lock:
    """Cross-process lock for read-modify-write: an exclusively created file, broken when its owner died."""

    def __init__(self):
        self.path = directory() / "hubs.lock"

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        end = time.monotonic() + _LOCK_WAIT
        while True:
            try:
                os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
                return self
            except FileExistsError:
                try:
                    if time.time() - self.path.stat().st_mtime > _LOCK_STALE:
                        self.path.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
            except PermissionError:  # Windows: the file is being deleted by its owner
                pass
            if time.monotonic() > end:
                self.path.unlink(missing_ok=True)  # a lock nobody released in 10 s is stuck; take it
                continue
            time.sleep(0.02)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)


def _load() -> list[dict]:
    for _ in range(20):  # the file is replaced atomically; Windows can still refuse a read mid-replace
        try:
            data = json.loads(hubs_path().read_text(encoding="utf-8"))
            return [e for e in data.get("hubs", []) if isinstance(e, dict)]
        except FileNotFoundError:
            return []
        except (ValueError, OSError, AttributeError):
            time.sleep(0.02)
    return []


def _store(entries: list[dict]) -> None:
    p = hubs_path()
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps({"hubs": entries}, indent=1, ensure_ascii=False), encoding="utf-8")
    for i in range(20):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:  # Windows: a reader has it open for a moment
            if i == 19:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.02)


def _live(entries: list[dict]) -> list[dict]:
    return [e for e in entries if proc.alive(e.get("pid"))]


def hubs() -> list[dict]:
    """The running hubs on this machine (entries of dead processes dropped)."""
    return _live(_load())


def register(entry: dict) -> None:
    """Write or update this hub's entry (keyed by room_id; a dead hub's old entry for the room is replaced)."""
    with _Lock():
        rest = [e for e in _live(_load()) if e.get("room_id") != entry["room_id"]]
        _store(rest + [entry])


def unregister(room_id: str, pid: int | None = None) -> None:
    """Remove this hub's entry; an entry of the same room that belongs to another live pid stays."""
    pid = os.getpid() if pid is None else pid
    with _Lock():
        _store([e for e in _live(_load()) if not (e.get("room_id") == room_id and e.get("pid") == pid)])


# ---- install.json -------------------------------------------------------------------------------------------

def install_path() -> Path:
    return directory() / "install.json"


def write_install() -> None:
    """How to start a hub on this machine, for a panel that finds no running one (after a reboot): the interpreter
    this hub runs on and, inside WSL, the distro. Kept after the hub exits; rewritten only when it changed."""
    data = {"python": sys.executable, "distro": os.environ.get("WSL_DISTRO_NAME", ""), "os": os.name}
    p = install_path()
    try:
        if json.loads(p.read_text(encoding="utf-8")) == data:
            return
    except (OSError, ValueError):
        pass
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


# ---- sidebar.key --------------------------------------------------------------------------------------------

def _restrict(p: Path) -> None:
    try:
        p.chmod(0o600)
        if os.name == "nt":  # chmod only toggles read-only there: best effort, owner-only ACL
            user = os.environ.get("USERNAME")
            if user:
                subprocess.run(["icacls", str(p), "/inheritance:r", "/grant:r", f"{user}:F"], capture_output=True,
                               timeout=10)
    except (OSError, subprocess.SubprocessError):
        pass


def read_key() -> str | None:
    for _ in range(20):  # a concurrent first start may be mid-write
        try:
            k = key_path().read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if re.fullmatch(r"[0-9a-f]{64}", k):
            return k
        time.sleep(0.02)
    return None


def ensure_key() -> str:
    """The sidebar key; made (once, atomically) when it does not exist yet."""
    k = read_key()
    if k:
        return k
    p = key_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    fd = os.open(tmp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(secrets.token_hex(32))
    _restrict(tmp)
    try:
        os.link(tmp, p)  # fails when another hub got there first: that key wins
    except FileExistsError:
        pass
    except OSError:
        if not p.exists():
            os.replace(tmp, p)
    tmp.unlink(missing_ok=True)
    return read_key() or ""


def check_key(given) -> bool:
    """Constant-time comparison with the key on disk; False when there is none or nothing was given."""
    key = read_key()
    if not key or not isinstance(given, str) or not given:
        return False
    return hmac.compare_digest(given.strip().encode("utf-8"), key.encode("utf-8"))


_QUOTES = re.compile(r"[\"'\\]")
_SEARCH = {"grep", "egrep", "fgrep", "rg", "ag", "ack", "findstr", "select-string"}


def _names(text: str) -> bool:
    """The literal name (any case) or a glob word that would match it (`side*`, `*.key`)."""
    if KEY_NAME in text:
        return True
    globs = (w for w in re.split(r"[\s/;|&<>()=:,]+", text) if any(ch in w for ch in "*?["))
    # at least 3 literal characters, so a bare `*` (grep foo *) is not taken for an attempt
    return any(len(re.sub(r"[*?\[\]]", "", w)) >= 3 and fnmatch.fnmatchcase(KEY_NAME, w) for w in globs)


def _operands(cmd: str) -> list[str] | None:
    """The words of each simple command, minus a search tool's pattern (`grep -n "sidebar.key" src/x.py` searches
    source for the name, it does not open the file). None when the shell syntax does not parse."""
    lex = shlex.shlex(cmd, posix=True, punctuation_chars=True)
    lex.whitespace_split = True
    try:
        toks = list(lex)
    except ValueError:
        return None
    out, words = [], []
    for t in toks + [";"]:
        if t and all(ch in "();<>|&" for ch in t):
            while words and re.fullmatch(r"\w+=.*", words[0]):  # env prefixes
                words.pop(0)
            prog = words[0].replace("\\", "/").rsplit("/", 1)[-1].lower() if words else ""
            args = words[2:] if prog == "git" and words[1:2] == ["grep"] else words[1:]
            if prog in _SEARCH or (prog == "git" and words[1:2] == ["grep"]):
                if any(a in ("-e", "--regexp") for a in args):
                    args = [a for i, a in enumerate(args) if i == 0 or args[i - 1] not in ("-e", "--regexp")]
                else:
                    first = next((i for i, a in enumerate(args) if not a.startswith("-")), None)
                    args = [a for i, a in enumerate(args) if i != first]
                words = words[:1] + args
            out += words
            words = []
        else:
            words.append(t)
    return out


def mentions_key(cmd: str) -> bool:
    """A shell command that names the key file as something it would open: the literal name (quotes and backslashes
    inside it removed, any case) or a glob word that would match it. A search tool's pattern does not count. Only the
    same-user nudge of section 8.1."""
    words = _operands(str(cmd))
    if words is None:  # unparseable: the conservative reading of the whole text
        return _names(_QUOTES.sub("", str(cmd)).lower())
    return any(_names(w.lower()) for w in words)
