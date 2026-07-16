from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.xmuse.test_room_participant_outcomes import root_and_claims, submit
from xmuse_core.chat import room_execution_controller as controller
from xmuse_core.chat.room_execution_controller import (
    ControllerConfig,
    RoomExecutionControllerError,
    build_workspace_guard,
    repository_execution_lock,
    run_execution_controller,
    stage_exact_patch,
)
from xmuse_core.chat.room_execution_controller_store import RoomExecutionControllerStore
from xmuse_core.chat.room_execution_profiles import (
    build_execution_gate_plan,
    get_execution_gate_profile,
)
from xmuse_core.chat.room_execution_sandbox import (
    SANDBOX_ACTIVE_ENV,
    GateResult,
    GateSpec,
    build_repository_manifest_digest,
    build_toolchain_capability_digest,
    discover_sandbox_layout,
    run_gate,
)
from xmuse_core.chat.room_execution_store import RoomExecutionStore
from xmuse_core.chat.room_runtime import read_process_start_identity


def _controller_store(config: ControllerConfig) -> RoomExecutionControllerStore:
    return RoomExecutionControllerStore(config.xmuse_root / "chat.db")


def test_controller_store_withholds_operator_and_room_delivery_capabilities(
    tmp_path: Path,
) -> None:
    store = RoomExecutionControllerStore(tmp_path / "chat.db")

    assert not hasattr(store, "set_policy")
    assert not hasattr(store, "apply_operator_decision")
    assert not hasattr(store, "reconcile_consensus_candidate")
    assert not hasattr(store, "request_cancel")
    assert not hasattr(store, "get_review_material_for_batch")
    assert not hasattr(store, "bind_review_material_receipt")


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _repo(tmp_path: Path, *, two_files: bool = False, python_profile: bool = False) -> Path:
    repo = tmp_path / "target"
    repo.mkdir(parents=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "test@example.invalid")
    _git(repo, "config", "user.name", "Test")
    (repo / ".gitignore").write_text(".venv\n", encoding="utf-8")
    (repo / "README.md").write_text("old\n", encoding="utf-8")
    if two_files:
        (repo / "CHANGELOG.md").write_text("before\n", encoding="utf-8")
    if python_profile:
        (repo / "src").mkdir()
        (repo / "src" / "example.py").write_text("VALUE = 1\n", encoding="utf-8")
        (repo / "pyproject.toml").write_text(
            "[project]\nname='acceptance'\nversion='0.0.0'\n", encoding="utf-8"
        )
        (repo / "uv.lock").write_text(
            "version = 1\n\n[[package]]\nname = 'acceptance'\n"
            "version = '0.0.0'\nsource = { editable = '.' }\n",
            encoding="utf-8",
        )
    current_repo = Path(__file__).resolve().parents[2]
    os.symlink(current_repo / ".venv", repo / ".venv", target_is_directory=True)
    additions = [".gitignore", "README.md"]
    if two_files:
        additions.append("CHANGELOG.md")
    if python_profile:
        additions.extend(("src/example.py", "pyproject.toml", "uv.lock"))
    _git(repo, "add", *additions)
    _git(repo, "commit", "-qm", "base")
    return repo


def _patch(
    repo: Path, *, two_files: bool = False, python_profile: bool = False
) -> tuple[str, tuple[str, ...]]:
    if python_profile:
        path = "src/example.py"
        (repo / path).write_text("VALUE = 2\n", encoding="utf-8")
        diff = _git(repo, "diff", "--", path) + "\n"
        _git(repo, "restore", "--worktree", "--", path)
        return diff, (path,)
    (repo / "README.md").write_text("new\n", encoding="utf-8")
    paths = ["README.md"]
    if two_files:
        (repo / "CHANGELOG.md").write_text("after\n", encoding="utf-8")
        paths.append("CHANGELOG.md")
    diff = _git(repo, "diff", "--", *paths) + "\n"
    _git(repo, "restore", "--worktree", "--", *paths)
    return diff, tuple(sorted(paths))


