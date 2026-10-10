#!/usr/bin/env python3
"""MemoryOS offline replay for xmuse 2 runs (standard library only).

Rebuilds the /curate, /recall and /similar requests the hub *would* have sent if MemoryOS had been on during a
recorded multi-agent run, sends them to a MemoryOS service (or a fake) and scores the answers. Nothing here is on
the hub's correctness path; this is an offline evaluator for data/results/<run>/.

usage:
  replay_mo.py build <results-dir...> --out DIR            # offline: requests + index.json
  replay_mo.py send DIR --url http://127.0.0.1:8301 [...]  # sends, writes *.resp.json (resumable)
  replay_mo.py score DIR --out report.md [--results data/results]

Every rule below is a pure-function port of hub/src/xmuse/memoryos.py (named in the comments); where the recording
cannot answer a question the choice is documented in the README section "MemoryOS 离线回放".
"""
import argparse
import calendar
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# port of memoryos.py constants (KINDS/MSGS/EVERY/WINDOW/CONTEXT/ACTIVE/SIMILAR)
KINDS = ("decision", "convention", "assumption", "question", "lesson")   # what /curate may propose
MSGS = ("message", "handoff", "review_request", "decision", "assumption", "question")  # what curate reads
EVERY, WINDOW, CONTEXT, ACTIVE, SIMILAR = 8, 32, 8, 60, 0.88
# port of config.py defaults (align_thread_cap / recall_budget_tokens)
THREAD_CAP, RECALL_BUDGET = 15, 2000
# port of align.py / align.py:add scope
SCOPE = "thread:"
# XMUSE2-MO-ALIGN §3.2/§3.4 limits
ITEM_TEXT, ITEM_ID, QUERY_CHARS, WINDOW_TEXT, SPEAKER_CHARS, SCOPE_ID = 2000, 128, 4000, 200_000, 255, 255
ACTIVITY_TYPES = ("message", "review_objection", "gate_failure")
KEEP_OPS = ("add", "confirm")    # entry_events ops that put an entry in `active` (align.py:_move / review)
TYPES = {"curate", "recall", "similar"}


# ---------------------------------------------------------------- loading
def is_run(p: Path) -> bool:
    return (p / "meta.json").exists() and (p / "log.json").exists()


def run_dirs(paths) -> list:
    """Accept run folders and parents of run folders (metrics.py:units does the same)."""
    out = []
    for p in map(Path, paths):
        out += [p] if is_run(p) else sorted(d for d in p.iterdir() if d.is_dir() and is_run(d))
    return sorted(out, key=lambda p: str(p))


def load_run(d: Path) -> dict:
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    log = json.loads((d / "log.json").read_text(encoding="utf-8"))
    ent = json.loads((d / "entries.json").read_text(encoding="utf-8")) if (d / "entries.json").exists() else {}
    # the folder name is the only unique run id: meta.json repeats "ledger-A-1" for its re-runs
    # (ledger-A-1-20261010-155459), and two runs sharing an output folder would silently overwrite each other
    return {"name": d.name, "meta_run": meta.get("run") or d.name, "dir": str(d), "meta": meta,
            "messages": sorted(log.get("messages") or [], key=lambda m: m.get("id") or 0),
            "entries": ent.get("entries") or [], "events": ent.get("events") or []}


# ---------------------------------------------------------------- pure rules (ports of memoryos.py)
def act(m: dict) -> dict:
    """Port of memoryos.py:_act - a hub message row as a CurateActivity. `why` is appended to the text because the
    hub appends it too (the hub's own `why` column holds the handoff Why-First fields marshalled as JSON)."""
    try:
        why = json.loads(m.get("why") or "{}")
    except (TypeError, ValueError):
        why = {}
    extra = "".join(f"\n{k}: {v}" for k, v in why.items() if v) if isinstance(why, dict) else ""
    return {"id": f"m{m['id']}", "seq": int(m["id"]), "type": "message", "speaker": str(m.get("sender") or ""),
            "kind": str(m.get("kind") or "message"), "text": str(m.get("body") or "") + extra}


def activities(msgs) -> list:
    """The replay hands over hub message rows, but a caller may already have CurateActivity dicts: accept both."""
    return [m if isinstance(m.get("seq"), int) and "text" in m else act(m) for m in msgs]


def _entries_by_id(entries) -> dict:
    return {int(e["id"]): e for e in entries}


def _last_events(events, at: float = None) -> dict:
    """entry id -> its newest entry_events row at or before `at` (align.py keeps one row per state change).
    `at` matters: an entry superseded later in the run was still active when an earlier /curate was sent."""
    out = {}
    for e in events:
        if at is not None and float(e["at"]) > at:
            continue
        i = int(e["entry_id"])
        if i not in out or int(e["seq"]) > int(out[i]["seq"]):
            out[i] = e
    return out


