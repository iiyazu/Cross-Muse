from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RUNNER_SESSION_SCHEMA_VERSION = "xmuse.runner_session.v1"
RUNNER_SESSION_LINEAGE_SCHEMA_VERSION = "xmuse.runner_session_lineage.v1"
RUNNER_SESSION_AUTHORITY = "platform_runner_session_boundary"
RUNNER_SESSION_COMPLETED_STATUS = "session_completed"
RUNNER_SESSION_STARTED_STATUS = "session_started"
RUNNER_SESSION_FAILED_STATUS = "session_failed"
RUNNER_SESSION_STATUSES = frozenset(
    {
        RUNNER_SESSION_STARTED_STATUS,
        RUNNER_SESSION_COMPLETED_STATUS,
        RUNNER_SESSION_FAILED_STATUS,
    }
)

RUNNER_SESSION_FORBIDDEN_CLAIMS = [
    "runner_session_is_review_truth",
    "runner_session_is_server_truth",
    "runner_session_is_live_invocation_proof",
    "runner_session_is_graph_wide_closure",
    "end_to_end_execution_review_closure",
    "ready_to_merge",
    "pr_merged",
]

RUNNER_SESSION_MANUAL_GAPS = [
    "review_truth_not_proven",
    "server_truth_not_proven",
    "github_truth_not_checked",
    "live_memoryos_trace_not_proven",
    "overnight_safe_recovery_not_proven",
]
RUNNER_SESSION_CANDIDATE_REFS_MISSING_GAP = "runner_session_candidate_refs_missing"


def capture_runner_session_started(
    *,
    output_path: str | Path,
    session_id: str,
    run_id: str,
    runner_id: str,
    lanes_path: str | Path,
    xmuse_root: str | Path,
    graph_id: str | None = None,
    resolution_id: str | None = None,
    writer_lease_id: str | None = None,
) -> dict[str, Any]:
    artifact = build_runner_session_artifact(
        session_id=session_id,
        run_id=run_id,
        runner_id=runner_id,
        status=RUNNER_SESSION_STARTED_STATUS,
        started_at=_utc_now(),
        lanes_path=str(lanes_path),
        xmuse_root=str(xmuse_root),
        graph_id=graph_id,
        resolution_id=resolution_id,
        writer_lease_id=writer_lease_id,
    )
    _write_json(output_path, artifact)
    return artifact


def capture_runner_session_finished(
    *,
    output_path: str | Path,
    status: str,
    candidate_artifact_refs: Sequence[str] = (),
    candidate_lane_ids: Sequence[str] = (),
    worker_evidence_bundle_refs: Sequence[str] = (),
    failure: str | None = None,
) -> dict[str, Any]:
    path = Path(output_path)
    existing = _load_existing(path)
    artifact = build_runner_session_artifact(
        session_id=_required_text(existing.get("session_id"), "session_id"),
        run_id=_required_text(existing.get("run_id"), "run_id"),
        runner_id=_required_text(existing.get("runner_id"), "runner_id"),
        status=status,
        started_at=_required_text(existing.get("started_at"), "started_at"),
        completed_at=_utc_now(),
        lanes_path=_text(existing.get("lanes_path")),
        xmuse_root=_text(existing.get("xmuse_root")),
        graph_id=_text(existing.get("graph_id")),
        resolution_id=_text(existing.get("resolution_id")),
        writer_lease_id=_text(existing.get("writer_lease_id")),
        candidate_artifact_refs=candidate_artifact_refs,
        candidate_lane_ids=candidate_lane_ids,
        worker_evidence_bundle_refs=worker_evidence_bundle_refs,
        failure=failure,
    )
    _write_json(path, artifact)
    return artifact


