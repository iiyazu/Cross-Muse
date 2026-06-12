from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.execution.github_ops import (
    GitHubCliServerSideTruthClient,
    ReadOnlyGitHubServerSideTruthCollector,
    can_emit_pr_merged,
)
from xmuse_core.platform.github_truth_release_gate import (
    build_github_server_truth_release_gate,
)
from xmuse_core.platform.memoryos_live_release_gate import (
    capture_memoryos_live_release_gate,
)
from xmuse_core.platform.natural_deliberation_release_gate import (
    capture_natural_deliberation_release_gate,
)
from xmuse_core.platform.real_provider_runtime_release_gate import (
    capture_real_provider_runtime_release_gate,
)
from xmuse_core.platform.release_readiness import ReleaseGateKind

CommandRunner = Callable[[tuple[str, ...]], "ProbeResult"]
GitHubTruthRunner = Callable[..., subprocess.CompletedProcess[str]]

DEFAULT_REQUIRED_CHECKS = (
    "quality-gates",
    "contract-smoke-gates",
    "real-runtime-integration-gate",
)

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:TOKEN|API_KEY|SECRET|PASSWORD)[A-Z0-9_]*=)([^\s]+)"
    ),
    re.compile(r"(?i)\b(--(?:api-key|token|secret|password)\s+)([^\s]+)"),
    re.compile(r"(?i)\b(authorization:\s*bearer\s+)([^\s]+)"),
    re.compile(r"\bsk-[A-Za-z0-9._-]+\b"),
    re.compile(r"\b(?:secret|token)[-_][A-Za-z0-9._-]+\b", re.IGNORECASE),
)


@dataclass(frozen=True)
class ProbeResult:
    name: str
    command: tuple[str, ...]
    returncode: int
    stdout: str
    stderr: str

    def model_dump(self) -> dict[str, Any]:
        data = asdict(self)
        data["command"] = list(self.command)
        return data


