"""OpenCode 2.x: a dedicated `opencode serve` per workspace, prompt + SSE (M0 §3).

The server keeps a durable inbox and serializes every input (hub, TUI, web), so there is no
lease: the hub posts with delivery "queue" and metadata.xmuse; anything enqueued without that
metadata is a human, and admission waits for that execution to end.
"""
import base64
import fnmatch
import json
import re
import secrets
import shlex
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from .. import proc, registry
from ..config import SHIM
from ..env import clean_env
from .base import Presence, TurnEnd, TurnSpec, Usage

END = {"session.execution.succeeded": "succeeded", "session.execution.failed": "failed",
       "session.execution.interrupted": "interrupted"}
CODE_TOOLS = {"edit", "write", "patch", "apply_patch", "multiedit", "shell", "bash"}

# Shell auto-approval is an allowlist (audit B2-2): OpenCode asks for every shell command (write_config), and the
# hub approves a command on its own only when it is one simple command (no chaining, substitution, redirection
# other than 2>&1, subshells or interpreters given inline code) whose argv passes ALLOW below. Everything else
# goes to the human. This keeps unattended runs moving on tests and read-only inspection; it is not a sandbox.
READ_ONLY = {"ls", "cat", "head", "tail", "wc", "grep", "rg", "pwd", "echo", "diff", "sort", "uniq", "tree",
             "which", "true", "file", "stat", "du", "basename", "dirname", "realpath", "nl", "cut", "tr", "cmp"}
# options that turn a read-only tool into a writer or a launcher (T8): long options by prefix, short ones by letter
# (also inside clusters like -uo)
DENY_LONG = {"sort": ("--output", "--compress-program"), "tree": ("--output",), "rg": ("--pre",),
             "git": ("--output", "--open-files-in-pager", "--ext-diff", "--textconv", "--exec")}
DENY_SHORT = {"sort": "o", "tree": "o", "git": "O"}
GIT_LOCAL = {"status", "diff", "log", "show", "add", "commit", "rev-parse", "ls-files", "blame", "grep",
             "shortlog", "describe"}  # no restore/checkout/reset: they discard work
_SED_PRINT = re.compile(r"^\d+(,\d+)?p$")
PIPE_FILTERS = {"head", "tail", "grep", "wc", "sort", "uniq", "cut", "tr", "nl"}  # may follow `|`
# Unattended experiments only (XMUSE_SHELL_POLICY=blocklist-experiment, set in the hub's environment by the runner,
# never by config): the pre-T5 rule, approve unless the env-stripped command starts like one of these. Bypassable
# (audit B2-2); kept so experiment runs need no human and stay comparable with the M2b runs.
ASK_SHELL = ["git push*", "git merge*", "git rebase*", "git reset --hard*", "git clean*", "git branch -D*",
             "git checkout -- *", "rm -r*", "rm -f*", "sudo *", "curl *", "wget *"]