def build_runner_session_artifact(
    *,
    session_id: str,
    run_id: str,
    runner_id: str,
    status: str,
    started_at: str,
    completed_at: str | None = None,
    lanes_path: str | None = None,
    xmuse_root: str | None = None,
    graph_id: str | None = None,
    resolution_id: str | None = None,
    writer_lease_id: str | None = None,
    candidate_artifact_refs: Sequence[str] = (),
    candidate_lane_ids: Sequence[str] = (),
    worker_evidence_bundle_refs: Sequence[str] = (),
    failure: str | None = None,
) -> dict[str, Any]:
    clean_status = _required_text(status, "status")
    if clean_status not in RUNNER_SESSION_STATUSES:
        raise ValueError("runner session status is unsupported")
    completed = clean_status == RUNNER_SESSION_COMPLETED_STATUS
    if completed and _text(completed_at) is None:
        raise ValueError("completed runner session requires completed_at")
    if clean_status == RUNNER_SESSION_STARTED_STATUS and _text(completed_at) is not None:
        raise ValueError("started runner session must not have completed_at")
    candidate_refs = _dedupe(_string_list(candidate_artifact_refs))
    lane_ids = _dedupe(_string_list(candidate_lane_ids))
    worker_bundle_refs = _dedupe(_string_list(worker_evidence_bundle_refs))
    local_runtime_proven = completed and bool(candidate_refs)
    manual_gaps = list(RUNNER_SESSION_MANUAL_GAPS)
    if not completed:
        manual_gaps = _dedupe(
            ["runner_session_not_completed", *manual_gaps]
        )
    elif not candidate_refs:
        manual_gaps = _dedupe(
            [RUNNER_SESSION_CANDIDATE_REFS_MISSING_GAP, *manual_gaps]
        )
    return {
        "schema_version": RUNNER_SESSION_SCHEMA_VERSION,
        "source_authority": RUNNER_SESSION_AUTHORITY,
        "session_id": _required_text(session_id, "session_id"),
        "run_id": _required_text(run_id, "run_id"),
        "runner_id": _required_text(runner_id, "runner_id"),
        "status": clean_status,
        "proof_level": "local_runtime_proof" if local_runtime_proven else "manual_gap",
        "started_at": _required_text(started_at, "started_at"),
        "completed_at": _text(completed_at),
        "lanes_path": _text(lanes_path),
        "xmuse_root": _text(xmuse_root),
        "graph_id": _text(graph_id),
        "resolution_id": _text(resolution_id),
        "writer_lease_id": _text(writer_lease_id),
        "candidate_artifact_refs": candidate_refs,
        "candidate_lane_ids": lane_ids,
        "candidate_count": len(candidate_refs),
        "worker_evidence_bundle_refs": worker_bundle_refs,
        "worker_evidence_bundle_count": len(worker_bundle_refs),
        "failure": _text(failure),
        "manual_gaps": manual_gaps,
        "forbidden_claims": list(RUNNER_SESSION_FORBIDDEN_CLAIMS),
    }


def load_runner_session_lineage(
    *,
    root: str | Path,
    artifact_ref: str,
    session_id: str | None = None,
    run_id: str | None = None,
    runner_id: str | None = None,
    candidate_artifact_ref: str | None = None,
    graph_id: str | None = None,
) -> dict[str, Any]:
    path = runner_session_artifact_path(root, artifact_ref)
    if path is None or not path.is_file():
        raise FileNotFoundError(artifact_ref)
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("runner session artifact is invalid JSON") from exc
    if not isinstance(artifact, Mapping):
        raise ValueError("runner session artifact must be an object")
    return build_runner_session_lineage(
        artifact=artifact,
        artifact_ref=artifact_ref,
        session_id=session_id,
        run_id=run_id,
        runner_id=runner_id,
        candidate_artifact_ref=candidate_artifact_ref,
        graph_id=graph_id,
    )


