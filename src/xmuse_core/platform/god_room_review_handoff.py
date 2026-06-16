from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from xmuse_core.platform.closure_objects import REQUIRED_FORBIDDEN_CLAIMS
from xmuse_core.platform.local_execution_candidate import (
    LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS,
    LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
    valid_local_execution_candidate_lineages,
)
from xmuse_core.platform.runner_session import load_runner_session_lineage

GOD_ROOM_REVIEW_CLOSURE_HANDOFF_SCHEMA_VERSION = (
    "xmuse.god_room_review_closure_handoff.v1"
)
REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION = (
    "xmuse.review_closure_handoff_evaluation.v1"
)
REVIEW_CHAIN_HANDOFF_SCHEMA_VERSION = "xmuse.god_room_lane_review_chain_proof.v1"
RELEASE_EVIDENCE_CANDIDATES_SCHEMA_VERSION = "xmuse.release_evidence_candidates.v1"
REQUIRED_GOD_ROOM_REVIEW_CLOSURE_FORBIDDEN_CLAIMS = frozenset(
    LOCAL_EXECUTION_CANDIDATE_FORBIDDEN_CLAIMS
)


def build_god_room_review_closure_handoff(
    *,
    root: str | Path,
    review_closure: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate review-closure handoff inputs shared by L9 and L10."""
    xmuse_root = Path(root)
    base = {
        "schema_version": GOD_ROOM_REVIEW_CLOSURE_HANDOFF_SCHEMA_VERSION,
        "gate_ready": False,
        "summary": None,
        "source_refs": [],
        "source_ref_count": 0,
        "candidate_artifact_refs": [],
        "candidate_artifact_ref_count": 0,
        "runner_session_refs": [],
        "runner_session_ref_count": 0,
    }
    schema_version = _text(review_closure.get("schema_version"))
    proof_level = _text(review_closure.get("proof_level"))
    server_truth_status = _text(review_closure.get("server_truth_status"))
    conversation_id = _text(review_closure.get("conversation_id"))
    forbidden_claims = set(_string_list(review_closure.get("forbidden_claims")))
    if schema_version != "xmuse.god_room_lane_review_closure.v1":
        return {
            **base,
            "summary": "GOD room review closure schema is unsupported.",
        }
    if proof_level != "contract_proof":
        return {
            **base,
            "summary": "GOD room review closure must remain contract_proof.",
        }
    if server_truth_status != "not_server_truth":
        return {
            **base,
            "summary": "GOD room review closure overclaims server truth.",
        }
    if conversation_id is None:
        return {
            **base,
            "summary": "GOD room review closure missing conversation scope.",
        }
    missing_forbidden = sorted(
        REQUIRED_GOD_ROOM_REVIEW_CLOSURE_FORBIDDEN_CLAIMS - forbidden_claims
    )
    if missing_forbidden:
        return {
            **base,
            "summary": (
                "GOD room review closure missing forbidden claims: "
                + ", ".join(missing_forbidden)
            ),
        }
    try:
        candidate_artifact_lineages = valid_local_execution_candidate_lineages(
            root=xmuse_root,
            refs=_string_list(review_closure.get("cited_candidate_refs")),
            lane_id=_text(review_closure.get("terminal_lane_id")),
            graph_id=_text(review_closure.get("graph_id")),
            conversation_id=conversation_id,
            required_producer=LOCAL_EXECUTION_CANDIDATE_PLATFORM_RUNNER_PRODUCER,
        )
    except ValueError as exc:
        return {
            **base,
            "summary": (
                "GOD room review closure has an invalid cited candidate "
                f"evidence artifact: {exc}"
            ),
        }
    candidate_artifact_refs = [
        str(lineage["artifact_ref"]) for lineage in candidate_artifact_lineages
    ]
    if not candidate_artifact_refs:
        return {
            **base,
            "summary": (
                "GOD room review closure has no valid cited candidate "
                "evidence artifact."
            ),
        }
    cited_candidate_artifact_refs = _ordered_unique(
        _string_list(review_closure.get("cited_candidate_artifact_refs"))
    )
    candidate_artifact_ref_set = set(candidate_artifact_refs)
    cited_candidate_artifact_ref_set = set(cited_candidate_artifact_refs)
    missing_cited_refs = [
        ref for ref in cited_candidate_artifact_refs if ref not in candidate_artifact_ref_set
    ]
    unexpected_candidate_refs = [
        ref for ref in candidate_artifact_refs if ref not in cited_candidate_artifact_ref_set
    ]
    if missing_cited_refs or unexpected_candidate_refs:
        details = []
        if missing_cited_refs:
            details.append(
                "unresolved cited_candidate_artifact_refs: "
                + ", ".join(missing_cited_refs)
            )
        if unexpected_candidate_refs:
            details.append(
                "resolved artifacts not declared by cited_candidate_artifact_refs: "
                + ", ".join(unexpected_candidate_refs)
            )
        return {
            **base,
            "summary": (
                "GOD room review closure candidate artifact refs do not match "
                "resolved local execution candidate lineage: "
                + "; ".join(details)
            ),
        }
    embedded_lineages = _mapping_list(
        review_closure.get("cited_candidate_artifact_lineage")
    )
    embedded_by_ref = _lineages_by_artifact_ref(embedded_lineages)
    resolved_by_ref = _lineages_by_artifact_ref(candidate_artifact_lineages)
    missing_embedded_refs = [
        ref for ref in candidate_artifact_refs if ref not in embedded_by_ref
    ]
    unexpected_embedded_refs = [
        ref for ref in embedded_by_ref if ref not in candidate_artifact_ref_set
    ]
    mismatched_embedded_refs = [
        ref
        for ref in candidate_artifact_refs
        if ref in embedded_by_ref and embedded_by_ref[ref] != resolved_by_ref[ref]
    ]
    if missing_embedded_refs or unexpected_embedded_refs or mismatched_embedded_refs:
        details = []
        if missing_embedded_refs:
            details.append(
                "missing cited_candidate_artifact_lineage refs: "
                + ", ".join(missing_embedded_refs)
            )
        if unexpected_embedded_refs:
            details.append(
                "unexpected cited_candidate_artifact_lineage refs: "
                + ", ".join(unexpected_embedded_refs)
            )
        if mismatched_embedded_refs:
            details.append(
                "mismatched cited_candidate_artifact_lineage refs: "
                + ", ".join(mismatched_embedded_refs)
            )
        return {
            **base,
            "summary": (
                "GOD room review closure candidate artifact lineage does not "
                "match resolved local execution candidate lineage: "
                + "; ".join(details)
            ),
        }
    runner_session_gate = _validate_runner_session_lineage(
        root=xmuse_root,
        graph_id=_text(review_closure.get("graph_id")),
        candidate_lineages=candidate_artifact_lineages,
    )
    if runner_session_gate["gate_ready"] is not True:
        return {
            **base,
            "summary": runner_session_gate["summary"],
            "candidate_artifact_refs": candidate_artifact_refs,
            "candidate_artifact_ref_count": len(candidate_artifact_refs),
            "runner_session_refs": runner_session_gate["runner_session_refs"],
            "runner_session_ref_count": runner_session_gate["runner_session_ref_count"],
        }
    source_refs = god_room_review_closure_source_refs(review_closure)
    return {
        **base,
        "gate_ready": True,
        "summary": "GOD room review closure can seed MemoryOS source refs.",
        "source_refs": source_refs,
        "source_ref_count": len(source_refs),
        "candidate_artifact_refs": candidate_artifact_refs,
        "candidate_artifact_ref_count": len(candidate_artifact_refs),
        "runner_session_refs": runner_session_gate["runner_session_refs"],
        "runner_session_ref_count": runner_session_gate["runner_session_ref_count"],
    }


def build_review_closure_handoff_evaluation(
    *,
    root: str | Path,
    review_closure: Mapping[str, Any],
) -> dict[str, Any]:
    """Build the shared L9->L10 review-closure handoff evaluation surface."""
    handoff = build_god_room_review_closure_handoff(
        root=root,
        review_closure=review_closure,
    )
    schema_version = _text(review_closure.get("schema_version"))
    proof_level = _text(review_closure.get("proof_level"))
    review_truth_status = _text(review_closure.get("review_truth_status"))
    execution_truth_status = _text(review_closure.get("execution_truth_status"))
    server_truth_status = _text(review_closure.get("server_truth_status"))
    forbidden_claims = _string_list(review_closure.get("forbidden_claims"))
    forbidden_claim_set = set(forbidden_claims)
    missing_forbidden_claims = sorted(
        REQUIRED_GOD_ROOM_REVIEW_CLOSURE_FORBIDDEN_CLAIMS - forbidden_claim_set
    )
    candidate_refs = _ordered_unique(_string_list(review_closure.get("candidate_refs")))
    cited_candidate_refs = _ordered_unique(
        _string_list(review_closure.get("cited_candidate_refs"))
    )
    source_event_lineage_refs = _source_event_lineage_refs(
        review_closure.get("source_event_lineage")
    )
    manual_gaps = _ordered_unique(_string_list(review_closure.get("manual_gaps")))
    issues = _evaluation_issues(
        schema_version=schema_version,
        proof_level=proof_level,
        review_truth_status=review_truth_status,
        execution_truth_status=execution_truth_status,
        server_truth_status=server_truth_status,
        missing_forbidden_claims=missing_forbidden_claims,
        handoff=handoff,
    )
    status = _evaluation_status(
        issues=issues,
        server_truth_status=server_truth_status,
    )
    if status != "ready":
        manual_gaps = _ordered_unique(
            [
                *manual_gaps,
                "review_closure_handoff_not_ready",
            ]
        )

    return {
        "schema_version": REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION,
        "graph_id": _text(review_closure.get("graph_id")),
        "lane_id": _text(review_closure.get("terminal_lane_id"))
        or _text(review_closure.get("failed_lane_id")),
        "status": status,
        "review_truth_status": review_truth_status,
        "execution_truth_status": execution_truth_status,
        "server_truth_status": server_truth_status or "not_server_truth",
        "candidate_refs": candidate_refs,
        "candidate_ref_count": len(candidate_refs),
        "cited_candidate_refs": cited_candidate_refs,
        "cited_candidate_ref_count": len(cited_candidate_refs),
        "candidate_artifact_refs": _string_list(
            handoff.get("candidate_artifact_refs")
        ),
        "candidate_artifact_ref_count": int(
            handoff.get("candidate_artifact_ref_count") or 0
        ),
        "runner_session_refs": _string_list(handoff.get("runner_session_refs")),
        "runner_session_ref_count": int(handoff.get("runner_session_ref_count") or 0),
        "source_refs": (
            _string_list(handoff.get("source_refs")) if status == "ready" else []
        ),
        "source_ref_count": int(handoff.get("source_ref_count") or 0)
        if status == "ready"
        else 0,
        "source_event_lineage_refs": source_event_lineage_refs,
        "source_event_lineage_ref_count": len(source_event_lineage_refs),
        "source_event_lineage_count": len(
            _mapping_list(review_closure.get("source_event_lineage"))
        ),
        "required_forbidden_claims_present": not missing_forbidden_claims,
        "missing_forbidden_claims": missing_forbidden_claims,
        "manual_gaps": manual_gaps,
        "forbidden_claims": forbidden_claims,
        "handoff_gate_ready": handoff.get("gate_ready") is True,
        "handoff_summary": _text(handoff.get("summary")),
        "issues": issues,
    }


def build_release_handoff_gate_evaluation_for_closure(
    *,
    release_handoff: Mapping[str, Any] | None,
    graph_id: str,
    lane_id: str,
    review_closure: Mapping[str, Any] | None = None,
    root: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate L9->L10 handoff readiness for closure-level reconciliation."""

    if release_handoff is None:
        return {
            "status": "false",
            "severity": "manual_gap",
            "reason": "release handoff artifact/report is missing",
            "source_refs": [],
            "target_refs": [],
            "is_blocking": False,
        }

    scope_mismatch = _release_handoff_scope_mismatch(
        release_handoff=release_handoff,
        review_closure=review_closure,
    )
    if scope_mismatch is not None:
        return {
            "status": "false",
            "severity": "manual_gap",
            "reason": scope_mismatch,
            "source_refs": [],
            "target_refs": [],
            "is_blocking": False,
        }

    schema_version = _text(release_handoff.get("schema_version"))
    if schema_version not in {
        REVIEW_CHAIN_HANDOFF_SCHEMA_VERSION,
        RELEASE_EVIDENCE_CANDIDATES_SCHEMA_VERSION,
        REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION,
    }:
        return {
            "status": "false",
            "severity": "blocked",
            "reason": "release handoff schema is unsupported",
            "source_refs": [],
            "target_refs": [],
            "is_blocking": True,
        }

    if schema_version == REVIEW_CHAIN_HANDOFF_SCHEMA_VERSION:
        if _text(release_handoff.get("status")) != "chain_ready":
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release handoff status is not chain_ready",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        if _text(release_handoff.get("proof_level")) != "contract_proof":
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release handoff proof level is not contract_proof",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        actual_graph_id = _text(release_handoff.get("graph_id"))
        if actual_graph_id is None:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release handoff graph_id is missing",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        if actual_graph_id != graph_id:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release handoff graph_id does not match current closure graph",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        terminal_lane = _text(release_handoff.get("terminal_lane_id"))
        if terminal_lane is None:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release handoff terminal_lane_id is missing",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        if terminal_lane != lane_id:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release handoff terminal lane id does not match current closure lane",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }

    if schema_version == REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION:
        if _text(release_handoff.get("status")) != "ready":
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "review-closure handoff status is not ready",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        actual_graph_id = _text(release_handoff.get("graph_id"))
        if actual_graph_id is None:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "review-closure handoff graph_id is missing",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        if actual_graph_id != graph_id:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "review-closure handoff graph_id does not match current closure graph",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        handoff_lane_id = _text(release_handoff.get("lane_id"))
        if handoff_lane_id is None:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "review-closure handoff lane_id is missing",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        if handoff_lane_id != lane_id:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "review-closure handoff lane_id does not match current closure lane",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }

    if schema_version == RELEASE_EVIDENCE_CANDIDATES_SCHEMA_VERSION:
        release_graph = _text(release_handoff.get("graph_id"))
        if release_graph is None:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release evidence candidate handoff graph_id is missing",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        if release_graph != graph_id:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": (
                    "release evidence candidate handoff graph_id does not match "
                    "current closure graph"
                ),
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        release_lane = _text(
            release_handoff.get("lane_id") or release_handoff.get("terminal_lane_id")
        )
        if release_lane is None:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": "release evidence candidate handoff lane_id is missing",
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }
        if release_lane != lane_id:
            return {
                "status": "false",
                "severity": "manual_gap",
                "reason": (
                    "release evidence candidate handoff lane_id does not match "
                    "current closure lane"
                ),
                "source_refs": [],
                "target_refs": [],
                "is_blocking": False,
            }

    if _text(release_handoff.get("server_truth_status")) not in {None, "not_server_truth"}:
        return {
            "status": "false",
            "severity": "blocked",
            "reason": "release handoff overclaims server truth",
            "source_refs": [],
            "target_refs": [],
            "is_blocking": True,
        }

    source_refs = _ordered_unique(
        (
            *_string_list(release_handoff.get("source_refs")),
            *_string_list(release_handoff.get("candidate_artifact_refs")),
            *_string_list(release_handoff.get("review_closure_candidate_artifact_refs")),
        )
    )
    if not source_refs:
        return {
            "status": "false",
            "severity": "manual_gap",
            "reason": "release handoff is missing source refs",
            "source_refs": [],
            "target_refs": [],
            "is_blocking": False,
        }
    unresolved_candidate_refs = _unresolved_candidate_artifact_refs(
        root=root,
        release_handoff=release_handoff,
    )
    if unresolved_candidate_refs:
        return {
            "status": "false",
            "severity": "manual_gap",
            "reason": (
                "release handoff candidate artifact refs are not resolvable: "
                + ", ".join(unresolved_candidate_refs)
            ),
            "source_refs": source_refs,
            "target_refs": _string_list(release_handoff.get("target_refs")),
            "is_blocking": False,
        }
    missing_forbidden_claims = [
        claim
        for claim in REQUIRED_FORBIDDEN_CLAIMS
        if claim not in set(_string_list(release_handoff.get("forbidden_claims")))
    ]
    if missing_forbidden_claims:
        return {
            "status": "false",
            "severity": "manual_gap",
            "reason": (
                "release handoff missing forbidden claims: "
                + ", ".join(missing_forbidden_claims)
            ),
            "source_refs": source_refs,
            "target_refs": _string_list(release_handoff.get("target_refs")),
            "is_blocking": False,
        }
    return {
        "status": "true",
        "severity": "ok",
        "reason": "release handoff has been evaluated without server-truth overclaim",
        "source_refs": source_refs,
        "target_refs": _string_list(release_handoff.get("target_refs")),
        "is_blocking": False,
    }


