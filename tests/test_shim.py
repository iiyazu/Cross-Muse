"""The TS shim speaking MCP over stdio to a real hub: tool forwarding, channel registration and push."""
import json
import os
import shutil
import subprocess
import urllib.error
import urllib.request

import pytest

from xmuse.config import SHIM
from xmuse.tools import TOOLS

pytestmark = pytest.mark.skipif(shutil.which("node") is None or not (SHIM.parent / "node_modules").exists(),
                                reason="node or shim/node_modules missing")


class Mcp:
    def __init__(self, env):
        self.p = subprocess.Popen(["node", str(SHIM)], env={"PATH": os.environ["PATH"], **{k: os.environ[k] for k in ("SYSTEMROOT",) if k in os.environ}, **env},
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.n = 0
        self.notes = []

    def req(self, method, params=None):
        self.n += 1
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method,
                                       "params": params or {}}) + "\n")
        self.p.stdin.flush()
        while True:
            msg = json.loads(self.p.stdout.readline())
            if msg.get("id") == self.n:
                return msg
            self.notes.append(msg)

    def next_note(self):
        msg = json.loads(self.p.stdout.readline())
        return msg

    def init(self):
        r = self.req("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                    "clientInfo": {"name": "test", "version": "0"}})
        self.p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        self.p.stdin.flush()
        return r["result"]

    def close(self):
        self.p.stdin.close()
        self.p.wait(5)


def test_tools_are_listed_and_forwarded(make):
    h = make([("claude-1", "claude"), ("claude-2", "claude")])
    m = Mcp({"XMUSE_STATE": str(h.state), "XMUSE_AGENT": "claude-1"})
    try:
        info = m.init()
        assert "claude/channel" not in info["capabilities"].get("experimental", {})
        tools = m.req("tools/list")["result"]["tools"]
        assert [t["name"] for t in tools][:2] == ["xmuse_whoami", "xmuse_send"] and len(tools) == len(TOOLS)
        r = m.req("tools/call", {"name": "xmuse_whoami", "arguments": {}})["result"]
        assert json.loads(r["content"][0]["text"])["id"] == "claude-1" and not r["isError"]
        r = m.req("tools/call", {"name": "xmuse_send", "arguments": {"to": "nobody", "body": "x"}})["result"]
        assert r["isError"] and json.loads(r["content"][0]["text"])["code"] == "unknown_recipient"
    finally:
        m.close()


def test_hub_down_is_a_tool_error_not_a_crash(make):
    h = make()
    m = Mcp({"XMUSE_STATE": str(h.state), "XMUSE_AGENT": "claude-1"})
    try:
        m.init()
        h.hub.shutdown()
        r = m.req("tools/call", {"name": "xmuse_whoami", "arguments": {}})["result"]
        assert r["isError"] and json.loads(r["content"][0]["text"])["code"] == "hub_unreachable"
    finally:
        m.close()
        h.hub.start()


def test_channel_registers_dynamic_endpoint_and_gates_pushes(make):
    h = make()
    m = Mcp({"XMUSE_STATE": str(h.state), "XMUSE_AGENT": "claude-1", "XMUSE_CHANNEL": "1",
             "CLAUDE_CODE_ENTRYPOINT": "cli", "CLAUDE_CODE_SESSION_ID": "sess-tui"})
    try:
        info = m.init()
        assert "claude/channel" in info["capabilities"]["experimental"]
        h.wait(lambda: h.q("select 1 from leases where channel_url is not null"), what="registration")
        [lease] = h.q("select * from leases")
        assert lease["vendor_session"] == "sess-tui" and lease["pid"] == os.getpid()  # shim's parent = "claude"
        bad = urllib.request.Request(lease["channel_url"], method="POST", data=b"{}",
                                     headers={"x-xmuse-nonce": "wrong"})
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(bad, timeout=5)
        assert e.value.code == 403
        ok = urllib.request.Request(lease["channel_url"], method="POST",
                                    data=json.dumps({"content": "hello tui", "meta": {"turn": "7"}}).encode(),
                                    headers={"x-xmuse-nonce": lease["channel_nonce"]})
        assert urllib.request.urlopen(ok, timeout=5).read() == b"ok\n"
        note = m.next_note()
        assert note["method"] == "notifications/claude/channel"
        assert note["params"] == {"content": "hello tui", "meta": {"turn": "7"}}
    finally:
        m.close()


def test_headless_claude_does_not_open_a_channel(make):
    h = make()
    m = Mcp({"XMUSE_STATE": str(h.state), "XMUSE_AGENT": "claude-1", "XMUSE_CHANNEL": "1",
             "CLAUDE_CODE_ENTRYPOINT": "sdk-cli"})
    try:
        assert "claude/channel" not in m.init()["capabilities"].get("experimental", {})
    finally:
        m.close()
