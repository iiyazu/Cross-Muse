"""Behaviour tests for the board integration job and engine (M2b).

Real git repositories in tmp dirs back every rule test, like the
verification tests: owner clones commit work, the engine rebuilds the
host-owned integration branch in the host mirror, and gates are stubbed.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any

import pytest

from tests.xmuse.board_scenarios import DIGEST_A, DIGEST_B, NOW, T0
from tests.xmuse.room_fixtures import RoomTestStore
from xmuse_core.chat import room_board_integration as integration
from xmuse_core.chat.participant_store import ParticipantStore
from xmuse_core.chat.room_board import (
    RoomBoardStore,
    integration_apply_order,
)
from xmuse_core.chat.room_board_projection import review_digest
from xmuse_core.chat.room_collaboration import write_room_collaboration_policy_conn
from xmuse_core.chat.room_database import RoomDatabase
from xmuse_core.chat.room_execution_sandbox import GateResult
from xmuse_core.chat.room_kernel import RoomKernelStore
from xmuse_core.chat.room_owner_clones import OwnerCloneManager
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


def _git_mirror(mirror: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", f"--git-dir={mirror}", *args],
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def _source_repo(path: Path, files: dict[str, str]) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.email", "test@example.com")
    _git(path, "config", "user.name", "Test")
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    _git(path, "add", ".")
    _git(path, "commit", "-m", "base")
    return path


def _commit_in_clone(clone: Path, filename: str, content: str | None, message: str) -> None:
    _git(clone, "config", "user.email", "owner@example.com")
    _git(clone, "config", "user.name", "Owner")
    target = clone / filename
    if content is None:
        _git(clone, "rm", "-q", filename)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        _git(clone, "add", filename)
    _git(clone, "commit", "-m", message)


def _t(seconds: int) -> datetime:
    return T0 + timedelta(seconds=seconds)


class _FakeLayout:
    def __init__(self, stage: Path) -> None:
        self.stage = stage

    def close(self) -> None:
        return None


def _passing_gate(layout: Any, gate_id: str, **kw: Any) -> GateResult:
    return GateResult(gate_id, "passed", None, DIGEST_A, DIGEST_A, 0, 1)


def _claim_obs(db: Path, conversation_id: str, participant: Any, owner: str) -> dict[str, Any]:
    claimed = RoomKernelStore(db).claim_next_observation_batch(
        conversation_id=conversation_id,
        participant_id=participant.participant_id,
        lease_owner=owner,
        lease_ttl_s=86400 * 30,
        now=T0,
    )
    assert claimed is not None
    return claimed["observation"]


def _room(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    name: str,
    specs: list[dict[str, Any]],
    files: dict[str, str],
    review_policy: str = "off",
    gate: Any = None,
    delays: tuple[float, float] = (60.0, 120.0),
) -> dict[str, Any]:
    """Build a room with one owner participant per spec plus owner clones."""

    home = tmp_path / name
    home.mkdir()
    db = home / "chat.db"
    conversation = RoomTestStore(db).create_conversation("integration room")
    participants = ParticipantStore(db)
    members = [
        participants.add(
            conversation_id=conversation.id,
            role=f"role-{index}",
            display_name=f"Agent {index}",
            cli_kind="codex",
            model="gpt-5",
        )
        for index in range(len(specs) + 1)
    ]
    with RoomDatabase(db).connect() as conn:
        write_room_collaboration_policy_conn(
            conn,
            conversation_id=conversation.id,
            mode="broadcast",
            lead_participant_id=members[0].participant_id,
            updated_at="2026-01-01T00:00:00.000000Z",
            review_policy=review_policy,
        )
        conn.commit()
    RoomKernelStore(db).post_human_activity(
        conversation_id=conversation.id,
        human_id="human",
        content="kickoff",
        client_request_id="kickoff",
    )
    store = RoomBoardStore(db)
    leases = {
        member.participant_id: _claim_obs(db, conversation.id, member, f"host-{index}")
        for index, member in enumerate(members)
    }

    def lease_kwargs(member: Any, request_id: str, *, now: datetime = NOW) -> dict[str, Any]:
        obs = leases[member.participant_id]
        return {
            "conversation_id": conversation.id,
            "participant_id": member.participant_id,
            "caller_identity": f"god:testsess:{member.participant_id}",
            "observation_id": obs["observation_id"],
            "lease_token": obs["lease_token"],
            "client_request_id": request_id,
            "now": now,
        }

    modules: list[dict[str, Any]] = []
    assignments: dict[str, str] = {}
    contracts: list[dict[str, Any]] = []
    for index, spec in enumerate(specs):
        owner = members[index + 1]
        provides = spec.get("provides", [f"api.{spec['id']}"])
        modules.append(
            {
                "module_id": spec["id"],
                "title": spec["id"],
                "paths": spec["paths"],
                "provides": provides,
                "depends": spec.get("depends", []),
                "acceptance": ["works"],
                "report_to": members[0].participant_id,
            }
        )
        assignments[spec["id"]] = owner.participant_id
        for contract_id in provides:
            contracts.append(
                {
                    "contract_id": contract_id,
                    "provider_module_id": spec["id"],
                    "kind": "api_schema",
                    "content": "{}",
                    "rationale": "",
                }
            )
    proposed = store.propose_split(
        **lease_kwargs(members[0], "propose-1"),
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
    source = _source_repo(tmp_path / f"{name}-source", files)
    clones_root = home / "runtime" / "owner-clones"
    manager = OwnerCloneManager(clones_root)
    clones = {}
    for index, spec in enumerate(specs):
        owner_id = owner_id_for_participant(conversation.id, members[index + 1].participant_id)
        clones[spec["id"]] = manager.ensure(source, owner_id).path
    monkeypatch.setattr(
        integration, "build_repository_manifest_digest", lambda _root, _profile: DIGEST_A
    )
    monkeypatch.setattr(
        integration,
        "build_toolchain_capability_digest",
        lambda _root, _profile, **_kw: DIGEST_B,
    )
    monkeypatch.setattr(
        integration, "discover_sandbox_layout", lambda **kw: _FakeLayout(Path(str(kw["stage"])))
    )
    monkeypatch.setattr(integration, "run_gate", gate or _passing_gate)
    worker = integration.RoomBoardIntegrationWorker(
        db_path=db,
        clones_root=clones_root,
        xmuse_root=home,
        execution_root=source,
        execution_profile_id="docs/v1",
        auto_retry_delays_s=delays,
    )
    return {
        "db": db,
        "home": home,
        "conversation_id": conversation.id,
        "members": members,
        "store": store,
        "leases": leases,
        "lease_kwargs": lease_kwargs,
        "source": source,
        "clones_root": clones_root,
        "clones": clones,
        "worker": worker,
        "specs": specs,
    }


def _pass_module(
    ctx: dict[str, Any], member_index: int, module_id: str, request_id: str, *, now: datetime
) -> dict[str, Any]:
    """Report done, export the real patch, and complete a passed verification."""

    store = ctx["store"]
    owner = ctx["members"][member_index]
    reported = store.report_progress(
        **ctx["lease_kwargs"](owner, request_id, now=now),
        module_id=module_id,
        status="done",
        summary="finished",
        claims=[],
    )
    manager = OwnerCloneManager(ctx["clones_root"])
    owner_id = owner_id_for_participant(ctx["conversation_id"], owner.participant_id)
    base = manager.read_base_commit(owner_id)
    patch = manager.export_patch(owner_id, base_commit=base)
    claimed = store.claim_next_board_verification(worker_id="w1", now=now)
    assert claimed is not None
    assert claimed["verification_id"] == reported["verification_id"]
    store.complete_board_verification(
        verification_id=reported["verification_id"],
        lease_token=claimed["lease_token"],
        status="passed",
        reason_code=None,
        head_commit=patch.head_commit,
        patch_digest=f"sha256:{sha256(patch.unified_diff.encode('utf-8')).hexdigest()}",
        changed_paths=sorted(patch.changed_paths),
        gates=[{"gate_id": "patch_diff_check", "status": "passed", "exit_code": 0}],
        evidence={},
        now=now,
        patch_text=patch.unified_diff,
        stacked=[],
        base_commit=base,
    )
    return {"verification_id": reported["verification_id"], "head_commit": patch.head_commit}


def _latest_job(ctx: dict[str, Any]) -> dict[str, Any]:
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = conn.execute(
            "select * from room_board_integrations order by created_at desc, rowid desc limit 1"
        ).fetchone()
    assert row is not None
    job = dict(row)
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        items = conn.execute(
            "select * from room_board_integration_items where integration_id = ? "
            "order by item_order",
            (job["integration_id"],),
        ).fetchall()
    job["items"] = [dict(item) for item in items]
    for item in job["items"]:
        item["conflicts"] = json.loads(str(item.pop("conflicts_json") or "[]"))
    return job


def _job_count(ctx: dict[str, Any]) -> int:
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        return int(conn.execute("select count(*) from room_board_integrations").fetchone()[0])


def _integration_activity(ctx: dict[str, Any]) -> dict[str, Any]:
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = conn.execute(
            "select * from room_activities where activity_type = 'board.integration' "
            "order by seq desc limit 1"
        ).fetchone()
    assert row is not None
    activity = dict(row)
    activity["payload"] = json.loads(str(activity["payload_json"]))
    return activity


def _observations_for(db: Path, participant_id: str, activity_id: str) -> list[Any]:
    with RoomDatabase(db).connect(readonly=True) as conn:
        return conn.execute(
            "select * from room_observations where participant_id = ? and activity_id = ?",
            (participant_id, activity_id),
        ).fetchall()


def _mirror_ref(ctx: dict[str, Any]) -> str | None:
    mirror = ctx["clones_root"] / ".mirror.git"
    result = subprocess.run(
        [
            "git",
            f"--git-dir={mirror}",
            "rev-parse",
            "--verify",
            f"refs/heads/xmuse/integration/{ctx['conversation_id']}^{{commit}}",
        ],
        env=_GIT_ENV,
        capture_output=True,
        text=True,
        timeout=60,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def _mirror_tree(ctx: dict[str, Any], commit: str) -> dict[str, str]:
    mirror = ctx["clones_root"] / ".mirror.git"
    names = _git_mirror(mirror, "ls-tree", "-r", "--name-only", commit).splitlines()
    tree = {}
    for name in names:
        result = subprocess.run(
            ["git", f"--git-dir={mirror}", "show", f"{commit}:{name}"],
            env=_GIT_ENV,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
        tree[name] = result.stdout
    return tree


def _source_snapshot(source: Path) -> dict[str, Any]:
    head = _git(source, "rev-parse", "HEAD")
    status = _git(source, "status", "--porcelain")
    worktrees = _git(source, "worktree", "list")
    refs = _git(source, "show-ref")
    hashes: dict[str, str] = {}
    for path in sorted(source.rglob("*")):
        if ".git" in path.parts or not path.is_file():
            continue
        hashes[str(path.relative_to(source))] = sha256(path.read_bytes()).hexdigest()
    return {"head": head, "status": status, "worktrees": worktrees, "refs": refs, "hashes": hashes}


# ---------------------------------------------------------------------------
# pure ordering and conflict helpers
# ---------------------------------------------------------------------------


def test_integration_apply_order_incumbents_first_then_dependencies() -> None:
    providers = {"m1": [], "m2": ["m1"], "m3": []}
    roles = {"m1": "newcomer", "m2": "incumbent", "m3": "incumbent"}
    # m2 is an incumbent but depends on the newcomer m1: it still goes last,
    # while the ready incumbent m3 goes before the ready newcomer m1.
    assert integration_apply_order(["m1", "m2", "m3"], providers, roles) == ["m3", "m1", "m2"]
    # Among ready candidates incumbents go before newcomers, then module id.
    assert integration_apply_order(
        ["b", "a"], {"b": [], "a": []}, {"b": "newcomer", "a": "newcomer"}
    ) == [
        "a",
        "b",
    ]
    assert integration_apply_order(
        ["b", "a"], {"b": [], "a": []}, {"b": "newcomer", "a": "incumbent"}
    ) == ["a", "b"]


def test_parse_apply_conflicts_reads_git_stderr() -> None:
    stderr = (
        "error: patch failed: docs/a.txt:1\n"
        "error: docs/a.txt: already exists in working directory\n"
        "error: docs/gone.txt: does not exist in index\n"
        "error: patch failed: docs/a.txt:8\n"
        "From https://example.com/x\n"
    )
    assert integration.parse_apply_conflicts(stderr) == [
        "docs/a.txt",
        "docs/gone.txt",
    ]


def test_attribute_conflicts_counts_invalid_paths_without_listing() -> None:
    charters = {
        "m1": {"charter": {"paths": ["docs/shared/**"]}},
        "m2": {"charter": {"paths": ["docs/shared/s.txt"]}},
        "m3": {"charter": {"paths": ["docs/other/**"]}},
    }
    listed, total = integration.attribute_conflicts(
        ["docs/shared/s.txt", "docs/\u202ereversed.txt", "docs/shared/s.txt"],
        charters,
    )
    # The bidirectional-control path breaks the Finding.path rule: counted only.
    assert total == 2
    assert listed == [
        {"path": "docs/shared/s.txt", "attributed_module_ids": ["m1", "m2"]},
    ]
    assert len(listed) <= integration.MAX_CONFLICT_PATHS_LISTED


# ---------------------------------------------------------------------------
# incumbents first + fallback keeps the older version, branch moves
# ---------------------------------------------------------------------------


def test_incumbent_first_newcomer_falls_back_and_branch_moves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-incumbent",
        specs=[
            {"id": "m1", "paths": ["docs/a.txt"]},
            {"id": "m2", "paths": ["docs/b.txt"]},
        ],
        files={"docs/a.txt": "a0\n", "docs/b.txt": "b0\n"},
    )
    before = _source_snapshot(ctx["source"])
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _commit_in_clone(ctx["clones"]["m2"], "docs/b.txt", "b1\n", "m2 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    _pass_module(ctx, 2, "m2", "done-m2v1", now=_t(20))
    assert ctx["worker"].reconcile_once(now=_t(30))["board_integrations_integrated"] == 1
    green1 = _mirror_ref(ctx)
    assert green1
    assert _job_count(ctx) == 1

    # m1's new candidate also rewrites m2's file: m2 (incumbent) applies first,
    # m1 conflicts and falls back to its older integrated version.
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a2\n", "m1 v2a")
    _commit_in_clone(ctx["clones"]["m1"], "docs/b.txt", "bX\n", "m1 v2b")
    _pass_module(ctx, 1, "m1", "done-m1v2", now=_t(40))
    result = ctx["worker"].reconcile_once(now=_t(50))

    assert result["board_integrations_integrated"] == 1
    job = _latest_job(ctx)
    assert job["status"] == "integrated"
    assert job["reason_code"] is None
    by_module = {item["module_id"]: item for item in job["items"]}
    assert [item["module_id"] for item in job["items"]] == ["m2", "m1"]
    assert by_module["m2"]["role"] == "incumbent"
    assert by_module["m2"]["status"] == "applied"
    assert by_module["m1"]["role"] == "newcomer"
    assert by_module["m1"]["status"] == "fell_back"
    assert by_module["m1"]["applied_verification_id"] != by_module["m1"]["verification_id"]
    assert by_module["m1"]["conflicts_total"] == 1
    assert by_module["m1"]["conflicts"] == [{"path": "docs/b.txt", "attributed_module_ids": ["m2"]}]
    # Only a fallback, no new code: the result equals the green head, so no gate
    # runs and the branch does not move (rule 5).
    green2 = _mirror_ref(ctx)
    assert green2 == green1
    assert job["green_after"] == green1
    assert job["result_commit"] == green1
    tree = _mirror_tree(ctx, green2)
    assert tree["docs/a.txt"] == "a1\n"
    assert tree["docs/b.txt"] == "b1\n"
    # An integrated job wakes nobody.
    activity = _integration_activity(ctx)
    payload = activity["payload"]
    assert payload["status"] == "integrated"
    assert activity["actor_kind"] == "infrastructure"
    for member in ctx["members"]:
        assert not _observations_for(ctx["db"], member.participant_id, activity["activity_id"])
    assert payload["green_head_commit"] == green2
    assert sorted(payload["integrated_module_ids"]) == ["m1", "m2"]
    assert payload["suspect_module_ids"] == []
    assert payload["waiting_module_ids"] == []
    assert payload["gate_ids"] == []
    assert payload["conflicts"] == [
        {
            "module_id": "m1",
            "conflict_path_count": 1,
            "attributed_module_ids": ["m2"],
            "fell_back": True,
        }
    ]
    # The user's checkout is byte-identical; only the host mirror ref moved.
    assert _source_snapshot(ctx["source"]) == before


def test_dependency_order_beats_incumbency(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-deporder",
        specs=[
            {"id": "m1", "paths": ["docs/a.txt"]},
            {"id": "m2", "paths": ["docs/b.txt"], "depends": ["api.m1"]},
        ],
        files={"docs/a.txt": "a0\n", "docs/b.txt": "b0\n"},
    )
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _commit_in_clone(ctx["clones"]["m2"], "docs/b.txt", "b1\n", "m2 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    _pass_module(ctx, 2, "m2", "done-m2v1", now=_t(20))
    assert ctx["worker"].reconcile_once(now=_t(30))["board_integrations_integrated"] == 1

    # Only the provider gets a new candidate: it still applies first even
    # though the dependent is the incumbent.
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a2\n", "m1 v2")
    _pass_module(ctx, 1, "m1", "done-m1v2", now=_t(40))
    assert ctx["worker"].reconcile_once(now=_t(50))["board_integrations_integrated"] == 1
    job = _latest_job(ctx)
    by_module = {item["module_id"]: item for item in job["items"]}
    assert [item["module_id"] for item in job["items"]] == ["m1", "m2"]
    assert by_module["m1"]["role"] == "newcomer"
    assert by_module["m2"]["role"] == "incumbent"
    assert by_module["m1"]["status"] == "applied"
    assert by_module["m2"]["status"] == "applied"
    tree = _mirror_tree(ctx, _mirror_ref(ctx))
    assert tree["docs/a.txt"] == "a2\n"
    assert tree["docs/b.txt"] == "b1\n"


# ---------------------------------------------------------------------------
# rule 4 culprit pinning: a newcomer never makes an incumbent conflicted
# ---------------------------------------------------------------------------


def test_rule4_pin_culprit_newcomer_never_breaks_incumbent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-rule4",
        specs=[
            {"id": "m1", "paths": ["docs/a.txt", "docs/shared.txt"]},
            {"id": "m2", "paths": ["docs/b.txt", "docs/shared.txt"], "depends": ["api.m1"]},
        ],
        files={"docs/a.txt": "a0\n", "docs/b.txt": "b0\n", "docs/shared.txt": "s0\n"},
    )
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _commit_in_clone(ctx["clones"]["m2"], "docs/b.txt", "b1\n", "m2 v1a")
    _commit_in_clone(ctx["clones"]["m2"], "docs/shared.txt", "m2s\n", "m2 v1b")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    _pass_module(ctx, 2, "m2", "done-m2v1", now=_t(20))
    assert ctx["worker"].reconcile_once(now=_t(30))["board_integrations_integrated"] == 1
    green1 = _mirror_ref(ctx)

    # m1's new candidate rewrites the shared file the unchanged m2 owns: m1 is
    # the culprit, pinned to its fallback, and m2 stays integrated.
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a2\n", "m1 v2a")
    _commit_in_clone(ctx["clones"]["m1"], "docs/shared.txt", "m1s\n", "m1 v2b")
    _pass_module(ctx, 1, "m1", "done-m1v2", now=_t(40))
    result = ctx["worker"].reconcile_once(now=_t(50))

    assert result["board_integrations_integrated"] == 1
    job = _latest_job(ctx)
    assert job["status"] == "integrated"
    by_module = {item["module_id"]: item for item in job["items"]}
    assert by_module["m2"]["role"] == "incumbent"
    assert by_module["m2"]["status"] == "applied"
    assert by_module["m2"]["applied_verification_id"] == by_module["m2"]["verification_id"]
    assert by_module["m1"]["role"] == "newcomer"
    assert by_module["m1"]["status"] == "conflicted"
    assert by_module["m1"]["applied_verification_id"] != by_module["m1"]["verification_id"]
    assert by_module["m1"]["conflicts"] == [
        {"path": "docs/shared.txt", "attributed_module_ids": ["m1", "m2"]}
    ]
    assert by_module["m1"]["conflicts_total"] == 1
    green2 = _mirror_ref(ctx)
    assert green2 == green1  # culprit pinned back: nothing new, branch stays (rule 5)
    tree = _mirror_tree(ctx, green2)
    assert tree["docs/a.txt"] == "a1\n"
    assert tree["docs/shared.txt"] == "m2s\n"
    assert tree["docs/b.txt"] == "b1\n"
    payload = _integration_activity(ctx)["payload"]
    assert payload["conflicts"] == [
        {
            "module_id": "m1",
            "conflict_path_count": 1,
            "attributed_module_ids": ["m1", "m2"],
            "fell_back": True,
        }
    ]


# ---------------------------------------------------------------------------
# rule 3 closure under depends: dependents fall back or wait
# ---------------------------------------------------------------------------


def test_dependent_of_fallback_waits_and_set_stays_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-closure",
        specs=[
            {"id": "m0", "paths": ["docs/s.txt"]},
            {"id": "m1", "paths": ["docs/s.txt", "docs/c.txt"]},
            {"id": "m2", "paths": ["docs/d.txt"], "depends": ["api.m1"], "provides": []},
        ],
        files={"docs/s.txt": "s0\n", "docs/c.txt": "c0\n", "docs/d.txt": "d0\n"},
    )
    _commit_in_clone(ctx["clones"]["m0"], "docs/s.txt", "m0a\n", "m0 v1")
    _commit_in_clone(ctx["clones"]["m1"], "docs/c.txt", "c1\n", "m1 v1")
    _pass_module(ctx, 1, "m0", "done-m0v1", now=_t(10))
    _pass_module(ctx, 2, "m1", "done-m1v1", now=_t(20))
    assert ctx["worker"].reconcile_once(now=_t(30))["board_integrations_integrated"] == 1

    _commit_in_clone(ctx["clones"]["m0"], "docs/s.txt", "m0b\n", "m0 v2")
    _commit_in_clone(ctx["clones"]["m1"], "docs/s.txt", "m1x\n", "m1 v2a")
    _commit_in_clone(ctx["clones"]["m1"], "docs/c.txt", "c2\n", "m1 v2b")
    _commit_in_clone(ctx["clones"]["m2"], "docs/d.txt", "d2\n", "m2 v1")
    _pass_module(ctx, 1, "m0", "done-m0v2", now=_t(40))
    _pass_module(ctx, 2, "m1", "done-m1v2", now=_t(50))
    _pass_module(ctx, 3, "m2", "done-m2v1", now=_t(60))
    assert ctx["worker"].reconcile_once(now=_t(70))["board_integrations_integrated"] == 1
    job = _latest_job(ctx)
    by_module = {item["module_id"]: item for item in job["items"]}
    assert by_module["m0"]["status"] == "applied"
    assert by_module["m1"]["status"] == "fell_back"
    assert by_module["m2"]["status"] == "waiting"
    assert by_module["m2"]["reason_code"] == "board_integration_waiting_for_dependency"
    assert by_module["m2"]["applied_verification_id"] is None
    tree = _mirror_tree(ctx, _mirror_ref(ctx))
    assert tree["docs/s.txt"] == "m0b\n"
    assert tree["docs/c.txt"] == "c1\n"
    # m2's own patch never entered the result: the set stays closed.
    assert tree["docs/d.txt"] == "d0\n"
    payload = _integration_activity(ctx)["payload"]
    assert payload["waiting_module_ids"] == ["m2"]
    assert sorted(payload["integrated_module_ids"]) == ["m0", "m1"]


# ---------------------------------------------------------------------------
# rule 6: gate failure keeps the branch and marks the newcomer batch
# ---------------------------------------------------------------------------


def test_gate_failure_keeps_branch_and_marks_newcomers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def failing_gate(layout: Any, gate_id: str, **kw: Any) -> GateResult:
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

    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-gatefail",
        specs=[
            {"id": "m1", "paths": ["docs/a.txt"]},
            {"id": "m2", "paths": ["docs/b.txt"]},
        ],
        files={"docs/a.txt": "a0\n", "docs/b.txt": "b0\n"},
        gate=failing_gate,
    )
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _commit_in_clone(ctx["clones"]["m2"], "docs/b.txt", "b1\n", "m2 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    _pass_module(ctx, 2, "m2", "done-m2v1", now=_t(20))
    result = ctx["worker"].reconcile_once(now=_t(30))

    assert result["board_integrations_gate_failed"] == 1
    job = _latest_job(ctx)
    assert job["status"] == "gate_failed"
    assert job["reason_code"] == "board_integration_gate_failed"
    assert job["result_commit"] is None
    assert _mirror_ref(ctx) is None
    stored = ctx["store"].get_board_integration(job["integration_id"])
    assert stored is not None
    gates = stored["gates"]["gates"]
    assert gates and all(item["status"] == "failed" for item in gates)
    tails = stored["gates"]["evidence"]["output_tails"]
    assert tails == {"patch_diff_check": "E   AssertionError: expected Hello, Ada!"}
    activity = _integration_activity(ctx)
    payload = activity["payload"]
    assert payload["suspect_module_ids"] == ["m1", "m2"]
    assert payload["gate_ids"] == ["patch_diff_check"]
    assert payload["green_head_commit"] is None
    lead = ctx["members"][0]
    assert _observations_for(ctx["db"], lead.participant_id, activity["activity_id"])
    for member in ctx["members"][1:]:
        assert not _observations_for(ctx["db"], member.participant_id, activity["activity_id"])

    # A newer candidate enqueues a fresh job; with passing gates it moves.
    monkeypatch.setattr(integration, "run_gate", _passing_gate)
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a2\n", "m1 v2")
    _pass_module(ctx, 1, "m1", "done-m1v2", now=_t(35))
    assert ctx["worker"].reconcile_once(now=_t(40))["board_integrations_integrated"] == 1
    assert _mirror_ref(ctx) is not None


def test_gate_failure_incumbent_stays_integrated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-gatefail2",
        specs=[
            {"id": "m1", "paths": ["docs/a.txt"]},
            {"id": "m2", "paths": ["docs/b.txt"]},
        ],
        files={"docs/a.txt": "a0\n", "docs/b.txt": "b0\n"},
    )
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    assert ctx["worker"].reconcile_once(now=_t(20))["board_integrations_integrated"] == 1
    green1 = _mirror_ref(ctx)

    def failing_gate(layout: Any, gate_id: str, **kw: Any) -> GateResult:
        return GateResult(gate_id, "failed", "execution_gate_failed", DIGEST_A, DIGEST_A, 1, 1)

    monkeypatch.setattr(integration, "run_gate", failing_gate)
    _commit_in_clone(ctx["clones"]["m2"], "docs/b.txt", "b1\n", "m2 v1")
    _pass_module(ctx, 2, "m2", "done-m2v1", now=_t(30))
    assert ctx["worker"].reconcile_once(now=_t(40))["board_integrations_gate_failed"] == 1
    job = _latest_job(ctx)
    by_module = {item["module_id"]: item for item in job["items"]}
    assert by_module["m1"]["status"] == "applied"
    assert by_module["m1"]["applied_verification_id"] == by_module["m1"]["verification_id"]
    assert _mirror_ref(ctx) == green1
    payload = _integration_activity(ctx)["payload"]
    assert payload["suspect_module_ids"] == ["m2"]
    assert payload["integrated_module_ids"] == ["m1"]


# ---------------------------------------------------------------------------
# rule 7: last resort never moves the branch and runs no gates
# ---------------------------------------------------------------------------


def test_rule7_conflicted_without_gates_or_branch_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate_calls: list[str] = []

    def counting_gate(layout: Any, gate_id: str, **kw: Any) -> GateResult:
        gate_calls.append(gate_id)
        return _passing_gate(layout, gate_id, **kw)

    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-rule7",
        specs=[
            {"id": "m2", "paths": ["docs/a.txt"]},
            {"id": "n1", "paths": ["docs/b.txt"]},
        ],
        files={"docs/a.txt": "a0\n", "docs/b.txt": "b0\n"},
        gate=counting_gate,
    )
    _commit_in_clone(ctx["clones"]["m2"], "docs/a.txt", "m2a\n", "m2 v1")
    _pass_module(ctx, 1, "m2", "done-m2v1", now=_t(10))
    assert ctx["worker"].reconcile_once(now=_t(20))["board_integrations_integrated"] == 1
    green1 = _mirror_ref(ctx)
    gate_calls.clear()

    _commit_in_clone(ctx["clones"]["n1"], "docs/b.txt", "n1b\n", "n1 v1")
    _pass_module(ctx, 2, "n1", "done-n1v1", now=_t(30))

    real_try_apply = integration.RoomBoardIntegrationEngine._try_apply

    def fail_incumbent(self: Any, stage: Path, patch_text: str) -> list[str] | None:
        if "+m2a" in patch_text:
            return ["docs/a.txt"]
        return real_try_apply(self, stage, patch_text)

    monkeypatch.setattr(integration.RoomBoardIntegrationEngine, "_try_apply", fail_incumbent)
    result = ctx["worker"].reconcile_once(now=_t(40))

    assert result["board_integrations_conflicted"] == 1
    assert gate_calls == []
    job = _latest_job(ctx)
    assert job["status"] == "conflicted"
    assert job["reason_code"] == "board_integration_would_drop_accepted"
    assert job["result_commit"] is None
    assert _mirror_ref(ctx) == green1
    by_module = {item["module_id"]: item for item in job["items"]}
    assert by_module["m2"]["status"] == "conflicted"
    assert by_module["m2"]["reason_code"] == "board_integration_would_drop_accepted"
    assert by_module["m2"]["applied_verification_id"] is None
    assert by_module["m2"]["conflicts"] == [{"path": "docs/a.txt", "attributed_module_ids": ["m2"]}]
    activity = _integration_activity(ctx)
    payload = activity["payload"]
    assert payload["reason_code"] == "board_integration_would_drop_accepted"
    assert payload["conflicts"] == [
        {
            "module_id": "m2",
            "conflict_path_count": 1,
            "attributed_module_ids": ["m2"],
            "fell_back": False,
        }
    ]
    # The conflicted module's owner and the lead are woken; others are not.
    assert _observations_for(ctx["db"], ctx["members"][1].participant_id, activity["activity_id"])
    assert _observations_for(ctx["db"], ctx["members"][0].participant_id, activity["activity_id"])
    assert not _observations_for(
        ctx["db"], ctx["members"][2].participant_id, activity["activity_id"]
    )


# ---------------------------------------------------------------------------
# enqueue rules, leases, retries
# ---------------------------------------------------------------------------


def test_enqueue_only_on_set_change_and_one_pending_behind_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-enqueue",
        specs=[{"id": "m1", "paths": ["docs/a.txt"]}],
        files={"docs/a.txt": "a0\n"},
    )
    store = ctx["store"]
    assert store.ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(5)) is None
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    first = store.ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(11))
    assert first is not None
    assert store.ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(12)) is None
    claimed = store.claim_next_board_integration(worker_id="w1", now=_t(13))
    assert claimed is not None and claimed["integration_id"] == first
    # Same set while running: nothing new.
    assert store.ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(14)) is None
    # A set change during the running job enqueues the next one.
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a2\n", "m1 v2")
    _pass_module(ctx, 1, "m1", "done-m1v2", now=_t(15))
    second = store.ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(16))
    assert second is not None and second != first
    assert store.ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(17)) is None
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        statuses = {
            row["integration_id"]: row["status"]
            for row in conn.execute("select * from room_board_integrations")
        }
    assert statuses == {first: "running", second: "pending"}


def test_idempotent_reclaim_after_lost_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-lease",
        specs=[{"id": "m1", "paths": ["docs/a.txt"]}],
        files={"docs/a.txt": "a0\n"},
    )
    store = ctx["store"]
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    first = store.ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(11))
    assert first is not None
    claimed = store.claim_next_board_integration(worker_id="w1", lease_ttl_s=60, now=_t(20))
    assert claimed is not None
    assert claimed["attempt_count"] == 1
    old_token = claimed["lease_token"]
    # After the lease lapses the same job is re-claimed with a fresh token.
    reclaimed = store.claim_next_board_integration(worker_id="w1", lease_ttl_s=60, now=_t(200))
    assert reclaimed is not None
    assert reclaimed["integration_id"] == first
    assert reclaimed["attempt_count"] == 2
    assert reclaimed["lease_token"] != old_token
    with pytest.raises(ValueError, match="room_board_integration_lease_lost"):
        store.complete_board_integration(
            integration_id=first,
            lease_token=old_token,
            status="integrated",
            reason_code=None,
            green_after="d" * 40,
            result_commit="d" * 40,
            gates=[],
            evidence={},
            items=[
                {
                    "module_id": "m1",
                    "status": "applied",
                    "applied_verification_id": reclaimed["items"][0]["verification_id"],
                    "conflicts": [],
                    "conflicts_total": 0,
                    "reason_code": None,
                }
            ],
            now=_t(210),
        )


def test_transient_failures_retry_then_error_with_bounded_reruns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-retry",
        specs=[{"id": "m1", "paths": ["docs/a.txt"]}],
        files={"docs/a.txt": "a0\n"},
    )
    monkeypatch.setattr(
        integration.RoomBoardIntegrationEngine,
        "run_job",
        lambda self, **kw: (_ for _ in ()).throw(
            integration.BoardIntegrationTransientError("execution_repo_busy")
        ),
    )
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))

    def drain(worker: Any, now: datetime, ticks: int) -> dict[str, int]:
        total: dict[str, int] = {}
        for _ in range(ticks):
            for key, value in worker.reconcile_once(now=now).items():
                total[key] = total.get(key, 0) + value
        return total

    worker = ctx["worker"]
    # Three attempts, then the fourth tick marks the job error.
    first = drain(worker, _t(20), 3)
    assert first["board_integrations_abandoned"] == 3
    assert _latest_job(ctx)["status"] == "pending"
    done = drain(worker, _t(21), 1)
    assert done["board_integrations_claimed"] == 0
    job = _latest_job(ctx)
    assert job["status"] == "error"
    assert job["reason_code"] == "board_integration_attempts_exhausted"
    activity = _integration_activity(ctx)
    assert activity["payload"]["status"] == "error"
    assert activity["payload"]["reason_code"] == "board_integration_attempts_exhausted"
    for member in ctx["members"]:
        assert not _observations_for(ctx["db"], member.participant_id, activity["activity_id"])

    # Too early for the first automatic re-run (delay 60s).
    assert drain(worker, _t(80), 1)["board_integrations_retried"] == 0
    assert _latest_job(ctx)["status"] == "error"
    # After 10 injected minutes the same set re-runs, then errors again.
    assert drain(worker, _t(81), 1)["board_integrations_retried"] == 1
    assert _latest_job(ctx)["status"] == "pending"
    drain(worker, _t(82), 2)
    assert _latest_job(ctx)["status"] == "pending"
    drain(worker, _t(83), 1)
    assert _latest_job(ctx)["status"] == "error"
    # After 30 more injected minutes the second re-run fires, then errors.
    assert drain(worker, _t(202), 1)["board_integrations_retried"] == 0
    assert drain(worker, _t(203), 1)["board_integrations_retried"] == 1
    drain(worker, _t(204), 3)
    assert _latest_job(ctx)["status"] == "error"
    # A host restart grants exactly one more run, then the job stays error.
    worker2 = integration.RoomBoardIntegrationWorker(
        db_path=ctx["db"],
        clones_root=ctx["clones_root"],
        xmuse_root=ctx["home"],
        execution_root=ctx["source"],
        execution_profile_id="docs/v1",
        auto_retry_delays_s=(60.0, 120.0),
    )
    assert drain(worker2, _t(300), 1)["board_integrations_retried"] == 1
    drain(worker2, _t(301), 4)
    assert _latest_job(ctx)["status"] == "error"
    worker3 = integration.RoomBoardIntegrationWorker(
        db_path=ctx["db"],
        clones_root=ctx["clones_root"],
        xmuse_root=ctx["home"],
        execution_root=ctx["source"],
        execution_profile_id="docs/v1",
        auto_retry_delays_s=(60.0, 120.0),
    )
    assert drain(worker3, _t(400), 2)["board_integrations_retried"] == 0
    assert _latest_job(ctx)["status"] == "error"
    # Until the set changes, which enqueues a fresh job.
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a2\n", "m1 v2")
    _pass_module(ctx, 1, "m1", "done-m1v2", now=_t(410))
    assert (
        ctx["store"].ensure_board_integration_enqueued(ctx["conversation_id"], now=_t(411))
        is not None
    )


# ---------------------------------------------------------------------------
# reviews gate the input set; equal sets run nothing twice
# ---------------------------------------------------------------------------


def test_review_endorsement_gates_candidacy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-reviews",
        specs=[{"id": "m1", "paths": ["docs/a.txt"]}],
        files={"docs/a.txt": "a0\n"},
        review_policy="cross_family",
    )
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    passed = _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    # Passed but not yet endorsed: no candidate, no job.
    assert ctx["worker"].reconcile_once(now=_t(20))["board_integrations_enqueued"] == 0
    assert _job_count(ctx) == 0
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        review = conn.execute(
            "select * from room_board_reviews where verification_id = ?",
            (passed["verification_id"],),
        ).fetchone()
    assert review is not None and review["reviewer_kind"] == "operator"
    digest = review_digest(
        review_id=str(review["review_id"]),
        verification_id=passed["verification_id"],
        head_commit=passed["head_commit"],
        patch_text=_patch_text(ctx, passed["verification_id"]),
    )
    ctx["store"].decide_review(
        conversation_id=ctx["conversation_id"],
        review_id=str(review["review_id"]),
        verdict="endorse",
        summary="looks good",
        findings=[],
        expected_digest=digest,
        operator_identity="operator:host",
        decided_via="web",
        now=_t(25),
    )
    assert ctx["worker"].reconcile_once(now=_t(30))["board_integrations_integrated"] == 1
    assert _mirror_ref(ctx) is not None


def _patch_text(ctx: dict[str, Any], verification_id: str) -> str:
    with RoomDatabase(ctx["db"]).connect(readonly=True) as conn:
        row = conn.execute(
            "select patch_text from room_board_verifications where verification_id = ?",
            (verification_id,),
        ).fetchone()
    assert row is not None
    return str(row["patch_text"])


def test_equal_set_runs_no_gates_and_enqueues_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    gate_calls: list[str] = []

    def counting_gate(layout: Any, gate_id: str, **kw: Any) -> GateResult:
        gate_calls.append(gate_id)
        return _passing_gate(layout, gate_id, **kw)

    ctx = _room(
        tmp_path,
        monkeypatch,
        name="home-nogates",
        specs=[{"id": "m1", "paths": ["docs/a.txt"]}],
        files={"docs/a.txt": "a0\n"},
        gate=counting_gate,
    )
    _commit_in_clone(ctx["clones"]["m1"], "docs/a.txt", "a1\n", "m1 v1")
    _pass_module(ctx, 1, "m1", "done-m1v1", now=_t(10))
    assert ctx["worker"].reconcile_once(now=_t(20))["board_integrations_integrated"] == 1
    assert gate_calls == ["patch_diff_check"]
    assert _job_count(ctx) == 1
    # Nothing changed: no new job, no new gates.
    assert ctx["worker"].reconcile_once(now=_t(30))["board_integrations_claimed"] == 0
    assert _job_count(ctx) == 1
    assert gate_calls == ["patch_diff_check"]
