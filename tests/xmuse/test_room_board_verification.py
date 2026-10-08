"""Behaviour tests for host-verified board completion."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.board_scenarios import (
    DIGEST_A,
    DIGEST_B,
    NOW,
    T0,
    _activity_payload,
    _approved_board,
    _claim,
    _lease_kwargs,
    _observations_for,
    _report_done,
    _round,
    _round_time,
    _split_payload,
    _verification_row,
)
from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat import room_board_verification as verification
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_board import (
    RoomBoardStore,
    board_activity_content,
    charter_outside_paths,
    charter_path_allowed,
    split_dependency_cycle,
)
from xmuse_core.chat.room_board_view import materialize_owner_board_view
from xmuse_core.chat.room_collaboration import write_room_collaboration_policy_conn
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_sandbox import GateResult, sanitize_gate_output_tail
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_observation_transport_base import build_room_observation_prompt
from xmuse_core.chat.room_owner_clones import OwnerCloneError, OwnerCloneManager
from xmuse_core.chat.room_owner_ids import owner_id_for_participant

_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_PAGER": "cat",
}


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


# ---------------------------------------------------------------------------
# path-ownership helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("path", "patterns", "expected"),
    [
        ("src/alpha/a.py", ["src/alpha/**"], True),
        ("src/alpha/nested/deep.py", ["src/alpha/**"], True),
        ("src/alpha", ["src/alpha/**"], True),
        ("src/beta/b.py", ["src/alpha/**"], False),
        ("src/other.py", ["src/alpha/**", "docs/**"], False),
        ("docs/guide.md", ["docs/*.md"], True),
        ("docs/nested/guide.md", ["docs/**"], True),
        ("src/alpha/a.py", ["src/alpha/*.py"], True),
        # The host-owned board view is never allowed.
        (".xmuse/charter.md", ["**"], False),
        (".xmuse", ["**"], False),
        (".xmuse", [".xmuse"], False),
        # Unsafe paths are never allowed.
        ("../escape.py", ["**"], False),
        ("/abs/path.py", ["**"], False),
        ("", ["**"], False),
    ],
)
def test_charter_path_allowed_matches(path: str, patterns: list[str], expected: bool) -> None:
    assert charter_path_allowed(path, patterns) is expected


def test_charter_outside_paths_lists_offenders() -> None:
    assert charter_outside_paths(["docs/a.md", "src/x.py"], ["docs/**"]) == ["src/x.py"]
    assert charter_outside_paths(["docs/a.md"], ["docs/**"]) == []


# ---------------------------------------------------------------------------
# enqueue on done
# ---------------------------------------------------------------------------


def test_done_report_enqueues_pending_verification(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)

    reported = _report_done(ctx, 1, "done-1")

    assert reported["verification_id"]
    row = _verification_row(ctx["db"], reported["verification_id"])
    assert row["status"] == "pending"
    assert row["module_id"] == "alpha"
    assert row["progress_id"] == reported["progress_id"]
    assert row["attempt_count"] == 0


@pytest.mark.parametrize("status", ["working", "blocked", "ready_for_review"])
def test_other_statuses_enqueue_nothing(tmp_path: Path, status: str) -> None:
    ctx = _approved_board(tmp_path)
    owner = ctx["members"][1]

    reported = ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="nd-1"),
        module_id="alpha",
        status=status,
        summary="not done",
        claims=[],
    )

    assert reported["verification_id"] is None
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_board_verifications").fetchone()[0] == 0


def test_done_replay_does_not_enqueue_twice(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    owner = ctx["members"][1]
    kwargs = _lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-idem")

    first = ctx["store"].report_progress(
        **kwargs, module_id="alpha", status="done", summary="finished", claims=[]
    )
    second = ctx["store"].report_progress(
        **kwargs, module_id="alpha", status="done", summary="finished", claims=[]
    )

    assert first == second
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        assert conn.execute("select count(*) from room_board_verifications").fetchone()[0] == 1


def test_newer_done_supersedes_pending_job(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)

    first = _report_done(ctx, 1, "done-1")
    second = _report_done(ctx, 1, "done-2")

    assert first["verification_id"] != second["verification_id"]
    assert _verification_row(ctx["db"], first["verification_id"])["status"] == "superseded"
    assert _verification_row(ctx["db"], second["verification_id"])["status"] == "pending"


# ---------------------------------------------------------------------------
# claim lease
# ---------------------------------------------------------------------------


def test_claim_lease_and_expiry_recovery(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    reported = _report_done(ctx, 1, "done-1")
    store = ctx["store"]

    claimed = store.claim_next_board_verification(
        worker_id="w1", lease_ttl_s=60, now=T0 + timedelta(seconds=20)
    )
    assert claimed is not None
    assert claimed["verification_id"] == reported["verification_id"]
    assert claimed["status"] == "running"
    assert claimed["attempt_count"] == 1

    # Nothing pending while the lease is held.
    assert (
        store.claim_next_board_verification(
            worker_id="w1", lease_ttl_s=60, now=T0 + timedelta(seconds=30)
        )
        is None
    )

    # After expiry the same job returns to pending and is re-claimed.
    reclaimed = store.claim_next_board_verification(
        worker_id="w1", lease_ttl_s=60, now=T0 + timedelta(seconds=200)
    )
    assert reclaimed is not None
    assert reclaimed["verification_id"] == reported["verification_id"]
    assert reclaimed["attempt_count"] == 2
    assert reclaimed["lease_token"] != claimed["lease_token"]


def test_attempt_cap_moves_job_to_error(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    reported = _report_done(ctx, 1, "done-1")
    store = ctx["store"]

    claimed = store.claim_next_board_verification(
        worker_id="w1", lease_ttl_s=60, max_attempts=1, now=T0 + timedelta(seconds=20)
    )
    assert claimed is not None
    store.abandon_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        reason_code="transient",
        now=T0 + timedelta(seconds=30),
    )
    assert (
        store.claim_next_board_verification(
            worker_id="w1", lease_ttl_s=60, max_attempts=1, now=T0 + timedelta(seconds=40)
        )
        is None
    )
    row = _verification_row(ctx["db"], reported["verification_id"])
    assert row["status"] == "error"
    # The exhausted claim is visible on the board, addressed to report_to/lead,
    # and wakes nobody: the host failed to verify, not the owner.
    assert row["activity_id"]
    payload = _activity_payload(ctx["db"], str(row["activity_id"]))["payload"]
    assert payload["status"] == "error"
    assert payload["reason_code"] == "board_verification_attempts_exhausted"
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        woken = conn.execute(
            "select count(*) from room_observations where activity_id = ?",
            (str(row["activity_id"]),),
        ).fetchone()[0]
    assert woken == 0


def test_gate_output_tail_is_sanitized_and_bounded() -> None:
    raw = (
        b"line one\n"
        b"\x1b[31mred\x1b[0m text\r\n"
        b"\x1b]0;title\x07osc gone\n"
        b"bell\x07 nul\x00 bidi\xe2\x80\xae end\n"
    )

    assert sanitize_gate_output_tail(raw, 4096) == (
        "line one\nred text\nosc gone\nbell nul bidi end"
    )
    clipped = sanitize_gate_output_tail(b"aaaa\nbbbb\ncccc\n", 8)
    assert clipped == "cccc"
    assert sanitize_gate_output_tail(raw, 0) == ""


def test_gate_output_tail_never_carries_absolute_paths() -> None:
    raw = (
        b'File "/workspace/src/api/greeting.py", line 3, in greet\n'
        b'File "/opt/python/lib/python3.11/typing.py", line 9\n'
        b"/deps/site-packages/pydantic/main.py:12: error\n"
        b"cwd /workspace\n"
        b"stage /srv/xmuse/stages/abc/src/x.py and /srv/xmuse/stages/abc\n"
        b"leak /home/alice/.cache/uv/x.py and /mnt/d/Dev/repo/y.py\n"
        b"win C:\\Users\\alice\\repo\\z.py tmp /tmp/pytest-of-alice/t0/a.py\n"
        b"sys /usr/lib/python3.11/site.py:5 and (/etc/passwd) home ~/.cache/uv/z.py\n"
        b"keep src/api/routes.py:7 and ratio 3/4 and https://example.test/a\n"
    )

    text = sanitize_gate_output_tail(raw, 4096, ("/srv/xmuse/stages/abc",))

    assert text.splitlines() == [
        'File "src/api/greeting.py", line 3, in greet',
        'File "<python>/lib/python3.11/typing.py", line 9',
        "<site-packages>/pydantic/main.py:12: error",
        "cwd .",
        "stage src/x.py and .",
        "leak <host-path> and <host-path>",
        "win <host-path> tmp <host-path>",
        "sys <host-path>:5 and (<host-path>) home <host-path>",
        "keep src/api/routes.py:7 and ratio 3/4 and https://example.test/a",
    ]
    assert "alice" not in text


def test_failed_verification_fence_survives_backticks_in_tail() -> None:
    tail = "E   assert '```' == '````'\nend"
    content = board_activity_content(
        "board.verification",
        {
            "module_id": "api",
            "status": "failed",
            "reason_code": "board_verification_gate_failed",
            "gates": [{"gate_id": "python_uv_pytest", "status": "failed"}],
            "evidence": {"output_tails": {"python_uv_pytest": tail}},
        },
    )

    opening = content.index("`````\n")
    assert content.endswith("\n`````")
    assert content[opening + 6 :].removesuffix("\n`````") == tail


def test_complete_rejects_wrong_lease_and_unknown_job(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    reported = _report_done(ctx, 1, "done-1")
    store = ctx["store"]
    claimed = store.claim_next_board_verification(worker_id="w1", now=NOW)
    assert claimed is not None
    with pytest.raises(ValueError, match="room_board_verification_lease_lost"):
        store.complete_board_verification(
            verification_id=reported["verification_id"],
            lease_token="wrong-token",
            status="passed",
            reason_code=None,
            head_commit="a" * 40,
            patch_digest=DIGEST_A,
            changed_paths=[],
            gates=[],
            evidence={},
            now=NOW,
        )
    with pytest.raises(ValueError, match="room_board_verification_unknown"):
        store.complete_board_verification(
            verification_id="boardverify_missing",
            lease_token="token",
            status="passed",
            reason_code=None,
            head_commit=None,
            patch_digest=None,
            changed_paths=[],
            gates=[],
            evidence={},
        )


def test_stale_result_is_dropped_without_activity(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    store = ctx["store"]
    first = _report_done(ctx, 1, "done-1", now=_round_time(0))
    claimed = store.claim_next_board_verification(worker_id="w1", now=_round_time(0))
    assert claimed is not None
    second = _report_done(ctx, 1, "done-2", now=_round_time(1))
    assert second["verification_id"] != first["verification_id"]

    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        before = conn.execute(
            "select count(*) from room_activities where activity_type = 'board.verification'"
        ).fetchone()[0]
    result = store.complete_board_verification(
        verification_id=first["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit="a" * 40,
        patch_digest=DIGEST_A,
        changed_paths=[],
        gates=[],
        evidence={},
        now=_round_time(0) + timedelta(seconds=30),
    )
    assert result["status"] == "dropped"
    assert result["woken_participant_ids"] == []
    assert _verification_row(ctx["db"], first["verification_id"])["status"] == "superseded"
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        after = conn.execute(
            "select count(*) from room_activities where activity_type = 'board.verification'"
        ).fetchone()[0]
    assert after == before


# ---------------------------------------------------------------------------
# completion: activity, wake-up, escalation
# ---------------------------------------------------------------------------


def test_failed_completion_wakes_owner_with_evidence(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    owner, lead = ctx["members"][1], ctx["members"][0]

    _reported, result = _round(ctx, "done-1", status="failed", reason="owner_patch_empty")

    assert result["status"] == "failed"
    assert result["woken_participant_ids"] == [owner.participant_id]
    assert result["escalated"] is False
    activity_id = result["activity_id"]
    assert _observations_for(ctx["db"], owner.participant_id, activity_id)
    assert not _observations_for(ctx["db"], lead.participant_id, activity_id)
    seen = _activity_payload(ctx["db"], activity_id)
    assert seen["row"]["actor_kind"] == "infrastructure"
    assert seen["row"]["actor_identity"] == "infrastructure:board-verification"
    assert seen["row"]["actor_participant_id"] is None
    payload = seen["payload"]
    assert payload["status"] == "failed"
    assert payload["reason_code"] == "owner_patch_empty"
    assert payload["schema_version"] == "room_board_activity/v1"
    assert "commit" in payload["content"]


def test_passed_completion_reports_to_lead_without_wake(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    owner, lead = ctx["members"][1], ctx["members"][0]

    _reported, result = _round(ctx, "done-1", status="passed")

    assert result["status"] == "passed"
    assert result["woken_participant_ids"] == []
    activity_id = result["activity_id"]
    assert not _observations_for(ctx["db"], owner.participant_id, activity_id)
    assert not _observations_for(ctx["db"], lead.participant_id, activity_id)
    seen = _activity_payload(ctx["db"], activity_id)
    assert seen["row"]["actor_kind"] == "infrastructure"
    audience = json.loads(str(seen["row"]["audience_json"]))
    assert audience["participant_ids"] == [lead.participant_id]


def test_third_consecutive_failure_escalates_to_lead(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    owner, lead = ctx["members"][1], ctx["members"][0]

    _round(ctx, "done-1", status="failed", reason="owner_patch_empty", now=_round_time(0))
    _round(ctx, "done-2", status="failed", reason="owner_patch_empty", now=_round_time(1))
    _reported, result = _round(
        ctx, "done-3", status="failed", reason="owner_patch_empty", now=_round_time(2)
    )

    assert result["escalated"] is True
    assert sorted(result["woken_participant_ids"]) == sorted(
        [owner.participant_id, lead.participant_id]
    )
    activity_id = result["activity_id"]
    assert _observations_for(ctx["db"], lead.participant_id, activity_id)


def test_failure_streak_resets_after_pass(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)

    _round(ctx, "done-1", status="failed", reason="owner_patch_empty", now=_round_time(0))
    _round(ctx, "done-2", status="failed", reason="owner_patch_empty", now=_round_time(1))
    _round(ctx, "done-3", status="passed", now=_round_time(2))
    _reported, result = _round(
        ctx, "done-4", status="failed", reason="owner_patch_empty", now=_round_time(3)
    )

    assert result["escalated"] is False
    assert result["woken_participant_ids"] == [ctx["members"][1].participant_id]


# ---------------------------------------------------------------------------
# projection counters and owner view
# ---------------------------------------------------------------------------


def test_board_projection_counters_and_browser_safety(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)

    _round(ctx, "done-1", status="failed", reason="owner_patch_empty", now=_round_time(0))
    _round(ctx, "done-2", status="failed", reason="owner_patch_empty", now=_round_time(1))
    _round(ctx, "done-3", status="passed", now=_round_time(2))

    payload = ctx["store"].board_projection(conversation_id=ctx["conversation_id"])
    entry = next(item for item in payload["modules"] if item["module_id"] == "alpha")
    assert entry["counters"] == {
        "done_reports": 3,
        "passed": 1,
        "failed": 2,
        "superseded": 0,
        "errored": 0,
        "rework_rounds": 2,
        "reviews_endorsed": 0,
        "reviews_objected": 0,
        "integrations_conflicted": 0,
        "integrations_gate_failed": 0,
        "conflict_fix_rounds": 0,
    }
    assert entry["lifecycle"] == "done_claimed"
    assert entry["state"] == "verified"
    assert entry["verification"]["status"] == "passed"
    assert "payload" not in entry


def test_owner_view_shows_latest_verification_result(tmp_path: Path) -> None:
    ctx = _approved_board(tmp_path)
    owner = ctx["members"][1]

    _round(ctx, "done-1", status="failed", reason="owner_patch_empty")

    view = ctx["store"].owner_view(
        conversation_id=ctx["conversation_id"], participant_id=owner.participant_id
    )
    mine = next(item for item in view["my_modules"] if item["module_id"] == "alpha")
    assert mine["verification"]["status"] == "failed"
    assert mine["verification"]["reason_code"] == "owner_patch_empty"
    assert mine["verification"]["done_reports"] == 1
    assert mine["verification"]["verifications_failed"] == 1
    assert mine["lifecycle"] == "done_claimed"
    assert mine["state"] == "verification_failed"

    target = tmp_path / "board-view"
    target.mkdir()
    materialize_owner_board_view(ctx["db"], ctx["conversation_id"], owner.participant_id, target)
    charter_md = (target / "charter.md").read_text(encoding="utf-8")
    assert "Verification: failed" in charter_md
    assert "- State: verification_failed" in charter_md


# ---------------------------------------------------------------------------
# worker end-to-end with a real git repo + owner clone
# ---------------------------------------------------------------------------


def _source_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    (path / "docs").mkdir()
    (path / "docs" / "guide.md").write_text("old\n", encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "base")
    return path


def _commit_in_clone(clone: Path, filename: str, content: str, message: str) -> str:
    _git(clone, "config", "user.email", "owner@example.com")
    _git(clone, "config", "user.name", "Owner")
    target = clone / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    _git(clone, "add", filename)
    _git(clone, "commit", "-m", message)
    return _git(clone, "rev-parse", "HEAD")


class _FakeLayout:
    def __init__(self, stage: Path) -> None:
        self.stage = stage

    def close(self) -> None:
        return None


def _stubbed_worker(monkeypatch: pytest.MonkeyPatch, **kwargs: Any):
    monkeypatch.setattr(
        verification, "build_repository_manifest_digest", lambda _root, _profile: DIGEST_A
    )
    monkeypatch.setattr(
        verification,
        "build_toolchain_capability_digest",
        lambda _root, _profile, **_kw: DIGEST_B,
    )
    monkeypatch.setattr(
        verification, "discover_sandbox_layout", lambda **kw: _FakeLayout(kw["stage"])
    )
    return verification.RoomBoardVerificationWorker(**kwargs)


def _passing_gate(gate_id: str) -> GateResult:
    return GateResult(gate_id, "passed", None, DIGEST_A, DIGEST_A, 0, 1)


def _owner_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    home = tmp_path / "home"
    home.mkdir()
    db = home / "chat.db"
    conversation = RoomTestStore(db).create_conversation("board room")
    participants = ParticipantStore(db)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(3)
    ]
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=members[0].participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation.id, members[0], owner="host-lead")
    obs_a = _claim(db, conversation.id, members[1], owner="host-a")
    modules, assignments, contracts = _split_payload(members, paths=["docs/**"])
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    store.decide_split(
        conversation_id=conversation.id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
        now=NOW,
    )
    source = _source_repo(tmp_path / "source")
    clones_root = home / "runtime" / "owner-clones"
    owner_id = owner_id_for_participant(conversation.id, members[1].participant_id)
    clone = OwnerCloneManager(clones_root).ensure(source, owner_id)
    worker = _stubbed_worker(
        monkeypatch,
        db_path=db,
        clones_root=clones_root,
        xmuse_root=home,
        execution_root=source,
        execution_profile_id="docs/v1",
    )
    return {
        "db": db,
        "conversation_id": conversation.id,
        "members": members,
        "store": store,
        "source": source,
        "clone": clone,
        "worker": worker,
        "leases": {
            members[1].participant_id: obs_a,
        },
    }


def test_worker_pass_verifies_committed_branch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _owner_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    head = _commit_in_clone(ctx["clone"].path, "docs/guide.md", "new\n", "owner work")
    owner = ctx["members"][1]
    ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )

    result = ctx["worker"].reconcile_once()

    assert result["board_verifications_passed"] == 1
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = conn.execute("select * from room_board_verifications").fetchone()
        activity = conn.execute(
            "select * from room_activities where activity_type = 'board.verification'"
        ).fetchone()
    assert row["status"] == "passed"
    assert row["head_commit"] == head
    assert json.loads(str(row["changed_paths_json"])) == ["docs/guide.md"]
    payload = json.loads(str(activity["payload_json"]))
    assert payload["status"] == "passed"
    assert payload["gates"] == [
        {
            "gate_id": "patch_diff_check",
            "status": "passed",
            "exit_code": 0,
            "reason_code": None,
        }
    ]
    assert activity["actor_kind"] == "infrastructure"
    assert not _observations_for(ctx["db"], owner.participant_id, activity["activity_id"])


def test_worker_verifies_while_human_checkout_moved_and_dirty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _owner_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    _commit_in_clone(ctx["clone"].path, "docs/guide.md", "new\n", "owner work")
    source = ctx["source"]
    (source / "docs" / "other.md").write_text("human\n", encoding="utf-8")
    _git(source, "add", "docs/other.md")
    _git(source, "commit", "-m", "human moves on")
    (source / "docs" / "guide.md").write_text("uncommitted human edit\n", encoding="utf-8")
    owner = ctx["members"][1]
    ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )

    result = ctx["worker"].reconcile_once()

    assert result["board_verifications_passed"] == 1
    assert (source / "docs" / "guide.md").read_text(encoding="utf-8") == (
        "uncommitted human edit\n"
    )


def test_worker_gate_failure_wakes_owner_with_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _owner_fixture(tmp_path, monkeypatch)

    requested: list[int] = []

    def failing_gate(_layout: Any, gate_id: str, **kw: Any) -> GateResult:
        requested.append(int(kw.get("output_tail_bytes", 0)))
        return GateResult(
            gate_id,
            "failed",
            "execution_gate_failed",
            DIGEST_A,
            DIGEST_A,
            1,
            1,
            output_tail="E   AssertionError: expected Hello, Ada!",
        )

    monkeypatch.setattr(verification, "run_gate", failing_gate)
    _commit_in_clone(ctx["clone"].path, "docs/guide.md", "new\n", "owner work")
    owner = ctx["members"][1]
    ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )

    result = ctx["worker"].reconcile_once()

    assert result["board_verifications_failed"] == 1
    assert requested and all(value > 0 for value in requested)
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = dict(conn.execute("select * from room_board_verifications").fetchone())
        activity = conn.execute(
            "select * from room_activities where activity_type = 'board.verification'"
        ).fetchone()
    assert row["status"] == "failed"
    payload = json.loads(str(activity["payload_json"]))
    assert payload["reason_code"] == "board_verification_gate_failed"
    assert payload["evidence"]["failed_gates"] == ["patch_diff_check"]
    assert payload["evidence"]["output_tails"] == {
        "patch_diff_check": "E   AssertionError: expected Hello, Ada!"
    }
    # The owner's delivery text carries the failing output.
    assert "AssertionError: expected Hello, Ada!" in str(payload["content"])
    assert _observations_for(ctx["db"], owner.participant_id, activity["activity_id"])


def test_worker_empty_patch_fails_without_waking_lead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _owner_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    owner, lead = ctx["members"][1], ctx["members"][0]
    ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )

    result = ctx["worker"].reconcile_once()

    assert result["board_verifications_failed"] == 1
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = dict(conn.execute("select * from room_board_verifications").fetchone())
        activity = conn.execute(
            "select * from room_activities where activity_type = 'board.verification'"
        ).fetchone()
    assert row["status"] == "failed"
    assert json.loads(str(row["result_json"]))["reason_code"] == "owner_patch_empty"
    assert _observations_for(ctx["db"], owner.participant_id, activity["activity_id"])
    assert not _observations_for(ctx["db"], lead.participant_id, activity["activity_id"])


def test_worker_path_outside_charter_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _owner_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    _commit_in_clone(ctx["clone"].path, "src/evil.py", "EVIL = 1\n", "out of bounds")
    owner = ctx["members"][1]
    ctx["store"].report_progress(
        **_lease_kwargs(owner, ctx["leases"][owner.participant_id], request_id="done-1"),
        module_id="alpha",
        status="done",
        summary="finished",
        claims=[],
    )

    result = ctx["worker"].reconcile_once()

    assert result["board_verifications_failed"] == 1
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = dict(conn.execute("select * from room_board_verifications").fetchone())
    outcome = json.loads(str(row["result_json"]))
    assert outcome["reason_code"] == "board_verification_outside_charter"
    assert outcome["evidence"]["offending_paths"] == ["src/evil.py"]


def test_worker_third_failure_escalates_to_lead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _owner_fixture(tmp_path, monkeypatch)

    def failing_gate(_layout: Any, gate_id: str, **_kw: Any) -> GateResult:
        return GateResult(gate_id, "failed", "execution_gate_failed", DIGEST_A, DIGEST_A, 1, 1)

    monkeypatch.setattr(verification, "run_gate", failing_gate)
    _commit_in_clone(ctx["clone"].path, "docs/guide.md", "new\n", "owner work")
    owner, lead = ctx["members"][1], ctx["members"][0]
    for index in range(3):
        kwargs = _lease_kwargs(
            owner, ctx["leases"][owner.participant_id], request_id=f"done-{index}"
        )
        kwargs["now"] = _round_time(index)
        ctx["store"].report_progress(
            **kwargs,
            module_id="alpha",
            status="done",
            summary="finished",
            claims=[],
        )
        result = ctx["worker"].reconcile_once(now=_round_time(index))
        assert result["board_verifications_failed"] == 1

    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        activities = conn.execute(
            "select * from room_activities where activity_type = 'board.verification' order by seq"
        ).fetchall()
    assert len(activities) == 3
    assert not _observations_for(ctx["db"], lead.participant_id, activities[0]["activity_id"])
    assert not _observations_for(ctx["db"], lead.participant_id, activities[1]["activity_id"])
    assert _observations_for(ctx["db"], lead.participant_id, activities[2]["activity_id"])


def test_read_base_commit_returns_host_metadata(tmp_path: Path) -> None:
    source = _source_repo(tmp_path / "source")
    manager = OwnerCloneManager(tmp_path / "clones")
    clone = manager.ensure(source, "p-abc123")

    assert manager.read_base_commit("p-abc123") == clone.base_commit
    with pytest.raises(OwnerCloneError) as invalid:
        manager.read_base_commit("NOT VALID!")
    assert invalid.value.code == "owner_id_invalid"
    with pytest.raises(OwnerCloneError):
        manager.read_base_commit("p-missing")


def test_owner_prompt_describes_host_verification() -> None:
    prompt = build_room_observation_prompt("claude", owner=True)

    assert "commit before reporting done" in prompt
    assert "failed verification" in prompt


# ---------------------------------------------------------------------------
# dependency-aware verification (M1.1)
# ---------------------------------------------------------------------------


def _stack_board(tmp_path: Path, *, home_name: str = "home-stack"):
    db_parent = tmp_path / home_name
    db_parent.mkdir(parents=True, exist_ok=True)
    db = db_parent / "chat.db"
    conversation = RoomTestStore(db).create_conversation("board room")
    participants = ParticipantStore(db)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(3)
    ]
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=members[0].participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    return db, conversation.id, members


def _stack_fixture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    backend_paths: list[str] | None = None,
    frontend_paths: list[str] | None = None,
    home_name: str = "home-stack",
    source_name: str = "source-stack",
):
    db, conversation_id, members = _stack_board(tmp_path, home_name=home_name)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    obs_backend = _claim(db, conversation_id, members[1], owner="host-b")
    obs_frontend = _claim(db, conversation_id, members[2], owner="host-f")
    modules = [
        {
            "module_id": "backend",
            "title": "Backend API",
            "paths": backend_paths or ["src/api/**"],
            "provides": ["api.greeting"],
            "depends": [],
            "acceptance": ["backend works"],
            "report_to": members[0].participant_id,
        },
        {
            "module_id": "frontend",
            "title": "Frontend client",
            "paths": frontend_paths or ["src/client/**"],
            "provides": [],
            "depends": ["api.greeting"],
            "acceptance": ["frontend works"],
            "report_to": members[0].participant_id,
        },
    ]
    assignments = {
        "backend": members[1].participant_id,
        "frontend": members[2].participant_id,
    }
    contracts = [
        {
            "contract_id": "api.greeting",
            "provider_module_id": "backend",
            "kind": "protocol",
            "content": "greet v1",
            "rationale": "initial",
        }
    ]
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
        now=NOW,
    )
    home = tmp_path / home_name
    source = _source_repo(tmp_path / source_name)
    clones_root = home / "runtime" / "owner-clones"
    manager = OwnerCloneManager(clones_root)
    backend_clone = manager.ensure(
        source, owner_id_for_participant(conversation_id, members[1].participant_id)
    )
    frontend_clone = manager.ensure(
        source, owner_id_for_participant(conversation_id, members[2].participant_id)
    )
    worker = _stubbed_worker(
        monkeypatch,
        db_path=db,
        clones_root=clones_root,
        xmuse_root=home,
        execution_root=source,
        execution_profile_id="python-uv/v1",
    )
    return {
        "db": db,
        "conversation_id": conversation_id,
        "members": members,
        "store": store,
        "source": source,
        "backend_clone": backend_clone,
        "frontend_clone": frontend_clone,
        "worker": worker,
        "leases": {
            members[0].participant_id: lead_obs,
            members[1].participant_id: obs_backend,
            members[2].participant_id: obs_frontend,
        },
    }


def _follow_up_split(ctx, *, depends: list[str], module_id: str = "backend-v2") -> None:
    """The lead adds a module for the backend owner on the same paths, and it is approved."""

    lead = ctx["members"][0]
    store = ctx["store"]
    proposed = store.propose_split(
        **_lease_kwargs(
            lead, ctx["leases"][lead.participant_id], request_id=f"propose-{module_id}"
        ),
        modules=[
            {
                "module_id": module_id,
                "title": "Backend follow-up",
                "paths": ["src/api/**"],
                "provides": ["api.farewell"],
                "depends": depends,
                "acceptance": ["farewell works"],
                "report_to": lead.participant_id,
            }
        ],
        assignments={module_id: ctx["members"][1].participant_id},
        contracts=[
            {
                "contract_id": "api.farewell",
                "provider_module_id": module_id,
                "kind": "protocol",
                "content": "farewell v1",
                "rationale": "follow-up",
            }
        ],
    )
    store.decide_split(
        conversation_id=ctx["conversation_id"],
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
        now=NOW,
    )


@pytest.mark.parametrize("depends", [["api.greeting"], []])
def test_follow_up_module_of_the_same_owner_stacks_its_predecessor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, depends: list[str]
) -> None:
    """Module start: the owner's second module carries only its own delta.

    Real run root4: the owner's follow-up module touched the file of its first
    module. With ``depends`` it failed as a dependency overlap; without it the
    patch carried the first module's change again and integration conflicted.
    """

    ctx = _stack_fixture(
        tmp_path,
        monkeypatch,
        home_name=f"home-follow-{len(depends)}",
        source_name=f"source-follow-{len(depends)}",
    )
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    clone = ctx["backend_clone"].path
    first_head = _commit_in_clone(clone, "src/api/greeting.py", "GREET = 1\n", "backend v1")
    _report_module_done(ctx, 1, "backend", "done-b1")
    assert ctx["worker"].reconcile_once()["board_verifications_passed"] == 1
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        first_vid = str(
            conn.execute(
                "select verification_id from room_board_verifications where module_id = 'backend'"
            ).fetchone()[0]
        )

    _follow_up_split(ctx, depends=depends)
    captured: dict[str, str] = {}

    def _capturing_gate(layout: Any, gate_id: str, **_kw: Any) -> GateResult:
        stage = Path(str(layout.stage))
        captured["greeting"] = (stage / "src/api/greeting.py").read_text(encoding="utf-8")
        return _passing_gate(gate_id)

    monkeypatch.setattr(verification, "run_gate", _capturing_gate)
    second_head = _commit_in_clone(
        clone, "src/api/greeting.py", "GREET = 1\nBYE = 2\n", "backend follow-up"
    )
    report = _report_module_done(ctx, 1, "backend-v2", "done-b2")

    result = ctx["worker"].reconcile_once()

    assert result["board_verifications_passed"] == 1
    # The stage saw the owner's whole tree: first module stacked below the delta.
    assert captured["greeting"] == "GREET = 1\nBYE = 2\n"
    row = _verification_row(ctx["db"], report["verification_id"])
    assert row["status"] == "passed"
    assert row["head_commit"] == second_head
    own_patch = str(row["patch_text"])
    assert "+BYE = 2" in own_patch
    assert "+GREET = 1" not in own_patch
    outcome = json.loads(str(row["result_json"]))
    assert outcome["stacked"] == [
        {
            "module_id": "backend",
            "verification_id": first_vid,
            "head_commit": first_head,
            "kind": "predecessor",
        }
    ]
    # Integration applies the predecessor first even without a contract edge.
    inputs = ctx["store"].board_integration_inputs(ctx["conversation_id"])
    assert "backend" in inputs["providers"]["backend-v2"]


def test_module_without_earlier_owner_work_exports_from_the_clone_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first module of an owner keeps the old behaviour: no predecessor."""

    ctx = _stack_fixture(tmp_path, monkeypatch, home_name="home-first", source_name="source-first")
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    _commit_in_clone(ctx["backend_clone"].path, "src/api/greeting.py", "GREET = 1\n", "v1")
    report = _report_module_done(ctx, 1, "backend", "done-b1")
    assert ctx["worker"].reconcile_once()["board_verifications_passed"] == 1
    row = _verification_row(ctx["db"], report["verification_id"])
    assert json.loads(str(row["result_json"]))["stacked"] == []
    assert "+GREET = 1" in str(row["patch_text"])


