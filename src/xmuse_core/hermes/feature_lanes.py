from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from xmuse_core.core.paths import (
    controller_display_path,
    resolve_controller_path,
)
from xmuse_core.hermes.active_jobs import git_status_short
from xmuse_core.hermes.json_artifacts import atomic_write_json, atomic_write_text, read_json

PROMOTION_PASS_VERDICTS = {"pass", "passed", "usable", "usable_ack", "ack", "approved"}
FEATURE_LANES_FILE = "feature_lanes.json"
FEATURE_PASS_STATES = {"acked", "ready_for_master_review", "ready_for_merge", "merged"}
MASTER_REVIEW_STATES = {"ready_for_master_review"}
MERGE_REQUEST_STATES = {"ready_for_merge", "merge_requested"}
TARGET_BRANCH_STATES = MASTER_REVIEW_STATES | MERGE_REQUEST_STATES

MergeQueueGate = Callable[[Path, dict[str, Any]], dict[str, Any]]
ResolveActiveController = Callable[[Path], dict[str, Any]]
WriteMasterStatus = Callable[[Path, dict[str, Any]], dict[str, Any]]


def load_feature_lanes(loop_root: str | Path) -> dict[str, Any]:
    """Load optional master/slave feature-lane registry."""
    loop = Path(loop_root)
    registry_path = loop / FEATURE_LANES_FILE
    if not registry_path.exists():
        return {
            "ok": True,
            "state": "missing",
            "path": str(registry_path),
            "master_god": {},
            "features": [],
        }
    try:
        registry = read_json(registry_path)
    except Exception as exc:
        return {
            "ok": False,
            "state": "invalid",
            "path": str(registry_path),
            "error": f"invalid {FEATURE_LANES_FILE}: {exc}",
            "master_god": {},
            "features": [],
        }
    if not isinstance(registry, dict):
        return {
            "ok": False,
            "state": "invalid",
            "path": str(registry_path),
            "error": f"{FEATURE_LANES_FILE} root is not an object",
            "master_god": {},
            "features": [],
        }
    features = registry.get("features", [])
    if not isinstance(features, list):
        return {
            "ok": False,
            "state": "invalid",
            "path": str(registry_path),
            "error": "features must be a list",
            "master_god": registry.get("master_god", {}),
            "features": [],
        }
    return {
        "ok": True,
        "state": "loaded",
        "path": controller_display_path(loop, registry_path),
        "master_god": registry.get("master_god", {}),
        "features": features,
    }