# open-experiment (T15 team runs, user 10-12): no request ever waits for a human and every request is approved.
# A first version rejected build/test runners, but OpenCode ends the agent's turn on a rejection (r4: oc-ms13 lost
# the rest of P1 to one `mvn compile`), so the user had that lifted too. Runner use is only logged here (the words
# below) and searched for in the transcripts afterwards; a hit is recorded as a violation.
RUNNERS = {"docker", "podman", "java", "javac", "mvn", "mvnw", "mvn.cmd", "gradle", "gradlew", "gradle.bat",
           "wsl", "wsl.exe", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe"}
_WORDS = re.compile(r"[^\s;&|()<>`'\"$={}]+")
POLICIES = ("allowlist", "blocklist-experiment", "open-experiment")
_META = re.compile(r";|&&|\|\||&|`|\$\(|\$\{|<\(|>\(|<|\n|\\\n")
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")


def strip_env(cmd: str) -> str:
    """Drop leading `NAME=value` assignments: `PYTHONPATH=x python -m unittest` -> `python -m unittest`."""
    cmd = cmd.strip()
    while (m := _ENV_ASSIGN.match(cmd)):
        cmd = cmd[m.end():].lstrip()
    return cmd


def _safe_path(p: str) -> bool:
    """A path an agent may delete without asking: under /tmp/, or relative inside its workspace; no globs."""
    if not p or p.startswith("-") or any(c in p for c in "*?[") or ".." in p.split("/"):
        return False
    return p.startswith("/tmp/") or not p.startswith(("/", "~"))


_LOOPBACK = re.compile(r"(localhost|127(\.\d{1,3}){3}|\[::1\])(:\d+)?")
_HOSTISH = re.compile(r"(\d{1,3}(\.\d{1,3}){3}|[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}|localhost|\[[0-9a-fA-F:]+\])"
                      r"(:\d+)?(/\S*)?")
# options that would send the request somewhere else, or read more URLs from a file
_CURL_AWAY = ("-x", "--proxy", "--preproxy", "--socks4", "--socks4a", "--socks5", "--socks5-hostname",
              "--connect-to", "--resolve", "-K", "--config", "--doh-url", "-:", "--next")


def loopback_curl(cmd: str) -> bool:
    """`curl` to this machine only (user 10-12: agents check their own local servers without asking). Every URL
    must be http(s) on localhost/127.x/[::1], bare host arguments too; proxies, --resolve/--connect-to, config
    files and --next stay with the human. No chaining or substitution; the harmless redirections 2>&1 and
    >/dev/null are allowed."""
    cmd = re.sub(r"\s+(\d?>&\d|\d?>\s*/dev/null)(?=\s|$)", "", cmd)
    if any(c in cmd for c in ";&|`$\n") or "<(" in cmd:
        return False
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return False
    if not argv or argv[0].rsplit("/", 1)[-1] != "curl":
        return False
    urls = []
    for a in argv[1:]:
        if a in _CURL_AWAY or any(a.startswith(o + "=") for o in _CURL_AWAY if o.startswith("--")) \
                or re.match(r"-[A-Za-z]*[xK]", a):  # also attached/clustered short forms: -xhost, -sK file
            return False
        if "://" in a:
            m = re.fullmatch(r"https?://([^/?#@]+@)?([^/?#]+)([/?#]\S*)?", a)
            if not m or not _LOOPBACK.fullmatch(m.group(2)):
                return False
            urls.append(a)
        elif not a.startswith("-") and _HOSTISH.fullmatch(a):
            if not _LOOPBACK.fullmatch(a.split("/", 1)[0]):
                return False
            urls.append(a)
    return bool(urls)


def safe_rm_f(cmd: str) -> bool:
    """`rm -f PATH...` with only -f and only safe paths (agents clean up their own probe files, e.g. /tmp/x.py).

    Without this the plain `rm -f*` ask rule parks unattended runs on a human until the turn times out.
    Recursive flags, absolute paths outside /tmp, `..`, `~` and wildcards all stay with the human."""
    if any(c in cmd for c in ";&|<>$`()\n\\"):  # chaining, redirection or substitution: not a plain rm
        return False
    try:
        argv = shlex.split(cmd)
    except ValueError:
        return False
    if argv[:2] != ["rm", "-f"] or len(argv) < 3:
        return False
    return all(_safe_path(a) for a in argv[2:])


def _python_ok(argv: list[str]) -> bool:
    """Tests, or a script file in the workspace or /tmp. Inline code (-c) and other modules go to the human."""
    rest = argv[1:]
    while rest and rest[0] in ("-u", "-B", "-I"):  # harmless interpreter flags
        rest = rest[1:]
    if not rest:
        return False
    if rest[0] == "-m":
        return len(rest) > 1 and rest[1] in ("pytest", "unittest", "py_compile", "compileall")
    return rest[0].endswith(".py") and _safe_path(rest[0])


def _denied_option(cmd: str, args: list[str]) -> bool:
    long, short = DENY_LONG.get(cmd, ()), DENY_SHORT.get(cmd, "")
    for a in args:
        if a == "--":
            break
        if a.startswith("--") and any(a.startswith(d) for d in long):
            return True
        if a.startswith("-") and not a.startswith("--") and any(c in a[1:] for c in short):
            return True
    return False


def _argv_ok(argv: list[str], first: bool) -> bool:
    if not argv or "/" in argv[0]:  # `/usr/bin/git push` and `./x` name no allowlisted program
        return False
    cmd, args = argv[0], argv[1:]
    if _denied_option(cmd, args):
        return False
    if not first:
        return cmd in PIPE_FILTERS and not any(a.startswith("/") and not a.startswith("/tmp/") for a in args)
    if cmd in READ_ONLY:
        return True
    if cmd == "sed":  # only `sed -n 'N[,M]p' FILE...`: other scripts can write (w/W) or execute (e)
        return len(args) >= 2 and args[0] == "-n" and bool(_SED_PRINT.match(args[1])) and \
            all(_safe_path(a) for a in args[2:])
    if cmd == "find":
        return not any(a in ("-exec", "-execdir", "-delete", "-ok", "-okdir") or a.startswith(("-fprint", "-fls"))
                       for a in args)
    if cmd == "git":
        return bool(args) and args[0] in GIT_LOCAL  # no `git -C`, `git -c`, push, merge, reset, ...
    if cmd in ("python", "python3"):
        return _python_ok(argv)
    if cmd == "pytest":
        return True
    if cmd == "mkdir":
        return all(a == "-p" or _safe_path(a) for a in args) and any(a != "-p" for a in args)
    if cmd == "rm":
        return safe_rm_f(shlex.join(argv))
    return False


def command_auto_ok(cmd: str) -> bool:
    """One shell command line, decided by the allowlist. `x | head` is allowed when x is allowlisted and every
    later stage is a read-only filter; `2>&1` is the only redirection allowed."""
    cmd = strip_env(cmd).replace("2>&1", " ")
    if not cmd.strip() or _META.search(cmd) or ">" in cmd:
        return False
    stages = cmd.split("|")
    try:
        argvs = [shlex.split(s) for s in stages]
    except ValueError:
        return False
    return all(_argv_ok(argv, i == 0) for i, argv in enumerate(argvs))


def blocklist_ok(cmd: str) -> bool:
    c = strip_env(cmd)
    return safe_rm_f(c) or loopback_curl(c) or not any(fnmatch.fnmatchcase(c, p) for p in ASK_SHELL)


def names_key(resources) -> bool:
    return isinstance(resources, list) and any(isinstance(r, str) and registry.mentions_key(r) for r in resources)


def shell_auto_ok(action: str | None, resources, policy: str = "allowlist") -> bool:
    """True when every shell command in a permission request passes the policy's check (env prefixes removed
    first: `PYTHONPATH=x python -m unittest` is the common case that used to park unattended runs)."""
    if action != "shell" or not isinstance(resources, list) or not resources or names_key(resources):
        return False
    ok = blocklist_ok if policy == "blocklist-experiment" else command_auto_ok
    return all(isinstance(r, str) and ok(r) for r in resources)


def names_runner(cmd: str) -> bool:
    return any(w.rsplit("/", 1)[-1].rsplit("\\", 1)[-1].lower() in RUNNERS for w in _WORDS.findall(cmd))


def auto_decision(action: str | None, resources, policy: str = "allowlist") -> str | None:
    """The hub's own answer to a permission request ('once' or 'reject'), or None: the human decides."""
    if policy == "open-experiment":
        return "once"
    if action == "shell" and names_key(resources):  # the sidebar key (contract 8.1): agents do not join by themselves
        return "reject"
    return "once" if shell_auto_ok(action, resources, policy) else None


def instance_dir(state: Path, agent_id: str) -> Path:
    """Per-instance OpenCode files in the hub state (T12): config with the identity, server password."""
    return state / "oc" / agent_id


def write_config(ws: Path, agent: dict, state: Path) -> list[Path]:
    """Identity goes into the instance's own config (loaded by its server through OPENCODE_CONFIG, probe 10-11 on
    v2.0.21: /api/config lists it next to the project file); the workspace opencode.json is shared by every instance
    and carries only the permission rules."""
    from .dsh import extra_mcp
    d = instance_dir(state, agent["id"])
    d.mkdir(parents=True, exist_ok=True)
    servers = {"xmuse": {"type": "local", "command": ["node", str(SHIM)],
                         "environment": {"XMUSE_STATE": str(state), "XMUSE_AGENT": agent["id"]}}}
    # per-agent extra stdio MCP servers (`xmuse agent add --extra-mcp`), same entries as for headless dsh
    extra = extra_mcp(agent)
    for x in extra:
        servers[x["name"]] = {"type": "local", "command": [x["command"], *x.get("args", [])],
                              "environment": x.get("env", {})}
    inst = {"$schema": "https://opencode.ai/config.json", "mcp": {"servers": servers}}
    (d / "opencode.json").write_text(json.dumps(inst, indent=2) + "\n", encoding="utf-8")
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        # every shell command asks; the hub answers allowlisted ones itself (shell_auto_ok) and forwards the rest
        "permissions": [{"action": "xmuse_*", "resource": "*", "effect": "allow"},
                        *({"action": f"{x['name']}_*", "resource": "*", "effect": "allow"} for x in extra),
                        {"action": "shell", "resource": "*", "effect": "ask"}],
    }
    (ws / "opencode.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
    return [d / "opencode.json", ws / "opencode.json"]


class Server:
    """One agent's dedicated OpenCode server (own port, password file and config; never the user's service)."""

    def __init__(self, ws: Path, state: Path, agent_id: str, port: int | None = None, base: str | None = None,
                 binary: str = "opencode"):
        self.ws, self.state, self.agent_id, self.binary, self.proc = ws, state, agent_id, binary, None
        self.dir = instance_dir(state, agent_id)
        self.dir.mkdir(parents=True, exist_ok=True)
        pw = self.dir / "oc.pass"
        if not pw.exists():
            pw.write_text(secrets.token_urlsafe(24), encoding="utf-8")
            pw.chmod(0o600)
        self.pw = pw
        self.auth = "Basic " + base64.b64encode(f"opencode:{pw.read_text(encoding="utf-8").strip()}".encode()).decode()
        self.base = base or f"http://127.0.0.1:{port or _free_port()}"

    def start(self, timeout: float = 60) -> None:
        port = self.base.rsplit(":", 1)[1]
        log = (self.state / "logs" / f"opencode-{self.agent_id}.log").open("a", encoding="utf-8")
        self.proc = proc.popen(
            [*proc.argv(self.binary), "serve", "--hostname", "127.0.0.1", "--port", port, "--print-logs"],
            cwd=self.ws, env=clean_env({"OPENCODE_SERVER_PASSWORD": self.pw.read_text(encoding="utf-8").strip(),
                                        "OPENCODE_CONFIG": str(self.dir / "opencode.json")}),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace")

        def pump():  # keep the log, never the password line
            for line in self.proc.stdout:
                if "password" not in line.lower():
                    log.write(line)
                    log.flush()
        threading.Thread(target=pump, daemon=True).start()
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                self.api("GET", "/api/session")
                return
            except (urllib.error.URLError, ConnectionError):
                time.sleep(0.5)
        raise RuntimeError(f"opencode serve did not come up on {self.base}")

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None and proc.WINDOWS:  # terminate() would leave its children
            proc.kill_tree(self.proc)
            self.proc.wait(10)
        elif self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(10)
            except subprocess.TimeoutExpired:
                self.proc.kill()

    def api(self, method: str, path: str, body: dict | None = None):
        req = urllib.request.Request(self.base + path, method=method, data=None if body is None else
                                     json.dumps(body).encode(),
                                     headers={"authorization": self.auth, "content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read()
            return json.loads(raw) if raw else None

    def events(self):
        req = urllib.request.Request(self.base + "/api/event",
                                     headers={"authorization": self.auth, "accept": "text/event-stream"})
        with urllib.request.urlopen(req, timeout=3600) as r:
            buf = ""
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\n")
                if line.startswith("data:"):
                    buf += line[5:].strip()
                elif line == "" and buf:
                    ev, buf = json.loads(buf), ""
                    yield ev


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Tracked:
    def __init__(self, spec: TurnSpec):
        self.spec, self.usage, self.seen, self.delivered, self.log = spec, Usage(), set(), False, spec.run_log.open("w", encoding="utf-8")


class OpenCodePrompt:
    name = "opencode"

    def __init__(self, sink, server: Server):
        self.sink, self.server = sink, server
        self.turns: dict[str, Tracked] = {}      # session -> tracked hub turn
        self.human: dict[str, bool] = {}         # session -> a human input is executing
        self.known: set[str] = set()             # sessions this server has reported (routes approvals)
        self.lock = threading.Lock()
        self.ready = threading.Event()
        threading.Thread(target=self._listen, daemon=True).start()

    def start(self, spec: TurnSpec) -> dict:
        self.ready.wait(30)  # subscribe before posting, or the turn end could be missed
        sid = spec.session
        if sid is None:
            prov, mid = spec.agent["model"].split("/", 1)
            sid = self.server.api("POST", "/api/session", {
                "title": f"xmuse {spec.agent['id']}", "model": {"providerID": prov, "id": mid},
                "location": {"directory": str(spec.cwd)}})["data"]["id"]
        self.known.add(sid)
        with self.lock:
            self.turns[sid] = Tracked(spec)
        try:
            self.server.api("POST", f"/api/session/{sid}/prompt", {
                "text": spec.prompt, "delivery": "queue",
                "metadata": {"xmuse": {"turn": spec.turn_id, "agent": spec.agent["id"]}}})
        except Exception as e:
            with self.lock:
                self.turns.pop(sid, None)
            raise RuntimeError(f"prompt failed: {e}") from e
        return {"handle": sid}

    def interrupt(self, turn_id: int) -> None:
        for sid, t in list(self.turns.items()):
            if t.spec.turn_id == turn_id:
                self.server.api("POST", f"/api/session/{sid}/interrupt")

    def _listen(self):
        while True:
            try:
                for ev in self.server.events():
                    if ev.get("type") == "server.connected":
                        self.ready.set()
                    self.handle(ev)
            except Exception:  # server restarting or gone; reconnect
                self.ready.clear()
                time.sleep(1)

    def handle(self, ev: dict) -> None:
        typ, d = ev.get("type", ""), ev.get("data") or {}
        sid = d.get("sessionID")
        if sid:
            self.known.add(sid)
        with self.lock:
            t = self.turns.get(sid)
        if t is not None:
            t.log.write(json.dumps(ev) + "\n")
            t.log.flush()  # evidence.py reads this log while the turn still runs (at xmuse_done)
        if typ == "session.inbox.enqueued":
            meta = ((d.get("item") or {}).get("payload") or {}).get("metadata") or {}
            if "xmuse" not in meta:
                self.human[sid] = True
        elif typ == "session.inbox.delivered" and t is not None:
            t.delivered = True
        elif typ == "session.step.ended" and t is not None and ev.get("id") not in t.seen:
            t.seen.add(ev.get("id"))
            tok = d.get("tokens") or {}
            c = tok.get("cache") or {}
            u = t.usage
            u.input += tok.get("input", 0)
            u.cache_read += c.get("read", 0)
            u.cache_write += c.get("write", 0)
            u.output += tok.get("output", 0) + tok.get("reasoning", 0)
            u.context = tok.get("input", 0) + c.get("read", 0) + c.get("write", 0)
            u.calls += 1
            if d.get("files"):
                u.mode = "code"
        elif typ == "session.step.started" and t is not None:
            t.usage.model = (d.get("model") or {}).get("id", t.usage.model)
        elif typ == "session.tool.input.started" and t is not None and d.get("name") in CODE_TOOLS:
            t.usage.mode = "code"
        elif typ == "session.compaction.ended":  # `failed` keeps the context, so the watermark stays
            self.sink.compacted(sid)
        elif typ == "permission.asked":
            self.sink.approval(self._agent(sid), sid, d)
        elif typ in END:
            was_human = self.human.pop(sid, False)
            if t is not None and t.delivered:
                with self.lock:
                    self.turns.pop(sid, None)
                t.log.close()
                err = json.dumps(d.get("error"))[:300] if d.get("error") else None
                self.sink.turn_ended(TurnEnd(t.spec.turn_id, END[typ], sid, t.usage, err))
            elif was_human:
                self.sink.kick()

    def _agent(self, sid):
        t = self.turns.get(sid)
        return t.spec.agent["id"] if t else None


class _AllReady:
    def __init__(self, prompts):
        self.prompts = prompts

    def wait(self, timeout: float | None = None) -> bool:
        end = None if timeout is None else time.time() + timeout
        return all(p.ready.wait(None if end is None else max(0.0, end - time.time())) for p in list(self.prompts()))


class _Router:
    """The engine's headless adapter: each turn goes to its agent's own server."""
    name = OpenCodePrompt.name

    def __init__(self, driver: "OpenCodeDriver"):
        self.driver = driver
        self.ready = _AllReady(lambda: driver.prompts.values())

    def start(self, spec: TurnSpec) -> dict:
        return self.driver.prompt_for(spec.agent["id"]).start(spec)

    def interrupt(self, turn_id: int) -> None:
        for p in list(self.driver.prompts.values()):
            p.interrupt(turn_id)

    @property
    def turns(self) -> dict:
        return {sid: t for p in list(self.driver.prompts.values()) for sid, t in p.turns.items()}

    @property
    def human(self) -> dict:
        return {sid: h for p in list(self.driver.prompts.values()) for sid, h in p.human.items()}


class OpenCodeDriver:
    """Several OpenCode agents per workspace (T12): each runs on its own `opencode serve`, whose OPENCODE_CONFIG
    names that agent. Servers given one shared `base` (tests with one fake server) share one listener."""
    vendor = "opencode"
    push = None  # one path for both modes: the server serializes TUI and hub input

    def __init__(self, sink, servers: dict[str, Server], start: bool = True):
        self.sink, self.servers, self.autostart = sink, dict(servers), start
        self.prompts: dict[str, OpenCodePrompt] = {}  # server base -> listener
        self.lock = threading.Lock()
        for aid in list(self.servers):
            self.prompt_for(aid)
        self.headless = _Router(self)

    def prompt_for(self, agent_id: str) -> OpenCodePrompt:
        with self.lock:
            srv = self.servers.get(agent_id)
            if srv is None:  # agent added while the hub runs
                srv = self.servers[agent_id] = Server(self.sink.ws, self.sink.state, agent_id,
                                                      binary=self.sink.cfg.get("opencode_bin", "opencode"))
                if self.autostart:
                    srv.start()
            if srv.base not in self.prompts:
                self.prompts[srv.base] = OpenCodePrompt(self.sink, srv)
            return self.prompts[srv.base]

    @property
    def server(self) -> Server:  # single-instance callers (one OpenCode agent)
        return next(iter(self.servers.values()))

    def server_for(self, session: str, agent_id: str | None = None) -> Server:
        """The server that owns a session: the agent's own when known (session ids are only unique per server),
        else the listener that has seen it, else the agent recorded in hub.db."""
        if agent_id in self.servers:
            return self.servers[agent_id]
        for p in list(self.prompts.values()):
            if session in p.known:
                return p.server
        r = self.sink.db().execute("select agent_id from sessions where vendor_session=?", (session,)).fetchone()
        if r and r[0] in self.servers:
            return self.servers[r[0]]
        return self.server

    def presence(self, agent: dict, session: str | None) -> Presence:
        return Presence("free", bool(session and self.prompt_for(agent["id"]).human.get(session)), False)

    def on_hook(self, agent: dict, event: str, payload: dict) -> bool:
        return False  # the SSE stream carries everything

    def precheck(self, agent: dict, ws: Path, wait: float = 30) -> str | None:
        """The model must be in the server's catalog (filled in shortly after start; costs no tokens)."""
        prov, mid = agent["model"].split("/", 1)
        end = time.time() + wait
        srv = self.prompt_for(agent["id"]).server
        while True:
            models = srv.api("GET", "/api/model")["data"]
            if any(m.get("providerID") == prov and m.get("id") == mid for m in models):
                return None
            if time.time() > end:
                return f"not in the OpenCode catalog ({len(models)} models; is provider {prov} logged in?)"
            time.sleep(1)

    def approve(self, session: str, request_id: str, decision: str, agent_id: str | None = None) -> None:
        self.server_for(session, agent_id).api("POST", f"/api/session/{session}/permission/{request_id}/reply",
                                     {"decision": decision})

    write_config = staticmethod(write_config)

    def attach_command(self, agent: dict, session: str | None) -> str:
        srv = self.prompt_for(agent["id"]).server
        return (f"OPENCODE_SERVER_PASSWORD=$(cat {srv.pw}) "
                f"opencode --server {srv.base}{' --session ' + session if session else ''}")

    def close(self) -> None:
        for srv in list(self.servers.values()):
            srv.stop()