def _authorized(
    tmp_path: Path,
    *,
    two_files: bool = False,
    python_profile: bool = False,
    consensus_policy: bool = False,
) -> tuple[RoomExecutionStore, ControllerConfig, dict[str, object], str]:
    repo = _repo(tmp_path, two_files=two_files, python_profile=python_profile)
    diff, allowed = _patch(repo, two_files=two_files, python_profile=python_profile)
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    db, registry, conversation_id, records, _, claims = root_and_claims(runtime)
    if consensus_policy:
        policy_store = RoomExecutionStore(db)
        policy_store.set_policy(
            conversation_id=conversation_id,
            mode="consensus",
            client_action_id="enable-consensus",
            operator_identity="operator",
            expected_revision=0,
        )
    payload = {
        "proposal_type": "execution_patch",
        "content": "candidate",
        "references": [],
        "execution_patch": {
            "schema_version": "room_execution_patch/v1",
            "base_head": _git(repo, "rev-parse", "HEAD"),
            "summary": "Update documentation",
            "unified_diff": diff,
            "allowed_files": list(allowed),
        },
    }
    author, session = records[0]
    outcome = submit(
        db,
        registry,
        conversation_id,
        author,
        session,
        claims[author.participant_id],
        "execution-candidate",
        outcome_type="propose",
        outcome_payload=payload,
    )
    store = RoomExecutionStore(db)
    candidate_id = outcome["execution_candidate"]["candidate_id"]
    candidate = store.get_candidate(candidate_id, include_patch=True)
    assert candidate is not None
    guard = build_workspace_guard(
        repo,
        SimpleNamespace(
            base_head=candidate["base_head"],
            allowed_files=tuple(candidate["allowed_files"]),
        ),
    )
    policy = store.get_policy(conversation_id)
    assert policy is not None
    profile = get_execution_gate_profile("python-uv/v1" if python_profile else "docs/v1")
    gate_plan = build_execution_gate_plan(
        profile_id=profile.profile_id,
        changed_paths=allowed,
        repository_manifest_digest=build_repository_manifest_digest(repo, profile),
        toolchain_capability_digest=build_toolchain_capability_digest(
            repo, profile, gate_ids=profile.gate_ids
        ),
    )
    decision = store.apply_operator_decision(
        candidate_id=candidate_id,
        decision="execute",
        client_action_id="execute-1",
        operator_identity="operator",
        expected_candidate_digest=candidate["candidate_digest"],
        expected_candidate_revision=candidate["revision"],
        expected_policy_revision=policy["revision"],
        workspace_guard=guard,
        gate_plan=gate_plan,
    )
    run_id = decision["run"]["run_id"]
    pid = os.getpid()
    identity = read_process_start_identity(pid)
    assert identity is not None
    config = ControllerConfig(
        xmuse_root=runtime,
        execution_root=repo,
        run_id=run_id,
        controller_id="execution_controller_test",
        controller_generation="test-generation",
        controller_pid=pid,
        controller_start_identity=identity,
    )
    return store, config, candidate, diff


def _passing_gate(gate_id: str) -> GateResult:
    digest = "sha256:" + hashlib.sha256(gate_id.encode()).hexdigest()
    return GateResult(gate_id, "passed", None, digest, digest, 0, 1)


def _advance_to_ready_with_passed_gates(
    store: RoomExecutionStore,
    config: ControllerConfig,
    material: dict[str, object],
) -> dict[str, object]:
    generation = int(material["execution_generation"])
    identity = {
        "controller_id": config.controller_id,
        "controller_generation": config.controller_generation,
        "controller_pid": config.controller_pid,
        "controller_start_identity": config.controller_start_identity,
    }
    for target in ("staging", "verifying"):
        material = store.advance_run(
            run_id=config.run_id,
            expected_state=str(material["state"]),
            expected_revision=int(material["revision"]),
            execution_generation=generation,
            **identity,
            target_state=target,
        )
    gate_plan = material["gate_plan"]
    assert isinstance(gate_plan, dict)
    for gate_id in gate_plan["gate_ids"]:
        assert isinstance(gate_id, str)
        digest = "sha256:" + hashlib.sha256(gate_id.encode()).hexdigest()
        material = store.record_gate_evidence(
            run_id=config.run_id,
            expected_run_state="verifying",
            expected_run_revision=int(material["revision"]),
            execution_generation=generation,
            **identity,
            gate_id=gate_id,
            status="running",
            evidence_digest=digest,
            started_at="2026-07-12T00:00:00Z",
        )
        material = store.record_gate_evidence(
            run_id=config.run_id,
            expected_run_state="verifying",
            expected_run_revision=int(material["revision"]),
            execution_generation=generation,
            **identity,
            gate_id=gate_id,
            status="passed",
            evidence_digest=digest,
            started_at="2026-07-12T00:00:00Z",
            finished_at="2026-07-12T00:00:01Z",
        )
    return store.advance_run(
        run_id=config.run_id,
        expected_state="verifying",
        expected_revision=int(material["revision"]),
        execution_generation=generation,
        **identity,
        target_state="ready_to_promote",
    )


