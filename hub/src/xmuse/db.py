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
  token_digest text not null, paused integer not null default 0, created_at real not null);
create table if not exists sessions(
  id integer primary key, agent_id text not null, vendor_session text,
  origin text not null,                      -- hub | tui
  state text not null default 'current',     -- current | retired
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
  state text not null,   -- queued | admitted | done | failed | canceled | held | passive
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
create table if not exists approvals(
  id text primary key, agent_id text not null, vendor_session text, action text,
  resources text, state text not null default 'pending', decision text,
  created_at real not null, decided_at real);
"""


def connect(path) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=30, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("pragma journal_mode=wal")
    conn.execute("pragma busy_timeout=30000")
    return conn


def init(path) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(SCHEMA)
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


class Pool:
    """One connection per thread (HTTP handlers, engine, adapter watchers)."""

    def __init__(self, path):
        self.path, self.local = path, threading.local()

    def __call__(self) -> sqlite3.Connection:
        c = getattr(self.local, "c", None)
        if c is None:
            c = self.local.c = connect(self.path)
        return c
