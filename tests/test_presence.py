"""Claude session lease, channel push and human-input admission (hook reports as Claude sends them)."""
import json
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest


@pytest.fixture
def tui():
    """A live process standing in for the interactive Claude Code TUI (its pid is the lease holder)."""
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(120)"])
    yield p
    p.kill()


class Channel:
    """The shim's push endpoint inside a TUI: records pushes that carry the registered nonce."""

    def __init__(self, nonce="n0nce"):
        self.nonce, self.pushes, ch = nonce, [], self

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers["content-length"]))
                if self.headers.get("x-xmuse-nonce") != ch.nonce:
                    self.send_response(403)
                    self.end_headers()
                    return
                ch.pushes.append(json.loads(body))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok\n")

            def log_message(self, *a):
                pass
        self.srv = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()


def first_session(h):
    h.plan_claude({})
    h.send("claude-1", "warm up")
    h.wait_quiet()
    return h.q("select vendor_session from sessions where state='current'")[0]["vendor_session"]


def write_transcript(h, sid, tokens):
    from xmuse.adapters.claude import transcript
    path = transcript(h.ws, sid)
    path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"type": "assistant", "uuid": "u1", "parentUuid": None, "timestamp": ts,
                            "message": {"id": "m1", "model": "claude-opus-5-5", "content": [
                                {"type": "tool_use", "name": "Edit", "input": {}}],
                                "usage": {"input_tokens": 3, "cache_read_input_tokens": tokens,
                                          "cache_creation_input_tokens": 100, "output_tokens": 50}}}) + "\n")
    return path


def test_tui_lease_blocks_headless_until_session_end(make, tui):
    h = make()
    sid = first_session(h)
    h.hook("claude-1", "SessionStart", pid=tui.pid, entrypoint="cli", session_id=sid, source="resume")
    h.send("claude-1", "while the human has the TUI open")
    time.sleep(0.5)
    assert len(h.turns()) == 1  # no headless write into a session a TUI holds
    assert h.q("select state from deliveries order by id desc limit 1")[0]["state"] == "queued"
    h.plan_claude({})
    h.hook("claude-1", "SessionEnd", pid=tui.pid, entrypoint="cli", session_id=sid, reason="exit")
    h.wait_quiet()
    c = h.claude_calls()[-1]
    assert c["argv"][c["argv"].index("--resume") + 1] == sid
    assert h.q("select count(*) n from leases")[0]["n"] == 0


def test_channel_push_and_stop_hook_close_the_turn(make, tui):
    h = make()
    sid = first_session(h)
    ch = Channel()
    h.hook("claude-1", "SessionStart", pid=tui.pid, entrypoint="cli", session_id=sid, source="resume")
    assert h.post("/v1/shim/register", {"port": ch.port, "nonce": ch.nonce, "session_id": sid,
                                        "claude_pid": tui.pid}, h.token("claude-1"))["result"]["ok"]
    m = h.send("claude-1", "review please")
    h.wait(lambda: ch.pushes, what="channel push")
    assert "review please" in ch.pushes[0]["content"] and ch.pushes[0]["meta"]["turn"] == "2"
    [t] = h.q("select * from turns where id=2")
    assert t["adapter"] == "claude_channel" and t["state"] == "running" and t["fresh"] == 0
    h.hook("claude-1", "UserPromptSubmit", pid=tui.pid, entrypoint="cli", session_id=sid,
           prompt='<channel source="xmuse" turn="2">review please</channel>')
    assert h.q("select human_turn from leases")[0]["human_turn"] == 0  # channel input is not a human
    path = write_transcript(h, sid, 40_000)
    h.hook("claude-1", "Stop", pid=tui.pid, entrypoint="cli", session_id=sid, transcript_path=str(path))
    h.wait_quiet()
    t = h.turns()[1]
    assert t["state"] == "succeeded" and t["mode"] == "code"
    assert (t["cache_read"], t["output"], t["context"]) == (40_000, 50, 40_103)
    assert h.q("select state from deliveries where message_id=?", m["id"])[0]["state"] == "done"
    assert len(h.claude_calls()) == 1  # nothing ran headless


