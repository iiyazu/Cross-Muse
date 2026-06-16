from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.execution.github_ops import (
    GitHubServerSideTruthEvidence,
    can_emit_pr_merged,
)

_PR_MERGED_FORBIDDEN_CLAIMS = ["pr_merged"]


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
    evidence = _github_truth_evidence(github_truth)
    can_emit_merged = evidence is not None and can_emit_pr_merged(evidence)
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
            forbidden_claims=_PR_MERGED_FORBIDDEN_CLAIMS,
            github_truth=_truth_detail(
                github_truth,
                actual_head_sha=actual_head_sha,
                expected_head_sha=expected_head_sha,
                can_emit_pr_merged=can_emit_merged,
            ),
        )
    if _has_server_enforcement_proof(evidence):
        proof_level = (
            "server_side_merge_proof"
            if can_emit_merged
            else "server_side_enforcement_proof"
        )
        return _gate(
            status="ok",
            proof_level=proof_level,
            summary="GitHub branch protection/ruleset and required check truth were captured.",
            source_refs=source_refs,
            artifact_path=artifact_path,
            next_action=_next_action(github_truth, can_emit_pr_merged=can_emit_merged),
            forbidden_claims=[] if can_emit_merged else _PR_MERGED_FORBIDDEN_CLAIMS,
            github_truth=_truth_detail(
                github_truth,
                actual_head_sha=actual_head_sha,
                expected_head_sha=expected_head_sha,
                can_emit_pr_merged=can_emit_merged,
            ),
        )
    return _gate(
        status="manual_gap",
        proof_level="manual_gap",
        summary=_gap_summary(github_truth, evidence=evidence),
        source_refs=source_refs,
        artifact_path=artifact_path,
        next_action="Capture GitHub branch protection/ruleset and required check truth.",
        forbidden_claims=_PR_MERGED_FORBIDDEN_CLAIMS,
        github_truth=_truth_detail(
            github_truth,
            actual_head_sha=actual_head_sha,
            expected_head_sha=expected_head_sha,
            can_emit_pr_merged=can_emit_merged,
        ),
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
    forbidden_claims: list[str],
    github_truth: dict[str, Any],
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
        "forbidden_claims": forbidden_claims,
        "artifacts": [str(artifact_path)],
        "github_truth": github_truth,
        "generated_at": _utc_now(),
    }


def _truth_detail(
    github_truth: dict[str, Any],
    *,
    actual_head_sha: str | None,
    expected_head_sha: str | None,
    can_emit_pr_merged: bool,
) -> dict[str, Any]:
    if expected_head_sha is None:
        freshness_status = "unchecked"
        matches_expected = None
    elif actual_head_sha == expected_head_sha:
        freshness_status = "matched"
        matches_expected = True
    else:
        freshness_status = "mismatch"
        matches_expected = False
    return {
        "authority": "github_truth_release_gate",
        "head_sha": actual_head_sha,
        "expected_head_sha": expected_head_sha,
        "head_sha_matches_expected": matches_expected,
        "head_freshness_status": freshness_status,
        "can_emit_pr_merged": can_emit_pr_merged,
    }


def _has_server_enforcement_proof(
    evidence: GitHubServerSideTruthEvidence | None,
) -> bool:
    return (
        evidence is not None
        and evidence.has_status_check_truth
        and evidence.has_server_enforcement_truth
    )


def _next_action(
    github_truth: dict[str, Any],
    *,
    can_emit_pr_merged: bool,
) -> str:
    if can_emit_pr_merged:
        return "No GitHub server-truth action required."
    gap_reason = _text(github_truth.get("gap_reason"))
    if gap_reason is not None:
        return f"Resolve remaining GitHub truth gap before pr_merged: {gap_reason}."
    return "Keep GitHub server-truth artifact attached to release readiness evidence."


def _gap_summary(
    github_truth: dict[str, Any],
    *,
    evidence: GitHubServerSideTruthEvidence | None,
) -> str:
    if evidence is not None:
        missing = []
        if not evidence.has_status_check_truth:
            missing.append("status_check_truth")
        if not evidence.has_server_enforcement_truth:
            missing.append("server_enforcement_truth")
        if missing:
            return (
                "GitHub server truth is incomplete: missing server-side truth: "
                + ", ".join(missing)
                + "."
            )
    gap_reason = _text(github_truth.get("gap_reason"))
    if gap_reason is not None:
        return f"GitHub server truth is incomplete: {gap_reason}."
    return "GitHub branch protection/ruleset or required check truth is unavailable."


def _github_truth_evidence(
    github_truth: dict[str, Any],
) -> GitHubServerSideTruthEvidence | None:
    try:
        payload = {
            key: value
            for key in GitHubServerSideTruthEvidence.model_fields
            if (value := github_truth.get(key)) is not None
        }
        return GitHubServerSideTruthEvidence.model_validate(payload)
    except ValueError:
        return None


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


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
