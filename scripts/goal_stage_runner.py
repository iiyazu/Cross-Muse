from __future__ import annotations

import argparse
import json
import os
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

DEFAULT_GOAL_ENGINE = "codex"
DEFAULT_CLI_TIMEOUT_SECONDS = 1800
DEFAULT_OPENCODE_RUN_MODEL = "opencode-go/deepseek-v4-flash"
DEFAULT_OPENCODE_RUN_VARIANT = "max"
DEFAULT_CODEX_MODEL = os.getenv("GOAL_CODEX_MODEL", "gpt-5.5")


StageStatus = Literal["ok", "retry", "blocked"]


def _utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class StageManifest:
    stage_id: str
    objective: str
    scope: list[str]
    acceptance_contracts: list[str]
    owner: str | None = None
    max_retries: int = 1
    risk: str = "medium"
    constraints: list[str] | None = None
    escalation_triggers: list[str] | None = None
    prompt: str | None = None
    engine_hint: str | None = None
    worker_kind: str | None = None
    candidate_patch: bool = False
    allowed_files: list[str] | None = None
    forbidden_paths: list[str] | None = None
    allowed_actions: list[str] | None = None
    forbidden_actions: list[str] | None = None
    closure: dict[str, Any] | None = None
    task_understanding: dict[str, Any] | None = None
    invariants: dict[str, Any] | None = None
    verification: dict[str, Any] | None = None
    evidence_summary: dict[str, Any] | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> StageManifest:
        return cls(
            stage_id=str(payload.get("stage_id", "")).strip(),
            objective=str(payload.get("objective", "")).strip(),
            scope=_normalize_list(payload.get("scope"), "scope"),
            acceptance_contracts=_normalize_list(
                payload.get("acceptance_contracts"), "acceptance_contracts"
            ),
            owner=_normalize_optional_str(payload.get("owner")),
            max_retries=max(0, int(payload.get("max_retries", 1))),
            risk=_normalize_optional_str(payload.get("risk"), default="medium") or "medium",
            constraints=_normalize_optional_list(payload.get("constraints")),
            escalation_triggers=_normalize_optional_list(payload.get("escalation_triggers")),
            prompt=_normalize_optional_str(payload.get("prompt")),
            engine_hint=_normalize_optional_str(payload.get("engine")),
            worker_kind=_normalize_optional_str(payload.get("worker_kind")),
            candidate_patch=_normalize_bool(payload.get("candidate_patch")),
            allowed_files=_normalize_optional_list(payload.get("allowed_files")),
            forbidden_paths=_normalize_optional_list(payload.get("forbidden_paths")),
            allowed_actions=_normalize_optional_list(payload.get("allowed_actions")),
            forbidden_actions=_normalize_optional_list(payload.get("forbidden_actions")),
            closure=_normalize_optional_mapping(payload.get("closure"), "closure"),
            task_understanding=_normalize_optional_mapping(
                payload.get("task_understanding"), "task_understanding"
            ),
            invariants=_normalize_optional_mapping(payload.get("invariants"), "invariants"),
            verification=_normalize_optional_mapping(payload.get("verification"), "verification"),
            evidence_summary=_normalize_optional_mapping(
                payload.get("evidence_summary"), "evidence_summary"
            ),
        )


def _normalize_list(value: Any, field_name: str) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list of strings")
    normalized: list[str] = []
    for item in value:
        if item is None:
            continue
        text = str(item).strip()
        if text:
            normalized.append(text)
    return normalized


