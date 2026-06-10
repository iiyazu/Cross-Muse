#!/usr/bin/env python3
# ruff: noqa: E402,I001
"""Hermes hardening helpers for launcher state, active jobs, and promotion gates.

Writes are limited to explicit controller artifacts such as state, active job,
heartbeat, status, and stale-index files. It does not mutate source code or
benchmark reports.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

_SRC_ROOT = Path(__file__).resolve().parents[1] / "src"
if _SRC_ROOT.exists() and str(_SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(_SRC_ROOT))

from xmuse_core.core.paths import (
    controller_path as _core_controller_path,
)
from xmuse_core.core.schema import (
    FEATURE_AMENDMENT_ACTIONS as _CORE_FEATURE_AMENDMENT_ACTIONS,
    FEATURE_LOCAL_ACTIVE_STATES as _CORE_FEATURE_LOCAL_ACTIVE_STATES,
    MASTER_ACTIVATION_STATES as _CORE_MASTER_ACTIVATION_STATES,
    MASTER_BLOCKED_STATES as _CORE_MASTER_BLOCKED_STATES,
    MASTER_HELD_STATES as _CORE_MASTER_HELD_STATES,
    MASTER_QUEUE_NAMES as _CORE_MASTER_QUEUE_NAMES,
    MASTER_REVIEW_STATES as _CORE_MASTER_REVIEW_STATES,
    MERGE_REQUEST_STATES as _CORE_MERGE_REQUEST_STATES,
    REQUIRED_FEATURE_AMENDMENT_KEYS as _CORE_REQUIRED_FEATURE_AMENDMENT_KEYS,
    REQUIRED_FEATURE_ARTIFACT_KEYS as _CORE_REQUIRED_FEATURE_ARTIFACT_KEYS,
    REQUIRED_FEATURE_KEYS as _CORE_REQUIRED_FEATURE_KEYS,
    REQUIRED_MASTER_STATE_KEYS as _CORE_REQUIRED_MASTER_STATE_KEYS,
    STATE_RANK as _CORE_STATE_RANK,
    TARGET_BRANCH_STATES as _CORE_TARGET_BRANCH_STATES,
    validate_master_state as _core_validate_master_state,
)
from xmuse_core.core.state import (
    resolve_active_controller as _core_resolve_active_controller,
)
from xmuse_core.core.status import (
    build_master_status as _core_build_master_status,
    derive_master_queues as _core_derive_master_queues,
    master_status_markdown as _core_master_status_markdown,
)
from xmuse_core.hermes.active_jobs import (
    classify_active_job,
    complete_active_job,
    git_status_short as _git_status_short,
    pid_alive_default as _pid_alive_default,
    write_active_job,
)
from xmuse_core.hermes.eval_runs import (
    classify_eval_run,
    counter_dict as _counter_dict,
    llm_promotion_problem as _llm_promotion_problem,
    summarize_eval_report,
)
from xmuse_core.hermes.feature_lanes import (
    classify_feature_lane,
    load_feature_lanes,
    summarize_master_slave_control as _summarize_master_slave_control_core,
    write_master_slave_status as _write_master_slave_status_core,
)
from xmuse_core.hermes.json_artifacts import (
    atomic_write_json as _atomic_write_json,
    atomic_write_text as _atomic_write_text,
    canonical_json_bytes,
    canonical_json_digest,
    file_json_digest,
    read_json as _read_json,
)
from xmuse_core.hermes.merge_gates import (
    current_target_head_default as _current_target_head,
    validate_merge_approval,
    validate_merge_decision,
    validate_merge_queue_gate as _validate_merge_queue_gate_core,
    validate_post_merge_verification,
)
from xmuse_core.hermes.phase_gates import (
    STALE_CANDIDATE_FILES,
    check_config_blueprint_consistency,
    check_execute_bootstrap_gate,
    check_execute_completion_gate,
    check_execute_goal_contract,
    check_review_eval_decision,
    check_state_ack_consistency,
    check_state_phase_order,
    generate_shard_resume_plan,
    promote_dispatch_to_execute,
    promote_execute_to_self_review,
    run_phase_hardening as _run_phase_hardening_core,
    scan_stale_artifacts,
    write_phase_status,
    _context_bundle_path,
)

__all__ = [
    "STALE_CANDIDATE_FILES",
    "_atomic_write_json",
    "_atomic_write_text",
    "_context_bundle_path",
    "_counter_dict",
    "_git_status_short",
    "_llm_promotion_problem",
    "_pid_alive_default",
    "_read_json",
    "canonical_json_bytes",
    "canonical_json_digest",
    "check_config_blueprint_consistency",
    "check_execute_bootstrap_gate",
    "check_execute_completion_gate",
    "check_execute_goal_contract",
    "check_review_eval_decision",
    "check_state_ack_consistency",
    "check_state_phase_order",
    "classify_active_job",
    "classify_eval_run",
    "classify_feature_lane",
    "complete_active_job",
    "file_json_digest",
    "generate_shard_resume_plan",
    "load_feature_lanes",
    "promote_dispatch_to_execute",
    "promote_execute_to_self_review",
    "run_phase_hardening",
    "scan_stale_artifacts",
    "summarize_eval_report",
    "summarize_master_slave_control",
    "validate_merge_approval",
    "validate_merge_decision",
    "validate_merge_queue_gate",
    "validate_post_merge_verification",
    "write_active_job",
    "write_master_slave_status",
    "write_phase_status",
]

PROMOTION_PASS_VERDICTS = {"pass", "passed", "usable", "usable_ack", "ack", "approved"}
FEATURE_LANES_FILE = "feature_lanes.json"
MASTER_STATE_FILE = "master_state.json"
MASTER_STATUS_JSON = "master_status.json"
MASTER_STATUS_MD = "master_status.md"
LEGACY_ROOT_LOOP_DIR = "legacy/root-loop"
LEGACY_ROOT_FILES = [
    "state.json",
    "feature_lanes.json",
    "master_slave_status.json",
    "master_slave_status.md",
    "config.json",
    "blueprint.md",
    "blueprint.zh.md",
    "god_loop_prompt.md",
]
MASTER_ACTIVATION_STATES = _CORE_MASTER_ACTIVATION_STATES
MASTER_QUEUE_NAMES = _CORE_MASTER_QUEUE_NAMES
FEATURE_AMENDMENT_ACTIONS = _CORE_FEATURE_AMENDMENT_ACTIONS
REQUIRED_FEATURE_AMENDMENT_KEYS = _CORE_REQUIRED_FEATURE_AMENDMENT_KEYS
REQUIRED_MASTER_STATE_KEYS = _CORE_REQUIRED_MASTER_STATE_KEYS
REQUIRED_FEATURE_KEYS = _CORE_REQUIRED_FEATURE_KEYS
REQUIRED_FEATURE_ARTIFACT_KEYS = _CORE_REQUIRED_FEATURE_ARTIFACT_KEYS
STATE_RANK = _CORE_STATE_RANK
FEATURE_LOCAL_ACTIVE_STATES = _CORE_FEATURE_LOCAL_ACTIVE_STATES
MASTER_HELD_STATES = _CORE_MASTER_HELD_STATES
MASTER_BLOCKED_STATES = _CORE_MASTER_BLOCKED_STATES
MASTER_REVIEW_STATES = _CORE_MASTER_REVIEW_STATES
MERGE_REQUEST_STATES = _CORE_MERGE_REQUEST_STATES
TARGET_BRANCH_STATES = _CORE_TARGET_BRANCH_STATES


def _append_missing(
    errors: list[str], payload: dict[str, Any], required: set[str], prefix: str
) -> None:
    for key in sorted(required - set(payload)):
        errors.append(f"{prefix} missing required key: {key}")


def _validate_feature_amendment(
    amendment: dict[str, Any], errors: list[str], index: int
) -> None:
    prefix = f"feature_amendments[{index}]"
    _append_missing(errors, amendment, REQUIRED_FEATURE_AMENDMENT_KEYS, prefix)

    if amendment.get("action") not in FEATURE_AMENDMENT_ACTIONS:
        errors.append(f"{prefix} unsupported action: {amendment.get('action')}")
    if amendment.get("status") not in {"proposed", "accepted", "applied", "rejected"}:
        errors.append(f"{prefix} unsupported status: {amendment.get('status')}")
    if amendment.get("recorded_by") != "master-god":
        errors.append(f"{prefix} recorded_by must be master-god")

    feature_ids = amendment.get("feature_ids")
    if not isinstance(feature_ids, list) or not feature_ids or not all(
        isinstance(feature_id, str) and feature_id for feature_id in feature_ids
    ):
        errors.append(f"{prefix} feature_ids must be a non-empty string list")
    if not isinstance(amendment.get("target_feature_id"), str) or not amendment.get(
        "target_feature_id"
    ):
        errors.append(f"{prefix} target_feature_id is required")

    policy = amendment.get("policy_preserved", {})
    if not isinstance(policy, dict):
        errors.append(f"{prefix} policy_preserved must be an object")
    else:
        for key in (
            "v1_fallback_preserved",
            "kernel_opt_in_preserved",
            "no_benchmark_score_targets",
            "no_gate_lowering",
        ):
            if policy.get(key) is not True:
                errors.append(f"{prefix} policy_preserved.{key} must be true")

    if amendment.get("gate_effect") != "no_gate_lowering":
        errors.append(f"{prefix} gate_effect must be no_gate_lowering")

    artifacts = amendment.get("artifacts", {})
    if not isinstance(artifacts, dict):
        errors.append(f"{prefix} artifacts must be an object")
        return
    artifact_ref = artifacts.get("amendment")
    if not isinstance(artifact_ref, str) or not artifact_ref.startswith(
        "xmuse/master/amendments/"
    ):
        errors.append(
            f"{prefix} amendment artifact must live under xmuse/master/amendments/"
        )


def validate_master_state(state: dict[str, Any]) -> dict[str, Any]:
    return _core_validate_master_state(state)


def _load_json_path(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"missing file: {path}"]
    except json.JSONDecodeError as exc:
        return None, [f"invalid JSON in {path}: {exc}"]
    if not isinstance(payload, dict):
        return None, [f"JSON root must be an object: {path}"]
    return payload, []


def resolve_active_controller(loop_root: str | Path, *, audit: bool = False) -> dict[str, Any]:
    return _core_resolve_active_controller(loop_root, audit=audit)


def _project_relative(path: Path) -> str:
    return str(path).replace("\\", "/")


def _master_feature_from_legacy(feature: dict[str, Any]) -> dict[str, Any]:
    feature_id = feature["id"]
    artifacts = feature.get("artifacts", {})
    merge = feature.get("merge", {})
    target_branch = feature.get("target_branch", merge.get("target_branch", "main"))
    return {
        "id": feature_id,
        "name": feature.get("name", feature_id),
        "state": feature.get("state", "planned"),
        "branch": feature.get("branch", f"feature/{feature_id}"),
        "target_branch": target_branch,
        "worktree": feature.get("worktree", f"../xmuse-{feature_id}"),
        "slave_state_path": f"xmuse/work/features/{feature_id}/slave_state.json",
        "slave_god": {
            "owner": f"slave-god-{feature_id}",
            "mode": "feature_local_single_god",
            "last_reported_at": "",
        },
        "blueprint_path": f"xmuse/work/features/{feature_id}/blueprint.md",
        "artifacts": {
            "result": artifacts.get("result", f"xmuse/work/features/{feature_id}/result.md"),
            "ack": artifacts.get("ack", f"xmuse/work/features/{feature_id}/ack.json"),
            "review_verdict": artifacts.get(
                "review_verdict",
                f"xmuse/work/features/{feature_id}/review_verdict.json",
            ),
            "integrated_tests": f"xmuse/master/features/{feature_id}/integrated_tests.json",
            "master_review": f"xmuse/master/features/{feature_id}/master_review.json",
            "merge_approval_request": (
                f"xmuse/approvals/{feature_id}/merge_approval_request.json"
            ),
            "merge_approval": f"xmuse/approvals/{feature_id}/merge_approval.json",
            "post_merge_verification": (
                f"xmuse/approvals/{feature_id}/post_merge_verification.json"
            ),
            "merge_decision": f"xmuse/approvals/{feature_id}/merge_decision.json",
            "next_action": f"xmuse/approvals/{feature_id}/next_action.json",
        },
        "merge": {
            "status": merge.get("status", feature.get("state", "planned")),
            "target_branch": target_branch,
            "strategy": "no_ff_merge_commit",
            "github_pr": merge.get("github_pr"),
        },
        "policy_flags": {
            "requires_integrated_tests": True,
            "requires_explicit_merge_approval": True,
            "allows_github_evidence": True,
        },
        "risk": feature.get("risk", {"level": "medium", "notes": []}),
    }


def _empty_master_queues() -> dict[str, list[str]]:
    return {name: [] for name in sorted(MASTER_QUEUE_NAMES)}


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _active_template_text(relative_path: str, fallback: str) -> str:
    template_path = Path(__file__).resolve().parent / relative_path
    if template_path.exists():
        return template_path.read_text(encoding="utf-8")
    return fallback


def _active_template_json(relative_path: str, fallback: dict[str, Any]) -> dict[str, Any]:
    template_path = Path(__file__).resolve().parent / relative_path
    if template_path.exists():
        payload = json.loads(template_path.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            return payload
    return fallback


def derive_master_queues(
    master_state: dict[str, Any], *, loop_root: str | Path | None = None
) -> dict[str, Any]:
    merge_gate_validator = None
    if loop_root is not None:
        loop = Path(loop_root)

        def merge_gate_validator(feature: dict[str, Any]) -> dict[str, Any]:
            return validate_merge_queue_gate(loop, feature)

    return _core_derive_master_queues(
        master_state,
        merge_gate_validator=merge_gate_validator,
        missing_validator_reason="loop_root is required",
    )


def _optional_artifact_json(loop: Path, ref: str | None) -> dict[str, Any] | None:
    if not ref:
        return None
    path = _controller_path(loop, ref)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def classify_feature_reconcile_state(
    loop_root: str | Path, feature: dict[str, Any]
) -> dict[str, Any]:
    """Classify stale feature state from feature-local and Master-owned evidence."""
    loop = Path(loop_root)
    artifacts = feature.get("artifacts", {})
    ack = _optional_artifact_json(loop, artifacts.get("ack"))
    review = _optional_artifact_json(loop, artifacts.get("review_verdict"))
    master_review = _optional_artifact_json(loop, artifacts.get("master_review"))
    integrated_tests = _optional_artifact_json(loop, artifacts.get("integrated_tests"))

    head_commit = None
    for payload in (integrated_tests, master_review, review, ack):
        if payload and payload.get("head_commit"):
            head_commit = payload["head_commit"]
            break

    ack_level = str((ack or {}).get("ack_level", "")).lower()
    verdict = str((review or {}).get("verdict", "")).lower()
    if (ack and ack_level not in PROMOTION_PASS_VERDICTS) or (
        review and verdict not in PROMOTION_PASS_VERDICTS
    ):
        return {
            "state": "repairing",
            "dispatch_status": "rework_required",
            "head_commit": head_commit,
            "reason": "feature-local ACK or review requires autonomous Slave repair",
        }

    if (
        ack_level in PROMOTION_PASS_VERDICTS
        and verdict in PROMOTION_PASS_VERDICTS
        and master_review
        and master_review.get("status") == "accepted"
        and integrated_tests
        and integrated_tests.get("status") != "passed"
    ):
        return {
            "state": "repairing",
            "dispatch_status": "rework_required",
            "head_commit": head_commit,
            "reason": "integrated test gate requires Slave repair or refreshed evidence",
        }

    if (
        ack_level in PROMOTION_PASS_VERDICTS
        and verdict in PROMOTION_PASS_VERDICTS
        and master_review
        and master_review.get("status") == "accepted"
        and integrated_tests
        and integrated_tests.get("status") == "passed"
    ):
        approval_ref = artifacts.get("merge_approval")
        approval_present = bool(approval_ref and _controller_path(loop, approval_ref).exists())
        if not approval_present:
            return {
                "state": "approval_blocked",
                "dispatch_status": "approval_required",
                "head_commit": head_commit,
                "reason": "feature passed Slave/Master evidence but awaits external approval",
            }
        gate = validate_merge_queue_gate(loop, feature)
        if not gate["valid"] and any(
            "approval" in error or "allowed_target_branches" in error
            for error in gate["errors"]
        ):
            return {
                "state": "approval_blocked",
                "dispatch_status": "approval_required",
                "head_commit": head_commit,
                "reason": (
                    "feature passed Slave/Master evidence but awaits approval or branch policy"
                ),
            }

    return {
        "state": feature.get("state", "active"),
        "dispatch_status": feature.get("slave_god", {}).get("dispatch_status"),
        "head_commit": head_commit or feature.get("slave_god", {}).get("head_commit"),
        "reason": "no reconcile change",
    }


def build_master_status(loop_root: str | Path, master_state: dict[str, Any]) -> dict[str, Any]:
    loop = Path(loop_root)

    def merge_gate_validator(feature: dict[str, Any]) -> dict[str, Any]:
        return validate_merge_queue_gate(loop, feature)

    return _core_build_master_status(
        master_state,
        merge_gate_validator=merge_gate_validator,
        missing_validator_reason="loop_root is required",
    )


def _write_master_status_files(status: dict[str, Any], json_path: Path, md_path: Path) -> None:
    _write_json(json_path, status)
    md_path.write_text(_core_master_status_markdown(status), encoding="utf-8")


def write_master_status(loop_root: str | Path, master_state: dict[str, Any]) -> dict[str, Any]:
    loop = Path(loop_root)
    status = build_master_status(loop, master_state)
    _write_master_status_files(status, loop / MASTER_STATUS_JSON, loop / MASTER_STATUS_MD)
    return status


def prepare_master_migration(loop_root: str | Path) -> dict[str, Any]:
    loop = Path(loop_root)
    legacy_state = json.loads((loop / "state.json").read_text(encoding="utf-8"))
    legacy_lanes_path = loop / "feature_lanes.json"
    legacy_lanes = (
        json.loads(legacy_lanes_path.read_text(encoding="utf-8"))
        if legacy_lanes_path.exists()
        else {"features": []}
    )
    features = [
        _master_feature_from_legacy(feature) for feature in legacy_lanes.get("features", [])
    ]

    master_state = {
        "version": "1.0",
        "mode": "master_control",
        "activation_state": "master_pending",
        "active": False,
        "history_baseline": "xmuse/history/main_loop_phase0_18.json",
        "legacy_root_loop": "xmuse/legacy/root-loop/",
        "master_blueprint": "xmuse/master_blueprint.md",
        "master_config": "xmuse/master_config.json",
        "prompts": {
            "master": "xmuse/prompts/master_god_prompt.md",
            "slave": "xmuse/prompts/slave_god_prompt.md",
        },
        "dispatch_contracts": {
            "master": "xmuse/contracts/master_dispatch_template.json",
            "slave": "xmuse/contracts/slave_dispatch_template.json",
        },
        "master_policy": {
            "v1_fallback_preserved": True,
            "kernel_opt_in_preserved": True,
            "no_benchmark_score_targets": True,
            "same_slice_repair_smoke_not_promotion": True,
        },
        "features": features,
        "queues": derive_master_queues({"features": features})["queues"],
        "decisions": [],
        "integration": {"legacy_state": legacy_state},
        "github": {"enabled": False},
        "last_updated": "2026-05-24T00:00:00Z",
    }

    _write_json(loop / "master_state.json", master_state)
    (loop / "master_blueprint.md").write_text(
        "# Hermes Master Blueprint\n\n"
        "Master is the only active controller after activation. "
        "Legacy root-loop files are audit history.\n\n"
        "## Dynamic Feature Control\n\n"
        "Master owns feature-lane lifecycle decisions. It may create, split, combine, "
        "rename, re-scope, reorder, hold, resume, archive, or request bounded repair "
        "for feature lanes when the decision is recorded as Master-owned evidence.\n\n"
        "Dynamic changes must be append-only and auditable under "
        "`xmuse/master/amendments/`. Every amendment must preserve v3 default, "
        "v1 fallback, kernel opt-in, diagnostic-only benchmark semantics, and "
        "`no_gate_lowering`.\n\n"
        "Slave Gods may refine a feature-local blueprint or propose a feature "
        "amendment, but only Master may apply registry-level changes in "
        "`master_state.json`.\n",
        encoding="utf-8",
    )
    _write_json(
        loop / "master_config.json",
        {
            "version": "1.0",
            "allowed_target_branches": ["main"],
            "merge_strategy": "no_ff_merge_commit",
        },
    )
    (loop / "prompts" / "master_god_prompt.md").parent.mkdir(parents=True, exist_ok=True)
    (loop / "prompts" / "master_god_prompt.md").write_text(
        _active_template_text(
            "prompts/master_god_prompt.md",
            "Read master_state.json, master_config.json, master_blueprint.md, "
            "and master dispatch contract before acting.\n",
        ),
        encoding="utf-8",
    )
    (loop / "prompts" / "slave_god_prompt.md").write_text(
        _active_template_text(
            "prompts/slave_god_prompt.md",
            "Read assigned feature registry entry, slave prompt, slave dispatch contract, "
            "slave_state.json, and feature blueprint.\n",
        ),
        encoding="utf-8",
    )
    node_launcher = loop / "codex_node_launcher.sh"
    node_launcher.write_text(
        _active_template_text(
            "codex_node_launcher.sh",
            "#!/bin/bash\n"
            "set -euo pipefail\n"
            "NODE_TYPE=\"${1:?node type}\"\n"
            "PROMPT_FILE=\"${2:?prompt file}\"\n"
            "case \"$NODE_TYPE\" in master|slave|plan|execute|review) ;; *) exit 2 ;; esac\n"
            "codex exec --yolo -c approval_policy=never \"$(< \"$PROMPT_FILE\")\"\n",
        ),
        encoding="utf-8",
    )
    node_launcher.chmod(0o755)
    _write_json(
        loop / "contracts" / "master_dispatch_template.json",
        _active_template_json(
            "contracts/master_dispatch_template.json",
            {"version": "1.0", "role": "master_god"},
        ),
    )
    _write_json(
        loop / "contracts" / "slave_dispatch_template.json",
        _active_template_json(
            "contracts/slave_dispatch_template.json",
            {"version": "1.0", "role": "slave_god"},
        ),
    )

    for feature in features:
        feature_id = feature["id"]
        _write_json(
            loop / "work" / "features" / feature_id / "slave_state.json",
            {
                "version": "1.0",
                "feature_id": feature_id,
                "mode": "feature_local_single_god",
                "state": feature["state"],
                "artifacts": feature["artifacts"],
                "last_updated": "2026-05-24T00:00:00Z",
            },
        )
        (loop / "work" / "features" / feature_id / "blueprint.md").parent.mkdir(
            parents=True, exist_ok=True
        )
        (loop / "work" / "features" / feature_id / "blueprint.md").touch(exist_ok=True)
        (loop / "master" / "features" / feature_id).mkdir(parents=True, exist_ok=True)
        (loop / "approvals" / feature_id).mkdir(parents=True, exist_ok=True)

    validation = validate_master_state(master_state)
    return {"status": "prepared" if validation["valid"] else "blocked", "validation": validation}


def _controller_path(loop: Path, ref: str) -> Path:
    return _core_controller_path(loop, ref)


def validate_merge_queue_gate(loop_root: str | Path, feature: dict[str, Any]) -> dict[str, Any]:
    return _validate_merge_queue_gate_core(
        loop_root,
        feature,
        current_target_head=_current_target_head,
    )


def _move_if_exists(source: Path, destination: Path) -> None:
    if source.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)


def _rollback_moves(moved: list[tuple[Path, Path]]) -> None:
    for original, moved_path in reversed(moved):
        if moved_path.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            moved_path.replace(original)


def _restore_legacy_sources(loop: Path, legacy_root: Path) -> None:
    for name in LEGACY_ROOT_FILES:
        moved_path = legacy_root / name
        original = loop / name
        if moved_path.exists() and not original.exists():
            original.parent.mkdir(parents=True, exist_ok=True)
            moved_path.replace(original)
    moved_dispatch = legacy_root / "contracts" / "god_dispatch_template.json"
    original_dispatch = loop / "contracts" / "god_dispatch_template.json"
    if moved_dispatch.exists() and not original_dispatch.exists():
        original_dispatch.parent.mkdir(parents=True, exist_ok=True)
        moved_dispatch.replace(original_dispatch)


def _snapshot_file(path: Path) -> str | None:
    return path.read_text(encoding="utf-8") if path.exists() else None


def _restore_file_snapshot(path: Path, content: str | None) -> None:
    if content is None:
        if path.exists():
            path.unlink()
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def activate_master_migration(loop_root: str | Path) -> dict[str, Any]:
    loop = Path(loop_root)
    master_path = loop / MASTER_STATE_FILE
    master_state = json.loads(master_path.read_text(encoding="utf-8"))
    validation = validate_master_state(master_state)
    if not validation["valid"] or master_state.get("activation_state") != "master_pending":
        return {
            "status": "blocked",
            "errors": validation["errors"]
            + ["master_state must be valid master_pending before activation"],
        }

    required_files = [
        loop / "master_blueprint.md",
        loop / "master_config.json",
        loop / "prompts" / "master_god_prompt.md",
        loop / "prompts" / "slave_god_prompt.md",
        loop / "codex_node_launcher.sh",
        loop / "contracts" / "master_dispatch_template.json",
        loop / "contracts" / "slave_dispatch_template.json",
    ]
    missing = [str(path) for path in required_files if not path.exists()]
    for feature in master_state["features"]:
        slave_state = _controller_path(loop, feature["slave_state_path"])
        if not slave_state.exists():
            missing.append(str(slave_state))
    if missing:
        return {
            "status": "blocked",
            "errors": [f"missing activation file: {path}" for path in missing],
        }

    active_state = dict(master_state)
    active_state["activation_state"] = "master_active"
    active_state["active"] = True
    active_state["queues"] = derive_master_queues(active_state, loop_root=loop)["queues"]
    validation = validate_master_state(active_state)
    if not validation["valid"]:
        return {"status": "blocked", "errors": validation["errors"]}

    legacy_root = loop / LEGACY_ROOT_LOOP_DIR
    pending_snapshot = json.loads(master_path.read_text(encoding="utf-8"))
    staged_master = master_path.with_suffix(".json.active.tmp")
    status_json = loop / MASTER_STATUS_JSON
    status_md = loop / MASTER_STATUS_MD
    status_json_snapshot = _snapshot_file(status_json)
    status_md_snapshot = _snapshot_file(status_md)
    staged_status_json = status_json.with_suffix(".json.active.tmp")
    staged_status_md = status_md.with_suffix(".md.active.tmp")
    moved: list[tuple[Path, Path]] = []
    try:
        for name in LEGACY_ROOT_FILES:
            source = loop / name
            destination = legacy_root / name
            _move_if_exists(source, destination)
            if destination.exists():
                moved.append((source, destination))
        dispatch_source = loop / "contracts" / "god_dispatch_template.json"
        dispatch_destination = legacy_root / "contracts" / "god_dispatch_template.json"
        _move_if_exists(dispatch_source, dispatch_destination)
        if dispatch_destination.exists():
            moved.append((dispatch_source, dispatch_destination))
        active_status = build_master_status(loop, active_state)
        _write_master_status_files(active_status, staged_status_json, staged_status_md)
        _write_json(staged_master, active_state)
        staged_master.replace(master_path)
        staged_status_json.replace(status_json)
        staged_status_md.replace(status_md)
    except Exception as exc:
        _rollback_moves(moved)
        _restore_legacy_sources(loop, legacy_root)
        for staged in (staged_master, staged_status_json, staged_status_md):
            if staged.exists():
                staged.unlink()
        _restore_file_snapshot(status_json, status_json_snapshot)
        _restore_file_snapshot(status_md, status_md_snapshot)
        _write_json(master_path, pending_snapshot)
        return {"status": "blocked", "errors": [str(exc)]}
    return {"status": "activated", "errors": []}


def summarize_master_slave_control(
    loop_root: str | Path,
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    return _summarize_master_slave_control_core(
        loop_root,
        project_root=project_root,
        resolve_active_controller=resolve_active_controller,
        write_master_status=write_master_status,
    )


def write_master_slave_status(
    loop_root: str | Path,
    summary: dict[str, Any] | None = None,
) -> dict[str, str]:
    return _write_master_slave_status_core(
        loop_root,
        summary,
        summarize=lambda loop: summarize_master_slave_control(loop),
    )


def run_phase_hardening(
    loop_root: str | Path,
    eval_root: str | Path,
    phase_id: str,
    *,
    write: bool = False,
) -> dict[str, Any]:
    return _run_phase_hardening_core(
        loop_root,
        eval_root,
        phase_id,
        write=write,
        summarize_master_slave=lambda loop: summarize_master_slave_control(
            loop,
            project_root=Path(loop).parent,
        ),
        write_master_slave_status=write_master_slave_status,
    )


def _run_phase8(loop_root: Path, eval_root: Path, write: bool) -> dict[str, Any]:
    reports = loop_root / "work" / "phase-8" / "reports" / "run_ids.txt"
    run_ids: dict[str, str] = {}
    if reports.exists():
        for line in reports.read_text(encoding="utf-8").splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                run_ids[key.strip()] = value.strip()

    specs = [
        ("longmemeval", run_ids.get("LME_RUN_ID", "")),
        ("locomo", run_ids.get("LOCOMO_RUN_ID", "")),
    ]
    statuses = []
    for benchmark, run_id in specs:
        if not run_id:
            continue
        suffix = "longmemeval" if benchmark == "longmemeval" else "locomo"
        statuses.append(
            classify_eval_run(
                run_id=run_id,
                benchmark=benchmark,
                partial_path=eval_root / f"{run_id}_{suffix}.partial.json",
                final_path=eval_root / f"{run_id}_{suffix}.json",
            )
        )

    ack_gate = check_state_ack_consistency(loop_root, "phase-8")
    stale_index = scan_stale_artifacts(
        loop_root / "work" / "phase-8", current_context_bundle="work/phase-8/context_bundle.md"
    )
    if write:
        write_phase_status(
            loop_root,
            "phase-8",
            statuses,
            ack_gate=ack_gate,
            stale_index=stale_index,
        )
    return {"eval_runs": statuses, "ack_gate": ack_gate, "stale_index": stale_index}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop-root", default=Path(__file__).resolve().parent)
    parser.add_argument(
        "--eval-root",
        default=Path(__file__).resolve().parent.parent / ".memoryos" / "evals",
    )
    parser.add_argument("--phase", default="phase-8")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    loop_root = Path(args.loop_root)
    if args.phase == "phase-8":
        result = _run_phase8(loop_root, Path(args.eval_root), args.write)
    else:
        result = run_phase_hardening(
            loop_root,
            Path(args.eval_root),
            args.phase,
            write=args.write,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
