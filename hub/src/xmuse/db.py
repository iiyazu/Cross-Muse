"""hub.db: schema, connection and the transaction helper.

Every fact the hub owns lives here (design §4.1 principle 2): roster, sessions,
threads, messages, per-recipient deliveries, turns, leases, causal chains and
per-turn usage. Session contents stay in each vendor's CLI.
"""
import contextlib
import json
import sqlite3
import threading
import time

SCHEMA = """
create table if not exists agents(
  id text primary key, vendor text not null, model text not null, family text not null,
  role text not null default '', settings text not null default '{}',
  token_digest text not null, paused integer not null default 0,
  paused_until real, created_at real not null);
create table if not exists sessions(
  id integer primary key, agent_id text not null, vendor_session text,
  cwd text,                                  -- dsh resumes only in the exact cwd it was created in
  origin text not null,                      -- hub | tui
  state text not null default 'current',     -- current | retired
  thread_id text,                            -- room binding: the thread whose turns resume this session (null = room-less)
  context_tokens integer not null default 0, total_tokens integer not null default 0,
  wakes integer not null default 0, created_at real not null, retired_at real);
create table if not exists threads(
  id text primary key, kind text not null, title text not null default '', owner text,
  created_at real not null);
create table if not exists thread_members(
  thread_id text not null, member text not null, primary key(thread_id, member));
create table if not exists chains(
  id integer primary key, thread_id text not null, origin text not null,
  state text not null default 'open',        -- open | capped | stopped
  wakes integer not null default 0, tokens integer not null default 0,
  max_wakes integer not null, max_tokens integer not null, note text, created_at real not null);
create table if not exists messages(
  id integer primary key, thread_id text not null, sender text not null, kind text not null,
  body text not null, why text, mentions text not null default '[]',
  chain_id integer not null, depth integer not null default 0, turn_id integer,
  idem_key text, created_at real not null, unique(sender, idem_key));
create table if not exists deliveries(
  id integer primary key, message_id integer not null, recipient text not null,
  wake integer not null,
  state text not null,   -- queued | admitted | done | failed | canceled | held | passive | delivered (relay)
                         -- | blocked (handoff whose assignment waits on depends_on; align.release queues it)
  turn_id integer, read_at real, acked_at real, outcome text, updated_at real not null,
  unique(message_id, recipient));
create index if not exists deliveries_open on deliveries(recipient, state);
create table if not exists turns(
  id integer primary key, agent_id text not null, session_id integer, adapter text not null,
  chain_id integer, fresh integer not null default 0,
  state text not null,   -- running | succeeded | failed | interrupted | canceled
  started_at real not null, ended_at real, error text, summary text, pid integer, handle text);
create table if not exists leases(
  pid integer primary key, agent_id text not null, vendor_session text,
  holder text not null,  -- tui | hub
  entrypoint text, channel_url text, channel_nonce text,
  human_turn integer not null default 0, updated_at real not null);
create table if not exists usage(
  turn_id integer primary key, agent_id text not null, vendor text not null, model text,
  mode text not null,    -- chat | code
  input integer not null, cache_read integer not null, cache_write integer not null,
  output integer not null, context integer not null, calls integer not null,
  created_at real not null);
create table if not exists entries(          -- alignment library (design §4.5.1); never deleted
  id integer primary key,                    -- shown as E<id>
  kind text not null,                        -- decision|convention|assumption|question|lesson|assignment
  scope text not null,                       -- global | role:<role> | thread:<tid> | agent:<id> | module:<name>
  thread_id text, statement text not null, refs text not null default '[]',  -- refs: source message ids
  author text not null,
  status text not null,                      -- proposed|active|superseded|resolved|archived|rejected
  supersedes integer, assignee text, depends_on text,  -- depends_on: JSON list of entry ids (assignments)
  valid_at real not null, recorded_at real not null, invalid_at real,
  seq integer not null);                     -- alignment version of the last change
create table if not exists entry_events(
  seq integer primary key,                   -- global monotonic alignment version
  entry_id integer not null, op text not null,  -- add|supersede|resolve|archive|confirm|reject|audit
  at real not null);                         -- audit: a version for audit_flags only; the entry itself is unchanged
create table if not exists audits(           -- one row per superseded entry the auditor handled (audit.py)
  entry_id integer primary key, by_id integer, -- by_id: the entry that replaced it
  state text not null,                       -- done|failed|skipped (skipped: before the hub started, or no replacement)
  at real not null, result text,             -- result: JSON {flagged, candidates} from MemoryOS /audit
  tries integer not null default 1);         -- a failed audit is retried once (audit_retry_s)
create table if not exists audit_flags(      -- a message that relied on a superseded entry; shown to its author once
  id integer primary key, entry_id integer not null, by_id integer, message_id integer not null,
  agent_id text not null, quote text not null, seq integer not null);  -- seq: the entry_events 'audit' version
create table if not exists seen(             -- watermark: alignment version this session has been shown
  session_id integer primary key, seq integer not null);
create table if not exists curated(          -- last message of each thread already sent to MemoryOS /curate
  thread_id text primary key, msg_id integer not null);
create table if not exists preset_runs(       -- orchestration presets (T13): one row per run
  id integer primary key, preset text not null, task text not null, planner text not null,
  executors text not null,                   -- JSON list of agent ids
  base text not null, branch text not null,  -- base commit and the main workspace's branch
  phase text not null, phase_at real not null, round integer not null default 0,
  state text not null default 'running',     -- running | finished | failed
  limits text not null, data text not null default '{}', created_at real not null, ended_at real);
create table if not exists preset_events(
  id integer primary key, run_id integer not null, at real not null, phase text, kind text not null,
  detail text not null default '{}');
create table if not exists approvals(
  id text primary key, agent_id text not null, vendor_session text, action text,
  resources text, state text not null default 'pending', decision text,
  created_at real not null, decided_at real);
create table if not exists room(             -- the room this workspace is (D2, contract XMUSE2-VIEW-API v0): one row
  id text primary key, name text not null, dir text not null, host text, created_at real not null);
create table if not exists operators(        -- sidebar operator tokens: the user acting from a member's sidebar
  token_digest text primary key, member_id text not null, created_at real not null);
create table if not exists invites(          -- one-time invitation codes (/v1/act invite -> /v1/join)
  code text primary key, vendor text not null, role text not null default '', description text not null default '',
  name text, created_by text, created_at real not null, expires_at real not null, used_at real, used_by text);
create table if not exists meta(key text primary key, value text not null);  -- view_version
create table if not exists share_marks(      -- user DMs released for sharing (T3, share.py); target '' = to anyone
  message_id integer not null, target text not null default '', created_at real not null,
  primary key(message_id, target));
create table if not exists share_hints(      -- T3: a user DM that may relate to a teammate's question, shown once to its holder
  dm_id integer not null, question_id integer not null, holder text not null, asker text not null,
  shown integer not null default 0, primary key(dm_id, question_id));
create table if not exists human_reads(      -- T8a H6: the user's read cursor per thread (operator act `read` moves it)
  thread_id text primary key, last_read_id integer not null);
create table if not exists evidence(         -- xmuse_done evidence and the hub's check of it (evidence.py)
  message_id integer primary key, items text not null,  -- items: JSON [{kind, ref, result}]
  status text not null,                      -- verified | unverified (no row: none)
  problems text not null default '[]', checked_at real not null);
create table if not exists dispatches(        -- host handoffs, one per assignee, until a result returns them (dispatch.py)
  id integer primary key, message_id integer not null, entry_id integer, host text not null, member text not null,
  notify text not null default 'batch',      -- batch | now (wake the host as soon as this one is back)
  created_at real not null, returned_at real, result_id integer, unique(message_id, member));
create table if not exists dispatch_holds(    -- results held back from the host (no delivery) until its batch is released
  message_id integer not null, host text not null, created_at real not null, released_at real, why text,
  primary key(message_id, host));
"""


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma busy_timeout=30000")
    return conn


