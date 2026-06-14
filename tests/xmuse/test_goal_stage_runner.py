import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / "scripts" / "goal_stage_runner.py"

module_name = "goal_stage_runner_test_harness"
loader = importlib.util.spec_from_file_location(module_name, SCRIPT_PATH)
assert loader is not None and loader.loader is not None
module = importlib.util.module_from_spec(loader)
sys.modules[module_name] = module
loader.loader.exec_module(module)


def _write_manifest(path: Path, content: dict[str, object]) -> None:
    path.write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")


def test_goal_stage_runner_dry_run_generates_artifacts(tmp_path: Path) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "stage_id": "S1",
            "objective": "Verify stage harness behavior.",
            "scope": ["tests/xmuse", "src/xmuse_core"],
            "acceptance_contracts": ["Contract A", "Contract B"],
            "owner": "cross-muse",
            "max_retries": 2,
            "risk": "low",
        },
    )

    output = tmp_path / "S1.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=True,
    )

    assert rc == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["review_decision"] == "dry_run"
    assert result["stage_id"] == "S1"
    assert (tmp_path / "S1.result.json.prompt.txt").exists()
    assert (tmp_path / "S1.result.json.manifest.jsonl").exists()
    assert (tmp_path / "S1.result.json.evidence" / "engine_output.txt").exists()

    manifest_log = json.loads(
        (tmp_path / "S1.result.json.manifest.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()[0]
    )
    assert manifest_log["status"] == "blocked"


def test_goal_stage_runner_blocks_on_missing_required_fields(tmp_path: Path) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "scope": ["tests"],
            "acceptance_contracts": ["a"],
        },
    )

    output = tmp_path / "S2.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )

    assert rc == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert any("stage_id" in issue["message"] for issue in result["issues"])


def test_goal_stage_runner_classifies_non_zero_as_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {"stage_id": "S3", "objective": "Check retry", "scope": [], "acceptance_contracts": []},
    )

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="temporary failure",
            stderr="retry needed",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    output = tmp_path / "S3.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )

    assert rc == 1
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "retry"
    assert result["returncode"] == 2


def test_goal_stage_runner_respects_zero_retry_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "stage_id": "S3-zero",
            "objective": "Check zero retry budget",
            "scope": [],
            "acceptance_contracts": [],
            "max_retries": 0,
        },
    )

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="permanent failure",
            stderr="do not retry",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    output = tmp_path / "S3-zero.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )

    assert rc == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["attempt"] == 1


def test_goal_stage_runner_opencode_message_does_not_get_consumed_as_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GOAL_OPENCODE_MODEL", "deepseek/unsafe")
    prompt_path = tmp_path / "prompt.txt"
    command = module._pick_command("opencode", repo_root=ROOT, prompt_path=prompt_path)

    file_index = command.index("--file")
    assert command[file_index + 1] == str(prompt_path)
    assert command[-2:] != ["--file", "Execute the attached goal stage prompt."]
    assert "Execute the attached goal stage prompt." in command[:file_index]
    assert command[:6] == [
        "opencode",
        "run",
        "--model",
        "opencode-go/deepseek-v4-flash",
        "--variant",
        "max",
    ]


def test_goal_stage_runner_prompt_includes_candidate_patch_gate(tmp_path: Path) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "stage_id": "S-candidate",
            "objective": "Produce a bounded candidate patch.",
            "scope": ["scripts/goal_stage_runner.py", "tests/xmuse/test_goal_stage_runner.py"],
            "acceptance_contracts": ["Candidate patch stays within allowed files."],
            "worker_kind": "mechanical_patch",
            "candidate_patch": True,
            "allowed_files": ["scripts/goal_stage_runner.py"],
            "forbidden_paths": ["xmuse/__init__.py", "feature_lanes.json", "xmuse/logs/"],
            "allowed_actions": ["edit_allowed_files", "run_focused_tests"],
            "forbidden_actions": ["commit", "push", "write_runtime_state"],
            "closure": {
                "target_layers": ["L2"],
                "proof_level": "contract_proof",
                "forbidden_claims": ["peer_god_live_proof"],
            },
            "evidence_summary": {
                "target_layers": ["L2"],
                "proof_level": "contract_proof",
                "candidate_patch": True,
            },
        },
    )

    output = tmp_path / "S-candidate.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="opencode",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=True,
    )

    assert rc == 0
    prompt = (tmp_path / "S-candidate.result.json.prompt.txt").read_text(encoding="utf-8")
    assert "OpenCode Candidate Patch Gate" in prompt
    assert "Worker kind: mechanical_patch" in prompt
    assert "Candidate patch: true" in prompt
    assert "- scripts/goal_stage_runner.py" in prompt
    assert "- xmuse/__init__.py" in prompt
    assert '"target_layers": [' in prompt
    assert '"L2"' in prompt
    assert "Do not commit, push, write runtime state, or claim completion." in prompt