def active_at(run: dict, tid: str, at_time: float) -> list:
    """Port of Curator.kick's `active` query, evaluated at the moment a /curate would have been sent.

    memoryos.py asks hub.db for scope='thread:<tid>', status='active', kind in KINDS, newest seq first, LIMIT 60.
    A recording has no `status` column *at that time*, so the status is rebuilt from entry_events: the entry must
    have been recorded (`recorded_at <= at_time`) and its last event at that time must be add/confirm, which is
    exactly what align.py:_move writes when the entry enters `active`."""
    byid, last = _entries_by_id(run["entries"]), _last_events(run["events"], at_time)
    out = []
    for i, e in byid.items():
        ev = last.get(i)
        if ev is None or ev["op"] not in KEEP_OPS or float(e.get("recorded_at") or 0) > at_time:
            continue
        if e.get("scope") != SCOPE + tid or e.get("kind") not in KINDS:
            continue
        out.append(e)
    out.sort(key=lambda e: -int(e["seq"]))
    return out[:ACTIVE]


def _final_active(run: dict) -> list:
    """All entries still active when the recording stopped (any scope, any kind) - the /recall and /similar input."""
    byid, last = _entries_by_id(run["entries"]), _last_events(run["events"])
    out = [byid[i] for i, ev in last.items() if ev["op"] in KEEP_OPS and byid[i].get("status") == "active"]
    return sorted(out, key=lambda e: -int(e["seq"]))


def active_payload(entries) -> list:
    """Port of memoryos.py:_curate's active list: id E<n>, kind, topic_key e<n>, statement, version=seq."""
    return [{"id": f"E{int(e['id'])}", "kind": e["kind"], "topic_key": f"e{int(e['id'])}",
             "statement": e["statement"], "version": int(e["seq"])} for e in entries]


def window_and_context(msgs, tid: str, last_id: int, upto: int = None) -> tuple:
    """Port of Curator.kick's two message queries: the ≤32 newest messages after the watermark, and the ≤8 newest
    before it (both restricted to kind in MSGS and the same thread). `upto` is the message that just arrived: the
    hub's query runs at that instant, so the window must not look into the future of the recording."""
    pool = [m for m in msgs if m.get("thread_id") == tid and m.get("kind") in MSGS]
    win = [m for m in pool if int(m["id"]) > last_id and (upto is None or int(m["id"]) <= upto)][-WINDOW:]
    ctx = [m for m in pool if int(m["id"]) <= last_id][-CONTEXT:]
    return win, ctx


def similar_note(active: list, pairs: list) -> dict | None:
    """Port of memoryos.py:Curator._similar (the >120% thread-cap gate and the hub-similar activity)."""
    if len(active) <= THREAD_CAP * 1.2 or not pairs:
        return None
    txt = ", ".join(f"{p['a']}~{p['b']} ({float(p['score']):.2f})" for p in pairs)
    return {"id": "hub-similar", "seq": 0, "type": "message", "speaker": "hub", "kind": "message",
            "text": f"Near-duplicate active entries, consider proposing a merge: {txt}"}


def curate_request(run: dict, tid: str, win: list, ctx: list, active: list, at_time: float, pairs=None) -> dict:
    """Port of memoryos.py:Curator._curate's request body. The hub sends no `schema`; we add it because the
    contract names the schema, and a server that validates the named shape must accept it. Validation is strict."""
    note = similar_note(active, pairs or [])
    win, ctx = activities(win)[-WINDOW:], activities(ctx)[-CONTEXT:]
    body = {"scope_id": tid, "profile": "collab", "active": active_payload(active),
            "context": ctx[-(CONTEXT - bool(note)):] + ([note] if note else []),
            "window": win, "max_repairs": 1}
    return {"schema": "memoryos_curate/v1", **body,
            "_replay": {"run": run["name"], "seed": run["meta"].get("seed") or run["name"].split("-")[0],
                        "thread": tid, "at": iso(at_time),
                        "last_activity_id": str(win[-1]["id"]) if win else None,
                        "active_ids": [a["id"] for a in body["active"]]}}


def recall_request(run: dict, items: list, query: str, k: int) -> dict:
    """Port of memoryos.py:Client.rank's body, with the replay's own query/k choice (spec section 3.1)."""
    return {"schema": "memoryos_recall/v1", "query": query[:QUERY_CHARS],
            "items": [{"id": f"E{int(e['id'])}", "text": e["statement"], "kind": e["kind"], "seq": int(e["seq"])}
                      for e in items[:500]],
            "hints": {}, "budget_tokens": RECALL_BUDGET, "k": k,
            "_replay": {"run": run["name"], "seed": run["meta"].get("seed") or run["name"].split("-")[0],
                        "thread": None, "at": iso(run_end(run))}}


def similar_request(run: dict, items: list) -> dict:
    """Port of memoryos.py:Curator._similar's body (threshold 0.88, E<n>/statement items)."""
    return {"schema": "memoryos_similar/v1", "threshold": SIMILAR,
            "items": [{"id": f"E{int(e['id'])}", "text": e["statement"]} for e in items[:500]],
            "_replay": {"run": run["name"], "seed": run["meta"].get("seed") or run["name"].split("-")[0],
                        "thread": None, "at": iso(run_end(run))}}