COLUMNS = [("turns", "view_entries", "integer"),  # entries in the agent's view at wake (experiment curve)
           ("turns", "align_tokens", "integer"),("turns", "align_mode", "text"),  # added after M1: per-turn metrics
           ("sessions", "notified", "integer not null default 0"),               # size notice sent
           ("sessions", "online", "integer not null default 0"),                 # desktop session between SessionStart/End
           ("messages", "via", "text"), ("entries", "via", "text"),  # coordinator that relayed a human decision
           ("entries", "resolves", "text"),  # proposed entries: JSON ids of questions they answer, applied on confirm
           # dsh relay: a polled agent's delivery reported into its desktop session
           ("deliveries", "delivered_at", "real"), ("deliveries", "delivered_session", "text"),
           # the dsh session a foreground agent is bound to (/v1/relay/bind); its tool calls must come from it
           ("agents", "bound_session", "text"),
           # assignments: JSON list of modules the assignee owns (handoff scope module:a,b); module entries reach them
           ("entries", "modules", "text"),
           ("messages", "stage", "text"),  # xmuse_done(stage=...): the plan-split-integrate phase it ends (T13)
           # D2: what a member is responsible for (shown to peers and in the sidebars); removed from the room
           ("agents", "description", "text not null default ''"), ("agents", "removed", "integer not null default 0"),
           ("threads", "private", "integer not null default 0"),  # T2: a private group is for its members only
           ("messages", "shared_from", "text"),  # T3: JSON {member, message_id} of a shared user DM (via "shared")
           # T0 outcome labels on done messages: the label in effect, member | hub (upgraded), why the hub upgraded it
           ("messages", "outcome", "text"), ("messages", "outcome_by", "text"), ("messages", "outcome_reason", "text"),
           # T4 §8.7: duty-routed question (column is route_to: dispatch's routed_to return field keeps its name)
           ("messages", "route_to", "text"), ("messages", "route_reason", "text"),
           # T8a H9: the message this one replies to (a reply wakes whoever it answers)
           ("messages", "reply_to", "integer"),
           # T8c H3: compaction state per session (auto-compact mark, in-flight flag)
           ("sessions", "auto_compacted", "integer not null default 0"),
           ("sessions", "compacting", "integer not null default 0"),
           # room binding: the thread whose turns resume this session (null = pre-binding / room-less)
           ("sessions", "thread_id", "text"),
           # when the last hub-run compaction of the session succeeded: the size the view shows is stale until a turn
           ("sessions", "compacted_at", "real"),
           # the user took a message back (panel "撤回"): its body is replaced, this is when
           ("messages", "retracted_at", "real"),
           # E13: a failed audit is retried once
           ("audits", "tries", "integer not null default 1")]


