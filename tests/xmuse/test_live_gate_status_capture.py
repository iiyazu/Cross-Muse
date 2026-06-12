from __future__ import annotations

import json
import tomllib
from pathlib import Path

from xmuse_core.platform.live_gate_status_capture import (
    ProbeResult,
    capture_live_gate_status,
)
from xmuse_core.platform.release_readiness_capture import capture_release_readiness


def test_live_gate_status_capture_writes_release_gate_artifacts_without_secrets(
    tmp_path: Path,
) -> None:
    env = {
        "XMUSE_MEMORYOS_LITE_URL": "http://127.0.0.1:8000?token=secret-memoryos",
        "XMUSE_LIVE_MEMORYOS_LITE": "1",
        "XMUSE_CHAT_API_AUTH_TOKEN": "secret-chat-token",
        "XMUSE_CHAT_API_KEY": "secret-chat-key",
        "XMUSE_MCP_AUTH_TOKEN": "secret-mcp-token",
        "DEEPSEEK_API_KEY": "sk-secret-deepseek",
        "XMUSE_PEER_GOD_BACKEND": "ray",
        "XMUSE_RAY_GOD_MCP": "1",
    }

    summary = capture_live_gate_status(
        output_dir=tmp_path,
        env=env,
        command_runner=_fake_runner(
            {
                "gh auth status": ProbeResult(
                    name="github_auth",
                    command=("gh", "auth", "status"),
                    returncode=0,
                    stdout="Logged in to github.com as iiyazu",
                    stderr="",
                ),
                "codex --version": ProbeResult(
                    name="codex_version",
                    command=("codex", "--version"),
                    returncode=0,
                    stdout="codex-cli 0.139.0",
                    stderr="",
                ),
                "opencode --version": ProbeResult(
                    name="opencode_version",
                    command=("opencode", "--version"),
                    returncode=0,
                    stdout="1.17.3",
                    stderr="",
                ),
                "uv run python -c import ray; print(ray.__version__)": ProbeResult(
                    name="ray_import",
                    command=(
                        "uv",
                        "run",
                        "python",
                        "-c",
                        "import ray; print(ray.__version__)",
                    ),
                    returncode=0,
                    stdout="2.55.1",
                    stderr="",
                ),
            }
        ),
    )

    assert summary["schema_version"] == "xmuse.live_gate_status_capture.v1"
    assert summary["artifact_count"] == 4
    artifacts = sorted(tmp_path.glob("*.json"))
    assert [path.name for path in artifacts] == [
        "github-server-truth-status.json",
        "live-memoryos-status.json",
        "natural-deliberation-status.json",
        "real-provider-status.json",
    ]

    memoryos = json.loads((tmp_path / "live-memoryos-status.json").read_text())
    assert memoryos["gate_id"] == "live-memoryos"
    assert memoryos["kind"] == "live_memoryos"
    assert memoryos["configured"] is True
    assert memoryos["required"] is True
    assert memoryos["status"] == "blocked"
    assert memoryos["proof_level"] == "manual_gap"
    assert "XMUSE_MEMORYOS_LITE_URL" in memoryos["source_refs"]
    assert "secret-memoryos" not in json.dumps(memoryos, sort_keys=True)

    rendered_summary = json.dumps(summary, sort_keys=True)
    assert "secret-chat-token" not in rendered_summary
    assert "secret-chat-key" not in rendered_summary
    assert "secret-mcp-token" not in rendered_summary
    assert "sk-secret-deepseek" not in rendered_summary


def test_live_gate_status_artifacts_feed_release_readiness_as_blockers(
    tmp_path: Path,
) -> None:
    capture_live_gate_status(
        output_dir=tmp_path / "artifacts",
        env={},
        command_runner=_fake_runner({}),
    )

    report = capture_release_readiness(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "readiness.json",
    )

    assert report["decision"] == "blocked"
    blocker_ids = {blocker["gate_id"] for blocker in report["blockers"]}
    assert {
        "live-memoryos",
        "github-server-truth",
        "real-provider-runtime",
        "natural-god-deliberation",
    }.issubset(blocker_ids)


def test_live_gate_status_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-live-gate-status-capture"]
        == "xmuse.live_gate_status_capture:main"
    )


def _fake_runner(results: dict[str, ProbeResult]):
    def run(command: tuple[str, ...]) -> ProbeResult:
        key = " ".join(command)
        return results.get(
            key,
            ProbeResult(
                name=key.replace(" ", "_"),
                command=command,
                returncode=127,
                stdout="",
                stderr="not configured for test",
            ),
        )

    return run
