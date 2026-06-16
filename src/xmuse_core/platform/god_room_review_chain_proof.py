from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from xmuse_core.platform.god_room_review_handoff import (
    REQUIRED_GOD_ROOM_REVIEW_CLOSURE_FORBIDDEN_CLAIMS,
    build_review_closure_handoff_evaluation,
)
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
    valid_local_execution_candidate_lineages,
)
from xmuse_core.platform.runner_session import (
    RUNNER_SESSION_FORBIDDEN_CLAIMS,
    load_runner_session_lineage,
)
from xmuse_core.structuring.feature_graph_status_store import FeatureGraphStatusStore
from xmuse_core.structuring.feature_plan_store import FeatureGraphSetStore
from xmuse_core.structuring.feature_review_contracts import FeatureGraphExecutionStatus

GOD_ROOM_REVIEW_CHAIN_PROOF_SCHEMA_VERSION = (
    "xmuse.god_room_lane_review_chain_proof.v1"
)
GOD_ROOM_REVIEW_CHAIN_PROOF_AUTHORITY = (
    "god_room_lane_review_closure_artifact+local_execution_candidate_lineage+"
    "shared_god_room_review_closure_handoff_gate"
)
GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS = [
    "worker_output_is_review_truth",
    "end_to_end_execution_review_closure",
    "ready_to_merge",
    "pr_merged",
    "github_review_truth",
    "live_memoryos",
    "server_side_truth",
    "overnight_readiness",
    "worker_self_review_equals_review_truth",
]
GOD_ROOM_REVIEW_CHAIN_PROOF_MANUAL_GAPS = [
    "live_memoryos_trace_not_proven",
    "github_truth_not_checked",
    "server_truth_not_proven",
    "release_evidence_export_not_attempted",
]
LOCAL_EXECUTION_REVIEW_SESSION_SCHEMA_VERSION = (
    "xmuse.local_execution_review_session.v1"
)
LOCAL_EXECUTION_REVIEW_SESSION_SCOPE_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.local_execution_review_session_scope_boundary.v1"
)
LOCAL_EXECUTION_REVIEW_SESSION_ARTIFACT_VALIDATION_SCHEMA_VERSION = (
    "xmuse.local_execution_review_session_artifact_validation.v1"
)
PATCH_FORWARD_ARTIFACT_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.patch_forward_artifact_boundary.v1"
)
REVIEWER_INDEPENDENCE_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.reviewer_independence_boundary.v1"
)
REVIEW_INTAKE_GRAPH_STATUS_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.review_intake_graph_status_boundary.v1"
)
CANDIDATE_GRAPH_STATUS_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.candidate_graph_status_boundary.v1"
)
CANDIDATE_ARTIFACT_REF_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.candidate_artifact_ref_boundary.v1"
)
CANDIDATE_LINEAGE_BOUNDARY_SCHEMA_VERSION = "xmuse.candidate_lineage_boundary.v1"
RUNNER_RECOVERY_LINEAGE_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.runner_recovery_lineage_boundary.v1"
)
RUNNER_SESSION_BOUNDARY_SCHEMA_VERSION = "xmuse.runner_session_boundary.v1"
GRAPH_WIDE_LANE_ACCOUNTING_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.graph_wide_lane_accounting_boundary.v1"
)
WORKER_EVIDENCE_BUNDLE_CITATION_BOUNDARY_SCHEMA_VERSION = (
    "xmuse.worker_evidence_bundle_citation_boundary.v1"
)
REVIEW_CHAIN_PROOF_BOUNDED_SESSION_GATE_SCHEMA_VERSION = (
    "xmuse.review_chain_proof_bounded_session_gate.v1"
)
REVIEW_CHAIN_PROOF_L10_HANDOFF_EVALUATION_SCHEMA_VERSION = (
    "xmuse.review_chain_proof_l10_handoff_evaluation.v1"
)
REQUIRED_REVIEW_CHAIN_SESSION_BOUNDARIES = (
    "session_scope_boundary",
    "runner_session_boundary",
    "graph_wide_lane_accounting_boundary",
    "runner_recovery_lineage_boundary",
    "review_intake_graph_status_boundary",
    "candidate_graph_status_boundary",
    "candidate_artifact_ref_boundary",
    "candidate_lineage_boundary",
    "worker_evidence_bundle_citation_boundary",
    "reviewer_independence",
)