def capture_live_gate_status(
    *,
    output_dir: str | Path,
    env: Mapping[str, str] | None = None,
    command_runner: CommandRunner | None = None,
    github_truth_runner: GitHubTruthRunner | None = None,
) -> dict[str, Any]:
    environment = os.environ if env is None else env
    runner = _run_probe if command_runner is None else command_runner
    probes = _collect_probes(runner)
    root = Path(output_dir)
    root.mkdir(parents=True, exist_ok=True)
    artifacts = [
        _memoryos_gate(environment, output_dir=root),
        _github_gate(
            environment,
            probes["github_auth"],
            output_dir=root,
            github_truth_runner=github_truth_runner,
        ),
        _provider_gate(environment, probes, output_dir=root),
        _natural_deliberation_gate(environment, output_dir=root),
    ]

    artifact_paths: list[str] = []
    for artifact in artifacts:
        path = root / _artifact_filename(str(artifact["gate_id"]))
        redacted = _redact_value(artifact)
        path.write_text(
            json.dumps(redacted, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        artifact_paths.append(str(path))

    summary = _redact_value(
        {
            "schema_version": "xmuse.live_gate_status_capture.v1",
            "generated_at": _utc_now(),
            "output_dir": str(root),
            "artifact_count": len(artifacts),
            "artifacts": artifact_paths,
            "probes": {
                name: probe.model_dump()
                for name, probe in sorted(probes.items(), key=lambda item: item[0])
            },
            "env_keys_present": sorted(_known_env_keys_present(environment)),
        }
    )
    return summary


def _collect_probes(runner: CommandRunner) -> dict[str, ProbeResult]:
    probe_commands = {
        "github_auth": ("gh", "auth", "status"),
        "codex_version": ("codex", "--version"),
        "opencode_version": ("opencode", "--version"),
        "ray_import": ("uv", "run", "python", "-c", "import ray; print(ray.__version__)"),
    }
    return {
        name: _normalize_probe_result(name, command, runner(command))
        for name, command in probe_commands.items()
    }


def _normalize_probe_result(
    name: str,
    command: tuple[str, ...],
    result: ProbeResult,
) -> ProbeResult:
    return ProbeResult(
        name=name,
        command=command,
        returncode=result.returncode,
        stdout=result.stdout.strip(),
        stderr=result.stderr.strip(),
    )


def _memoryos_gate(env: Mapping[str, str], *, output_dir: Path) -> dict[str, Any]:
    artifact_path = _clean_text(env.get("XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT"))
    if artifact_path is not None:
        return capture_memoryos_live_release_gate(
            artifact_path=artifact_path,
            output_path=output_dir / _artifact_filename("live-memoryos"),
        )
    source_refs = _present_keys(env, "XMUSE_LIVE_MEMORYOS_LITE", "XMUSE_MEMORYOS_LITE_URL")
    configured = bool(source_refs)
    return _gate(
        gate_id="live-memoryos",
        kind=ReleaseGateKind.LIVE_MEMORYOS,
        configured=configured,
        status="blocked" if configured else "manual_gap",
        summary=(
            "MemoryOS Lite configuration is present, but no live trace artifact was "
            "captured by this status command."
            if configured
            else "MemoryOS Lite live gate is required but not configured in this environment."
        ),
        attempted_command="uv run xmuse-memoryos-live-trace-capture",
        next_action=(
            "Run xmuse-memoryos-live-trace-capture against a configured MemoryOS "
            "Lite service, then convert the xmuse.memoryos_lite_trace.v1 artifact "
            "to a live_service_proof gate artifact."
        ),
        source_refs=source_refs,
    )


def _github_gate(
    env: Mapping[str, str],
    github_probe: ProbeResult,
    *,
    output_dir: Path,
    github_truth_runner: GitHubTruthRunner | None,
) -> dict[str, Any]:
    configured = github_probe.returncode == 0
    target = _github_truth_target(env)
    if configured and target is not None:
        captured = _capture_github_server_truth_gate(
            target,
            output_dir=output_dir,
            github_truth_runner=github_truth_runner,
        )
        if captured is not None:
            return captured
    return _gate(
        gate_id="github-server-truth",
        kind=ReleaseGateKind.GITHUB_SERVER_TRUTH,
        configured=configured,
        status="blocked" if configured else "manual_gap",
        summary=(
            "GitHub auth is available, but branch protection/ruleset/check/review "
            "server truth was not captured by this status command."
            if configured
            else "GitHub auth/server-truth visibility is required but unavailable."
        ),
        attempted_command="gh auth status",
        next_action=(
            "Run the GitHub server truth collector for the target PR/branch and "
            "write server_side_enforcement_proof."
        ),
        source_refs=["probe:gh auth status"],
    )


def _provider_gate(
    env: Mapping[str, str],
    probes: Mapping[str, ProbeResult],
    *,
    output_dir: Path,
) -> dict[str, Any]:
    artifact_path = _clean_text(env.get("XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT"))
    if artifact_path is not None:
        return capture_real_provider_runtime_release_gate(
            artifact_path=artifact_path,
            output_path=output_dir / _artifact_filename("real-provider-runtime"),
        )
    source_refs = _present_keys(
        env,
        "XMUSE_PEER_GOD_BACKEND",
        "XMUSE_EXECUTE_GOD_BACKEND",
        "XMUSE_REVIEW_GOD_BACKEND",
        "XMUSE_RAY_GOD_TRANSPORT",
        "XMUSE_RAY_GOD_MCP",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    )
    successful_probe_refs = [
        f"probe:{label}"
        for label, probe_name in (
            ("codex --version", "codex_version"),
            ("opencode --version", "opencode_version"),
            ("ray import", "ray_import"),
        )
        if probes[probe_name].returncode == 0
    ]
    configured = bool(source_refs or successful_probe_refs)
    return _gate(
        gate_id="real-provider-runtime",
        kind=ReleaseGateKind.REAL_PROVIDER,
        configured=configured,
        status="blocked" if configured else "manual_gap",
        summary=(
            "Provider/Ray/CLI capability is visible, but no real provider runtime "
            "soak artifact was captured by this status command."
            if configured
            else "Real provider/Ray/Codex/OpenCode gate is required but not configured."
        ),
        attempted_command="\n".join(
            [
                "codex --version",
                "opencode --version",
                "uv run python -c 'import ray; print(ray.__version__)'",
            ]
        ),
        next_action=(
            "Run the configured real provider/Ray/Codex/OpenCode runtime gate and "
            "write real_provider_proof."
        ),
        source_refs=source_refs + successful_probe_refs,
    )


def _natural_deliberation_gate(env: Mapping[str, str], *, output_dir: Path) -> dict[str, Any]:
    transcript_path = _clean_text(env.get("XMUSE_NATURAL_GOD_TRANSCRIPT_PATH"))
    if transcript_path is not None:
        return capture_natural_deliberation_release_gate(
            artifact_path=transcript_path,
            output_path=output_dir / _artifact_filename("natural-god-deliberation"),
        )
    source_refs = _present_keys(env, "XMUSE_NATURAL_GOD_TRANSCRIPT_PATH")
    configured = bool(source_refs)
    return _gate(
        gate_id="natural-god-deliberation",
        kind=ReleaseGateKind.NATURAL_DELIBERATION,
        configured=configured,
        status="blocked" if configured else "manual_gap",
        summary=(
            "A natural GOD transcript path is configured, but no real participant "
            "transcript proof was captured by this status command."
            if configured
            else "Natural GOD transcript gate is required but no transcript artifact is configured."
        ),
        attempted_command="uv run xmuse-chat-api / uv run xmuse-tui natural GOD session",
        next_action=(
            "Run a real selected-GOD deliberation session and export transcript "
            "evidence without relabeling deterministic replay."
        ),
        source_refs=source_refs,
    )


def _gate(
    *,
    gate_id: str,
    kind: ReleaseGateKind,
    configured: bool,
    status: str,
    summary: str,
    attempted_command: str,
    next_action: str,
    source_refs: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": gate_id,
        "kind": kind.value,
        "configured": configured,
        "required": True,
        "status": status,
        "proof_level": "manual_gap",
        "owner": "operator",
        "summary": summary,
        "attempted_command": attempted_command,
        "next_action": next_action,
        "source_refs": source_refs,
        "artifacts": [],
        "generated_at": _utc_now(),
    }


def _run_probe(command: tuple[str, ...]) -> ProbeResult:
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return ProbeResult(
            name=" ".join(command),
            command=command,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return ProbeResult(
            name=" ".join(command),
            command=command,
            returncode=124 if isinstance(exc, subprocess.TimeoutExpired) else 127,
            stdout="",
            stderr=str(exc),
        )


def _present_keys(env: Mapping[str, str], *keys: str) -> list[str]:
    return [key for key in keys if _has_value(env.get(key))]


def _known_env_keys_present(env: Mapping[str, str]) -> set[str]:
    keys = {
        "XMUSE_LIVE_MEMORYOS_LITE",
        "XMUSE_MEMORYOS_LITE_URL",
        "XMUSE_CHAT_API_AUTH_TOKEN",
        "XMUSE_CHAT_API_KEY",
        "XMUSE_MCP_AUTH_TOKEN",
        "XMUSE_MCP_API_KEY",
        "XMUSE_PEER_GOD_BACKEND",
        "XMUSE_EXECUTE_GOD_BACKEND",
        "XMUSE_REVIEW_GOD_BACKEND",
        "XMUSE_RAY_GOD_TRANSPORT",
        "XMUSE_RAY_GOD_MCP",
        "XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT",
        "XMUSE_NATURAL_GOD_TRANSCRIPT_PATH",
        "XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT",
        "XMUSE_GITHUB_TRUTH_REPO",
        "XMUSE_GITHUB_TRUTH_PULL_REQUEST",
        "XMUSE_GITHUB_TRUTH_BASE_BRANCH",
        "XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    }
    return {key for key in keys if _has_value(env.get(key))}


def _github_truth_target(env: Mapping[str, str]) -> dict[str, Any] | None:
    repo = _clean_text(env.get("XMUSE_GITHUB_TRUTH_REPO"))
    pull_request = _clean_text(env.get("XMUSE_GITHUB_TRUTH_PULL_REQUEST"))
    if repo is None and pull_request is None:
        return None
    if repo is None or pull_request is None:
        return {
            "error": (
                "GitHub server truth requires both XMUSE_GITHUB_TRUTH_REPO and "
                "XMUSE_GITHUB_TRUTH_PULL_REQUEST"
            )
        }
    try:
        pull_request_number = int(pull_request)
    except ValueError:
        return {"error": "XMUSE_GITHUB_TRUTH_PULL_REQUEST must be an integer"}
    if pull_request_number <= 0:
        return {"error": "XMUSE_GITHUB_TRUTH_PULL_REQUEST must be positive"}
    return {
        "repo": repo,
        "pull_request_number": pull_request_number,
        "base_branch": _clean_text(env.get("XMUSE_GITHUB_TRUTH_BASE_BRANCH")) or "main",
        "required_checks": _required_checks(env.get("XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS")),
    }


def _capture_github_server_truth_gate(
    target: dict[str, Any],
    *,
    output_dir: Path,
    github_truth_runner: GitHubTruthRunner | None,
) -> dict[str, Any] | None:
    error = _clean_text(target.get("error"))
    if error is not None:
        return _github_truth_config_error_gate(error)
    raw_path = output_dir / "github-server-truth-snapshot.json"
    base_branch = str(target["base_branch"])
    try:
        client = GitHubCliServerSideTruthClient(
            base_branch=base_branch,
            runner=github_truth_runner,
        )
        collector = ReadOnlyGitHubServerSideTruthCollector(client=client)
        evidence = collector.collect(
            repo=str(target["repo"]),
            pull_request_number=int(target["pull_request_number"]),
            required_checks=list(target["required_checks"]),
        )
        payload = evidence.model_dump(mode="json")
        payload["schema_version"] = "github_server_side_truth_capture.v1"
        payload["can_emit_pr_merged"] = can_emit_pr_merged(evidence)
        payload["merged"] = payload["can_emit_pr_merged"] is True
        payload["capture_mode"] = "opt_in_read_only_gh_api"
        raw_path.write_text(
            json.dumps(_redact_value(payload), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return build_github_server_truth_release_gate(
            payload,
            artifact_path=raw_path,
            base_branch=base_branch,
        )
    except Exception as exc:
        return _github_truth_config_error_gate(
            f"GitHub server truth capture failed: {exc}"
        )


def _github_truth_config_error_gate(summary: str) -> dict[str, Any]:
    return _gate(
        gate_id="github-server-truth",
        kind=ReleaseGateKind.GITHUB_SERVER_TRUTH,
        configured=True,
        status="blocked",
        summary=summary,
        attempted_command="uv run python scripts/github_server_truth_capture.py",
        next_action=(
            "Fix XMUSE_GITHUB_TRUTH_* configuration and rerun the GitHub "
            "server truth collector."
        ),
        source_refs=[
            "env:XMUSE_GITHUB_TRUTH_REPO",
            "env:XMUSE_GITHUB_TRUTH_PULL_REQUEST",
        ],
    )


def _required_checks(value: str | None) -> list[str]:
    configured = _clean_text(value)
    if configured is None:
        return list(DEFAULT_REQUIRED_CHECKS)
    checks = [item.strip() for item in configured.split(",") if item.strip()]
    return checks or list(DEFAULT_REQUIRED_CHECKS)


def _has_value(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def _clean_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _artifact_filename(gate_id: str) -> str:
    aliases = {
        "natural-god-deliberation": "natural-deliberation",
        "real-provider-runtime": "real-provider",
    }
    gate_id = aliases.get(gate_id, gate_id)
    return f"{gate_id}-status.json"


def _redact_value(value: Any) -> Any:
    if isinstance(value, str):
        return _redact_text(value)
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    return value


def _redact_text(value: str) -> str:
    redacted = value
    for pattern in _SECRET_PATTERNS[:3]:
        redacted = pattern.sub(r"\1<redacted>", redacted)
    for pattern in _SECRET_PATTERNS[3:]:
        redacted = pattern.sub("<redacted>", redacted)
    return redacted


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