def test_human_input_defers_admission_until_their_turn_ends(make, tui):
    h = make()
    sid = first_session(h)
    ch = Channel()
    h.hook("claude-1", "SessionStart", pid=tui.pid, entrypoint="cli", session_id=sid, source="resume")
    h.post("/v1/shim/register", {"port": ch.port, "nonce": ch.nonce, "session_id": sid, "claude_pid": tui.pid},
           h.token("claude-1"))
    h.hook("claude-1", "UserPromptSubmit", pid=tui.pid, entrypoint="cli", session_id=sid, prompt="human typing")
    h.send("claude-1", "peer message")
    time.sleep(0.5)
    assert ch.pushes == [] and len(h.turns()) == 1
    h.hook("claude-1", "Stop", pid=tui.pid, entrypoint="cli", session_id=sid)
    h.wait(lambda: ch.pushes, what="push after the human turn")
    assert "peer message" in ch.pushes[0]["content"]


def test_wrong_nonce_push_fails_the_turn(make, tui):
    h = make()
    sid = first_session(h)
    ch = Channel()
    h.hook("claude-1", "SessionStart", pid=tui.pid, entrypoint="cli", session_id=sid)
    h.post("/v1/shim/register", {"port": ch.port, "nonce": "other", "session_id": sid, "claude_pid": tui.pid},
           h.token("claude-1"))
    h.send("claude-1", "x")
    h.wait(lambda: len(h.turns()) == 2 and h.turns()[1]["state"] == "failed", what="failed push")
    assert "channel push failed" in h.turns()[1]["error"]


def test_dead_tui_pid_releases_the_lease(make):
    h = make()
    sid = first_session(h)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])
    dead.wait()
    h.hook("claude-1", "SessionStart", pid=dead.pid, entrypoint="cli", session_id=sid)
    h.plan_claude({})
    h.send("claude-1", "after the TUI crashed")
    h.wait_quiet()
    assert len(h.claude_calls()) == 2 and h.q("select count(*) n from leases")[0]["n"] == 0


def test_tui_new_session_is_adopted(make, tui):
    h = make()
    sid = first_session(h)
    h.hook("claude-1", "SessionStart", pid=tui.pid, entrypoint="cli", session_id="tui-new-session", source="startup")
    rows = h.q("select vendor_session, origin, state from sessions order by id")
    assert rows == [{"vendor_session": sid, "origin": "hub", "state": "retired"},
                    {"vendor_session": "tui-new-session", "origin": "tui", "state": "current"}]
    h.plan_claude({})
    h.hook("claude-1", "SessionEnd", pid=tui.pid, entrypoint="cli", session_id="tui-new-session")
    h.send("claude-1", "continue where the human left off")
    h.wait_quiet()
    c = h.claude_calls()[-1]
    assert c["argv"][c["argv"].index("--resume") + 1] == "tui-new-session"


def test_headless_hooks_are_ignored(make):
    h = make()
    sid = first_session(h)
    h.hook("claude-1", "SessionStart", pid=1, entrypoint="sdk-cli", session_id=sid)
    h.hook("claude-1", "UserPromptSubmit", pid=1, entrypoint="sdk-cli", session_id=sid, prompt="x")
    assert h.q("select count(*) n from leases")[0]["n"] == 0


def test_hook_script_reports_to_the_hub(make, tui):
    """hook.py as Claude runs it: env from settings.json, payload on stdin."""
    from xmuse.config import HOOK
    h = make()
    payload = {"session_id": "s-hook", "hook_event_name": "SessionStart", "source": "startup",
               "transcript_path": "/x"}
    env = {"XMUSE_STATE": str(h.state), "XMUSE_AGENT": "claude-1", "CLAUDE_PID": str(tui.pid),
           "CLAUDE_CODE_ENTRYPOINT": "cli", "PATH": "/usr/bin:/bin",
           **{k: os.environ[k] for k in ("SYSTEMROOT",) if k in os.environ}}  # Windows sockets need it
    subprocess.run([sys.executable, str(HOOK), "SessionStart"], input=json.dumps(payload), text=True, env=env,
                   check=True, timeout=10)
    assert h.q("select pid, vendor_session, holder from leases")[0] == {"pid": tui.pid, "vendor_session": "s-hook",
                                                                       "holder": "tui"}
    # never blocks Claude, even when the hub is gone
    r = subprocess.run([sys.executable, str(HOOK), "Stop"], input="{}", text=True,
                       env={**env, "XMUSE_STATE": "/nonexistent"}, timeout=10)
    assert r.returncode == 0


def test_shim_registration_needs_an_agent_token(make):
    h = make()
    bad = h.post("/v1/shim/register", {"port": 1, "nonce": "x", "claude_pid": 1}, "xmt_wrong")
    assert bad["status"] == 401
    human = h.post("/v1/shim/register", {"port": 1, "nonce": "x", "claude_pid": 1}, h.token("human"))
    assert human["error"]["code"] == "not_found"