def review_chain_proof_bounded_session_gate(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate that a review-chain proof carries bounded L9 session evidence."""

    issues: list[str] = []
    session = _mapping(payload.get("local_execution_review_session"))
    if not session:
        issues.append("local_execution_review_session is missing")

    session_status = _text(session.get("status"))
    proof_level = _text(session.get("proof_level"))
    session_truth_status = _text(session.get("session_truth_status"))
    execution_truth_status = _text(session.get("execution_truth_status"))
    review_truth_status = _text(session.get("review_truth_status"))
    server_truth_status = _text(session.get("server_truth_status"))
    if session_status != "bounded_session_ready":
        issues.append("local_execution_review_session is not bounded_session_ready")
    if _text(session.get("schema_version")) != LOCAL_EXECUTION_REVIEW_SESSION_SCHEMA_VERSION:
        issues.append("local_execution_review_session schema is not supported")
    if _text(session.get("session_id")) is None:
        issues.append("local_execution_review_session session_id is missing")
    if proof_level != "contract_proof":
        issues.append("local_execution_review_session proof level is not contract_proof")
    if session_truth_status != "bounded_local_execution_review_session":
        issues.append(
            "local_execution_review_session truth status is not "
            "bounded_local_execution_review_session"
        )
    if execution_truth_status != "candidate_reviewed":
        issues.append(
            "local_execution_review_session execution truth status is not "
            "candidate_reviewed"
        )
    if review_truth_status != "independent_review_artifact":
        issues.append(
            "local_execution_review_session review truth status is not "
            "independent_review_artifact"
        )
    if server_truth_status != "not_server_truth":
        issues.append("local_execution_review_session overclaims server truth")

    session_candidate_refs = _ordered_unique(
        _string_list(session.get("candidate_artifact_refs"))
    )
    session_artifact_refs = _ordered_unique(
        _string_list(session.get("session_artifact_refs"))
    )
    session_source_refs = _ordered_unique(_string_list(session.get("session_source_refs")))
    handoff = _mapping(payload.get("release_evidence_handoff"))
    handoff_candidate_refs = _ordered_unique(
        _string_list(handoff.get("review_closure_candidate_artifact_refs"))
    )
    candidate_lineage = _mapping(payload.get("candidate_lineage"))
    lineage_candidate_refs = _ordered_unique(
        _string_list(candidate_lineage.get("candidate_artifact_refs"))
    )
    session_candidate_producers = _ordered_unique(
        _string_list(session.get("candidate_producers"))
    )
    lineage_candidate_producers = _ordered_unique(
        _string_list(candidate_lineage.get("producers"))
    )
    if not session_candidate_refs:
        issues.append("local_execution_review_session has no candidate artifact refs")
    if not session_artifact_refs:
        issues.append("local_execution_review_session has no session artifact refs")
    if not session_source_refs:
        issues.append("local_execution_review_session has no session source refs")
    missing_session_candidate_refs = [
        ref for ref in session_candidate_refs if ref not in session_artifact_refs
    ]
    if missing_session_candidate_refs:
        issues.append(
            "local_execution_review_session session artifact refs missing "
            "candidate artifact refs: "
            + ", ".join(missing_session_candidate_refs)
        )
    if not handoff_candidate_refs:
        issues.append("review chain proof handoff has no candidate artifact refs")
    if handoff_candidate_refs and handoff_candidate_refs != session_candidate_refs:
        issues.append(
            "local_execution_review_session candidate artifact refs do not match "
            "release evidence handoff refs"
        )
    if not lineage_candidate_refs:
        issues.append("review chain proof candidate lineage has no candidate artifact refs")
    if lineage_candidate_refs and lineage_candidate_refs != session_candidate_refs:
        issues.append(
            "local_execution_review_session candidate artifact refs do not match "
            "candidate lineage refs"
        )
    if _non_negative_int(session.get("candidate_count")) != len(session_candidate_refs):
        issues.append(
            "local_execution_review_session candidate_count does not match "
            "candidate artifact refs"
        )
    if session_candidate_producers != [
        LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER
    ]:
        issues.append(
            "local_execution_review_session candidate producers do not prove "
            "platform runner dispatch"
        )
    if lineage_candidate_producers != [
        LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER
    ]:
        issues.append(
            "review chain proof candidate lineage producers do not prove "
            "platform runner dispatch"
        )

    validation = _mapping(session.get("session_artifact_validation"))
    validation_status = _text(validation.get("status"))
    validation_proof_level = _text(validation.get("proof_level"))
    if validation_status != "validated":
        issues.append("local_execution_review_session artifacts are not validated")
    if validation_proof_level != "contract_proof":
        issues.append(
            "local_execution_review_session artifact validation proof level is not "
            "contract_proof"
        )

    boundary_statuses: dict[str, dict[str, str | None]] = {}
    for boundary_name in REQUIRED_REVIEW_CHAIN_SESSION_BOUNDARIES:
        boundary = _mapping(session.get(boundary_name))
        boundary_status = _text(boundary.get("status"))
        boundary_proof_level = _text(boundary.get("proof_level"))
        boundary_statuses[boundary_name] = {
            "status": boundary_status,
            "proof_level": boundary_proof_level,
        }
        if boundary_status != "verified":
            issues.append(f"{boundary_name} is not verified")
        if boundary_proof_level != "contract_proof":
            issues.append(f"{boundary_name} proof level is not contract_proof")
        if boundary_name == "candidate_artifact_ref_boundary":
            closure_refs = _ordered_unique(
                _string_list(boundary.get("closure_cited_candidate_artifact_refs"))
            )
            resolved_refs = _ordered_unique(
                _string_list(boundary.get("resolved_candidate_artifact_refs"))
            )
            if closure_refs != session_candidate_refs:
                issues.append(
                    "candidate_artifact_ref_boundary closure refs do not match "
                    "session candidate refs"
                )
            if resolved_refs != session_candidate_refs:
                issues.append(
                    "candidate_artifact_ref_boundary resolved refs do not match "
                    "session candidate refs"
                )
        if boundary_name == "candidate_lineage_boundary":
            closure_refs = _ordered_unique(
                _string_list(boundary.get("closure_candidate_artifact_refs"))
            )
            resolved_refs = _ordered_unique(
                _string_list(boundary.get("resolved_candidate_artifact_refs"))
            )
            if closure_refs != session_candidate_refs:
                issues.append(
                    "candidate_lineage_boundary closure refs do not match "
                    "session candidate refs"
                )
            if resolved_refs != session_candidate_refs:
                issues.append(
                    "candidate_lineage_boundary resolved refs do not match "
                    "session candidate refs"
                )
        if boundary_name == "graph_wide_lane_accounting_boundary":
            accounting_refs = _ordered_unique(
                _string_list(boundary.get("candidate_artifact_refs"))
            )
            if accounting_refs and accounting_refs != session_candidate_refs:
                issues.append(
                    "graph_wide_lane_accounting_boundary candidate artifact refs "
                    "do not match session candidate refs"
                )
        if boundary_name == "runner_session_boundary":
            runner_session_refs = _ordered_unique(
                _string_list(boundary.get("runner_session_refs"))
            )
            runner_candidate_refs = _ordered_unique(
                _string_list(boundary.get("candidate_artifact_refs"))
            )
            if not runner_session_refs:
                issues.append("runner_session_boundary has no runner session refs")
            if runner_candidate_refs != session_candidate_refs:
                issues.append(
                    "runner_session_boundary candidate artifact refs do not match "
                    "session candidate refs"
                )

    status = "verified" if not issues else "manual_gap"
    return {
        "schema_version": REVIEW_CHAIN_PROOF_BOUNDED_SESSION_GATE_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "summary": (
            "GOD room review chain proof carries bounded local execution/review "
            "session evidence."
            if status == "verified"
            else (
                "GOD room review chain proof bounded session is not verified: "
                + "; ".join(_ordered_unique(issues))
            )
        ),
        "session_status": session_status,
        "session_truth_status": session_truth_status,
        "execution_truth_status": execution_truth_status,
        "review_truth_status": review_truth_status,
        "server_truth_status": server_truth_status,
        "session_artifact_validation_status": validation_status,
        "candidate_artifact_refs": session_candidate_refs,
        "candidate_producers": session_candidate_producers,
        "boundary_statuses": boundary_statuses,
        "issues": _ordered_unique(issues),
        "manual_gaps": (
            []
            if status == "verified"
            else ["bounded_local_execution_review_session_not_verified"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
            "server_side_truth",
        ],
    }


def review_chain_proof_worker_evidence_bundle_refs(
    payload: Mapping[str, Any],
) -> list[str]:
    """Return worker bundle refs only from a verified review-chain boundary."""

    session = _mapping(payload.get("local_execution_review_session"))
    boundary = _mapping(session.get("worker_evidence_bundle_citation_boundary"))
    if (
        _text(boundary.get("status")) != "verified"
        or _text(boundary.get("proof_level")) != "contract_proof"
    ):
        return []
    refs = _string_list(boundary.get("all_worker_evidence_bundle_refs"))
    if not refs:
        refs = _ordered_unique(
            [
                *_string_list(
                    boundary.get("source_review_verdict_worker_evidence_bundle_refs")
                ),
                *_string_list(boundary.get("patch_forward_worker_evidence_bundle_refs")),
                *_string_list(
                    boundary.get("terminal_review_verdict_worker_evidence_bundle_refs")
                ),
            ]
        )
    return _ordered_unique(refs)


def build_review_chain_proof_l10_handoff_evaluation(
    *,
    root: str | Path,
    artifact_path: str | Path,
    review_chain_proof: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the single L10 handoff surface for review-chain proof consumers."""

    xmuse_root = Path(root)
    issues: list[str] = []
    schema_version = _text(review_chain_proof.get("schema_version"))
    status = _text(review_chain_proof.get("status")) or "manual_gap"
    proof_level = _text(review_chain_proof.get("proof_level")) or "manual_gap"
    server_truth_status = _text(review_chain_proof.get("server_truth_status"))
    forbidden_claims = _string_list(review_chain_proof.get("forbidden_claims"))
    forbidden_claim_set = set(forbidden_claims)
    missing_forbidden = sorted(
        set(GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS) - forbidden_claim_set
    )
    if schema_version != GOD_ROOM_REVIEW_CHAIN_PROOF_SCHEMA_VERSION:
        issues.append("GOD room review chain proof artifact has unexpected schema")
    if status != "chain_ready":
        issues.append("GOD room review chain proof is not chain_ready")
    if proof_level != "contract_proof":
        issues.append("GOD room review chain proof proof level is not contract_proof")
    if server_truth_status != "not_server_truth":
        issues.append("GOD room review chain proof overclaims server truth")
    if missing_forbidden:
        issues.append(
            "GOD room review chain proof missing forbidden claims: "
            + ", ".join(missing_forbidden)
        )

    release_handoff = _mapping(review_chain_proof.get("release_evidence_handoff"))
    embedded_handoff_ready = (
        release_handoff.get("review_closure_artifact_gate_ready") is True
    )
    if not release_handoff:
        issues.append("GOD room review chain proof missing release handoff")
    elif not embedded_handoff_ready:
        issues.append("GOD room review chain proof release handoff is not gate-ready")
    embedded_candidate_refs = _string_list(
        release_handoff.get("review_closure_candidate_artifact_refs")
    )
    if not embedded_candidate_refs:
        issues.append("GOD room review chain proof has no candidate artifact refs")

    bounded_session_gate = review_chain_proof_bounded_session_gate(review_chain_proof)
    if bounded_session_gate["status"] != "verified":
        issues.append(str(bounded_session_gate["summary"]))

    current_handoff_evaluation = _review_chain_current_handoff_evaluation(
        artifact_path=artifact_path,
        payload=review_chain_proof,
    )
    current_ready = current_handoff_evaluation.get("status") == "ready"
    current_summary = _text(current_handoff_evaluation.get("handoff_summary"))
    current_candidate_refs = _string_list(
        current_handoff_evaluation.get("candidate_artifact_refs")
    )
    if not current_ready:
        issues.append(
            "GOD room review chain proof current review-closure handoff is not "
            f"gate-ready: {current_summary or 'unknown'}"
        )
    elif current_candidate_refs != embedded_candidate_refs:
        issues.append(
            "GOD room review chain proof current review-closure handoff "
            "candidate refs do not match embedded handoff refs"
        )

    evaluation_status = "ready" if not issues else (
        "blocked" if server_truth_status not in {None, "not_server_truth"} else "manual_gap"
    )
    source_refs = (
        _review_chain_proof_source_refs(
            xmuse_root,
            review_chain_proof,
            str(artifact_path),
            current_handoff=current_handoff_evaluation,
        )
        if evaluation_status == "ready"
        else []
    )
    worker_evidence_bundle_refs = (
        review_chain_proof_worker_evidence_bundle_refs(review_chain_proof)
        if evaluation_status == "ready"
        else []
    )
    return {
        "schema_version": REVIEW_CHAIN_PROOF_L10_HANDOFF_EVALUATION_SCHEMA_VERSION,
        "status": evaluation_status,
        "proof_level": "contract_proof" if evaluation_status == "ready" else "manual_gap",
        "server_truth_status": server_truth_status or "not_server_truth",
        "review_chain_proof_status": status,
        "review_chain_proof_level": proof_level,
        "handoff_summary": (
            "GOD room review chain proof can seed MemoryOS source refs."
            if evaluation_status == "ready"
            else _review_chain_l10_handoff_summary(issues)
        ),
        "embedded_handoff_gate_ready": embedded_handoff_ready,
        "current_handoff_gate_ready": current_ready,
        "current_handoff_summary": current_summary,
        "current_handoff_evaluation": current_handoff_evaluation,
        "candidate_artifact_refs": embedded_candidate_refs
        if evaluation_status == "ready"
        else [],
        "candidate_artifact_ref_count": (
            len(embedded_candidate_refs) if evaluation_status == "ready" else 0
        ),
        "current_handoff_candidate_artifact_refs": current_candidate_refs,
        "current_handoff_candidate_artifact_ref_count": len(current_candidate_refs),
        "bounded_session_gate": bounded_session_gate,
        "bounded_session_gate_status": _text(bounded_session_gate.get("status")),
        "bounded_session_gate_summary": _text(bounded_session_gate.get("summary")),
        "worker_evidence_bundle_refs": worker_evidence_bundle_refs,
        "worker_evidence_bundle_ref_count": len(worker_evidence_bundle_refs),
        "source_refs": source_refs,
        "source_ref_count": len(source_refs),
        "issues": _ordered_unique(issues),
        "manual_gaps": (
            []
            if evaluation_status == "ready"
            else ["review_chain_proof_l10_handoff_not_ready"]
        ),
        "forbidden_claims": _ordered_unique(
            [
                *GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS,
                *forbidden_claims,
                "server_side_truth",
            ]
        ),
    }


def _review_chain_l10_handoff_summary(issues: list[str]) -> str:
    unique = _ordered_unique(issues)
    if not unique:
        return "GOD room review chain proof L10 handoff is not ready."
    primary = unique[0]
    period_primary = {
        "GOD room review chain proof artifact has unexpected schema",
        "GOD room review chain proof is not chain_ready",
        "GOD room review chain proof proof level is not contract_proof",
        "GOD room review chain proof overclaims server truth",
        "GOD room review chain proof missing release handoff",
        "GOD room review chain proof release handoff is not gate-ready",
        "GOD room review chain proof has no candidate artifact refs",
    }
    if primary in period_primary:
        return f"{primary}."
    return "; ".join(unique)


def capture_god_room_review_chain_proof(
    *,
    root: str | Path,
    review_closure_artifact: str | Path,
    output_path: str | Path,
) -> dict[str, Any]:
    proof = build_god_room_review_chain_proof(
        root=root,
        review_closure_artifact=review_closure_artifact,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return proof


def build_god_room_review_chain_proof(
    *,
    root: str | Path,
    review_closure_artifact: str | Path,
) -> dict[str, Any]:
    xmuse_root = Path(root)
    closure_path = _artifact_path(xmuse_root, review_closure_artifact)
    base = _base_artifact(
        root=xmuse_root,
        review_closure_artifact=review_closure_artifact,
        closure_path=closure_path,
    )
    closure, load_error = _load_json(closure_path)
    if closure is None:
        return _manual_gap_artifact(
            base,
            summary=load_error or "GOD room review closure artifact is missing.",
            manual_gaps=["review_closure_artifact_not_readable"],
        )

    issues = _review_closure_issues(closure)
    conversation_id = _text(closure.get("conversation_id"))
    graph_id = _text(closure.get("graph_id"))
    failed_lane_id = _text(closure.get("failed_lane_id"))
    terminal_lane_id = _text(closure.get("terminal_lane_id"))
    candidate_lineages: list[dict[str, Any]] = []
    try:
        candidate_lineages = valid_local_execution_candidate_lineages(
            root=xmuse_root,
            refs=_string_list(closure.get("cited_candidate_refs")),
            lane_id=terminal_lane_id,
            graph_id=graph_id,
            conversation_id=conversation_id,
            required_producer=LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
        )
    except ValueError as exc:
        issues.append(str(exc))
    session_artifact_validation = _validate_session_artifacts(
        root=xmuse_root,
        closure=closure,
        conversation_id=conversation_id,
        graph_id=graph_id,
        failed_lane_id=failed_lane_id,
        terminal_lane_id=terminal_lane_id,
        candidate_lineages=candidate_lineages,
    )
    session_artifact_issues = _string_list(session_artifact_validation.get("issues"))
    issues.extend(session_artifact_issues)
    if not candidate_lineages:
        issues.append("review closure has no valid local execution candidate lineage")
    reviewer_independence = _reviewer_independence_boundary(
        candidate_lineages=candidate_lineages,
        session_artifact_validation=session_artifact_validation,
    )
    issues.extend(_string_list(reviewer_independence.get("issues")))

    runner_recovery_lineage = _runner_recovery_lineage(
        closure.get("runner_recovery_proof_lineage")
    )
    runner_recovery_lineage_boundary = _runner_recovery_lineage_boundary(
        runner_recovery_lineage,
        root=xmuse_root,
        graph_id=graph_id,
        failed_lane_id=failed_lane_id,
    )
    issues.extend(_string_list(runner_recovery_lineage_boundary.get("issues")))
    runner_session_boundary = _runner_session_boundary(
        root=xmuse_root,
        graph_id=graph_id,
        candidate_lineages=candidate_lineages,
    )
    issues.extend(_string_list(runner_session_boundary.get("issues")))
    graph_wide_lane_accounting_boundary = _graph_wide_lane_accounting_boundary(
        root=xmuse_root,
        closure=closure,
        candidate_lineages=candidate_lineages,
    )
    issues.extend(_string_list(graph_wide_lane_accounting_boundary.get("issues")))
    session_scope_boundary = _local_execution_review_session_scope_boundary(
        closure=closure,
        candidate_lineages=candidate_lineages,
        runner_recovery_lineage=runner_recovery_lineage,
        session_artifact_validation=session_artifact_validation,
    )
    issues.extend(_string_list(session_scope_boundary.get("issues")))
    runner_recovery_status = runner_recovery_lineage.get("status")
    runner_recovery_proof_level = runner_recovery_lineage.get("proof_level")
    runner_recovery_manual_gaps = _string_list(runner_recovery_lineage.get("manual_gaps"))

    release_handoff_evaluation = build_review_closure_handoff_evaluation(
        root=xmuse_root,
        review_closure=closure,
    )
    review_gate_ready = release_handoff_evaluation.get("status") == "ready"
    if not review_gate_ready:
        summary = _text(release_handoff_evaluation.get("handoff_summary"))
        issues.append(summary or "release evidence candidate gate rejected review closure")

    status = "chain_ready" if not issues else "manual_gap"
    proof_level = "contract_proof" if status == "chain_ready" else "manual_gap"
    patch_forward_artifact_boundary = _resolve_patch_forward_artifact_boundary(
        closure=closure,
        candidate_lineages=candidate_lineages,
        session_artifact_validation=session_artifact_validation,
    )
    manual_gaps = _ordered_unique(
        [
            *GOD_ROOM_REVIEW_CHAIN_PROOF_MANUAL_GAPS,
            *_string_list(closure.get("manual_gaps")),
            *_string_list(
                patch_forward_artifact_boundary.get("retained_manual_gaps")
            ),
            *_string_list(reviewer_independence.get("manual_gaps")),
            *_string_list(runner_session_boundary.get("manual_gaps")),
            *_string_list(graph_wide_lane_accounting_boundary.get("manual_gaps")),
            *[
                gap
                for lineage in candidate_lineages
                for gap in _string_list(lineage.get("manual_gaps"))
            ],
            *runner_recovery_manual_gaps,
            *(
                ["local_execution_review_session_artifact_validation_failed"]
                if session_artifact_issues
                else []
            ),
            *(
                []
                if review_gate_ready
                else ["release_evidence_candidate_gate_not_ready"]
            ),
        ]
    )
    forbidden_claims = _ordered_unique(
        [
            *GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS,
            *_string_list(closure.get("forbidden_claims")),
            *_string_list(
                patch_forward_artifact_boundary.get("source_forbidden_claims")
            ),
            *_string_list(reviewer_independence.get("forbidden_claims")),
            *_string_list(runner_session_boundary.get("forbidden_claims")),
            *[
                claim
                for lineage in candidate_lineages
                for claim in _string_list(lineage.get("forbidden_claims"))
            ],
            *_string_list(runner_recovery_lineage.get("forbidden_claims")),
        ]
    )
    return {
        **base,
        "status": status,
        "proof_level": proof_level,
        "summary": (
            "GOD room review chain reached the shared review-closure handoff gate."
            if status == "chain_ready"
            else "GOD room review chain is not gate-ready."
        ),
        "conversation_id": conversation_id,
        "graph_id": graph_id,
        "failed_lane_id": failed_lane_id,
        "terminal_lane_id": terminal_lane_id,
        "review_closure": {
            "schema_version": _text(closure.get("schema_version")),
            "source_authority": _text(closure.get("source_authority")),
            "proof_level": _text(closure.get("proof_level")),
            "review_truth_status": _text(closure.get("review_truth_status")),
            "execution_truth_status": _text(closure.get("execution_truth_status")),
            "server_truth_status": _text(closure.get("server_truth_status")),
            "release_evidence_handoff_status": _text(
                closure.get("release_evidence_handoff_status")
            ),
            "review_plane_sync_status": _text(closure.get("review_plane_sync_status")),
            "graph_status_merge_status": _text(closure.get("graph_status_merge_status")),
            "graph_status_source_authority": _text(
                closure.get("graph_status_source_authority")
            ),
            "source_event_lineage_count": len(
                _mapping_list(closure.get("source_event_lineage"))
            ),
            "terminal_feature_graph_status": {
                "status": _text(
                    _mapping(closure.get("terminal_feature_graph_status")).get("status")
                ),
                "source_event_lineage_count": len(
                    _mapping_list(
                        _mapping(closure.get("terminal_feature_graph_status")).get(
                            "source_event_lineage"
                        )
                    )
                ),
            },
            "review_plane_verdict_ref": _text(closure.get("review_plane_verdict_ref")),
            "patch_forward_artifact": _text(closure.get("patch_forward_artifact")),
            "patch_lane_review_intake_artifact": _text(
                closure.get("patch_lane_review_intake_artifact")
            ),
            "patch_lane_review_verdict_artifact": _text(
                closure.get("patch_lane_review_verdict_artifact")
            ),
        },
        "candidate_lineage": {
            "candidate_artifact_refs": [
                _text(lineage.get("artifact_ref")) for lineage in candidate_lineages
            ],
            "candidate_count": len(candidate_lineages),
            "producers": _ordered_unique(
                _text(lineage.get("producer")) for lineage in candidate_lineages
            ),
            "candidate_truth_statuses": _ordered_unique(
                _text(lineage.get("candidate_truth_status"))
                for lineage in candidate_lineages
            ),
            "proof_levels": _ordered_unique(
                _text(lineage.get("proof_level")) for lineage in candidate_lineages
            ),
            "graph_status_source_authorities": _ordered_unique(
                _text(_mapping(lineage.get("graph_status_lineage")).get("source_authority"))
                for lineage in candidate_lineages
            ),
            "runner_session_refs": _ordered_unique(
                _text(lineage.get("runner_session_ref")) for lineage in candidate_lineages
            ),
            "runner_session_ids": _ordered_unique(
                _text(lineage.get("runner_session_id")) for lineage in candidate_lineages
            ),
        },
        "local_execution_review_session": _local_execution_review_session(
            status=status,
            proof_level=proof_level,
            closure=closure,
            candidate_lineages=candidate_lineages,
            runner_recovery_lineage=runner_recovery_lineage,
            session_artifact_validation=session_artifact_validation,
            session_scope_boundary=session_scope_boundary,
            patch_forward_artifact_boundary=patch_forward_artifact_boundary,
            worker_evidence_bundle_citation_boundary=_mapping(
                session_artifact_validation.get(
                    "worker_evidence_bundle_citation_boundary"
                )
            ),
            reviewer_independence=reviewer_independence,
            runner_session_boundary=runner_session_boundary,
            runner_recovery_lineage_boundary=runner_recovery_lineage_boundary,
            graph_wide_lane_accounting_boundary=graph_wide_lane_accounting_boundary,
            manual_gaps=manual_gaps,
            forbidden_claims=forbidden_claims,
        ),
        "runner_recovery_proof_lineage": {
            "status": runner_recovery_status or "not_provided",
            "proof_level": runner_recovery_proof_level or "manual_gap",
            "artifact_ref": _text(runner_recovery_lineage.get("artifact_ref")),
            "source_ref_count": len(_string_list(runner_recovery_lineage.get("source_refs"))),
            "manual_gaps": runner_recovery_manual_gaps,
        },
        "release_evidence_handoff": {
            "candidate_report_schema_version": None,
            "handoff_validator_schema_version": _text(
                release_handoff_evaluation.get("schema_version")
            ),
            "memoryos_export_ready": False,
            "review_closure_artifact_gate_ready": review_gate_ready,
            "review_closure_artifact_summary": _text(
                release_handoff_evaluation.get("handoff_summary")
            ),
            "review_closure_source_ref_count": _non_negative_int(
                release_handoff_evaluation.get("source_ref_count")
            ),
            "review_closure_candidate_artifact_refs": _string_list(
                release_handoff_evaluation.get("candidate_artifact_refs")
            ),
            "review_closure_candidate_artifact_ref_count": _non_negative_int(
                release_handoff_evaluation.get("candidate_artifact_ref_count")
            ),
            "blockers": (
                []
                if review_gate_ready
                else ["god_room_review_closure_artifact_not_ready"]
            ),
        },
        "issues": _ordered_unique(issues),
        "manual_gaps": manual_gaps,
        "forbidden_claims": forbidden_claims,
    }


def _base_artifact(
    *,
    root: Path,
    review_closure_artifact: str | Path,
    closure_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": GOD_ROOM_REVIEW_CHAIN_PROOF_SCHEMA_VERSION,
        "source_authority": GOD_ROOM_REVIEW_CHAIN_PROOF_AUTHORITY,
        "generated_at": _utc_now(),
        "xmuse_root": str(root.resolve(strict=False)),
        "review_closure_artifact": _artifact_ref(root, review_closure_artifact, closure_path),
        "server_truth_status": "not_server_truth",
    }


def _manual_gap_artifact(
    base: Mapping[str, Any],
    *,
    summary: str,
    manual_gaps: list[str],
) -> dict[str, Any]:
    return {
        **dict(base),
        "status": "manual_gap",
        "proof_level": "manual_gap",
        "summary": summary,
        "conversation_id": None,
        "graph_id": None,
        "failed_lane_id": None,
        "terminal_lane_id": None,
        "review_closure": None,
        "candidate_lineage": {
            "candidate_artifact_refs": [],
            "candidate_count": 0,
            "producers": [],
            "candidate_truth_statuses": [],
            "proof_levels": [],
            "graph_status_source_authorities": [],
        },
        "local_execution_review_session": {
            "schema_version": LOCAL_EXECUTION_REVIEW_SESSION_SCHEMA_VERSION,
            "session_id": None,
            "source_authority": GOD_ROOM_REVIEW_CHAIN_PROOF_AUTHORITY,
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "session_truth_status": "not_ready",
            "execution_truth_status": None,
            "review_truth_status": None,
            "server_truth_status": "not_server_truth",
            "graph_id": None,
            "failed_lane_id": None,
            "terminal_lane_id": None,
            "session_artifact_refs": [],
            "session_source_refs": [],
            "candidate_count": 0,
            "candidate_artifact_refs": [],
            "candidate_ids": [],
            "candidate_run_ids": [],
            "candidate_worker_ids": [],
            "candidate_producers": [],
            "candidate_source_refs": [],
            "candidate_output_refs": [],
            "candidate_changed_file_refs": [],
            "candidate_verification_refs": [],
            "review_plane_verdict_ref": None,
            "patch_forward_artifact": None,
            "patch_lane_review_intake_artifact": None,
            "patch_lane_review_verdict_artifact": None,
            "session_artifact_validation": {
                "schema_version": (
                    LOCAL_EXECUTION_REVIEW_SESSION_ARTIFACT_VALIDATION_SCHEMA_VERSION
                ),
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "artifact_count": 0,
                "artifact_refs": [],
                "validated_artifacts": {},
                "issues": [summary],
                "manual_gaps": [
                    "local_execution_review_session_artifact_validation_failed"
                ],
            },
            "session_scope_boundary": {
                "schema_version": (
                    LOCAL_EXECUTION_REVIEW_SESSION_SCOPE_BOUNDARY_SCHEMA_VERSION
                ),
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "session_id": None,
                "session_artifact_refs": [],
                "session_source_refs": [],
                "issues": [summary],
                "manual_gaps": ["local_execution_review_session_scope_not_verified"],
                "forbidden_claims": [
                    "worker_output_is_review_truth",
                    "end_to_end_execution_review_closure",
                    "server_side_truth",
                ],
            },
            "graph_wide_lane_accounting_boundary": {
                "schema_version": GRAPH_WIDE_LANE_ACCOUNTING_BOUNDARY_SCHEMA_VERSION,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "server_truth_status": "not_server_truth",
                "conversation_id": None,
                "graph_id": None,
                "graph_set_id": None,
                "graph_set_loaded": False,
                "status_store_loaded": False,
                "graph_count": 0,
                "lane_count": 0,
                "candidate_artifact_refs": [],
                "candidate_covered_lane_ids": [],
                "issues": [summary],
                "manual_gaps": ["graph_wide_lane_accounting_not_verified"],
                "forbidden_claims": [
                    "worker_output_is_review_truth",
                    "end_to_end_execution_review_closure",
                    "graph_wide_execution_review_closure",
                    "server_side_truth",
                ],
            },
            "review_intake_graph_status_boundary": {
                "schema_version": REVIEW_INTAKE_GRAPH_STATUS_BOUNDARY_SCHEMA_VERSION,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "issues": [summary],
                "manual_gaps": ["review_intake_graph_status_boundary_not_proven"],
                "forbidden_claims": [
                    "worker_output_is_review_truth",
                    "end_to_end_execution_review_closure",
                ],
            },
            "candidate_graph_status_boundary": {
                "schema_version": CANDIDATE_GRAPH_STATUS_BOUNDARY_SCHEMA_VERSION,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "candidate_artifact_refs": [],
                "candidate_count": 0,
                "issues": [summary],
                "manual_gaps": ["candidate_graph_status_boundary_not_proven"],
                "forbidden_claims": [
                    "worker_output_is_review_truth",
                    "end_to_end_execution_review_closure",
                ],
            },
            "candidate_artifact_ref_boundary": {
                "schema_version": CANDIDATE_ARTIFACT_REF_BOUNDARY_SCHEMA_VERSION,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "closure_cited_candidate_artifact_refs": [],
                "resolved_candidate_artifact_refs": [],
                "issues": [summary],
                "manual_gaps": ["candidate_artifact_refs_not_resolved"],
                "forbidden_claims": [
                    "worker_output_is_review_truth",
                    "end_to_end_execution_review_closure",
                ],
            },
            "candidate_lineage_boundary": {
                "schema_version": CANDIDATE_LINEAGE_BOUNDARY_SCHEMA_VERSION,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "closure_candidate_artifact_refs": [],
                "resolved_candidate_artifact_refs": [],
                "issues": [summary],
                "manual_gaps": ["candidate_artifact_lineage_not_resolved"],
                "forbidden_claims": [
                    "worker_output_is_review_truth",
                    "end_to_end_execution_review_closure",
                ],
            },
            "runner_recovery_lineage_boundary": {
                "schema_version": RUNNER_RECOVERY_LINEAGE_BOUNDARY_SCHEMA_VERSION,
                "status": "manual_gap",
                "proof_level": "manual_gap",
                "runner_recovery_status": "not_provided",
                "runner_recovery_proof_level": "manual_gap",
                "source_ref_count": 0,
                "issues": [summary],
                "manual_gaps": ["runner_recovery_lineage_not_verified"],
                "forbidden_claims": [
                    "overnight_safe_recovery",
                    "end_to_end_execution_review_closure",
                    "server_side_truth",
                ],
            },
            "runner_recovery_proof_status": "not_provided",
            "runner_recovery_proof_level": "manual_gap",
            "manual_gaps": _ordered_unique(
                [*manual_gaps, *GOD_ROOM_REVIEW_CHAIN_PROOF_MANUAL_GAPS]
            ),
            "forbidden_claims": list(GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS),
        },
        "runner_recovery_proof_lineage": {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "artifact_ref": None,
            "source_ref_count": 0,
            "manual_gaps": [],
        },
        "release_evidence_handoff": {
            "candidate_report_schema_version": None,
            "handoff_validator_schema_version": None,
            "memoryos_export_ready": False,
            "review_closure_artifact_gate_ready": False,
            "review_closure_artifact_summary": None,
            "review_closure_source_ref_count": 0,
            "review_closure_candidate_artifact_refs": [],
            "review_closure_candidate_artifact_ref_count": 0,
            "blockers": [],
        },
        "issues": [summary],
        "manual_gaps": _ordered_unique(
            [*manual_gaps, *GOD_ROOM_REVIEW_CHAIN_PROOF_MANUAL_GAPS]
        ),
        "forbidden_claims": list(GOD_ROOM_REVIEW_CHAIN_PROOF_FORBIDDEN_CLAIMS),
    }


def _local_execution_review_session_scope_boundary(
    *,
    closure: Mapping[str, Any],
    candidate_lineages: list[dict[str, Any]],
    runner_recovery_lineage: Mapping[str, Any],
    session_artifact_validation: Mapping[str, Any],
) -> dict[str, Any]:
    graph_id = _text(closure.get("graph_id"))
    failed_lane_id = _text(closure.get("failed_lane_id"))
    terminal_lane_id = _text(closure.get("terminal_lane_id"))
    session_id = (
        "local-execution-review-session:"
        f"{graph_id}:{failed_lane_id}:{terminal_lane_id}"
        if graph_id and failed_lane_id and terminal_lane_id
        else None
    )
    candidate_artifact_refs = _ordered_unique(
        _text(lineage.get("artifact_ref")) for lineage in candidate_lineages
    )
    session_artifact_refs = _ordered_unique(
        [
            _text(closure.get("patch_forward_artifact")),
            _text(closure.get("patch_lane_review_intake_artifact")),
            _text(closure.get("patch_lane_review_verdict_artifact")),
            *_string_list(session_artifact_validation.get("artifact_refs")),
            *candidate_artifact_refs,
            _text(runner_recovery_lineage.get("artifact_ref")),
        ]
    )
    session_source_refs = _ordered_unique(
        [
            f"god-room-review-chain-session:{graph_id}:{failed_lane_id}:{terminal_lane_id}"
            if graph_id and failed_lane_id and terminal_lane_id
            else None,
            f"graph:{graph_id}" if graph_id else None,
            f"lane:{failed_lane_id}" if failed_lane_id else None,
            f"lane:{terminal_lane_id}" if terminal_lane_id else None,
            *session_artifact_refs,
            *[
                ref
                for lineage in candidate_lineages
                for ref in _string_list(lineage.get("source_refs"))
            ],
            *_string_list(runner_recovery_lineage.get("source_refs")),
        ]
    )
    issues: list[str] = []
    for key, value in (
        ("graph_id", graph_id),
        ("failed_lane_id", failed_lane_id),
        ("terminal_lane_id", terminal_lane_id),
    ):
        if value is None:
            issues.append(f"local execution review session missing {key}")
    if _text(closure.get("execution_truth_status")) != "candidate_reviewed":
        issues.append(
            "local execution review session execution truth status is not "
            "candidate_reviewed"
        )
    if _text(closure.get("review_truth_status")) != "independent_review_artifact":
        issues.append(
            "local execution review session review truth status is not "
            "independent_review_artifact"
        )
    if _text(closure.get("server_truth_status")) != "not_server_truth":
        issues.append("local execution review session overclaims server truth")
    if not candidate_artifact_refs:
        issues.append("local execution review session has no candidate artifact refs")
    if _text(runner_recovery_lineage.get("artifact_ref")) is None:
        issues.append("local execution review session has no runner recovery artifact ref")
    if _text(session_artifact_validation.get("status")) != "validated":
        issues.append("local execution review session artifacts are not validated")
    missing_core_artifact_refs = [
        ref
        for ref in (
            _text(closure.get("patch_forward_artifact")),
            _text(closure.get("patch_lane_review_intake_artifact")),
            _text(closure.get("patch_lane_review_verdict_artifact")),
        )
        if ref is None
    ]
    if missing_core_artifact_refs:
        issues.append("local execution review session core artifact refs are missing")
    if not session_artifact_refs:
        issues.append("local execution review session has no session artifact refs")
    if not session_source_refs:
        issues.append("local execution review session has no session source refs")
    status = "verified" if not issues else "manual_gap"
    return {
        "schema_version": LOCAL_EXECUTION_REVIEW_SESSION_SCOPE_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "session_id": session_id,
        "graph_id": graph_id,
        "failed_lane_id": failed_lane_id,
        "terminal_lane_id": terminal_lane_id,
        "candidate_artifact_refs": candidate_artifact_refs,
        "runner_recovery_artifact_ref": _text(
            runner_recovery_lineage.get("artifact_ref")
        ),
        "session_artifact_refs": session_artifact_refs,
        "session_source_refs": session_source_refs,
        "issues": issues,
        "manual_gaps": (
            []
            if status == "verified"
            else ["local_execution_review_session_scope_not_verified"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
            "server_side_truth",
        ],
    }


def _local_execution_review_session(
    *,
    status: str,
    proof_level: str,
    closure: Mapping[str, Any],
    candidate_lineages: list[dict[str, Any]],
    runner_recovery_lineage: Mapping[str, Any],
    session_artifact_validation: Mapping[str, Any],
    session_scope_boundary: Mapping[str, Any],
    patch_forward_artifact_boundary: Mapping[str, Any],
    worker_evidence_bundle_citation_boundary: Mapping[str, Any],
    reviewer_independence: Mapping[str, Any],
    runner_session_boundary: Mapping[str, Any],
    runner_recovery_lineage_boundary: Mapping[str, Any],
    graph_wide_lane_accounting_boundary: Mapping[str, Any],
    manual_gaps: list[str],
    forbidden_claims: list[str],
) -> dict[str, Any]:
    ready = status == "chain_ready"
    session_id = _text(session_scope_boundary.get("session_id"))
    session_artifact_refs = _string_list(session_scope_boundary.get("session_artifact_refs"))
    session_source_refs = _string_list(session_scope_boundary.get("session_source_refs"))
    return {
        "schema_version": LOCAL_EXECUTION_REVIEW_SESSION_SCHEMA_VERSION,
        "session_id": session_id,
        "source_authority": GOD_ROOM_REVIEW_CHAIN_PROOF_AUTHORITY,
        "status": "bounded_session_ready" if ready else "manual_gap",
        "proof_level": proof_level if ready else "manual_gap",
        "session_truth_status": (
            "bounded_local_execution_review_session" if ready else "not_ready"
        ),
        "execution_truth_status": _text(closure.get("execution_truth_status")),
        "review_truth_status": _text(closure.get("review_truth_status")),
        "server_truth_status": "not_server_truth",
        "graph_id": _text(closure.get("graph_id")),
        "failed_lane_id": _text(closure.get("failed_lane_id")),
        "terminal_lane_id": _text(closure.get("terminal_lane_id")),
        "session_artifact_refs": session_artifact_refs,
        "session_source_refs": session_source_refs,
        "candidate_count": len(candidate_lineages),
        "candidate_artifact_refs": _ordered_unique(
            _text(lineage.get("artifact_ref")) for lineage in candidate_lineages
        ),
        "candidate_ids": _ordered_unique(
            _text(lineage.get("candidate_id")) for lineage in candidate_lineages
        ),
        "candidate_run_ids": _ordered_unique(
            _text(lineage.get("run_id")) for lineage in candidate_lineages
        ),
        "candidate_worker_ids": _ordered_unique(
            _text(lineage.get("worker_id")) for lineage in candidate_lineages
        ),
        "candidate_runner_session_ids": _ordered_unique(
            _text(lineage.get("runner_session_id")) for lineage in candidate_lineages
        ),
        "candidate_runner_session_refs": _ordered_unique(
            _text(lineage.get("runner_session_ref")) for lineage in candidate_lineages
        ),
        "candidate_producers": _ordered_unique(
            _text(lineage.get("producer")) for lineage in candidate_lineages
        ),
        "candidate_source_refs": _ordered_unique(
            ref
            for lineage in candidate_lineages
            for ref in _string_list(lineage.get("source_refs"))
        ),
        "candidate_output_refs": _ordered_unique(
            ref
            for lineage in candidate_lineages
            for ref in _string_list(lineage.get("output_refs"))
        ),
        "candidate_changed_file_refs": _ordered_unique(
            ref
            for lineage in candidate_lineages
            for ref in _string_list(lineage.get("changed_file_refs"))
        ),
        "candidate_verification_refs": _ordered_unique(
            ref
            for lineage in candidate_lineages
            for ref in _string_list(lineage.get("verification_refs"))
        ),
        "review_plane_verdict_ref": _text(closure.get("review_plane_verdict_ref")),
        "patch_forward_artifact": _text(closure.get("patch_forward_artifact")),
        "patch_lane_review_intake_artifact": _text(
            closure.get("patch_lane_review_intake_artifact")
        ),
        "patch_lane_review_verdict_artifact": _text(
            closure.get("patch_lane_review_verdict_artifact")
        ),
        "session_artifact_validation": session_artifact_validation,
        "session_scope_boundary": dict(session_scope_boundary),
        "review_intake_graph_status_boundary": dict(
            _mapping(
                session_artifact_validation.get(
                    "review_intake_graph_status_boundary"
                )
            )
        ),
        "graph_wide_lane_accounting_boundary": dict(
            graph_wide_lane_accounting_boundary
        ),
        "candidate_graph_status_boundary": dict(
            _mapping(
                session_artifact_validation.get(
                    "candidate_graph_status_boundary"
                )
            )
        ),
        "candidate_artifact_ref_boundary": dict(
            _mapping(
                session_artifact_validation.get(
                    "candidate_artifact_ref_boundary"
                )
            )
        ),
        "candidate_lineage_boundary": dict(
            _mapping(
                session_artifact_validation.get(
                    "candidate_lineage_boundary"
                )
            )
        ),
        "patch_forward_artifact_boundary": dict(patch_forward_artifact_boundary),
        "worker_evidence_bundle_citation_boundary": dict(
            worker_evidence_bundle_citation_boundary
        ),
        "reviewer_independence": dict(reviewer_independence),
        "runner_session_boundary": dict(runner_session_boundary),
        "runner_recovery_lineage_boundary": dict(runner_recovery_lineage_boundary),
        "runner_recovery_proof_status": (
            _text(runner_recovery_lineage.get("status")) or "not_provided"
        ),
        "runner_recovery_proof_level": (
            _text(runner_recovery_lineage.get("proof_level")) or "manual_gap"
        ),
        "manual_gaps": manual_gaps,
        "forbidden_claims": forbidden_claims,
    }


def _validate_session_artifacts(
    *,
    root: Path,
    closure: Mapping[str, Any],
    conversation_id: str | None,
    graph_id: str | None,
    failed_lane_id: str | None,
    terminal_lane_id: str | None,
    candidate_lineages: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[str] = []
    artifacts: dict[str, dict[str, Any]] = {}
    specs = (
        {
            "key": "patch_forward_artifact",
            "expected_dir": "reports/god_room_patch_forward",
            "schema_version": "xmuse.god_room_lane_patch_forward.v1",
            "checks": {
                "conversation_id": conversation_id,
                "graph_id": graph_id,
                "failed_lane_id": failed_lane_id,
                "patch_lane_id": terminal_lane_id,
            },
        },
        {
            "key": "patch_lane_review_intake_artifact",
            "expected_dir": "reports/god_room_review_intake",
            "schema_version": "xmuse.god_room_lane_review_intake.v1",
            "checks": {
                "conversation_id": conversation_id,
                "graph_id": graph_id,
                "lane_id": terminal_lane_id,
                "candidate_truth_status": "candidate_only",
            },
        },
        {
            "key": "patch_lane_review_verdict_artifact",
            "expected_dir": "reports/god_room_review_verdicts",
            "schema_version": "xmuse.god_room_lane_review_verdict.v1",
            "checks": {
                "conversation_id": conversation_id,
                "graph_id": graph_id,
                "lane_id": terminal_lane_id,
                "review_truth_status": "independent_review_artifact",
                "server_truth_status": "not_server_truth",
            },
        },
    )
    for spec in specs:
        key = str(spec["key"])
        ref = _text(closure.get(key))
        detail, artifact_issues = _validate_session_artifact(
            root=root,
            key=key,
            ref=ref,
            expected_dir=str(spec["expected_dir"]),
            expected_schema=str(spec["schema_version"]),
            expected_fields=dict(spec["checks"]),
        )
        issues.extend(artifact_issues)
        artifacts[key] = detail

    patch_forward_detail = artifacts.get("patch_forward_artifact", {})
    patch_forward_payload = _mapping(patch_forward_detail.get("payload"))
    patch_forward_verdict_detail, patch_forward_verdict_issues = (
        _validate_session_artifact(
            root=root,
            key="patch_forward_review_verdict_artifact",
            ref=_text(patch_forward_payload.get("review_verdict_artifact")),
            expected_dir="reports/god_room_review_verdicts",
            expected_schema="xmuse.god_room_lane_review_verdict.v1",
            expected_fields={
                "conversation_id": conversation_id,
                "graph_id": graph_id,
                "lane_id": failed_lane_id,
                "review_truth_status": "independent_review_artifact",
                "server_truth_status": "not_server_truth",
            },
        )
    )
    issues.extend(patch_forward_verdict_issues)
    artifacts["patch_forward_review_verdict_artifact"] = patch_forward_verdict_detail
    patch_forward_verdict_payload = _mapping(
        patch_forward_verdict_detail.get("payload")
    )
    patch_forward_verdict = _mapping(
        patch_forward_verdict_payload.get("review_verdict")
    )
    if (
        patch_forward_verdict_payload
        and _text(patch_forward_verdict.get("decision")) != "patch-forward"
    ):
        issues.append("patch forward review verdict artifact decision is not patch-forward")
    issues.extend(
        _validate_patch_forward_lane_contract(
            closure=closure,
            patch_forward_payload=patch_forward_payload,
            failed_lane_id=failed_lane_id,
            terminal_lane_id=terminal_lane_id,
            patch_forward_verdict_id=_text(patch_forward_verdict.get("id")),
        )
    )
    intake_detail = artifacts.get("patch_lane_review_intake_artifact", {})
    intake_payload = _mapping(intake_detail.get("payload"))
    review_intake_graph_status_boundary = _review_intake_graph_status_boundary(
        intake_detail
    )
    issues.extend(_string_list(review_intake_graph_status_boundary.get("issues")))
    candidate_graph_status_boundary = _candidate_graph_status_boundary(
        candidate_lineages=candidate_lineages,
        intake_detail=intake_detail,
    )
    issues.extend(_string_list(candidate_graph_status_boundary.get("issues")))
    candidate_artifact_ref_boundary = _candidate_artifact_ref_boundary(
        closure=closure,
        candidate_lineages=candidate_lineages,
    )
    issues.extend(_string_list(candidate_artifact_ref_boundary.get("issues")))
    candidate_lineage_boundary = _candidate_lineage_boundary(
        closure=closure,
        candidate_lineages=candidate_lineages,
    )
    issues.extend(_string_list(candidate_lineage_boundary.get("issues")))
    intake_execution_artifact_refs = set(
        _string_list(intake_payload.get("execution_artifact_refs"))
    )
    closure_cited_candidate_artifact_refs = _string_list(
        closure.get("cited_candidate_artifact_refs")
    )
    missing_intake_candidate_refs = [
        ref
        for ref in closure_cited_candidate_artifact_refs
        if ref not in intake_execution_artifact_refs
    ]
    if missing_intake_candidate_refs:
        issues.append(
            "patch lane review intake execution_artifact_refs missing closure "
            "cited candidate artifact refs: "
            + ", ".join(missing_intake_candidate_refs)
        )

    verdict_detail = artifacts.get("patch_lane_review_verdict_artifact", {})
    verdict_payload = _mapping(verdict_detail.get("payload"))
    review_verdict = _mapping(verdict_payload.get("review_verdict"))
    if verdict_payload:
        if _text(review_verdict.get("decision")) != "merge":
            issues.append("patch lane review verdict artifact decision is not merge")
        closure_verdict = _mapping(closure.get("terminal_review_verdict"))
        closure_verdict_id = _text(closure_verdict.get("id"))
        verdict_id = _text(review_verdict.get("id"))
        if closure_verdict_id is not None and verdict_id != closure_verdict_id:
            issues.append("patch lane review verdict artifact id does not match closure")
        closure_review_plane_ref = _text(closure.get("review_plane_verdict_ref"))
        verdict_review_plane_ref = _text(verdict_payload.get("review_plane_verdict_ref"))
        if (
            closure_review_plane_ref is not None
            and verdict_review_plane_ref != closure_review_plane_ref
        ):
            issues.append(
                "patch lane review verdict artifact review-plane ref does not match closure"
            )
        verdict_evidence_refs = set(_string_list(review_verdict.get("evidence_refs")))
        patch_lane_review_intake_ref = _text(
            closure.get("patch_lane_review_intake_artifact")
        )
        if (
            patch_lane_review_intake_ref is not None
            and patch_lane_review_intake_ref not in verdict_evidence_refs
        ):
            issues.append(
                "patch lane review verdict evidence_refs missing review intake artifact"
            )
        missing_verdict_candidate_refs = [
            ref
            for ref in _string_list(closure.get("cited_candidate_refs"))
            if ref not in verdict_evidence_refs
        ]
        if missing_verdict_candidate_refs:
            issues.append(
                "patch lane review verdict evidence_refs missing closure cited "
                "candidate refs: "
                + ", ".join(missing_verdict_candidate_refs)
            )

    worker_evidence_bundle_citation_boundary = (
        _worker_evidence_bundle_citation_boundary(
            patch_forward_payload=patch_forward_payload,
            patch_forward_verdict_payload=patch_forward_verdict_payload,
            terminal_verdict_payload=verdict_payload,
        )
    )
    issues.extend(
        _string_list(worker_evidence_bundle_citation_boundary.get("issues"))
    )

    validated_artifacts = {
        key: _session_artifact_summary(value) for key, value in artifacts.items()
    }
    artifact_refs = _ordered_unique(
        _text(value.get("artifact_ref")) for value in artifacts.values()
    )
    status = "validated" if not issues else "manual_gap"
    return {
        "schema_version": LOCAL_EXECUTION_REVIEW_SESSION_ARTIFACT_VALIDATION_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "validated" else "manual_gap",
        "artifact_count": len(
            [
                value
                for value in validated_artifacts.values()
                if value.get("status") == "validated"
            ]
        ),
        "artifact_refs": artifact_refs,
        "validated_artifacts": validated_artifacts,
        "patch_forward_artifact_boundary": _patch_forward_source_boundary(
            patch_forward_detail
        ),
        "review_intake_graph_status_boundary": review_intake_graph_status_boundary,
        "candidate_graph_status_boundary": candidate_graph_status_boundary,
        "candidate_artifact_ref_boundary": candidate_artifact_ref_boundary,
        "candidate_lineage_boundary": candidate_lineage_boundary,
        "worker_evidence_bundle_citation_boundary": (
            worker_evidence_bundle_citation_boundary
        ),
        "issues": _ordered_unique(issues),
        "manual_gaps": (
            []
            if status == "validated"
            else ["local_execution_review_session_artifact_validation_failed"]
        ),
    }


def _worker_evidence_bundle_citation_boundary(
    *,
    patch_forward_payload: Mapping[str, Any],
    patch_forward_verdict_payload: Mapping[str, Any],
    terminal_verdict_payload: Mapping[str, Any],
) -> dict[str, Any]:
    verdict_refs = _ordered_unique(
        _string_list(patch_forward_verdict_payload.get("worker_evidence_bundle_refs"))
    )
    verdict_cited_refs = _ordered_unique(
        _string_list(
            patch_forward_verdict_payload.get("cited_worker_evidence_bundle_refs")
        )
    )
    patch_forward_refs = _ordered_unique(
        _string_list(patch_forward_payload.get("worker_evidence_bundle_refs"))
    )
    patch_forward_cited_refs = _ordered_unique(
        _string_list(patch_forward_payload.get("cited_worker_evidence_bundle_refs"))
    )
    verdict_status = (
        _text(patch_forward_verdict_payload.get("worker_evidence_bundle_citation_status"))
        or "not_required"
    )
    patch_forward_status = (
        _text(patch_forward_payload.get("worker_evidence_bundle_citation_status"))
        or "not_required"
    )
    terminal_refs = _ordered_unique(
        _string_list(terminal_verdict_payload.get("worker_evidence_bundle_refs"))
    )
    terminal_cited_refs = _ordered_unique(
        _string_list(terminal_verdict_payload.get("cited_worker_evidence_bundle_refs"))
    )
    terminal_status = (
        _text(terminal_verdict_payload.get("worker_evidence_bundle_citation_status"))
        or "not_required"
    )

    issues: list[str] = []
    missing_cited_refs = [
        ref for ref in verdict_refs if ref not in set(verdict_cited_refs)
    ]
    if missing_cited_refs:
        issues.append(
            "patch-forward review verdict did not cite discovered worker evidence "
            "bundle refs: "
            + ", ".join(missing_cited_refs)
        )
    if verdict_refs and verdict_status != "verified":
        issues.append(
            "patch-forward review verdict worker evidence bundle citation status "
            "is not verified"
        )
    if patch_forward_refs != verdict_refs:
        issues.append(
            "patch-forward artifact worker evidence bundle refs do not match "
            "source review verdict"
        )
    if patch_forward_cited_refs != verdict_cited_refs:
        issues.append(
            "patch-forward artifact cited worker evidence bundle refs do not match "
            "source review verdict"
        )
    if patch_forward_status != verdict_status:
        issues.append(
            "patch-forward artifact worker evidence bundle citation status does "
            "not match source review verdict"
        )
    missing_terminal_cited_refs = [
        ref for ref in terminal_refs if ref not in set(terminal_cited_refs)
    ]
    if missing_terminal_cited_refs:
        issues.append(
            "terminal patch-lane review verdict did not cite discovered worker "
            "evidence bundle refs: "
            + ", ".join(missing_terminal_cited_refs)
        )
    if terminal_refs and terminal_status != "verified":
        issues.append(
            "terminal patch-lane review verdict worker evidence bundle citation "
            "status is not verified"
        )

    status = "verified" if not issues else "manual_gap"
    all_refs = _ordered_unique([*verdict_refs, *patch_forward_refs, *terminal_refs])
    all_cited_refs = _ordered_unique(
        [*verdict_cited_refs, *patch_forward_cited_refs, *terminal_cited_refs]
    )
    return {
        "schema_version": WORKER_EVIDENCE_BUNDLE_CITATION_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "citation_status": "verified" if all_refs else "not_required",
        "source_review_verdict_worker_evidence_bundle_refs": verdict_refs,
        "source_review_verdict_cited_worker_evidence_bundle_refs": verdict_cited_refs,
        "patch_forward_worker_evidence_bundle_refs": patch_forward_refs,
        "patch_forward_cited_worker_evidence_bundle_refs": patch_forward_cited_refs,
        "terminal_review_verdict_worker_evidence_bundle_refs": terminal_refs,
        "terminal_review_verdict_cited_worker_evidence_bundle_refs": (
            terminal_cited_refs
        ),
        "all_worker_evidence_bundle_refs": all_refs,
        "all_cited_worker_evidence_bundle_refs": all_cited_refs,
        "issues": issues,
        "manual_gaps": (
            []
            if status == "verified"
            else ["worker_evidence_bundle_citation_not_proven"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
            "server_side_truth",
        ],
    }


def _candidate_artifact_ref_boundary(
    *,
    closure: Mapping[str, Any],
    candidate_lineages: list[dict[str, Any]],
) -> dict[str, Any]:
    closure_refs = _ordered_unique(
        _text(ref) for ref in _string_list(closure.get("cited_candidate_artifact_refs"))
    )
    resolved_refs = _ordered_unique(
        _text(lineage.get("artifact_ref")) for lineage in candidate_lineages
    )
    closure_ref_set = set(closure_refs)
    resolved_ref_set = set(resolved_refs)
    missing_refs = [ref for ref in closure_refs if ref not in resolved_ref_set]
    unexpected_refs = [ref for ref in resolved_refs if ref not in closure_ref_set]
    issues: list[str] = []
    if missing_refs:
        issues.append(
            "review closure cited_candidate_artifact_refs not resolved as valid "
            "local execution candidate lineage: "
            + ", ".join(missing_refs)
        )
    if unexpected_refs:
        issues.append(
            "resolved local execution candidate lineage has artifact refs not "
            "declared by review closure cited_candidate_artifact_refs: "
            + ", ".join(unexpected_refs)
        )
    status = "verified" if closure_refs and not issues else "manual_gap"
    return {
        "schema_version": CANDIDATE_ARTIFACT_REF_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "closure_cited_candidate_artifact_refs": closure_refs,
        "resolved_candidate_artifact_refs": resolved_refs,
        "missing_resolved_candidate_artifact_refs": missing_refs,
        "unexpected_resolved_candidate_artifact_refs": unexpected_refs,
        "issues": issues,
        "manual_gaps": (
            []
            if status == "verified"
            else ["candidate_artifact_refs_not_resolved"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
        ],
    }


def _candidate_lineage_boundary(
    *,
    closure: Mapping[str, Any],
    candidate_lineages: list[dict[str, Any]],
) -> dict[str, Any]:
    closure_lineages = _mapping_list(closure.get("cited_candidate_artifact_lineage"))
    resolved_by_ref = _lineages_by_artifact_ref(candidate_lineages)
    closure_by_ref = _lineages_by_artifact_ref(closure_lineages)
    resolved_refs = list(resolved_by_ref)
    closure_refs = list(closure_by_ref)
    resolved_ref_set = set(resolved_refs)
    closure_ref_set = set(closure_refs)
    missing_embedded_refs = [
        ref for ref in resolved_refs if ref not in closure_ref_set
    ]
    unexpected_embedded_refs = [
        ref for ref in closure_refs if ref not in resolved_ref_set
    ]
    mismatched_embedded_refs = [
        ref
        for ref in resolved_refs
        if ref in closure_by_ref and closure_by_ref[ref] != resolved_by_ref[ref]
    ]
    issues: list[str] = []
    if missing_embedded_refs:
        issues.append(
            "review closure cited_candidate_artifact_lineage missing resolved "
            "local execution candidate lineage refs: "
            + ", ".join(missing_embedded_refs)
        )
    if unexpected_embedded_refs:
        issues.append(
            "review closure cited_candidate_artifact_lineage contains refs not "
            "resolved as valid local execution candidate lineage: "
            + ", ".join(unexpected_embedded_refs)
        )
    if mismatched_embedded_refs:
        issues.append(
            "review closure cited_candidate_artifact_lineage does not match "
            "resolved local execution candidate lineage for refs: "
            + ", ".join(mismatched_embedded_refs)
        )
    status = "verified" if closure_lineages and not issues else "manual_gap"
    return {
        "schema_version": CANDIDATE_LINEAGE_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "closure_candidate_artifact_refs": closure_refs,
        "resolved_candidate_artifact_refs": resolved_refs,
        "missing_closure_candidate_artifact_lineage_refs": missing_embedded_refs,
        "unexpected_closure_candidate_artifact_lineage_refs": unexpected_embedded_refs,
        "mismatched_closure_candidate_artifact_lineage_refs": mismatched_embedded_refs,
        "issues": issues,
        "manual_gaps": (
            []
            if status == "verified"
            else ["candidate_artifact_lineage_not_resolved"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
        ],
    }


def _lineages_by_artifact_ref(
    lineages: list[dict[str, Any]] | list[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for lineage in lineages:
        artifact_ref = _text(lineage.get("artifact_ref"))
        if artifact_ref is None:
            continue
        result[artifact_ref] = lineage
    return result


def _review_intake_graph_status_boundary(detail: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(detail.get("payload"))
    artifact_status = _text(detail.get("status")) or "manual_gap"
    source_authority = _text(payload.get("source_authority"))
    source_authorities = {
        part.strip()
        for part in (source_authority or "").split("+")
        if part.strip()
    }
    source_event_lineage = _mapping_list(payload.get("source_event_lineage"))
    feature_graph_status = _mapping(payload.get("feature_graph_status"))
    feature_status_lineage = _mapping_list(
        feature_graph_status.get("source_event_lineage")
    )
    issues: list[str] = []
    if artifact_status != "validated":
        issues.append("patch lane review intake artifact is not validated")
    if "feature_graph_status_store" not in source_authorities:
        issues.append(
            "patch lane review intake source_authority is missing "
            "feature_graph_status_store"
        )
    if "lane_dag_artifact" not in source_authorities:
        issues.append(
            "patch lane review intake source_authority is missing lane_dag_artifact"
        )
    if not source_event_lineage:
        issues.append("patch lane review intake source_event_lineage is missing")
    if not feature_graph_status:
        issues.append("patch lane review intake feature graph status is missing")
    else:
        if _text(feature_graph_status.get("status")) != "reviewing":
            issues.append(
                "patch lane review intake feature graph status is not reviewing"
            )
        if _text(feature_graph_status.get("graph_set_id")) != _text(
            payload.get("graph_set_id")
        ):
            issues.append(
                "patch lane review intake feature graph status graph_set_id "
                "does not match intake"
            )
        if _text(feature_graph_status.get("feature_graph_id")) != _text(
            payload.get("feature_graph_id")
        ):
            issues.append(
                "patch lane review intake feature graph status feature_graph_id "
                "does not match intake"
            )
        if feature_status_lineage != source_event_lineage:
            issues.append(
                "patch lane review intake feature graph status source_event_lineage "
                "does not match intake"
            )
    status = "verified" if not issues else "manual_gap"
    return {
        "schema_version": REVIEW_INTAKE_GRAPH_STATUS_BOUNDARY_SCHEMA_VERSION,
        "artifact_ref": _text(detail.get("artifact_ref")),
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "source_authority": source_authority,
        "graph_set_id": _text(payload.get("graph_set_id")),
        "feature_graph_id": _text(payload.get("feature_graph_id")),
        "feature_graph_status": _text(feature_graph_status.get("status")),
        "source_event_lineage_count": len(source_event_lineage),
        "issues": issues,
        "manual_gaps": (
            []
            if status == "verified"
            else ["review_intake_graph_status_boundary_not_proven"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
        ],
    }


def _candidate_graph_status_boundary(
    *,
    candidate_lineages: list[dict[str, Any]],
    intake_detail: Mapping[str, Any],
) -> dict[str, Any]:
    payload = _mapping(intake_detail.get("payload"))
    feature_graph_status = _mapping(payload.get("feature_graph_status"))
    expected_lineage = _mapping_list(feature_graph_status.get("source_event_lineage"))
    issues: list[str] = []
    refs: list[str] = []
    if not candidate_lineages:
        issues.append("candidate graph status boundary has no candidate lineage")
    if not feature_graph_status:
        issues.append("candidate graph status boundary has no intake feature graph status")

    for lineage in candidate_lineages:
        artifact_ref = _text(lineage.get("artifact_ref")) or "unknown"
        refs.append(artifact_ref)
        graph_status_lineage = _mapping(lineage.get("graph_status_lineage"))
        if not graph_status_lineage:
            issues.append(
                f"local execution candidate {artifact_ref} missing graph status lineage"
            )
            continue
        for key in ("graph_set_id", "feature_graph_id", "status_id", "status"):
            if _text(graph_status_lineage.get(key)) != _text(
                feature_graph_status.get(key)
            ):
                issues.append(
                    f"local execution candidate {artifact_ref} graph_status_lineage."
                    f"{key} does not match review intake feature graph status"
                )
        candidate_lineage = _mapping_list(
            graph_status_lineage.get("source_event_lineage")
        )
        if candidate_lineage != expected_lineage:
            issues.append(
                f"local execution candidate {artifact_ref} graph_status_lineage."
                "source_event_lineage does not match review intake feature graph status"
            )

    status = "verified" if not issues else "manual_gap"
    return {
        "schema_version": CANDIDATE_GRAPH_STATUS_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "candidate_artifact_refs": _ordered_unique(refs),
        "candidate_count": len(candidate_lineages),
        "intake_feature_graph_status": {
            "graph_set_id": _text(feature_graph_status.get("graph_set_id")),
            "feature_graph_id": _text(feature_graph_status.get("feature_graph_id")),
            "status_id": _text(feature_graph_status.get("status_id")),
            "status": _text(feature_graph_status.get("status")),
            "source_event_lineage_count": len(expected_lineage),
        },
        "issues": issues,
        "manual_gaps": (
            []
            if status == "verified"
            else ["candidate_graph_status_boundary_not_proven"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
        ],
    }


def _patch_forward_source_boundary(detail: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(detail.get("payload"))
    return {
        "schema_version": PATCH_FORWARD_ARTIFACT_BOUNDARY_SCHEMA_VERSION,
        "artifact_ref": _text(detail.get("artifact_ref")),
        "artifact_status": _text(detail.get("status")) or "manual_gap",
        "artifact_schema_version": _text(detail.get("schema_version")),
        "artifact_proof_level": _text(detail.get("proof_level")),
        "source_manual_gaps": _string_list(payload.get("manual_gaps")),
        "source_forbidden_claims": _string_list(payload.get("forbidden_claims")),
    }


def _resolve_patch_forward_artifact_boundary(
    *,
    closure: Mapping[str, Any],
    candidate_lineages: list[dict[str, Any]],
    session_artifact_validation: Mapping[str, Any],
) -> dict[str, Any]:
    source = _mapping(
        session_artifact_validation.get("patch_forward_artifact_boundary")
    )
    source_manual_gaps = _string_list(source.get("source_manual_gaps"))
    source_forbidden_claims = _string_list(source.get("source_forbidden_claims"))
    validated_artifacts = _mapping(
        session_artifact_validation.get("validated_artifacts")
    )
    intake = _mapping(validated_artifacts.get("patch_lane_review_intake_artifact"))
    verdict = _mapping(validated_artifacts.get("patch_lane_review_verdict_artifact"))
    candidate_artifact_refs = _ordered_unique(
        _text(lineage.get("artifact_ref")) for lineage in candidate_lineages
    )

    resolved: list[str] = []
    evidence_refs: dict[str, list[str]] = {}
    if (
        "patch_lane_not_executed" in source_manual_gaps
        and candidate_artifact_refs
        and _text(intake.get("status")) == "validated"
    ):
        resolved.append("patch_lane_not_executed")
        evidence_refs["patch_lane_not_executed"] = _ordered_unique(
            [
                _text(closure.get("patch_lane_review_intake_artifact")),
                *candidate_artifact_refs,
            ]
        )
    if (
        "patch_lane_not_reviewed" in source_manual_gaps
        and _text(verdict.get("status")) == "validated"
    ):
        resolved.append("patch_lane_not_reviewed")
        evidence_refs["patch_lane_not_reviewed"] = _ordered_unique(
            [
                _text(closure.get("patch_lane_review_verdict_artifact")),
                _text(closure.get("review_plane_verdict_ref")),
            ]
        )

    retained = [gap for gap in source_manual_gaps if gap not in set(resolved)]
    artifact_status = _text(source.get("artifact_status")) or "manual_gap"
    if artifact_status != "validated":
        status = "manual_gap"
    elif retained and resolved:
        status = "resolved_with_retained_manual_gaps"
    elif retained:
        status = "source_manual_gaps_retained"
    elif resolved:
        status = "source_manual_gaps_resolved"
    else:
        status = "no_source_manual_gaps"
    return {
        **source,
        "status": status,
        "resolved_manual_gaps": resolved,
        "retained_manual_gaps": retained,
        "resolution_evidence_refs": evidence_refs,
        "source_forbidden_claims": source_forbidden_claims,
    }


def _reviewer_independence_boundary(
    *,
    candidate_lineages: list[dict[str, Any]],
    session_artifact_validation: Mapping[str, Any],
) -> dict[str, Any]:
    validated_artifacts = _mapping(
        session_artifact_validation.get("validated_artifacts")
    )
    verdict = _mapping(validated_artifacts.get("patch_lane_review_verdict_artifact"))
    verdict_status = _text(verdict.get("status")) or "manual_gap"
    reviewer_id = _text(verdict.get("reviewer_id"))
    candidate_worker_ids = _ordered_unique(
        _text(lineage.get("worker_id")) for lineage in candidate_lineages
    )
    issues: list[str] = []
    manual_gaps: list[str] = []
    forbidden_claims = ["worker_self_review_equals_review_truth"]
    if verdict_status != "validated":
        status = "manual_gap"
        manual_gaps.append("reviewer_independence_not_checked")
    elif reviewer_id is None:
        status = "manual_gap"
        issues.append("patch lane review verdict reviewer_id is missing")
        manual_gaps.append("reviewer_identity_not_proven")
    elif not candidate_worker_ids:
        status = "manual_gap"
        issues.append("reviewer independence has no candidate worker identity")
        manual_gaps.append("candidate_worker_identity_not_proven")
    elif reviewer_id in candidate_worker_ids:
        status = "manual_gap"
        issues.append(
            "patch lane review verdict reviewer_id matches candidate worker_id: "
            f"{reviewer_id}"
        )
        manual_gaps.append("reviewer_matches_candidate_worker")
    else:
        status = "verified"
    return {
        "schema_version": REVIEWER_INDEPENDENCE_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "reviewer_id": reviewer_id,
        "candidate_worker_ids": candidate_worker_ids,
        "issues": issues,
        "manual_gaps": manual_gaps,
        "forbidden_claims": forbidden_claims,
    }


def _validate_patch_forward_lane_contract(
    *,
    closure: Mapping[str, Any],
    patch_forward_payload: Mapping[str, Any],
    failed_lane_id: str | None,
    terminal_lane_id: str | None,
    patch_forward_verdict_id: str | None,
) -> list[str]:
    issues: list[str] = []
    patch_forward_verdict_ref = _text(
        patch_forward_payload.get("review_verdict_artifact")
    )
    link = _mapping(patch_forward_payload.get("patch_forward_link"))
    if not link:
        issues.append("patch forward artifact missing patch_forward_link")
    else:
        if _text(link.get("failed_lane_id")) != failed_lane_id:
            issues.append(
                "patch forward artifact patch_forward_link.failed_lane_id "
                "does not match closure"
            )
        if _text(link.get("patch_lane_id")) != terminal_lane_id:
            issues.append(
                "patch forward artifact patch_forward_link.patch_lane_id "
                "does not match closure"
            )
        link_verdict_ref = _text(link.get("verdict_ref"))
        expected_verdict_ref = (
            f"god_room_review_verdict:{patch_forward_verdict_id}"
            if patch_forward_verdict_id is not None
            else None
        )
        if link_verdict_ref is None:
            issues.append("patch forward artifact patch_forward_link.verdict_ref is empty")
        elif expected_verdict_ref is not None and link_verdict_ref != expected_verdict_ref:
            issues.append(
                "patch forward artifact patch_forward_link.verdict_ref does not "
                "match patch-forward review verdict"
            )
        link_evidence_refs = _string_list(link.get("evidence_refs"))
        if not link_evidence_refs:
            issues.append(
                "patch forward artifact patch_forward_link.evidence_refs is empty"
            )
        elif (
            patch_forward_verdict_ref is not None
            and patch_forward_verdict_ref not in link_evidence_refs
        ):
            issues.append(
                "patch forward artifact patch_forward_link.evidence_refs missing "
                "review verdict artifact"
            )
        closure_link = _mapping(closure.get("patch_forward_link"))
        if closure_link and closure_link != link:
            issues.append(
                "patch forward artifact patch_forward_link does not match closure"
            )

    contract = _mapping(patch_forward_payload.get("patch_lane_contract"))
    if not contract:
        issues.append("patch forward artifact missing patch_lane_contract")
        return issues

    if _text(contract.get("lane_id")) != terminal_lane_id:
        issues.append(
            "patch forward artifact patch_lane_contract.lane_id does not match "
            "terminal lane"
        )
    for key in ("feature_id", "owner", "review_profile"):
        if _text(contract.get(key)) is None:
            issues.append(f"patch forward artifact patch_lane_contract.{key} is empty")

    expected_failed_lane_ref = (
        f"lane:{failed_lane_id}" if failed_lane_id is not None else None
    )
    expected_output_ref = (
        f"artifact://{terminal_lane_id}/patch-forward-evidence.json"
        if terminal_lane_id is not None
        else None
    )
    inputs = _string_list(contract.get("inputs"))
    outputs = _string_list(contract.get("outputs"))
    dependency_refs = _string_list(contract.get("dependency_refs"))
    required_checks = _string_list(contract.get("required_checks"))
    source_refs = _string_list(contract.get("source_refs"))
    if not inputs:
        issues.append("patch forward artifact patch_lane_contract.inputs is empty")
    elif expected_failed_lane_ref is not None and expected_failed_lane_ref not in inputs:
        issues.append(
            "patch forward artifact patch_lane_contract.inputs missing failed lane ref"
        )
    if not outputs:
        issues.append("patch forward artifact patch_lane_contract.outputs is empty")
    elif expected_output_ref is not None and expected_output_ref not in outputs:
        issues.append(
            "patch forward artifact patch_lane_contract.outputs missing patch lane "
            "output ref"
        )
    if (
        expected_failed_lane_ref is not None
        and expected_failed_lane_ref not in dependency_refs
    ):
        issues.append(
            "patch forward artifact patch_lane_contract.dependency_refs missing "
            "failed lane ref"
        )
    if not required_checks:
        issues.append(
            "patch forward artifact patch_lane_contract.required_checks is empty"
        )
    link_evidence_refs = _string_list(link.get("evidence_refs")) if link else []
    missing_source_refs = [ref for ref in link_evidence_refs if ref not in source_refs]
    if missing_source_refs:
        issues.append(
            "patch forward artifact patch_lane_contract.source_refs missing "
            "patch_forward_link evidence refs: "
            + ", ".join(missing_source_refs)
        )
    closure_contract = _mapping(closure.get("patch_lane_contract"))
    if closure_contract and closure_contract != contract:
        issues.append(
            "patch forward artifact patch_lane_contract does not match closure"
        )
    return issues


def _validate_session_artifact(
    *,
    root: Path,
    key: str,
    ref: str | None,
    expected_dir: str,
    expected_schema: str,
    expected_fields: Mapping[str, str | None],
) -> tuple[dict[str, Any], list[str]]:
    issues: list[str] = []
    base: dict[str, Any] = {
        "artifact_ref": ref,
        "status": "manual_gap",
        "schema_version": None,
        "proof_level": None,
        "payload": None,
    }
    if ref is None:
        return base, [f"{key} is missing"]
    path, path_issue = _session_artifact_path(root, ref, expected_dir=expected_dir)
    if path is None:
        return base, [path_issue or f"{key} path is invalid"]
    if not path.is_file():
        return base, [f"{key} artifact is missing"]
    payload, load_error = _load_json(path)
    if payload is None:
        return base, [load_error or f"{key} artifact is not readable"]
    base["payload"] = payload
    schema_version = _text(payload.get("schema_version"))
    proof_level = _text(payload.get("proof_level"))
    base["schema_version"] = schema_version
    base["proof_level"] = proof_level
    if schema_version != expected_schema:
        issues.append(f"{key} schema is not {expected_schema}")
    if proof_level != "contract_proof":
        issues.append(f"{key} proof_level is not contract_proof")
    for field, expected in expected_fields.items():
        if expected is None:
            continue
        if _text(payload.get(field)) != expected:
            issues.append(f"{key} {field} does not match closure")
    if issues:
        return base, issues
    return {**base, "status": "validated"}, []


def _session_artifact_path(
    root: Path,
    artifact_ref: str,
    *,
    expected_dir: str,
) -> tuple[Path | None, str | None]:
    if "://" in artifact_ref:
        return None, "session artifact ref must be a local artifact path"
    root_resolved = root.resolve(strict=False)
    path = Path(artifact_ref)
    resolved = path.resolve(strict=False) if path.is_absolute() else (
        root_resolved / path
    ).resolve(strict=False)
    try:
        relative = resolved.relative_to(root_resolved)
    except ValueError:
        return None, "session artifact ref escapes xmuse root"
    expected_prefix = Path(expected_dir)
    if not relative.parts or not _path_startswith(relative, expected_prefix):
        return None, f"session artifact ref is not under {expected_dir}"
    return resolved, None


def _path_startswith(path: Path, prefix: Path) -> bool:
    prefix_parts = prefix.parts
    return path.parts[: len(prefix_parts)] == prefix_parts


def _session_artifact_summary(detail: Mapping[str, Any]) -> dict[str, Any]:
    payload = _mapping(detail.get("payload"))
    return {
        "artifact_ref": _text(detail.get("artifact_ref")),
        "status": _text(detail.get("status")) or "manual_gap",
        "schema_version": _text(detail.get("schema_version")),
        "proof_level": _text(detail.get("proof_level")),
        "reviewer_id": _text(payload.get("reviewer_id")),
    }


def _review_closure_issues(closure: Mapping[str, Any]) -> list[str]:
    issues: list[str] = []
    expected = {
        "schema_version": "xmuse.god_room_lane_review_closure.v1",
        "proof_level": "contract_proof",
        "review_truth_status": "independent_review_artifact",
        "execution_truth_status": "candidate_reviewed",
        "server_truth_status": "not_server_truth",
        "release_evidence_handoff_status": "candidate_input_ready",
    }
    for key, value in expected.items():
        if _text(closure.get(key)) != value:
            issues.append(f"GOD room review closure {key} is not {value}")
    for key in ("conversation_id", "graph_id", "failed_lane_id", "terminal_lane_id"):
        if _text(closure.get(key)) is None:
            issues.append(f"GOD room review closure missing {key}")
    forbidden_claims = set(_string_list(closure.get("forbidden_claims")))
    missing_forbidden = sorted(
        REQUIRED_GOD_ROOM_REVIEW_CLOSURE_FORBIDDEN_CLAIMS - forbidden_claims
    )
    if missing_forbidden:
        issues.append(
            "GOD room review closure missing forbidden claims: "
            + ", ".join(missing_forbidden)
        )
    terminal_verdict = _mapping(closure.get("terminal_review_verdict"))
    if _text(terminal_verdict.get("decision")) != "merge":
        issues.append("GOD room review closure terminal verdict is not merge")
    if _text(closure.get("review_plane_sync_status")) != "review_plane_store_updated":
        issues.append("GOD room review closure is missing review-plane store sync")
    if _text(closure.get("graph_status_merge_status")) != "verified_merged":
        issues.append("GOD room review closure terminal graph status is not merged")
    if _text(closure.get("graph_status_source_authority")) != "feature_graph_status_store":
        issues.append(
            "GOD room review closure graph status authority is not "
            "feature_graph_status_store"
        )
    source_event_lineage = _mapping_list(closure.get("source_event_lineage"))
    if not source_event_lineage:
        issues.append("GOD room review closure source_event_lineage is missing")
    elif any(_text(event.get("event_id")) is None for event in source_event_lineage):
        issues.append("GOD room review closure source_event_lineage has missing event_id")
    terminal_graph_status = _mapping(closure.get("terminal_feature_graph_status"))
    if not terminal_graph_status:
        issues.append("GOD room review closure terminal feature graph status is missing")
    else:
        if _text(terminal_graph_status.get("status")) != "merged":
            issues.append(
                "GOD room review closure terminal feature graph status is not merged"
            )
        if (
            _mapping_list(terminal_graph_status.get("source_event_lineage"))
            != source_event_lineage
        ):
            issues.append(
                "GOD room review closure terminal feature graph status "
                "source_event_lineage does not match closure"
            )
    return issues


def _graph_wide_lane_accounting_boundary(
    *,
    root: Path,
    closure: Mapping[str, Any],
    candidate_lineages: list[dict[str, Any]],
) -> dict[str, Any]:
    conversation_id = _text(closure.get("conversation_id"))
    graph_id = _text(closure.get("graph_id"))
    failed_lane_id = _text(closure.get("failed_lane_id"))
    terminal_lane_id = _text(closure.get("terminal_lane_id"))
    terminal_status = _mapping(closure.get("terminal_feature_graph_status"))
    graph_set_id = _text(terminal_status.get("graph_set_id"))
    candidate_refs = _ordered_unique(
        _text(lineage.get("artifact_ref")) for lineage in candidate_lineages
    )
    candidate_lanes_by_graph: dict[str, set[str]] = {}
    candidate_refs_by_graph: dict[str, list[str]] = {}
    for lineage in candidate_lineages:
        graph_status_lineage = _mapping(lineage.get("graph_status_lineage"))
        feature_graph_id = _text(graph_status_lineage.get("feature_graph_id"))
        lane_id = _text(lineage.get("lane_id"))
        artifact_ref = _text(lineage.get("artifact_ref"))
        if feature_graph_id is None or lane_id is None:
            continue
        candidate_lanes_by_graph.setdefault(feature_graph_id, set()).add(lane_id)
        if artifact_ref is not None:
            candidate_refs_by_graph.setdefault(feature_graph_id, []).append(artifact_ref)

    issues: list[str] = []
    if conversation_id is None:
        issues.append("graph-wide lane accounting missing conversation_id")
    if graph_id is None:
        issues.append("graph-wide lane accounting missing graph_id")
    if graph_set_id is None:
        issues.append("graph-wide lane accounting missing graph_set_id")

    graph_set_loaded = False
    expected_feature_graph_ids: list[str] = []
    expected_lane_ids_by_graph: dict[str, list[str]] = {}
    if graph_set_id is not None:
        try:
            graph_set = FeatureGraphSetStore(root / "graph_sets").get(
                graph_set_id,
                conversation_id=conversation_id,
            )
            graph_set_loaded = True
            expected_feature_graph_ids = _ordered_unique(
                _text(graph.id) for graph in graph_set.graphs
            )
            expected_lane_ids_by_graph = {
                graph.id: _ordered_unique(_text(lane.feature_id) for lane in graph.lanes)
                for graph in graph_set.graphs
            }
        except (KeyError, ValueError) as exc:
            issues.append(f"feature graph set artifact is not readable: {exc}")

    status_store_loaded = False
    status_records = []
    if graph_set_id is not None:
        try:
            status_records = FeatureGraphStatusStore(
                root / "feature_graph_statuses.json"
            ).list(graph_set_id=graph_set_id, conversation_id=conversation_id)
            status_store_loaded = True
        except (ValueError, OSError) as exc:
            issues.append(f"feature graph status store is not readable: {exc}")
    if not status_records:
        issues.append("graph-wide lane accounting has no feature graph status records")

    observed_feature_graph_ids = _ordered_unique(
        _text(record.feature_graph_id) for record in status_records
    )
    missing_feature_graph_ids = [
        feature_graph_id
        for feature_graph_id in expected_feature_graph_ids
        if feature_graph_id not in observed_feature_graph_ids
    ]
    unexpected_feature_graph_ids = [
        feature_graph_id
        for feature_graph_id in observed_feature_graph_ids
        if expected_feature_graph_ids and feature_graph_id not in expected_feature_graph_ids
    ]
    if missing_feature_graph_ids:
        issues.append(
            "graph-wide lane accounting missing feature graph status records: "
            + ", ".join(missing_feature_graph_ids)
        )
    if unexpected_feature_graph_ids:
        issues.append(
            "graph-wide lane accounting found status records outside graph set: "
            + ", ".join(unexpected_feature_graph_ids)
        )

    per_graph: list[dict[str, Any]] = []
    all_ready_lane_ids: list[str] = []
    all_active_lane_ids: list[str] = []
    all_completed_lane_ids: list[str] = []
    all_blocked_lane_ids: list[str] = []
    all_projection_lane_ids: list[str] = []
    uncovered_completed_lane_ids: list[str] = []
    missing_expected_lane_ids: list[str] = []
    patch_forward_superseded_lane_ids: list[str] = []
    terminal_lane_completed = (
        terminal_lane_id is not None
        and any(terminal_lane_id in record.completed_lane_ids for record in status_records)
    )
    for record in status_records:
        feature_graph_id = record.feature_graph_id
        ready_lane_ids = _ordered_unique(record.ready_lane_ids)
        active_lane_ids = _ordered_unique(record.active_lane_ids)
        completed_lane_ids = _ordered_unique(record.completed_lane_ids)
        blocked_lane_ids = _ordered_unique(record.blocked_lane_ids)
        projection_lane_ids = _ordered_unique(record.projection_lane_ids)
        observed_lane_ids = _ordered_unique(
            [
                *ready_lane_ids,
                *active_lane_ids,
                *completed_lane_ids,
                *blocked_lane_ids,
                *projection_lane_ids,
            ]
        )
        expected_lane_ids = expected_lane_ids_by_graph.get(feature_graph_id, [])
        superseded_lanes = []
        if (
            failed_lane_id is not None
            and terminal_lane_id is not None
            and failed_lane_id in expected_lane_ids
            and terminal_lane_completed
        ):
            superseded_lanes.append(failed_lane_id)
            patch_forward_superseded_lane_ids.append(failed_lane_id)
        missing_lanes = [
            lane_id
            for lane_id in expected_lane_ids
            if lane_id not in observed_lane_ids and lane_id not in superseded_lanes
        ]
        missing_expected_lane_ids.extend(missing_lanes)

        covered_lanes = sorted(candidate_lanes_by_graph.get(feature_graph_id, set()))
        uncovered_completed = [
            lane_id
            for lane_id in completed_lane_ids
            if lane_id not in covered_lanes and lane_id not in superseded_lanes
        ]
        uncovered_completed_lane_ids.extend(uncovered_completed)
        record_satisfied_by_patch_forward = (
            bool(superseded_lanes)
            and set(completed_lane_ids).issubset(set(superseded_lanes))
            and not ready_lane_ids
            and not active_lane_ids
            and not blocked_lane_ids
        )
        if (
            record.status is not FeatureGraphExecutionStatus.MERGED
            and not record_satisfied_by_patch_forward
        ):
            issues.append(
                "graph-wide lane accounting feature graph status is not merged: "
                f"{feature_graph_id}={record.status.value}"
            )
        if ready_lane_ids:
            issues.append(
                "graph-wide lane accounting has ready lanes not reviewed: "
                + ", ".join(ready_lane_ids)
            )
        if active_lane_ids:
            issues.append(
                "graph-wide lane accounting has active lanes not reviewed: "
                + ", ".join(active_lane_ids)
            )
        if blocked_lane_ids:
            issues.append(
                "graph-wide lane accounting has blocked lanes without graph-wide "
                "review closure: "
                + ", ".join(blocked_lane_ids)
            )
        if not completed_lane_ids:
            issues.append(
                "graph-wide lane accounting has no completed lanes for feature graph: "
                + feature_graph_id
            )
        if missing_lanes:
            issues.append(
                "graph-wide lane accounting status record does not account expected "
                f"lanes for {feature_graph_id}: "
                + ", ".join(missing_lanes)
            )
        if uncovered_completed:
            issues.append(
                "graph-wide lane accounting completed lanes missing platform-runner "
                f"candidate lineage for {feature_graph_id}: "
                + ", ".join(uncovered_completed)
            )
        if not record.source_event_lineage:
            issues.append(
                "graph-wide lane accounting feature graph status source_event_lineage "
                f"is missing: {feature_graph_id}"
            )
        all_ready_lane_ids.extend(ready_lane_ids)
        all_active_lane_ids.extend(active_lane_ids)
        all_completed_lane_ids.extend(completed_lane_ids)
        all_blocked_lane_ids.extend(blocked_lane_ids)
        all_projection_lane_ids.extend(projection_lane_ids)
        per_graph.append(
            {
                "feature_graph_id": feature_graph_id,
                "status": record.status.value,
                "ready_lane_ids": ready_lane_ids,
                "active_lane_ids": active_lane_ids,
                "completed_lane_ids": completed_lane_ids,
                "blocked_lane_ids": blocked_lane_ids,
                "projection_lane_ids": projection_lane_ids,
                "expected_lane_ids": expected_lane_ids,
                "patch_forward_superseded_lane_ids": superseded_lanes,
                "candidate_covered_lane_ids": covered_lanes,
                "candidate_artifact_refs": _ordered_unique(
                    candidate_refs_by_graph.get(feature_graph_id, [])
                ),
                "source_event_lineage_count": len(record.source_event_lineage),
            }
        )

    if not candidate_refs:
        issues.append("graph-wide lane accounting has no candidate artifact refs")
    if missing_expected_lane_ids:
        issues.append(
            "graph-wide lane accounting missing expected lane ids from status records: "
            + ", ".join(_ordered_unique(missing_expected_lane_ids))
        )
    status = "verified" if not issues else "manual_gap"
    completed_lane_ids = _ordered_unique(all_completed_lane_ids)
    return {
        "schema_version": GRAPH_WIDE_LANE_ACCOUNTING_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "server_truth_status": "not_server_truth",
        "conversation_id": conversation_id,
        "graph_id": graph_id,
        "graph_set_id": graph_set_id,
        "graph_set_loaded": graph_set_loaded,
        "status_store_loaded": status_store_loaded,
        "expected_feature_graph_ids": expected_feature_graph_ids,
        "observed_feature_graph_ids": observed_feature_graph_ids,
        "missing_feature_graph_status_ids": missing_feature_graph_ids,
        "unexpected_feature_graph_status_ids": unexpected_feature_graph_ids,
        "graph_count": len(status_records),
        "lane_count": len(
            _ordered_unique(
                [
                    *all_ready_lane_ids,
                    *all_active_lane_ids,
                    *all_completed_lane_ids,
                    *all_blocked_lane_ids,
                    *all_projection_lane_ids,
                ]
            )
        ),
        "ready_lane_ids": _ordered_unique(all_ready_lane_ids),
        "active_lane_ids": _ordered_unique(all_active_lane_ids),
        "completed_lane_ids": completed_lane_ids,
        "blocked_lane_ids": _ordered_unique(all_blocked_lane_ids),
        "projection_lane_ids": _ordered_unique(all_projection_lane_ids),
        "patch_forward_superseded_lane_ids": _ordered_unique(
            patch_forward_superseded_lane_ids
        ),
        "candidate_artifact_refs": candidate_refs,
        "candidate_covered_lane_ids": _ordered_unique(
            lane_id
            for lanes in candidate_lanes_by_graph.values()
            for lane_id in sorted(lanes)
        ),
        "uncovered_completed_lane_ids": _ordered_unique(uncovered_completed_lane_ids),
        "per_graph": per_graph,
        "issues": _ordered_unique(issues),
        "manual_gaps": (
            []
            if status == "verified"
            else ["graph_wide_lane_accounting_not_verified"]
        ),
        "forbidden_claims": [
            "worker_output_is_review_truth",
            "end_to_end_execution_review_closure",
            "graph_wide_execution_review_closure",
            "server_side_truth",
        ],
    }


def _runner_session_boundary(
    *,
    root: Path,
    graph_id: str | None,
    candidate_lineages: list[dict[str, Any]],
) -> dict[str, Any]:
    issues: list[str] = []
    session_lineages: list[dict[str, Any]] = []
    candidate_refs: list[str] = []
    for lineage in candidate_lineages:
        candidate_ref = _text(lineage.get("artifact_ref"))
        session_ref = _text(lineage.get("runner_session_ref"))
        session_id = _text(lineage.get("runner_session_id"))
        run_id = _text(lineage.get("run_id"))
        runner_id = _text(lineage.get("worker_id"))
        if candidate_ref is not None:
            candidate_refs.append(candidate_ref)
        missing_fields = [
            field
            for field, value in (
                ("runner_session_ref", session_ref),
                ("runner_session_id", session_id),
                ("run_id", run_id),
                ("worker_id", runner_id),
            )
            if value is None
        ]
        if missing_fields:
            issues.append(
                "local execution candidate missing runner session fields for "
                f"{candidate_ref or 'unknown candidate'}: "
                + ", ".join(missing_fields)
            )
            continue
        try:
            session_lineages.append(
                load_runner_session_lineage(
                    root=root,
                    artifact_ref=session_ref,
                    session_id=session_id,
                    run_id=run_id,
                    runner_id=runner_id,
                    candidate_artifact_ref=candidate_ref,
                    graph_id=graph_id,
                )
            )
        except FileNotFoundError:
            issues.append(
                "runner session artifact is not readable: "
                f"{session_ref}"
            )
        except ValueError as exc:
            issues.append(f"runner session artifact is invalid: {exc}")

    session_ids = _ordered_unique(
        _text(lineage.get("session_id")) for lineage in session_lineages
    )
    session_refs = _ordered_unique(
        _text(lineage.get("artifact_ref")) for lineage in session_lineages
    )
    run_ids = _ordered_unique(_text(lineage.get("run_id")) for lineage in session_lineages)
    runner_ids = _ordered_unique(
        _text(lineage.get("runner_id")) for lineage in session_lineages
    )
    candidate_worker_bundle_refs = _ordered_unique(
        ref
        for lineage in candidate_lineages
        for ref in _string_list(lineage.get("source_refs"))
        if ref.startswith("feature_evidence_bundle:")
    )
    session_worker_bundle_refs = _ordered_unique(
        ref
        for lineage in session_lineages
        for ref in _string_list(lineage.get("worker_evidence_bundle_refs"))
    )
    missing_session_worker_bundle_refs = [
        ref for ref in candidate_worker_bundle_refs if ref not in session_worker_bundle_refs
    ]
    if missing_session_worker_bundle_refs:
        issues.append(
            "runner session artifact does not record candidate worker evidence "
            "bundle refs: "
            + ", ".join(missing_session_worker_bundle_refs)
        )
    if not candidate_lineages:
        issues.append("runner session boundary has no candidate lineages")
    if not session_lineages:
        issues.append("runner session boundary has no validated runner session")
    if len(session_ids) > 1:
        issues.append(
            "runner session boundary spans multiple runner sessions: "
            + ", ".join(session_ids)
        )
    status = "verified" if not issues else "manual_gap"
    return {
        "schema_version": RUNNER_SESSION_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "server_truth_status": "not_server_truth",
        "runner_session_ids": session_ids,
        "runner_session_refs": session_refs,
        "run_ids": run_ids,
        "runner_ids": runner_ids,
        "candidate_artifact_refs": _ordered_unique(candidate_refs),
        "candidate_count": len(_ordered_unique(candidate_refs)),
        "session_count": len(session_ids),
        "candidate_worker_evidence_bundle_refs": candidate_worker_bundle_refs,
        "session_worker_evidence_bundle_refs": session_worker_bundle_refs,
        "missing_session_worker_evidence_bundle_refs": (
            missing_session_worker_bundle_refs
        ),
        "session_lineages": session_lineages,
        "issues": _ordered_unique(issues),
        "manual_gaps": (
            [] if status == "verified" else ["runner_session_boundary_not_verified"]
        ),
        "forbidden_claims": list(RUNNER_SESSION_FORBIDDEN_CLAIMS),
    }


def _runner_recovery_lineage_boundary(
    lineage: Mapping[str, Any],
    *,
    root: Path,
    graph_id: str | None,
    failed_lane_id: str | None,
) -> dict[str, Any]:
    runner_status = _text(lineage.get("status")) or "not_provided"
    proof_level = _text(lineage.get("proof_level")) or "manual_gap"
    artifact_ref = _text(lineage.get("artifact_ref"))
    filtered_graph_id = _text(lineage.get("filtered_graph_id"))
    source_refs = _string_list(lineage.get("source_refs"))
    target_refs = _string_list(lineage.get("target_refs"))
    forbidden_claims = _string_list(lineage.get("forbidden_claims"))
    manual_gaps = _string_list(lineage.get("manual_gaps"))
    issues: list[str] = []
    if _text(lineage.get("schema_version")) != "xmuse.local_runner_recovery_proof_lineage.v1":
        issues.append("runner recovery proof lineage schema is not supported")
    if runner_status not in {
        "target_lane_recovery_blocked",
        "target_lane_recovery_artifact_invalid",
    }:
        issues.append(
            "runner recovery proof lineage does not show target-lane recovery enforcement"
        )
    if proof_level != "local_runtime_proof":
        issues.append("runner recovery proof lineage proof level is not local_runtime_proof")
    if filtered_graph_id is None:
        issues.append("runner recovery proof lineage graph filter is missing")
    elif graph_id is None or filtered_graph_id != graph_id:
        issues.append("runner recovery proof lineage graph filter does not match closure")
    if artifact_ref is None:
        issues.append("runner recovery proof lineage artifact ref is missing")
    elif not _artifact_path(root, artifact_ref).is_file():
        issues.append("runner recovery proof lineage artifact ref is not readable")
    if not source_refs:
        issues.append("runner recovery proof lineage has no durable source refs")
    else:
        missing_source_refs = [
            source_ref
            for source_ref in source_refs
            if not _artifact_path(root, source_ref).is_file()
        ]
        if missing_source_refs:
            issues.append(
                "runner recovery proof lineage source refs are not readable: "
                + ", ".join(_ordered_unique(missing_source_refs))
            )
    if not target_refs:
        issues.append("runner recovery proof lineage has no target refs")
    elif failed_lane_id is None or f"lane:{failed_lane_id}" not in target_refs:
        issues.append("runner recovery proof lineage does not target the failed lane")
    required_forbidden = {
        "overnight_safe_recovery",
        "end_to_end_execution_review_closure",
        "worker_output_is_review_truth",
        "ready_to_merge",
        "pr_merged",
    }
    missing_forbidden = sorted(required_forbidden - set(forbidden_claims))
    if missing_forbidden:
        issues.append(
            "runner recovery proof lineage missing forbidden claims: "
            + ", ".join(missing_forbidden)
        )
    required_manual_gaps = {
        "review_truth_not_proven",
        "server_truth_not_proven",
        "overnight_safe_recovery_not_proven",
    }
    missing_manual_gaps = sorted(required_manual_gaps - set(manual_gaps))
    if missing_manual_gaps:
        issues.append(
            "runner recovery proof lineage missing manual gaps: "
            + ", ".join(missing_manual_gaps)
        )
    status = "verified" if not issues else "manual_gap"
    return {
        "schema_version": RUNNER_RECOVERY_LINEAGE_BOUNDARY_SCHEMA_VERSION,
        "status": status,
        "proof_level": "contract_proof" if status == "verified" else "manual_gap",
        "runner_recovery_status": runner_status,
        "runner_recovery_proof_level": proof_level,
        "artifact_ref": artifact_ref,
        "filtered_graph_id": filtered_graph_id,
        "source_ref_count": len(source_refs),
        "target_ref_count": len(target_refs),
        "issues": issues,
        "manual_gaps": (
            []
            if status == "verified"
            else ["runner_recovery_lineage_not_verified"]
        ),
        "forbidden_claims": [
            "overnight_safe_recovery",
            "end_to_end_execution_review_closure",
            "server_side_truth",
        ],
    }


def _runner_recovery_lineage(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {
            "status": "not_provided",
            "proof_level": "manual_gap",
            "manual_gaps": ["runner_recovery_proof_not_linked"],
            "forbidden_claims": [],
            "source_refs": [],
        }
    lineage = dict(value)
    if _text(lineage.get("schema_version")) != "xmuse.local_runner_recovery_proof_lineage.v1":
        return {
            "status": "manual_gap",
            "proof_level": "manual_gap",
            "artifact_ref": _text(lineage.get("artifact_ref")),
            "manual_gaps": _ordered_unique(
                [
                    *_string_list(lineage.get("manual_gaps")),
                    "runner_recovery_proof_lineage_schema_unsupported",
                ]
            ),
            "forbidden_claims": _string_list(lineage.get("forbidden_claims")),
            "source_refs": [],
        }
    return lineage


def _review_chain_proof_source_refs(
    root: Path,
    artifact: Mapping[str, Any],
    artifact_path: str | Path,
    *,
    current_handoff: Mapping[str, Any],
) -> list[str]:
    graph_id = _text(artifact.get("graph_id"))
    failed_lane_id = _text(artifact.get("failed_lane_id"))
    terminal_lane_id = _text(artifact.get("terminal_lane_id"))
    review_closure_ref = _text(artifact.get("review_closure_artifact"))
    release_handoff = _mapping(artifact.get("release_evidence_handoff"))
    runner_recovery = artifact.get("runner_recovery_proof_lineage")
    runner_recovery_refs: list[str] = []
    if isinstance(runner_recovery, Mapping):
        recovery_ref = _text(runner_recovery.get("artifact_ref"))
        if recovery_ref is not None:
            runner_recovery_refs.append(
                f"runner_recovery_proof_artifact:{recovery_ref}"
            )
    worker_evidence_bundle_refs = review_chain_proof_worker_evidence_bundle_refs(
        artifact
    )
    try:
        artifact_ref = str(
            Path(artifact_path).resolve(strict=False).relative_to(
                root.resolve(strict=False)
            )
        )
    except ValueError:
        artifact_ref = str(artifact_path)
    synthetic_ref = (
        f"god-room-review-chain-proof:{graph_id}:{failed_lane_id}:{terminal_lane_id}"
        if graph_id and failed_lane_id and terminal_lane_id
        else None
    )
    return _ordered_unique(
        [
            synthetic_ref,
            f"review_chain_proof_artifact:{artifact_ref}",
            review_closure_ref,
            f"lane:{failed_lane_id}" if failed_lane_id else None,
            f"lane:{terminal_lane_id}" if terminal_lane_id else None,
            *_string_list(current_handoff.get("source_refs")),
            *_string_list(release_handoff.get("review_closure_candidate_artifact_refs")),
            *runner_recovery_refs,
            *worker_evidence_bundle_refs,
        ]
    )


def _artifact_path(root: Path, artifact: str | Path) -> Path:
    path = Path(artifact)
    if path.is_absolute():
        return path
    return root / path


def _artifact_ref(root: Path, artifact: str | Path, path: Path) -> str:
    raw = str(artifact)
    try:
        return str(path.resolve(strict=False).relative_to(root.resolve(strict=False)))
    except ValueError:
        return raw


def _review_chain_current_handoff_evaluation(
    *,
    artifact_path: str | Path,
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    review_closure_ref = _text(payload.get("review_closure_artifact"))
    base = {
        "schema_version": "xmuse.review_closure_handoff_evaluation.v1",
        "status": "manual_gap",
        "handoff_gate_ready": False,
        "handoff_summary": (
            "GOD room review chain proof missing review_closure_artifact."
        ),
        "candidate_artifact_refs": [],
        "candidate_artifact_ref_count": 0,
        "source_refs": [],
        "source_ref_count": 0,
        "issues": ["GOD room review chain proof missing review_closure_artifact"],
        "manual_gaps": ["review_closure_handoff_not_ready"],
    }
    if review_closure_ref is None:
        return base
    root = _review_chain_root(artifact_path, payload)
    review_closure_path = _root_relative_artifact_path(root, review_closure_ref)
    if review_closure_path is None:
        return {
            **base,
            "handoff_summary": (
                "GOD room review chain proof review_closure_artifact escapes "
                "xmuse root."
            ),
            "issues": [
                "GOD room review chain proof review_closure_artifact escapes "
                "xmuse root"
            ],
        }
    review_closure, load_error = _load_json(review_closure_path)
    if not isinstance(review_closure, Mapping):
        return {
            **base,
            "handoff_summary": (
                load_error
                or "GOD room review closure artifact referenced by chain proof "
                "is missing"
            ),
            "issues": [
                load_error
                or "GOD room review closure artifact referenced by chain proof "
                "is missing"
            ],
        }
    return build_review_closure_handoff_evaluation(
        root=root,
        review_closure=review_closure,
    )


def _review_chain_root(path: str | Path, payload: Mapping[str, Any]) -> Path:
    root_ref = _text(payload.get("xmuse_root"))
    if root_ref is not None:
        return Path(root_ref)
    return Path(path).parent


def _root_relative_artifact_path(root: Path, artifact_ref: str) -> Path | None:
    raw_path = Path(artifact_ref)
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return None
    return candidate


def _load_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "GOD room review closure artifact is missing."
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"GOD room review closure artifact is invalid JSON: {exc}"
    if not isinstance(value, dict):
        return None, "GOD room review closure artifact must be an object."
    return value, None


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [text for item in value if (text := _text(item)) is not None]


def _mapping_list(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]


def _ordered_unique(values: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    iterable = values if isinstance(values, list | tuple | set) else list(values)
    for value in iterable:
        text = _text(value)
        if text is None or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int) and value >= 0:
        return value
    return 0


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


__all__ = [
    "GOD_ROOM_REVIEW_CHAIN_PROOF_SCHEMA_VERSION",
    "REVIEW_CHAIN_PROOF_L10_HANDOFF_EVALUATION_SCHEMA_VERSION",
    "build_review_chain_proof_l10_handoff_evaluation",
    "build_god_room_review_chain_proof",
    "capture_god_room_review_chain_proof",
    "review_chain_proof_bounded_session_gate",
    "review_chain_proof_worker_evidence_bundle_refs",
]
