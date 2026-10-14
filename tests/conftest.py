"""Test harness: a real hub (HTTP + engine thread) in-process, with fake agents replaying M0 recordings."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))
from fakes.fake_opencode import FakeOpenCode  # noqa: E402
from xmuse import auth, db, init as xinit, registry  # noqa: E402
from xmuse.config import MODELS, family  # noqa: E402
from xmuse.server import Hub, digest  # noqa: E402

FAKE_CLAUDE = Path(__file__).parent / "fakes" / "fake_claude.py"
FAKE_DSH = Path(__file__).parent / "fakes" / "fake_dsh.py"
FAKE_AGY = Path(__file__).parent / "fakes" / "fake_agy.py"
FAKE_OC_SERVE = Path(__file__).parent / "fakes" / "fake_opencode_serve.py"


class Harness:
    def __init__(self, tmp: Path, agents, cfg: dict):
        human_check = cfg.pop("_human_check", False)
        oc_serve = cfg.pop("_oc_serve", False)  # one fake `opencode serve` subprocess per agent (T12)
        self.tmp, self.home = tmp, Path(os.environ["HOME"])
        self.ws = tmp / "ws"
        self.ws.mkdir(exist_ok=True)  # a test may create member directories inside it first
        if oc_serve and os.name == "nt":  # no shebangs: the hub runs a .py binary with its own interpreter
            cfg["opencode_bin"] = str(FAKE_OC_SERVE)
        elif oc_serve:
            wrapper = tmp / "fake-opencode"
            wrapper.write_text(f'#!/bin/sh\nexec {sys.executable} {FAKE_OC_SERVE} "$@"\n', encoding="utf-8")
            wrapper.chmod(0o755)
            cfg["opencode_bin"] = str(wrapper)
        subprocess.run(["git", "init", "-q", str(self.ws)], check=True)
        self.state = xinit.init(self.ws)
        c = json.loads((self.state / "config.json").read_text(encoding="utf-8"))
        (self.state / "config.json").write_text(json.dumps({**c, "sweep_interval": 3600, "dsh_exe": str(FAKE_DSH),
                                                            "dsh_backoff": 0.1, "dsh_home": str(tmp / "dsh-home"),
                                                            "agy_bin": str(FAKE_AGY),
                                                            **cfg}), encoding="utf-8")
        for i, (aid, vendor, *rest) in enumerate(agents):
            settings = rest[0] if rest else {}
            same_vendor = i and vendor in [v for _, v, *_ in agents[:i]]
            if vendor == "dsh" or vendor == "claude" and same_vendor and not settings.get("cwd"):
                self.add_raw(aid, vendor, settings)  # dsh: ws is not on C:\; a second claude in the same dir: one .mcp.json
            else:
                xinit.add_agent(self.state, aid, vendor, settings=settings)
        (self.home / "fake-claude").mkdir(parents=True, exist_ok=True)
        (self.home / "fake-dsh").mkdir(parents=True, exist_ok=True)
        (self.home / "fake-agy").mkdir(parents=True, exist_ok=True)
        self.oc = FakeOpenCode(self.state) if not oc_serve and any(v == "opencode" for _, v, *_ in agents) else None
        # the human-only admin check (peer.py) is exercised in test_trust.py; elsewhere tests drive admin calls
        self.hub = Hub(self.state, claude_bin=str(FAKE_CLAUDE), oc_base=self.oc and self.oc.base,
                       human_check=human_check)
        self.hub.start()
        # hub.start() ends with a kick that the engine thread handles asynchronously. Wait for it, or on a loaded machine
        # it can select the agents before a test pauses one and then admit a turn for mail queued afterwards.
        self.hub.engine.call(lambda: None)
        if "opencode" in self.hub.engine.drivers:
            assert self.hub.engine.drivers["opencode"].headless.ready.wait(5)

    def add_raw(self, aid, vendor, settings=None):
        """A second agent of the same vendor (project configs allow one; the engine does not care), or dsh."""
        tok = auth.issue(self.state, aid, "member")
        model = (settings or {}).pop("model", None) or MODELS[vendor]
        with db.tx(self.conn()) as c:
            c.execute("insert into agents(id, vendor, model, family, settings, token_digest, created_at)"
                      " values(?,?,?,?,?,?,?)", (aid, vendor, model, family(vendor, model), json.dumps(settings or {}),
                                                 digest(tok), time.time()))

    def close(self):
        self.hub.shutdown()
        if self.oc:
            self.oc.close()

    # ---- driving -------------------------------------------------------------------
    def conn(self):
        return db.connect(self.state / "hub.db")

    def q(self, sql, *args):
        return db.rows(self.conn().execute(sql, args))

    def post(self, path, body, token, session=None):
        port = json.loads((self.state / "hub.json").read_text(encoding="utf-8"))["port"]
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", data=json.dumps(body).encode(),
                                     headers={"authorization": f"Bearer {token}", "content-type": "application/json",
                                              **({"x-xmuse-session": session} if session else {})})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=10).read())
        except urllib.error.HTTPError as e:
            return {"status": e.code, **json.loads(e.read())}

    def key(self):
        """The sidebar key a local sidebar plugin would read from the registry dir."""
        return sidebar_key()

    def token(self, who):
        return (self.state / "tokens" / ("_admin" if who == "human" else who)).read_text(encoding="utf-8").strip()

    def admin(self, name, **body):
        return self.post(f"/v1/admin/{name}", body, self.token("human"))

    def send(self, to, body, mentions=(), kind="message", **kw):
        out = self.admin("send", to=to, body=body, mentions=list(mentions), kind=kind, **kw)
        assert "result" in out, out
        return out["result"]

    def tool(self, agent, name, _session=None, **args):
        return self.post(f"/v1/tools/{name}", {"args": args}, self.token(agent), _session)

    def hook(self, agent, event, **payload):
        return self.post("/v1/hooks/claude", {"event": event, **payload}, self.token(agent))

    def hook_dsh(self, agent, event, **payload):
        return self.post("/v1/hooks/dsh", {"event": event, **payload}, self.token(agent))

    def plan_claude(self, *steps):
        """Set the fake's plan; the step counter restarts at the first step."""
        (self.home / "fake-claude" / "plan.json").write_text(json.dumps(list(steps)), encoding="utf-8")
        (self.home / "fake-claude" / "n").write_text("0", encoding="utf-8")

    def plan_dsh(self, *steps):
        (self.home / "fake-dsh" / "plan.json").write_text(json.dumps(list(steps)), encoding="utf-8")
        (self.home / "fake-dsh" / "n").write_text("0", encoding="utf-8")

    def dsh_calls(self):
        f = self.home / "fake-dsh" / "calls.jsonl"
        return [json.loads(x) for x in f.open(encoding="utf-8")] if f.exists() else []

    def plan_agy(self, *steps):
        (self.home / "fake-agy" / "plan.json").write_text(json.dumps(list(steps)))
        (self.home / "fake-agy" / "n").write_text("0")

    def agy_calls(self):
        f = self.home / "fake-agy" / "calls.jsonl"
        return [json.loads(x) for x in f.open()] if f.exists() else []

    def claude_calls(self):
        f = self.home / "fake-claude" / "calls.jsonl"
        return [json.loads(x) for x in f.open(encoding="utf-8")] if f.exists() else []

    def wait(self, cond, timeout=10, what="condition"):
        end = time.time() + timeout
        while time.time() < end:
            if cond():
                return
            time.sleep(0.05)
        raise AssertionError(f"timeout waiting for {what}")

    def wait_quiet(self, timeout=15):
        def quiet():
            return not self.q("select 1 from turns where state='running'") and not self.q(
                "select 1 from deliveries d join agents a on a.id=d.recipient"
                " where d.state='queued' and d.wake=1 and a.paused=0")
        self.wait(quiet, timeout, "quiet hub")
        time.sleep(0.2)
        self.wait(quiet, timeout, "quiet hub")

    def turns(self):
        return self.q("select t.*, u.mode, u.input, u.cache_read, u.cache_write, u.output, u.context, u.calls"
                      " from turns t left join usage u on u.turn_id=t.id order by t.id")


