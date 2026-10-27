"""Probe check for `xmuse trace export`.

For each run, derive the spans locally from its hub.db (the same otel.spans() replay uses) and compare them with
what the backend holds, read back through Phoenix's REST API:
  - every derived span is in Phoenix, with the same parent;
  - span counts equal the hub.db rows (terminal turns, messages, decided approvals, capped chains, finished
    MemoryOS calls);
  - token totals on the invoke_agent spans equal the usage table;
  - every MemoryOS call that got an HTTP answer has a MemoryOS server span whose parent is the call's client span
    (MemoryOS traced into the same project).
Read-only on both sides. Exit status 1 on any mismatch.

  hub/.venv/bin/python scripts/otel/check_replay.py [--endpoint URL] [--project NAME] RUN_DIR[=ROOM_ID] ...

ROOM_ID is the --room-id the run was replayed with. Without it, a db with a room row (a room's state dir, exported
live) uses that room; one without (an experiment run) uses the run directory's name. Without --project, each run is
looked up where the hub sends it: the shared project (otel.project, default "xmuse") for a db that recorded MemoryOS
calls, Phoenix's "default" for any other.
"""
import argparse
import collections
import json
import sqlite3
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from xmuse import otel

try:
    from xmuse import otel_remote  # registers the MemoryOS call source
except ImportError:  # a hub without the module: no MemoryOS call spans to check
    otel_remote = None


def phoenix_spans(endpoint: str, project: str) -> dict[str, dict]:
    out, cursor = {}, None
    while True:
        q = {"limit": "1000", **({"cursor": cursor} if cursor else {})}
        url = f"{endpoint.rstrip('/')}/v1/projects/{urllib.parse.quote(project)}/spans?{urllib.parse.urlencode(q)}"
        with urllib.request.urlopen(url, timeout=30) as r:
            d = json.load(r)
        for s in d["data"]:
            out[s["context"]["span_id"]] = s
        cursor = d.get("next_cursor")
        if not cursor:
            return out


def check(run: Path, room_id: str | None, remote: dict[str, dict]) -> dict:
    dbfile = run / "hub.db" if run.is_dir() else run
    conn = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    one = lambda sql: conn.execute(sql).fetchone()[0]
    try:
        own = otel._room(conn)["id"] if room_id is None else ""
        room_id = room_id if room_id is not None else own or run.name
        local = otel.spans(conn, room=None if own else (room_id, room_id))
        rows = {"invoke_agent": one("select count(*) from turns where state in"
                                    " ('succeeded','failed','interrupted','canceled')"),
                "xmuse.message": one("select count(*) from messages"),
                "xmuse.approval": one("select count(*) from approvals where decided_at is not null"),
                "xmuse.chain.capped": one("select count(*) from chains where state in ('capped','stopped')")}
        if otel_remote is not None and otel_remote._has_table(conn):
            rows["xmuse.memoryos.call"] = one("select count(*) from mo_calls where ended_at is not null")
            answered = {str(r[0]) for r in conn.execute("select id from mo_calls where status is not null")}
        else:
            answered = set()
        usage = dict(zip(("input", "output", "cache_read", "cache_write"), conn.execute(
            "select coalesce(sum(input),0), coalesce(sum(output),0), coalesce(sum(cache_read),0),"
            " coalesce(sum(cache_write),0) from usage").fetchone()))
        turns_by_agent = dict(conn.execute("select agent_id, count(*) from turns group by agent_id").fetchall())
    finally:
        conn.close()
    kinds = collections.Counter("xmuse.message" if s.name.startswith("xmuse.message") else
                                "invoke_agent" if s.name.startswith("invoke_agent") else
                                "xmuse.memoryos.call" if s.name.startswith("xmuse.memoryos.call") else s.name
                                for s in local)
    problems = [f"{k}: {kinds.get(k, 0)} spans, {n} rows" for k, n in rows.items() if kinds.get(k, 0) != n]
    found, tokens = 0, collections.Counter()
    for s in local:
        sid = format(s.context.span_id, "016x")
        r = remote.get(sid)
        if r is None:
            problems.append(f"missing in backend: {s.name} {sid}")
            continue
        found += 1
        want_parent = format(s.parent.span_id, "016x") if s.parent is not None else None
        if (r.get("parent_id") or None) != want_parent:
            problems.append(f"parent differs: {s.name} {sid}: backend {r.get('parent_id')}, derived {want_parent}")
        if s.name.startswith("invoke_agent"):
            a = r.get("attributes") or {}
            tokens["input"] += int(a.get(otel.ATTR_USAGE_IN) or 0)
            tokens["output"] += int(a.get(otel.ATTR_USAGE_OUT) or 0)
            tokens["cache_read"] += int(a.get(otel.ATTR_USAGE_CACHE_READ) or 0)
            tokens["cache_write"] += int(a.get(otel.ATTR_USAGE_CACHE_WRITE) or 0)
    if found == len(local):
        problems += [f"tokens {k}: backend {tokens[k]}, usage {v}" for k, v in usage.items() if tokens[k] != v]
    mo = memoryos_side(local, answered, remote, problems)
    return {"run": str(run), "room_id": room_id, "rows": rows, "spans_derived": len(local), "spans_in_backend": found,
            "usage": usage, "backend_tokens": dict(tokens), "turns_by_agent": turns_by_agent, **mo,
            "problems": problems}