# ---------------------------------------------------------------- timing helpers
def iso(t: float) -> str:
    """UTC ISO-8601 seconds: deterministic across platforms, unlike formatting a float."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(float(t)))


def run_end(run: dict) -> float:
    return max([float(m.get("created_at") or 0) for m in run["messages"]] + [0.0])


def trigger_time(run: dict, msg: dict) -> float:
    """When the hub would have queued this curation: right after the message that tripped the trigger."""
    return float(msg.get("created_at") or 0)


# ---------------------------------------------------------------- build
def build_run(run: dict) -> list:
    """Replay one run's threads. Returns [(kind, name, request, reason)] in a deterministic order.

    Port of Curator.kick: the watermark is the last message already sent to /curate, the window is the newest
    ≤32 messages of kind in MSGS after it, and a curation is queued when the thread is closed, the window has ≥8
    messages, or it contains a handoff. The hub advances the watermark only when it actually curates, so messages
    that do not trip a trigger stay in the window for the next one; the hub also skips while a thread is `busy`,
    which a replay cannot see (no worker), and the batched effect is the same on the recorded data (see README)."""
    out = []
    for tid in sorted({m["thread_id"] for m in run["messages"] if m.get("thread_id")}):
        last = 0
        n = 0
        for m in run["messages"]:
            if m.get("thread_id") != tid or m.get("kind") not in MSGS:
                continue
            win, ctx = window_and_context(run["messages"], tid, last, int(m["id"]))
            activities_win = activities(win)
            reasons = []
            if len(activities_win) >= EVERY:
                reasons.append(f"every{EVERY}")
            if any(x["kind"] == "handoff" for x in activities_win):
                reasons.append("handoff")
            if not activities_win or not reasons:
                continue
            last = max(last, int(m["id"]))  # the hub writes the watermark when it curates, not when a message arrives
            n += 1
            t = trigger_time(run, m)
            req = curate_request(run, tid, win, ctx, active_at(run, tid, t), t)
            out.append({"type": "curate", "file": f"curate-{n}.json", "run": run["name"], "thread": tid,
                        "reason": "+".join(reasons), "message_id": int(m["id"]), "request": req})
    return out


def build_run_tail(run: dict) -> list:
    """The per-run /recall and /similar requests (spec section 3.1): all entries still active at the end."""
    items = _final_active(run)
    humans = [m for m in run["messages"] if m.get("sender") == "human"]
    query = str(humans[-1].get("body") or "") if humans else ""
    out = [{"type": "recall", "file": "recall.json", "run": run["name"], "thread": None,
            "reason": "end-of-run active entries", "message_id": humans[-1]["id"] if humans else None,
            "request": recall_request(run, items, query, max(3, len(items) // 2))}]
    if items:
        out.append({"type": "similar", "file": "similar.json", "run": run["name"], "thread": None,
                    "reason": "all end-of-run active entries", "message_id": None,
                    "request": similar_request(run, items)})
    return out


def cmd_build(a) -> int:
    runs = [load_run(d) for d in run_dirs(a.results)]
    if not runs:
        raise SystemExit("no run folder (meta.json + log.json) under: " + " ".join(a.results))
    index, count = [], {}
    for run in runs:
        jobs = build_run(run) + build_run_tail(run)
        d = Path(a.out) / run["name"]
        d.mkdir(parents=True, exist_ok=True)
        for j in jobs:
            validate(j["request"], j["type"])
            write_json(d / j["file"], j["request"])
            index.append({"file": f"{run['name']}/{j['file']}", "run": run["name"], "type": j["type"],
                          "thread": j["thread"], "reason": j["reason"], "message_id": j["message_id"]})
        count[run["name"]] = sum(j["type"] == "curate" for j in jobs)
    write_json(Path(a.out) / "index.json", {"requests": index, "curate_per_run": count})
    print(f"build: {len(runs)} runs, {len(index)} requests -> {a.out}")
    for k, v in sorted(count.items()):
        print(f"  {k}: {v} curate")
    return 0


# ---------------------------------------------------------------- validate (contract + XMUSE2-MO-ALIGN §3)
class BadRequest(ValueError):
    pass


def _check(cond, msg):
    if not cond:
        raise BadRequest(msg)


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def validate(req: dict, kind: str) -> dict:
    """Reject anything the contract (v1.2) or the alignment doc's field limits forbid. Returns the request."""
    _check(isinstance(req, dict) and req.get("schema") == f"memoryos_{kind}/v1", f"{kind}: bad schema")
    if kind == "curate":
        _curate_ok(req)
    elif kind == "recall":
        _recall_ok(req)
    elif kind == "similar":
        _similar_ok(req)
    else:
        raise BadRequest(f"unknown request kind {kind!r}")
    return req


def _act_ok(x, where):
    _check(isinstance(x, dict), f"{where}: not an object")
    _check(_is_int(x.get("seq")) and x["seq"] >= 0, f"{where}.seq must be a non-negative int")
    _check(x.get("type") in ACTIVITY_TYPES, f"{where}.type must be one of {ACTIVITY_TYPES}")
    _check(isinstance(x.get("speaker"), str) and 0 < len(x["speaker"]) <= SPEAKER_CHARS, f"{where}.speaker")
    _check(isinstance(x.get("text"), str), f"{where}.text must be a string")
    if x.get("kind") is not None:
        _check(isinstance(x["kind"], str) and len(x["kind"]) <= 32, f"{where}.kind must be <= 32 chars")
    _check(isinstance(x.get("id"), str) and 0 < len(x["id"]) <= ITEM_ID, f"{where}.id")


