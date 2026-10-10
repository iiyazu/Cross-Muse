#!/usr/bin/env python3
"""Minimal fake MemoryOS for replay_mo.py tests: /health, /curate (collab), /recall, /similar.

Standard library only. The answers are deliberately deterministic and derived from the request, so the fake works
on synthetic test runs *and* on the real data/results runs:

  /health    -> all four capabilities, always.
  /curate    -> 2-3 proposals: one statement built from a declare-checklist regex of the run (it must hit the
                checklist), one exact copy of an active entry (a duplicate), plus supersedes/conflict wiring;
                every source quote is a verbatim substring of a window activity, as the real service guarantees.
  /recall    -> ranked by id descending, i.e. the opposite of the hub's "newest by seq" fallback.
  /similar   -> one pair (the first two items), 0.91.

usage: fake_mo_server.py [--port N] [--checklist DIR]   (default port 8301, checklist: this directory)
"""
import argparse
import json
import re
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

EXP = Path(__file__).resolve().parent
CAPS = ["curate", "curate.collab", "recall", "similar"]


def parse_checklist(seed: str, root: Path) -> list:
    f = root / "declare-checklist" / f"{seed}.txt"
    if not f.exists():
        return []
    return [(ln.split("|", 1)[0].strip(), ln.split("|", 1)[1].strip())
            for ln in f.read_text(encoding="utf-8").splitlines() if "|" in ln and not ln.startswith("#")]


def checklist_labels(seed: str, root: Path) -> list:
    return [label for label, _ in parse_checklist(seed, root)]


def _strip_groups(rx: str) -> str:
    """Drop parentheses but keep their contents, so alternatives inside a group survive as branches."""
    return rx.replace("(", "").replace(")", "")


def _literals(branch: str) -> list:
    """The literal runs of one regex branch; character classes, escapes and .* become a space (a wildcard gap)."""
    out, cur, i = [], "", 0
    while i < len(branch):
        c = branch[i]
        if c == "\\":
            i += 1
            nxt = branch[i] if i < len(branch) else ""
            cur += nxt if nxt and not nxt.isalnum() else " "  # \. is a literal dot; \d, \b are not text
        elif c == "[":
            i = branch.find("]", i) if "]" in branch[i:] else len(branch)
            cur += " "
        elif c in ".*+?^$":
            cur += " "
        elif c == "|":
            out, cur = out + [cur], ""
        else:
            cur += c
        i += 1
    return [re.sub(r"\s+", " ", x).strip() for x in out + [cur]]


def literal(rx: str) -> str:
    """A phrase the checklist regex is guaranteed to match, built by un-parsing the pattern."""
    cands = [x for b in _strip_groups(rx).split("|") for x in _literals(b)]
    for cand in sorted(set(cands), key=len, reverse=True):
        if cand and re.search(rx, cand, re.I):
            return cand
    return ""


def hit_proposal(seed: str, root: Path, window: list) -> dict:
    """A proposal whose statement matches exactly one checklist item (the report must count it as covered)."""
    label, word = "convention", ""
    for lab, rx in parse_checklist(seed, root):
        for cand in sorted(set(_candidates(rx)), key=len, reverse=True):
            body = f"Off-line proposal (fake service): {cand}."
            if re.search(rx, body, re.I) and not re.search(lab, body, re.I):
                label, word = lab, cand
                break
        if word:
            break
    body = f"Off-line proposal (fake service): {word}." if word else "Off-line proposal (fake service)."
    return {"id": "mem_fake_checklist", "kind": "convention", "topic_key": f"e{label}", "statement": body,
            "version": max([w.get("seq") or 0 for w in window] or [0]), "confidence": 0.9,
            "sources": [{"activity_id": window[0]["id"], "quote": _quote(window[0]["text"])}] if window else [],
            "supersedes_id": None, "resolves_ids": []}


def _candidates(rx: str) -> list:
    return [x for b in _strip_groups(rx).split("|") for x in _literals(b)]


def _quote(text: str) -> str:
    """A verbatim substring of the activity text; the real service validates quotes against the source."""
    return text[:120] if text else ""


def canon(req: dict) -> str:
    # `send` drops `schema` from /curate bodies (the real service rejects it), so it must not take part in matching
    return json.dumps({k: v for k, v in req.items() if k not in ("_replay", "schema")}, sort_keys=True)