def memoryos_side(local: list, answered: set[str], remote: dict[str, dict], problems: list[str]) -> dict:
    """Under each answered MemoryOS call's client span: one MemoryOS server span, and whatever MemoryOS traced
    below it (graph nodes, LLM calls), all in the call's trace."""
    children = collections.defaultdict(list)
    for r in remote.values():
        if r.get("parent_id"):
            children[r["parent_id"]].append(r)
    servers, below = 0, collections.Counter()
    for s in local:
        cid = (s.attributes or {}).get("xmuse.memoryos.call.id")
        if cid is None or str(cid) not in answered:
            continue
        sid, trace = format(s.context.span_id, "016x"), format(s.context.trace_id, "032x")
        mine = [r for r in children.get(sid, []) if r["name"].startswith("POST ")]
        if len(mine) != 1:
            problems.append(f"{len(mine)} MemoryOS server spans under {s.name} {sid}")
            continue
        servers += 1
        todo = [mine[0]]
        while todo:
            r = todo.pop()
            if r["context"]["trace_id"] != trace:
                problems.append(f"MemoryOS span {r['name']} {r['context']['span_id']} left trace {trace}")
            below[(s.attributes or {}).get("url.path", "?")] += 1
            todo += children.get(r["context"]["span_id"], [])
    return {"memoryos_calls_answered": len(answered), "memoryos_server_spans": servers,
            "memoryos_spans_by_path": dict(below)}


def project_of(run: Path) -> str:
    """The Phoenix project the hub sends this db's spans to: the shared one (otel.project in the run's config.json,
    else $XMUSE_OTEL_PROJECT, else "xmuse") once it recorded MemoryOS calls, else Phoenix's "default"."""
    dbfile = run / "hub.db" if run.is_dir() else run
    if otel_remote is None:
        return "default"
    conn = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    try:
        if not otel_remote._has_table(conn):
            return "default"
    finally:
        conn.close()
    cfg = dbfile.parent / "config.json"
    return otel_remote.project(json.loads(cfg.read_text(encoding="utf-8")) if cfg.exists() else {})


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--endpoint", default="http://localhost:6006")
    ap.add_argument("--project", help="Phoenix project for every run (default: where the hub sent each one)")
    ap.add_argument("runs", nargs="+", help="RUN_DIR[=ROOM_ID]")
    a = ap.parse_args()
    remote: dict[str, dict] = {}
    out = []
    for spec in a.runs:
        path, eq, room = spec.partition("=")
        run = Path(path).expanduser()
        project = a.project or project_of(run)
        if project not in remote:
            remote[project] = phoenix_spans(a.endpoint, project)
        out.append({"project": project, **check(run, room if eq else None, remote[project])})
    print(json.dumps({"backend_spans": {p: len(s) for p, s in remote.items()}, "runs": out}, indent=1,
                     ensure_ascii=False))
    sys.exit(1 if any(r["problems"] for r in out) else 0)


if __name__ == "__main__":
    main()
