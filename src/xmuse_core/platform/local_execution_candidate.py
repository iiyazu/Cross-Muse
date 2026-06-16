from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.structuring.feature_graph_artifact_store import FeatureGraphArtifactStore
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_review_contracts import FeatureGraphExecutionStatus

LOCAL_EXECUTION_CANDIDATE_SCHEMA_VERSION = "xmuse.local_execution_candidate.v1"
LOCAL_EXECUTION_CANDIDATE_LINEAGE_SCHEMA_VERSION = (
    "xmuse.local_execution_candidate_lineage.v1"
)
LOCAL_EXECUTION_CANDIDATE_WORKER_EVIDENCE_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.local_execution_candidate_worker_evidence_boundary.v1"
)
VALIDATED_EXECUTION_CANDIDATE_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.validated_execution_candidate_boundary.v1"
)
LOCAL_EXECUTION_CANDIDATE_AUTHORITY = "local_execution_candidate_capture"
LOCAL_EXECUTION_CANDIDATE_GRAPH_STATUS_AUTHORITY = "feature_graph_status_store"
LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER = "platform_runner_dispatch"
LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER = "manual_cli_capture"
LOCAL_EXECUTION_CANDIDATE_PRODUCERS = frozenset(
    {
        LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
        LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER,
    }
)

LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS = [
    "worker_output_is_review_truth",
    "end_to_end_execution_review_closure",
    "ready_to_merge",
    "pr_merged",
    "github_review_truth",
    "live_memoryos",
]

LOCAL_EXECUTION_CANDIDATE_MANUAL_GAPS = [
    "review_truth_not_proven",
    "server_truth_not_proven",
    "github_truth_not_checked",
    "live_memoryos_trace_not_proven",
]


