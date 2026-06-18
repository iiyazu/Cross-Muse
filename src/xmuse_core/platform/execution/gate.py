from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path
from typing import Any

from xmuse_core.observability import log_event

logger = logging.getLogger(__name__)


def get_changed_paths(worktree: Path) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            cwd=worktree, capture_output=True, text=True, timeout=10,
        )
        return [p for p in result.stdout.strip().splitlines() if p]
    except Exception:
        return []


async def run_gate(*, lane_id: str, lane: dict[str, Any], root: Path) -> bool:
    worktree = Path(lane.get("worktree", "."))
    gate_profile = lane.get("gate_profile")
    gate_profiles = lane.get("gate_profiles")

    try:
        from xmuse_core.gates.loader import load_gate_config
        from xmuse_core.gates.resolver import GateProfileResolver
        from xmuse_core.gates.runner import GateRunner

        config_path = root / "gate_profiles.json"
        if not config_path.exists():
            log_event(logger, logging.WARNING, "gate_profiles_missing", lane_id=lane_id)
            _write_gate_profiles_missing_report(lane_id=lane_id, root=root, worktree=worktree)
            return True

        config = load_gate_config(config_path, repo_root=root.parent)
        resolver = GateProfileResolver(config)

        explicit_profiles: list[str] = []
        if isinstance(gate_profiles, list):
            explicit_profiles.extend(str(profile) for profile in gate_profiles)
        if gate_profile:
            explicit_profiles.append(str(gate_profile))
        changed = get_changed_paths(worktree)
        warnings: list[str] = []
        resolver_changed_paths = changed
        if explicit_profiles:
            resolver_changed_paths = []
            if changed:
                warnings.append(
                    "explicit gate_profiles selected; full dirty-worktree "
                    "coverage is recorded but not used to reject this lane"
                )

        plan = resolver.resolve(
            feature_id=lane_id,
            worktree=worktree,
            explicit_profiles=explicit_profiles,
            changed_paths=resolver_changed_paths,
            warnings=warnings,
        )

        runner = GateRunner(
            repo_root=root.parent,
            logs_root=root / "logs" / "gates",
        )
        report = await runner.run(plan)
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
        "passed": True,
        "blocking_passed": True,
        "profile_ids": [],
        "resolution_reasons": {
            "gate_profiles": ["gate_profiles_missing"],
        },
        "command_results": [],
        "artifact_dir": str(report_dir),
        "worktree": str(worktree),
        "warnings": [
            "gate_profiles.json missing; gate failed open and wrote this report for review evidence"
        ],
    }
    (report_dir / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
