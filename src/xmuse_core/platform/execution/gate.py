from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from xmuse_core.observability import log_event

logger = logging.getLogger(__name__)

_WORKTREE_GATE_PROFILE_WARNING = (
    "gate_profiles.json missing in XMUSE_ROOT; "
    "using lane worktree xmuse/gate_profiles.json"
)


def get_changed_paths(worktree: Path) -> list[str]:
    paths: list[str] = []
    for command in (
        ["git", "diff", "--name-only", "HEAD"],
        ["git", "ls-files", "--others", "--exclude-standard"],
    ):
        try:
            result = subprocess.run(
                command,
                cwd=worktree, capture_output=True, text=True, timeout=10,
            )
        except Exception:
            continue
        if result.returncode != 0:
            continue
        paths.extend(p for p in result.stdout.strip().splitlines() if p)
    return list(dict.fromkeys(paths))


async def run_gate(*, lane_id: str, lane: dict[str, Any], root: Path) -> bool:
    worktree = Path(lane.get("worktree", "."))
    gate_profile = lane.get("gate_profile")
    gate_profiles = lane.get("gate_profiles")

    try:
        from xmuse_core.gates.loader import load_gate_config
        from xmuse_core.gates.resolver import GateProfileResolver, ProfileMismatchError
        from xmuse_core.gates.runner import GateRunner

        config_path, config_repo_root, source_warning = _resolve_gate_config(
            root=root,
            worktree=worktree,
        )
        if config_path is None:
            log_event(logger, logging.WARNING, "gate_profiles_missing", lane_id=lane_id)
            _write_gate_profiles_missing_report(lane_id=lane_id, root=root, worktree=worktree)
            return False

        config = load_gate_config(config_path, repo_root=config_repo_root)
        resolver = GateProfileResolver(config)

        explicit_profiles: list[str] = []
        if isinstance(gate_profiles, list):
            explicit_profiles.extend(str(profile) for profile in gate_profiles)
        if gate_profile:
            explicit_profiles.append(str(gate_profile))
        changed = get_changed_paths(worktree)
        warnings: list[str] = []
        if source_warning:
            warnings.append(source_warning)

        try:
            plan = resolver.resolve(
                feature_id=lane_id,
                worktree=worktree,
                explicit_profiles=explicit_profiles,
                changed_paths=changed,
                warnings=warnings,
            )
        except ProfileMismatchError as exc:
            log_event(
                logger,
                logging.WARNING,
                "gate_profile_resolution_failed",
                lane_id=lane_id,
                error=str(exc),
                explicit_profiles=explicit_profiles,
                changed_paths=changed,
            )
            _write_gate_profile_resolution_failure_report(
                lane_id=lane_id,
                root=root,
                worktree=worktree,
                selected_path=config_path,
                explicit_profiles=explicit_profiles,
                changed_paths=changed,
                error=str(exc),
                warnings=warnings,
            )
            return False

        runner = GateRunner(
            repo_root=config_repo_root,
            logs_root=root / "logs" / "gates",
        )
        report = await runner.run(plan)
        _write_gate_profiles_source_report(
            lane_id=lane_id,
            root=root,
            worktree=worktree,
            selected_path=config_path,
        )
        log_event(
            logger,
            logging.INFO,
            "gate_completed",
            lane_id=lane_id,
            passed=report.passed,
        )
        return report.passed

    except Exception as exc:
        log_event(
            logger,
            logging.ERROR,
            "gate_failed",
            lane_id=lane_id,
            error=str(exc),
            exc_info=True,
        )
        return False


def _resolve_gate_config(
    *,
    root: Path,
    worktree: Path,
) -> tuple[Path | None, Path, str | None]:
    runtime_config = root / "gate_profiles.json"
    if runtime_config.exists():
        return runtime_config, root.parent, None

    worktree_config = worktree / "xmuse" / "gate_profiles.json"
    if worktree_config.exists():
        return (
            worktree_config,
            worktree,
            _WORKTREE_GATE_PROFILE_WARNING,
        )

    return None, worktree, None


def _write_gate_profiles_missing_report(
    *,
    lane_id: str,
    root: Path,
    worktree: Path,
) -> None:
    report_dir = root / "logs" / "gates" / lane_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "feature_id": lane_id,
        "passed": False,
        "blocking_passed": False,
        "profile_ids": [],
        "resolution_reasons": {
            "gate_profiles": ["gate_profiles_missing"],
        },
        "command_results": [],
        "artifact_dir": str(report_dir),
        "worktree": str(worktree),
        "gate_profiles_source": _gate_profiles_source_payload(
            root=root,
            worktree=worktree,
            selected_path=None,
        ),
        "warnings": [
            "gate_profiles.json missing in XMUSE_ROOT and lane worktree; gate failed closed"
        ],
    }
    (report_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


def _write_gate_profile_resolution_failure_report(
    *,
    lane_id: str,
    root: Path,
    worktree: Path,
    selected_path: Path,
    explicit_profiles: list[str],
    changed_paths: list[str],
    error: str,
    warnings: list[str],
) -> None:
    report_dir = root / "logs" / "gates" / lane_id
    report_dir.mkdir(parents=True, exist_ok=True)
    report = {
        "feature_id": lane_id,
        "passed": False,
        "blocking_passed": False,
        "profile_ids": list(explicit_profiles),
        "resolution_reasons": {
            profile_id: ["explicit_lane_profile"]
            for profile_id in explicit_profiles
        },
        "command_results": [],
        "artifact_dir": str(report_dir),
        "worktree": str(worktree),
        "changed_paths": list(changed_paths),
        "gate_profiles_source": _gate_profiles_source_payload(
            root=root,
            worktree=worktree,
            selected_path=selected_path,
        ),
        "warnings": [
            *warnings,
            f"gate profile resolution failed closed: {error}",
        ],
        "error": {
            "type": "ProfileMismatchError",
            "message": error,
        },
    }
    (report_dir / "report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _write_gate_profiles_source_report(
    *,
    lane_id: str,
    root: Path,
    worktree: Path,
    selected_path: Path,
) -> None:
    report_path = root / "logs" / "gates" / lane_id / "report.json"
    try:
        payload = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return
    if not isinstance(payload, dict):
        return
    payload["gate_profiles_source"] = _gate_profiles_source_payload(
        root=root,
        worktree=worktree,
        selected_path=selected_path,
    )
    report_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _gate_profiles_source_payload(
    *,
    root: Path,
    worktree: Path,
    selected_path: Path | None,
) -> dict[str, str | None]:
    runtime_config = root / "gate_profiles.json"
    worktree_config = worktree / "xmuse" / "gate_profiles.json"
    if selected_path == runtime_config:
        source = "xmuse_root"
    elif selected_path == worktree_config:
        source = "lane_worktree_fallback"
    else:
        source = "missing"
    return {
        "source": source,
        "selected_path": str(selected_path) if selected_path is not None else None,
        "xmuse_root_path": str(runtime_config),
        "lane_worktree_path": str(worktree_config),
    }
