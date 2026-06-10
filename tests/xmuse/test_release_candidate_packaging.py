from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_root_readme_is_new_developer_release_entrypoint() -> None:
    readme = _read("README.md")

    required_phrases = [
        "xmuse is a multi-agent software delivery platform",
        "Current Capabilities",
        "Architecture Overview",
        "Install",
        "Quickstart",
        "Fake Groupchat Demo",
        "Real Ray/Codex/MCP Manual Gate",
        "Production / Experimental / Legacy Boundaries",
        "Codex = primary",
        "OpenCode = secondary",
        "Fake = test/demo only",
        "Legacy",
    ]
    for phrase in required_phrases:
        assert phrase in readme

    assert "uv sync --frozen --all-groups" in readme
    assert "uv run python scripts/demo_fake_groupchat.py" in readme
    assert "memoryos" not in readme.lower()


def test_quickstart_documents_clean_fake_demo_path() -> None:
    quickstart = _read("QUICKSTART.md")

    required_phrases = [
        "Clean Environment Setup",
        "uv sync --frozen --all-groups",
        "uv run xmuse-platform-runner --health-once",
        "uv run python scripts/demo_fake_groupchat.py",
        "does not require Codex, Ray, OpenCode, DeepSeek, or memoryOS",
        "Optional Real Runtime Notes",
    ]
    for phrase in required_phrases:
        assert phrase in quickstart


def test_release_checklist_captures_gates_and_limits() -> None:
    checklist = _read("docs/xmuse/release-checklist.md")

    required_phrases = [
        "Default CI Gates",
        "Manual Real Runtime Gate",
        "Provider Support Levels",
        "Known Limitations",
        "tests/xmuse/test_full_chain_real_run.py::test_real_runtime_restart_resume_smoke_with_fake_app_server",
        "tests/xmuse/test_full_chain_real_run.py::test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume",
        "Codex = PRIMARY",
        "OpenCode = SECONDARY",
        "Fake = TEST ONLY",
        "Chat API and MCP have no auth layer",
    ]
    for phrase in required_phrases:
        assert phrase in checklist


def test_release_facing_matrices_have_current_manual_gate_and_settings_claims() -> None:
    provider_matrix = _read("docs/xmuse/provider-matrix.md")
    config_matrix = _read("docs/xmuse/config-matrix.md")

    assert (
        "tests/xmuse/test_full_chain_real_run.py::"
        "test_real_ray_codex_app_server_mcp_writeback_soak_restart_resume"
    ) in provider_matrix
    assert "tests/xmuse/test_ray_adapters.py::test_real_ray_codex_app_server" not in (
        provider_matrix
    )
    assert "没有 `BaseSettings` 类" not in config_matrix
    assert "没有 `BaseSettings` 类" not in provider_matrix
    assert "`pydantic-settings` 依赖声明但未使用" not in config_matrix
    assert "`pydantic-settings` 依赖声明但未使用" not in provider_matrix


def test_pyproject_release_metadata_points_to_root_readme() -> None:
    pyproject = tomllib.loads(_read("pyproject.toml"))
    project = pyproject["project"]

    assert project["readme"] == "README.md"
    assert (
        project["description"]
        == "Multi-agent software delivery platform for chat-driven GOD orchestration"
    )
    assert "MemoryOS" not in project["description"]


def test_fake_groupchat_demo_command_runs_without_real_providers(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/demo_fake_groupchat.py",
            "--xmuse-root",
            str(tmp_path / "xmuse-demo"),
            "--message",
            "Need a small release candidate packaging plan.",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "fake-groupchat-demo-ok" in result.stdout
    assert "GOD reply:" in result.stdout
    assert "scheduler_happy_path=1" in result.stdout
    assert "Codex" not in result.stderr
    assert "Ray" not in result.stderr
    assert "DeepSeek" not in result.stderr
