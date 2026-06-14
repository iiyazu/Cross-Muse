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

CommandRunner = Callable[[tuple[str, ...]], "ProbeResult"]

_SECRET_PATTERNS = (
    re.compile(
        r"(?i)\b([A-Z0-9_]*(?:TOKEN|API_KEY|SECRET|PASSWORD)[A-Z0-9_]*=)([^\s]+)"
    ),
    re.compile(r"(?i)\b(--(?:api-key|token|secret|password)\s+)([^\s]+)"),
    re.compile(r"(?i)\b(authorization:\s*bearer\s+)([^\s]+)"),
    re.compile(r"\bsk-[A-Za-z0-9._-]+\b"),
    re.compile(r"\bgh[opsu]_[A-Za-z0-9_*]+"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]+\b"),
    re.compile(r"\b(?:secret|token)[-_][A-Za-z0-9._-]+\b", re.IGNORECASE),
)

_KNOWN_ENV_KEYS = {
    "XMUSE_CHAT_API_AUTH_TOKEN",
    "XMUSE_CHAT_API_KEY",
    "XMUSE_DEPLOYMENT_PROFILE",
    "XMUSE_EXECUTE_GOD_BACKEND",
    "XMUSE_GITHUB_TRUTH_BASE_BRANCH",
    "XMUSE_GITHUB_TRUTH_EXPECTED_HEAD_SHA",
    "XMUSE_GITHUB_TRUTH_PULL_REQUEST",
    "XMUSE_GITHUB_TRUTH_REPO",
    "XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS",
    "XMUSE_LIVE_MEMORYOS_LITE",
    "XMUSE_MCP_API_KEY",
    "XMUSE_MCP_AUTH_TOKEN",
    "XMUSE_MEMORYOS_LITE_URL",
    "XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT",
    "XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT",
    "XMUSE_NATURAL_GOD_TRANSCRIPT_PATH",
    "XMUSE_PEER_GOD_BACKEND",
    "XMUSE_RAY_GOD_MCP",
    "XMUSE_RAY_GOD_TRANSPORT",
    "XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT",
    "XMUSE_REVIEW_GOD_BACKEND",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
}


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


def capture_production_baseline(
    *,
    repo_root: str | Path,
    output_path: str | Path | None = None,
    env: Mapping[str, str] | None = None,
    command_runner: CommandRunner | None = None,
) -> dict[str, Any]:
    root = Path(repo_root)
    environment = os.environ if env is None else env
    runner = command_runner or (lambda command: _run_probe(command, cwd=root))
    probes = _collect_probes(runner)
    package_boundary = _package_boundary(root)
    live_resources = _live_resources(environment, probes)
    blockers = _unique(
        [
            *package_boundary["blockers"],
            *[
                blocker
                for resource in live_resources.values()
                for blocker in resource["blockers"]
            ],
        ]
    )
    report = _redact_value(
        {
            "schema_version": "xmuse.production_baseline.v1",
            "stage_id": "S0",
            "action": "production_baseline_capture",
            "status": "blocked" if blockers else "ok",
            "proof_level": "contract_proof",
            "source_authority": "local_repository_and_environment",
            "generated_at": _utc_now(),
            "repo_root": str(root),
            "git": _git_state(probes),
            "package_boundary": package_boundary,
            "env_keys_present": sorted(_known_env_keys_present(environment)),
            "live_resources": live_resources,
            "probes": {
                name: probe.model_dump()
                for name, probe in sorted(probes.items(), key=lambda item: item[0])
            },
            "blockers": blockers,
            "owner": "operator",
            "next_action": _next_action(blockers),
        }
    )
    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return report


