from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from xmuse_core.core.paths import controller_path
from xmuse_core.hermes.json_artifacts import canonical_json_digest, file_json_digest, read_json

PROMOTION_PASS_VERDICTS = {"pass", "passed", "usable", "usable_ack", "ack", "approved"}
PROVENANCE_METHODS = {
    "signed_approval",
    "git_signature",
    "github_review",
    "github_check",
    "ci_artifact",
}
CurrentTargetHead = Callable[[Path, str | None], str | None]


def _load_required_json(
    loop: Path,
    ref: str,
    errors: list[str],
    label: str,
) -> dict[str, Any] | None:
    path = controller_path(loop, ref)
    try:
        payload = read_json(path)
    except FileNotFoundError:
        errors.append(f"missing {label}: {ref}")
        return None
    except Exception as exc:
        errors.append(f"invalid {label} JSON: {ref}: {exc}")
        return None
    if not isinstance(payload, dict):
        errors.append(f"{label} JSON root must be an object: {ref}")
        return None
    return payload


def current_target_head_default(loop: Path, target_branch: str | None) -> str | None:
    if not target_branch:
        return None
    result = subprocess.run(
        ["git", "-C", str(loop.parent), "rev-parse", target_branch],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def allowed_target_branches(loop: Path) -> list[str] | None:
    config_path = loop / "master_config.json"
    if not config_path.exists():
        return None
    try:
        config = read_json(config_path)
    except Exception:
        return None
    allowed = config.get("allowed_target_branches") if isinstance(config, dict) else None
    if not isinstance(allowed, list):
        return None
    return [branch for branch in allowed if isinstance(branch, str) and branch]


def same_commit_ref(left: Any, right: Any) -> bool:
    left_s = str(left or "")
    right_s = str(right or "")
    return bool(left_s and right_s) and (
        left_s == right_s or left_s.startswith(right_s) or right_s.startswith(left_s)
    )


def validate_merge_queue_gate(
    loop_root: str | Path,
    feature: dict[str, Any],
    *,
    current_target_head: CurrentTargetHead | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    errors: list[str] = []
    feature_id = feature["id"]
    artifacts = feature["artifacts"]
    expected_master_prefix = f"xmuse/master/features/{feature_id}/"
    target_head = current_target_head or current_target_head_default

    if not artifacts["master_review"].startswith(expected_master_prefix):
        errors.append(f"master_review must live under {expected_master_prefix}")
    if not artifacts["integrated_tests"].startswith(expected_master_prefix):
        errors.append(f"integrated_tests must live under {expected_master_prefix}")

    for label in ("ack", "review_verdict", "result"):
        if not controller_path(loop, artifacts[label]).exists():
            errors.append(f"missing slave {label}: {artifacts[label]}")

    ack = _load_required_json(loop, artifacts["ack"], errors, "ack")
    if ack and str(ack.get("ack_level", "")).lower() not in PROMOTION_PASS_VERDICTS:
        errors.append("ack ack_level must be usable")
    review_verdict = _load_required_json(
        loop,
        artifacts["review_verdict"],
        errors,
        "review_verdict",
    )
    if (
        review_verdict
        and str(review_verdict.get("verdict", "")).lower() not in PROMOTION_PASS_VERDICTS
    ):
        errors.append("review_verdict verdict must be PASS")

    slave_state_ref = feature.get("slave_state_path")
    if isinstance(slave_state_ref, str) and not controller_path(loop, slave_state_ref).exists():
        errors.append(f"missing slave_state: {slave_state_ref}")

    master_review = _load_required_json(loop, artifacts["master_review"], errors, "master_review")
    integrated_tests = _load_required_json(
        loop,
        artifacts["integrated_tests"],
        errors,
        "integrated_tests",
    )

    if master_review:
        if master_review.get("recorded_by") != "master-god":
            errors.append("master_review must be recorded_by master-god")
        if master_review.get("status") != "accepted":
            errors.append("master_review status must be accepted")
        for key in (
            "feature_id",
            "branch",
            "base_commit",
            "head_commit",
            "target_branch",
            "artifact_digests",
        ):
            if key not in master_review:
                errors.append(f"master_review missing required key: {key}")

    if integrated_tests:
        if integrated_tests.get("recorded_by") != "master-god":
            errors.append("integrated_tests must be recorded_by master-god")
        if integrated_tests.get("status") != "passed":
            errors.append("integrated_tests status must be passed")
        if integrated_tests.get("worktree_clean") is not True:
            errors.append("integrated_tests worktree_clean must be true")
        for key in (
            "feature_id",
            "branch",
            "base_commit",
            "head_commit",
            "target_branch",
            "commands",
        ):
            if key not in integrated_tests:
                errors.append(f"integrated_tests missing required key: {key}")

    if master_review and integrated_tests:
        for key in ("feature_id", "branch", "base_commit", "head_commit", "target_branch"):
            if master_review.get(key) != integrated_tests.get(key):
                errors.append(f"master_review and integrated_tests mismatch on {key}")
        if master_review.get("branch") != feature.get("branch"):
            errors.append("gate evidence branch does not match feature branch")
        if master_review.get("target_branch") != feature.get("target_branch"):
            errors.append("gate evidence target_branch does not match feature target_branch")
        current_head = target_head(loop, feature.get("target_branch"))
        if current_head is None:
            errors.append("unable to resolve current target HEAD")
        elif not same_commit_ref(master_review.get("base_commit"), current_head):
            errors.append("gate evidence base_commit does not match current target HEAD")

    merge = feature.get("merge", {})
    target_branch = merge.get("target_branch") or feature.get("target_branch")
    allowed = allowed_target_branches(loop)
    if allowed is not None and target_branch not in allowed:
        errors.append(f"target_branch {target_branch} is not allowed by master_config")
    if merge.get("strategy") != "no_ff_merge_commit":
        errors.append("merge strategy must be no_ff_merge_commit")

    return {"valid": not errors, "errors": errors}


def validate_merge_approval(
    loop_root: str | Path,
    request_ref: str,
    approval_ref: str,
    *,
    policy_snapshot_digest: str,
) -> dict[str, Any]:
    loop = Path(loop_root)
    errors: list[str] = []

    if not request_ref.startswith("xmuse/approvals/"):
        errors.append("merge_approval_request must live under xmuse/approvals/")
    if not approval_ref.startswith("xmuse/approvals/"):
        errors.append("merge_approval must live under xmuse/approvals/")

    request = _load_required_json(loop, request_ref, errors, "merge_approval_request")
    approval = _load_required_json(loop, approval_ref, errors, "merge_approval")
    if not request or not approval:
        return {
            "schema_valid": False,
            "valid": False,
            "errors": errors,
            "provenance_scope": "schema_level_only",
            "provenance_verified": False,
        }

    expected_request_digest = canonical_json_digest(request, exclude_keys={"request_digest"})
    if request.get("request_digest") != expected_request_digest:
        errors.append("request_digest does not match canonical request JSON")

    for key in ("request_id", "request_digest"):
        if approval.get(key) != request.get(key):
            errors.append(f"approval {key} does not match request")

    for key in ("head_commit", "base_commit", "approved_range", "target_branch", "merge_strategy"):
        approval_key = "approved_commit" if key == "head_commit" else key
        if approval.get(approval_key) != request.get(key):
            errors.append(f"approval {approval_key} does not match request {key}")

    if approval.get("created_by") != "external_to_master_and_slave":
        errors.append("approval must be external_to_master_and_slave")
    if approval.get("decision") != "approved":
        errors.append("approval decision must be approved")

    verification = approval.get("verification", {})
    method = verification.get("method") if isinstance(verification, dict) else None
    if method == "maintainer_allowlist":
        errors.append("maintainer_allowlist cannot be sole provenance verification")
    elif method not in PROVENANCE_METHODS:
        errors.append(f"unsupported approval provenance method: {method}")
    if not isinstance(verification, dict) or verification.get("status") != "verified":
        errors.append("approval verification status must be verified")
    if not isinstance(verification, dict) or not verification.get("ref"):
        errors.append("approval verification ref is required")
    if not isinstance(verification, dict) or not verification.get("digest"):
        errors.append("approval verification digest is required")

    if request.get("policy_snapshot_digest") != policy_snapshot_digest:
        errors.append("policy snapshot digest does not match current policy")
    if approval.get("policy_snapshot_digest") != policy_snapshot_digest:
        errors.append("approval policy snapshot digest does not match current policy")

    try:
        review_digest = file_json_digest(controller_path(loop, request["master_review_ref"]))
    except Exception:
        review_digest = None
        errors.append("current master_review digest does not match approval request")
    try:
        tests_digest = file_json_digest(controller_path(loop, request["integrated_tests_ref"]))
    except Exception:
        tests_digest = None
        errors.append("current integrated_tests digest does not match approval request")
    if review_digest != request.get("master_review_digest"):
        errors.append("current master_review digest does not match approval request")
    if tests_digest != request.get("integrated_tests_digest"):
        errors.append("current integrated_tests digest does not match approval request")
    if approval.get("master_review_digest") != request.get("master_review_digest"):
        errors.append("approval master_review_digest does not match request")
    if approval.get("integrated_tests_digest") != request.get("integrated_tests_digest"):
        errors.append("approval integrated_tests_digest does not match request")

    schema_valid = not errors
    return {
        "schema_valid": schema_valid,
        "valid": False,
        "errors": errors,
        "provenance_scope": "schema_level_only",
        "provenance_verified": False,
    }


def validate_post_merge_verification(
    loop_root: str | Path,
    verification_ref: str,
    *,
    expected_digest: str,
    expected_status: str,
) -> dict[str, Any]:
    loop = Path(loop_root)
    errors: list[str] = []
    if not verification_ref.startswith("xmuse/approvals/"):
        errors.append("post_merge_verification must live under xmuse/approvals/")
    payload = _load_required_json(loop, verification_ref, errors, "post_merge_verification")
    if not payload:
        return {"valid": False, "errors": errors}

    actual_digest = canonical_json_digest(payload)
    if actual_digest != expected_digest:
        errors.append("post_merge_verification digest mismatch")
    for key in (
        "target_branch",
        "pre_merge_head",
        "approved_head",
        "post_merge_head",
        "merge_commit",
        "merge_strategy",
        "merge_execution_status",
        "approval_ref",
        "approval_digest",
        "approval_request_ref",
        "approval_request_digest",
        "ancestry_check",
        "verification_commands",
        "status",
    ):
        if not payload.get(key):
            errors.append(f"post_merge_verification missing required key: {key}")
    if payload.get("merge_strategy") != "no_ff_merge_commit":
        errors.append("post_merge_verification merge_strategy must be no_ff_merge_commit")
    if payload.get("merge_execution_status") != "passed":
        errors.append("post_merge_verification merge_execution_status must be passed")
    if payload.get("status") != expected_status:
        errors.append(f"post_merge_verification status must be {expected_status}")
    if payload.get("ancestry_check", {}).get("status") != "passed":
        errors.append("post_merge_verification ancestry_check status must be passed")
    commands = payload.get("verification_commands", [])
    if expected_status == "passed":
        for command in commands:
            if command.get("status") != "passed":
                errors.append("passed post_merge_verification requires every command to pass")
            if not command.get("artifact_digest"):
                errors.append("post_merge_verification command artifact_digest is required")
    elif expected_status == "failed":
        if not any(command.get("status") == "failed" for command in commands):
            errors.append("failed post_merge_verification requires at least one failed command")
    else:
        errors.append(f"unsupported post_merge_verification expected_status: {expected_status}")
    return {"valid": not errors, "errors": errors, "payload": payload}


def validate_merge_decision(loop_root: str | Path, decision: dict[str, Any]) -> dict[str, Any]:
    errors: list[str] = []
    selected = decision.get("decision")

    if decision.get("recorded_by") != "master-god":
        errors.append("merge_decision must be recorded_by master-god")

    if selected == "merged":
        for key in (
            "merge_commit",
            "approval_ref",
            "approval_digest",
            "approval_request_ref",
            "approval_request_digest",
            "post_merge_verification_refs",
            "post_merge_verification_digests",
        ):
            if not decision.get(key):
                errors.append(f"merged decision requires {key}")
        if len(decision.get("post_merge_verification_refs", [])) != len(
            decision.get("post_merge_verification_digests", [])
        ):
            errors.append("post_merge_verification refs and digests length mismatch")
        for ref, digest in zip(
            decision.get("post_merge_verification_refs", []),
            decision.get("post_merge_verification_digests", []),
            strict=False,
        ):
            verification = validate_post_merge_verification(
                loop_root,
                ref,
                expected_digest=digest,
                expected_status="passed",
            )
            if not verification["valid"]:
                errors.extend(verification["errors"])
    elif selected in {"held", "rejected"}:
        if not decision.get("blocked_gate"):
            errors.append(f"{selected} decision requires blocked_gate")
        if not decision.get("reasons"):
            errors.append(f"{selected} decision requires reasons")
        for forbidden in (
            "merge_commit",
            "post_merge_verification_refs",
            "post_merge_verification_digests",
        ):
            if decision.get(forbidden):
                errors.append(f"{selected} decision forbids {forbidden}")
    elif selected == "held_after_merge":
        for key in (
            "merge_commit",
            "approval_ref",
            "approval_digest",
            "approval_request_ref",
            "approval_request_digest",
            "failed_post_merge_verification_ref",
            "failed_post_merge_verification_digest",
            "next_action",
            "next_action_ref",
        ):
            if not decision.get(key):
                errors.append(f"held_after_merge requires {key}")
        if decision.get("blocked_gate") != "post_merge_verification":
            errors.append("held_after_merge blocked_gate must be post_merge_verification")
        if decision.get("failed_post_merge_verification_ref") and decision.get(
            "failed_post_merge_verification_digest"
        ):
            verification = validate_post_merge_verification(
                loop_root,
                decision["failed_post_merge_verification_ref"],
                expected_digest=decision["failed_post_merge_verification_digest"],
                expected_status="failed",
            )
            if not verification["valid"]:
                errors.extend(verification["errors"])
    else:
        errors.append(f"unsupported merge decision: {selected}")

    return {"valid": not errors, "errors": errors}


__all__ = [
    "allowed_target_branches",
    "current_target_head_default",
    "same_commit_ref",
    "validate_merge_approval",
    "validate_merge_decision",
    "validate_merge_queue_gate",
    "validate_post_merge_verification",
]