def _normalize_optional_list(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("value must be a list")
    normalized = [str(item).strip() for item in value if str(item).strip()]
    return normalized


def _normalize_optional_str(value: Any, *, default: str | None = None) -> str | None:
    if value is None:
        return default
    text = str(value).strip()
    if not text:
        return default
    return text


def _normalize_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    if value is None:
        return False
    return bool(value)


def _normalize_optional_mapping(value: Any, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return dict(value)


def _validate_manifest(manifest: StageManifest) -> list[str]:
    issues: list[str] = []
    if not manifest.stage_id:
        issues.append("stage_manifest is missing required field: stage_id")
    if not manifest.objective:
        issues.append("stage_manifest is missing required field: objective")
    if manifest.candidate_patch and not (manifest.allowed_files or manifest.scope):
        issues.append("candidate_patch stages require allowed_files or scope")
    return issues


def _build_prompt(manifest: StageManifest, evidence_dir: Path) -> str:
    scope_lines = "\n".join(f"- {item}" for item in (manifest.scope or ["(not specified)"]))
    acceptance_lines = "\n".join(
        f"- {item}" for item in manifest.acceptance_contracts or ["(not specified)"]
    )
    constraint_lines = _join_bullets(manifest.constraints)
    escalation_lines = _join_bullets(manifest.escalation_triggers)
    allowed_file_lines = _join_bullets(manifest.allowed_files or manifest.scope)
    forbidden_path_lines = _join_bullets(_default_forbidden_paths(manifest))
    allowed_action_lines = _join_bullets(manifest.allowed_actions)
    forbidden_action_lines = _join_bullets(_default_forbidden_actions(manifest))
    structured_sections = _structured_prompt_sections(manifest)

    base_prompt = manifest.prompt or ""
    if base_prompt:
        base_prompt = base_prompt.strip() + "\n\n"

    return (
        f"{base_prompt}"
        f"Stage: {manifest.stage_id}\n"
        f"Objective: {manifest.objective}\n"
        f"Scope:\n{scope_lines}\n"
        f"Acceptance Contracts:\n{acceptance_lines}\n"
        f"Risk: {manifest.risk}\n"
        f"Max retries: {manifest.max_retries}\n"
        f"Owner: {manifest.owner or 'unassigned'}\n"
        f"Evidence directory: {evidence_dir}\n"
        f"Constraints:\n{constraint_lines}\n"
        f"Escalation triggers:\n{escalation_lines}\n"
        "\nOpenCode Candidate Patch Gate:\n"
        f"Worker kind: {manifest.worker_kind or 'unspecified'}\n"
        f"Candidate patch: {str(manifest.candidate_patch).lower()}\n"
        "Allowed files:\n"
        f"{allowed_file_lines}\n"
        "Forbidden paths:\n"
        f"{forbidden_path_lines}\n"
        "Allowed actions:\n"
        f"{allowed_action_lines}\n"
        "Forbidden actions:\n"
        f"{forbidden_action_lines}\n"
        "Candidate patch rules:\n"
        "- Treat any edits as candidate patch only.\n"
        "- Stay inside allowed files and scope.\n"
        "- Do not commit, push, write runtime state, or claim completion.\n"
        "- Do not change proof levels or delete manual_gap without explicit evidence.\n"
        "- Report changed files, tests attempted, blockers, and residual risk.\n"
        f"{structured_sections}"
        f"{_output_requirement(manifest)}"
    )


def _join_bullets(items: list[str] | None) -> str:
    if not items:
        return "- (none)"
    return "\n".join(f"- {item}" for item in items)


def _default_forbidden_paths(manifest: StageManifest) -> list[str]:
    defaults = [
        "xmuse/__init__.py",
        "feature_lanes.json",
        "xmuse/work/",
        "xmuse/history/",
        "xmuse/logs/",
        "*.db",
        "*.sqlite3",
        "*.jsonl",
    ]
    return [*defaults, *(manifest.forbidden_paths or [])]


def _default_forbidden_actions(manifest: StageManifest) -> list[str]:
    defaults = [
        "commit",
        "push",
        "write_runtime_state",
        "read_or_write_secrets",
        "bypass_authority_contracts",
        "expand_scope",
    ]
    return [*defaults, *(manifest.forbidden_actions or [])]


def _structured_prompt_sections(manifest: StageManifest) -> str:
    sections = [
        ("Closure contract", manifest.closure),
        ("Task understanding", manifest.task_understanding),
        ("Invariants", manifest.invariants),
        ("Verification", manifest.verification),
        ("Evidence summary expectation", manifest.evidence_summary),
    ]
    rendered = ""
    for title, payload in sections:
        if payload is None:
            continue
        rendered += f"\n{title}:\n{_json_block(payload)}\n"
    return rendered


def _json_block(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)


def _output_requirement(manifest: StageManifest) -> str:
    if manifest.candidate_patch:
        return (
            "\nOutput requirement: produce a bounded candidate patch or audit summary, "
            "then explain changed files, validation attempted, blockers, and residual risk."
        )
    return "\nOutput requirement: produce only structured evidence updates, no direct state writes."


def _manifest_metadata(manifest: StageManifest) -> dict[str, Any]:
    return {
        "worker_kind": manifest.worker_kind,
        "candidate_patch": manifest.candidate_patch,
        "allowed_files": manifest.allowed_files,
        "forbidden_paths": manifest.forbidden_paths,
        "allowed_actions": manifest.allowed_actions,
        "forbidden_actions": manifest.forbidden_actions,
        "closure": manifest.closure,
        "evidence_summary": manifest.evidence_summary,
    }


def _with_manifest_metadata(result: dict[str, Any], manifest: StageManifest) -> dict[str, Any]:
    enriched = dict(result)
    for key, value in _manifest_metadata(manifest).items():
        if value is not None:
            enriched[key] = value
    return enriched


@dataclass(frozen=True)
class StagePaths:
    output: Path
    prompt: Path
    manifest_log: Path
    evidence_dir: Path
    runner_log: Path


def _stage_paths(output: Path) -> StagePaths:
    evidence_dir = output.parent / f"{output.name}.evidence"
    return StagePaths(
        output=output,
        prompt=output.parent / f"{output.name}.prompt.txt",
        manifest_log=output.parent / f"{output.name}.manifest.jsonl",
        evidence_dir=evidence_dir,
        runner_log=evidence_dir / "engine_output.txt",
    )


def _pick_command(engine: str, repo_root: Path, prompt_path: Path) -> list[str]:
    if engine == "codex":
        return [
            "codex",
            "exec",
            "-m",
            DEFAULT_CODEX_MODEL,
            "--dangerously-bypass-approvals-and-sandbox",
            "-",
        ]
    if engine == "opencode":
        return [
            "opencode",
            "run",
            "--model",
            DEFAULT_OPENCODE_RUN_MODEL,
            "--variant",
            DEFAULT_OPENCODE_RUN_VARIANT,
            "--format",
            "json",
            "--dir",
            str(repo_root),
            "Execute the attached goal stage prompt.",
            "--file",
            str(prompt_path),
        ]
    raise ValueError(f"unsupported engine: {engine}")


def _classify_status(
    result: subprocess.CompletedProcess[str],
    max_retries: int,
    previous_retries: int,
) -> StageStatus:
    if result.returncode == 0:
        return "ok"
    if previous_retries >= max_retries:
        return "blocked"
    return "retry"


def _is_recoverable_error(output: str) -> bool:
    lowered = output.lower()
    return any(
        token in lowered
        for token in [
            "timeout",
            "network",
            "rate limit",
            "429",
            "econnreset",
            "temporary",
            "retry",
        ]
    )


def _build_retry_hint(returncode: int, output: str) -> str:
    if returncode == 124:
        return "Retry with longer timeout or smaller scope."
    if _is_recoverable_error(output):
        return "Retry once; if repeated, switch to codex."
    return "Check manifest scope/permissions and rerun with corrected constraints."


def _write_result(path: Path, payload: dict[str, Any]) -> None:
    payload = dict(payload)
    payload["timestamp_utc"] = _utcnow()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_manifest_line(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        compact = json.dumps(payload, ensure_ascii=False)
        handle.write(compact + "\n")


def _as_issue_list(message: str, context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    issue: dict[str, Any] = {"message": message}
    if context:
        issue["context"] = context
    return [issue]


def _count_previous_retries(manifest_log: Path, stage_id: str) -> int:
    if not manifest_log.exists():
        return 0
    retries = 0
    for line in manifest_log.read_text(encoding="utf-8").splitlines():
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("stage_id") == stage_id and payload.get("status") == "retry":
            retries += 1
    return retries


def _blocked_manifest_result(
    *,
    stage_id: str,
    engine: str,
    paths: StagePaths,
    message: str,
    context: dict[str, Any] | None = None,
) -> int:
    result = {
        "stage_id": stage_id,
        "status": "blocked",
        "engine": engine,
        "issues": _as_issue_list(message, context),
        "review_decision": "blocked",
        "retry_hint": "Fix stage manifest fields before rerun.",
        "evidence_dir": str(paths.evidence_dir),
        "agent_output_path": str(paths.output),
        "command": [],
    }
    paths.runner_log.write_text(message + "\n", encoding="utf-8")
    _write_result(paths.output, result)
    _append_manifest_line(paths.manifest_log, result)
    return 2


def run_stage(
    *,
    stage_manifest_path: Path,
    engine: str,
    repo_root: Path,
    output: Path,
    timeout_seconds: int,
    dry_run: bool,
) -> int:
    paths = _stage_paths(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    paths.evidence_dir.mkdir(parents=True, exist_ok=True)

    chosen_engine = engine or DEFAULT_GOAL_ENGINE
    if chosen_engine == "auto":
        chosen_engine = DEFAULT_GOAL_ENGINE

    try:
        payload = json.loads(stage_manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("stage manifest must be a JSON object")
        manifest = StageManifest.from_dict(payload)
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return _blocked_manifest_result(
            stage_id="unknown",
            engine=chosen_engine,
            paths=paths,
            message=f"Invalid stage manifest: {exc}",
            context={"stage_manifest": str(stage_manifest_path)},
        )

    issues = _validate_manifest(manifest)
    if engine == "auto" and manifest.engine_hint:
        chosen_engine = manifest.engine_hint

    if chosen_engine not in {"codex", "opencode"}:
        issues.append(f"unsupported engine: {chosen_engine}")

    prompt = _build_prompt(manifest, paths.evidence_dir)
    paths.prompt.write_text(prompt, encoding="utf-8")

    if issues:
        issue_message = "; ".join(issues)
        result = _with_manifest_metadata(
            {
                "stage_id": manifest.stage_id,
                "status": "blocked",
                "engine": chosen_engine,
                "issues": _as_issue_list(issue_message),
                "review_decision": "blocked",
                "retry_hint": "Fix stage manifest fields before rerun.",
                "evidence_dir": str(paths.evidence_dir),
                "agent_output_path": str(output),
                "command": [],
            },
            manifest,
        )
        paths.runner_log.write_text(issue_message + "\n", encoding="utf-8")
        _write_result(output, result)
        _append_manifest_line(paths.manifest_log, result)
        return 2

    command = _pick_command(chosen_engine, repo_root=repo_root, prompt_path=paths.prompt)
    command_repr = " ".join(command)

    if dry_run:
        dry_run_message = "Dry run generated prompt and command but did not execute stage."
        result = _with_manifest_metadata(
            {
                "stage_id": manifest.stage_id,
                "status": "blocked",
                "engine": chosen_engine,
                "issues": _as_issue_list(dry_run_message),
                "review_decision": "dry_run",
                "retry_hint": "Run the same stage without --dry-run before advancing.",
                "evidence_dir": str(paths.evidence_dir),
                "agent_output_path": str(output),
                "command": command,
                "agent_stdout_path": str(paths.runner_log),
            },
            manifest,
        )
        paths.runner_log.write_text(dry_run_message + "\n", encoding="utf-8")
        _write_result(output, result)
        _append_manifest_line(paths.manifest_log, result)
        return 0

    try:
        completed = subprocess.run(
            command,
            cwd=str(repo_root),
            capture_output=True,
            input=prompt if chosen_engine == "codex" else None,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:
        result = _with_manifest_metadata(
            {
                "stage_id": manifest.stage_id,
                "status": "blocked",
                "engine": chosen_engine,
                "issues": _as_issue_list(
                    f"Command not found: {exc}",
                    {"command": command_repr},
                ),
                "review_decision": "blocked",
                "retry_hint": "Install command and retry; otherwise switch engine explicitly.",
                "evidence_dir": str(paths.evidence_dir),
                "agent_output_path": str(output),
                "command": command,
                "agent_stdout_path": str(paths.runner_log),
            },
            manifest,
        )
        _write_result(output, result)
        _append_manifest_line(paths.manifest_log, result)
        return 2
    except subprocess.TimeoutExpired as exc:
        previous_retries = _count_previous_retries(paths.manifest_log, manifest.stage_id)
        status = "blocked" if previous_retries >= manifest.max_retries else "retry"
        result = _with_manifest_metadata(
            {
                "stage_id": manifest.stage_id,
                "status": status,
                "engine": chosen_engine,
                "issues": _as_issue_list(
                    f"Engine invocation timed out: {exc}",
                    {"command": command_repr},
                ),
                "review_decision": status,
                "retry_hint": _build_retry_hint(124, "timeout"),
                "evidence_dir": str(paths.evidence_dir),
                "agent_output_path": str(output),
                "command": command,
                "agent_stdout_path": str(paths.runner_log),
                "attempt": previous_retries + 1,
            },
            manifest,
        )
        paths.runner_log.write_text(
            _timeout_output(exc),
            encoding="utf-8",
        )
        _write_result(output, result)
        _append_manifest_line(paths.manifest_log, result)
        return 1 if status == "retry" else 2

    paths.runner_log.write_text(
        completed.stdout + ("\n---STDERR---\n" + completed.stderr if completed.stderr else ""),
        encoding="utf-8",
    )

    previous_retries = _count_previous_retries(paths.manifest_log, manifest.stage_id)
    status = _classify_status(completed, manifest.max_retries, previous_retries)
    issues_out = [] if completed.returncode == 0 else [
        {
            "message": f"Engine returned non-zero exit: {completed.returncode}",
            "context": {
                "stdout_tail": completed.stdout[-1200:],
                "stderr_tail": completed.stderr[-1200:],
            },
        }
    ]

    result = _with_manifest_metadata(
        {
            "stage_id": manifest.stage_id,
            "status": status,
            "engine": chosen_engine,
            "issues": issues_out,
            "review_decision": "pass" if status == "ok" else status,
            "retry_hint": _build_retry_hint(
                completed.returncode,
                completed.stdout + "\n" + completed.stderr,
            )
            if status != "ok"
            else None,
            "evidence_dir": str(paths.evidence_dir),
            "agent_output_path": str(output),
            "command": command,
            "agent_stdout_path": str(paths.runner_log),
            "returncode": completed.returncode,
            "attempt": previous_retries + 1,
        },
        manifest,
    )
    _write_result(output, result)
    _append_manifest_line(paths.manifest_log, result)
    return 0 if status == "ok" else 1 if status == "retry" else 2


def _timeout_output(exc: subprocess.TimeoutExpired) -> str:
    stdout = _decode_timeout_stream(exc.stdout)
    stderr = _decode_timeout_stream(exc.stderr)
    return stdout + "\n" + stderr


def _decode_timeout_stream(value: bytes | str | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one /goal execution stage through bounded engine command",
    )
    parser.add_argument(
        "--stage-manifest",
        type=Path,
        required=True,
        help="Path to stage manifest JSON file",
    )
    parser.add_argument(
        "--engine",
        default="auto",
        choices=["auto", "codex", "opencode"],
        help="Execution engine to use",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=Path("."),
        help="Repository root to execute against",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(".goal-runs/stage-result.json"),
        help="Path to write stage execution result JSON",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_CLI_TIMEOUT_SECONDS,
        help="Subprocess timeout in seconds",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Build prompt and command, but do not invoke engine",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    return run_stage(
        stage_manifest_path=args.stage_manifest,
        engine=args.engine,
        repo_root=args.repo_root,
        output=args.output,
        timeout_seconds=args.timeout_seconds,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    raise SystemExit(main())
