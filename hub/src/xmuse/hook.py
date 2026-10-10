#!/usr/bin/env python3
"""Claude Code project hook -> xmuse hub. Standalone (stdlib only, no package import) so it stays fast.

usage (from .claude/settings.json): XMUSE_STATE=... XMUSE_AGENT=... python3 hook.py <Event>
Reports the session lease (SessionStart/SessionEnd with CLAUDE_PID), human input (UserPromptSubmit)
and turn end (Stop). Never blocks Claude: any failure is ignored.

Desktop app mode (XMUSE_DESKTOP=1): the report carries "desktop": true (the pid is a Windows pid, the hub does not
probe it) and the hub's reply carries the agent's unread counts; on UserPromptSubmit a reminder line goes to stdout,
which Claude puts into the model's context.
"""
import json
import os
import sys
import urllib.request

try:
    state, agent, event = os.environ["XMUSE_STATE"], os.environ["XMUSE_AGENT"], sys.argv[1]
    desktop = os.environ.get("XMUSE_DESKTOP") == "1"
    p = json.load(sys.stdin)
    hub = json.load(open(os.path.join(state, "hub.json")))
    token = open(os.path.join(state, "tokens", agent)).read().strip()
    pid = int(os.environ.get("CLAUDE_PID") or os.getppid())
    body = {"event": event, "pid": pid, "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT"),
            "session_id": p.get("session_id"), "source": p.get("source"), "reason": p.get("reason"),
            "transcript_path": p.get("transcript_path"), "prompt": str(p.get("prompt", ""))[:200]}
    if desktop:
        body["desktop"] = True
    req = urllib.request.Request(f"http://127.0.0.1:{hub['port']}/v1/hooks/claude", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    reply = json.loads(urllib.request.urlopen(req, timeout=3).read())
    res = reply.get("result") or {}
    if desktop and event == "UserPromptSubmit":
        if res.get("pending", 0) > 0:
            print(f"[xmuse] {res['pending']} new message(s) ({res.get('mentions', 0)} mention you). "
                  "Call xmuse_inbox before anything else, and xmuse_ack when handled.")
        if res.get("context"):  # alignment snapshot/delta + unread list built by the hub
            print(res["context"])
except Exception:
    pass