def build_runner_session_lineage(
    *,
    artifact: Mapping[str, Any],
    artifact_ref: str,
    session_id: str | None = None,
    run_id: str | None = None,
    runner_id: str | None = None,
    candidate_artifact_ref: str | None = None,
    graph_id: str | None = None,
) -> dict[str, Any]:
    if _text(artifact.get("schema_version")) != RUNNER_SESSION_SCHEMA_VERSION:
        raise ValueError("runner session schema is unsupported")
    if _text(artifact.get("source_authority")) != RUNNER_SESSION_AUTHORITY:
        raise ValueError("runner session source authority is unsupported")
    status = _text(artifact.get("status"))
    proof_level = _text(artifact.get("proof_level"))
    if status != RUNNER_SESSION_COMPLETED_STATUS:
        raise ValueError("runner session is not completed")
    if proof_level != "local_runtime_proof":
        raise ValueError("runner session proof level is not local_runtime_proof")
    artifact_session_id = _required_text(artifact.get("session_id"), "session_id")
    artifact_run_id = _required_text(artifact.get("run_id"), "run_id")
    artifact_runner_id = _required_text(artifact.get("runner_id"), "runner_id")
    if session_id is not None and artifact_session_id != session_id:
        raise ValueError("runner session_id does not match candidate")
    if run_id is not None and artifact_run_id != run_id:
        raise ValueError("runner session run_id does not match candidate")
    if runner_id is not None and artifact_runner_id != runner_id:
        raise ValueError("runner session runner_id does not match candidate")
    if graph_id is not None:
        artifact_graph_id = _text(artifact.get("graph_id"))
        if artifact_graph_id not in {None, graph_id}:
            raise ValueError("runner session graph_id does not match review graph")
    candidate_refs = _dedupe(_string_list(artifact.get("candidate_artifact_refs")))
    if candidate_artifact_ref is not None and candidate_artifact_ref not in candidate_refs:
        raise ValueError("runner session does not include candidate artifact ref")
    worker_bundle_refs = _dedupe(
        _string_list(artifact.get("worker_evidence_bundle_refs"))
    )
    forbidden_claims = _string_list(artifact.get("forbidden_claims"))
    missing_forbidden = [
        claim for claim in RUNNER_SESSION_FORBIDDEN_CLAIMS if claim not in forbidden_claims
    ]
    if missing_forbidden:
        raise ValueError("runner session missing forbidden claims")
    manual_gaps = _dedupe(_string_list(artifact.get("manual_gaps")))
    if not set(RUNNER_SESSION_MANUAL_GAPS).issubset(set(manual_gaps)):
        raise ValueError("runner session missing manual gaps")
    return {
        "schema_version": RUNNER_SESSION_LINEAGE_SCHEMA_VERSION,
        "artifact_ref": artifact_ref,
        "source_authority": RUNNER_SESSION_AUTHORITY,
        "session_id": artifact_session_id,
        "run_id": artifact_run_id,
        "runner_id": artifact_runner_id,
        "status": status,
        "proof_level": proof_level,
        "graph_id": _text(artifact.get("graph_id")),
        "resolution_id": _text(artifact.get("resolution_id")),
        "writer_lease_id": _text(artifact.get("writer_lease_id")),
        "started_at": _text(artifact.get("started_at")),
        "completed_at": _text(artifact.get("completed_at")),
        "candidate_artifact_refs": candidate_refs,
        "candidate_lane_ids": _dedupe(_string_list(artifact.get("candidate_lane_ids"))),
        "candidate_count": len(candidate_refs),
        "worker_evidence_bundle_refs": worker_bundle_refs,
        "worker_evidence_bundle_count": len(worker_bundle_refs),
        "manual_gaps": manual_gaps,
        "forbidden_claims": forbidden_claims,
    }


def runner_session_artifact_path(root: str | Path, artifact_ref: str) -> Path | None:
    candidate = artifact_ref.strip()
    if not candidate or "://" in candidate or "/" not in candidate:
        return None
    base = Path(root).resolve()
    path = Path(candidate)
    resolved = path.resolve() if path.is_absolute() else (base / path).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


def _load_existing(path: Path) -> Mapping[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError("runner session start artifact is missing") from exc
    except json.JSONDecodeError as exc:
        raise ValueError("runner session start artifact is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise ValueError("runner session start artifact must be an object")
    return payload


def _write_json(path: str | Path, payload: Mapping[str, Any]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name(f".{output.name}.{os.getpid()}.tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(output)


def _required_text(value: object, field: str) -> str:
    text = _text(value)
    if text is None:
        raise ValueError(f"{field} is required")
    return text


def _text(value: object) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return None


def _string_list(value: object) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if not isinstance(value, Sequence):
        return []
    return [
        item.strip()
        for item in value
        if isinstance(item, str) and item.strip()
    ]


def _dedupe(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


__all__ = [
    "RUNNER_SESSION_AUTHORITY",
    "RUNNER_SESSION_COMPLETED_STATUS",
    "RUNNER_SESSION_FAILED_STATUS",
    "RUNNER_SESSION_FORBIDDEN_CLAIMS",
    "RUNNER_SESSION_LINEAGE_SCHEMA_VERSION",
    "RUNNER_SESSION_MANUAL_GAPS",
    "RUNNER_SESSION_SCHEMA_VERSION",
    "RUNNER_SESSION_STARTED_STATUS",
    "build_runner_session_artifact",
    "build_runner_session_lineage",
    "capture_runner_session_finished",
    "capture_runner_session_started",
    "load_runner_session_lineage",
    "runner_session_artifact_path",
]