@pytest.fixture(autouse=True)
def wsl_host(tmp_path, monkeypatch):
    """Host facts xmuse derives from WSL (host.py), fixed so the suite runs the same on WSL and plain Linux CI."""
    monkeypatch.setenv("WSL_DISTRO_NAME", "Ubuntu-Test")
    monkeypatch.delenv("XMUSE_WSL_DISTRO", raising=False)
    monkeypatch.setenv("XMUSE_WIN_HOME", str(tmp_path / "winhome"))
    # hubs.json and sidebar.key (registry.py) live in the user's state dir: never the real one in tests
    monkeypatch.setenv("XMUSE_REGISTRY_DIR", str(tmp_path / "registry"))


def sidebar_key() -> str:
    """The sidebar key of this test's registry dir (made by the first hub that started, or here)."""
    return registry.ensure_key()


def set_home(monkeypatch, path) -> None:
    """HOME for the fakes and POSIX; USERPROFILE is what Path.home() (and Claude Code) use on Windows."""
    monkeypatch.setenv("HOME", str(path))
    if os.name == "nt":
        monkeypatch.setenv("USERPROFILE", str(path))


posix_only = pytest.mark.skipif(os.name == "nt", reason="POSIX only (pty / process groups / ctty)")
# A hub in WSL reaches Windows-side apps through wsl.exe and UNC paths; a Windows-native hub (D1) needs neither.
wsl_hub = pytest.mark.skipif(os.name == "nt", reason="WSL-hub behaviour (wsl.exe, /mnt and UNC paths)")
windows_hub = pytest.mark.skipif(os.name != "nt", reason="Windows-native hub behaviour")


@pytest.fixture
def make(tmp_path, monkeypatch):
    set_home(monkeypatch, tmp_path / "home")
    monkeypatch.setenv("XMUSE_STATE_ROOT", str(tmp_path / "state"))
    monkeypatch.delenv("XMUSE_STATE", raising=False)
    (tmp_path / "home").mkdir()
    made = []

    def _make(agents=(("claude-1", "claude"),), **cfg):
        h = Harness(tmp_path, list(agents), cfg)
        made.append(h)
        return h
    yield _make
    for h in made:
        h.close()
