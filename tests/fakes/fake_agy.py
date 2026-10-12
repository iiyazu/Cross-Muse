#!/usr/bin/env python3
"""Fake `agy` CLI for hub tests: simulates prompt execution, tool calls, and failure cases."""
import json
import os
import sys
import time
import urllib.request
import uuid
from pathlib import Path

home = Path(os.environ.get("HOME", os.environ.get("USERPROFILE", "."))) / "fake-agy"
home.mkdir(parents=True, exist_ok=True)
argv = sys.argv[1:]

# Extract session id and prompt
sid = None
for a in argv:
    if a.startswith("--conversation="):
        sid = a.split("=", 1)[1]
    elif a == "--conversation":
        idx = argv.index(a)
        if idx + 1 < len(argv):
            sid = argv[idx + 1]

prompt = ""
if "-p" in argv:
    idx = argv.index("-p")
    if idx + 1 < len(argv):
        prompt = argv[idx + 1]

if "--version" in argv:  # the registry probe: no turn, no counter
    print("agy 0.0-fake")
    sys.exit(0)

n_file = home / "n"
n = int(n_file.read_text(encoding="utf-8")) if n_file.exists() else 0
n_file.write_text(str(n + 1), encoding="utf-8")

plan_file = home / "plan.json"
plan = json.loads(plan_file.read_text(encoding="utf-8")) if plan_file.exists() else []
step = plan[n] if n < len(plan) else {}

with (home / "calls.jsonl").open("a", encoding="utf-8") as f:
    f.write(json.dumps({"n": n, "argv": argv, "prompt": prompt, "cwd": os.getcwd(),
                        "step": step}) + "\n")

store = home / "sessions.json"
sessions = json.loads(store.read_text(encoding="utf-8")) if store.exists() else {}

# Failures
if step.get("result") == "unknown" or (sid is not None and sid not in sessions and step.get("unknown", True) and not sid.startswith("session-")):
    print(f"Conversation {sid} not found, ignoring --conversation flag", file=sys.stderr)
    sys.exit(1)

if step.get("result") == "quota":
    print("RESOURCE_EXHAUSTED: quota exceeded", file=sys.stderr)
    sys.exit(1)

if step.get("result") == "error":
    print("Error: model execution failed", file=sys.stderr)
    sys.exit(1)

if step.get("result") == "hang":
    time.sleep(step.get("sleep", 60))

if step.get("sleep"):
    time.sleep(step["sleep"])

sid = sid or step.get("session") or f"session-{uuid.uuid4()}"
sessions[sid] = os.getcwd()
store.write_text(json.dumps(sessions), encoding="utf-8")

# Tool calls
def tool(name, args):
    ws_file = Path.cwd() / ".xmuse.json"
    if ws_file.exists():
        state = Path(json.loads(ws_file.read_text(encoding="utf-8"))["state"])
    else:
        state = Path(os.environ.get("XMUSE_STATE", "."))
    port = json.loads((state / "hub.json").read_text(encoding="utf-8"))["port"]
    agent_id = step.get("as", "agy-1")
    token = (state / "tokens" / agent_id).read_text(encoding="utf-8").strip()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/tools/{name}", method="POST",
                                 data=json.dumps({"args": args}).encode(),
                                 headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

for name, args in step.get("calls", []):
    tool(name, args)

if step.get("code"):
    print("Executing tool: run_command")

print(f"Created conversation {sid}")
print("Response: OK")
sys.exit(0)
