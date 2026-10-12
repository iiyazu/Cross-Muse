"""Evidence for `xmuse_done` and the reviewer gate (contract XMUSE2-VIEW-API 8.5, package T5).

An agent that finishes may attach evidence: [{kind: test|diff|command, ref, result}]. The hub checks it against the
turn's own log, the one thing the agent cannot edit afterwards:
  test / command  the command line (whitespace-normalised, contained in what ran) was run in this turn, and the
                  exit code, or failing output when the tool reports no code, agrees with the claimed result;
  diff            the path was written or edited in this turn.
What each vendor's log gives (see parse functions): Claude exit codes of Bash (is_error + "Exit code N"), writes of
Write/Edit/MultiEdit; OpenCode shell exit codes only when the tool metadata or output states one, writes from the
edit tools and from each step's `files`; dsh shell output only (no exit code), writes from its write/edit tools.
No readable log (polled desktop/foreground members, unknown adapter): unverified, "transcript unavailable".

After a finished task the review gate hands the work to a reviewer member before the chain ends (request_review).
"""
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from . import db
from .config import HUB, info_on
from .transcript import _blocks_text

UNAVAILABLE = "transcript unavailable"
CLAUDE_SHELL, CLAUDE_WRITE = {"Bash", "PowerShell"}, {"Write", "Edit", "MultiEdit", "NotebookEdit"}
OC_SHELL, OC_WRITE = {"shell", "bash", "command"}, {"edit", "write", "patch", "apply_patch", "multiedit"}
DSH_SHELL = {"pwsh", "powershell", "bash", "shell", "cmd"}
DSH_WRITE = {"write", "edit", "multiedit", "patch", "apply_patch"}
PATH_KEYS = ("file_path", "filePath", "path", "filepath", "file", "notebook_path")


@dataclass
class Call:
    kind: str                # shell | write
    text: str                # the command line, or the path written
    exit: int | None = None  # None: the log states no exit code
    failed: bool = False     # the tool itself reported an error
    output: str = ""


# ---- reading a turn's log -------------------------------------------------------------------------------------

def _objs(lines):
    """JSON objects of a JSONL stream; lines that are not JSON objects are skipped."""
    for line in lines:
        line = line.strip()
        if line.startswith("{"):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if isinstance(o, dict):
                yield o


_EXIT = re.compile(r"(?i)\bexit(?:ed)?(?:\s+(?:with|code|status))*\s*[:=]?\s*(-?\d+)")


def _exit_in(text: str) -> int | None:
    m = _EXIT.findall(text or "")
    return int(m[-1]) if m else None


def _path_of(inp) -> str:
    return next((str(inp[k]) for k in PATH_KEYS if isinstance(inp, dict) and isinstance(inp.get(k), str)), "")


def _patch_paths(inp) -> list[str]:
    """Files named by an apply_patch style body ('*** Update File: x')."""
    texts = [v for v in inp.values() if isinstance(v, str)] if isinstance(inp, dict) else [str(inp)]
    return [p.strip() for t in texts for p in re.findall(r"\*\*\* (?:Add|Update) File: (.+)", t)]


def claude(lines, since: float | None = None) -> list[Call] | None:
    """`claude -p --output-format stream-json` run log, or a Claude Code session transcript (same record shapes;
    `since` keeps only records stamped at or after it)."""
    calls, by_id, n = [], {}, 0
    for o in _objs(lines):
        n += 1
        ts = o.get("timestamp")
        if since and isinstance(ts, str) and datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp() < since:
            continue
        content = (o.get("message") or {}).get("content")
        if not isinstance(content, list):
            continue
        for c in content:
            if not isinstance(c, dict):
                continue
            if o.get("type") == "assistant" and c.get("type") == "tool_use" and c.get("id") not in by_id:
                inp = c.get("input") or {}
                if c.get("name") in CLAUDE_SHELL:
                    call = Call("shell", str(inp.get("command", "")))
                elif c.get("name") in CLAUDE_WRITE:
                    call = Call("write", _path_of(inp))
                else:
                    continue
                by_id[c["id"]] = call
                calls.append(call)
            elif o.get("type") == "user" and c.get("type") == "tool_result" and c.get("tool_use_id") in by_id:
                call, text = by_id[c["tool_use_id"]], _blocks_text(c.get("content"))
                call.output, call.failed = text, bool(c.get("is_error"))
                m = re.match(r"\s*Exit code (-?\d+)", text)
                call.exit = int(m[1]) if m else (None if call.failed else 0 if call.kind == "shell" else None)
    return calls if n else None


