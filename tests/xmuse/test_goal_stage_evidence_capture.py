from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.goal_stage_evidence_capture import (
    capture_goal_stage_evidence,
)


def test_goal_stage_evidence_capture_indexes_stage_results(tmp_path: Path) -> None:
    result = tmp_path / "S1.result.json"
    _write_stage_result(
        result,
        stage_id="S1",
        status="ok",
        engine="opencode",
        command=[
            "opencode",
            "run",
            "--model",
            "opencode-go/deepseek-v4-flash",
            "--variant",
            "max",
        ],
    )
    (tmp_path / "S1.result.json.prompt.txt").write_text(
        "Stage: S1\nObjective: prepare evidence spine\n",
        encoding="utf-8",
    )
    (tmp_path / "S1.result.json.manifest.jsonl").write_text(
        json.dumps({"stage_id": "S1", "status": "ok"}) + "\n",
        encoding="utf-8",
    )
    evidence_dir = tmp_path / "S1.result.json.evidence"
    evidence_dir.mkdir()
    (evidence_dir / "engine_output.txt").write_text("structured worker output\n", encoding="utf-8")

    output = tmp_path / "stage-evidence.json"
    evidence = capture_goal_stage_evidence(
        run_id="overnight-stage-run",
        output_path=output,
        stage_results=(result,),
    )

    assert evidence["schema_version"] == "xmuse.production_evidence.v1"
    assert evidence["stage_id"] == "S1"
    assert evidence["action"] == "goal_stage_results_indexed"
    assert evidence["status"] == "ok"
    assert evidence["proof_level"] == "contract_proof"
    assert evidence["source_authority"] == "goal_stage_harness"
    assert evidence["source_refs"] == [
        "goal_run:overnight-stage-run",
        "goal_stage:S1",
        f"goal_stage_result:{result}",
    ]
    assert evidence["artifacts"] == [
        str(result),
        str(tmp_path / "S1.result.json.prompt.txt"),
        str(tmp_path / "S1.result.json.manifest.jsonl"),
        str(evidence_dir / "engine_output.txt"),
    ]
    assert evidence["stage_results"] == [
        {
            "stage_id": "S1",
            "status": "ok",
            "engine": "opencode",
            "returncode": 0,
            "attempt": 1,
            "result_path": str(result),
        }
    ]
    assert evidence["summary"] == "Goal stage harness indexed 1 result(s): ok=1."
    assert json.loads(output.read_text(encoding="utf-8")) == evidence


def test_goal_stage_evidence_capture_preserves_blocked_stage_as_manual_gap(
    tmp_path: Path,
) -> None:
    result = tmp_path / "S4.result.json"
    _write_stage_result(
        result,
        stage_id="S4",
        status="blocked",
        engine="codex",
        issues=[{"message": "MemoryOS Lite live URL is missing"}],
    )

    evidence = capture_goal_stage_evidence(
        run_id="overnight-stage-run",
        output_path=tmp_path / "stage-evidence.json",
        stage_results=(result,),
    )

    assert evidence["status"] == "blocked"
    assert evidence["proof_level"] == "manual_gap"
    assert evidence["blocked_reason"] == "goal stage results include non-ok stages: S4=blocked"
    assert evidence["next_action"] == (
        "Resolve non-ok goal stage results before claiming overnight stage completion."
    )
    assert evidence["stage_results"][0]["issues"] == [
        "MemoryOS Lite live URL is missing"
    ]


def test_goal_stage_evidence_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-goal-stage-evidence-capture"]
        == "xmuse.goal_stage_evidence_capture:main"
    )


def _write_stage_result(
    path: Path,
    *,
    stage_id: str,
    status: str,
    engine: str,
    command: list[str] | None = None,
    issues: list[dict[str, str]] | None = None,
) -> None:
    payload = {
        "stage_id": stage_id,
        "status": status,
        "engine": engine,
        "issues": issues or [],
        "review_decision": "pass" if status == "ok" else status,
        "retry_hint": None if status == "ok" else "Resolve blockers.",
        "evidence_dir": str(path.parent / f"{path.name}.evidence"),
        "agent_output_path": str(path),
        "command": command or ["codex", "exec", "-"],
        "agent_stdout_path": str(path.parent / f"{path.name}.evidence" / "engine_output.txt"),
        "returncode": 0 if status == "ok" else 2,
        "attempt": 1,
        "timestamp_utc": "2026-06-12T00:00:00Z",
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
