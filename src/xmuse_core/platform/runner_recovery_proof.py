from __future__ import annotations

import json
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
