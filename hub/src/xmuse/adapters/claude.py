"""Claude Code: headless `-p --resume` (autonomous) and channel push (human present).

Lease (M0 §4): Claude does not serialize writers; a TUI and a headless resume on the same
session silently fork it. Project hooks report TUI ownership (SessionStart/SessionEnd with
CLAUDE_PID), human input (UserPromptSubmit not starting with "<channel") and turn end (Stop).
While a TUI holds the session the hub never writes headless; it pushes through the shim's
channel endpoint or waits. A transcript branch count before/after each resume is the backstop.
"""
import json
import os
import re
import signal
import subprocess
import threading
import time
import urllib.request
import uuid
from datetime import datetime
from pathlib import Path

from .. import db
from ..config import SHIM
from ..env import clean_env
from .base import Presence, TurnEnd, TurnSpec, Usage

CODE_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit", "Bash"}


def transcript(cwd: Path, session: str) -> Path:
    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(cwd)) / f"{session}.jsonl"


def branch_points(path: Path) -> int:
    """Parents with more than one user prompt as child: two writers resumed the same leaf (ported from
    spikes/cc-tree.py). Parallel tool calls also give a parent several children (one assistant record
    per tool_use, results hanging off different records), so only prompts count, not tool results."""
    if not path.exists():
        return 0
    kids: dict = {}
    for line in path.open():
        o = json.loads(line)
        if o.get("type") != "user" or "uuid" not in o or o.get("isSidechain"):
            continue
        c = (o.get("message") or {}).get("content")
        if isinstance(c, list) and any(isinstance(x, dict) and x.get("type") == "tool_result" for x in c):
            continue
        kids.setdefault(o.get("parentUuid"), []).append(o["uuid"])
    return sum(1 for p, k in kids.items() if p is not None and len(k) > 1)


def parse_stream(lines) -> tuple[dict, Usage]:
    """stream-json of one `claude -p` run -> (result info, usage). result.usage is per run."""
    info, u, last, seen = {}, Usage(), None, set()
    for line in lines:
        if not line.startswith("{"):
            continue
        o = json.loads(line)
        if o.get("type") == "system" and o.get("subtype") == "init":
            info["session"], u.model = o.get("session_id"), o.get("model", "")
        elif o.get("type") == "assistant":
            m = o["message"]
            seen.add(m.get("id"))
            last = m.get("usage") or last
            if any(c.get("type") == "tool_use" and c.get("name") in CODE_TOOLS for c in m.get("content", [])):
                u.mode = "code"
        elif o.get("type") == "rate_limit_event" and o["rate_limit_info"].get("status") == "rejected":
            info["retry_at"] = o["rate_limit_info"].get("resetsAt") or time.time() + 3600
        elif o.get("type") == "result":
            r = o.get("usage") or {}
            u.input, u.output = r.get("input_tokens", 0), r.get("output_tokens", 0)
            u.cache_read, u.cache_write = r.get("cache_read_input_tokens", 0), r.get("cache_creation_input_tokens", 0)
            info.update(session=o.get("session_id"), ok=o.get("subtype") == "success" and not o.get("is_error"),
                        error=None if o.get("subtype") == "success" else o.get("subtype"),
                        denied=[d.get("tool_name") for d in o.get("permission_denials") or []])
    if last:
        u.context = last.get("input_tokens", 0) + last.get("cache_read_input_tokens", 0) + \
            last.get("cache_creation_input_tokens", 0)
    u.calls = len(seen)
    return info, u


def transcript_usage(path: Path, after_uuid: str | None = None, since: float = 0) -> Usage:
    """Usage of an interactive (channel) turn read from the transcript (ported from spikes/cc-usage.py)."""
    u, seen, last = Usage(), set(), None
    for line in path.open():
        o = json.loads(line)
        ts = o.get("timestamp")
        if o.get("type") != "assistant" or not ts or _epoch(ts) < since:
            continue
        m = o.get("message") or {}
        if m.get("id") in seen:
            continue
        seen.add(m.get("id"))
        x = m.get("usage") or {}
        u.input += x.get("input_tokens", 0)
        u.cache_read += x.get("cache_read_input_tokens", 0)
        u.cache_write += x.get("cache_creation_input_tokens", 0)
        u.output += x.get("output_tokens", 0)
        u.model = m.get("model", u.model)
        last = x
        if any(c.get("type") == "tool_use" and c.get("name") in CODE_TOOLS for c in m.get("content", [])):
            u.mode = "code"
    if last:
        u.context = last.get("input_tokens", 0) + last.get("cache_read_input_tokens", 0) + \
            last.get("cache_creation_input_tokens", 0)
    u.calls = len(seen)
    return u