def test_goal_stage_runner_result_preserves_candidate_patch_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "stage_id": "S-candidate-result",
            "objective": "Run bounded candidate patch stage.",
            "scope": ["scripts/goal_stage_runner.py"],
            "acceptance_contracts": ["Candidate metadata is preserved."],
            "engine": "opencode",
            "worker_kind": "mechanical_patch",
            "candidate_patch": True,
            "allowed_files": ["scripts/goal_stage_runner.py"],
            "forbidden_paths": ["xmuse/__init__.py"],
            "closure": {"target_layers": ["L2"], "proof_level": "contract_proof"},
            "evidence_summary": {"projection_only": False},
        },
    )
    captured: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = args[0] if args else kwargs.get("args") or kwargs.get("command")
        return subprocess.CompletedProcess(
            args=captured["command"],
            returncode=0,
            stdout='{"status":"ok"}',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    output = tmp_path / "S-candidate-result.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="auto",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )

    assert rc == 0
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["engine"] == "opencode"
    assert result["worker_kind"] == "mechanical_patch"
    assert result["candidate_patch"] is True
    assert result["allowed_files"] == ["scripts/goal_stage_runner.py"]
    assert result["forbidden_paths"] == ["xmuse/__init__.py"]
    assert result["closure"] == {"target_layers": ["L2"], "proof_level": "contract_proof"}
    assert result["evidence_summary"] == {"projection_only": False}


def test_goal_stage_runner_run_stage_pins_opencode_model_with_hostile_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "stage_id": "S4",
            "objective": "Check pinned opencode command",
            "scope": [],
            "acceptance_contracts": [],
        },
    )
    monkeypatch.setenv("GOAL_OPENCODE_MODEL", "deepseek/unsafe")
    captured: dict[str, Any] = {}

    def fake_run(*args: Any, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        captured["command"] = args[0] if args else kwargs.get("args") or kwargs.get("command")
        return subprocess.CompletedProcess(
            args=captured["command"],
            returncode=0,
            stdout='{"status":"ok"}',
            stderr="",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="opencode",
        repo_root=ROOT,
        output=tmp_path / "S4.result.json",
        timeout_seconds=10,
        dry_run=False,
    )

    assert rc == 0
    assert captured["command"][:6] == [
        "opencode",
        "run",
        "--model",
        "opencode-go/deepseek-v4-flash",
        "--variant",
        "max",
    ]


def test_goal_stage_runner_blocks_after_retry_budget_is_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "stage_id": "S3",
            "objective": "Check retry budget",
            "scope": [],
            "acceptance_contracts": [],
            "max_retries": 1,
        },
    )

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            args=[],
            returncode=2,
            stdout="temporary failure",
            stderr="retry needed",
        )

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    output = tmp_path / "S3.result.json"
    first_rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )
    second_rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )

    assert first_rc == 1
    assert second_rc == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["attempt"] == 2


def test_goal_stage_runner_writes_blocked_result_for_invalid_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "stage.json"
    manifest.write_text("{not-json", encoding="utf-8")

    output = tmp_path / "S5.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )

    assert rc == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert "manifest" in result["issues"][0]["message"].lower()
    assert (tmp_path / "S5.result.json.manifest.jsonl").exists()
    assert (tmp_path / "S5.result.json.evidence" / "engine_output.txt").exists()


def test_goal_stage_runner_marks_blocked_when_command_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest = tmp_path / "stage.json"
    _write_manifest(
        manifest,
        {
            "stage_id": "S4",
            "objective": "Check missing command",
            "scope": [],
            "acceptance_contracts": [],
        },
    )

    def fake_run(*_args: Any, **_kwargs: Any) -> subprocess.CompletedProcess[str]:
        raise FileNotFoundError("codex")

    monkeypatch.setattr(module.subprocess, "run", fake_run)

    output = tmp_path / "S4.result.json"
    rc = module.run_stage(
        stage_manifest_path=manifest,
        engine="codex",
        repo_root=ROOT,
        output=output,
        timeout_seconds=10,
        dry_run=False,
    )

    assert rc == 2
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "blocked"
    assert result["issues"][0]["message"].startswith("Command not found")
