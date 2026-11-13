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