def _artifact_gate(loop: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    paths: dict[str, str] = {}

    ack_path = resolve_controller_path(loop, artifacts.get("ack"))
    review_path = resolve_controller_path(loop, artifacts.get("review_verdict"))
    result_path = resolve_controller_path(loop, artifacts.get("result"))

    if ack_path is None:
        blockers.append("missing ack artifact path")
    else:
        paths["ack"] = controller_display_path(loop, ack_path)
        if not ack_path.exists():
            blockers.append("ack artifact does not exist")
        else:
            try:
                ack = read_json(ack_path)
            except Exception as exc:
                blockers.append(f"invalid ack artifact: {exc}")
            else:
                if not isinstance(ack, dict):
                    blockers.append("ack artifact root is not an object")
                elif str(ack.get("ack_level", "")).lower() != "usable":
                    blockers.append("ack artifact is not usable")

    if review_path is None:
        blockers.append("missing review_verdict artifact path")
    else:
        paths["review_verdict"] = controller_display_path(loop, review_path)
        if not review_path.exists():
            blockers.append("review_verdict artifact does not exist")
        else:
            try:
                review = read_json(review_path)
            except Exception as exc:
                blockers.append(f"invalid review_verdict artifact: {exc}")
            else:
                verdict = str(review.get("verdict", "")).lower() if isinstance(review, dict) else ""
                if verdict not in PROMOTION_PASS_VERDICTS:
                    blockers.append("review_verdict artifact is not passing")

    if result_path is None:
        blockers.append("missing result artifact path")
    else:
        paths["result"] = controller_display_path(loop, result_path)
        if not result_path.exists():
            blockers.append("result artifact does not exist")

    return {"ok": not blockers, "blockers": blockers, "paths": paths}


def _integrated_tests_gate(loop: Path, artifacts: dict[str, Any]) -> dict[str, Any]:
    blockers: list[str] = []
    paths: dict[str, str] = {}

    tests_path = resolve_controller_path(loop, artifacts.get("integrated_tests"))
    if tests_path is None:
        return {
            "ok": False,
            "blockers": ["missing integrated_tests artifact path"],
            "paths": paths,
        }
    paths["integrated_tests"] = controller_display_path(loop, tests_path)
    if not tests_path.exists():
        blockers.append("integrated_tests artifact does not exist")
    else:
        try:
            integrated = read_json(tests_path)
        except Exception as exc:
            blockers.append(f"invalid integrated_tests artifact: {exc}")
        else:
            if not isinstance(integrated, dict):
                blockers.append("integrated_tests artifact root is not an object")
            elif str(integrated.get("status", "")).lower() not in PROMOTION_PASS_VERDICTS:
                blockers.append("integrated_tests artifact is not passing")
    return {"ok": not blockers, "blockers": blockers, "paths": paths}


def classify_feature_lane(
    loop_root: str | Path,
    feature: dict[str, Any],
    *,
    project_root: str | Path | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    blockers: list[str] = []
    warnings: list[str] = []
    feature_id = str(feature.get("id") or "").strip()
    if not feature_id:
        blockers.append("feature id is required")
        feature_id = "<missing>"

    state = str(feature.get("state") or "planned").lower()
    if state not in {
        "planned",
        "planning",
        "executing",
        "review",
        "acked",
        "ready_for_master_review",
        "ready_for_merge",
        "merge_requested",
        "merged",
        "blocked",
        "held",
    }:
        blockers.append(f"unsupported feature state: {state}")

    slave_god = feature.get("slave_god", {})
    if not isinstance(slave_god, dict):
        blockers.append("slave_god must be an object")
        slave_god = {}

    merge = feature.get("merge", {})
    if not isinstance(merge, dict):
        merge = {}
        blockers.append("merge must be an object")
    merge_status = str(merge.get("status") or state).lower()
    gate_requested = (
        state in FEATURE_PASS_STATES | {"merge_requested"} or merge_status in TARGET_BRANCH_STATES
    )
    if merge_status in MERGE_REQUEST_STATES and state not in MERGE_REQUEST_STATES:
        blockers.append("merge status is ahead of feature state")
    if merge_status in MASTER_REVIEW_STATES and state not in MASTER_REVIEW_STATES:
        blockers.append("master review status is ahead of feature state")

    branch = feature.get("branch")
    worktree = feature.get("worktree")
    if gate_requested and not isinstance(branch, str):
        blockers.append("merge-ready feature requires branch")
    worktree_path = Path(worktree) if isinstance(worktree, str) and worktree else None
    if gate_requested:
        if worktree_path is None:
            blockers.append("merge-ready feature requires worktree")
        elif not worktree_path.exists():
            blockers.append("feature worktree does not exist")

    artifacts = feature.get("artifacts", {})
    if not isinstance(artifacts, dict):
        artifacts = {}
        blockers.append("artifacts must be an object")
    if gate_requested:
        artifact_gate = _artifact_gate(loop, artifacts)
    else:
        artifact_gate = {"ok": True, "blockers": [], "paths": {}}
    blockers.extend(artifact_gate["blockers"])

    target_branch = str(merge.get("target_branch") or "").strip()
    if merge_status in MERGE_REQUEST_STATES and not target_branch:
        blockers.append("merge target_branch is required")
    if merge_status in MASTER_REVIEW_STATES and not target_branch:
        blockers.append("master review target_branch is required")

    requires_integrated_tests = merge_status in MERGE_REQUEST_STATES or bool(
        merge.get("requires_integrated_tests")
    )
    if merge_status in MERGE_REQUEST_STATES:
        integrated_tests_gate = _integrated_tests_gate(loop, artifacts)
        blockers.extend(integrated_tests_gate["blockers"])
        artifact_gate["paths"].update(integrated_tests_gate["paths"])
    else:
        integrated_tests_gate = {"ok": True, "blockers": [], "paths": {}}

    git_status = None
    if worktree_path is not None and worktree_path.exists():
        git_status = git_status_short(worktree_path)
        if git_status and merge_status in TARGET_BRANCH_STATES:
            blockers.append("feature worktree has uncommitted changes")
        elif git_status:
            warnings.append("feature worktree has uncommitted changes")

    reviewable = (
        not blockers and merge_status in MASTER_REVIEW_STATES and artifact_gate.get("ok") is True
    )
    mergeable = (
        not blockers
        and merge_status in MERGE_REQUEST_STATES
        and artifact_gate.get("ok") is True
        and (not requires_integrated_tests or integrated_tests_gate.get("ok") is True)
    )
    return {
        "id": feature_id,
        "name": feature.get("name"),
        "state": state,
        "slave_god": slave_god,
        "branch": branch,
        "worktree": str(worktree_path) if worktree_path is not None else None,
        "merge": merge,
        "merge_status": merge_status,
        "reviewable": reviewable,
        "mergeable": mergeable,
        "blockers": blockers,
        "warnings": warnings,
        "artifact_gate": artifact_gate,
        "integrated_tests_gate": integrated_tests_gate,
        "git_status_short": git_status,
        "project_root": str(project_root) if project_root is not None else str(loop.parent),
    }


def summarize_master_slave_control(
    loop_root: str | Path,
    *,
    project_root: str | Path | None = None,
    resolve_active_controller: ResolveActiveController | None = None,
    write_master_status: WriteMasterStatus | None = None,
) -> dict[str, Any]:
    loop = Path(loop_root)
    if resolve_active_controller is not None and write_master_status is not None:
        controller = resolve_active_controller(loop)
        if controller["source"] == "master":
            status = write_master_status(loop, controller["state"])
            return {
                "ok": not status["errors"],
                "source": "xmuse/master_state.json",
                "path": "xmuse/master_state.json",
                "counts": status["counts"],
                "queues": status["queues"],
                "errors": status["errors"],
                "features": controller["state"].get("features", []),
                "master_review_queue": status["queues"].get("master_review_queue", []),
                "merge_queue": status["queues"].get("merge_queue", []),
                "blockers": status["errors"],
            }
        if controller["source"] == "blocked":
            return {
                "ok": False,
                "source": "blocked",
                "path": controller.get("path"),
                "counts": {
                    "total": 0,
                    "reviewable": 0,
                    "mergeable": 0,
                    "held": 0,
                    "blocked": 1,
                    "merged": 0,
                },
                "queues": {"blocked": ["master_state"]},
                "errors": controller.get("errors", []),
                "features": [],
                "master_review_queue": [],
                "merge_queue": [],
                "blockers": controller.get("errors", []),
            }

    registry = load_feature_lanes(loop)
    if not registry.get("ok"):
        return {
            "ok": False,
            "state": registry.get("state"),
            "path": registry.get("path"),
            "error": registry.get("error"),
            "master_god": registry.get("master_god", {}),
            "features": [],
            "master_review_queue": [],
            "merge_queue": [],
            "blockers": [registry.get("error", "invalid feature registry")],
        }

    features = [
        classify_feature_lane(loop, feature, project_root=project_root)
        for feature in registry.get("features", [])
        if isinstance(feature, dict)
    ]
    malformed_count = sum(
        1 for feature in registry.get("features", []) if not isinstance(feature, dict)
    )
    blockers: list[str] = []
    if malformed_count:
        blockers.append(f"{malformed_count} feature entries are not objects")
    for feature in features:
        for blocker in feature["blockers"]:
            blockers.append(f"{feature['id']}: {blocker}")

    def _queue_item(feature: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": feature["id"],
            "branch": feature["branch"],
            "worktree": feature["worktree"],
            "target_branch": feature["merge"].get("target_branch"),
            "strategy": feature["merge"].get("strategy", "git_worktree"),
        }

    master_review_queue = [_queue_item(feature) for feature in features if feature["reviewable"]]
    merge_queue = [_queue_item(feature) for feature in features if feature["mergeable"]]
    return {
        "ok": not blockers,
        "state": registry.get("state"),
        "path": registry.get("path"),
        "master_god": registry.get("master_god", {}),
        "features": features,
        "master_review_queue": master_review_queue,
        "merge_queue": merge_queue,
        "blockers": blockers,
        "counts": {
            "features": len(features),
            "reviewable": len(master_review_queue),
            "mergeable": len(merge_queue),
            "blocked": sum(1 for feature in features if feature["blockers"]),
        },
    }


def write_master_slave_status(
    loop_root: str | Path,
    summary: dict[str, Any] | None = None,
    *,
    summarize: Callable[[Path], dict[str, Any]] | None = None,
) -> dict[str, str]:
    loop = Path(loop_root)
    payload = summary or (summarize(loop) if summarize else summarize_master_slave_control(loop))
    json_path = loop / "master_slave_status.json"
    md_path = loop / "master_slave_status.md"
    atomic_write_json(json_path, payload)

    lines = ["# Hermes Master/Slave Feature Status", ""]
    lines.append(f"- registry: `{payload.get('path')}`")
    lines.append(f"- ok: `{payload.get('ok')}`")
    lines.append(f"- features: `{payload.get('counts', {}).get('features', 0)}`")
    lines.append(f"- reviewable: `{payload.get('counts', {}).get('reviewable', 0)}`")
    lines.append(f"- mergeable: `{payload.get('counts', {}).get('mergeable', 0)}`")
    lines.append("")
    for feature in payload.get("features", []):
        lines.append(
            f"- `{feature.get('id')}` state={feature.get('state')} "
            f"reviewable={feature.get('reviewable')} "
            f"mergeable={feature.get('mergeable')} branch={feature.get('branch')}"
        )
        for blocker in feature.get("blockers", []):
            lines.append(f"  - blocker: {blocker}")
        for warning in feature.get("warnings", []):
            lines.append(f"  - warning: {warning}")
    if payload.get("master_review_queue"):
        lines.append("")
        lines.append("## Master Review Queue")
        for item in payload["master_review_queue"]:
            lines.append(
                f"- `{item.get('id')}` {item.get('branch')} -> {item.get('target_branch')} "
                f"via {item.get('strategy')}"
            )
    if payload.get("merge_queue"):
        lines.append("")
        lines.append("## Merge Queue")
        for item in payload["merge_queue"]:
            lines.append(
                f"- `{item.get('id')}` {item.get('branch')} -> {item.get('target_branch')} "
                f"via {item.get('strategy')}"
            )
    atomic_write_text(md_path, "\n".join(lines) + "\n")
    return {"json": str(json_path), "markdown": str(md_path)}


__all__ = [
    "classify_feature_lane",
    "load_feature_lanes",
    "summarize_master_slave_control",
    "write_master_slave_status",
]