def test_real_store_manual_run_promotes_exact_patch_with_real_bwrap(tmp_path: Path) -> None:
    if os.environ.get(SANDBOX_ACTIVE_ENV) == "1":
        pytest.skip("nested user namespaces are disabled by the outer execution sandbox")
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap unavailable")
    store, config, candidate, _diff = _authorized(tmp_path)
    with sqlite3.connect(config.xmuse_root / "chat.db") as conn:
        conn.execute(
            """insert into participants (
                   participant_id, conversation_id, role, display_name, cli_kind, model,
                   status, created_at
               ) values ('part_historical_a2a', ?, 'review', 'Historical A2A',
                         'a2a', 'historical', 'active', '2026-07-12T00:00:00Z')""",
            (candidate["conversation_id"],),
        )

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "succeeded"
    assert (config.execution_root / "README.md").read_text() == "new\n"
    assert _git(config.execution_root, "diff", "--name-only") == "README.md"
    assert _git(config.execution_root, "diff", "--cached", "--name-only") == ""
    durable = store.get_run(config.run_id)
    assert durable is not None
    assert durable["promotion_journal"]["status"] == "applied"
    assert durable["gate_ids"] == ["patch_diff_check"]
    with sqlite3.connect(config.xmuse_root / "chat.db") as conn:
        assert (
            conn.execute(
                "select count(*) from room_observations where participant_id = ?",
                ("part_historical_a2a",),
            ).fetchone()[0]
            == 0
        )


def test_consensus_room_manual_fallback_uses_frozen_room_policy(tmp_path: Path) -> None:
    if os.environ.get(SANDBOX_ACTIVE_ENV) == "1":
        pytest.skip("nested user namespaces are disabled by the outer execution sandbox")
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap unavailable")
    store, config, candidate, _diff = _authorized(tmp_path, consensus_policy=True)
    assert candidate["policy_snapshot"]["mode"] == "consensus"

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "succeeded"
    assert (config.execution_root / "README.md").read_text() == "new\n"


def test_gate_failure_leaves_target_bytes_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, config, _candidate, _diff = _authorized(tmp_path)
    digest = "sha256:" + "f" * 64
    monkeypatch.setattr(controller, "probe_sandbox_capability", lambda _layout, **_kwargs: digest)
    monkeypatch.setattr(controller, "discover_sandbox_layout", lambda **_kwargs: object())
    monkeypatch.setattr(
        controller,
        "run_gate",
        lambda *_args, **_kwargs: GateResult(
            "patch_diff_check",
            "failed",
            "execution_gate_failed",
            digest,
            digest,
            1,
            1,
        ),
    )

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "failed"
    assert (config.execution_root / "README.md").read_text() == "old\n"
    assert _git(config.execution_root, "status", "--porcelain") == ""


def test_cancel_during_gate_is_durable_and_target_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, config, _candidate, _diff = _authorized(tmp_path)
    digest = "sha256:" + "c" * 64
    monkeypatch.setattr(controller, "probe_sandbox_capability", lambda _layout, **_kwargs: digest)
    monkeypatch.setattr(controller, "discover_sandbox_layout", lambda **_kwargs: object())

    def cancel_gate(*_args, **_kwargs):
        current = store.get_run(config.run_id)
        assert current is not None and current["state"] == "verifying"
        store.request_cancel(
            run_id=config.run_id,
            client_action_id="cancel-1",
            operator_identity="operator",
            expected_state="verifying",
            expected_revision=current["revision"],
        )
        return GateResult(
            "patch_diff_check",
            "cancelled",
            "execution_cancelled",
            digest,
            digest,
            -15,
            1,
        )

    monkeypatch.setattr(controller, "run_gate", cancel_gate)

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "cancelled"
    assert (config.execution_root / "README.md").read_text() == "old\n"
    assert _git(config.execution_root, "status", "--porcelain") == ""


