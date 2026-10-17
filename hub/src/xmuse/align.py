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
MIN_STATEMENT = 12  # shortest first-sentence prefix worth keeping when a long statement is cut


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
        resolves: list | None = None, via: str | None = None) -> int:
    """A proposed entry only records `supersedes` / `resolves`; `review(confirm)` applies them."""
    if len(statement) > LIMIT:  # keep the first sentence; the full text stays in the referenced message
        # sentences until there is real content: a leading "1." or "Task." must not be the whole statement
        first = ""
        for sent in re.split(r"(?<=[.!?。！？])\s+", statement.strip()):
            first = (first + " " + sent).strip()
            if len(first) >= MIN_STATEMENT:
                break
        statement = first[:LIMIT - 1] + "…" if len(first) > LIMIT else first + " …"
    eid = conn.execute(
        "insert into entries(kind, scope, thread_id, statement, refs, author, status, supersedes, assignee, depends_on,"
        " resolves, valid_at, recorded_at, seq, via) values(?,?,?,?,?,?,?,?,?,?,?,?,?,0,?)",
        (kind, scope, tid, statement, json.dumps(msg if isinstance(msg, list) else [msg]), author, status, supersedes,
         assignee, json.dumps(depends_on) if depends_on else None, json.dumps(resolves) if resolves else None,
         db.now(), db.now(), via)).lastrowid
    _move(conn, eid, "add", status)
    if supersedes and status == "active":
        _move(conn, supersedes, "supersede", "superseded")
    return eid


_MODULE = re.compile(r"[A-Za-z0-9_.\-/]+")
_OWN_MODULE = "(e.author=? and e.scope like 'module:%')"  # module entries also reach their author


def modules_of(scope: str | None) -> list[str]:
    """`module:a` or `module:a,b` (also `module:a,module:b`) -> ['a', 'b']; anything else -> []."""
    if not scope or not scope.startswith("module:"):
        return []
    names = [n.strip().removeprefix("module:") for n in scope[7:].split(",")]
    bad = [n for n in names if not _MODULE.fullmatch(n)]
    if bad or not names:
        raise ToolError("invalid_arguments", f"module names: letters, digits and _.-/; got {scope!r}")
    return list(dict.fromkeys(names))


def declare(conn, author: str, tid: str, msg: int, kind: str, statement: str, scope: str | None = None,
            supersedes: str | None = None, via: str | None = None) -> int:
    old = _ref(conn, supersedes) if supersedes else None
    if scope is None and old:  # an answer or correction reaches whoever saw what it replaces (T14)
        scope = conn.execute("select scope from entries where id=?", (old,)).fetchone()[0]
        return add(conn, kind, scope, tid, statement, msg, author, old, via=via)
    scope = {"all": "global"}.get(scope or "thread", scope or "thread")
    if scope.startswith("module:"):
        mods = modules_of(scope)
        if len(mods) != 1:
            raise ToolError("invalid_arguments", f"a {kind} has one module scope; got {scope!r}")
        scope = f"module:{mods[0]}"
    elif scope not in ("global", "thread") and not scope.startswith("role:"):
        raise ToolError("invalid_arguments",
                        f"scope must be global, all, thread, role:<role> or module:<name>; got {scope!r}")
    return add(conn, kind, f"thread:{tid}" if scope == "thread" else scope, tid, statement, msg, author, old, via=via)


def assign(conn, author: str, tid: str, msg: int, statement: str, assignees: list, depends_on: list,
           via: str | None = None, modules: list | None = None) -> list[int]:
    """One assignment per assignee. `modules` (handoff scope module:a,b) are what the assignee owns: from now on it
    sees entries scoped to them, and so does the author (the planner)."""
    deps = [_ref(conn, d, None) for d in depends_on]
    eids = [add(conn, "assignment", f"thread:{tid}", tid, statement, msg, author, assignee=a, depends_on=deps, via=via)
            for a in assignees]
    if modules:
        conn.executemany("update entries set modules=? where id=?", [(json.dumps(modules), e) for e in eids])
    return eids


def subscribed(conn, agent_id: str) -> list[str]:
    """Modules an agent works on or planned: from its live assignments, as assignee or as author."""
    out = set()
    for (mods,) in conn.execute("select modules from entries where kind='assignment' and modules is not null and "
                                "status not in ('rejected','archived') and (assignee=? or author=?)",
                                (agent_id, agent_id)):
        out |= set(json.loads(mods))
    return sorted(out)


