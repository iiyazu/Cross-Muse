"""`xmuse agent release` and `xmuse agent remove`: the CLI reaches the hub's admin routes (a real hub process)."""
import json
import os

import pytest

from xmuse import config, db
from test_init_cli import run, ws  # noqa: F401  (ws: fixture)


def member(state, mid):
    conn = db.connect(state / "hub.db")
    try:
        return db.row(conn.execute("select * from agents where id=?", (mid,)))
    finally:
        conn.close()


def test_release_frees_the_binding_and_remove_takes_the_member_out(ws):  # noqa: F811
    run(ws, "init", ".")
    run(ws, "agent", "add", "claude-1", "--vendor", "claude", "--desktop")
    (ws / "b").mkdir()  # claude members each need their own directory (.mcp.json carries one identity)
    run(ws, "agent", "add", "claude-2", "--vendor", "claude", "--desktop", "--cwd", str(ws / "b"))
    state = config.find_state(ws)
    try:
        assert "hub started" in run(ws, "hub", "start").stdout
        conn = db.connect(state / "hub.db")
        conn.execute("update agents set bound_session='desktop-old' where id='claude-1'")
        conn.close()
        out = json.loads(run(ws, "agent", "release", "claude-1").stdout)
        assert out["ok"] is True and member(state, "claude-1")["bound_session"] is None
        out = json.loads(run(ws, "agent", "remove", "claude-2").stdout)
        assert out["ok"] is True
        gone = member(state, "claude-2")
        assert gone["removed"] == 1 and gone["paused"] == 1 and gone["bound_session"] is None
        conn = db.connect(state / "hub.db")
        assert conn.execute("select count(*) from messages where body like '%claude-2 was removed%'").fetchone()[0] == 1
        conn.close()
    finally:
        run(ws, "hub", "stop", check=False)


def test_release_and_remove_name_an_unknown_member(ws):  # noqa: F811
    run(ws, "init", ".")
    state = config.find_state(ws)
    try:
        assert "hub started" in run(ws, "hub", "start").stdout
        r = run(ws, "agent", "release", "nobody", check=False)
        assert r.returncode != 0 and "no member" in (r.stdout + r.stderr)
    finally:
        run(ws, "hub", "stop", check=False)