def load_seeds(outdir: Path) -> dict:
    """canonical request body -> seed, from the replay_mo build folder. `send` strips the _replay block, so the
    fake finds the run's seed (for its declare-checklist) by matching the body against the files on disk."""
    seeds = {}
    for r in json.loads((Path(outdir) / "index.json").read_text(encoding="utf-8"))["requests"]:
        req = json.loads((Path(outdir) / r["file"]).read_text(encoding="utf-8"))
        seeds[canon(req)] = (req.get("_replay") or {}).get("seed")
    return seeds


def curate(req: dict, root: Path, seed=None) -> dict:
    # scope_id is a thread ("#task"): the seed comes from the build folder (see load_seeds), else "task"
    seed = str(seed or (req.get("_replay") or {}).get("seed") or "task")
    window = req.get("window") or []
    active = req.get("active") or []
    mem = [hit_proposal(seed, root, window)]
    if active:
        mem.append({"id": "mem_fake_duplicate", "kind": active[0]["kind"], "topic_key": active[0]["topic_key"],
                    "statement": active[0]["statement"], "version": active[0]["version"],
                    "sources": [{"activity_id": window[0]["id"], "quote": _quote(window[0]["text"])}] if window else [],
                    "supersedes_id": None, "resolves_ids": []})
    if len(active) > 1:
        mem.append({"id": "mem_fake_supersede", "kind": active[-1]["kind"], "topic_key": active[-1]["topic_key"],
                    "statement": "Replaces the oldest active entry (fake service).", "version": active[-1]["version"],
                    "sources": [{"activity_id": window[-1]["id"], "quote": _quote(window[-1]["text"])}] if window else [],
                    "supersedes_id": active[-1]["id"], "resolves_ids": []})
    conflicts = ([{"a_id": active[0]["id"], "b_id": active[1]["id"], "reason": "fake: statements may contradict",
                   "sources": [{"activity_id": window[0]["id"], "quote": _quote(window[0]["text"])}] if window else []}]
                 if len(active) > 1 else [])
    return {"schema": "memoryos_curate/v1", "scope_id": req.get("scope_id"), "memories": mem, "conflicts": conflicts,
            "assignments": [], "unaccounted": [],
            "diagnostics": {"llm_calls": 1, "repairs": 0, "attempts": [{"outcome": "ok", "secs": 0.01,
                                                                        "input_tokens": 700, "output_tokens": 300}],
                            "usage": {"input_tokens": 700, "output_tokens": 300, "attempts": 1,
                                      "unmetered_attempts": 0}}}


def recall(req: dict) -> dict:
    ranked = sorted(req.get("items") or [], key=lambda i: str(i.get("id")), reverse=True)[:int(req.get("k") or 0)]
    return {"schema": "memoryos_recall/v1",
            "ranked": [{"id": i["id"], "score": 1.0, "why": ["bm25"]} for i in ranked],
            "dropped": [i["id"] for i in (req.get("items") or []) if i not in ranked],
            "tokens_used": 0, "diagnostics": {"dense": False, "token_estimator": "fake/len"}}


def similar(req: dict) -> dict:
    ids = [i["id"] for i in (req.get("items") or [])]
    pairs = [{"a": a, "b": b, "score": 0.91} for a, b in zip(sorted(ids), sorted(ids)[1:])][:1]
    return {"schema": "memoryos_similar/v1", "pairs": pairs, "diagnostics": {"dense": True}}


class Handler(BaseHTTPRequestHandler):
    checklist = EXP
    calls: list = []
    seeds: dict = {}

    def do_GET(self):
        if self.path != "/health":
            return self._send(404, {"error": "not_found"})
        self._send(200, {"status": "ok", "version": "0.5.0-fake", "capabilities": CAPS})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        Handler.calls.append((self.path, body))
        fn = {"/curate": lambda: curate(body, self.checklist, self.seeds.get(canon(body))), "/recall": lambda: recall(body),
              "/similar": lambda: similar(body)}.get(self.path)
        self._send(200, fn()) if fn else self._send(404, {"error": "not_found"})

    def _send(self, code, obj):
        raw = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *a):
        pass


def serve(port: int = 8301, checklist: Path = EXP, requests: Path = None):
    Handler.checklist = Path(checklist)
    Handler.seeds = load_seeds(requests) if requests else {}
    ThreadingHTTPServer.daemon_threads = True
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    return httpd


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=8301)
    ap.add_argument("--checklist", default=str(EXP))
    ap.add_argument("--requests", help="replay_mo build folder: lets /curate know each run's seed")
    a = ap.parse_args(argv)
    httpd = serve(a.port, Path(a.checklist), Path(a.requests) if a.requests else None)
    print(f"fake MemoryOS on http://127.0.0.1:{httpd.server_address[1]}  (ctrl-c to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
