from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.production_baseline_capture import (
    ProbeResult,
    capture_production_baseline,
)


def test_production_baseline_capture_writes_redacted_s0_truth_map(
    tmp_path: Path,
) -> None:
    (tmp_path / "xmuse").mkdir()
    output_path = tmp_path / "baseline.json"

    report = capture_production_baseline(
        repo_root=tmp_path,
        output_path=output_path,
        env={
            "XMUSE_LIVE_MEMORYOS_LITE": "1",
            "XMUSE_MEMORYOS_LITE_URL": "http://127.0.0.1:8000?token=secret-memoryos",
            "XMUSE_GITHUB_TRUTH_REPO": "iiyazu/Cross-Muse",
            "XMUSE_GITHUB_TRUTH_PULL_REQUEST": "43",
            "XMUSE_CHAT_API_AUTH_TOKEN": "secret-chat-token",
            "XMUSE_MCP_AUTH_TOKEN": "secret-mcp-token",
            "DEEPSEEK_API_KEY": "sk-secret-deepseek",
            "OPENAI_API_KEY": "sk-secret-openai",
            "XMUSE_PEER_GOD_BACKEND": "ray",
            "XMUSE_RAY_GOD_MCP": "1",
        },
        command_runner=_fake_runner(
            {
                "git status --short --branch": _probe(
                    "git_status",
                    ("git", "status", "--short", "--branch"),
                    0,
                    (
                        "## vision-closure-deliberation-tui..."
                        "origin/vision-closure-deliberation-tui\n"
                        " M docs/xmuse/plan.md\n"
                    ),
                ),
                "git rev-parse HEAD": _probe(
                    "git_head",
                    ("git", "rev-parse", "HEAD"),
                    0,
                    "abc123\n",
                ),
                "gh auth status": _probe(
                    "github_auth",
                    ("gh", "auth", "status"),
                    0,
                    (
                        "Logged in to github.com as iiyazu\n"
                        "Token: gho_secretgithubtoken\n"
                        "Masked token: gho_************************************\n"
                    ),
                ),
                "codex --version": _probe(
                    "codex_version",
                    ("codex", "--version"),
                    0,
                    "codex-cli 0.139.0\n",
                ),
                "opencode --version": _probe(
                    "opencode_version",
                    ("opencode", "--version"),
                    0,
                    "1.17.3\n",
                ),
                "uv run python -c import ray; print(ray.__version__)": _probe(
                    "ray_import",
                    ("uv", "run", "python", "-c", "import ray; print(ray.__version__)"),
                    0,
                    "2.55.1\n",
                ),
            }
        ),
    )

    written = json.loads(output_path.read_text())
    rendered = json.dumps(written, sort_keys=True)
    assert report == written
    assert report["schema_version"] == "xmuse.production_baseline.v1"
    assert report["stage_id"] == "S0"
    assert report["proof_level"] == "contract_proof"
    assert report["git"]["head_sha"] == "abc123"
    assert report["git"]["dirty"] is True
    assert report["package_boundary"]["xmuse_init_absent"] is True
    assert report["live_resources"]["memoryos_lite"]["configured"] is True
    assert report["live_resources"]["github"]["available"] is True
    assert report["live_resources"]["provider_runtime"]["available"] is True
    assert "memoryos_live_trace_artifact_missing" in report["blockers"]
    assert "natural_god_transcript_artifact_missing" in report["blockers"]
    assert "secret-memoryos" not in rendered
    assert "secret-chat-token" not in rendered
    assert "secret-mcp-token" not in rendered
    assert "sk-secret" not in rendered
    assert "gho_" not in rendered


def test_production_baseline_capture_blocks_runtime_namespace_violation(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "xmuse"
    runtime.mkdir()
    (runtime / "__init__.py").write_text("# forbidden\n", encoding="utf-8")

    report = capture_production_baseline(
        repo_root=tmp_path,
        env={},
        command_runner=_fake_runner({}),
    )

    assert report["package_boundary"]["xmuse_init_absent"] is False
    assert report["package_boundary"]["status"] == "blocked"
    assert "xmuse_init_py_exists" in report["blockers"]


def test_production_baseline_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-production-baseline-capture"]
        == "xmuse.production_baseline_capture:main"
    )


def _probe(
    name: str,
    command: tuple[str, ...],
    returncode: int,
    stdout: str,
    stderr: str = "",
) -> ProbeResult:
    return ProbeResult(
        name=name,
        command=command,
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def _fake_runner(
    results: dict[str, ProbeResult],
):
    def run(command: tuple[str, ...]) -> ProbeResult:
        return results.get(
            " ".join(command),
            ProbeResult(
                name=" ".join(command),
                command=command,
                returncode=127,
                stdout="",
                stderr="not found",
            ),
        )

    return run