def _report_module_done(
    ctx, member_index: int, module_id: str, request_id: str, *, now: datetime = NOW
) -> dict[str, Any]:
    return _report_done(ctx, member_index, request_id, now=now, module_id=module_id)


def _verification_activities(db: Path) -> list[dict[str, Any]]:
    with RoomDatabase(db).connect(readonly=True) as conn:
        rows = conn.execute(
            "select * from room_activities where activity_type = 'board.verification'"
        ).fetchall()
        return [dict(row) for row in rows]


def test_provider_modules_resolve_from_latest_contracts(tmp_path: Path) -> None:
    # Build a lightweight board without clones to exercise the store helper.
    db, conversation_id, members = _stack_board(tmp_path, home_name="home-prov")
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members, paths=["src/alpha/**"])
    proposed = store.propose_split(
        **_lease_kwargs(members[0], lead_obs, request_id="propose-1"),
        modules=modules,
        assignments=assignments,
        contracts=contracts,
    )
    store.decide_split(
        conversation_id=conversation_id,
        split_id=proposed["split_id"],
        decision="approve",
        operator_identity="operator:host",
    )
    # beta depends on api.alpha (provided by alpha); alpha depends on nothing.
    assert store.provider_modules_for_module(conversation_id, "alpha") == []
    assert store.provider_modules_for_module(conversation_id, "beta") == ["alpha"]


