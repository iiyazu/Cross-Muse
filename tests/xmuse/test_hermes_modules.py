from __future__ import annotations

import json
from pathlib import Path

from xmuse_core.hermes.active_jobs import (
    _git_status_short,
    _pid_alive_default,
    classify_active_job,
    complete_active_job,
    git_status_short,
    pid_alive_default,
    write_active_job,
)
from xmuse_core.hermes.json_artifacts import (
    _atomic_write_json,
    _atomic_write_text,
    _read_json,
    atomic_write_json,
    atomic_write_text,
    canonical_json_bytes,
    canonical_json_digest,
    file_json_digest,
    read_json,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_hermes_json_artifacts_module_exposes_stable_digest() -> None:
    left = {"b": 2, "a": {"z": 3, "y": [1, 2]}}
    right = {"a": {"y": [1, 2], "z": 3}, "b": 2}

    assert canonical_json_digest(left) == canonical_json_digest(right)
    assert canonical_json_digest(left).startswith("sha256:")


def test_hermes_json_artifacts_module_supports_file_helpers(tmp_path: Path) -> None:
    artifact = tmp_path / "nested" / "artifact.json"
    payload = {"request_digest": "old", "body": {"b": 2, "a": 1}}

    atomic_write_json(artifact, payload)
    digest = canonical_json_digest(payload)
    excluded_digest = canonical_json_digest(payload, exclude_keys={"request_digest"})

    assert read_json(artifact) == payload
    assert file_json_digest(artifact) == digest
    assert excluded_digest == canonical_json_digest({"body": {"a": 1, "b": 2}})
    assert canonical_json_bytes({"z": "µ"}, exclude_keys=set()) == b'{"z":"\xc2\xb5"}'


def test_hermes_json_artifacts_module_writes_text_atomically(tmp_path: Path) -> None:
    target = tmp_path / "logs" / "active.txt"

    atomic_write_text(target, "first")
    atomic_write_text(target, "second")

    assert target.read_text(encoding="utf-8") == "second"
    assert not (target.parent / ".active.txt.tmp").exists()


def test_hermes_modules_expose_legacy_facade_aliases(tmp_path: Path) -> None:
    artifact = tmp_path / "artifact.json"

    _atomic_write_json(artifact, {"ok": True})
    _atomic_write_text(tmp_path / "note.txt", "hello")

    assert _read_json(artifact) == {"ok": True}
    assert _git_status_short(tmp_path / "missing") is None
    assert _git_status_short is git_status_short
    assert _pid_alive_default is pid_alive_default


def test_hermes_eval_runs_module_classifies_llm_final_report(tmp_path: Path) -> None:
    from xmuse_core.hermes.eval_runs import classify_eval_run, summarize_eval_report

    final = tmp_path / "run.json"
    _write_json(
        final,
        [
            {
                "case_id": "case-1",
                "verdict": "pass",
                "answer_mode": "llm",
                "judge_status": "judge_pass",
                "movement_status": "unchanged_pass",
            }
        ],
    )

    summary = summarize_eval_report(final)
    status = classify_eval_run(
        run_id="run",
        benchmark="longmemeval",
        partial_path=tmp_path / "run.partial.json",
        final_path=final,
        require_llm=True,
    )

    assert summary["rows_done"] == 1
    assert summary["movement_counts"] == {"unchanged_pass": 1}
    assert status["state"] == "completed"


def test_hermes_eval_runs_module_reports_missing_and_invalid_reports(tmp_path: Path) -> None:
    from xmuse_core.hermes.eval_runs import summarize_eval_report

    missing = summarize_eval_report(tmp_path / "missing.json")
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    object_report = tmp_path / "object.json"
    _write_json(object_report, {"rows": []})

    assert missing == {
        "valid": False,
        "error": "missing report",
        "path": str(tmp_path / "missing.json"),
        "rows_done": 0,
    }
    assert summarize_eval_report(invalid)["error"].startswith("invalid json:")
    assert summarize_eval_report(object_report) == {
        "valid": False,
        "error": "report root is not a list",
        "path": str(object_report),
        "rows_done": 0,
    }


def test_hermes_eval_runs_module_prefers_movement_status_over_legacy_movement(
    tmp_path: Path,
) -> None:
    from xmuse_core.hermes.eval_runs import summarize_eval_report

    report = tmp_path / "run.json"
    _write_json(
        report,
        [
            {
                "case_id": "case-1",
                "verdict": "pass",
                "movement": "legacy_fail",
                "movement_status": "unchanged_pass",
            }
        ],
    )

    summary = summarize_eval_report(report)

    assert summary["movement_counts"] == {"unchanged_pass": 1}


def test_hermes_eval_runs_module_requires_llm_answers_and_judges_for_promotion(
    tmp_path: Path,
) -> None:
    from xmuse_core.hermes.eval_runs import classify_eval_run

    projected = tmp_path / "projected.partial.json"
    _write_json(
        projected,
        [{"case_id": "case-1", "answer_mode": "projected", "judge_status": "judge_pass"}],
    )
    unjudged = tmp_path / "unjudged.partial.json"
    _write_json(
        unjudged,
        [{"case_id": "case-1", "answer_mode": "llm", "judge_status": "not_run"}],
    )

    projected_status = classify_eval_run(
        run_id="projected",
        benchmark="longmemeval",
        partial_path=projected,
        final_path=tmp_path / "projected.json",
        require_llm=True,
    )
    unjudged_status = classify_eval_run(
        run_id="unjudged",
        benchmark="locomo",
        partial_path=unjudged,
        final_path=tmp_path / "unjudged.json",
        require_llm=True,
    )

    assert projected_status["state"] == "invalid_for_promotion"
    assert "some rows are not llm answer mode" in projected_status["reason"]
    assert unjudged_status["state"] == "invalid_for_promotion"
    assert "non-judged rows exist" in unjudged_status["reason"]


def test_hermes_eval_runs_module_classifies_partial_progress_and_stale(
    tmp_path: Path,
) -> None:
    from xmuse_core.hermes.eval_runs import classify_eval_run

    partial = tmp_path / "run.partial.json"
    _write_json(partial, [{"case_id": "case-1", "answer_mode": "llm", "judge_status": "pass"}])
    os_snapshot = {"file_size": partial.stat().st_size - 1, "rows_done": 0, "mtime": 1}

    progressing = classify_eval_run(
        run_id="run",
        benchmark="locomo",
        partial_path=partial,
        final_path=tmp_path / "run.json",
        previous_snapshot=os_snapshot,
        now=partial.stat().st_mtime + 1000,
        stale_after_seconds=10,
        require_llm=False,
    )

    assert progressing["state"] == "running_or_progressing"
    assert progressing["reason"] == "partial grew since previous snapshot"

    snapshot = {
        "file_size": partial.stat().st_size,
        "rows_done": 1,
        "mtime": partial.stat().st_mtime,
    }
    stalled = classify_eval_run(
        run_id="run",
        benchmark="locomo",
        partial_path=partial,
        final_path=tmp_path / "run.json",
        previous_snapshot=snapshot,
        now=partial.stat().st_mtime + 1000,
        stale_after_seconds=10,
        require_llm=False,
    )

    assert stalled["state"] == "stalled"
    assert "no final report and partial stale" in stalled["reason"]


def test_hermes_active_jobs_module_writes_classifies_and_completes(tmp_path: Path) -> None:
    loop = tmp_path / "xmuse"
    output = loop / "codex_output.log"
    output.parent.mkdir(parents=True)
    output.write_text("running\n", encoding="utf-8")

    written = write_active_job(
        loop,
        pid=123,
        phase_id="phase-1",
        prompt_file="prompt.md",
        attempt=2,
        output_path="codex_output.log",
        idle_timeout_seconds=60,
        started_at="2026-06-02T00:00:00Z",
    )
    running = classify_active_job(loop, now=output.stat().st_mtime, pid_alive=lambda pid: True)
    completed = complete_active_job(
        loop,
        exit_code=0,
        status="completed",
        completed_at="2026-06-02T00:01:00Z",
    )

    assert written["path"].endswith("active_job.json")
    assert running["state"] == "running"
    assert completed["status"] == "completed"
    assert completed["exit_code"] == 0


def test_hermes_active_jobs_module_classifies_missing_invalid_and_dead_jobs(
    tmp_path: Path,
) -> None:
    loop = tmp_path / "xmuse"

    missing = classify_active_job(loop)
    loop.mkdir()
    (loop / "active_job.json").write_text("[1, 2]\n", encoding="utf-8")
    invalid_root = classify_active_job(loop)
    (loop / "active_job.json").write_text('{"pid": 999, "status": "running"}\n', encoding="utf-8")
    dead = classify_active_job(loop, pid_alive=lambda pid: False)

    assert missing["state"] == "missing"
    assert invalid_root["ok"] is False
    assert invalid_root["state"] == "invalid"
    assert dead["state"] == "exited_or_missing"
    assert dead["reason"] == "pid is not alive"


def test_hermes_active_jobs_module_detects_stalled_output(tmp_path: Path) -> None:
    loop = tmp_path / "xmuse"
    output = loop / "codex_output.log"
    output.parent.mkdir(parents=True)
    output.write_text("old\n", encoding="utf-8")
    write_active_job(
        loop,
        pid=123,
        phase_id=None,
        prompt_file="prompt.md",
        attempt=1,
        output_path="codex_output.log",
        idle_timeout_seconds=10,
        started_at="2026-06-02T00:00:00Z",
    )

    stalled = classify_active_job(
        loop,
        now=output.stat().st_mtime + 11,
        pid_alive=lambda pid: True,
    )

    assert stalled["ok"] is False
    assert stalled["state"] == "stalled"
    assert stalled["output_age_seconds"] == 11


def test_hermes_phase_gates_module_checks_execute_goal_contract(tmp_path: Path) -> None:
    from xmuse_core.hermes.phase_gates import check_execute_goal_contract

    loop = tmp_path / "xmuse"
    phase_dir = loop / "work" / "phase-1"
    phase_dir.mkdir(parents=True)
    (phase_dir / "execute_goal.md").write_text(
        "\n".join(
            [
                "# phase: phase-1",
                "/goal implement real MemoryOS path wiring.",
                "Write result.md and tests.",
                "No demo-only implementation.",
                "Max repair cycles: 2",
            ]
        ),
        encoding="utf-8",
    )

    result = check_execute_goal_contract(loop, "phase-1")

    assert result["ok"] is True
    assert result["blockers"] == []


def test_hermes_phase_gates_module_blocks_stale_execute_result(tmp_path: Path) -> None:
    from xmuse_core.hermes.phase_gates import check_execute_completion_gate

    loop = tmp_path / "xmuse"
    phase_dir = loop / "work" / "phase-3"
    phase_dir.mkdir(parents=True)
    _write_json(
        loop / "state.json",
        {
            "current_state": "EXECUTE",
            "execute_lane": {"phase": "phase-3", "state": "EXECUTE"},
        },
    )
    (phase_dir / "result.md").write_text("# phase: phase-2\nold result\n", encoding="utf-8")

    result = check_execute_completion_gate(loop)

    assert result["ok"] is False
    assert result["action"] == "blocked_stale_result"
    assert result["blockers"] == ["result.md phase binding mismatch"]


def test_hermes_phase_gates_module_scans_stale_artifacts(tmp_path: Path) -> None:
    from xmuse_core.hermes.phase_gates import scan_stale_artifacts

    phase_dir = tmp_path / "phase-4"
    phase_dir.mkdir()
    (phase_dir / "ack.json").write_text(
        '{"context_bundle":"work/phase-4/context_bundle.md"}',
        encoding="utf-8",
    )
    (phase_dir / "review_verdict.json").write_text(
        "work/phase-3/context_bundle.md",
        encoding="utf-8",
    )

    result = scan_stale_artifacts(
        phase_dir,
        current_context_bundle="work/phase-4/context_bundle.md",
        candidate_files=("ack.json", "review_verdict.json", "result.md"),
    )

    assert result["active_files"] == ["ack.json"]
    assert result["stale_files"] == ["review_verdict.json"]
    assert result["missing_files"] == ["result.md"]


def test_hermes_phase_gates_module_writes_phase_status(tmp_path: Path) -> None:
    from xmuse_core.hermes.phase_gates import write_phase_status

    result = write_phase_status(
        tmp_path / "xmuse",
        "phase-5",
        [
            {
                "benchmark": "longmemeval",
                "run_id": "run-1",
                "state": "completed",
                "rows_done": 2,
            }
        ],
        ack_gate={"ok": False, "blockers": ["missing ack.json"]},
    )

    payload = json.loads(result["json"].read_text(encoding="utf-8"))
    markdown = result["markdown"].read_text(encoding="utf-8")

    assert payload["phase_id"] == "phase-5"
    assert payload["ack_gate"]["blockers"] == ["missing ack.json"]
    assert "longmemeval `run-1`: completed rows=2" in markdown
    assert "- ack_gate: blocked" in markdown


def test_hermes_merge_gates_module_accepts_injected_target_head(tmp_path: Path) -> None:
    from xmuse_core.hermes.merge_gates import validate_merge_queue_gate

    loop = tmp_path / "xmuse"
    project = tmp_path
    feature_id = "feature-a"
    feature = {
        "id": feature_id,
        "branch": "feature/a",
        "target_branch": "main",
        "slave_state_path": f"xmuse/work/features/{feature_id}/slave_state.json",
        "artifacts": {
            "ack": f"xmuse/work/features/{feature_id}/ack.json",
            "review_verdict": f"xmuse/work/features/{feature_id}/review_verdict.json",
            "result": f"xmuse/work/features/{feature_id}/result.md",
            "master_review": f"xmuse/master/features/{feature_id}/master_review.json",
            "integrated_tests": f"xmuse/master/features/{feature_id}/integrated_tests.json",
        },
        "merge": {"target_branch": "main", "strategy": "no_ff_merge_commit"},
    }
    _write_json(project / feature["artifacts"]["ack"], {"ack_level": "usable"})
    _write_json(project / feature["artifacts"]["review_verdict"], {"verdict": "pass"})
    result_path = project / feature["artifacts"]["result"]
    result_path.parent.mkdir(parents=True, exist_ok=True)
    result_path.write_text("ok\n", encoding="utf-8")
    _write_json(project / feature["slave_state_path"], {"state": "ready"})
    evidence = {
        "recorded_by": "master-god",
        "status": "accepted",
        "feature_id": feature_id,
        "branch": "feature/a",
        "base_commit": "abc123",
        "head_commit": "def456",
        "target_branch": "main",
        "artifact_digests": {},
    }
    _write_json(project / feature["artifacts"]["master_review"], evidence)
    _write_json(
        project / feature["artifacts"]["integrated_tests"],
        {**evidence, "status": "passed", "worktree_clean": True, "commands": []},
    )

    result = validate_merge_queue_gate(
        loop,
        feature,
        current_target_head=lambda _loop, _branch: "abc123",
    )

    assert result == {"valid": True, "errors": []}


def test_hermes_feature_lanes_module_allows_missing_registry(tmp_path: Path) -> None:
    from xmuse_core.hermes.feature_lanes import load_feature_lanes

    loop = tmp_path / "xmuse"

    result = load_feature_lanes(loop)

    assert result["ok"] is True
    assert result["state"] == "missing"
    assert result["features"] == []