def init(path) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
    for table, col, decl in COLUMNS:
        if col not in {r[1] for r in conn.execute(f"pragma table_info({table})")}:
            conn.execute(f"alter table {table} add column {col} {decl}")
    # room binding: at most one current session per (agent, thread). Room-less (null) rows stay
    # exempt (nulls are distinct): pre-binding hubs keep working untouched.
    if {"agent_id", "thread_id", "state"} <= {r[1] for r in conn.execute("pragma table_info(sessions)")}:
        conn.execute("create unique index if not exists sessions_current_room on sessions(agent_id, thread_id)"
                     " where state='current'")
    return conn


@contextlib.contextmanager
def tx(conn: sqlite3.Connection):
    """One write transaction; BEGIN IMMEDIATE so concurrent writers queue instead of failing."""
    conn.execute("begin immediate")
    try:
        yield conn
    except BaseException:
        conn.execute("rollback")
        raise
    conn.execute("commit")


def now() -> float:
    return time.time()


def row(r) -> dict | None:
    if isinstance(r, sqlite3.Cursor):
        r = r.fetchone()
    return None if r is None else dict(r)


def rows(rs) -> list[dict]:
    return [dict(r) for r in rs]


def settings(agent: dict) -> dict:
    return json.loads(agent["settings"] or "{}")


def workdir(agent: dict, ws) -> "Path":
    """Where the agent works and where a Claude member's project configs (.mcp.json, .claude/) live: its own
    settings.cwd (a member directory, or a git worktree), else the workspace root."""
    from pathlib import Path
    return Path(settings(agent).get("cwd") or ws)


def polled(agent: dict) -> bool:
    """Lives in a desktop session the hub never runs (Claude coordinator or dsh foreground): only polled."""
    s = settings(agent)
    return bool(s.get("desktop") or s.get("foreground"))


class Pool:
    """One connection per thread (HTTP handlers, engine, adapter watchers). The HTTP API's worker threads come and go
    (and outlive a stopped server): a new connection closes those of threads that have ended, and close() closes all."""

    def __init__(self, path):
        self.path, self.local = path, threading.local()
        self.lock, self.open = threading.Lock(), []  # [(thread, connection)]

    def __call__(self) -> sqlite3.Connection:
        c = getattr(self.local, "c", None)
        if c is None:
            c = self.local.c = connect(self.path)
            with self.lock:
                for t, old in self.open:
                    if not t.is_alive():
                        old.close()
                self.open = [(t, o) for t, o in self.open if t.is_alive()] + [(threading.current_thread(), c)]
        return c

    def close(self) -> None:
        with self.lock:
            for _, c in self.open:
                c.close()
            self.open = []
        self.local = threading.local()