def _release_handoff_scope_mismatch(
    *,
    release_handoff: Mapping[str, Any],
    review_closure: Mapping[str, Any] | None,
) -> str | None:
    if review_closure is None:
        return None
    release_graph = _text(release_handoff.get("graph_id"))
    review_graph = _text(review_closure.get("graph_id"))
    if (
        release_graph is not None
        and review_graph is not None
        and release_graph != review_graph
    ):
        return "release handoff graph_id does not match review closure graph_id"
    release_lane = _text(
        release_handoff.get("lane_id")
        or release_handoff.get("terminal_lane_id")
        or release_handoff.get("failed_lane_id")
    )
    review_lane = _text(
        review_closure.get("terminal_lane_id")
        or review_closure.get("lane_id")
        or review_closure.get("failed_lane_id")
    )
    if release_lane is not None and review_lane is not None and release_lane != review_lane:
        return "release handoff lane scope does not match review closure lane scope"
    return None


def _unresolved_candidate_artifact_refs(
    *,
    root: str | Path | None,
    release_handoff: Mapping[str, Any],
) -> list[str]:
    if root is None:
        return []
    xmuse_root = Path(root)
    unresolved: list[str] = []
    for ref in _release_handoff_candidate_artifact_refs(release_handoff):
        path = _root_relative_artifact_path(xmuse_root, ref)
        if path is None or not path.is_file():
            unresolved.append(ref)
    return _ordered_unique(unresolved)