def test_cancel_before_controller_claim_is_terminal_and_never_touches_target(
    tmp_path: Path,
) -> None:
    store, config, _candidate, _diff = _authorized(tmp_path)
    run = store.get_run(config.run_id)
    assert run is not None and run["state"] == "requested"

    cancelled = store.request_cancel(
        run_id=config.run_id,
        client_action_id="cancel-before-claim",
        operator_identity="operator",
        expected_state="requested",
        expected_revision=run["revision"],
    )

    assert cancelled["state"] == "cancelled"
    assert cancelled["reason_code"] == "operator_cancelled_before_start"
    assert (config.execution_root / "README.md").read_text() == "old\n"
    assert run_execution_controller(_controller_store(config), config)["state"] == "cancelled"
    assert _git(config.execution_root, "status", "--porcelain") == ""


@pytest.mark.parametrize("journal_state", ["prepared", "applying"])
def test_preimage_crash_recovery_finishes_exact_promotion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    journal_state: str,
) -> None:
    store, config, candidate_payload, _diff = _authorized(tmp_path)
    material = store.claim_requested_run(
        run_id=config.run_id,
        controller_id=config.controller_id,
        controller_generation=config.controller_generation,
        controller_pid=config.controller_pid,
        controller_start_identity=config.controller_start_identity,
    )
    generation = material["execution_generation"]
    material = _advance_to_ready_with_passed_gates(store, config, material)
    exact = controller.candidate_from_mapping(candidate_payload)
    exact = controller.replace(
        exact,
        workspace_guard_digest=material["authorization"]["workspace_guard_digest"],
    )
    with stage_exact_patch(
        xmuse_root=config.xmuse_root,
        execution_root=config.execution_root,
        run_id=config.run_id,
        candidate=exact,
    ) as staged:
        material = store.prepare_promotion(
            run_id=config.run_id,
            expected_revision=material["revision"],
            execution_generation=generation,
            controller_id=config.controller_id,
            controller_generation=config.controller_generation,
            controller_pid=config.controller_pid,
            controller_start_identity=config.controller_start_identity,
            target_head=exact.base_head,
            pre_manifest_digest=staged.pre_manifest_digest,
            post_manifest_digest=staged.post_manifest_digest,
            file_entries=[entry.store_payload() for entry in staged.entries],
        )
        if journal_state == "applying":
            material = store.mark_promotion_applying(
                run_id=config.run_id,
                expected_revision=material["revision"],
                execution_generation=generation,
                controller_id=config.controller_id,
                controller_generation=config.controller_generation,
                controller_pid=config.controller_pid,
                controller_start_identity=config.controller_start_identity,
            )
    monkeypatch.setattr(
        controller,
        "probe_sandbox_capability",
        lambda _layout, **_kwargs: "unused",
    )

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "succeeded"
    assert (config.execution_root / "README.md").read_text() == "new\n"