def _curate_ok(req: dict) -> None:
    _check(req.get("profile") == "collab", "curate.profile must be 'collab'")
    _check(isinstance(req.get("scope_id"), str) and 0 < len(req["scope_id"]) <= SCOPE_ID, "curate.scope_id")
    _check(isinstance(req.get("active"), list) and len(req["active"]) <= ACTIVE, f"curate.active must be <= {ACTIVE}")
    seen = set()
    for i, e in enumerate(req["active"]):
        w = f"active[{i}]"
        _check(isinstance(e, dict), f"{w}: not an object")
        _check(isinstance(e.get("id"), str) and re.fullmatch(r"E\d+", e["id"] or ""), f"{w}.id must be E<n>")
        _check(e["id"] not in seen, f"{w}.id {e['id']} duplicated")
        seen.add(e["id"])
        # XMUSE2-MO-ALIGN 3.4: assignment is rejected with 422; hub filters it out before sending
        _check(e.get("kind") in KINDS, f"{w}.kind must be one of {KINDS} (assignment is not allowed in active)")
        _check(isinstance(e.get("topic_key"), str) and e["topic_key"], f"{w}.topic_key is required (v1.2)")
        _check(isinstance(e.get("statement"), str) and e["statement"].strip(), f"{w}.statement")
        _check(_is_int(e.get("version")) and e["version"] >= 0, f"{w}.version must be >= 0")
    win = req.get("window")
    _check(isinstance(win, list) and 1 <= len(win) <= WINDOW, f"curate.window must be 1..{WINDOW} activities")
    ids = set()
    for i, x in enumerate(win):
        _act_ok(x, f"window[{i}]")
        _check(x["id"] not in ids, f"window[{i}].id {x['id']} must be unique inside the request")
        ids.add(x["id"])
        _check(len(x["text"]) <= WINDOW_TEXT, f"window[{i}].text must be <= {WINDOW_TEXT} chars")
    ctx = req.get("context")
    _check(isinstance(ctx, list) and len(ctx) <= CONTEXT, f"curate.context must be <= {CONTEXT} activities")
    for i, x in enumerate(ctx):
        _act_ok(x, f"context[{i}]")
    mr = req.get("max_repairs")
    _check(_is_int(mr) and 0 <= mr <= 2, "curate.max_repairs must be 0..2")  # memoryos.py sends 1


def _recall_ok(req: dict) -> None:
    _check(isinstance(req.get("query"), str) and len(req["query"]) <= QUERY_CHARS, "recall.query <= 4000 chars")
    items = req.get("items")
    _check(isinstance(items, list) and len(items) <= 500, "recall.items must be <= 500")
    seen = set()
    for i, it in enumerate(items):
        w = f"items[{i}]"
        _check(isinstance(it, dict), f"{w}: not an object")
        _check(isinstance(it.get("id"), str) and 0 < len(it["id"]) <= ITEM_ID, f"{w}.id is 1..{ITEM_ID} chars")
        _check(it["id"] not in seen, f"{w}.id {it['id']} duplicated")
        seen.add(it["id"])
        _check(isinstance(it.get("text"), str) and 0 < len(it["text"]) <= ITEM_TEXT, f"{w}.text is 1..{ITEM_TEXT}")
        _check(_is_int(it.get("seq")) and it["seq"] >= 0, f"{w}.seq must be >= 0")
        _check(it.get("kind") is None or (isinstance(it["kind"], str) and len(it["kind"]) <= 32),
               f"{w}.kind is a free label of <= 32 chars")
        _check(it.get("roles") is None or (isinstance(it["roles"], list) and len(it["roles"]) <= 16), f"{w}.roles")
    b = req.get("budget_tokens")
    _check(_is_int(b) and 1 <= b <= 200_000, "recall.budget_tokens must be 1..200000")
    _check(_is_int(req.get("k")) and 1 <= req["k"] <= 500, "recall.k must be 1..500")
    hints = req.get("hints")
    _check(isinstance(hints, dict) and set(hints) <= {"thread_id", "role"}, "recall.hints may hold thread_id/role")


def _similar_ok(req: dict) -> None:
    items = req.get("items")
    _check(isinstance(items, list) and len(items) <= 500, "similar.items must be <= 500")
    for i, it in enumerate(items):
        _check(isinstance(it, dict) and isinstance(it.get("id"), str) and isinstance(it.get("text"), str),
               f"items[{i}] needs id and text")
    t = req.get("threshold")
    _check(isinstance(t, (int, float)) and not isinstance(t, bool) and 0 < t <= 1, "similar.threshold in (0, 1]")


# ---------------------------------------------------------------- send
URLS = {"curate": "/curate", "recall": "/recall", "similar": "/similar"}
TIMEOUTS = {"curate": 480, "recall": 10, "similar": 30}   # spec section 3.2
HEALTH_TIMEOUT = 5