def _release_handoff_candidate_artifact_refs(
    release_handoff: Mapping[str, Any],
) -> list[str]:
    refs: list[str] = [
        *_string_list(release_handoff.get("candidate_artifact_refs")),
        *_string_list(release_handoff.get("review_closure_candidate_artifact_refs")),
    ]
    candidate_lineage = release_handoff.get("candidate_lineage")
    if isinstance(candidate_lineage, Mapping):
        refs.extend(_string_list(candidate_lineage.get("candidate_artifact_refs")))
    session = release_handoff.get("local_execution_review_session")
    if isinstance(session, Mapping):
        refs.extend(_string_list(session.get("candidate_artifact_refs")))
    release_evidence_handoff = release_handoff.get("release_evidence_handoff")
    if isinstance(release_evidence_handoff, Mapping):
        refs.extend(
            _string_list(
                release_evidence_handoff.get("review_closure_candidate_artifact_refs")
            )
        )
    return _ordered_unique(refs)


def load_and_evaluate_review_closure_handoff(
    *,
    root: str | Path,
    review_closure_ref: str,
    missing_summary: str = "GOD room review closure artifact is missing.",
    escape_summary: str = "GOD room review closure artifact escapes xmuse root.",
) -> dict[str, Any]:
    """Resolve a review-closure artifact ref and evaluate the shared handoff gate."""

    xmuse_root = Path(root)
    base = {
        "schema_version": REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION,
        "status": "manual_gap",
        "handoff_gate_ready": False,
        "handoff_summary": None,
        "candidate_artifact_refs": [],
        "candidate_artifact_ref_count": 0,
        "source_refs": [],
        "source_ref_count": 0,
        "issues": [],
        "manual_gaps": ["review_closure_handoff_not_ready"],
    }
    review_closure_path = _root_relative_artifact_path(
        root=xmuse_root,
        artifact_ref=review_closure_ref,
    )
    if review_closure_path is None:
        return {
            **base,
            "handoff_summary": escape_summary,
            "issues": [escape_summary.rstrip(".")],
        }
    review_closure, load_error = _load_review_closure_json(review_closure_path)
    if review_closure is None:
        summary = load_error or missing_summary
        if summary == "GOD room review closure artifact is missing.":
            summary = missing_summary
        return {
            **base,
            "handoff_summary": summary,
            "issues": [summary.rstrip(".")],
        }
    handoff_root_ref = _text(review_closure.get("xmuse_root"))
    handoff_root = Path(handoff_root_ref) if handoff_root_ref is not None else xmuse_root
    return build_review_closure_handoff_evaluation(
        root=handoff_root,
        review_closure=review_closure,
    )