def _collect_probes(runner: CommandRunner) -> dict[str, ProbeResult]:
    commands = {
        "git_status": ("git", "status", "--short", "--branch"),
        "git_head": ("git", "rev-parse", "HEAD"),
        "github_auth": ("gh", "auth", "status"),
        "codex_version": ("codex", "--version"),
        "opencode_version": ("opencode", "--version"),
        "ray_import": ("uv", "run", "python", "-c", "import ray; print(ray.__version__)"),
    }
    return {
        name: _normalize_probe_result(name, command, runner(command))
        for name, command in commands.items()
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


def _git_state(probes: Mapping[str, ProbeResult]) -> dict[str, Any]:
    status_probe = probes["git_status"]
    status_lines = [line for line in status_probe.stdout.splitlines() if line.strip()]
    branch_line = status_lines[0] if status_lines and status_lines[0].startswith("## ") else None
    dirty_lines = [
        line
        for line in status_lines
        if not line.startswith("## ") and line.strip()
    ]
    head_probe = probes["git_head"]
    head_sha = head_probe.stdout.strip() if head_probe.returncode == 0 else None
    return {
        "head_sha": head_sha or None,
        "branch": branch_line[3:] if branch_line else None,
        "dirty": bool(dirty_lines) or status_probe.returncode != 0,
        "status_returncode": status_probe.returncode,
        "dirty_entries": dirty_lines,
    }


def _package_boundary(repo_root: Path) -> dict[str, Any]:
    init_path = repo_root / "xmuse" / "__init__.py"
    exists = init_path.exists()
    return {
        "xmuse_init_absent": not exists,
        "status": "blocked" if exists else "ok",
        "source_refs": ["path:xmuse/__init__.py"],
        "blockers": ["xmuse_init_py_exists"] if exists else [],
    }


def _live_resources(
    env: Mapping[str, str],
    probes: Mapping[str, ProbeResult],
) -> dict[str, dict[str, Any]]:
    return {
        "memoryos_lite": _memoryos_resource(env),
        "github": _github_resource(env, probes["github_auth"]),
        "provider_runtime": _provider_resource(env, probes),
        "natural_deliberation": _natural_resource(env),
        "chat_api": _token_resource(
            env,
            "chat_api",
            ("XMUSE_CHAT_API_AUTH_TOKEN", "XMUSE_CHAT_API_KEY"),
            "chat_api_write_auth_missing",
        ),
        "mcp": _token_resource(
            env,
            "mcp",
            ("XMUSE_MCP_AUTH_TOKEN", "XMUSE_MCP_API_KEY"),
            "mcp_write_auth_missing",
        ),
    }


def _memoryos_resource(env: Mapping[str, str]) -> dict[str, Any]:
    configured = env.get("XMUSE_LIVE_MEMORYOS_LITE") == "1" and _has_value(
        env.get("XMUSE_MEMORYOS_LITE_URL")
    )
    artifact_configured = _has_value(env.get("XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT"))
    blockers = []
    if configured and not artifact_configured:
        blockers.append("memoryos_live_trace_artifact_missing")
    if not configured:
        blockers.append("memoryos_lite_live_environment_missing")
    return {
        "configured": configured,
        "available": configured,
        "artifact_configured": artifact_configured,
        "env_keys_present": _present_keys(
            env,
            "XMUSE_LIVE_MEMORYOS_LITE",
            "XMUSE_MEMORYOS_LITE_URL",
            "XMUSE_MEMORYOS_LIVE_TRACE_ARTIFACT",
        ),
        "proof_level": "manual_gap" if blockers else "contract_proof",
        "blockers": blockers,
        "next_action": (
            "Run uv run xmuse-memoryos-live-trace-capture and attach the produced "
            "xmuse.memoryos_lite_trace.v1 artifact."
        ),
    }


def _github_resource(env: Mapping[str, str], probe: ProbeResult) -> dict[str, Any]:
    target_configured = _has_value(env.get("XMUSE_GITHUB_TRUTH_REPO")) and _has_value(
        env.get("XMUSE_GITHUB_TRUTH_PULL_REQUEST")
    )
    available = probe.returncode == 0
    blockers = []
    if not available:
        blockers.append("github_auth_unavailable")
    if available and not target_configured:
        blockers.append("github_truth_target_missing")
    if available and target_configured:
        blockers.append("github_server_truth_capture_pending")
    return {
        "configured": target_configured,
        "available": available,
        "env_keys_present": _present_keys(
            env,
            "XMUSE_GITHUB_TRUTH_REPO",
            "XMUSE_GITHUB_TRUTH_PULL_REQUEST",
            "XMUSE_GITHUB_TRUTH_BASE_BRANCH",
            "XMUSE_GITHUB_TRUTH_REQUIRED_CHECKS",
            "XMUSE_GITHUB_TRUTH_EXPECTED_HEAD_SHA",
        ),
        "proof_level": "manual_gap",
        "blockers": blockers,
        "next_action": (
            "Run the GitHub server truth collector for the target PR and keep "
            "review/merge truth separate from enforcement truth."
        ),
    }


def _provider_resource(
    env: Mapping[str, str],
    probes: Mapping[str, ProbeResult],
) -> dict[str, Any]:
    env_configured = bool(
        _present_keys(
            env,
            "XMUSE_PEER_GOD_BACKEND",
            "XMUSE_EXECUTE_GOD_BACKEND",
            "XMUSE_REVIEW_GOD_BACKEND",
            "XMUSE_RAY_GOD_TRANSPORT",
            "XMUSE_RAY_GOD_MCP",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
        )
    )
    available_probe_refs = [
        name
        for name in ("codex_version", "opencode_version", "ray_import")
        if probes[name].returncode == 0
    ]
    available = bool(available_probe_refs)
    artifact_configured = _has_value(env.get("XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT"))
    blockers = []
    if (env_configured or available) and not artifact_configured:
        blockers.append("real_provider_runtime_artifact_missing")
    if not env_configured and not available:
        blockers.append("provider_runtime_unavailable")
    return {
        "configured": env_configured,
        "available": available,
        "available_probe_refs": available_probe_refs,
        "artifact_configured": artifact_configured,
        "env_keys_present": _present_keys(
            env,
            "XMUSE_PEER_GOD_BACKEND",
            "XMUSE_EXECUTE_GOD_BACKEND",
            "XMUSE_REVIEW_GOD_BACKEND",
            "XMUSE_RAY_GOD_TRANSPORT",
            "XMUSE_RAY_GOD_MCP",
            "XMUSE_REAL_PROVIDER_RUNTIME_ARTIFACT",
            "OPENAI_API_KEY",
            "DEEPSEEK_API_KEY",
        ),
        "proof_level": "manual_gap",
        "blockers": blockers,
        "next_action": (
            "Capture a real provider runtime soak artifact with durable session "
            "reuse, MCP writeback, and ordered stage timings."
        ),
    }


def _natural_resource(env: Mapping[str, str]) -> dict[str, Any]:
    transcript_configured = _has_value(env.get("XMUSE_NATURAL_GOD_TRANSCRIPT_PATH"))
    runtime_configured = _has_value(env.get("XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT"))
    blockers = []
    if not transcript_configured:
        blockers.append("natural_god_transcript_artifact_missing")
    if transcript_configured and not runtime_configured:
        blockers.append("natural_god_runtime_artifact_missing")
    return {
        "configured": transcript_configured or runtime_configured,
        "available": transcript_configured and runtime_configured,
        "transcript_configured": transcript_configured,
        "runtime_configured": runtime_configured,
        "env_keys_present": _present_keys(
            env,
            "XMUSE_NATURAL_GOD_TRANSCRIPT_PATH",
            "XMUSE_NATURAL_GOD_RUNTIME_ARTIFACT",
        ),
        "proof_level": "manual_gap",
        "blockers": blockers,
        "next_action": (
            "Export a real multi-GOD transcript and selected-GOD runtime continuity "
            "artifact before converting natural deliberation proof."
        ),
    }


def _token_resource(
    env: Mapping[str, str],
    resource_id: str,
    keys: tuple[str, ...],
    missing_blocker: str,
) -> dict[str, Any]:
    configured = bool(_present_keys(env, *keys))
    return {
        "configured": configured,
        "available": configured,
        "env_keys_present": _present_keys(env, *keys),
        "proof_level": "contract_proof" if configured else "manual_gap",
        "blockers": [] if configured else [missing_blocker],
        "next_action": (
            f"Configure {resource_id} write auth token/capability bundle for production "
            "operator actions."
        ),
    }


def _next_action(blockers: list[str]) -> str | None:
    if not blockers:
        return None
    return (
        "Resolve or record the listed S0 blockers before treating the overnight "
        "run as production-ready; independent stages may continue with manual_gap evidence."
    )


def _run_probe(command: tuple[str, ...], *, cwd: Path) -> ProbeResult:
    try:
        completed = subprocess.run(  # noqa: S603
            command,
            cwd=cwd,
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
    return {key for key in _KNOWN_ENV_KEYS if _has_value(env.get(key))}


def _has_value(value: str | None) -> bool:
    return value is not None and value.strip() != ""


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


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
