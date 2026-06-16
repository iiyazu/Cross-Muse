from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.execution.github_ops import (
    GitHubServerSideTruthEvidence,
    can_emit_pr_merged,
)


def build_github_server_truth_release_gate(
    github_truth: dict[str, Any],
    *,
    artifact_path: str | Path,
    base_branch: str = "main",
    expected_head_sha: str | None = None,
) -> dict[str, Any]:
    pull_request_number = github_truth.get("pull_request_number")
    actual_head_sha = _text(github_truth.get("head_sha"))
    expected_head_sha = expected_head_sha or _text(github_truth.get("expected_head_sha"))
    source_refs = _source_refs(
        pull_request_number,
        base_branch=base_branch,
        head_sha=actual_head_sha,
        expected_head_sha=expected_head_sha,
    )
    if expected_head_sha is not None and actual_head_sha != expected_head_sha:
        return _gate(
            status="manual_gap",
            proof_level="manual_gap",
            summary=(
                "GitHub server truth head "
                f"{actual_head_sha or '<missing>'} does not match expected current "
                f"head {expected_head_sha}."
            ),
            source_refs=source_refs,
            artifact_path=artifact_path,
            next_action=(
                "Re-capture GitHub server truth for the current PR head before "
                "using this artifact in release readiness."
            ),
        )
    if _has_server_enforcement_proof(github_truth):
        proof_level = (
            "server_side_merge_proof"
            if _can_emit_pr_merged(github_truth)
            else "server_side_enforcement_proof"
        )
        return _gate(
            status="ok",
            proof_level=proof_level,
            summary="GitHub branch protection/ruleset and required check truth were captured.",
            source_refs=source_refs,
            artifact_path=artifact_path,
            next_action=_next_action(github_truth),
        )
    return _gate(
        status="manual_gap",
        proof_level="manual_gap",
        summary=_gap_summary(github_truth),
        source_refs=source_refs,
        artifact_path=artifact_path,
        next_action="Capture GitHub branch protection/ruleset and required check truth.",
    )


def write_github_server_truth_release_gate(
    github_truth: dict[str, Any],
    *,
    artifact_path: str | Path,
    output_path: str | Path,
    base_branch: str = "main",
    expected_head_sha: str | None = None,
) -> dict[str, Any]:
    gate = build_github_server_truth_release_gate(
        github_truth,
        artifact_path=artifact_path,
        base_branch=base_branch,
        expected_head_sha=expected_head_sha,
    )
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(gate, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return gate


def _gate(
    *,
    status: str,
    proof_level: str,
    summary: str,
    source_refs: list[str],
    artifact_path: str | Path,
    next_action: str,
) -> dict[str, Any]:
    return {
        "schema_version": "xmuse.production_evidence.v1",
        "gate_id": "github-server-truth",
        "kind": "github_server_truth",
        "configured": True,
        "required": True,
        "status": status,
        "proof_level": proof_level,
        "owner": "github",
        "summary": summary,
        "attempted_command": "uv run python scripts/github_server_truth_capture.py",
        "next_action": next_action,
        "source_refs": source_refs,
        "artifacts": [str(artifact_path)],
        "generated_at": _utc_now(),
    }


def _has_server_enforcement_proof(github_truth: dict[str, Any]) -> bool:
    return (
        _has_status_check_truth(github_truth)
        and _has_server_enforcement_truth(github_truth)
    )


def _has_status_check_truth(github_truth: dict[str, Any]) -> bool:
    required_checks = _string_list(github_truth.get("required_checks"))
    check_run_ids = github_truth.get("check_run_ids")
    return (
        bool(required_checks)
        and isinstance(check_run_ids, list)
        and len(check_run_ids) >= len(required_checks)
        and _text(github_truth.get("expected_source_app")) is not None
    )


def _has_server_enforcement_truth(github_truth: dict[str, Any]) -> bool:
    return isinstance(github_truth.get("branch_protection_snapshot"), dict) or isinstance(
        github_truth.get("ruleset_snapshot"),
        dict,
    )


def _next_action(github_truth: dict[str, Any]) -> str:
    if _can_emit_pr_merged(github_truth):
        return "No GitHub server-truth action required."
    gap_reason = _text(github_truth.get("gap_reason"))
    if gap_reason is not None:
        return f"Resolve remaining GitHub truth gap before pr_merged: {gap_reason}."
    return "Keep GitHub server-truth artifact attached to release readiness evidence."


def _can_emit_pr_merged(github_truth: dict[str, Any]) -> bool:
    try:
        payload = {
            key: value
            for key in GitHubServerSideTruthEvidence.model_fields
            if (value := github_truth.get(key)) is not None
        }
        evidence = GitHubServerSideTruthEvidence.model_validate(payload)
    except ValueError:
        return False
    return can_emit_pr_merged(evidence)


def _gap_summary(github_truth: dict[str, Any]) -> str:
    gap_reason = _text(github_truth.get("gap_reason"))
    if gap_reason is not None:
        return f"GitHub server truth is incomplete: {gap_reason}."
    return "GitHub branch protection/ruleset or required check truth is unavailable."


def _source_refs(
    pull_request_number: Any,
    *,
    base_branch: str,
    head_sha: str | None,
    expected_head_sha: str | None,
) -> list[str]:
    refs: list[str] = []
    if isinstance(pull_request_number, int) and not isinstance(pull_request_number, bool):
        refs.append(f"github:pr:{pull_request_number}")
    refs.append(f"github:branch:{base_branch}")
    if head_sha is not None:
        refs.append(f"github:head:{head_sha}")
    if expected_head_sha is not None:
        refs.append(f"github:expected-head:{expected_head_sha}")
    return refs


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