def test_upstream_modules_walk_chains_and_diamonds() -> None:
    edges = {"c": ["a", "b"], "b": ["a"], "a": [], "d": ["c"]}

    class _Store:
        def provider_modules_for_module(self, _conversation_id: str, module_id: str):
            return edges[module_id]

    store: Any = _Store()
    assert verification.upstream_modules(store, "room", "d") == ["a", "b", "c"]
    assert verification.upstream_modules(store, "room", "c") == ["a", "b"]
    assert verification.upstream_modules(store, "room", "a") == []


def test_patch_text_paths_reads_only_own_headers() -> None:
    text = (
        "diff --git a/src/b/x.py b/src/b/x.py\n--- a/src/b/x.py\n+++ b/src/b/x.py\n"
        "@@ -1 +1 @@\n-a\n+b\n"
        "diff --git a/src/b/old.py b/src/b/new.py\nrename from src/b/old.py\n"
    )

    assert verification.patch_text_paths(text) == [
        "src/b/new.py",
        "src/b/old.py",
        "src/b/x.py",
    ]
    # Diamond: b's own patch and a's patch do not overlap even though b's
    # recorded verification paths include a's files.
    assert verification.find_overlapping_paths([["src/a/y.py"], ["src/b/x.py"]]) == []


def test_split_dependency_cycle_is_detected() -> None:
    contracts = [
        {"contract_id": "api.a", "provider_module_id": "a"},
        {"contract_id": "api.b", "provider_module_id": "b"},
        {"contract_id": "api.c", "provider_module_id": "c"},
    ]
    acyclic = [
        {"module_id": "a", "depends": []},
        {"module_id": "b", "depends": ["api.a"]},
        {"module_id": "c", "depends": ["api.a", "api.b"]},
    ]
    cyclic = [
        {"module_id": "a", "depends": ["api.c"]},
        {"module_id": "b", "depends": ["api.a"]},
        {"module_id": "c", "depends": ["api.b"]},
    ]

    assert split_dependency_cycle(acyclic, contracts) is None
    assert split_dependency_cycle(cyclic, contracts) == ["a", "c", "b", "a"]