def release(conn) -> list[str]:
    """Handoff deliveries parked as 'blocked' whose assignment no longer waits on anything become wakeable (T14).
    Returns the recipients released. Runs inside the caller's transaction after every entry change."""
    out = []
    for d in db.rows(conn.execute("select d.id, d.recipient, d.message_id, c.state chain from deliveries d"
                                  " join messages m on m.id=d.message_id join chains c on c.id=m.chain_id"
                                  " where d.state='blocked'")):
        es = db.rows(conn.execute("select * from entries where kind='assignment' and assignee=? and refs=?",
                                  (d["recipient"], json.dumps([d["message_id"]]))))
        if any(_blocked(conn, e) for e in es):
            continue
        conn.execute("update deliveries set state=?, updated_at=? where id=?",
                     ("queued" if d["chain"] == "open" else "held", db.now(), d["id"]))
        out.append(d["recipient"])
    return out


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
        released = release(conn)
    return {"ok": True, **({"released": released} if released else {})}


def close_thread(conn, tid: str) -> dict:
    """Task closed: its specific entries decay out of every view (promotion to global is explicit)."""
    with db.tx(conn):
        ids = [r[0] for r in conn.execute("select id from entries where scope=? and status in ('active','proposed')",
                                          (f"thread:{tid}",))]
        for eid in ids:
            _move(conn, eid, "archive", "archived")
        released = release(conn)
    return {"archived": len(ids), **({"released": released} if released else {})}


def _pub(e: dict) -> dict:
    out = {"id": f"E{e['id']}", "kind": e["kind"], "statement": e["statement"], "author": e["author"],
           "refs": json.loads(e["refs"])}
    if e.get("via"):
        out["via"] = e["via"]
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
    return ["global"] + ([] if topic else [f"role:{role}"] * bool(role) + [f"agent:{agent_id}"]
                         + [f"module:{m}" for m in subscribed(conn, agent_id)]) + \
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
        f"select e.*, v.op from entry_events v join entries e on e.id=v.entry_id where v.seq>? and v.op != 'audit' and "
        f"(e.scope in ({','.join('?' * len(scopes))}) or e.assignee=? or {_OWN_MODULE}) order by v.seq",
        (since, *scopes, agent_id, agent_id)))
    ops, ents = {}, {}
    for r in rs:
        ops.setdefault(r["id"], []).append(r["op"])
        ents[r["id"]] = {**_pub(r), "status": r["status"], "scope": r["scope"]}
    # own: per replaced entry, the agent's own live entries in its scope, which may restate it (T8 probe 10-13)
    out = {"added": [], "superseded": [], "resolved": [], "archived": {}, "own": []}
    for eid in sorted(ops):
        e, last = ents[eid], ops[eid][-1]
        if "add" in ops[eid] or "confirm" in ops[eid]:
            if e["status"] == "active":
                out["added"].append(e)
        elif last == "supersede":  # the replacement's text too: it may be scoped where this agent does not look
            by = conn.execute("select id, statement from entries where supersedes=? and status not in"
                              " ('proposed','rejected') order by id desc limit 1", (eid,)).fetchone()
            label = "E?" if by is None else f"E{by[0]}" if by[0] in ents else f'E{by[0]}: "{by[1]}"'
            out["superseded"].append((e, label))
            # the agent is asked to check these itself: it knows what it meant, the hub does not guess similarity
            own = conn.execute(
                "select id, statement from entries where author=? and status='active' and scope=? and kind in"
                " ('decision','assumption','convention') and id not in (?, ?) order by id",
                (agent_id, e["scope"], by[0] if by else -1, eid)).fetchall()
            if own:
                out["own"].append((e["id"], [(f"E{o[0]}", o[1]) for o in own]))
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
    me = None if topic else agent_id
    rs = db.rows(conn.execute(
        f"select * from entries e where status='active' and (scope in ({','.join('?' * len(scopes))}) or assignee=?"
        f" or {_OWN_MODULE}) order by seq desc", (*scopes, me, me)))
    caps = {"global": cfg["align_global_cap"], "role": cfg["align_role_cap"], "thread": cfg["align_thread_cap"],
            "module": cfg["align_thread_cap"]}
    by, assigned = {s: [] for s in scopes}, []
    for e in rs:
        (assigned if e["assignee"] == agent_id else by.setdefault(e["scope"], [])).append(e)
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