def post(url: str, path: str, body: dict, timeout: float) -> dict:
    """One call. Every failure becomes a value, never an exception (the hub's Client.call does the same)."""
    t0 = time.time()
    try:
        req = urllib.request.Request(url.rstrip("/") + path, data=json.dumps(body).encode("utf-8"),
                                     headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
        return {"status": r.status, "seconds": round(time.time() - t0, 3),
                "body": json.loads(raw.decode("utf-8"))}
    except urllib.error.HTTPError as e:
        return {"status": e.code, "seconds": round(time.time() - t0, 3),
                "error": f"{e.code} {e.reason}", "body": _safe(e.read())}
    except Exception as e:  # noqa: BLE001 - timeout, connection refused, bad JSON: all "memory unavailable"
        return {"status": None, "seconds": round(time.time() - t0, 3), "error": f"{type(e).__name__}: {e}"}


def _safe(raw):
    try:
        return json.loads(raw.decode("utf-8"))
    except Exception:  # noqa: BLE001
        return raw[:500].decode("utf-8", "replace")


def health(url: str) -> dict:
    """A service that does not answer /health is not a service: exit 2 (nothing can be sent or spent)."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=HEALTH_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        print(f"/health failed for {url}: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(2)


def cmd_send(a) -> int:
    index = json.loads((Path(a.out) / "index.json").read_text(encoding="utf-8"))["requests"]
    caps = set(health(a.url).get("capabilities") or [])
    wanted = {"curate": "curate.collab", "recall": "recall", "similar": "similar"}
    todo = [r for r in index if (not a.only or r["type"] in a.only) and wanted[r["type"]] in caps]
    skipped = [r["file"] for r in index if r["type"] not in {x["type"] for x in todo}]
    calls = 0
    for r in todo:
        dest = Path(a.out) / r["file"]
        resp = dest.with_suffix(".resp.json")
        if resp.exists():
            print(f"skip (has response): {r['file']}")
            continue
        if calls >= a.max_calls:
            print(f"stop: --max-calls {a.max_calls} reached, {len(todo) - calls} request(s) left")
            break
        calls += 1
        body = json.loads(dest.read_text(encoding="utf-8"))
        body.pop("_replay", None)  # offline scoring metadata stays on disk (score reads it there); never sent
        out = post(a.url, URLS[r["type"]], body, TIMEOUTS[r["type"]])
        write_json(resp, out)
        print(f"{r['type']:7} {r['file']:22} status={out['status']} {out['seconds']}s"
              + (f" error={out['error']}" if out.get("error") else ""))
    if skipped:
        print("skipped (capability missing or --only): " + ", ".join(sorted(set(skipped))))
    print(f"send: {calls} call(s)")
    return 0


# ---------------------------------------------------------------- score
def load_requests(outdir: Path, index) -> list:
    out = []
    for r in index:
        p = outdir / r["file"]
        if not p.exists():
            continue
        resp = p.with_suffix(".resp.json")
        out.append({**r, "request": json.loads(p.read_text(encoding="utf-8")),
                    "response": json.loads(resp.read_text(encoding="utf-8")) if resp.exists() else None})
    return out


def checklist(exp: Path, seed: str) -> list:
    f = exp / "declare-checklist" / f"{seed}.txt"
    if not f.exists():
        return []
    return [(ln.split("|", 1)[0].strip(), ln.split("|", 1)[1].strip())
            for ln in f.read_text(encoding="utf-8").splitlines() if "|" in ln and not ln.startswith("#")]


def norm(s: str) -> str:
    """The hub's duplicate test: statement equality ignoring whitespace and case (XMUSE2-MO-ALIGN 3.4)."""
    return re.sub(r"\s+", "", str(s or "")).lower()


def hits(texts, items) -> list:
    return [label for label, rx in items if any(re.search(rx, t or "", re.I) for t in texts)]


def responses_of(reqs, kind: str) -> list:
    return [r for r in reqs if r["type"] == kind and r["response"] and r["response"].get("body")]


def _memories(r) -> list:
    return (r["response"].get("body") or {}).get("memories") or []


def propose_text(m) -> str:
    """The text a proposal would put into the library (statement + its quotes)."""
    quotes = [s.get("quote") or "" for s in (m.get("sources") or []) if isinstance(s, dict)]
    return str(m.get("statement") or "") + "\n" + "\n".join(quotes)


def agent_entries(run: dict) -> list:
    """Port of metrics.py:declaration - decision/assumption/convention entries authored by an agent (not human)."""
    agents = {a[0] for a in (run["meta"].get("agents") or [])} or \
             {m["sender"] for m in run["messages"] if m.get("sender") != "human"}
    return [e for e in run["entries"]
            if e.get("kind") in ("decision", "assumption", "convention") and e.get("author") in agents]


def active_texts(run: dict, active_ids) -> set:
    """Normalized statements of the entries the request itself carried (the hub's duplicate test)."""
    keep = set(active_ids)
    return {norm(x["statement"]) for x in run["entries"] if f"E{int(x['id'])}" in keep}


def score_run(run: dict, reqs: list, exp: Path, seed: str) -> dict:
    items = checklist(exp, seed)
    active = {f"E{int(e['id'])}": e for e in _final_active(run)}
    rot = run["meta"].get("rot") or {}
    rot_at = float(rot.get("at") or 0) if rot.get("injected") else None
    declared = hits([e["statement"] for e in agent_entries(run)], items)

    # a) declaration gap
    cur = [r for r in reqs if r["type"] == "curate"]
    proposed = [m for r in cur for m in _memories(r)]
    covered = hits([propose_text(m) for m in proposed], items)
    gap = {"labels": len(items), "declared_by_agents": sorted(declared), "declared_count": len(declared),
           "curate_covered": sorted(covered), "curate_new": sorted(set(covered) - set(declared)),
           "still_missing": sorted({l for l, _ in items} - set(declared) - set(covered)),
           "proposals": len(proposed)}

    # b) rot conflict: did curate touch the convention the rot overturned?
    superseded, conflicts = [], []
    for r in cur:
        aid = set(r["request"].get("_replay", {}).get("active_ids") or [])
        at = r["request"].get("_replay", {}).get("at")
        for m in _memories(r):
            sid = m.get("supersedes_id")
            if not sid or sid not in aid:
                continue
            superseded.append({"file": r["file"], "at": at, "supersedes_id": sid,
                               "old_statement": active.get(sid, {}).get("statement"),
                               "old_recorded_at": iso(active[sid]["recorded_at"]) if sid in active else None,
                               "after_rot": bool(rot_at and at and _epoch(at) >= rot_at),
                               "proposal": m.get("statement")})
        for c in (r["response"].get("body") or {}).get("conflicts") or []:
            conflicts.append({**{k: c.get(k) for k in ("a_id", "b_id", "reason")}, "file": r["file"], "at": at,
                              "after_rot": bool(rot_at and at and _epoch(at) >= rot_at)})
    after_rot = [c for c in superseded + conflicts if c["after_rot"]]
    rot_sec = {"injected": bool(rot.get("injected")), "kind": rot.get("kind"), "at": iso(rot_at) if rot_at else None,
               "superseded_ids": superseded, "conflicts": conflicts,
               "first_curate_after_rot_touches_old": bool(after_rot),
               "rot_entry_still_active_at_end": any(
                   norm(e["statement"]) == norm(rot.get("text")) for e in active.values())}

    # c) noise
    aid = {x for r in cur for x in (r["request"].get("_replay", {}).get("active_ids") or [])}
    known = active_texts(run, aid)
    dup, unmatched = 0, []
    for m in proposed:
        if norm(m.get("statement")) in known:
            dup += 1
        if not hits([propose_text(m)], items):
            unmatched.append({"id": m.get("id"), "kind": m.get("kind"),
                              "statement": m.get("statement"), "supersedes_id": m.get("supersedes_id")})
    noise = {"proposals": len(proposed), "duplicates_of_active": dup,
             "unmatched_checklist": unmatched, "unmatched_count": len(unmatched)}

    # d) /recall
    recall = {"requests": 0, "compared": [], "checklist_kept": {"memoryos": 0, "newest_by_seq": 0},
              "memoryos_only": [], "newest_only": [], "dense": None, "token_estimator": None}
    for r in [x for x in reqs if x["type"] == "recall"]:
        body = r["response"].get("body") or {}
        ranked = [x.get("id") for x in body.get("ranked") or []]
        items_by_id = {i["id"]: i for i in r["request"]["items"]}
        by_seq = [i["id"] for i in sorted(r["request"]["items"], key=lambda i: (-i["seq"], i["id"]))[:len(ranked)]]
        keep_m, keep_s = set(ranked), set(by_seq)
        lab = lambda ids: sorted(set(hits([items_by_id[i]["text"] for i in ids if i in items_by_id], items)))
        recall["requests"] += 1
        recall["compared"].append({"file": r["file"], "items": len(items_by_id), "k": r["request"]["k"],
                                   "ranked": len(ranked), "kept_by_memoryos": sorted(keep_m),
                                   "kept_by_newest": sorted(keep_s), "shared": sorted(keep_m & keep_s)})
        recall["memoryos_only"] += sorted(keep_m - keep_s)
        recall["newest_only"] += sorted(keep_s - keep_m)
        recall["checklist_kept"]["memoryos"] += len(lab(keep_m))
        recall["checklist_kept"]["newest_by_seq"] += len(lab(keep_s))
        recall["checklist_memoryos"] = sorted(set(recall.get("checklist_memoryos") or []) | set(lab(keep_m)))
        recall["checklist_newest"] = sorted(set(recall.get("checklist_newest") or []) | set(lab(keep_s)))
        recall["dense"] = (body.get("diagnostics") or {}).get("dense")
        recall["token_estimator"] = (body.get("diagnostics") or {}).get("token_estimator")

    # e) cost
    cost = {"curate": [], "recall_seconds": [], "similar_seconds": [], "usage_total": {},
            "unmetered_attempts": 0, "errors": []}
    for r in reqs:
        resp = r["response"]
        if not resp:
            continue
        if resp.get("error") or (resp.get("status") or 0) >= 400:
            cost["errors"].append({"file": r["file"], "type": r["type"], "status": resp.get("status"),
                                   "error": resp.get("error")})
        if r["type"] == "curate":
            d = (resp.get("body") or {}).get("diagnostics") or {}
            u = d.get("usage") or {}
            cost["curate"].append({"file": r["file"], "seconds": resp.get("seconds"), "status": resp.get("status"),
                                   "llm_calls": d.get("llm_calls"), "repairs": d.get("repairs"), "usage": u,
                                   "attempts": len(d.get("attempts") or []) or u.get("attempts"),
                                   "unmetered_attempts": u.get("unmetered_attempts") or 0,
                                   "lower_bound": bool(u.get("unmetered_attempts"))})
            cost["unmetered_attempts"] += u.get("unmetered_attempts") or 0
            for k, v in u.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    cost["usage_total"][k] = cost["usage_total"].get(k, 0) + v
        elif r["type"] == "recall":
            cost["recall_seconds"].append(resp.get("seconds"))
        elif r["type"] == "similar":
            cost["similar_seconds"].append(resp.get("seconds"))
    return {"run": run["name"], "seed": seed, "threads": sorted({r["thread"] for r in cur if r["thread"]}),
            "requests": {"curate": len(cur), "recall": len([r for r in reqs if r["type"] == "recall"]),
                         "similar": len([r for r in reqs if r["type"] == "similar"])},
            "declaration": gap, "rot": rot_sec, "noise": noise, "recall": recall, "cost": cost}


def _epoch(at: str) -> float:
    return calendar.timegm(time.strptime(at, "%Y-%m-%dT%H:%M:%SZ"))   # iso() writes UTC


def cmd_score(a) -> int:
    outdir = Path(a.out_dir)
    root = Path(a.out)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))["requests"]
    reqs = load_requests(root, index)
    exp = Path(a.checklist)
    runs = {d.name: load_run(d) for d in run_dirs([a.results])}
    per_run = []
    # a run with no trigger at all (every message fits in one window) still belongs in the report, with zero rows
    for name in sorted(runs):
        mine = [r for r in reqs if r["run"] == name]
        per_run.append(score_run(runs[name], mine, exp, seed_of(runs[name], name, mine)))
    for name in sorted({r["run"] for r in reqs} - set(runs)):
        mine = [r for r in reqs if r["run"] == name]
        per_run.append(score_run({"name": name, "meta": {}, "entries": [], "events": [], "messages": []},
                                 mine, exp, seed_of({"meta": {}}, name, mine)))
    report = {"runs": per_run, "totals": totals(per_run), "requests": len(index),
              "responded": sum(1 for r in reqs if r["response"]), "checklist_dir": str(exp)}
    write_json(outdir / "report.json", report)
    outdir.mkdir(parents=True, exist_ok=True)
    (outdir / "report.md").write_text(markdown(report), encoding="utf-8", newline="\n")
    print(f"score: {len(per_run)} runs, {report['responded']}/{report['requests']} requests answered -> {outdir}/report.md")
    return 0