def _epoch(ts: str) -> float:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def write_config(ws: Path, agent: dict, state: Path) -> list[Path]:
    env = {"XMUSE_STATE": str(state), "XMUSE_AGENT": agent["id"], "XMUSE_CHANNEL": "1"}
    mcp = {"mcpServers": {"xmuse": {"command": "node", "args": [str(SHIM)], "env": env}}}
    (ws / ".mcp.json").write_text(json.dumps(mcp, indent=2) + "\n")
    hook = f"XMUSE_STATE={state} XMUSE_AGENT={agent['id']} python3 {Path(__file__).parents[1] / 'hook.py'}"
    hooks = {ev: [{"hooks": [{"type": "command", "command": f"{hook} {ev}", "timeout": 10}]}]
             for ev in ("SessionStart", "SessionEnd", "UserPromptSubmit", "Stop")}
    settings = {"enabledMcpjsonServers": ["xmuse"], "permissions": {"allow": ["mcp__xmuse__*"]}, "hooks": hooks}
    (ws / ".claude").mkdir(exist_ok=True)
    (ws / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2) + "\n")
    return [ws / ".mcp.json", ws / ".claude" / "settings.json"]


class ClaudeResume:
    name = "claude_resume"

    def __init__(self, sink, claude_bin: str = "claude"):
        self.sink, self.bin, self.procs = sink, claude_bin, {}

    def start(self, spec: TurnSpec) -> dict:
        s = db.settings(spec.agent)
        sid = spec.session or str(uuid.uuid4())
        cmd = [self.bin, "-p", spec.prompt, "--output-format", "stream-json", "--verbose",
               "--model", spec.agent["model"], *(["--resume", sid] if spec.session else ["--session-id", sid]),
               "--permission-mode", s.get("permission_mode", "acceptEdits"),
               "--allowedTools", "mcp__xmuse__*", *s.get("allowed_tools", [])]
        before = branch_points(transcript(spec.cwd, sid)) if spec.session else 0
        err = spec.run_log.with_suffix(".err").open("w")
        p = subprocess.Popen(cmd, cwd=spec.cwd, env=clean_env(), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=err, text=True, start_new_session=True)
        self.procs[spec.turn_id] = {"p": p, "interrupted": False}
        threading.Thread(target=self._watch, args=(spec, p, sid, before, err), daemon=True).start()
        return {"pid": p.pid, "handle": sid}

    def _watch(self, spec: TurnSpec, p, sid: str, before: int, err):
        lines = []
        with spec.run_log.open("w") as out:
            for line in p.stdout:
                out.write(line)
                lines.append(line)
        p.wait()
        err.close()
        info, usage = parse_stream(lines)
        sid = info.get("session") or sid
        st = self.procs.pop(spec.turn_id, {})
        note = None
        if spec.session and branch_points(transcript(spec.cwd, sid)) > before:
            note = "fork_detected"
        if st.get("interrupted"):
            status, error = "interrupted", "interrupted by hub"
        elif info.get("ok"):
            status, error = "succeeded", None
        else:
            tail = spec.run_log.with_suffix(".err").read_text()[-400:].strip()
            status, error = "failed", info.get("error") or f"exit {p.returncode}: {tail}"
        retry_at = info.get("retry_at") if status == "failed" else None
        if retry_at:
            error = "usage limit reached"
        if info.get("denied"):
            note = (note + "; " if note else "") + "permission_denied: " + ", ".join(info["denied"])
        self.sink.turn_ended(TurnEnd(spec.turn_id, status, sid, usage, error, note, retry_at))

    def interrupt(self, turn_id: int) -> None:
        st = self.procs.get(turn_id)
        if not st:
            return
        st["interrupted"] = True
        try:
            os.killpg(st["p"].pid, signal.SIGINT)
            try:
                st["p"].wait(5)
            except subprocess.TimeoutExpired:
                os.killpg(st["p"].pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


class ClaudeChannel:
    """Push into a live TUI through the shim's channel endpoint; the TUI's Stop hook ends the turn."""
    name = "claude_channel"

    def __init__(self, sink, dbf):
        self.sink, self.db, self.turns = sink, dbf, {}  # session -> turn info

    def start(self, spec: TurnSpec) -> dict:
        lease = db.row(self.db().execute(
            "select * from leases where vendor_session=? and holder='tui' and channel_url is not null"
            " order by updated_at desc limit 1", (spec.session,)))
        self.turns[spec.session] = {"turn_id": spec.turn_id, "since": time.time(), "cwd": spec.cwd}
        try:
            req = urllib.request.Request(lease["channel_url"], method="POST",
                                         data=json.dumps({"content": spec.prompt,
                                                          "meta": {"turn": str(spec.turn_id)}}).encode(),
                                         headers={"x-xmuse-nonce": lease["channel_nonce"],
                                                  "content-type": "application/json"})
            urllib.request.urlopen(req, timeout=10).read()
        except Exception as e:  # the TUI went away between presence() and start()
            self.turns.pop(spec.session, None)
            threading.Thread(target=self.sink.turn_ended, daemon=True, args=(
                TurnEnd(spec.turn_id, "failed", spec.session, error=f"channel push failed: {e}"),)).start()
        return {"pid": lease["pid"], "handle": spec.session}

    def stopped(self, session: str, transcript_path: str | None) -> bool:
        t = self.turns.pop(session, None)
        if t is None:
            return False
        path = Path(transcript_path) if transcript_path else transcript(t["cwd"], session)
        usage = transcript_usage(path, since=t["since"] - 1) if path.exists() else Usage()
        self.sink.turn_ended(TurnEnd(t["turn_id"], "succeeded", session, usage))
        return True

    def interrupt(self, turn_id: int) -> None:
        """A TUI turn cannot be interrupted remotely; stop tracking it (the human can press Esc)."""
        for s, t in list(self.turns.items()):
            if t["turn_id"] == turn_id:
                self.turns.pop(s)
                self.sink.turn_ended(TurnEnd(turn_id, "interrupted", s, error="stopped tracking channel turn"))


class ClaudeDriver:
    vendor = "claude"

    def __init__(self, sink, dbf, claude_bin: str = "claude"):
        self.db = dbf
        self.headless = ClaudeResume(sink, claude_bin)
        self.push = ClaudeChannel(sink, dbf)

    def presence(self, agent: dict, session: str | None) -> Presence:
        if session is None:
            return Presence()
        for lease in db.rows(self.db().execute(
                "select * from leases where vendor_session=? and holder='tui'", (session,))):
            if _alive(lease["pid"]):
                return Presence("tui", bool(lease["human_turn"]), bool(lease["channel_url"]))
            with db.tx(self.db()):
                self.db().execute("delete from leases where pid=?", (lease["pid"],))
        return Presence()

    def on_hook(self, agent: dict, event: str, p: dict) -> bool:
        """Hook report from hook.py: {event, session_id, pid (CLAUDE_PID), entrypoint, channels, prompt, ...}."""
        if p.get("entrypoint") != "cli":  # headless runs are hub-owned; their hooks carry no news
            return False
        pid, sid, now = p["pid"], p.get("session_id"), db.now()
        with db.tx(self.db()):
            if event == "SessionStart":
                self.db().execute(
                    "insert into leases(pid, agent_id, vendor_session, holder, entrypoint, updated_at)"
                    " values(?,?,?,?,?,?) on conflict(pid) do update set vendor_session=excluded.vendor_session,"
                    " updated_at=excluded.updated_at", (pid, agent["id"], sid, "tui", "cli", now))
                self._adopt(agent["id"], sid)
            elif event == "SessionEnd":
                self.db().execute("delete from leases where pid=?", (pid,))
            elif event == "UserPromptSubmit":
                human = not str(p.get("prompt", "")).lstrip().startswith("<channel")
                if human:
                    self.db().execute("update leases set human_turn=1, updated_at=? where pid=?", (now, pid))
            elif event == "Stop":
                self.db().execute("update leases set human_turn=0, updated_at=? where pid=?", (now, pid))
        if event == "Stop":
            self.push.stopped(sid, p.get("transcript_path"))
        return True

    def register_shim(self, agent: dict, p: dict) -> None:
        """The shim inside a TUI announces its push endpoint (dynamic port) and nonce."""
        with db.tx(self.db()):
            self.db().execute(
                "insert into leases(pid, agent_id, vendor_session, holder, entrypoint, channel_url, channel_nonce,"
                " updated_at) values(?,?,?,?,?,?,?,?) on conflict(pid) do update set"
                " channel_url=excluded.channel_url, channel_nonce=excluded.channel_nonce,"
                " vendor_session=coalesce(leases.vendor_session, excluded.vendor_session),"
                " updated_at=excluded.updated_at",
                (p["claude_pid"], agent["id"], p.get("session_id"), "tui", "cli",
                 f"http://127.0.0.1:{int(p['port'])}/push", p["nonce"], db.now()))

    def _adopt(self, agent_id: str, sid: str) -> None:
        """A TUI opened for this agent becomes its current session: the hub continues it after."""
        cur = db.row(self.db().execute("select * from sessions where agent_id=? and state='current'", (agent_id,)))
        if cur and cur["vendor_session"] == sid:
            return
        if cur:
            self.db().execute("update sessions set state='retired', retired_at=? where id=?", (db.now(), cur["id"]))
        old = db.row(self.db().execute("select * from sessions where agent_id=? and vendor_session=?", (agent_id, sid)))
        if old:
            self.db().execute("update sessions set state='current', retired_at=null where id=?", (old["id"],))
        else:
            self.db().execute("insert into sessions(agent_id, vendor_session, origin, created_at) values(?,?,?,?)",
                              (agent_id, sid, "tui", db.now()))

    write_config = staticmethod(write_config)

    def attach_command(self, agent: dict, session: str | None) -> str:
        return (f"claude --model {agent['model']} {'--resume ' + session if session else ''}"
                " --dangerously-load-development-channels server:xmuse")

    def close(self) -> None:
        for t in list(self.headless.procs):
            self.headless.interrupt(t)