@pytest.mark.parametrize("journal_state", ["prepared", "applying"])
@pytest.mark.parametrize("drift_kind", ["manifest", "policy", "plan", "profile"])
def test_preimage_recovery_blocks_durable_profile_drift_before_write(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    journal_state: str,
    drift_kind: str,
) -> None:
    store, config, candidate_payload, _diff = _authorized(tmp_path)
    material = store.claim_requested_run(
        run_id=config.run_id,
        controller_id=config.controller_id,
        controller_generation=config.controller_generation,
        controller_pid=config.controller_pid,
        controller_start_identity=config.controller_start_identity,
    )
    generation = int(material["execution_generation"])
    material = _advance_to_ready_with_passed_gates(store, config, material)
    exact = controller.replace(
        controller.candidate_from_mapping(candidate_payload),
        workspace_guard_digest=material["authorization"]["workspace_guard_digest"],
    )
    with stage_exact_patch(
        xmuse_root=config.xmuse_root,
        execution_root=config.execution_root,
        run_id=config.run_id,
        candidate=exact,
    ) as staged:
        material = store.prepare_promotion(
            run_id=config.run_id,
            expected_revision=material["revision"],
            execution_generation=generation,
            controller_id=config.controller_id,
            controller_generation=config.controller_generation,
            controller_pid=config.controller_pid,
            controller_start_identity=config.controller_start_identity,
            target_head=exact.base_head,
            pre_manifest_digest=staged.pre_manifest_digest,
            post_manifest_digest=staged.post_manifest_digest,
            file_entries=[entry.store_payload() for entry in staged.entries],
        )
        if journal_state == "applying":
            store.mark_promotion_applying(
                run_id=config.run_id,
                expected_revision=material["revision"],
                execution_generation=generation,
                controller_id=config.controller_id,
                controller_generation=config.controller_generation,
                controller_pid=config.controller_pid,
                controller_start_identity=config.controller_start_identity,
            )
    expected_reason = "execution_repository_manifest_drift"
    if drift_kind == "manifest":
        monkeypatch.setattr(
            controller,
            "build_repository_manifest_digest",
            lambda *_args, **_kwargs: "sha256:" + "0" * 64,
        )
    elif drift_kind == "policy":
        conversation_id = str(material["conversation_id"])
        with sqlite3.connect(config.xmuse_root / "chat.db") as conn:
            conn.execute(
                "update room_execution_policies set mode = 'consensus', "
                "revision = revision + 1 where conversation_id = ?",
                (conversation_id,),
            )
        expected_reason = "execution_policy_guard_changed"
    elif drift_kind == "plan":
        monkeypatch.setattr(
            controller,
            "_gate_plan_from_material",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RoomExecutionControllerError("execution_gate_plan_invalid")
            ),
        )
        expected_reason = "execution_gate_plan_invalid"
    else:
        monkeypatch.setattr(
            controller,
            "get_execution_gate_profile",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                controller.RoomExecutionProfileError("room_execution_gate_profile_unknown")
            ),
        )
        expected_reason = "execution_gate_profile_drift"

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "blocked"
    assert result["reason_code"] == expected_reason
    assert (config.execution_root / "README.md").read_text() == "old\n"
    assert _git(config.execution_root, "status", "--porcelain") == ""


def test_applied_multi_gate_recovery_preserves_durable_plan_order(tmp_path: Path) -> None:
    if os.environ.get(SANDBOX_ACTIVE_ENV) == "1":
        pytest.skip("outer sandbox intentionally does not expose a workspace .venv")
    store, config, candidate_payload, _diff = _authorized(tmp_path, python_profile=True)
    material = store.claim_requested_run(
        run_id=config.run_id,
        controller_id=config.controller_id,
        controller_generation=config.controller_generation,
        controller_pid=config.controller_pid,
        controller_start_identity=config.controller_start_identity,
    )
    generation = int(material["execution_generation"])
    material = _advance_to_ready_with_passed_gates(store, config, material)
    exact = controller.replace(
        controller.candidate_from_mapping(candidate_payload),
        workspace_guard_digest=material["authorization"]["workspace_guard_digest"],
    )
    with stage_exact_patch(
        xmuse_root=config.xmuse_root,
        execution_root=config.execution_root,
        run_id=config.run_id,
        candidate=exact,
    ) as staged:
        prepared = store.prepare_promotion(
            run_id=config.run_id,
            expected_revision=material["revision"],
            execution_generation=generation,
            controller_id=config.controller_id,
            controller_generation=config.controller_generation,
            controller_pid=config.controller_pid,
            controller_start_identity=config.controller_start_identity,
            target_head=exact.base_head,
            pre_manifest_digest=staged.pre_manifest_digest,
            post_manifest_digest=staged.post_manifest_digest,
            file_entries=[entry.store_payload() for entry in staged.entries],
        )
        applying = store.mark_promotion_applying(
            run_id=config.run_id,
            expected_revision=prepared["revision"],
            execution_generation=generation,
            controller_id=config.controller_id,
            controller_generation=config.controller_generation,
            controller_pid=config.controller_pid,
            controller_start_identity=config.controller_start_identity,
        )
        observed = controller.promote_exact_patch(
            execution_root=config.execution_root,
            candidate=exact,
            staged=staged,
        )
        resolved = store.resolve_promotion(
            run_id=config.run_id,
            expected_revision=applying["revision"],
            execution_generation=generation,
            controller_id=config.controller_id,
            controller_generation=config.controller_generation,
            controller_pid=config.controller_pid,
            controller_start_identity=config.controller_start_identity,
            observed_manifest_digest=observed,
        )
        assert resolved["resolution"] == "applied"

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "succeeded"
    assert result["gate_ids"] == [
        "patch_diff_check",
        "python_uv_ruff",
        "python_uv_mypy",
        "python_uv_pytest",
    ]
    assert (config.execution_root / "src" / "example.py").read_text() == "VALUE = 2\n"