def seed_of(run: dict, name: str, reqs=()) -> str:
    """The seed names declare-checklist/<seed>.txt. scope_id is a thread ("#task"), so it is no help; the run's
    meta.json is authoritative and _replay carries it into the request for tools that only have the file."""
    if run["meta"].get("seed"):
        return str(run["meta"]["seed"])
    for r in reqs:
        if (r.get("request") or {}).get("_replay", {}).get("seed"):
            return str(r["request"]["_replay"]["seed"])
    return name.split("-")[0]


def totals(per_run: list) -> dict:
    return {"runs": len(per_run),
            "proposals": sum(r["noise"]["proposals"] for r in per_run),
            "duplicates": sum(r["noise"]["duplicates_of_active"] for r in per_run),
            "unmatched": sum(r["noise"]["unmatched_count"] for r in per_run),
            "curate_new_declarations": sum(len(r["declaration"]["curate_new"]) for r in per_run),
            "rot_conflicts": sum(len(r["rot"]["superseded_ids"]) + len(r["rot"]["conflicts"]) for r in per_run),
            "recall_requests": sum(r["requests"]["recall"] for r in per_run),
            "seconds": {"recall": round(sum(s for r in per_run for s in r["cost"]["recall_seconds"]
                                            if s is not None), 3),
                        "similar": round(sum(s for r in per_run for s in r["cost"]["similar_seconds"]
                                             if s is not None), 3)},
            "usage_total": {k: v for r in per_run for k, v in r["cost"]["usage_total"].items()}}


