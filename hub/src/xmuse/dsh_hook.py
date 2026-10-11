#!/usr/bin/env python3
"""dsh hook -> xmuse hub. Standalone (stdlib only, no package import) so it stays fast.

usage: python3 dsh_hook.py <Event> [state] [agent] < payload.json
Reports the dsh Claude-dialect hooks this workspace subscribes to (SessionStart /
UserPromptSubmit with the prompt text / Stop). The hub tells hub-owned prompts
(the wakepack relay, starting with "[xmuse]") from human input itself; the script
only forwards what dsh fired. Never blocks dsh: any failure is ignored.

state/agent default to $XMUSE_STATE / $XMUSE_AGENT (Claude hook.py convention);
as argv they fit Windows hook commands, where `VAR=val` env prefixes do not run.
Without either, the state is discovered through the workspace pointer
`.xmuse.json` found by walking up from the current directory.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path


def find_state():
    p = Path.cwd().resolve()
    for d in (p, *p.parents):
        f = d / ".xmuse.json"
        try:
            if f.exists():
                return json.loads(f.read_text(encoding="utf-8"))["state"]
        except (OSError, ValueError, KeyError):
            pass
    return None


try:
    event = sys.argv[1]
    state = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("XMUSE_STATE")
    agent = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("XMUSE_AGENT")
    state = state or find_state()
    p = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace"))  # UTF-8 whatever the Windows code page
    hub = json.load(open(os.path.join(state, "hub.json"), encoding="utf-8"))
    token = open(os.path.join(state, "tokens", agent), encoding="utf-8").read().strip()
    body = {"event": event, "session_id": p.get("session_id"), "cwd": p.get("cwd"),
            "prompt": str(p.get("prompt", ""))[:200], "source": p.get("source"),
            "transcript_path": p.get("transcript_path")}
    req = urllib.request.Request("http://127.0.0.1:" + str(hub["port"]) + "/v1/hooks/dsh", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"authorization": "Bearer " + token, "content-type": "application/json"})
    urllib.request.urlopen(req, timeout=3).read()
except Exception:
    pass