def _evaluation_issues(
    *,
    schema_version: str | None,
    proof_level: str | None,
    review_truth_status: str | None,
    execution_truth_status: str | None,
    server_truth_status: str | None,
    missing_forbidden_claims: list[str],
    handoff: Mapping[str, Any],
) -> list[str]:
    issues: list[str] = []
    if schema_version != "xmuse.god_room_lane_review_closure.v1":
        issues.append("GOD room review closure schema is unsupported")
    if proof_level != "contract_proof":
        issues.append("GOD room review closure proof level must remain contract_proof")
    if review_truth_status != "independent_review_artifact":
        issues.append("GOD room review closure is missing independent review truth")
    if execution_truth_status != "candidate_reviewed":
        issues.append("GOD room review closure execution truth is not candidate_reviewed")
    if server_truth_status != "not_server_truth":
        issues.append("GOD room review closure overclaims server truth")
    if missing_forbidden_claims:
        issues.append(
            "GOD room review closure missing forbidden claims: "
            + ", ".join(missing_forbidden_claims)
        )
    if handoff.get("gate_ready") is not True:
        summary = _text(handoff.get("summary")) or "unknown"
        issues.append(f"GOD room review closure handoff is not gate-ready: {summary}")
    return issues


def _evaluation_status(
    *,
    issues: list[str],
    server_truth_status: str | None,
) -> str:
    if not issues:
        return "ready"
    if server_truth_status not in {None, "not_server_truth"}:
        return "blocked"
    return "manual_gap"


