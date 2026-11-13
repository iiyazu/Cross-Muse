"""Feature 2 tests: per-turn file overlap detection (no models involved).

Conventions under test (see xmuse/overlap.py):
- snapshot(workdir) -> (entries, head, too_many); entries maps repo-relative path
  to content hash, 'deleted' for deletions. None when workdir is not a git repo.
- A turn's change = paths whose entry differs between start/end snapshots, plus
  files from `git diff --name-only` when HEAD moved inside the turn (committed).
- touched(turn_id, agent_id, repo, worktree, path, at); overlap_notified(a, b,
  repo, path) dedups per member pair × path within overlap_window_s (an older
  notice re-fires and refreshes its timestamp).
- Notification goes through room.notice (#room): never wakes anyone, so no new
  turns are admitted by it.
"""
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "hub" / "src"))
from xmuse import db, overlap  # noqa: E402

NOW = time.time()


def git(cwd, *args):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    assert r.returncode == 0, (args, r.stderr[-300:])
    return r.stdout.strip()


@pytest.fixture()
def repo(tmp_path):
    d = tmp_path / "repo"
    d.mkdir()
    git(d, "init", "-q")
    git(d, "config", "user.email", "t@e.st")
    git(d, "config", "user.name", "t")
    (d / "a.txt").write_text("a0\n", encoding="utf-8")
    (d / "b.txt").write_text("b0\n", encoding="utf-8")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init")
    wt = tmp_path / "wt"
    git(d, "worktree", "add", "-q", str(wt))
    return d, wt


@pytest.fixture()
def hubdb(tmp_path):
    p = tmp_path / "hub.db"
    conn = db.init(p)
    for aid in ("a1", "a2"):
        conn.execute("insert into agents(id, vendor, model, family, settings, token_digest, created_at)"
                     " values(?, 'claude', 'm', 'claude', '{}', 'x', ?)", (aid, NOW))
    conn.commit()
    yield p
    conn.close()


def record(conn, cfg, agent, turn, wd, pre, t0=None, t1=None):
    t0 = NOW - 10 if t0 is None else t0
    t1 = NOW if t1 is None else t1
    conn.execute("insert into turns(id, agent_id, adapter, state, started_at, ended_at)"
                 " values(?, ?, 'x', 'succeeded', ?, ?)", (turn, agent, t0, t1))
    conn.commit()
    return overlap.record_turn_end(conn, cfg, agent, turn, wd, pre, t0, t1)


def snap(wd):
    entries, head, too_many = overlap.snapshot(wd)
    assert entries is not None and not too_many
    return entries, head


def cfg(**kw):
    c = {"file_overlap_notice": True, "overlap_window_s": 6 * 3600}
    c.update(kw)
    return c


def test_1_two_worktrees_same_file_one_notice(repo, hubdb):
    d, wt = repo
    conn = db.connect(hubdb)
    pre1 = snap(d)
    (d / "a.txt").write_text("a1\n", encoding="utf-8")
    assert record(conn, cfg(), "a1", 1, d, pre1) == []
    pre2 = snap(wt)
    (wt / "a.txt").write_text("a1-wt\n", encoding="utf-8")
    notes = record(conn, cfg(), "a2", 2, wt, pre2)
    assert len(notes) == 1 and "a.txt" in notes[0]
    assert "合并时可能冲突" in notes[0]


def test_2_different_files_no_notice(repo, hubdb):
    d, wt = repo
    conn = db.connect(hubdb)
    pre1 = snap(d)
    (d / "a.txt").write_text("a1\n", encoding="utf-8")
    assert record(conn, cfg(), "a1", 1, d, pre1) == []
    pre2 = snap(wt)
    (wt / "b.txt").write_text("b-wt\n", encoding="utf-8")
    assert record(conn, cfg(), "a2", 2, wt, pre2) == []


def test_3_committed_inside_turn_detected(repo, hubdb):
    d, wt = repo
    conn = db.connect(hubdb)
    entries, head = snap(d)
    (d / "a.txt").write_text("a1\n", encoding="utf-8")
    git(d, "commit", "-qam", "w1")
    notes = overlap.record_turn_end(conn, cfg(), "a1", 1, d, (entries, head), NOW - 10, NOW)
    assert notes == []  # nobody else touched it yet
    rows = conn.execute("select path from touched where turn_id=1").fetchall()
    assert [r[0] for r in rows] == ["a.txt"]


def test_4_non_git_dir_no_error_no_rows(repo, hubdb, tmp_path):
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "x.txt").write_text("x\n", encoding="utf-8")
    conn = db.connect(hubdb)
    assert overlap.snapshot(plain)[0] is None
    assert overlap.record_turn_end(conn, cfg(), "a1", 1, plain, (None, None), NOW - 10, NOW) == []
    assert conn.execute("select count(*) from touched").fetchone()[0] == 0