def markdown(rep: dict) -> str:
    L = ["# MemoryOS offline replay report", "",
         f"{rep['responded']}/{rep['requests']} requests have a response. "
         "`unmetered_attempts > 0` means the token usage is a lower bound.", "", "## a) declaration gap", "",
         "| run | checklist | declared by agents | new from /curate | still missing | proposals |",
         "|---|---|---|---|---|---|"]
    for r in rep["runs"]:
        d = r["declaration"]
        L.append(f"| {r['run']} | {d['labels']} | {d['declared_count']} | {len(d['curate_new'])} "
                 f"| {len(d['still_missing'])} | {d['proposals']} |")
    for r in rep["runs"]:
        d = r["declaration"]
        L += ["", f"### {r['run']}", f"- declared: {', '.join(d['declared_by_agents']) or '-'}",
              f"- added by /curate: {', '.join(d['curate_new']) or '-'}",
              f"- still missing: {', '.join(d['still_missing']) or '-'}"]
    L += ["", "## b) rot conflicts", "",
          "| run | rot injected | supersedes after rot | conflicts | first post-rot curate touches an old entry |",
          "|---|---|---|---|---|"]
    for r in rep["runs"]:
        t = r["rot"]
        L.append(f"| {r['run']} | {t['injected']} {t['kind'] or ''} | {len(t['superseded_ids'])} "
                 f"| {len(t['conflicts'])} | {t['first_curate_after_rot_touches_old']} |")
    for r in rep["runs"]:
        for s in r["rot"]["superseded_ids"]:
            L.append(f"- {r['run']} {s['file']} @{s['at']}: supersedes {s['supersedes_id']} "
                     f"(after rot: {s['after_rot']}) - old: {short(s['old_statement'])} | new: {short(s['proposal'])}")
        for c in r["rot"]["conflicts"]:
            L.append(f"- {r['run']} {c['file']} @{c['at']}: conflict {c['a_id']} vs {c['b_id']} "
                     f"(after rot: {c['after_rot']}) - {short(c['reason'])}")
    L += ["", "## c) noise", "", "| run | proposals | duplicates of active | not matched by any checklist item |",
          "|---|---|---|---|"]
    for r in rep["runs"]:
        n = r["noise"]
        L.append(f"| {r['run']} | {n['proposals']} | {n['duplicates_of_active']} | {n['unmatched_count']} |")
    false_positives = [(r["run"], m) for r in rep["runs"] for m in r["noise"]["unmatched_checklist"]]
    if false_positives:
        L += ["", "Unmatched proposals (left for a human: no checklist item claims them, this is not a verdict):", ""]
        for run, m in false_positives:
            L.append(f"- {run} [{m.get('kind')}] {m.get('id')}: {short(m.get('statement'), 400)}")
    L += ["", "## d) /recall: MemoryOS ranking vs newest-by-seq", "",
          "| run | items | kept | kept by /recall only | kept by newest only | checklist kept (/recall) | checklist kept (newest) |",
          "|---|---|---|---|---|---|---|"]
    for r in rep["runs"]:
        cmp = r["recall"]["compared"][0] if r["recall"]["compared"] else {}
        L.append(f"| {r['run']} | {cmp.get('items', '-')} | {cmp.get('ranked', '-')} "
                 f"| {len(r['recall']['memoryos_only'])} | {len(r['recall']['newest_only'])} "
                 f"| {r['recall']['checklist_kept']['memoryos']} | {r['recall']['checklist_kept']['newest_by_seq']} |")
    for r in rep["runs"]:
        if r["recall"]["compared"]:
            c = r["recall"]["compared"][0]
            L.append(f"- {r['run']}: /recall kept {', '.join(c['kept_by_memoryos']) or '-'}; newest-by-seq kept "
                     f"{', '.join(c['kept_by_newest']) or '-'}; shared {', '.join(c['shared']) or '-'}; "
                     f"hit checklist in /recall: {', '.join(r['recall'].get('checklist_memoryos') or []) or '-'}; "
                     f"in newest: {', '.join(r['recall'].get('checklist_newest') or []) or '-'}")
    L += ["", "## e) cost", "", "| run | curate calls | curate seconds | recall seconds | similar seconds "
          "| usage (lower bound when unmetered) |", "|---|---|---|---|---|---|"]
    for r in rep["runs"]:
        c = r["cost"]
        secs = [x["seconds"] for x in c["curate"] if x["seconds"] is not None]
        L.append(f"| {r['run']} | {len(c['curate'])} | {', '.join(str(s) for s in secs) or '-'} "
                 f"| {sum(x for x in c['recall_seconds'] if x is not None):.3f} "
                 f"| {sum(x for x in c['similar_seconds'] if x is not None):.3f} | {json.dumps(c['usage_total'])} |")
    L += ["", "### tokens and attempts per curate call", "",
          "| run | file | status | seconds | llm_calls | repairs | attempts | unmetered | usage |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rep["runs"]:
        for x in r["cost"]["curate"]:
            L.append(f"| {r['run']} | {x['file']} | {x['status']} | {x['seconds']} | {x['llm_calls']} "
                     f"| {x['repairs']} | {x['attempts']} | {x['unmetered_attempts']} | {json.dumps(x['usage'])} |")
    if any(r["cost"]["errors"] for r in rep["runs"]):
        L += ["", "### failures (recorded, never fatal)", ""]
        for r in rep["runs"]:
            for e in r["cost"]["errors"]:
                L.append(f"- {r['run']} {e['file']}: status={e['status']} {e['error']}")
    return "\n".join(L) + "\n"


def short(s, n: int = 160) -> str:
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s[:n] + ("…" if len(s) > n else "")


# ---------------------------------------------------------------- io / cli
def write_json(path: Path, obj) -> None:
    """Deterministic on purpose: sorted keys and a fixed newline, so two builds of the same input are byte-equal."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n",
                          encoding="utf-8", newline="\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="replay_mo.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="rebuild the requests a run would have sent (offline)")
    b.add_argument("results", nargs="+", help="run folders or parents of run folders")
    b.add_argument("--out", required=True, help="output directory for the requests")
    b.set_defaults(fn=cmd_build)
    s = sub.add_parser("send", help="send the built requests to a MemoryOS service")
    s.add_argument("out", help="directory written by build")
    s.add_argument("--url", default="http://127.0.0.1:8301")
    s.add_argument("--only", choices=sorted(TYPES), action="append", help="only this request type (repeatable)")
    s.add_argument("--max-calls", type=int, default=40, help="stop after N HTTP calls (default 40)")
    s.set_defaults(fn=cmd_send)
    c = sub.add_parser("score", help="score the responses into report.md + report.json (offline)")
    c.add_argument("out", help="directory written by build/send")
    c.add_argument("--out-dir", default=None, help="where report.md/report.json go (default: the build dir)")
    c.add_argument("--results", default="data/results", help="original run folders (default data/results)")
    c.add_argument("--checklist", default=str(Path(__file__).resolve().parent), help="declare-checklist parent")
    c.set_defaults(fn=cmd_score)
    a = ap.parse_args(argv)
    if a.cmd == "score" and a.out_dir is None:
        a.out_dir = a.out
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