def opencode(lines) -> list[Call] | None:
    """The run log is the hub's copy of the server's SSE events: session.tool.{input.started,called,success,...}."""
    calls, names, by_id, n = [], {}, {}, 0
    for o in _objs(lines):
        n += 1
        typ, d = o.get("type", ""), o.get("data") or {}
        cid = d.get("id")
        if typ == "session.tool.input.started":
            names[cid] = d.get("name")
        elif typ == "session.tool.called":
            name, inp = names.get(cid) or d.get("name"), d.get("input") or {}
            if name in OC_SHELL:
                by_id[cid] = Call("shell", str(inp.get("command") or inp.get("cmd") or ""))
            elif name in OC_WRITE:
                by_id[cid] = Call("write", _path_of(inp))
                calls.extend(Call("write", p) for p in _patch_paths(inp))
            else:
                continue
            calls.append(by_id[cid])
        elif typ == "session.tool.success" and cid in by_id:
            call, meta = by_id[cid], d.get("metadata") or {}
            call.output = _blocks_text(d.get("content"))
            call.exit = next((meta[k] for k in ("exit", "exitCode", "exit_code") if isinstance(meta.get(k), int)),
                             _exit_in(call.output) if call.kind == "shell" else None)
            calls.extend(Call("write", f["file"]) for f in meta.get("files") or [] if isinstance(f, dict)
                         and isinstance(f.get("file"), str))
        elif typ.startswith("session.tool.") and typ.endswith(("error", "failed")) and cid in by_id:
            by_id[cid].failed = True
            by_id[cid].output = json.dumps(d.get("error") or d.get("message") or "")
        elif typ == "session.step.ended":  # the files this step changed, whatever tool changed them
            calls.extend(Call("write", f) for f in d.get("files") or [] if isinstance(f, str))
    return calls if n else None


def dsh(lines) -> list[Call] | None:
    """`dsh --json` NDJSON run log: tool_call / tool_result pairs by callId; shell results carry no exit code."""
    calls, by_id, n = [], {}, 0
    for o in _objs(lines):
        n += 1
        if o.get("type") == "tool_call":
            inp = o.get("input") or {}
            if o.get("tool") in DSH_SHELL:
                call = Call("shell", str(inp.get("command", "")))
            elif o.get("tool") in DSH_WRITE:
                call = Call("write", _path_of(inp))
                calls.extend(Call("write", p) for p in _patch_paths(inp))
            else:
                continue
            by_id[o.get("callId")] = call
            calls.append(call)
        elif o.get("type") == "tool_result" and o.get("callId") in by_id:
            call = by_id[o["callId"]]
            call.output, call.failed = str(o.get("result", "")), o.get("status") == "error"
            call.exit = _exit_in(call.output) if call.kind == "shell" else None
    return calls if n else None


def _state_dir(conn) -> Path | None:
    f = next((r[2] for r in conn.execute("pragma database_list") if r[1] == "main"), "")
    return Path(f).parent if f else None


def calls_of(conn, turn: dict | None) -> list[Call] | None:
    """What the agent did in `turn`, or None when its log cannot be read."""
    if not turn:
        return None
    try:
        if turn["adapter"] == "claude_channel":  # a live TUI: no run log, the session's own transcript has it
            r = conn.execute("select s.vendor_session from sessions s where s.id=?", (turn["session_id"],)).fetchone()
            f = next(iter((Path.home() / ".claude" / "projects").glob(f"*/{r[0]}.jsonl")), None) if r and r[0] else None
            if f is None:
                return None
            with f.open(encoding="utf-8", errors="replace") as fh:
                return claude(fh, turn["started_at"] - 1)
        parse = {"claude_resume": claude, "opencode": opencode, "dsh": dsh}.get(turn["adapter"])
        state = _state_dir(conn)
        f = state and state / "runs" / f"turn-{turn['id']}.jsonl"
        if parse is None or not f or not f.exists():
            return None
        with f.open(encoding="utf-8", errors="replace") as fh:
            return parse(fh)
    except (OSError, ValueError, KeyError, TypeError, IndexError):
        return None