def test_applying_mixed_image_is_blocked_without_guessed_rollback(tmp_path: Path) -> None:
    store, config, candidate_payload, _diff = _authorized(tmp_path, two_files=True)
    material = store.claim_requested_run(
        run_id=config.run_id,
        controller_id=config.controller_id,
        controller_generation=config.controller_generation,
        controller_pid=config.controller_pid,
        controller_start_identity=config.controller_start_identity,
    )
    generation = material["execution_generation"]
    material = _advance_to_ready_with_passed_gates(store, config, material)
    exact = controller.replace(
        controller.candidate_from_mapping(candidate_payload),
        workspace_guard_digest=material["authorization"]["workspace_guard_digest"],
    )
    with stage_exact_patch(
        xmuse_root=config.xmuse_root,
        execution_root=config.execution_root,
        run_id=config.run_id,
        candidate=exact,
    ) as staged:
        material = store.prepare_promotion(
            run_id=config.run_id,
            expected_revision=material["revision"],
            execution_generation=generation,
            controller_id=config.controller_id,
            controller_generation=config.controller_generation,
            controller_pid=config.controller_pid,
            controller_start_identity=config.controller_start_identity,
            target_head=exact.base_head,
            pre_manifest_digest=staged.pre_manifest_digest,
            post_manifest_digest=staged.post_manifest_digest,
            file_entries=[entry.store_payload() for entry in staged.entries],
        )
        store.mark_promotion_applying(
            run_id=config.run_id,
            expected_revision=material["revision"],
            execution_generation=generation,
            controller_id=config.controller_id,
            controller_generation=config.controller_generation,
            controller_pid=config.controller_pid,
            controller_start_identity=config.controller_start_identity,
        )
    (config.execution_root / "README.md").write_text("new\n", encoding="utf-8")

    result = run_execution_controller(_controller_store(config), config)

    assert result["state"] == "blocked"
    assert (config.execution_root / "README.md").read_text() == "new\n"
    assert (config.execution_root / "CHANGELOG.md").read_text() == "before\n"


def test_real_store_repo_lock_and_live_binding_prevent_duplicate_controller(
    tmp_path: Path,
) -> None:
    store, config, _candidate, _diff = _authorized(tmp_path)
    with repository_execution_lock(config.execution_root):
        with pytest.raises(RoomExecutionControllerError) as busy:
            run_execution_controller(_controller_store(config), config)
    assert busy.value.code == "execution_repo_busy"
    assert store.get_run(config.run_id)["state"] == "requested"  # type: ignore[index]

    store.claim_requested_run(
        run_id=config.run_id,
        controller_id=config.controller_id,
        controller_generation=config.controller_generation,
        controller_pid=config.controller_pid,
        controller_start_identity=config.controller_start_identity,
    )
    contender = replace(config, controller_id="execution_controller_contender")
    with pytest.raises(RoomExecutionControllerError) as live:
        run_execution_controller(_controller_store(contender), contender)
    assert live.value.code == "execution_controller_already_live"
    assert store.get_run(config.run_id)["state"] == "preparing"  # type: ignore[index]


def test_confirmed_dead_binding_uses_store_reclaim_generation_cas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, config, _candidate, _diff = _authorized(tmp_path)
    first = store.claim_requested_run(
        run_id=config.run_id,
        controller_id=config.controller_id,
        controller_generation=config.controller_generation,
        controller_pid=config.controller_pid,
        controller_start_identity=config.controller_start_identity,
    )
    contender = replace(
        config,
        controller_id="execution_controller_recovery",
        controller_pid=config.controller_pid + 100_000,
        controller_start_identity="replacement-start-identity",
    )
    monkeypatch.setattr(controller, "read_process_start_identity", lambda _pid: None)

    reclaimed = controller._bind_controller(store, contender)

    assert reclaimed["execution_generation"] == first["execution_generation"] + 1
    assert reclaimed["controller"]["id"] == contender.controller_id
    recovery = store.list_controller_recovery()
    assert recovery[0]["controller_pid"] == contender.controller_pid


