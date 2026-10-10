"""Alignment library (design §4.5, §4.5.1): declared decisions, assumptions, questions and assignments.

Entries are never deleted: every state change writes an entry_events row, whose seq also versions the
entry. `view` is the deterministic per-agent slice behind xmuse_context (hot path, no LLM).
Functions that write expect the caller's transaction, except `review` and `close_thread`.
"""
import json
import re

from . import db
from .tools import ToolError

LIMIT = 300


def _move(conn, eid: int, op: str, status: str) -> None:
    seq = conn.execute("insert into entry_events(entry_id, op, at) values(?,?,?)", (eid, op, db.now())).lastrowid
    conn.execute("update entries set status=?, seq=?, invalid_at=? where id=?",
                 (status, seq, None if status in ("active", "proposed") else db.now(), eid))


def _ref(conn, ref, status: str | None = "active", kinds=()) -> int:
    m = re.fullmatch(r"E?(\d+)", str(ref))
    r = m and conn.execute("select kind, status from entries where id=?", (m[1],)).fetchone()
    if not r or (status and r[1] != status) or (kinds and r[0] not in kinds):
        raise ToolError("invalid_arguments", f"{ref}: no {status or 'such'} entry"
                                             + (f" of kind {'/'.join(kinds)}" if kinds else ""))
    return int(m[1])


def add(conn, kind: str, scope: str, tid: str, statement: str, msg: int | list, author: str, supersedes: int | None = None,
        assignee: str | None = None, depends_on: list | None = None, status: str = "active",
        resolves: list | None = None) -> int:
    """A proposed entry only records `supersedes` / `resolves`; `review(confirm)` applies them."""
    if len(statement) > LIMIT:  # keep the first sentence; the full text stays in the referenced message
        first = re.split(r"(?<=[.!?。！？])\s", statement, maxsplit=1)[0]
        statement = first[:LIMIT - 1] + "…" if len(first) > LIMIT else first + " …"
    eid = conn.execute(
        "insert into entries(kind, scope, thread_id, statement, refs, author, status, supersedes, assignee, depends_on,"
        " resolves, valid_at, recorded_at, seq) values(?,?,?,?,?,?,?,?,?,?,?,?,?,0)",
        (kind, scope, tid, statement, json.dumps(msg if isinstance(msg, list) else [msg]), author, status, supersedes,
         assignee, json.dumps(depends_on) if depends_on else None, json.dumps(resolves) if resolves else None,
         db.now(), db.now())).lastrowid
    _move(conn, eid, "add", status)
    if supersedes and status == "active":
        _move(conn, supersedes, "supersede", "superseded")
    return eid


def declare(conn, author: str, tid: str, msg: int, kind: str, statement: str, scope: str | None = None,
            supersedes: str | None = None) -> int:
    scope = scope or "thread"
    if scope not in ("global", "thread") and not scope.startswith("role:"):
        raise ToolError("invalid_arguments", f"scope must be global, thread or role:<role>; got {scope!r}")
    old = _ref(conn, supersedes) if supersedes else None
    return add(conn, kind, f"thread:{tid}" if scope == "thread" else scope, tid, statement, msg, author, old)


def assign(conn, author: str, tid: str, msg: int, statement: str, assignees: list, depends_on: list) -> list[int]:
    deps = [_ref(conn, d, None) for d in depends_on]
    return [add(conn, "assignment", f"thread:{tid}", tid, statement, msg, author, assignee=a, depends_on=deps)
            for a in assignees]


def resolve(conn, refs: list) -> None:
    for eid in [_ref(conn, r, kinds=("question", "assignment")) for r in refs]:
        _move(conn, eid, "resolve", "resolved")


def review(conn, op: str, ref: str) -> dict:
    with db.tx(conn):
        eid = _ref(conn, ref, "proposed")
        _move(conn, eid, op, "active" if op == "confirm" else "rejected")
        if op == "confirm":  # a human accepted the proposal, including what it replaces or answers
            sup, res = conn.execute("select supersedes, resolves from entries where id=?", (eid,)).fetchone()
            for old, how, to in [(sup, "supersede", "superseded"), *((r, "resolve", "resolved") for r in json.loads(res or "[]"))]:
                if old and conn.execute("select 1 from entries where id=? and status='active'", (old,)).fetchone():
                    _move(conn, old, how, to)
    return {"ok": True}


def close_thread(conn, tid: str) -> dict:
    """Task closed: its specific entries decay out of every view (promotion to global is explicit)."""
    with db.tx(conn):
        ids = [r[0] for r in conn.execute("select id from entries where scope=? and status in ('active','proposed')",
                                          (f"thread:{tid}",))]
        for eid in ids:
            _move(conn, eid, "archive", "archived")
    return {"archived": len(ids)}


def _pub(e: dict) -> dict:
    out = {"id": f"E{e['id']}", "kind": e["kind"], "statement": e["statement"], "author": e["author"],
           "refs": json.loads(e["refs"])}
    if e["assignee"]:
        out |= {"assignee": e["assignee"], "depends_on": [f"E{i}" for i in json.loads(e["depends_on"] or "[]")]}
    return out


