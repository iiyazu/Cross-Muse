"""Trust boundary (audit B2-1): holding the admin token is not enough for the actions that grant power.

Each admin call here runs in a separate process, the way an agent's shell (or the user's terminal) would make it:
  - no controlling terminal (how the hub starts agents)               -> refused
  - a controlling terminal, but inside a known agent process         -> refused (a TUI agent's shell tool)
  - a controlling terminal and outside every agent                    -> allowed (the user's terminal)
A Windows-native hub cannot identify the caller and refuses all three (test_windows_hub_refuses_every_caller).
"""
import json
import os
import subprocess
import sys

import pytest

from conftest import posix_only, windows_hub
from xmuse import db, peer

if os.name != "nt":
    import fcntl
    import termios


@windows_hub
def test_windows_hub_refuses_every_caller():
    """No /proc on Windows: the human-only admin actions fail closed; a person decides from a sidebar (D2)."""
    why = peer.human_check(50000, 50001, set())
    assert why and "sidebar" in why

CALL = r"""
import json, sys, urllib.request, urllib.error
port, token, path, body = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST", data=body.encode(),
                             headers={"authorization": "Bearer " + token, "content-type": "application/json"})
try:
    out = urllib.request.urlopen(req, timeout=10).read().decode()
except urllib.error.HTTPError as e:
    out = e.read().decode()
open(sys.argv[5], "w").write(out)
"""


def call_from_process(h, tmp_path, path, body, tty: bool) -> dict:
    """Make one admin request from a child process; with tty=True the child gets a pty as controlling terminal."""
    port = json.loads((h.state / "hub.json").read_text(encoding="utf-8"))["port"]
    out = tmp_path / f"out-{os.urandom(4).hex()}.json"
    argv = [sys.executable, "-c", CALL, str(port), h.token("human"), path, json.dumps(body), str(out)]
    if tty:
        master, slave = os.openpty()

        def ctty():
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
        p = subprocess.Popen(argv, stdin=slave, stdout=slave, stderr=slave, preexec_fn=ctty, close_fds=True)
        os.close(slave)
        p.wait(20)
        os.close(master)
    else:
        subprocess.run(argv, start_new_session=True, stdin=subprocess.DEVNULL, timeout=20, check=True)
    return json.loads(out.read_text(encoding="utf-8"))


def held_approval(h):
    h.oc.plan = [{"result": "hang"}]
    h.send("opencode-1", "go")
    h.wait(lambda: h.hub.engine.drivers["opencode"].headless.turns, what="tracked")
    h.oc.ask_permission("ses_fake1", "per_1", "cd sub && git push")
    h.wait(lambda: h.q("select * from approvals"), what="approval recorded")
    assert h.q("select state from approvals")[0]["state"] == "pending"  # the allowlist did not wave it through


OC = [("opencode-1", "opencode")]


@posix_only
def test_admin_approve_without_a_terminal_is_refused(make, tmp_path):
    h = make(OC, _human_check=True)
    held_approval(h)
    out = call_from_process(h, tmp_path, "/v1/admin/approve", {"id": "per_1", "decision": "once"}, tty=False)
    assert out["error"]["code"] == "human_only" and "no controlling terminal" in out["error"]["message"]
    for name, body in (("resume", {"agent": "opencode-1"}), ("align", {"op": "confirm", "id": "E1"})):
        out = call_from_process(h, tmp_path, f"/v1/admin/{name}", body, tty=False)
        assert out["error"]["code"] == "human_only", name
    assert h.q("select state from approvals")[0]["state"] == "pending"
    assert h.oc.replies == []
    h.admin("stop")


@posix_only
def test_admin_approve_from_inside_an_agent_process_is_refused(make, tmp_path):
    h = make(OC, _human_check=True)
    held_approval(h)
    with db.tx(h.conn()) as c:  # this test process plays a Claude TUI agent; its children are the agent's tools
        c.execute("insert into leases(pid, agent_id, vendor_session, holder, entrypoint, updated_at)"
                  " values(?,?,?,?,?,?)", (os.getpid(), "opencode-1", "s", "tui", "cli", 0))
    out = call_from_process(h, tmp_path, "/v1/admin/approve", {"id": "per_1", "decision": "once"}, tty=True)
    assert out["error"]["code"] == "human_only" and "inside agent process" in out["error"]["message"]
    assert h.oc.replies == []
    h.admin("stop")


@posix_only
def test_admin_approve_from_the_users_terminal_works(make, tmp_path):
    h = make(OC, _human_check=True)
    held_approval(h)
    out = call_from_process(h, tmp_path, "/v1/admin/approve", {"id": "per_1", "decision": "once"}, tty=True)
    assert out == {"result": {"ok": True}}
    assert h.q("select state, decision from approvals")[0] == {"state": "decided", "decision": "once"}
    assert any("decided by the user (terminal)" in n["body"] for n in h.q("select body from messages where kind='notice'"))
    h.admin("stop")


def test_operational_admin_calls_stay_open(make, tmp_path):
    """send/stop/log-style calls are not power grants: an agent-held token can still do them (marked via cli)."""
    h = make(OC, _human_check=True)
    h.oc.plan = [{"result": "done"}]
    out = call_from_process(h, tmp_path, "/v1/admin/send", {"to": "opencode-1", "body": "hi"}, tty=False)
    assert "result" in out
    h.wait_quiet()


TWO = [("dog", "claude", {"desktop": True}), ("opencode-1", "opencode")]


def test_coordinator_relays_the_users_approval(make):
    h = make(TWO, _human_check=True)
    held_approval(h)
    notice = [n["body"] for n in h.q("select body from messages where kind='notice'")]
    assert any("xmuse_approve" in b for b in notice)
    out = h.tool("dog", "xmuse_approve", id="per_1", decision="reject", user_said="no, don't push")
    assert out == {"result": {"ok": True}}
    assert h.q("select decision from approvals")[0]["decision"] == "reject"
    assert any('via dog ("no, don\'t push")' in n["body"] for n in h.q("select body from messages where kind='notice'"))
    again = h.tool("dog", "xmuse_approve", id="per_1", decision="once", user_said="ok")
    assert again["error"]["code"] == "invalid_arguments" and "already decided" in again["error"]["message"]
    h.admin("stop")


def test_only_the_coordinator_may_relay_an_approval(make):
    h = make(TWO, _human_check=True)
    held_approval(h)
    out = h.tool("opencode-1", "xmuse_approve", id="per_1", decision="once", user_said="sure")
    assert out["error"]["code"] == "invalid_arguments" and "coordinator" in out["error"]["message"]
    assert h.q("select state from approvals")[0]["state"] == "pending"
    h.admin("stop")