def test_cyclic_split_is_rejected(tmp_path: Path) -> None:
    db, conversation_id, members = _stack_board(tmp_path)
    store = RoomBoardStore(db)
    lead_obs = _claim(db, conversation_id, members[0], owner="host-lead")
    modules, assignments, contracts = _split_payload(members)
    modules[0]["depends"] = ["api.beta"]

    with pytest.raises(ValueError, match="room_board_split_dependency_cycle"):
        store.propose_split(
            **_lease_kwargs(members[0], lead_obs, request_id="propose-cycle"),
            modules=modules,
            assignments=assignments,
            contracts=contracts,
        )


def test_frontend_stacks_backend_pass(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _stack_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    backend_head = _commit_in_clone(
        ctx["backend_clone"].path, "src/api/greeting.py", "GREET = 1\n", "backend v1"
    )
    _report_module_done(ctx, 1, "backend", "done-b1")
    assert ctx["worker"].reconcile_once()["board_verifications_passed"] == 1

    captured: dict[str, Any] = {}

    def _capturing_gate(layout: Any, gate_id: str, **_kw: Any) -> GateResult:
        stage = Path(str(layout.stage))
        captured["greeting"] = (stage / "src/api/greeting.py").read_text(encoding="utf-8")
        captured["render"] = (stage / "src/client/render.py").read_text(encoding="utf-8")
        return _passing_gate(gate_id)

    monkeypatch.setattr(verification, "run_gate", _capturing_gate)
    frontend_head = _commit_in_clone(
        ctx["frontend_clone"].path, "src/client/render.py", "RENDER = 1\n", "frontend v1"
    )
    _report_module_done(ctx, 2, "frontend", "done-f1")

    result = ctx["worker"].reconcile_once()

    assert result["board_verifications_passed"] == 1
    assert captured["greeting"] == "GREET = 1\n"
    assert captured["render"] == "RENDER = 1\n"
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = conn.execute(
            "select * from room_board_verifications where module_id = 'frontend'"
        ).fetchone()
        assert row is not None
        assert row["status"] == "passed"
        assert row["head_commit"] == frontend_head
        assert row["patch_text"] is not None
        assert "RENDER" in str(row["patch_text"])
        result_json = json.loads(str(row["result_json"]))
    assert result_json["stacked"] == [
        {
            "module_id": "backend",
            "verification_id": result_json["stacked"][0]["verification_id"],
            "head_commit": backend_head,
        }
    ]
    activities = _verification_activities(ctx["db"])
    assert activities
    payload = json.loads(str(activities[-1]["payload_json"]))
    assert payload["module_id"] == "frontend"
    assert payload["stacked"] == result_json["stacked"]
    # The stage ran with both files; the recorded paths are the combined set.
    assert sorted(result_json["changed_paths"]) == [
        "src/api/greeting.py",
        "src/client/render.py",
    ]


def test_frontend_defers_until_backend_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _stack_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    t0 = NOW
    t1 = t0 + timedelta(seconds=5)
    t2 = t0 + timedelta(seconds=60)
    _commit_in_clone(
        ctx["frontend_clone"].path, "src/client/render.py", "RENDER = 1\n", "frontend v1"
    )
    frontend_report = _report_module_done(ctx, 2, "frontend", "done-f1", now=t0)
    before_activities = len(_verification_activities(ctx["db"]))
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        obs_before = conn.execute("select count(*) from room_observations").fetchone()[0]

    deferred = ctx["worker"].reconcile_once(now=t0)

    assert deferred["board_verifications_claimed"] == 1
    assert deferred["board_verifications_passed"] == 0
    assert deferred["board_verifications_failed"] == 0
    row = _verification_row(ctx["db"], frontend_report["verification_id"])
    assert row["status"] == "pending"
    assert int(row["attempt_count"]) == 0
    assert row["not_before"] is not None
    waiting = json.loads(str(row["result_json"]))
    assert waiting["status"] == "pending"
    assert waiting["reason_code"] == "board_verification_waiting_for_provider"
    assert waiting["providers"] == ["backend"]
    # A deferral writes no activity and wakes nobody.
    assert len(_verification_activities(ctx["db"])) == before_activities
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        obs_after = conn.execute("select count(*) from room_observations").fetchone()[0]
    assert obs_after == obs_before
    projected = ctx["store"].board_projection(conversation_id=ctx["conversation_id"])
    entry = next(item for item in projected["modules"] if item["module_id"] == "frontend")
    assert entry["verification"]["status"] == "waiting_for_provider"
    assert entry["verification"]["reason_code"] == "board_verification_waiting_for_provider"

    # The backend passes while the frontend waits.
    _commit_in_clone(ctx["backend_clone"].path, "src/api/greeting.py", "GREET = 1\n", "backend v1")
    _report_module_done(ctx, 1, "backend", "done-b1", now=t1)
    backend_result = ctx["worker"].reconcile_once(now=t1)
    assert backend_result["board_verifications_passed"] == 1

    final = ctx["worker"].reconcile_once(now=t2)
    assert final["board_verifications_passed"] == 1
    row = _verification_row(ctx["db"], frontend_report["verification_id"])
    assert row["status"] == "passed"


def test_newer_backend_pending_defers_frontend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _stack_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    t0 = NOW
    t1 = NOW + timedelta(seconds=60)
    t2 = NOW + timedelta(seconds=120)
    _commit_in_clone(ctx["backend_clone"].path, "src/api/greeting.py", "GREET = 1\n", "backend v1")
    _report_module_done(ctx, 1, "backend", "done-b1", now=t0)
    assert ctx["worker"].reconcile_once(now=t0)["board_verifications_passed"] == 1

    _commit_in_clone(
        ctx["frontend_clone"].path, "src/client/render.py", "RENDER = 1\n", "frontend v1"
    )
    frontend_report = _report_module_done(ctx, 2, "frontend", "done-f1", now=t1)
    _commit_in_clone(ctx["backend_clone"].path, "src/api/greeting.py", "GREET = 2\n", "backend v2")
    _report_module_done(ctx, 1, "backend", "done-b2", now=t1 + timedelta(seconds=5))

    deferred = ctx["worker"].reconcile_once(now=t2)
    assert deferred["board_verifications_claimed"] == 1
    row = _verification_row(ctx["db"], frontend_report["verification_id"])
    assert row["status"] == "pending"
    waiting = json.loads(str(row["result_json"]))
    assert waiting["reason_code"] == "board_verification_waiting_for_provider"
    assert waiting["providers"] == ["backend"]


def test_deferred_job_does_not_block_next_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _stack_fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    t0 = NOW
    t1 = t0 + timedelta(seconds=5)
    _commit_in_clone(
        ctx["frontend_clone"].path, "src/client/render.py", "RENDER = 1\n", "frontend v1"
    )
    _report_module_done(ctx, 2, "frontend", "done-f1", now=t0)
    assert ctx["worker"].reconcile_once(now=t0)["board_verifications_deferred"] == 1

    _commit_in_clone(ctx["backend_clone"].path, "src/api/greeting.py", "GREET = 1\n", "backend v1")
    backend_report = _report_module_done(ctx, 1, "backend", "done-b1", now=t1)
    claimed = ctx["store"].claim_next_board_verification(worker_id="w1", now=t1)
    assert claimed is not None
    assert claimed["verification_id"] == backend_report["verification_id"]


def test_overlapping_provider_paths_fail(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _stack_fixture(
        tmp_path,
        monkeypatch,
        backend_paths=["src/api/**", "src/shared/**"],
        frontend_paths=["src/client/**", "src/shared/**"],
        home_name="home-overlap",
        source_name="source-overlap",
    )
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    _commit_in_clone(
        ctx["backend_clone"].path, "src/shared/common.py", "BACKEND = 1\n", "backend shared"
    )
    _report_module_done(ctx, 1, "backend", "done-b1")
    assert ctx["worker"].reconcile_once()["board_verifications_passed"] == 1

    _commit_in_clone(
        ctx["frontend_clone"].path,
        "src/shared/common.py",
        "FRONTEND = 1\n",
        "frontend shared",
    )
    frontend_report = _report_module_done(ctx, 2, "frontend", "done-f1")
    result = ctx["worker"].reconcile_once()
    assert result["board_verifications_failed"] == 1
    row = _verification_row(ctx["db"], frontend_report["verification_id"])
    assert row["status"] == "failed"
    outcome = json.loads(str(row["result_json"]))
    assert outcome["reason_code"] == "board_verification_dependency_overlap"
    assert outcome["evidence"]["overlapping_paths"] == ["src/shared/common.py"]


def test_stacked_list_in_result_and_payload(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _stack_fixture(
        tmp_path,
        monkeypatch,
        home_name="home-stacked",
        source_name="source-stacked",
    )
    monkeypatch.setattr(
        verification, "run_gate", lambda _layout, gate_id, **_kw: _passing_gate(gate_id)
    )
    backend_head = _commit_in_clone(
        ctx["backend_clone"].path, "src/api/greeting.py", "GREET = 1\n", "backend v1"
    )
    _report_module_done(ctx, 1, "backend", "done-b1")
    assert ctx["worker"].reconcile_once()["board_verifications_passed"] == 1
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        backend_row = conn.execute(
            "select * from room_board_verifications where module_id = 'backend'"
        ).fetchone()
    backend_vid = str(backend_row["verification_id"])

    _commit_in_clone(
        ctx["frontend_clone"].path, "src/client/render.py", "RENDER = 1\n", "frontend v1"
    )
    frontend_report = _report_module_done(ctx, 2, "frontend", "done-f1")
    assert ctx["worker"].reconcile_once()["board_verifications_passed"] == 1

    row = _verification_row(ctx["db"], frontend_report["verification_id"])
    result_json = json.loads(str(row["result_json"]))
    assert result_json["stacked"] == [
        {"module_id": "backend", "verification_id": backend_vid, "head_commit": backend_head}
    ]
    activities = _verification_activities(ctx["db"])
    payload = json.loads(str(activities[-1]["payload_json"]))
    assert payload["module_id"] == "frontend"
    assert payload["stacked"] == result_json["stacked"]