# ---- checking claims ------------------------------------------------------------------------------------------

def _cmd(s: str) -> str:
    return " ".join(str(s).split())


def _path(p: str) -> str:
    p = str(p).strip().replace("\\", "/")
    m = re.match(r"/mnt/([A-Za-z])/(.*)", p)  # WSL and Windows spell one file two ways
    p = f"{m[1]}:/{m[2]}" if m else p
    return re.sub(r"^(\./)+", "", p).lower()


def _same_file(a: str, b: str) -> bool:
    a, b = _path(a), _path(b)
    return bool(a and b) and (a == b or a.endswith("/" + b) or b.endswith("/" + a))


_FAIL_OUT = re.compile(r"(?i)\b[1-9]\d*\s+(?:failed|failures?|errors?)\b|^FAILED\b|\bFAIL\b|Traceback \(most"
                       r" recent call last\)|\bAssertionError\b|npm ERR!|Command not found|is not recognized as", re.M)
_FAILN = re.compile(r"(?i)\b[1-9]\d*\s+(?:failed|failures?|errors?)\b")
# zero-count summary lines: node's "ℹ fail 0", "failures: 0", "0 failed" (dev room 10-12: a passing run read as failed)
_ZERO_OUT = re.compile(r"(?i)\b(?:fail(?:ed|ures?)?|errors?)\b\s*[:=]?\s*0\b|\b0\s+(?:failed|failures?|errors?)\b")
_ZERO_FAIL = re.compile(r"(?i)\b(?:0|no|zero|without)\s+(?:failed|failures?|errors?)\b")
_PASS = re.compile(r"(?i)\b(?:pass(?:ed|es|ing)?|ok|success(?:ful(?:ly)?)?|succeeded|green|clean)\b")
_FAILW = re.compile(r"(?i)\b(?:fail(?:ed|s|ing|ure|ures)?|errors?|non-?zero|red|broken)\b")


def _claim(result: str):
    """What the agent claims about a command: an exit code (int), 'pass', 'fail', or None (nothing checkable)."""
    result = result or ""
    m = _EXIT.search(result)
    if m:
        return int(m[1])
    if _FAILN.search(result):
        return "fail"
    result = _ZERO_FAIL.sub("", result)
    if _PASS.search(result):
        return "pass"
    return "fail" if _FAILW.search(result) else None


def _mismatch(c: Call, it: dict) -> str | None:
    """Why one run of the command contradicts the claimed result, or None."""
    claim, shown = _claim(it.get("result", "")), f"{it['ref']!r} claimed {it.get('result', '')!r}"
    if claim is None:
        return None
    if isinstance(claim, int):
        if c.exit is not None and c.exit != claim:
            return f"{shown} but exited {c.exit}"
        claim = "pass" if claim == 0 else "fail"
    if claim == "pass":
        if c.exit not in (0, None):
            return f"{shown} but exited {c.exit}"
        if c.failed:
            return f"{shown} but the tool reported an error"
        if c.exit is None and _FAIL_OUT.search(_ZERO_OUT.sub("", c.output)):
            return f"{shown} but its output shows failures"
    elif c.exit == 0 and not c.failed:
        return f"{shown} but exited 0"
    return None


def _check_command(calls: list[Call], it: dict) -> str | None:
    """Some run in this turn contained the command and agrees with the claim; else the last run's disagreement."""
    ref = _cmd(it["ref"])
    ran = [c for c in calls if c.kind == "shell" and ref and ref in _cmd(c.text)]
    if not ran:
        return f"{it['kind']} not run in this turn: {it['ref']!r}"
    problems = [_mismatch(c, it) for c in ran]
    return None if None in problems else problems[-1]


def _check_one(calls: list[Call], it: dict) -> str | None:
    if it["kind"] == "diff":
        if not any(c.kind == "write" and not c.failed and _same_file(c.text, it["ref"]) for c in calls):
            return f"diff not written in this turn: {it['ref']!r}"
        return None
    return _check_command(calls, it)


def check(conn, turn: dict | None, items: list[dict]) -> tuple[str, list[str]]:
    """(status, problems) for evidence given in `turn`. Read-only."""
    calls = calls_of(conn, turn)
    if calls is None:
        return "unverified", [UNAVAILABLE]
    problems = [p for it in items if (p := _check_one(calls, it))]
    return ("unverified", problems) if problems else ("verified", [])


