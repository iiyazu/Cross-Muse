from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUNNER_RECOVERY_PROOF_SCHEMA_VERSION = "xmuse.local_runner_recovery_proof.v1"
RUNNER_RECOVERY_PROOF_AUTHORITY = (
    "platform_runner_candidate_selection"
    "+shared_runner_health_model"
    "+lane_recovery_artifact"
)

RUNNER_RECOVERY_FORBIDDEN_CLAIMS = [
    "overnight_safe_recovery",
    "end_to_end_execution_review_closure",
    "worker_output_is_review_truth",
    "ready_to_merge",
    "pr_merged",
]

RUNNER_RECOVERY_LINEAGE_SCHEMA_VERSION = "xmuse.local_runner_recovery_proof_lineage.v1"


def capture_runner_recovery_proof(
    *,
    output_path: str | Path,
    run_id: str,
    runner_id: str,
    lanes: list[dict[str, Any]],
    candidate_lanes: list[dict[str, Any]],
    runner_status: dict[str, Any],
    lanes_path: str | Path,
    xmuse_root: str | Path,
    graph_id: str | None = None,
    resolution_id: str | None = None,
) -> dict[str, Any]:
    artifact = build_runner_recovery_proof(
        run_id=run_id,
        runner_id=runner_id,
        lanes=lanes,
        candidate_lanes=candidate_lanes,
        runner_status=runner_status,
        lanes_path=lanes_path,
        xmuse_root=xmuse_root,
        graph_id=graph_id,
        resolution_id=resolution_id,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def build_runner_recovery_proof(
    *,
    run_id: str,
    runner_id: str,
    lanes: list[dict[str, Any]],
    candidate_lanes: list[dict[str, Any]],
    runner_status: dict[str, Any],
    lanes_path: str | Path,
    xmuse_root: str | Path,
    graph_id: str | None = None,
    resolution_id: str | None = None,
) -> dict[str, Any]:
    candidate_lane_ids = _lane_ids(candidate_lanes)
    recovery = _dict(runner_status.get("health")).get("recovery")
    recovery_summary = _dict(recovery)
    blocked_lanes = _dict_rows(recovery_summary.get("blocked_lanes"))
    invalid_artifacts = _dict_rows(recovery_summary.get("invalid_artifacts"))
    blocked_lane_ids = _lane_ids(blocked_lanes)
    invalid_lane_ids = _lane_ids(invalid_artifacts)
    excluded_blocked_lane_ids = [
        lane_id for lane_id in blocked_lane_ids if lane_id not in candidate_lane_ids
    ]
    proof_observed = bool(excluded_blocked_lane_ids or invalid_lane_ids)
    manual_gaps = [
        "live_long_running_runner_recovery_session_not_proven",
        "overnight_safe_recovery_not_proven",
        "review_truth_not_proven",
        "server_truth_not_proven",
    ]
    if not proof_observed:
        manual_gaps.insert(0, "no_durable_recovery_block_observed")
    return {
        "schema_version": RUNNER_RECOVERY_PROOF_SCHEMA_VERSION,
        "run_id": run_id,
        "runner_id": runner_id,
        "generated_at": _utc_now(),
        "status": "ok" if proof_observed else "manual_gap",
        "proof_level": "local_runtime_proof" if proof_observed else "manual_gap",
        "source_authority": RUNNER_RECOVERY_PROOF_AUTHORITY,
        "lanes_path": str(lanes_path),
        "xmuse_root": str(xmuse_root),
        "filters": {
            "graph_id": graph_id,
            "resolution_id": resolution_id,
        },
        "candidate_selection": {
            "source_authority": "platform_runner._candidate_lanes",
            "candidate_lane_ids": candidate_lane_ids,
            "excluded_recovery_blocked_lane_ids": excluded_blocked_lane_ids,
            "invalid_recovery_artifact_lane_ids": invalid_lane_ids,
            "lane_count": len(lanes),
        },
        "runner_supervisor": {
            "source_authority": "run_health.build_run_health_model",
            "recovery": recovery_summary,
        },
        "source_refs": _dedupe(
            [
                *_string_list(recovery_summary.get("source_refs")),
                *[
                    str(item.get("artifact_ref"))
                    for item in [*blocked_lanes, *invalid_artifacts]
                    if item.get("artifact_ref")
                ],
            ]
        ),
        "target_refs": _dedupe(
            [
                *[f"lane:{lane_id}" for lane_id in candidate_lane_ids],
                *[f"lane:{lane_id}" for lane_id in blocked_lane_ids],
                *[f"lane:{lane_id}" for lane_id in invalid_lane_ids],
            ]
        ),
        "manual_gaps": _dedupe(manual_gaps),
        "forbidden_claims": list(RUNNER_RECOVERY_FORBIDDEN_CLAIMS),
    }


def build_runner_recovery_proof_lineage(
    *,
    proof: Mapping[str, Any],
    artifact_ref: str,
    graph_id: str,
    lane_id: str,
) -> dict[str, Any]:
    """Validate a runner recovery proof for L9 lineage consumption.

    The returned payload is intentionally lineage-only. It does not upgrade the
    recovery proof into review truth, execution truth, server truth, or merge
    readiness.
    """

    if _text(proof.get("schema_version")) != RUNNER_RECOVERY_PROOF_SCHEMA_VERSION:
        raise ValueError("runner recovery proof schema is unsupported")
    if _text(proof.get("source_authority")) != RUNNER_RECOVERY_PROOF_AUTHORITY:
        raise ValueError("runner recovery proof source authority is unsupported")
    status = _text(proof.get("status"))
    proof_level = _text(proof.get("proof_level"))
    if status not in {"ok", "manual_gap"}:
        raise ValueError("runner recovery proof status is unsupported")
    if proof_level not in {"local_runtime_proof", "manual_gap"}:
        raise ValueError("runner recovery proof overclaims proof level")
    if (status, proof_level) not in {
        ("ok", "local_runtime_proof"),
        ("manual_gap", "manual_gap"),
    }:
        raise ValueError("runner recovery proof status/proof_level mismatch")

    forbidden_claims = _string_list(proof.get("forbidden_claims"))
    missing_forbidden_claims = [
        claim for claim in RUNNER_RECOVERY_FORBIDDEN_CLAIMS if claim not in forbidden_claims
    ]
    if missing_forbidden_claims:
        raise ValueError("runner recovery proof missing forbidden claims")
    manual_gaps = _dedupe(_string_list(proof.get("manual_gaps")))
    required_manual_gaps = {
        "review_truth_not_proven",
        "server_truth_not_proven",
        "overnight_safe_recovery_not_proven",
    }
    if not required_manual_gaps.issubset(set(manual_gaps)):
        raise ValueError("runner recovery proof missing manual gaps")

    filters = _dict(proof.get("filters"))
    filtered_graph_id = _text(filters.get("graph_id"))
    if filtered_graph_id is None:
        raise ValueError("runner recovery proof graph filter is required")
    if filtered_graph_id != graph_id:
        raise ValueError("runner recovery proof graph filter does not match review closure")

    target_ref = f"lane:{lane_id}"
    target_refs = _string_list(proof.get("target_refs"))
    if target_ref not in target_refs:
        raise ValueError("runner recovery proof does not target the review closure lane")

    candidate_selection = _dict(proof.get("candidate_selection"))
    excluded_blocked_lane_ids = _string_list(
        candidate_selection.get("excluded_recovery_blocked_lane_ids")
    )
    invalid_lane_ids = _string_list(
        candidate_selection.get("invalid_recovery_artifact_lane_ids")
    )
    candidate_lane_ids = _string_list(candidate_selection.get("candidate_lane_ids"))
    blocked_or_invalid = lane_id in {
        *excluded_blocked_lane_ids,
        *invalid_lane_ids,
    }
    if proof_level == "local_runtime_proof" and not blocked_or_invalid:
        raise ValueError("runner recovery proof does not show a target-lane recovery block")

    source_refs = _string_list(proof.get("source_refs"))
    if proof_level == "local_runtime_proof" and not source_refs:
        raise ValueError("runner recovery proof has no durable source refs")

    lineage_status = "manual_gap"
    if lane_id in excluded_blocked_lane_ids:
        lineage_status = "target_lane_recovery_blocked"
    elif lane_id in invalid_lane_ids:
        lineage_status = "target_lane_recovery_artifact_invalid"

    return {
        "schema_version": RUNNER_RECOVERY_LINEAGE_SCHEMA_VERSION,
        "artifact_ref": artifact_ref,
        "source_authority": RUNNER_RECOVERY_PROOF_AUTHORITY,
        "status": lineage_status,
        "proof_level": proof_level,
        "graph_id": graph_id,
        "lane_id": lane_id,
        "filtered_graph_id": filtered_graph_id,
        "candidate_lane_ids": candidate_lane_ids,
        "excluded_recovery_blocked_lane_ids": excluded_blocked_lane_ids,
        "invalid_recovery_artifact_lane_ids": invalid_lane_ids,
        "source_refs": source_refs,
        "target_refs": target_refs,
        "manual_gaps": manual_gaps,
        "forbidden_claims": forbidden_claims,
    }


def _lane_ids(lanes: list[dict[str, Any]]) -> list[str]:
    return [
        lane_id
        for lane in lanes
        if (lane_id := _text(lane.get("lane_id") or lane.get("feature_id") or lane.get("id")))
        is not None
    ]


def _dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _dict_rows(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
