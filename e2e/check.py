#!/usr/bin/env python3
"""Summarize one e2e run from `xmuse log --json`: who did what, review rounds, human interventions,
per-wake tokens by vendor and by mode (chat wake = messaging/reading only; code wake = edited files
or ran commands).  usage: check.py <results-dir> <impl> <reviewer> <public> <hidden> <seconds> <wait-rc>"""
import json
import sys
from pathlib import Path

res, impl, rev, pub, hid, secs, rc = sys.argv[1:8]
log = json.loads((Path(res) / "log.json").read_text())
msgs, turns = log["messages"], log["turns"]
human = [m for m in msgs if m["sender"] == "human"]
review_requests = [m for m in msgs if m["sender"] == impl and m["kind"] == "review_request"]
reviews = [m for m in msgs if m["sender"] == rev and m["kind"] in ("message", "decision", "handoff", "question")]
first_review = reviews[0]["created_at"] if reviews else None
fix_turns = [t for t in turns if t["agent_id"] == impl and first_review and t["started_at"] > first_review
             and t["mode"] == "code"]
tok = lambda t: sum((t[k] or 0) for k in ("input", "cache_read", "cache_write", "output"))  # noqa: E731
wakes = {}
for t in turns:
    key = f"{t['agent_id']}:{t['mode'] or 'none'}"
    w = wakes.setdefault(key, {"wakes": 0, "tokens": 0, "max_context": 0, "per_wake": []})
    w["wakes"] += 1
    w["tokens"] += tok(t)
    w["max_context"] = max(w["max_context"], t["context"] or 0)
    w["per_wake"].append(tok(t))
notices = [m["body"] for m in msgs if m["kind"] == "notice"]
out = {
    "result": {"public_tests": pub, "hidden_tests": hid, "quiet": rc == "0", "seconds": int(secs)},
    "flow": {"messages": len(msgs), "turns": len(turns), "failed_turns": sum(t["state"] != "succeeded" for t in turns),
             "review_requests": len(review_requests), "reviewer_replies": len(reviews),
             "fix_turns_after_first_review": len(fix_turns),
             "final_report_to_human": any(m["sender"] == impl and m["thread_id"] in ("#task", f"dm:{impl}+human")
                                          or m["thread_id"].startswith("dm:") and "human" in m["thread_id"]
                                          and m["sender"] == impl for m in msgs[-6:]),
             "done_calls": sum(m["kind"] == "done" for m in msgs)},
    "human_interventions": len(human) - 1,
    "notices": notices,
    "tokens": {"total": sum(tok(t) for t in turns), "by_agent_mode": wakes},
}
print(json.dumps(out, indent=1, ensure_ascii=False))