# ---- storage and view -----------------------------------------------------------------------------------------

def record(conn, message_id: int, items: list[dict], status: str, problems: list[str]) -> None:
    """Inside the caller's transaction, with the done message."""
    conn.execute("insert or replace into evidence(message_id, items, status, problems, checked_at) values(?,?,?,?,?)",
                 (message_id, json.dumps(items, ensure_ascii=False), status, json.dumps(problems, ensure_ascii=False),
                  db.now()))


def status(conn, message_id: int) -> tuple[str, list[str]]:
    """('verified' | 'unverified' | 'none', problems) of a done message; the dispatch package turns a failed
    check into outcome 'blocked'."""
    r = conn.execute("select status, problems from evidence where message_id=?", (message_id,)).fetchone()
    return (r[0], json.loads(r[1])) if r else ("none", [])


def items(conn, message_id: int) -> list[dict]:
    r = conn.execute("select items from evidence where message_id=?", (message_id,)).fetchone()
    return json.loads(r[0]) if r else []


def view_fields(conn, message_id: int) -> dict:
    s, problems = status(conn, message_id)
    return {"evidence_status": s, "evidence_problems": problems}


# ---- reviewer gate --------------------------------------------------------------------------------------------

def reviewer_for(conn, agent_id: str) -> str | None:
    """The member who reviews `agent_id`'s finished work: the reviewer (role) with the smallest id."""
    r = conn.execute("select id from agents where removed=0 and lower(trim(role))='reviewer' and id!=? order by id"
                     " limit 1", (agent_id,)).fetchone()
    return r and r[0]


def _clip(s: str, n: int) -> str:
    s = str(s).strip()
    return s if len(s) <= n else s[:n] + " ..."


def review_body(conn, agent_id: str, message_id: int, summary: str) -> str:
    st, problems = status(conn, message_id)
    ev = items(conn, message_id)
    lines = [f"REVIEW REQUEST from the hub: {agent_id} finished its work (done #{message_id}, next: none). "
             "The work counts as finished only after you have reviewed it.",
             f"Summary: {_clip(summary, 1200)}",
             f"Evidence (hub check: {st}):" if ev else "Evidence: none given."]
    lines += [f"- {e['kind']} {_clip(e['ref'], 300)}" + (f" -> {_clip(e['result'], 200)}" if e.get("result") else "")
              for e in ev[:20]]
    lines += [f"Problems found by the hub: {_clip('; '.join(problems), 800)}"] if problems else []
    lines.append("Check the work yourself (read the changes, rerun what the evidence claims). Then either send "
                 f"{agent_id} what must be fixed (xmuse_send), or call xmuse_done(next=\"none\") to accept it.")
    return "\n".join(lines)


def request_review(conn, cfg: dict, agent_id: str, message_id: int, summary: str, nxt: str) -> str | None:
    """Review gate: when `agent_id` ends a task (next none) and the room has a reviewer who is not the agent, hand the
    work to that reviewer instead of ending the chain. Returns the reviewer's id, or None when the gate stays shut.
    Runs outside any transaction (it sends a message)."""
    if not cfg.get("review_gate", True) or not info_on(cfg) or nxt.strip().lower() != "none":
        return None
    me = conn.execute("select role from agents where id=? and removed=0", (agent_id,)).fetchone()
    if me is None or (me[0] or "").strip().lower() == "reviewer":
        return None  # the reviewer's own done ends the chain
    reviewer = reviewer_for(conn, agent_id)
    if reviewer is None:
        return None
    from . import mail
    st, problems = status(conn, message_id)
    mail.send(conn, cfg, HUB, reviewer, review_body(conn, agent_id, message_id, summary), "handoff", why={
        "what": f"Review {agent_id}'s finished work (done #{message_id})",
        "why": "room policy review_gate: finished work is reviewed before the task counts as done",
        "tradeoff": "costs one reviewer wake; catches claims nobody checked",
        "open_questions": f"evidence {st}" + (f": {'; '.join(problems)}" if problems else ""),
        "next_action": f"accept with xmuse_done(next=none) or send {agent_id} the defects"},
        idem=f"review:{message_id}")
    return reviewer
