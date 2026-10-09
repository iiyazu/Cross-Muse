#!/usr/bin/env python3
"""Claude Code project hook -> xmuse hub. Standalone (stdlib only, no package import) so it stays fast.

usage (from .claude/settings.json): XMUSE_STATE=... XMUSE_AGENT=... python3 hook.py <Event>
Reports the session lease (SessionStart/SessionEnd with CLAUDE_PID), human input (UserPromptSubmit)
and turn end (Stop). Never blocks Claude: any failure is ignored.
"""
import json
import os
import sys
import urllib.request

try:
    state, agent, event = os.environ["XMUSE_STATE"], os.environ["XMUSE_AGENT"], sys.argv[1]
    p = json.load(sys.stdin)
    hub = json.load(open(os.path.join(state, "hub.json")))
    token = open(os.path.join(state, "tokens", agent)).read().strip()
    pid = int(os.environ.get("CLAUDE_PID") or os.getppid())
    body = {"event": event, "pid": pid, "entrypoint": os.environ.get("CLAUDE_CODE_ENTRYPOINT"),
            "session_id": p.get("session_id"), "source": p.get("source"), "reason": p.get("reason"),
            "transcript_path": p.get("transcript_path"), "prompt": str(p.get("prompt", ""))[:200]}
    req = urllib.request.Request(f"http://127.0.0.1:{hub['port']}/v1/hooks/claude", method="POST",
                                 data=json.dumps(body).encode(),
                                 headers={"authorization": f"Bearer {token}", "content-type": "application/json"})
    urllib.request.urlopen(req, timeout=3).read()
except Exception:
    pass