def capture_local_execution_candidate(
    *,
    output_path: str | Path,
    lane_id: str,
    candidate_id: str,
    conversation_id: str | None = None,
    lane_local_id: str | None = None,
    graph_id: str | None = None,
    graph_set_id: str | None = None,
    feature_graph_id: str | None = None,
    feature_graph_status_id: str | None = None,
    feature_graph_status: str | None = None,
    graph_status_lineage: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    worker_id: str | None = None,
    runner_session_id: str | None = None,
    runner_session_ref: str | None = None,
    command: str | None = None,
    exit_code: int | None = None,
    producer: str = LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER,
    source_refs: Sequence[str] = (),
    output_refs: Sequence[str] = (),
    changed_file_refs: Sequence[str] = (),
    verification_refs: Sequence[str] = (),
    proof_level: str = "local_runtime_proof",
    status: str = "candidate_only",
    manual_gaps: Sequence[str] = (),
) -> dict[str, Any]:
    artifact = build_local_execution_candidate(
        lane_id=lane_id,
        candidate_id=candidate_id,
        conversation_id=conversation_id,
        lane_local_id=lane_local_id,
        graph_id=graph_id,
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
        feature_graph_status_id=feature_graph_status_id,
        feature_graph_status=feature_graph_status,
        graph_status_lineage=graph_status_lineage,
        run_id=run_id,
        worker_id=worker_id,
        runner_session_id=runner_session_id,
        runner_session_ref=runner_session_ref,
        command=command,
        exit_code=exit_code,
        producer=producer,
        source_refs=source_refs,
        output_refs=output_refs,
        changed_file_refs=changed_file_refs,
        verification_refs=verification_refs,
        proof_level=proof_level,
        status=status,
        manual_gaps=manual_gaps,
    )
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(artifact, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return artifact


def build_local_execution_candidate(
    *,
    lane_id: str,
    candidate_id: str,
    conversation_id: str | None = None,
    lane_local_id: str | None = None,
    graph_id: str | None = None,
    graph_set_id: str | None = None,
    feature_graph_id: str | None = None,
    feature_graph_status_id: str | None = None,
    feature_graph_status: str | None = None,
    graph_status_lineage: Mapping[str, Any] | None = None,
    run_id: str | None = None,
    worker_id: str | None = None,
    runner_session_id: str | None = None,
    runner_session_ref: str | None = None,
    command: str | None = None,
    exit_code: int | None = None,
    producer: str = LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER,
    source_refs: Sequence[str] = (),
    output_refs: Sequence[str] = (),
    changed_file_refs: Sequence[str] = (),
    verification_refs: Sequence[str] = (),
    proof_level: str = "local_runtime_proof",
    status: str = "candidate_only",
    manual_gaps: Sequence[str] = (),
) -> dict[str, Any]:
    clean_lane_id = _required_text(lane_id, "lane_id")
    clean_candidate_id = _required_text(candidate_id, "candidate_id")
    clean_status = _required_text(status, "status")
    clean_proof_level = _required_text(proof_level, "proof_level")
    clean_producer = _required_text(producer, "producer")
    if clean_status not in {"candidate_only", "manual_gap"}:
        raise ValueError("local execution candidate status is unsupported")
    if clean_proof_level not in {"local_runtime_proof", "manual_gap"}:
        raise ValueError("local execution candidate proof_level is unsupported")
    if clean_producer not in LOCAL_EXECUTION_CANDIDATE_PRODUCERS:
        raise ValueError("local execution candidate producer is unsupported")
    if (clean_status, clean_proof_level) not in {
        ("candidate_only", "local_runtime_proof"),
        ("manual_gap", "manual_gap"),
    }:
        raise ValueError("local execution candidate status/proof_level mismatch")
    if clean_status == "candidate_only" and (
        clean_producer == LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER
        and (
            _text(run_id) is None
            or _text(worker_id) is None
            or _text(runner_session_id) is None
            or _text(runner_session_ref) is None
        )
    ):
        raise ValueError(
            "platform_runner_dispatch local execution candidate requires "
            "run_id, worker_id, runner_session_id, and runner_session_ref"
        )
    clean_graph_status_lineage = _build_graph_status_lineage(
        graph_status_lineage=graph_status_lineage,
        graph_set_id=graph_set_id,
        feature_graph_id=feature_graph_id,
        feature_graph_status_id=feature_graph_status_id,
        feature_graph_status=feature_graph_status,
    )
    if clean_status == "candidate_only" and clean_graph_status_lineage is None:
        raise ValueError(
            "candidate_only local execution candidate requires graph status lineage"
        )

    all_manual_gaps = _dedupe(
        [
            *LOCAL_EXECUTION_CANDIDATE_MANUAL_GAPS,
            *_string_list(manual_gaps),
        ]
    )
    if clean_status == "manual_gap":
        candidate_missing_gaps = ["local_execution_candidate_not_observed"]
        if clean_graph_status_lineage is None:
            candidate_missing_gaps.append("graph_status_lineage_missing")
        all_manual_gaps = _dedupe(
            [
                *candidate_missing_gaps,
                *all_manual_gaps,
            ]
        )

    artifact: dict[str, Any] = {
        "schema_version": LOCAL_EXECUTION_CANDIDATE_SCHEMA_VERSION,
        "candidate_id": clean_candidate_id,
        "generated_at": _utc_now(),
        "status": clean_status,
        "proof_level": clean_proof_level,
        "source_authority": LOCAL_EXECUTION_CANDIDATE_AUTHORITY,
        "producer": clean_producer,
        "conversation_id": _text(conversation_id),
        "lane_id": clean_lane_id,
        "lane_local_id": _text(lane_local_id),
        "graph_id": _text(graph_id),
        "graph_set_id": (
            clean_graph_status_lineage.get("graph_set_id")
            if clean_graph_status_lineage is not None
            else _text(graph_set_id)
        ),
        "feature_graph_id": (
            clean_graph_status_lineage.get("feature_graph_id")
            if clean_graph_status_lineage is not None
            else _text(feature_graph_id)
        ),
        "feature_graph_status_id": (
            clean_graph_status_lineage.get("status_id")
            if clean_graph_status_lineage is not None
            else _text(feature_graph_status_id)
        ),
        "feature_graph_status": (
            clean_graph_status_lineage.get("status")
            if clean_graph_status_lineage is not None
            else _text(feature_graph_status)
        ),
        "graph_status_source_authority": (
            clean_graph_status_lineage.get("source_authority")
            if clean_graph_status_lineage is not None
            else None
        ),
        "graph_status_lineage": clean_graph_status_lineage,
        "run_id": _text(run_id),
        "worker_id": _text(worker_id),
        "runner_session_id": _text(runner_session_id),
        "runner_session_ref": _text(runner_session_ref),
        "command": _text(command),
        "exit_code": exit_code,
        "source_refs": _string_list(source_refs),
        "output_refs": _string_list(output_refs),
        "changed_file_refs": _string_list(changed_file_refs),
        "verification_refs": _string_list(verification_refs),
        "candidate_truth_status": "candidate_only",
        "manual_gaps": all_manual_gaps,
        "forbidden_claims": list(LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS),
    }
    return artifact


def load_local_execution_candidate_lineage(
    *,
    root: str | Path,
    artifact_ref: str,
    lane_id: str | None = None,
    graph_id: str | None = None,
    conversation_id: str | None = None,
    required_producer: str | None = None,
) -> dict[str, Any]:
    path = local_execution_candidate_artifact_path(root, artifact_ref)
    if path is None or not path.is_file():
        raise FileNotFoundError(artifact_ref)
    try:
        artifact = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("local execution candidate artifact is invalid JSON") from exc
    if not isinstance(artifact, Mapping):
        raise ValueError("local execution candidate artifact must be an object")
    return build_local_execution_candidate_lineage(
        artifact=artifact,
        artifact_ref=artifact_ref,
        lane_id=lane_id,
        graph_id=graph_id,
        conversation_id=conversation_id,
        required_producer=required_producer,
    )


def build_local_execution_candidate_lineage(
    *,
    artifact: Mapping[str, Any],
    artifact_ref: str,
    lane_id: str | None = None,
    graph_id: str | None = None,
    conversation_id: str | None = None,
    required_producer: str | None = None,
) -> dict[str, Any]:
    if _text(artifact.get("schema_version")) != LOCAL_EXECUTION_CANDIDATE_SCHEMA_VERSION:
        raise ValueError("local execution candidate schema is unsupported")
    if _text(artifact.get("source_authority")) != LOCAL_EXECUTION_CANDIDATE_AUTHORITY:
        raise ValueError("local execution candidate source authority is unsupported")
    producer = _text(artifact.get("producer")) or LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER
    if producer not in LOCAL_EXECUTION_CANDIDATE_PRODUCERS:
        raise ValueError("local execution candidate producer is unsupported")
    if required_producer is not None and producer != required_producer:
        raise ValueError(
            f"local execution candidate producer is not {required_producer}"
        )

    status = _text(artifact.get("status"))
    proof_level = _text(artifact.get("proof_level"))
    if status not in {"candidate_only", "manual_gap"}:
        raise ValueError("local execution candidate status is unsupported")
    if proof_level not in {"local_runtime_proof", "manual_gap"}:
        raise ValueError("local execution candidate proof level is unsupported")
    if (status, proof_level) not in {
        ("candidate_only", "local_runtime_proof"),
        ("manual_gap", "manual_gap"),
    }:
        raise ValueError("local execution candidate status/proof_level mismatch")

    artifact_lane_id = _text(artifact.get("lane_id"))
    if artifact_lane_id is None:
        raise ValueError("local execution candidate missing lane_id")
    artifact_lane_ids = {
        value
        for value in (artifact_lane_id, _text(artifact.get("lane_local_id")))
        if value is not None
    }
    if lane_id is not None and lane_id not in artifact_lane_ids:
        raise ValueError("local execution candidate lane_id does not match review lane")

    artifact_graph_id = _text(artifact.get("graph_id"))
    if graph_id is not None and artifact_graph_id not in {None, graph_id}:
        raise ValueError("local execution candidate graph_id does not match review graph")
    artifact_conversation_id = _text(artifact.get("conversation_id"))
    if conversation_id is not None and artifact_conversation_id != conversation_id:
        raise ValueError(
            "local execution candidate conversation_id does not match review scope"
        )
    graph_status_lineage = (
        _validate_graph_status_lineage(artifact.get("graph_status_lineage"))
        if status == "candidate_only"
        else None
    )
    if status == "candidate_only":
        if artifact_graph_id is None:
            raise ValueError("local execution candidate missing graph_id")
        if (
            producer == LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER
            and (
                _text(artifact.get("run_id")) is None
                or _text(artifact.get("worker_id")) is None
                or _text(artifact.get("runner_session_id")) is None
                or _text(artifact.get("runner_session_ref")) is None
            )
        ):
            raise ValueError(
                "platform_runner_dispatch local execution candidate missing "
                "run_id, worker_id, runner_session_id, or runner_session_ref"
            )
        if graph_status_lineage is None:
            raise ValueError(
                "local execution candidate missing graph status lineage"
            )
        _raise_if_artifact_graph_status_fields_conflict(
            artifact=artifact,
            lineage=graph_status_lineage,
        )

    forbidden_claims = _string_list(artifact.get("forbidden_claims"))
    missing_forbidden = [
        claim
        for claim in LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS
        if claim not in forbidden_claims
    ]
    if missing_forbidden:
        raise ValueError("local execution candidate missing forbidden claims")

    manual_gaps = _dedupe(_string_list(artifact.get("manual_gaps")))
    required_manual_gaps = set(LOCAL_EXECUTION_CANDIDATE_MANUAL_GAPS)
    if not required_manual_gaps.issubset(set(manual_gaps)):
        raise ValueError("local execution candidate missing manual gaps")

    return {
        "schema_version": LOCAL_EXECUTION_CANDIDATE_LINEAGE_SCHEMA_VERSION,
        "artifact_ref": artifact_ref,
        "candidate_id": _text(artifact.get("candidate_id")),
        "source_authority": LOCAL_EXECUTION_CANDIDATE_AUTHORITY,
        "producer": producer,
        "status": status,
        "proof_level": proof_level,
        "conversation_id": artifact_conversation_id,
        "lane_id": artifact_lane_id,
        "lane_local_id": _text(artifact.get("lane_local_id")),
        "graph_id": artifact_graph_id,
        "graph_status_lineage": graph_status_lineage,
        "run_id": _text(artifact.get("run_id")),
        "worker_id": _text(artifact.get("worker_id")),
        "runner_session_id": _text(artifact.get("runner_session_id")),
        "runner_session_ref": _text(artifact.get("runner_session_ref")),
        "candidate_truth_status": "candidate_only",
        "source_refs": _string_list(artifact.get("source_refs")),
        "output_refs": _string_list(artifact.get("output_refs")),
        "changed_file_refs": _string_list(artifact.get("changed_file_refs")),
        "verification_refs": _string_list(artifact.get("verification_refs")),
        "manual_gaps": manual_gaps,
        "forbidden_claims": forbidden_claims,
    }


def valid_local_execution_candidate_lineages(
    *,
    root: str | Path,
    refs: Sequence[str],
    lane_id: str | None = None,
    graph_id: str | None = None,
    conversation_id: str | None = None,
    required_producer: str | None = None,
) -> list[dict[str, Any]]:
    lineages: list[dict[str, Any]] = []
    for ref in refs:
        try:
            lineages.append(
                load_local_execution_candidate_lineage(
                    root=root,
                    artifact_ref=ref,
                    lane_id=lane_id,
                    graph_id=graph_id,
                    conversation_id=conversation_id,
                    required_producer=required_producer,
                )
            )
        except FileNotFoundError:
            continue
        except ValueError as exc:
            raise ValueError(
                f"local execution candidate artifact {ref} is invalid: {exc}"
            ) from exc
    return _unique_lineages(lineages)


def build_validated_execution_candidate_boundary(
    *,
    candidate_lineage: Mapping[str, Any],
    runner_session_lineage: Mapping[str, Any] | None,
    graph_id: str,
    lane_id: str,
) -> dict[str, Any]:
    """Validate bounded L9 review intake without promoting review truth."""

    required_graph_id = _required_text(graph_id, "graph_id")
    required_lane_id = _required_text(lane_id, "lane_id")
    issues: list[str] = []

    candidate_artifact_ref = _text(candidate_lineage.get("artifact_ref"))
    candidate_graph_id = _text(candidate_lineage.get("graph_id"))
    candidate_lane_id = _text(candidate_lineage.get("lane_id"))
    candidate_lane_local_id = _text(candidate_lineage.get("lane_local_id"))
    candidate_lane_ids = {
        value for value in (candidate_lane_id, candidate_lane_local_id) if value
    }
    candidate_run_id = _text(candidate_lineage.get("run_id"))
    candidate_worker_id = _text(candidate_lineage.get("worker_id"))
    candidate_runner_session_id = _text(candidate_lineage.get("runner_session_id"))
    candidate_runner_session_ref = _text(candidate_lineage.get("runner_session_ref"))
    graph_status_lineage = _mapping(candidate_lineage.get("graph_status_lineage"))
    candidate_bundle_refs = _feature_evidence_bundle_refs(
        candidate_lineage.get("source_refs")
    )

    if _text(candidate_lineage.get("producer")) != (
        LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER
    ):
        issues.append("local execution candidate is not platform_runner_dispatch")
    if _text(candidate_lineage.get("status")) != "candidate_only":
        issues.append("local execution candidate is not candidate_only")
    if _text(candidate_lineage.get("proof_level")) != "local_runtime_proof":
        issues.append("local execution candidate proof level is not local_runtime_proof")
    if candidate_graph_id != required_graph_id:
        issues.append("local execution candidate graph_id does not match review graph")
    if required_lane_id not in candidate_lane_ids:
        issues.append("local execution candidate lane_id does not match review lane")
    if _text(graph_status_lineage.get("status")) != (
        FeatureGraphExecutionStatus.REVIEWING.value
    ):
        issues.append("local execution candidate graph status is not reviewing")
    for field_name, value in (
        ("artifact_ref", candidate_artifact_ref),
        ("run_id", candidate_run_id),
        ("worker_id", candidate_worker_id),
        ("runner_session_id", candidate_runner_session_id),
        ("runner_session_ref", candidate_runner_session_ref),
    ):
        if value is None:
            issues.append(f"local execution candidate missing {field_name}")

    runner_session_ref: str | None = None
    runner_bundle_refs: list[str] = []
    if runner_session_lineage is None:
        issues.append("runner session lineage is missing")
    else:
        runner_session_ref = _text(runner_session_lineage.get("artifact_ref"))
        runner_bundle_refs = _string_list(
            runner_session_lineage.get("worker_evidence_bundle_refs")
        )
        if _text(runner_session_lineage.get("status")) != "session_completed":
            issues.append("runner session is not completed")
        if _text(runner_session_lineage.get("proof_level")) != "local_runtime_proof":
            issues.append("runner session proof level is not local_runtime_proof")
        if _text(runner_session_lineage.get("session_id")) != candidate_runner_session_id:
            issues.append("runner session_id does not match candidate")
        if _text(runner_session_lineage.get("run_id")) != candidate_run_id:
            issues.append("runner session run_id does not match candidate")
        if _text(runner_session_lineage.get("runner_id")) != candidate_worker_id:
            issues.append("runner session runner_id does not match candidate")
        session_graph_id = _text(runner_session_lineage.get("graph_id"))
        if session_graph_id not in {None, required_graph_id}:
            issues.append("runner session graph_id does not match review graph")
        candidate_refs = _string_list(
            runner_session_lineage.get("candidate_artifact_refs")
        )
        if candidate_artifact_ref is None or candidate_artifact_ref not in candidate_refs:
            issues.append("runner session does not include candidate artifact ref")
        session_lane_ids = set(
            _string_list(runner_session_lineage.get("candidate_lane_ids"))
        )
        if session_lane_ids and required_lane_id not in session_lane_ids:
            issues.append("runner session lane scope does not match review lane")
        if not candidate_bundle_refs:
            issues.append(
                "local execution candidate missing graph-native worker evidence "
                "bundle refs"
            )
        if not runner_bundle_refs:
            issues.append(
                "runner session missing graph-native worker evidence bundle refs"
            )
        if set(candidate_bundle_refs) != set(runner_bundle_refs):
            issues.append(
                "local execution candidate worker evidence bundle refs do not "
                "match runner session"
            )

    status = "validated" if not issues else "manual_gap"
    return {
        "schema_version": VALIDATED_EXECUTION_CANDIDATE_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "local_runtime_proof" if status == "validated" else "manual_gap",
        "source_authority": "local_execution_candidate_lineage+runner_session_lineage",
        "candidate_artifact_ref": candidate_artifact_ref,
        "runner_session_ref": runner_session_ref or candidate_runner_session_ref,
        "graph_id": required_graph_id,
        "lane_id": required_lane_id,
        "runner_session_id": candidate_runner_session_id,
        "run_id": candidate_run_id,
        "worker_id": candidate_worker_id,
        "worker_evidence_bundle_refs": _dedupe(candidate_bundle_refs),
        "runner_session_worker_evidence_bundle_refs": _dedupe(runner_bundle_refs),
        "issues": _dedupe(issues),
        "manual_gaps": (
            []
            if status == "validated"
            else ["validated_execution_candidate_not_proven"]
        ),
        "forbidden_claims": _dedupe(
            [
                *LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS,
                "runner_session_is_review_truth",
                "runner_session_is_server_truth",
                "independent_review_truth",
                "server_side_truth",
            ]
        ),
    }


def build_local_execution_candidate_worker_evidence_boundary(
    *,
    root: str | Path,
    lineage: Mapping[str, Any],
) -> dict[str, Any]:
    """Verify that a candidate consumes graph-native worker evidence.

    This verifies only producer handoff lineage. It does not promote worker
    output, local tests, or the evidence bundle to review truth.
    """

    xmuse_root = Path(root)
    artifact_ref = _text(lineage.get("artifact_ref"))
    graph_status_lineage = _mapping(lineage.get("graph_status_lineage"))
    graph_set_id = _text(graph_status_lineage.get("graph_set_id"))
    feature_graph_id = _text(graph_status_lineage.get("feature_graph_id"))
    lineage_status_id = _text(graph_status_lineage.get("status_id"))
    lineage_status = _text(graph_status_lineage.get("status"))
    worker_session_id = _text(lineage.get("runner_session_id"))
    source_refs = _string_list(lineage.get("source_refs"))
    lane_ids = {
        value
        for value in (
            _text(lineage.get("lane_id")),
            _text(lineage.get("lane_local_id")),
        )
        if value is not None
    }
    issues: list[str] = []
    if _text(lineage.get("status")) != "candidate_only":
        issues.append("local execution candidate is not candidate_only")
    if _text(lineage.get("producer")) != LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER:
        issues.append("local execution candidate is not platform_runner_dispatch")
    if lineage_status != FeatureGraphExecutionStatus.REVIEWING.value:
        issues.append("local execution candidate graph status is not reviewing")
    for field_name, value in (
        ("artifact_ref", artifact_ref),
        ("graph_set_id", graph_set_id),
        ("feature_graph_id", feature_graph_id),
        ("feature_graph_status_id", lineage_status_id),
        ("runner_session_id", worker_session_id),
    ):
        if value is None:
            issues.append(f"local execution candidate missing {field_name}")

    current_status_id: str | None = None
    current_status_value: str | None = None
    current_provider_session_binding_ref: str | None = None
    if graph_set_id is not None and feature_graph_id is not None:
        try:
            current_status = FeatureGraphStatusStore(
                xmuse_root / "feature_graph_statuses.json"
            ).get(
                graph_set_id=graph_set_id,
                feature_graph_id=feature_graph_id,
            )
            current_status_id = current_status.status_id
            current_status_value = current_status.status.value
            current_provider_session_binding_ref = (
                current_status.active_provider_session_binding_ref
            )
            if current_status_id != lineage_status_id:
                issues.append(
                    "local execution candidate graph status id is stale or mismatched"
                )
            if current_status_value != FeatureGraphExecutionStatus.REVIEWING.value:
                issues.append("current feature graph status is not reviewing")
            if current_status.active_worker_session_id != worker_session_id:
                issues.append(
                    "current feature graph worker session does not match candidate"
                )
        except (KeyError, ValueError) as exc:
            issues.append(f"current feature graph status not verified: {exc}")

    matching_bundle_ids: list[str] = []
    matching_bundle_refs: list[str] = []
    if graph_set_id is not None and feature_graph_id is not None:
        try:
            bundles = FeatureGraphArtifactStore(
                xmuse_root / "feature_graph_artifacts.json"
            ).list_evidence_bundles_for_feature_graph(
                graph_set_id=graph_set_id,
                feature_graph_id=feature_graph_id,
            )
        except ValueError as exc:
            bundles = []
            issues.append(f"feature graph artifact store not verified: {exc}")
        for bundle in bundles:
            bundle_ref = f"feature_evidence_bundle:{bundle.bundle_id}:v1"
            completed_lane_ids = set(bundle.lane_graph_summary.completed_lane_ids)
            if bundle.worker_session_id != worker_session_id:
                continue
            if (
                current_provider_session_binding_ref is not None
                and bundle.provider_session_binding_ref
                != current_provider_session_binding_ref
            ):
                continue
            if not lane_ids.intersection(completed_lane_ids):
                continue
            if _text(lineage.get("conversation_id")) != bundle.conversation_id:
                continue
            if bundle_ref not in source_refs:
                continue
            matching_bundle_ids.append(bundle.bundle_id)
            matching_bundle_refs.append(bundle_ref)
    if not matching_bundle_refs:
        issues.append(
            "local execution candidate is not backed by matching graph-native "
            "worker evidence bundle"
        )

    status = "verified" if not issues else "manual_gap"
    return {
        "schema_version": (
            LOCAL_EXECUTION_CANDIDATE_WORKER_EVIDENCE_BOUNDARY_SCHEMA_VERSION
        ),
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "source_authority": (
            "local_execution_candidate_lineage+"
            "feature_graph_status_store+feature_graph_artifact_store"
        ),
        "candidate_artifact_ref": artifact_ref,
        "graph_set_id": graph_set_id,
        "feature_graph_id": feature_graph_id,
        "feature_graph_status_id": lineage_status_id,
        "current_feature_graph_status_id": current_status_id,
        "current_feature_graph_status": current_status_value,
        "worker_session_id": worker_session_id,
        "evidence_bundle_ids": _dedupe(matching_bundle_ids),
        "evidence_bundle_refs": _dedupe(matching_bundle_refs),
        "issues": _dedupe(issues),
        "manual_gaps": (
            []
            if status == "verified"
            else ["worker_evidence_bundle_lineage_not_verified"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
            "server_side_truth",
        ],
    }


def local_execution_candidate_artifact_path(
    root: str | Path,
    artifact_ref: str,
) -> Path | None:
    candidate = artifact_ref.strip()
    for prefix in ("execution_artifact:", "candidate_artifact:", "artifact:"):
        if candidate.startswith(prefix):
            candidate = candidate.removeprefix(prefix).strip()
            break
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


def _unique_lineages(lineages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for lineage in lineages:
        ref = str(lineage.get("artifact_ref") or "")
        if not ref or ref in seen:
            continue
        seen.add(ref)
        result.append(lineage)
    return result


def _build_graph_status_lineage(
    *,
    graph_status_lineage: Mapping[str, Any] | None,
    graph_set_id: str | None,
    feature_graph_id: str | None,
    feature_graph_status_id: str | None,
    feature_graph_status: str | None,
) -> dict[str, Any] | None:
    if graph_status_lineage is not None:
        return _validate_graph_status_lineage(graph_status_lineage)
    values = {
        "graph_set_id": _text(graph_set_id),
        "feature_graph_id": _text(feature_graph_id),
        "status_id": _text(feature_graph_status_id),
        "status": _text(feature_graph_status),
    }
    if not any(values.values()):
        return None
    if any(value is None for value in values.values()):
        raise ValueError("graph status lineage is incomplete")
    return _validate_graph_status_lineage(
        {
            "source_authority": LOCAL_EXECUTION_CANDIDATE_GRAPH_STATUS_AUTHORITY,
            **values,
        }
    )


def _validate_graph_status_lineage(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError("graph status lineage must be an object")
    source_authority = _text(value.get("source_authority"))
    if source_authority != LOCAL_EXECUTION_CANDIDATE_GRAPH_STATUS_AUTHORITY:
        raise ValueError("graph status lineage source authority is unsupported")
    graph_set_id = _required_text(value.get("graph_set_id"), "graph_set_id")
    feature_graph_id = _required_text(
        value.get("feature_graph_id"), "feature_graph_id"
    )
    status_id = _required_text(value.get("status_id"), "status_id")
    status = _required_text(value.get("status"), "status")
    lineage: dict[str, Any] = {
        "source_authority": source_authority,
        "graph_set_id": graph_set_id,
        "feature_graph_id": feature_graph_id,
        "status_id": status_id,
        "status": status,
    }
    for key in (
        "blueprint_proof_level",
        "active_lane_ids",
        "completed_lane_ids",
        "source_event_lineage",
    ):
        if key in value:
            lineage[key] = value[key]
    return lineage


def _raise_if_artifact_graph_status_fields_conflict(
    *,
    artifact: Mapping[str, Any],
    lineage: Mapping[str, Any],
) -> None:
    pairs = (
        ("graph_set_id", "graph_set_id"),
        ("feature_graph_id", "feature_graph_id"),
        ("feature_graph_status_id", "status_id"),
        ("feature_graph_status", "status"),
        ("graph_status_source_authority", "source_authority"),
    )
    for artifact_key, lineage_key in pairs:
        artifact_value = _text(artifact.get(artifact_key))
        lineage_value = _text(lineage.get(lineage_key))
        if artifact_value is not None and artifact_value != lineage_value:
            raise ValueError(
                "local execution candidate graph status fields do not match lineage"
            )


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


def _mapping(value: object) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _feature_evidence_bundle_refs(value: object) -> list[str]:
    return [
        item
        for item in _string_list(value)
        if item.startswith("feature_evidence_bundle:")
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
    "LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS",
    "LOCAL_EXECUTION_CANDIDATE_GRAPH_STATUS_AUTHORITY",
    "LOCAL_EXECUTION_CANDIDATE_MANUAL_CLI_PRODUCER",
    "LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER",
    "LOCAL_EXECUTION_CANDIDATE_SCHEMA_VERSION",
    "LOCAL_EXECUTION_CANDIDATE_WORKER_EVIDENCE_BOUNDARY_SCHEMA_VERSION",
    "VALIDATED_EXECUTION_CANDIDATE_BOUNDARY_SCHEMA_VERSION",
    "build_local_execution_candidate_worker_evidence_boundary",
    "build_local_execution_candidate",
    "build_local_execution_candidate_lineage",
    "build_validated_execution_candidate_boundary",
    "capture_local_execution_candidate",
    "load_local_execution_candidate_lineage",
    "local_execution_candidate_artifact_path",
    "valid_local_execution_candidate_lineages",
]
