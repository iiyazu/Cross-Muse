from __future__ import annotations

import json
import subprocess
import tomllib
from pathlib import Path
from typing import Any

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
                    stdout=(
                        "Logged in to github.com as iiyazu\n"
                        "Token: gho_secretgithubtoken\n"
                        "Masked token: gho_************************************"
                    ),
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
    assert "gho_" not in rendered_summary


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


def test_live_gate_status_capture_uses_configured_github_server_truth(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "artifacts" / "live_gate_status"
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/43": {
                "node_id": "PR_node_43",
                "merged": False,
                "merged_at": None,
                "merge_commit_sha": "merge-candidate",
                "head": {"sha": "head456"},
            },
            "repos/iiyazu/Cross-Muse/pulls/43/reviews": [],
            "repos/iiyazu/Cross-Muse/branches/main/protection": {
                "required_status_checks": {
                    "checks": [
                        {"context": "quality-gates"},
                        {"context": "contract-smoke-gates"},
                        {"context": "real-runtime-integration-gate"},
                    ]
                },
            },
            "repos/iiyazu/Cross-Muse/commits/head456/check-runs": {
                "check_runs": [
                    {
                        "id": 211,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 212,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 213,
                        "name": "real-runtime-integration-gate",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ]
            },
        }
    )

    summary = capture_live_gate_status(
        output_dir=output_dir,
        env={
            "XMUSE_GITHUB_TRUTH_REPO": "iiyazu/Cross-Muse",
            "XMUSE_GITHUB_TRUTH_PULL_REQUEST": "43",
            "XMUSE_GITHUB_TRUTH_BASE_BRANCH": "main",
            "XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS": (
                "quality-gates,contract-smoke-gates,real-runtime-integration-gate"
            ),
        },
        command_runner=_fake_runner(
            {
                "gh auth status": ProbeResult(
                    name="github_auth",
                    command=("gh", "auth", "status"),
                    returncode=0,
                    stdout="Logged in to github.com as iiyazu",
                    stderr="",
                )
            }
        ),
        github_truth_runner=runner,
    )

    gate = json.loads((output_dir / "github-server-truth-status.json").read_text())
    snapshot_path = output_dir / "github-server-truth-snapshot.json"
    snapshot = json.loads(snapshot_path.read_text())
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "readiness.json",
    )

    assert summary["artifact_count"] == 4
    assert gate["gate_id"] == "github-server-truth"
    assert gate["kind"] == "github_server_truth"
    assert gate["status"] == "ok"
    assert gate["proof_level"] == "server_side_enforcement_proof"
    assert gate["source_refs"] == [
        "github:pr:43",
        "github:branch:main",
        "github:head:head456",
    ]
    assert gate["artifacts"] == [str(snapshot_path)]
    assert snapshot["schema_version"] == "github_server_side_truth_capture.v1"
    assert snapshot["capture_mode"] == "opt_in_read_only_gh_api"
    assert snapshot["can_emit_pr_merged"] is False
    assert snapshot["gap_reason"] == "missing server-side truth: review_truth, merge_truth"
    assert all(command[:2] == ["gh", "api"] for command in runner.commands)
    assert "github-server-truth" not in {
        blocker["gate_id"] for blocker in report["blockers"]
    }