def test_real_bwrap_hides_secrets_home_runtime_and_network(tmp_path: Path) -> None:
    if os.environ.get(SANDBOX_ACTIVE_ENV) == "1":
        pytest.skip("nested user namespaces are disabled by the outer execution sandbox")
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap unavailable")
    repo = _repo(tmp_path)
    stage = tmp_path / "stage"
    _git(repo, "worktree", "add", "--detach", str(stage), "HEAD")
    runtime_db = tmp_path / "private-runtime" / "chat.db"
    runtime_db.parent.mkdir()
    runtime_db.write_text("secret-db", encoding="utf-8")
    auth = tmp_path / "private-home" / ".codex" / "auth.json"
    auth.parent.mkdir(parents=True)
    auth.write_text("secret-auth", encoding="utf-8")
    home_secret = tmp_path / "private-home" / "sentinel"
    home_secret.write_text("secret-home", encoding="utf-8")
    target_secret = repo / "host-only-secret"
    target_secret.write_text("target-secret", encoding="utf-8")
    os.environ["XMUSE_OPERATOR_TOKEN"] = "must-not-cross"
    try:
        layout = discover_sandbox_layout(
            stage=stage,
            execution_root=repo,
            gate_ids=("backend_pytest",),
        )
        code = (
            "import os,pathlib,socket;"
            "assert os.getenv('XMUSE_OPERATOR_TOKEN') is None;"
            f"assert not pathlib.Path({str(runtime_db)!r}).exists();"
            f"assert not pathlib.Path({str(auth)!r}).exists();"
            f"assert not pathlib.Path({str(home_secret)!r}).exists();"
            f"assert not pathlib.Path({str(target_secret)!r}).exists();"
            "assert not pathlib.Path('/home').exists();"
            "p=pathlib.Path('/workspace/probe');p.write_text('ok');p.unlink();"
            "\nfor q in ('/repo-git/forbidden','/deps/site-packages/forbidden',"
            "'/opt/python/forbidden'):\n"
            " try:pathlib.Path(q).write_text('bad')\n"
            " except OSError:pass\n"
            " else:raise AssertionError(q)\n"
            "s=socket.socket();s.settimeout(.2);assert s.connect_ex(('1.1.1.1',53))!=0"
        )
        result = run_gate(
            layout,
            probe=GateSpec(
                "privacy_probe",
                ("/opt/python/bin/python3.11", "-c", code),
                "/workspace",
                10.0,
            ),
        )
    finally:
        os.environ.pop("XMUSE_OPERATOR_TOKEN", None)
        _git(repo, "worktree", "remove", "--force", str(stage))

    assert result.status == "passed"
    assert result.evidence_digest.startswith("sha256:")
    assert not hasattr(result, "output")


def test_real_frontend_gate_ignores_candidate_controlled_npm_scripts(tmp_path: Path) -> None:
    if os.environ.get(SANDBOX_ACTIVE_ENV) == "1":
        pytest.skip("nested user namespaces are disabled by the outer execution sandbox")
    if shutil.which("bwrap") is None:
        pytest.skip("bubblewrap unavailable")
    repo = Path(__file__).resolve().parents[2]
    stage = tmp_path / "frontend-stage"
    _git(repo, "worktree", "add", "--detach", str(stage), "HEAD")
    try:
        package_path = stage / "frontend" / "package.json"
        package = json.loads(package_path.read_text(encoding="utf-8"))
        package["scripts"]["build"] = (
            "node -e \"require('fs').writeFileSync('npm-script-ran','bad')\""
        )
        package_path.write_text(json.dumps(package), encoding="utf-8")
        layout = discover_sandbox_layout(
            stage=stage,
            execution_root=repo,
            gate_ids=("frontend_build",),
        )
        result = run_gate(layout, "frontend_build")

        assert result.status == "passed", result.reason_code
        assert not (stage / "frontend" / "npm-script-ran").exists()
        assert (stage / "frontend" / ".next").is_dir()
    finally:
        _git(repo, "worktree", "remove", "--force", str(stage))
