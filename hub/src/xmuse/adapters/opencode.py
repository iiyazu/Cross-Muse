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
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from ..config import SHIM
from ..env import clean_env
from .base import Presence, TurnEnd, TurnSpec, Usage

END = {"session.execution.succeeded": "succeeded", "session.execution.failed": "failed",
       "session.execution.interrupted": "interrupted"}
CODE_TOOLS = {"edit", "write", "patch", "apply_patch", "multiedit", "shell", "bash"}
# Consequential shell commands go to the human (design §4.7); everything else keeps OpenCode's defaults.
ASK_SHELL = ["git push*", "git merge*", "git rebase*", "git reset --hard*", "git clean*", "git branch -D*",
             "git checkout -- *", "rm -r*", "rm -f*", "sudo *", "curl *", "wget *"]


_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=\S*\s+")


def strip_env(cmd: str) -> str:
    """Drop leading `NAME=value` assignments: `PYTHONPATH=x python -m unittest` -> `python -m unittest`."""
    cmd = cmd.strip()
    while (m := _ENV_ASSIGN.match(cmd)):
        cmd = cmd[m.end():].lstrip()
    return cmd


def shell_auto_ok(action: str | None, resources) -> bool:
    """True when every shell command in a permission request is outside ASK_SHELL once env prefixes are removed.

    OpenCode matches its rules against the raw command text, so an env prefix hides the command from
    the patterns (`PYTHONPATH=x git push` matches no `git push*` rule, and a prefixed harmless command
    can end up asked). The hub therefore decides for shell requests itself; anything matching ASK_SHELL
    still goes to the human.
    """
    if action != "shell" or not isinstance(resources, list) or not resources:
        return False
    return all(isinstance(r, str) and not any(fnmatch.fnmatchcase(strip_env(r), p) for p in ASK_SHELL)
               for r in resources)


def write_config(ws: Path, agent: dict, state: Path) -> list[Path]:
    cfg = {
        "$schema": "https://opencode.ai/config.json",
        "mcp": {"servers": {"xmuse": {"type": "local", "command": ["node", str(SHIM)],
                                      "environment": {"XMUSE_STATE": str(state), "XMUSE_AGENT": agent["id"]}}}},
        "permissions": [{"action": "xmuse_*", "resource": "*", "effect": "allow"},
                        *({"action": "shell", "resource": r, "effect": "ask"} for r in ASK_SHELL),
                        # the same commands behind an env prefix (`FOO=1 git push`) must still ask
                        *({"action": "shell", "resource": "*=* " + r, "effect": "ask"} for r in ASK_SHELL)],
    }
    (ws / "opencode.json").write_text(json.dumps(cfg, indent=2) + "\n")
    return [ws / "opencode.json"]


class Server:
    """The workspace's dedicated OpenCode server (own port and password file; never the user's service)."""

    def __init__(self, ws: Path, state: Path, port: int | None = None, base: str | None = None):
        self.ws, self.state, self.proc = ws, state, None
        pw = state / "oc.pass"
        if not pw.exists():
            pw.write_text(secrets.token_urlsafe(24))
            pw.chmod(0o600)
        self.auth = "Basic " + base64.b64encode(f"opencode:{pw.read_text().strip()}".encode()).decode()
        self.base = base or f"http://127.0.0.1:{port or _free_port()}"

    def start(self, timeout: float = 60) -> None:
        port = self.base.rsplit(":", 1)[1]
        log = (self.state / "logs" / "opencode.log").open("a")
        self.proc = subprocess.Popen(
            ["opencode", "serve", "--hostname", "127.0.0.1", "--port", port, "--print-logs"],
            cwd=self.ws, env=clean_env({"OPENCODE_SERVER_PASSWORD": (self.state / "oc.pass").read_text().strip()}),
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            start_new_session=True)

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
        if self.proc and self.proc.poll() is None:
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
        self.spec, self.usage, self.seen, self.delivered, self.log = spec, Usage(), set(), False, spec.run_log.open("w")


class OpenCodePrompt:
    name = "opencode"

    def __init__(self, sink, server: Server):
        self.sink, self.server = sink, server
        self.turns: dict[str, Tracked] = {}      # session -> tracked hub turn
        self.human: dict[str, bool] = {}         # session -> a human input is executing
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
        with self.lock:
            t = self.turns.get(sid)
        if t is not None:
            t.log.write(json.dumps(ev) + "\n")
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


class OpenCodeDriver:
    vendor = "opencode"
    push = None  # one path for both modes: the server serializes TUI and hub input

    def __init__(self, sink, server: Server):
        self.server = server
        self.headless = OpenCodePrompt(sink, server)

    def presence(self, agent: dict, session: str | None) -> Presence:
        return Presence("free", bool(session and self.headless.human.get(session)), False)

    def on_hook(self, agent: dict, event: str, payload: dict) -> bool:
        return False  # the SSE stream carries everything

    def precheck(self, agent: dict, ws: Path, wait: float = 30) -> str | None:
        """The model must be in the server's catalog (filled in shortly after start; costs no tokens)."""
        prov, mid = agent["model"].split("/", 1)
        end = time.time() + wait
        while True:
            models = self.server.api("GET", "/api/model")["data"]
            if any(m.get("providerID") == prov and m.get("id") == mid for m in models):
                return None
            if time.time() > end:
                return f"not in the OpenCode catalog ({len(models)} models; is provider {prov} logged in?)"
            time.sleep(1)

    def approve(self, session: str, request_id: str, decision: str) -> None:
        self.server.api("POST", f"/api/session/{session}/permission/{request_id}/reply", {"decision": decision})

    write_config = staticmethod(write_config)

    def attach_command(self, agent: dict, session: str | None) -> str:
        return (f"OPENCODE_SERVER_PASSWORD=$(cat {self.server.state / 'oc.pass'}) "
                f"opencode --server {self.server.base}{' --session ' + session if session else ''}")

    def close(self) -> None:
        self.server.stop()