def test_5_same_pair_path_reported_once(repo, hubdb):
    d, wt = repo
    conn = db.connect(hubdb)
    pre1 = snap(d)
    (d / "a.txt").write_text("a1\n", encoding="utf-8")
    record(conn, cfg(), "a1", 1, d, pre1)
    pre2 = snap(wt)
    (wt / "a.txt").write_text("w1\n", encoding="utf-8")
    assert len(record(conn, cfg(), "a2", 2, wt, pre2)) == 1
    pre3 = snap(wt)
    (wt / "a.txt").write_text("w2\n", encoding="utf-8")
    assert record(conn, cfg(), "a2", 3, wt, pre3) == []
    assert conn.execute("select count(*) from overlap_notified").fetchone()[0] == 1


def test_6_notice_wakes_nobody(repo, hubdb):
    d, wt = repo
    conn = db.connect(hubdb)
    pre1 = snap(d)
    (d / "a.txt").write_text("a1\n", encoding="utf-8")
    record(conn, cfg(), "a1", 1, d, pre1)
    pre2 = snap(wt)
    (wt / "a.txt").write_text("w1\n", encoding="utf-8")
    record(conn, cfg(), "a2", 2, wt, pre2)
    assert conn.execute("select count(*) from deliveries where wake=1").fetchone()[0] == 0
    assert conn.execute("select count(*) from turns").fetchone()[0] == 2
    assert conn.execute("select count(*) from messages where sender='hub' and kind='notice'").fetchone()[0] >= 1


def test_7_concurrent_same_worktree(repo, hubdb):
    d, wt = repo
    conn = db.connect(hubdb)
    pre1 = snap(d)
    (d / "a.txt").write_text("a1\n", encoding="utf-8")
    # overlapping wall-clock intervals, same worktree
    assert record(conn, cfg(), "a1", 1, d, pre1, NOW - 10, NOW) == []
    pre2 = snap(d)
    (d / "a.txt").write_text("a2\n", encoding="utf-8")
    notes = record(conn, cfg(), "a2", 2, d, pre2, NOW - 5, NOW + 5)
    assert len(notes) == 1 and "并发改同一工作区" in notes[0]


def test_8_snapshot_cost_repo_itself():
    repo_root = Path(__file__).resolve().parent.parent
    t0 = time.perf_counter()
    entries, head, too_many = overlap.snapshot(repo_root)
    dt = time.perf_counter() - t0
    print(f"\nsnapshot xmuse repo: {len(entries or {})} files, head={bool(head)}, {dt * 1000:.0f}ms")
    assert not too_many and dt < 1.0


def test_9_expired_dedup_notifies_again(repo, hubdb):
    d, wt = repo
    conn = db.connect(hubdb)
    pre1 = snap(d)
    (d / "a.txt").write_text("a1\n", encoding="utf-8")
    record(conn, cfg(), "a1", 1, d, pre1)
    pre2 = snap(wt)
    (wt / "a.txt").write_text("w1\n", encoding="utf-8")
    assert len(record(conn, cfg(), "a2", 2, wt, pre2)) == 1
    # the pair x path collided again after the window: re-notify, same single row, fresher timestamp
    conn.execute("update overlap_notified set at=?", (NOW - 6 * 3600 - 1,))
    conn.commit()
    at0 = conn.execute("select at from overlap_notified").fetchone()[0]
    pre3 = snap(wt)
    (wt / "a.txt").write_text("w2\n", encoding="utf-8")
    assert len(record(conn, cfg(), "a2", 3, wt, pre3)) == 1
    rows = conn.execute("select count(*), max(at) from overlap_notified").fetchone()
    assert rows[0] == 1 and rows[1] > at0


def test_10_snapshot_500_dirty_files_under_point_two_seconds(tmp_path):
    d = tmp_path / "big"
    d.mkdir()
    git(d, "init", "-q")
    git(d, "config", "user.email", "t@e.st")
    git(d, "config", "user.name", "t")
    (d / "base.txt").write_text("base\n", encoding="utf-8")
    git(d, "add", "-A")
    git(d, "commit", "-qm", "init")
    for i in range(500):
        (d / f"f{i:04d}.txt").write_text("x" * 200 + str(i), encoding="utf-8")
    t0 = time.perf_counter()
    entries, _, too_many = overlap.snapshot(d)
    dt = time.perf_counter() - t0
    print(f"\nsnapshot 500 dirty files: {len(entries or {})} files, {dt * 1000:.0f}ms")
    assert not too_many and len(entries) == 500 and dt < 0.2