def god_room_review_closure_source_refs(
    review_closure: Mapping[str, Any],
) -> list[str]:
    terminal_verdict = review_closure.get("terminal_review_verdict")
    verdict_refs = (
        _string_list(terminal_verdict.get("evidence_refs"))
        if isinstance(terminal_verdict, Mapping)
        else []
    )
    runner_recovery = review_closure.get("runner_recovery_proof_lineage")
    runner_recovery_refs: list[str] = []
    if isinstance(runner_recovery, Mapping):
        artifact_ref = _text(runner_recovery.get("artifact_ref"))
        if artifact_ref is not None:
            runner_recovery_refs.append(
                f"runner_recovery_proof_artifact:{artifact_ref}"
            )
        runner_recovery_refs.extend(_string_list(runner_recovery.get("source_refs")))
    graph_id = _text(review_closure.get("graph_id"))
    failed_lane_id = _text(review_closure.get("failed_lane_id"))
    terminal_lane_id = _text(review_closure.get("terminal_lane_id"))
    synthetic_ref = (
        f"god-room-review-closure:{graph_id}:{failed_lane_id}:{terminal_lane_id}"
        if graph_id and failed_lane_id and terminal_lane_id
        else None
    )
    return _ordered_unique(
        [
            synthetic_ref,
            f"lane:{failed_lane_id}" if failed_lane_id else None,
            f"lane:{terminal_lane_id}" if terminal_lane_id else None,
            *_source_event_lineage_refs(review_closure.get("source_event_lineage")),
            _text(review_closure.get("patch_forward_artifact")),
            _text(review_closure.get("patch_lane_review_intake_artifact")),
            _text(review_closure.get("patch_lane_review_verdict_artifact")),
            *_string_list(review_closure.get("candidate_refs")),
            *_string_list(review_closure.get("cited_candidate_refs")),
            *verdict_refs,
            *runner_recovery_refs,
        ]
    )


