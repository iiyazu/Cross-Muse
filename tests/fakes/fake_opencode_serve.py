#!/usr/bin/env python3
"""`opencode serve` stand-in for T12 tests: started by the hub as a subprocess, one per OpenCode agent.

Like the real server it learns its MCP identity only from OPENCODE_CONFIG (the instance config) merged with the
workspace opencode.json in its cwd, and its password only from OPENCODE_SERVER_PASSWORD. Every prompt runs one step
that calls xmuse_whoami and then xmuse_send as that identity (what the shim would do with XMUSE_AGENT). Prompts and
tool results go to <state>/fake-oc/<identity>.jsonl.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fake_opencode import FakeOpenCode  # noqa: E402

port = int(sys.argv[sys.argv.index("--port") + 1])
merged: dict = {}
for f in (Path(os.environ["OPENCODE_CONFIG"]), Path.cwd() / "opencode.json"):
    for k, v in json.loads(f.read_text(encoding="utf-8")).items():
        merged.setdefault(k, v)
env = merged["mcp"]["servers"]["xmuse"]["environment"]
state, agent = Path(env["XMUSE_STATE"]), env["XMUSE_AGENT"]
(state / "fake-oc").mkdir(exist_ok=True)
record = state / "fake-oc" / f"{agent}.jsonl"
fake = FakeOpenCode(state, port=port, password=os.environ["OPENCODE_SERVER_PASSWORD"], record=record)
fake._record({"started": agent, "port": port, "shared_identity": "XMUSE_AGENT" in (Path.cwd() / "opencode.json").read_text(encoding="utf-8")})
fake.plan = [{"as": agent, "calls": [["xmuse_whoami", {}],
                                     ["xmuse_send", {"to": "human", "body": f"hello from {agent}"}]]}] * 50
while True:
    time.sleep(3600)