def _blocked(conn, e: dict):
    """A dependency is met when resolved/archived, or when it is a decision-like entry that exists
    (active, or superseded: a newer version does not re-block work). Assignments and active questions must
    resolve; a superseded question counts as answered (the newer entry replaces it)."""
    deps = json.loads(e["depends_on"] or "[]")
    return conn.execute(
        f"select 1 from entries where id in ({','.join('?' * len(deps))}) and status not in ('resolved','archived')"
        " and not (kind in ('decision','convention','assumption','lesson') and status in ('active','superseded'))"
        " and not (kind='question' and status='superseded')",
        deps).fetchone()


def _scopes(conn, agent_id: str, topic: str | None = None) -> list[str]:
    role = conn.execute("select role from agents where id=?", (agent_id,)).fetchone()[0]
    tids = [r[0] for r in conn.execute("select thread_id from thread_members where member=? order by 1", (agent_id,))]
    if topic and topic not in tids:
        raise ToolError("unknown_thread", f"topic must be one of your threads: {', '.join(tids) or '(none)'}")
    return ["global"] + ([] if topic else [f"role:{role}"] * bool(role) + [f"agent:{agent_id}"]) + \
           [f"thread:{t}" for t in ([topic] if topic else tids)]


def current_seq(conn) -> int:
    return conn.execute("select coalesce(max(seq), 0) from entry_events").fetchone()[0]


def watermark(conn, session_id: int) -> int | None:
    r = conn.execute("select seq from seen where session_id=?", (session_id,)).fetchone()
    return r and r[0]


def reset_watermark(conn, session_id: int) -> None:
    """The next wake of this session gets a full snapshot (vendor compaction, handoff)."""
    with db.tx(conn):
        conn.execute("delete from seen where session_id=?", (session_id,))


def delta(conn, agent_id: str, since: int) -> dict:
    """What changed in this agent's scope after alignment version `since`, as net effects: entries both
    created and invalidated inside the window were never shown, so they are not reported."""
    scopes = _scopes(conn, agent_id)
    rs = db.rows(conn.execute(
        f"select e.*, v.op from entry_events v join entries e on e.id=v.entry_id where v.seq>? and "
        f"(e.scope in ({','.join('?' * len(scopes))}) or e.assignee=?) order by v.seq", (since, *scopes, agent_id)))
    ops, ents = {}, {}
    for r in rs:
        ops.setdefault(r["id"], []).append(r["op"])
        ents[r["id"]] = {**_pub(r), "status": r["status"], "scope": r["scope"]}
    out = {"added": [], "superseded": [], "resolved": [], "archived": {}}
    for eid in sorted(ops):
        e, last = ents[eid], ops[eid][-1]
        if "add" in ops[eid] or "confirm" in ops[eid]:
            if e["status"] == "active":
                out["added"].append(e)
        elif last == "supersede":
            by = conn.execute("select max(id) from entries where supersedes=? and status not in ('proposed','rejected')",
                              (eid,)).fetchone()[0]
            out["superseded"].append((e, f"E{by}"))
        elif last == "resolve":
            out["resolved"].append(e)
        elif last == "archive":
            t = e["scope"][7:] if e["scope"].startswith("thread:") else ""
            out["archived"][t] = out["archived"].get(t, 0) + 1
    out["archived"] = sorted(out["archived"].items())
    return out


def view(conn, cfg: dict, agent_id: str, topic: str | None = None, query: str = "") -> dict:
    """Active entries for one agent: global + its role + its threads + its own, then work assigned to it.
    Layers are capped; `truncated` names the layers that overflowed. Which entries survive is MemoryOS's
    /recall ranking for `query` when available, else the newest by seq."""
    scopes = _scopes(conn, agent_id, topic)
    rs = db.rows(conn.execute(
        f"select * from entries where status='active' and (scope in ({','.join('?' * len(scopes))}) or assignee=?)"
        " order by seq desc", (*scopes, None if topic else agent_id)))
    caps = {"global": cfg["align_global_cap"], "role": cfg["align_role_cap"], "thread": cfg["align_thread_cap"]}
    by, assigned = {s: [] for s in scopes}, []
    for e in rs:
        (assigned if e["assignee"] == agent_id else by[e["scope"]]).append(e)
    mo, layers, truncated = cfg.get("_mo"), {}, []
    role = conn.execute("select role from agents where id=?", (agent_id,)).fetchone()[0]
    for s, es in by.items():
        cap = caps.get(s.split(":")[0]) or 1 << 30
        if len(es) > cap:
            truncated.append(s)
            keep = mo and mo.rank(es, s, role, query, cap, cfg["recall_budget_tokens"])
            mo = mo if keep else None  # one failure skips MemoryOS for the other layers of this view
            es = [e for e in es if f"E{e['id']}" in keep] if keep else es[:cap]
        layers[s] = es
    assigned.sort(key=lambda e: e["id"])
    ready = [f"E{e['id']}" for e in assigned if e["kind"] == "assignment" and not _blocked(conn, e)]
    return {"layers": {s: [_pub(e) for e in sorted(es, key=lambda e: e["id"])] for s, es in layers.items()},
            "assigned": [_pub(e) for e in assigned], "ready": ready, "truncated": truncated}
