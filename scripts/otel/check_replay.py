"""Probe check for `xmuse trace export`.

For each run, derive the spans locally from its hub.db (the same otel.spans() replay uses) and compare them with
what the backend holds, read back through Phoenix's REST API:
  - every derived span is in Phoenix, with the same parent;
  - span counts equal the hub.db rows (terminal turns, messages, decided approvals, capped chains);
  - token totals on the invoke_agent spans equal the usage table.
Read-only on both sides. Exit status 1 on any mismatch.

  hub/.venv/bin/python scripts/otel/check_replay.py [--endpoint URL] [--project NAME] RUN_DIR[=ROOM_ID] ...

ROOM_ID is the --room-id the run was replayed with (default: the run directory's name).
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


def check(run: Path, room_id: str, remote: dict[str, dict]) -> dict:
    dbfile = run / "hub.db" if run.is_dir() else run
    conn = sqlite3.connect(f"file:{dbfile}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    one = lambda sql: conn.execute(sql).fetchone()[0]
    try:
        local = otel.spans(conn, room=(room_id, room_id))
        rows = {"invoke_agent": one("select count(*) from turns where state in"
                                    " ('succeeded','failed','interrupted','canceled')"),
                "xmuse.message": one("select count(*) from messages"),
                "xmuse.approval": one("select count(*) from approvals where decided_at is not null"),
                "xmuse.chain.capped": one("select count(*) from chains where state in ('capped','stopped')")}
        usage = dict(zip(("input", "output", "cache_read", "cache_write"), conn.execute(
            "select coalesce(sum(input),0), coalesce(sum(output),0), coalesce(sum(cache_read),0),"
            " coalesce(sum(cache_write),0) from usage").fetchone()))
        turns_by_agent = dict(conn.execute("select agent_id, count(*) from turns group by agent_id").fetchall())
    finally:
        conn.close()
    kinds = collections.Counter("xmuse.message" if s.name.startswith("xmuse.message") else
                                "invoke_agent" if s.name.startswith("invoke_agent") else s.name for s in local)
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
    return {"run": str(run), "room_id": room_id, "rows": rows, "spans_derived": len(local), "spans_in_backend": found,
            "usage": usage, "backend_tokens": dict(tokens), "turns_by_agent": turns_by_agent, "problems": problems}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--endpoint", default="http://localhost:6006")
    ap.add_argument("--project", default="default")
    ap.add_argument("runs", nargs="+", help="RUN_DIR[=ROOM_ID]")
    a = ap.parse_args()
    remote = phoenix_spans(a.endpoint, a.project)
    out = []
    for spec in a.runs:
        path, _, room = spec.partition("=")
        p = Path(path).expanduser()
        out.append(check(p, room or p.name, remote))
    print(json.dumps({"backend_spans": len(remote), "runs": out}, indent=1, ensure_ascii=False))
    sys.exit(1 if any(r["problems"] for r in out) else 0)


if __name__ == "__main__":
    main()