def _source_event_lineage_refs(value: object) -> list[str]:
    refs: list[str] = []
    for item in _mapping_list(value):
        event_id = _text(item.get("event_id"))
        if event_id is not None:
            refs.append(f"god-room-event:{event_id}")
        provider_response_artifact_ref = _text(
            item.get("provider_response_artifact_ref")
        )
        if provider_response_artifact_ref is not None:
            refs.append(f"provider_response_artifact:{provider_response_artifact_ref}")
        refs.extend(_string_list(item.get("source_refs")))
    return _ordered_unique(refs)


def _text(value: object) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
        return cleaned or None
    return None


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item.strip() for item in value if isinstance(item, str) and item.strip()]


def _mapping_list(value: object) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _root_relative_artifact_path(root: Path, artifact_ref: str) -> Path | None:
    raw_path = Path(artifact_ref)
    candidate = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        candidate.resolve(strict=False).relative_to(root.resolve(strict=False))
    except ValueError:
        return None
    return candidate


def _load_review_closure_json(path: Path) -> tuple[dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, "GOD room review closure artifact is missing."
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return None, f"GOD room review closure artifact is invalid JSON: {exc}"
    if not isinstance(value, dict):
        return None, "GOD room review closure artifact must be an object."
    return value, None


def _lineages_by_artifact_ref(
    lineages: Sequence[Mapping[str, Any]],
) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for lineage in lineages:
        artifact_ref = _text(lineage.get("artifact_ref"))
        if artifact_ref is None:
            continue
        result[artifact_ref] = lineage
    return result


def _validate_runner_session_lineage(
    *,
    root: Path,
    graph_id: str | None,
    candidate_lineages: list[dict[str, Any]],
) -> dict[str, Any]:
    runner_session_refs: list[str] = []
    for lineage in candidate_lineages:
        artifact_ref = _text(lineage.get("artifact_ref"))
        session_ref = _text(lineage.get("runner_session_ref"))
        session_id = _text(lineage.get("runner_session_id"))
        run_id = _text(lineage.get("run_id"))
        runner_id = _text(lineage.get("worker_id"))
        missing = [
            field
            for field, value in (
                ("runner_session_ref", session_ref),
                ("runner_session_id", session_id),
                ("run_id", run_id),
                ("worker_id", runner_id),
            )
            if value is None
        ]
        if missing:
            return {
                "gate_ready": False,
                "summary": (
                    "GOD room review closure candidate missing runner session "
                    f"lineage for {artifact_ref or 'unknown candidate'}: "
                    + ", ".join(missing)
                ),
                "runner_session_refs": _ordered_unique(runner_session_refs),
                "runner_session_ref_count": len(_ordered_unique(runner_session_refs)),
            }
        assert artifact_ref is not None
        assert session_ref is not None
        assert session_id is not None
        assert run_id is not None
        assert runner_id is not None
        try:
            load_runner_session_lineage(
                root=root,
                artifact_ref=session_ref,
                session_id=session_id,
                run_id=run_id,
                runner_id=runner_id,
                candidate_artifact_ref=artifact_ref,
                graph_id=graph_id,
            )
        except FileNotFoundError:
            return {
                "gate_ready": False,
                "summary": (
                    "GOD room review closure runner session artifact is not "
                    f"readable: {session_ref}"
                ),
                "runner_session_refs": _ordered_unique(
                    [*runner_session_refs, session_ref]
                ),
                "runner_session_ref_count": len(
                    _ordered_unique([*runner_session_refs, session_ref])
                ),
            }
        except ValueError as exc:
            return {
                "gate_ready": False,
                "summary": (
                    "GOD room review closure runner session artifact is "
                    f"invalid: {exc}"
                ),
                "runner_session_refs": _ordered_unique(
                    [*runner_session_refs, session_ref]
                ),
                "runner_session_ref_count": len(
                    _ordered_unique([*runner_session_refs, session_ref])
                ),
            }
        runner_session_refs.append(session_ref)
    refs = _ordered_unique(runner_session_refs)
    return {
        "gate_ready": bool(refs),
        "summary": (
            "GOD room review closure runner session lineage verified."
            if refs
            else "GOD room review closure has no runner session lineage."
        ),
        "runner_session_refs": refs,
        "runner_session_ref_count": len(refs),
    }


def _ordered_unique(values: Sequence[str | None]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


__all__ = [
    "GOD_ROOM_REVIEW_CLOSURE_HANDOFF_SCHEMA_VERSION",
    "REVIEW_CLOSURE_HANDOFF_EVALUATION_SCHEMA_VERSION",
    "REQUIRED_GOD_ROOM_REVIEW_CLOSURE_FORBIDDEN_CLAIMS",
    "build_god_room_review_closure_handoff",
    "build_review_closure_handoff_evaluation",
    "build_release_handoff_gate_evaluation_for_closure",
    "god_room_review_closure_source_refs",
    "load_and_evaluate_review_closure_handoff",
]
