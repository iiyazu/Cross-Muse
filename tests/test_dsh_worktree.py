"""dsh member worktrees: hook files land in the member directory (no real dsh run: that needs a
Windows desktop session)."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hub" / "src"))
from xmuse.adapters.dsh import DshDriver  # noqa: E402


def git(d, *args):
    r = subprocess.run(["git", *args], cwd=d, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr[-300:])


def test_write_config_mirrors_hooks_into_member_worktree(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    git(ws, "init", "-q")
    git(ws, "config", "user.email", "t@e.st")
    git(ws, "config", "user.name", "t")
    (ws / "a.txt").write_text("a\n", encoding="utf-8")
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "init")
    wt = tmp_path / "wt"
    git(ws, "worktree", "add", "-q", str(wt))
    agent = {"id": "d1", "settings": json.dumps({"cwd": str(wt)})}
    out = DshDriver.write_config(ws, agent, tmp_path / "state")
    assert (ws / ".dsh" / "hooks.json").exists()
    assert (wt / ".dsh" / "hooks.json").exists()
    assert (wt / ".dsh" / "xmuse-dsh-hook.py").exists()
    assert str(wt / ".dsh" / "hooks.json") in [str(p) for p in out]


def test_write_config_without_cwd_writes_workspace_only(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    agent = {"id": "d1", "settings": json.dumps({})}
    out = DshDriver.write_config(ws, agent, tmp_path / "state")
    assert (ws / ".dsh" / "hooks.json").exists()
    assert len(out) == 2


@pytest.mark.parametrize("vendor", ["dsh", "agy"])
def test_hub_start_sync_covers_outside_worktree_members(tmp_path, vendor):
    """The hub-start worktree refresh (server calls sync_member_dirs): a member with an
    outside cwd gets the AGENTS.md section and the skill in its own worktree."""
    import time

    from xmuse import config, db
    from xmuse import init as xinit
    from xmuse.init import sync_member_dirs

    ws = tmp_path / "ws"
    ws.mkdir()
    git(ws, "init", "-q")
    git(ws, "config", "user.email", "t@e.st")
    git(ws, "config", "user.name", "t")
    (ws / "AGENTS.md").write_text("# ws\n", encoding="utf-8")
    git(ws, "add", "-A")
    git(ws, "commit", "-qm", "init")
    wt = tmp_path / "wt"
    git(ws, "worktree", "add", "-q", str(wt))
    state = xinit.init(ws)
    conn = db.connect(state / "hub.db")
    conn.execute("insert into agents(id, vendor, model, family, settings, token_digest, created_at)"
                 " values(?, ?, 'm', ?, ?, 'x', ?)",
                 ("m1", vendor, vendor, json.dumps({"cwd": str(wt)}), time.time()))
    conn.commit()
    conn.close()
    sync_member_dirs(ws, state, config.load(state))
    assert "<!-- xmuse:begin" in (wt / "AGENTS.md").read_text(encoding="utf-8")
    assert (wt / ".agents" / "skills" / "xmuse-collab" / "SKILL.md").exists()
    assert (wt / ".xmuse.json").exists()