def test_live_gate_status_capture_blocks_github_truth_for_stale_expected_head(
    tmp_path: Path,
) -> None:
    output_dir = tmp_path / "artifacts" / "live_gate_status"
    runner = _FakeGhApiRunner(
        {
            "repos/iiyazu/Cross-Muse/pulls/43": {
                "node_id": "PR_node_43",
                "merged": False,
                "merged_at": None,
                "merge_commit_sha": "merge-candidate",
                "head": {"sha": "old-head"},
            },
            "repos/iiyazu/Cross-Muse/pulls/43/reviews": [],
            "repos/iiyazu/Cross-Muse/branches/main/protection": {
                "required_status_checks": {
                    "checks": [
                        {"context": "quality-gates"},
                        {"context": "contract-smoke-gates"},
                        {"context": "real-runtime-integration-gate"},
                    ]
                },
            },
            "repos/iiyazu/Cross-Muse/commits/old-head/check-runs": {
                "check_runs": [
                    {
                        "id": 211,
                        "name": "quality-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 212,
                        "name": "contract-smoke-gates",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                    {
                        "id": 213,
                        "name": "real-runtime-integration-gate",
                        "conclusion": "success",
                        "app": {"slug": "github-actions"},
                    },
                ]
            },
        }
    )

    capture_live_gate_status(
        output_dir=output_dir,
        env={
            "XMUSE_GITHUB_TRUTH_REPO": "iiyazu/Cross-Muse",
            "XMUSE_GITHUB_TRUTH_PULL_REQUEST": "43",
            "XMUSE_GITHUB_TRUTH_EXPECTED_HEAD_SHA": "current-head",
        },
        command_runner=_fake_runner(
            {
                "gh auth status": ProbeResult(
                    name="github_auth",
                    command=("gh", "auth", "status"),
                    returncode=0,
                    stdout="Logged in to github.com as iiyazu",
                    stderr="",
                )
            }
        ),
        github_truth_runner=runner,
    )

    gate = json.loads((output_dir / "github-server-truth-status.json").read_text())
    snapshot = json.loads((output_dir / "github-server-truth-snapshot.json").read_text())
    assert gate["status"] == "manual_gap"
    assert gate["proof_level"] == "manual_gap"
    assert "does not match expected current head current-head" in gate["summary"]
    assert snapshot["head_sha"] == "old-head"
    assert snapshot["expected_head_sha"] == "current-head"
    assert snapshot["head_sha_matches_expected"] is False


def test_live_gate_status_capture_converts_configured_live_artifacts(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "source-artifacts"
    memoryos_trace = artifacts / "memoryos-trace.json"
    natural_transcript = artifacts / "natural-transcript.json"
    natural_runtime = artifacts / "god-runtime.json"
    provider_runtime = artifacts / "provider-runtime.json"
    _write_json(memoryos_trace, _memoryos_trace_artifact())
    _write_json(natural_transcript, _natural_transcript_artifact())
    _write_json(natural_runtime, _god_runtime_artifact())
    _write_json(provider_runtime, _provider_runtime_artifact())

    output_dir = tmp_path / "artifacts" / "live_gate_status"
    summary = capture_live_gate_status(
        output_dir=output_dir,
        env={
            "XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT": str(memoryos_trace),
            "XMUSE_NATURAL_GOD_TRANSCRIPT_PATH": str(natural_transcript),
            "XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT": str(natural_runtime),
            "XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT": str(provider_runtime),
        },
        command_runner=_fake_runner({}),
    )

    memoryos_gate = json.loads((output_dir / "live-memoryos-status.json").read_text())
    natural_gate = json.loads(
        (output_dir / "natural-deliberation-status.json").read_text()
    )
    provider_gate = json.loads((output_dir / "real-provider-status.json").read_text())
    report = capture_release_readiness(
        artifacts_dir=tmp_path / "artifacts",
        output_path=tmp_path / "readiness.json",
    )

    assert summary["artifact_count"] == 4
    assert memoryos_gate["status"] == "ok"
    assert memoryos_gate["proof_level"] == "live_service_proof"
    assert memoryos_gate["artifacts"] == [str(memoryos_trace)]
    assert natural_gate["status"] == "ok"
    assert natural_gate["proof_level"] == "real_provider_proof"
    assert natural_gate["artifacts"] == [str(natural_transcript), str(natural_runtime)]
    assert provider_gate["status"] == "ok"
    assert provider_gate["proof_level"] == "real_provider_proof"
    assert provider_gate["artifacts"] == [str(provider_runtime)]
    assert {
        blocker["gate_id"] for blocker in report["blockers"]
    } == {"github-server-truth"}


def test_live_gate_status_capture_blocks_natural_transcript_without_runtime(
    tmp_path: Path,
) -> None:
    artifacts = tmp_path / "source-artifacts"
    natural_transcript = artifacts / "natural-transcript.json"
    _write_json(natural_transcript, _natural_transcript_artifact())

    output_dir = tmp_path / "artifacts" / "live_gate_status"
    capture_live_gate_status(
        output_dir=output_dir,
        env={"XMUSE_NATURAL_GOD_TRANSCRIPT_PATH": str(natural_transcript)},
        command_runner=_fake_runner({}),
    )

    natural_gate = json.loads(
        (output_dir / "natural-deliberation-status.json").read_text()
    )

    assert natural_gate["status"] == "blocked"
    assert natural_gate["proof_level"] == "manual_gap"
    assert "selected GOD runtime continuity" in natural_gate["summary"]
    assert natural_gate["artifacts"] == [str(natural_transcript)]


def test_live_gate_status_capture_cli_script_is_registered() -> None:
    pyproject = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    assert (
        pyproject["project"]["scripts"]["xmuse-live-gate-status-capture"]
        == "xmuse.live_gate_status_capture:main"
    )


def test_live_gate_status_capture_cli_accepts_github_truth_target_flags(
    tmp_path: Path,
    monkeypatch: Any,
) -> None:
    from xmuse import live_gate_status_capture as cli

    captured: dict[str, Any] = {}

    def fake_capture_live_gate_status(*, output_dir: Path, env: dict[str, str]):
        captured["output_dir"] = output_dir
        captured["env"] = env
        return {
            "schema_version": "xmuse.live_gate_status_capture.v1",
            "artifact_count": 0,
            "artifacts": [],
        }

    monkeypatch.setattr(cli, "capture_live_gate_status", fake_capture_live_gate_status)

    assert (
        cli.main(
            [
                "--output-dir",
                str(tmp_path),
                "--github-repo",
                "iiyazu/Cross-Muse",
                "--github-pull-request",
                "43",
                "--github-base-branch",
                "main",
                "--github-required-check",
                "quality-gates",
                "--github-required-check",
                "contract-smoke-gates",
                "--github-required-check",
                "real-runtime-integration-gate",
                "--github-expected-head-sha",
                "head-sha",
            ]
        )
        == 0
    )

    assert captured["output_dir"] == tmp_path
    env = captured["env"]
    assert env["XMUSE_GITHUB_TRUTH_REPO"] == "iiyazu/Cross-Muse"
    assert env["XMUSE_GITHUB_TRUTH_PULL_REQUEST"] == "43"
    assert env["XMUSE_GITHUB_TRUTH_BASE_BRANCH"] == "main"
    assert env["XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS"] == (
        "quality-gates,contract-smoke-gates,real-runtime-integration-gate"
    )
    assert env["XMUSE_GITHUB_TRUTH_EXPECTED_HEAD_SHA"] == "head-sha"


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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _memoryos_trace_artifact() -> dict[str, object]:
    return {
        "schema_version": "xmuse.memoryos_lite_trace.v1",
        "trace_id": "xmuse-memoryos-trace:live-gate-status",
        "proof_level": "live_service_proof",
        "fact_state": "observed",
        "namespace_uri": "memory://conversation/conv-live/god-review/thread-1",
        "session_id": "ses-live-1",
        "trace_events": [
            {
                "kind": "session_created",
                "metadata": {"xmuse_source_refs": ["conversation:conv-live"]},
            },
            {
                "kind": "context_built",
                "estimated_tokens": 96,
                "metadata": {"xmuse_source_refs": ["blueprint:bp-1"]},
            },
        ],
        "source_refs": ["conversation:conv-live", "blueprint:bp-1"],
        "target_refs": [
            "memoryos:namespace:memory://conversation/conv-live/god-review/thread-1",
            "memoryos:session:ses-live-1",
        ],
        "estimated_tokens": 96,
        "blockers": [],
    }


def _natural_transcript_artifact() -> dict[str, object]:
    return {
        "schema_version": "xmuse.operator_transcript.v1",
        "conversation_id": "conv-prod-1",
        "proof_level": "real_provider_proof",
        "fact_state": "observed",
        "natural_deliberation": True,
        "source_refs": ["memory://conversation/conv-prod-1/transcript"],
        "messages": [
            {
                "message_id": "msg-1",
                "conversation_id": "conv-prod-1",
                "god_id": "architect-god",
                "provider_id": "codex",
                "provider_profile": "codex-prod",
                "session_id": "codex-session-1",
                "speech_act": "propose",
                "decision_scope": "blueprint.freeze",
                "blocking": False,
            },
            {
                "message_id": "msg-2",
                "conversation_id": "conv-prod-1",
                "god_id": "review-god",
                "provider_id": "opencode",
                "provider_profile": "opencode-prod",
                "session_id": "opencode-session-1",
                "speech_act": "vote",
                "decision_scope": "blueprint.freeze",
                "blocking": False,
            },
        ],
        "blockers": [],
    }


def _god_runtime_artifact() -> dict[str, object]:
    return {
        "schema_version": "xmuse.god_runtime_continuity.v1",
        "conversation_id": "conv-prod-1",
        "proof_level": "contract_proof",
        "fact_state": "observed",
        "source_refs": ["god_cli_selection:conv-prod-1"],
        "items": [
            {
                "god_id": "architect-god",
                "cli_id": "codex.god",
                "peer_god_ready": True,
                "bounded": False,
                "provider_session_ready": True,
                "proof_level": "contract_proof",
                "source_refs": ["god_session:architect"],
            },
            {
                "god_id": "review-god",
                "cli_id": "opencode.peer",
                "peer_god_ready": True,
                "bounded": False,
                "provider_session_ready": True,
                "proof_level": "contract_proof",
                "source_refs": ["god_session:review"],
            },
        ],
    }


def _provider_runtime_artifact() -> dict[str, object]:
    return {
        "schema_version": "xmuse.real_provider_runtime.v1",
        "proof_level": "real_provider_proof",
        "fact_state": "observed",
        "run_id": "real-soak-pr43-live",
        "conversation_id": "conv-real-1",
        "source_refs": ["chat:conversation:conv-real-1"],
        "provider_runtime": {
            "provider_id": "codex",
            "runtime_backend": "ray",
            "transport": "codex-app-server",
            "provider_session_id": "codex-thread-1",
            "mcp_writeback": True,
        },
        "restart_resume": {
            "fresh_provider_session_id": "codex-thread-1",
            "resumed_provider_session_id": "codex-thread-1",
            "provider_session_reused": True,
        },
        "turns": [
            _provider_turn("turn-fresh-1", "fresh", 1.0),
            _provider_turn("turn-resume-1", "resume", 10.0),
        ],
        "blockers": [],
    }


def _provider_turn(turn_id: str, phase: str, offset: float) -> dict[str, object]:
    return {
        "turn_id": turn_id,
        "phase": phase,
        "delivery_mode": "mcp_writeback",
        "degraded_reason": None,
        "provider_id": "codex",
        "runtime_backend": "ray",
        "transport": "codex-app-server",
        "provider_session_id": "codex-thread-1",
        "stage_timings": {
            "ray_actor_delivery_start": {"at": offset + 1.0},
            "codex_app_server_turn_start": {"at": offset + 2.0},
            "chat_post_message": {"at": offset + 3.0},
            "trace_persisted": {"at": offset + 4.0},
        },
    }


class _FakeGhApiRunner:
    def __init__(self, responses: dict[str, object]) -> None:
        self.responses = responses
        self.commands: list[list[str]] = []

    def __call__(
        self,
        command: list[str],
        **_kwargs: Any,
    ) -> subprocess.CompletedProcess[str]:
        self.commands.append(command)
        endpoint = command[2]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout=json.dumps(self.responses[endpoint]),
            stderr="",
        )
